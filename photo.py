"""Module photo de GotoAndrivet, dans l'esprit d'un ASIAIR : caméra ZWO (ou simulée), vue en continu,
photos et séquences en FITS, aide à la mise au point (étoiles, HFR) et astrométrie locale
(solve-field) pour synchroniser la monture et centrer la cible.

Les positions astrométriques sont en J2000 ; la monture les reçoit précessées (Mount.sync, Mount.goto).
"""
import csv
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

import numpy as np

try:
    import cv2
except ImportError:          # mesure des étoiles indisponible sans OpenCV
    cv2 = None

ASI_LIBS = ("/usr/lib/x86_64-linux-gnu/libASICamera2.so", "/usr/lib/libASICamera2.so",
            "/usr/local/lib/libASICamera2.so", os.path.expanduser("~/ASIStudio/lib/libASICamera2.so"))


# ════════════════════════════════════════════════════════════════
#  CAMÉRAS
# ════════════════════════════════════════════════════════════════
_asi = None

def _zwo():
    """Module zwoasi initialisé avec la bibliothèque ZWO (une seule fois)."""
    global _asi
    if _asi is None:
        import zwoasi
        lib = next((p for p in ASI_LIBS if os.path.exists(p)), None)
        if lib is None:
            raise ImportError("libASICamera2.so introuvable : installez le SDK caméra ZWO")
        zwoasi.init(lib)
        _asi = zwoasi
    return _asi


def list_cameras():
    """Noms des caméras ZWO branchées (liste vide si le SDK manque)."""
    try:
        return list(_zwo().list_cameras())
    except Exception:
        return []


class ZwoCamera:
    """Caméra ZWO par zwoasi : images 16 bits, pose interruptible."""
    simulated = False

    def __init__(self, index=0):
        asi = _zwo()
        self.asi = asi
        self.cam = asi.Camera(index)
        p = self.cam.get_camera_property()
        self.name = p["Name"]
        self.max_w, self.max_h = p["MaxWidth"], p["MaxHeight"]
        self.pixel_um = float(p["PixelSize"])
        self.color = bool(p["IsColorCam"])
        self.cooled = bool(p.get("IsCoolerCam", False))
        self.bins = list(p.get("SupportedBins", [1])) or [1]
        controls = self.cam.get_controls()
        if "BandWidth" in controls:
            self.cam.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, controls["BandWidth"]["MinValue"])
        self.gain_max = controls.get("Gain", {}).get("MaxValue", 600)
        self.bin = 1

    def setup(self, gain, binning):
        self.bin = binning if binning in self.bins else 1
        self.cam.set_control_value(self.asi.ASI_GAIN, int(gain))
        self.cam.set_roi(bins=self.bin, image_type=self.asi.ASI_IMG_RAW16)

    def expose(self, seconds, abort):
        """Pose de `seconds` secondes ; renvoie une image uint16 (lignes, colonnes) ou None si interrompue."""
        asi = self.asi
        self.cam.set_control_value(asi.ASI_EXPOSURE, max(32, int(seconds * 1e6)))
        self.cam.start_exposure()
        time.sleep(min(seconds, 0.05))
        while True:
            st = self.cam.get_exposure_status()
            if st == asi.ASI_EXP_SUCCESS:
                break
            if st == asi.ASI_EXP_FAILED:
                raise RuntimeError("échec de la pose")
            if abort.is_set():
                self.cam.stop_exposure()
                return None
            time.sleep(0.05)
        w, h, _, _ = self.cam.get_roi_format()
        buf = self.cam.get_data_after_exposure()
        return np.frombuffer(buf, dtype=np.uint16).reshape(h, w).copy()

    def temperature(self):
        try:
            return self.cam.get_control_value(self.asi.ASI_TEMPERATURE)[0] / 10.0
        except Exception:
            return None

    def set_cooler(self, on, target_c):
        if not self.cooled:
            return
        self.cam.set_control_value(self.asi.ASI_TARGET_TEMP, int(target_c))
        self.cam.set_control_value(self.asi.ASI_COOLER_ON, 1 if on else 0)

    def close(self):
        try:
            self.cam.close()
        except Exception:
            pass


class SimCamera:
    """Caméra simulée : le ciel réel au pointage de la monture (étoiles Tycho-2 téléchargées au CDS,
    Bright Star Catalogue hors ligne), avec bruit de fond. Permet d'essayer le module sans matériel."""
    simulated = True
    name = "Caméra simulée"
    max_w, max_h, pixel_um = 1936, 1216, 5.86          # format d'une ASI174
    color, cooled, bins, gain_max = False, False, [1, 2, 3, 4], 500

    def __init__(self, pointing, focal_mm, bright_stars=(), rotation=lambda: 0.0):
        self.pointing = pointing            # fonction -> (ra_h, dec_d) J2000 vers lequel pointe la monture
        self.focal_mm = focal_mm            # fonction -> focale en mm
        self.rotation = rotation            # fonction -> angle du rotateur : haut de l'image, ° vers l'Est du Nord
        self.bright = bright_stars          # [(ra_h, dec_d, mag), ...] hors ligne
        self.bin, self.gain = 1, 100
        rng = np.random.default_rng()
        self._err0 = rng.uniform(0.15, 0.5, 2) * rng.choice((-1, 1), 2)    # erreur de pointage simulée (°)
        self._err_k = 0.12                                                 # partie qui varie sur le ciel (°)
        self._corr = np.zeros(2)                                           # part absorbée par la dernière synchro
        self.seeing_px = 1.6
        self._field = None                  # (ra_h, dec_d, rayon °, étoiles) du dernier champ téléchargé

    def setup(self, gain, binning):
        self.gain, self.bin = gain, binning

    def _stars(self, ra_h, dec_d, radius):
        """Étoiles du champ : un cercle deux fois plus grand est téléchargé une fois, puis réutilisé tant que
        le champ y tient (les petits déplacements du guidage ne refont pas de requête au CDS)."""
        f = self._field
        if f is None or angular_dist(ra_h, dec_d, f[0], f[1]) + radius > f[2]:
            big = 2 * radius
            stars = tycho2(ra_h, dec_d, big)
            if not stars:   # hors ligne : étoiles brillantes seulement
                stars = [s for s in self.bright if angular_dist(ra_h, dec_d, s[0], s[1]) < big]
            f = self._field = (ra_h, dec_d, big, stars)
        return f[3]

    def expose(self, seconds, abort):
        for _ in range(int(min(seconds, 2.0) / 0.05)):     # la simulation ne fait pas attendre plus de 2 s
            if abort.is_set():
                return None
            time.sleep(0.05)
        ra, dec = self.pointing()
        e = self.error(ra, dec)
        ra += e[0] / 15.0
        dec += e[1]
        w, h = self.max_w // self.bin, self.max_h // self.bin
        scale = 206.265 * self.pixel_um * self.bin / self.focal_mm() / 3600.0        # degrés par pixel
        radius = math.hypot(w, h) * scale / 2 * 1.05
        rng = np.random.default_rng()
        img = rng.normal(400 + 20 * seconds, 12 + 2 * math.sqrt(seconds), (h, w))
        yy, xx = np.mgrid[-6:7, -6:7]
        t = math.radians(self.rotation())
        for sra, sdec, mag in self._stars(ra, dec, radius):
            x, y = gnomonic(ra, dec, sra, sdec)
            # haut de l'image : (sin t, cos t) en (Est, Nord) ; droite : (-cos t, sin t), sans miroir
            px = w / 2 + (-x * math.cos(t) + y * math.sin(t)) / scale
            py = h / 2 - (x * math.sin(t) + y * math.cos(t)) / scale
            if not (6 <= px < w - 7 and 6 <= py < h - 7):
                continue
            flux = 2.0e5 * seconds * (self.gain / 100.0 + 0.2) * 10 ** (-0.4 * (mag - 6.0))
            ix, iy = int(px), int(py)
            s = self.seeing_px / self.bin ** 0.5
            psf = np.exp(-((xx - (px - ix)) ** 2 + (yy - (py - iy)) ** 2) / (2 * s * s))
            img[iy - 6:iy + 7, ix - 6:ix + 7] += flux * psf / psf.sum()
        img = rng.poisson(np.clip(img, 0, None)).astype(np.float64)
        return np.clip(img, 0, 65535).astype(np.uint16)

    def error(self, ra_h, dec_d):
        """Erreur de pointage simulée (° en AD, ° en Déc) : une constante et une partie qui varie avec la
        position, moins ce que la dernière synchronisation a absorbé (comme la monture simulée, à un point)."""
        a = math.radians(ra_h * 15)
        return self._err0 + self._err_k * np.array((math.cos(a), math.sin(a) + math.sin(math.radians(dec_d)))) - self._corr

    def synced(self):
        """La monture vient d'être synchronisée sur l'image résolue : plus d'erreur à cet endroit."""
        self._corr = self._corr + self.error(*self.pointing())

    def temperature(self):
        return None

    def set_cooler(self, on, target_c):
        pass

    def close(self):
        pass


def tycho2(ra_h, dec_d, radius_deg, mag_max=11.5):
    """Étoiles Tycho-2 (CDS VizieR I/259) d'un champ : [(ra_h, dec_d, mag), ...], vide sans réseau."""
    q = (f'SELECT RAmdeg, DEmdeg, VTmag FROM "I/259/tyc2" WHERE VTmag < {mag_max} AND '
         f"1=CONTAINS(POINT('ICRS', RAmdeg, DEmdeg), CIRCLE('ICRS', {ra_h * 15:.5f}, {dec_d:.5f}, {radius_deg:.4f}))")
    data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
                                                           data=data), timeout=20) as r:
            rows = list(csv.DictReader(io.StringIO(r.read().decode())))
        return [(float(x["RAmdeg"]) / 15, float(x["DEmdeg"]), float(x["VTmag"])) for x in rows
                if x["RAmdeg"] and x["DEmdeg"] and x["VTmag"]]
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════
#  GÉOMÉTRIE
# ════════════════════════════════════════════════════════════════
def angular_dist(ra1_h, dec1_d, ra2_h, dec2_d):
    a1, d1, a2, d2 = math.radians(ra1_h * 15), math.radians(dec1_d), math.radians(ra2_h * 15), math.radians(dec2_d)
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def gnomonic(ra0_h, dec0_d, ra_h, dec_d):
    """Projection gnomonique autour de (ra0, dec0) : (x vers l'Est, y vers le Nord) en degrés."""
    a0, d0, a, d = math.radians(ra0_h * 15), math.radians(dec0_d), math.radians(ra_h * 15), math.radians(dec_d)
    c = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(a - a0)
    x = math.cos(d) * math.sin(a - a0) / c
    y = (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(a - a0)) / c
    return math.degrees(x), math.degrees(y)


def field_of_view(pixel_um, binning, width_px, height_px, focal_mm):
    """(échelle en ″/pixel, largeur en °, hauteur en °)."""
    scale = 206.265 * pixel_um * binning / focal_mm
    return scale, width_px * scale / 3600, height_px * scale / 3600


# ════════════════════════════════════════════════════════════════
#  IMAGE : FITS, ÉTIREMENT, ÉTOILES
# ════════════════════════════════════════════════════════════════
def write_fits(path, data, header):
    """Écrit une image uint16 en FITS (BITPIX 16, BZERO 32768), avec les mots-clés de `header`."""
    cards = [("SIMPLE", True, ""), ("BITPIX", 16, ""), ("NAXIS", 2, ""), ("NAXIS1", data.shape[1], ""),
             ("NAXIS2", data.shape[0], ""), ("BZERO", 32768, ""), ("BSCALE", 1, "")]
    cards += [(k[:8].upper(), v, c) for k, (v, c) in header.items()]
    out = []
    for k, v, c in cards:
        if isinstance(v, bool):
            val = f"{'T' if v else 'F':>20}"
        elif isinstance(v, (int, np.integer)):
            val = f"{int(v):>20}"
        elif isinstance(v, float):
            val = f"{v:>20.10G}"
        else:
            val = "'" + str(v).replace("'", "''")[:66].ljust(8) + "'"
        card = f"{k:<8}= {val}" + (f" / {c}" if c else "")
        out.append(card[:80].ljust(80))
    out.append("END".ljust(80))
    hdr = "".join(out).encode("ascii", "replace")
    hdr += b" " * (-len(hdr) % 2880)
    body = (data.astype(np.int32) - 32768).astype(">i2").tobytes()
    body += b"\0" * (-len(body) % 2880)
    with open(path, "wb") as f:
        f.write(hdr + body)


def autostretch(data, max_side=1400):
    """Étirement automatique façon « STF » (fond à 25 %), réduit pour l'affichage : uint8 (lignes, colonnes)."""
    step = max(1, int(math.ceil(max(data.shape) / max_side)))
    d = data[::step, ::step].astype(np.float32)
    med = float(np.median(d)); mad = float(np.median(np.abs(d - med))) * 1.4826 or 1.0
    lo = max(0.0, med - 2.8 * mad); hi = float(d.max()) or 1.0
    x = np.clip((d - lo) / max(hi - lo, 1.0), 0, 1)
    m = (med - lo) / max(hi - lo, 1.0)
    target = 0.25
    mb = (target - 1) * m / ((2 * target - 1) * m - target) if 0 < m < 1 else 0.5   # tons moyens : fond amené à 25 %
    y = (mb - 1) * x / ((2 * mb - 1) * x - mb)
    return (np.clip(y, 0, 1) * 255).astype(np.uint8)


def star_metrics(data, max_stars=60):
    """(nombre d'étoiles détectées, HFR médian en pixels) ; (None, None) sans OpenCV."""
    if cv2 is None:
        return None, None
    d = data.astype(np.float32)
    med = float(np.median(d)); mad = float(np.median(np.abs(d - med))) * 1.4826 or 1.0
    mask = (cv2.GaussianBlur(d, (0, 0), 1.2) > med + 6 * mad).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    blobs = [(stats[i, cv2.CC_STAT_AREA], cent[i]) for i in range(1, n) if 4 <= stats[i, cv2.CC_STAT_AREA] <= 2500]
    hfrs = []
    for area, (cx, cy) in sorted(blobs, key=lambda b: -b[0])[:max_stars]:
        r = int(max(6, math.sqrt(area) * 2))
        x0, y0 = int(cx) - r, int(cy) - r
        if x0 < 0 or y0 < 0 or x0 + 2 * r >= d.shape[1] or y0 + 2 * r >= d.shape[0]:
            continue
        win = d[y0:y0 + 2 * r + 1, x0:x0 + 2 * r + 1] - med
        win[win < 0] = 0
        yy, xx = np.mgrid[0:2 * r + 1, 0:2 * r + 1]
        tot = win.sum()
        if tot <= 0:
            continue
        sx, sy = (win * xx).sum() / tot, (win * yy).sum() / tot
        hfrs.append(float((win * np.hypot(xx - sx, yy - sy)).sum() / tot))
    return len(blobs), (float(np.median(hfrs)) if hfrs else None)


# ════════════════════════════════════════════════════════════════
#  ASTROMÉTRIE (solve-field d'astrometry.net, index locaux)
# ════════════════════════════════════════════════════════════════
APP_INDEX_DIR = Path(__file__).resolve().parent / "astrometry_data"     # index téléchargés par le configurateur


def solver_available():
    return shutil.which("solve-field") is not None


def _solver_config(work):
    """Fichier de configuration de solve-field : celui du système, plus les index du dossier de l'application."""
    lines = []
    for sys_cfg in ("/etc/astrometry.cfg", "/usr/local/etc/astrometry.cfg", "/usr/local/astrometry/etc/astrometry.cfg"):
        if os.path.exists(sys_cfg):
            lines = [ln.strip() for ln in Path(sys_cfg).read_text(errors="replace").splitlines()]
            break
    if not any(ln.startswith("add_path") for ln in lines):
        lines += ["add_path /usr/share/astrometry", "add_path /usr/local/share/astrometry"]
    if not any(ln == "autoindex" for ln in lines):
        lines.append("autoindex")
    if APP_INDEX_DIR.is_dir() and any(APP_INDEX_DIR.glob("index-*.fits")):
        lines.append(f"add_path {APP_INDEX_DIR}")
    path = os.path.join(work, "astrometry.cfg")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def plate_solve(fits_path, scale_arcsec=None, hint=None, radius_deg=10.0, timeout=90, abort=None):
    """Résout une image FITS. hint : (ra_h, dec_d) J2000 du pointage. Renvoie
    {ra_h, dec_d, rotation, scale, width_deg, height_deg} en J2000, ou lève RuntimeError."""
    if not solver_available():
        raise RuntimeError("solve-field introuvable : installez astrometry.net et ses fichiers d'index")
    work = tempfile.mkdtemp(prefix="gotoandrivet_solve_")
    cmd = ["solve-field", str(fits_path), "--config", _solver_config(work), "--dir", work, "--overwrite", "--no-plots", "--no-remove-lines",
           "--downsample", "2", "--cpulimit", str(timeout), "--new-fits", "none", "--index-xyls", "none",
           "--rdls", "none", "--corr", "none", "--match", "none", "--solved", "none", "--temp-axy"]
    if scale_arcsec:
        cmd += ["--scale-units", "arcsecperpix", "--scale-low", f"{scale_arcsec * 0.85:.3f}",
                "--scale-high", f"{scale_arcsec * 1.15:.3f}"]
    if hint:
        cmd += ["--ra", f"{hint[0] * 15:.5f}", "--dec", f"{hint[1]:.5f}", "--radius", f"{radius_deg:.2f}"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        t0 = time.time()
        while proc.poll() is None:
            if (abort is not None and abort.is_set()) or time.time() - t0 > timeout + 30:
                proc.kill()
                raise RuntimeError("astrométrie interrompue")
            time.sleep(0.2)
        out = proc.stdout.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    m = re.search(r"Field center: \(RA,Dec\) = \(\s*([-0-9.]+),\s*([-0-9.]+)\s*\) deg", out)
    if not m:
        raise RuntimeError("image non résolue (trop peu d'étoiles, mauvaise focale, ou index manquants)")
    res = {"ra_h": float(m.group(1)) / 15, "dec_d": float(m.group(2))}
    r = re.search(r"Field rotation angle: up is ([-0-9.]+) degrees (E|W) of N", out)
    rot = (float(r.group(1)) * (1 if r.group(2) == "E" else -1)) if r else 180.0
    # solve-field lit le FITS de bas en haut, l'image s'affiche ligne 0 en haut : le haut de l'écran est
    # son bas (+180°) et la parité s'inverse. rotation : haut de l'image affichée, en degrés vers l'Est du Nord.
    res["rotation"] = (rot + 360) % 360 - 180
    p = re.search(r"Field parity: (pos|neg)", out)
    res["mirrored"] = bool(p) and p.group(1) == "pos"
    s = re.search(r"pixel scale ([0-9.]+) arcsec/pix", out)
    res["scale"] = float(s.group(1)) if s else scale_arcsec
    f = re.search(r"Field size: ([0-9.]+) x ([0-9.]+) (degrees|arcminutes|arcseconds)", out)
    if f:
        k = {"degrees": 1, "arcminutes": 1 / 60, "arcseconds": 1 / 3600}[f.group(3)]
        res["width_deg"], res["height_deg"] = float(f.group(1)) * k, float(f.group(2)) * k
    return res


# ════════════════════════════════════════════════════════════════
#  FENÊTRE DU MODULE PHOTO
# ════════════════════════════════════════════════════════════════

TEXTS = {
    "fr": {
        "title": "GotoAndrivet — Caméra", "camera": "Caméra", "connect": "Connecter", "disconnect": "Déconnecter",
        "sim": "Caméra simulée", "color": "couleur", "mono": "mono", "cooler": "Refroidir à (°C) :",
        "focal": "Focale (mm) :", "scale": "{sc:.2f}″/px · champ {w:.2f}° × {h:.2f}°",
        "tab_capture": " Prise de vue ", "tab_astro": " Astrométrie ", "tab_model": " Modèle ",
        "capture": "Prise de vue", "exposure": "Pose (s) :", "gain": "Gain :", "binning": "Binning :",
        "live": "▶ Vue en continu", "stop": "■ Arrêter", "shot": "Photo", "sequence": "Séquence :", "frames": "images",
        "start_seq": "Lancer", "folder": "Dossier :", "choose": "Choisir…",
        "dither": "Dithering toutes les", "dither_by": "décalage de", "dither_px": "px de guidage", "dithering": "Dithering et stabilisation du guidage…",
        "dither_fail": "Guidage non stabilisé après le dithering : la séquence continue.",
        "focus": "Mise au point", "stars": "Étoiles", "hfr": "HFR (px)", "focuser_off": "Focuseur non connecté (onglet Focuseur)",
        "astrometry": "Astrométrie", "solve": "Résoudre", "solve_sync": "Résoudre et synchroniser",
        "center": "Centrer la cible", "tolerance": "Tolérance (′) :",
        "auto": "Après chaque GoTo : vérifier par astrométrie et corriger si l'écart dépasse la tolérance",
        "framing": "Angle de cadrage (dérotateur)", "angle": "Angle voulu (°) :", "rotate": "Tourner",
        "framing_note": "Angle du haut de l'image vers l'Est depuis le Nord. En équatoriale, le dérotateur sert de rotateur.",
        "model": "Modèle de pointage", "points": "Points :", "alt_min": "Hauteur min (°) :",
        "build": "Construire le modèle", "clear": "Effacer le modèle",
        "model_note": "Chaque synchronisation (modèle, centrage, correction après GoTo) ajoute un point au modèle "
                      "du firmware Teensy (50 points au plus, perdus à l'extinction). Le Mega ne garde que la dernière.",
        "model_empty": "Aucun point synchronisé dans cette session.",
        "model_sum": "{n} points synchronisés · écart avant synchro : moyen {m:.1f}′, max {x:.1f}′",
        "model_pt": "Point {i}/{n} : Az {az:.0f}° Alt {alt:.0f}°…", "model_done": "Modèle construit : {ok}/{n} points.",
        "model_fail": "Point {i} : {e}", "model_cleared": "Modèle effacé ({r}).",
        "ready": "Prêt.", "exposing": "Pose de {s} s…", "saved": "Enregistré : {f}", "solving": "Astrométrie…",
        "solved": "Résolu : AD {ra}  Déc {dec}  (J2000)  ·  rotation {rot:+.1f}°{mir}  ·  {sc:.2f}″/px",
        "mirrored": " (miroir)", "synced": "Monture synchronisée sur l'image.", "need_mount": "La monture n'est pas connectée.",
        "no_target": "Faites d'abord un GoTo vers la cible.", "center_try": "Centrage, essai {i} : écart {d:.1f}′",
        "centered": "Cible centrée : écart {d:.1f}′.", "center_fail": "Cible non centrée après {n} essais (écart {d:.1f}′).",
        "auto_start": "GoTo terminé : vérification par astrométrie…",
        "rot_try": "Cadrage, essai {i} : rotation {r:+.1f}°, écart {d:+.1f}°", "rot_done": "Cadrage atteint : rotation {r:+.1f}°.",
        "rot_fail": "Cadrage non atteint (écart {d:+.1f}°).", "need_derot": "Connectez d'abord le dérotateur (onglet Dérotateur).",
        "no_solver": "solve-field (astrometry.net) n'est pas installé.", "busy": "Une opération est déjà en cours.",
        "need_cam": "Connectez d'abord une caméra.", "seq_done": "Séquence terminée : {n} images.",
        "error": "Erreur : {e}", "stopped": "Arrêté.", "temp": "Capteur : {t}",
        "sim_offset": "Caméra simulée : erreur de pointage simulée de {d:.0f}′.",
        "goto_refused": "GoTo refusé par la monture : {r}",

        "tab_polar": " Mise en station ",
        "pa_board": "Carte de mise en station (moteurs des vis)", "pa_noboard": "Pas de carte : réglage des vis à la main.",
        "pa_board_st": "{v} · 12 V : {vm} · azimut {pa:+d} pas · hauteur {pl:+d} pas{fc}",
        "pa_fc": " · fin de course : {l}", "pa_vm_off": "absent",
        "pa_measure": "Mesure", "pa_angle": "Rotation d'AD (°) :", "pa_tol": "Tolérance (′) :",
        "pa_refr": "Viser le pôle relevé par la réfraction",
        "pa_axis": "1. Mesurer l'axe (3 images)", "pa_refresh": "Mesurer l'erreur",
        "pa_auto": "2. Correction automatique", "pa_calib": "Recalibrer",
        "pa_manual": "Moteurs à la main", "pa_steps": "Pas :", "pa_calib_st": "Calibration : {a} pas/′ azimut, {l} pas/′ hauteur",
        "pa_calib_none": "Moteurs pas encore calibrés (fait au début de la correction automatique).",
        "pa_note": "Visez vers le méridien, entre 30° et 70° de hauteur. Seul l'axe d'AD tourne entre les images.",
        "pa_need_eq": "La mise en station concerne les montures équatoriales (réglage Type de monture).",
        "pa_turn": "Monture non connectée : tournez l'axe d'AD d'environ {d:.0f}° à la main, puis cliquez OK.",
        "pa_need_axis": "Mesurez d'abord l'axe (3 images).", "pa_need_board": "Connectez d'abord la carte de mise en station.",
        "pa_done": "Erreur de mise en station : {e:.1f}′",
    },
    "en": {
        "title": "GotoAndrivet — Camera", "camera": "Camera", "connect": "Connect", "disconnect": "Disconnect",
        "sim": "Simulated camera", "color": "color", "mono": "mono", "cooler": "Cool to (°C):",
        "focal": "Focal length (mm):", "scale": "{sc:.2f}″/px · field {w:.2f}° × {h:.2f}°",
        "tab_capture": " Capture ", "tab_astro": " Astrometry ", "tab_model": " Model ",
        "capture": "Capture", "exposure": "Exposure (s):", "gain": "Gain:", "binning": "Binning:",
        "live": "▶ Live view", "stop": "■ Stop", "shot": "Shot", "sequence": "Sequence:", "frames": "frames",
        "start_seq": "Start", "folder": "Folder:", "choose": "Choose…",
        "dither": "Dither every", "dither_by": "offset of", "dither_px": "guide px", "dithering": "Dithering and guiding settling…",
        "dither_fail": "Guiding not settled after dithering: the sequence goes on.",
        "focus": "Focus", "stars": "Stars", "hfr": "HFR (px)", "focuser_off": "Focuser not connected (Focuser tab)",
        "astrometry": "Astrometry", "solve": "Solve", "solve_sync": "Solve and sync",
        "center": "Center target", "tolerance": "Tolerance (′):",
        "auto": "After each GoTo: check by plate solving and correct if the offset exceeds the tolerance",
        "framing": "Framing angle (derotator)", "angle": "Wanted angle (°):", "rotate": "Rotate",
        "framing_note": "Angle of the image top, East of North. On an equatorial mount the derotator acts as a rotator.",
        "model": "Pointing model", "points": "Points:", "alt_min": "Min altitude (°):",
        "build": "Build the model", "clear": "Clear the model",
        "model_note": "Every sync (model, centering, correction after GoTo) adds a point to the Teensy firmware "
                      "model (50 points at most, lost at power-off). The Mega keeps only the last one.",
        "model_empty": "No point synced in this session.",
        "model_sum": "{n} synced points · offset before sync: mean {m:.1f}′, max {x:.1f}′",
        "model_pt": "Point {i}/{n}: Az {az:.0f}° Alt {alt:.0f}°…", "model_done": "Model built: {ok}/{n} points.",
        "model_fail": "Point {i}: {e}", "model_cleared": "Model cleared ({r}).",
        "ready": "Ready.", "exposing": "Exposing {s} s…", "saved": "Saved: {f}", "solving": "Plate solving…",
        "solved": "Solved: RA {ra}  Dec {dec}  (J2000)  ·  rotation {rot:+.1f}°{mir}  ·  {sc:.2f}″/px",
        "mirrored": " (mirrored)", "synced": "Mount synced on the image.", "need_mount": "The mount is not connected.",
        "no_target": "GoTo the target first.", "center_try": "Centering, try {i}: offset {d:.1f}′",
        "centered": "Target centered: offset {d:.1f}′.", "center_fail": "Target not centered after {n} tries (offset {d:.1f}′).",
        "auto_start": "GoTo done: checking by plate solving…",
        "rot_try": "Framing, try {i}: rotation {r:+.1f}°, off by {d:+.1f}°", "rot_done": "Framing reached: rotation {r:+.1f}°.",
        "rot_fail": "Framing not reached (off by {d:+.1f}°).", "need_derot": "Connect the derotator first (Derotator tab).",
        "no_solver": "solve-field (astrometry.net) is not installed.", "busy": "An operation is already running.",
        "need_cam": "Connect a camera first.", "seq_done": "Sequence done: {n} frames.",
        "error": "Error: {e}", "stopped": "Stopped.", "temp": "Sensor: {t}",
        "sim_offset": "Simulated camera: simulated pointing error of {d:.0f}′.",
        "goto_refused": "GoTo refused by the mount: {r}",

        "tab_polar": " Polar align ",
        "pa_board": "Polar alignment board (screw motors)", "pa_noboard": "No board: turn the screws by hand.",
        "pa_board_st": "{v} · 12 V: {vm} · azimuth {pa:+d} steps · altitude {pl:+d} steps{fc}",
        "pa_fc": " · limit switch: {l}", "pa_vm_off": "missing",
        "pa_measure": "Measure", "pa_angle": "RA rotation (°):", "pa_tol": "Tolerance (′):",
        "pa_refr": "Aim at the refraction-raised pole",
        "pa_axis": "1. Measure the axis (3 frames)", "pa_refresh": "Measure the error",
        "pa_auto": "2. Automatic correction", "pa_calib": "Recalibrate",
        "pa_manual": "Motors by hand", "pa_steps": "Steps:", "pa_calib_st": "Calibration: {a} steps/′ azimuth, {l} steps/′ altitude",
        "pa_calib_none": "Motors not calibrated yet (done at the start of the automatic correction).",
        "pa_note": "Aim toward the meridian, 30° to 70° high. Only the RA axis turns between the frames.",
        "pa_need_eq": "Polar alignment is for equatorial mounts (Mount type setting).",
        "pa_turn": "Mount not connected: turn the RA axis by about {d:.0f}° by hand, then click OK.",
        "pa_need_axis": "Measure the axis first (3 frames).", "pa_need_board": "Connect the polar alignment board first.",
        "pa_done": "Polar alignment error: {e:.1f}′",
    },
}


def _fmt_ra(h):
    h %= 24; m = (h - int(h)) * 60; return f"{int(h):02d}h{int(m):02d}m{(m - int(m)) * 60:04.1f}s"


def _fmt_dec(d):
    s = "-" if d < 0 else "+"; d = abs(d); m = (d - int(d)) * 60
    return f"{s}{int(d):02d}°{int(m):02d}′{(m - int(m)) * 60:02.0f}″"


def model_points(n, alt_min, alt_max=72.0):
    """n positions (az, alt) réparties sur 2 ou 3 couronnes de hauteur, plus serrées en bas,
    parcourues en serpentin pour limiter les retournements."""
    k = 2 if n < 8 else 3
    alts = [alt_min + (alt_max - alt_min) * i / (k - 1) for i in range(k)]
    w = [math.cos(math.radians(a)) for a in alts]
    counts = [max(1, round(n * x / sum(w))) for x in w]
    counts[0] += n - sum(counts)
    pts = []
    for i, (alt, m) in enumerate(zip(alts, counts)):
        azs = [(j + 0.5 * (i % 2)) * 360.0 / m + 20.0 for j in range(m)]
        pts += [(az % 360, alt) for az in (azs if i % 2 == 0 else azs[::-1])]
    return pts


class PhotoWindow(tk.Toplevel):
    """Fenêtre du module photo. `app` fournit cfg, focuser, derot et les méthodes photo_* de la carte du ciel."""

    def __init__(self, app, colors):
        super().__init__(app)
        self.app, self.cfg, self.c = app, app.cfg, colors
        self.t = TEXTS.get(self.cfg.get("language", "fr"), TEXTS["fr"])
        self.title(self.t["title"]); self.geometry("1300x840"); self.minsize(1050, 700)
        self.configure(bg=colors["BG"])
        self.camera = None; self.image = None; self._tkimg = None
        self.abort = threading.Event(); self.busy = False
        self.solution = None; self.p = {}
        self.synced_pts = []          # [(az, alt, écart en ′ avant la synchro)] de cette session
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._refresh_cameras()
        self._update_scale()
        self._model_list()

    # ── Construction ──────────────────────────────────────────
    def _frame(self, parent, title):
        f = ttk.LabelFrame(parent, text=f" {title} ", padding=4); f.pack(fill=tk.X, padx=6, pady=4); return f

    def _row(self, parent):
        r = tk.Frame(parent, bg=self.c["BG2"]); r.pack(fill=tk.X, pady=2); return r

    def _lbl(self, parent, text, width=12):
        l = tk.Label(parent, text=text, bg=self.c["BG2"], fg=self.c["DIM"], font=self.c["FS"], width=width, anchor="w")
        l.pack(side=tk.LEFT); return l

    def _note(self, parent, text="", fg=None):
        l = tk.Label(parent, text=text, bg=self.c["BG2"], fg=fg or self.c["DIM"], font=self.c["FS"], justify="left",
                     anchor="w", wraplength=330)
        l.pack(fill=tk.X); return l

    def _spin(self, parent, var, lo, hi, inc, width=7):
        sp = ttk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=var, width=width, font=self.c["FS"])
        sp.pack(side=tk.LEFT, padx=4); return sp

    def _build(self):
        c, t = self.c, self.t
        left = tk.Frame(self, bg=c["BG2"], width=445); left.pack(side=tk.LEFT, fill=tk.Y); left.pack_propagate(False)
        right = tk.Frame(self, bg=c["BG"]); right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Caméra et optique, toujours visibles
        f = self._frame(left, t["camera"])
        r = self._row(f)
        self.v_cam = tk.StringVar()
        self.cb_cam = ttk.Combobox(r, textvariable=self.v_cam, state="readonly", width=21, font=c["FS"])
        self.cb_cam.pack(side=tk.LEFT, padx=2)
        ttk.Button(r, text="↺", width=3, command=self._refresh_cameras).pack(side=tk.LEFT, padx=2)
        self.b_conn = ttk.Button(r, text=t["connect"], command=self._toggle_camera); self.b_conn.pack(side=tk.LEFT, padx=2)
        self.l_info = self._note(f)
        r = self._row(f)
        self.v_cool = tk.BooleanVar(value=False)
        self.chk_cool = tk.Checkbutton(r, text=t["cooler"], variable=self.v_cool, command=self._cooler, bg=c["BG2"],
                                       fg=c["DIM"], selectcolor=c["BG3"], activebackground=c["BG2"], font=c["FS"])
        self.chk_cool.pack(side=tk.LEFT)
        self.v_cool_t = tk.IntVar(value=int(self.cfg.get("photo_cool_c", -10)))
        ttk.Spinbox(r, from_=-40, to=30, increment=1, textvariable=self.v_cool_t, width=5, font=c["FS"],
                    command=self._cooler).pack(side=tk.LEFT, padx=4)
        r = self._row(f); self._lbl(r, t["focal"], 14)
        self.v_focal = tk.StringVar(value=f"{float(self.cfg.get('focal_mm', 600)):g}")
        e = ttk.Entry(r, textvariable=self.v_focal, width=7, font=c["FS"]); e.pack(side=tk.LEFT, padx=4)
        e.bind("<FocusOut>", lambda ev: self._update_scale()); e.bind("<Return>", lambda ev: self._update_scale())
        self.l_scale = self._note(f, fg=c["ACC"])

        nb = self.nb = ttk.Notebook(left); nb.pack(fill=tk.BOTH, expand=True, padx=2, pady=4)
        tabs = []
        for key in ("tab_capture", "tab_astro", "tab_model", "tab_polar"):
            tab = tk.Frame(nb, bg=c["BG2"]); nb.add(tab, text=t[key]); tabs.append(tab)
        cap, ast, mod, pol = tabs
        self._build_polar(pol)

        # Onglet Prise de vue
        f = self._frame(cap, t["capture"])
        r = self._row(f); self._lbl(r, t["exposure"])
        self.v_exp = tk.DoubleVar(value=float(self.cfg.get("photo_exposure", 2.0)))
        self._spin(r, self.v_exp, 0.001, 3600, 0.5, 8)
        r = self._row(f); self._lbl(r, t["gain"])
        self.v_gain = tk.IntVar(value=int(self.cfg.get("photo_gain", 100)))
        self._spin(r, self.v_gain, 0, 600, 10, 8)
        r = self._row(f); self._lbl(r, t["binning"])
        self.v_bin = tk.StringVar(value=str(self.cfg.get("photo_bin", 1)))
        self.cb_bin = ttk.Combobox(r, textvariable=self.v_bin, values=["1", "2", "3", "4"], state="readonly", width=5, font=c["FS"])
        self.cb_bin.pack(side=tk.LEFT, padx=4); self.cb_bin.bind("<<ComboboxSelected>>", lambda e: self._update_scale())
        r = self._row(f)
        self.b_live = ttk.Button(r, text=t["live"], command=self._live); self.b_live.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        ttk.Button(r, text=t["shot"], command=self._shot).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        r = self._row(f); self._lbl(r, t["sequence"], 10)
        self.v_nseq = tk.IntVar(value=int(self.cfg.get("photo_seq", 10)))
        self._spin(r, self.v_nseq, 1, 999, 1, 5)
        tk.Label(r, text=t["frames"], bg=c["BG2"], fg=c["DIM"], font=c["FS"]).pack(side=tk.LEFT)
        ttk.Button(r, text=t["start_seq"], command=self._sequence).pack(side=tk.LEFT, padx=4)
        r = self._row(f)
        self.v_dither = tk.BooleanVar(value=self.cfg.get("photo_dither", False))
        tk.Checkbutton(r, text=t["dither"], variable=self.v_dither, bg=c["BG2"], fg=c["DIM"], selectcolor=c["BG3"],
                       activebackground=c["BG2"], font=c["FS"]).pack(side=tk.LEFT)
        self.v_dither_n = tk.IntVar(value=int(self.cfg.get("photo_dither_every", 3)))
        self._spin(r, self.v_dither_n, 1, 50, 1, 3)
        tk.Label(r, text=t["frames"], bg=c["BG2"], fg=c["DIM"], font=c["FS"]).pack(side=tk.LEFT)
        r = self._row(f)
        tk.Label(r, text=t["dither_by"], bg=c["BG2"], fg=c["DIM"], font=c["FS"]).pack(side=tk.LEFT, padx=(24, 0))
        self.v_dither_px = tk.DoubleVar(value=float(self.cfg.get("photo_dither_px", 5)))
        self._spin(r, self.v_dither_px, 1, 30, 1, 3)
        tk.Label(r, text=t["dither_px"], bg=c["BG2"], fg=c["DIM"], font=c["FS"]).pack(side=tk.LEFT)
        r = self._row(f); self._lbl(r, t["folder"], 8)
        self.v_dir = tk.StringVar(value=self.cfg.get("photo_dir", str(Path.home() / "Images" / "GotoAndrivet")))
        tk.Label(r, textvariable=self.v_dir, bg=c["BG3"], fg=c["TXT"], font=c["FS"], anchor="e", width=24).pack(side=tk.LEFT, padx=2)
        ttk.Button(r, text=t["choose"], command=self._choose_dir).pack(side=tk.LEFT)

        f = self._frame(cap, t["focus"])
        r = self._row(f)
        self.v_stars, self.v_hfr = tk.StringVar(value="—"), tk.StringVar(value="—")
        for lbl, var in ((t["stars"], self.v_stars), (t["hfr"], self.v_hfr)):
            box = tk.Frame(r, bg=c["BG3"]); box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
            tk.Label(box, text=lbl, bg=c["BG3"], fg=c["DIM"], font=c["FS"]).pack()
            tk.Label(box, textvariable=var, bg=c["BG3"], fg=c["GRN"], font=("Helvetica", 18, "bold")).pack()
        r = self._row(f)
        for i, (lbl, d, fast) in enumerate((("◀◀", -1, True), ("◀", -1, False), ("▶", 1, False), ("▶▶", 1, True))):
            r.columnconfigure(i, weight=1, uniform="pf")
            b = ttk.Button(r, text=lbl, width=4); b.grid(row=0, column=i, sticky="ew", padx=1)
            b.bind("<ButtonPress-1>", lambda e, d=d, f=fast: self.app.focuser.start(d, f))
            b.bind("<ButtonRelease-1>", lambda e: self.app.focuser.stop())
        self.l_focuser = self._note(f)

        # Onglet Astrométrie
        f = self._frame(ast, t["astrometry"])
        r = self._row(f)
        ttk.Button(r, text=t["solve"], command=lambda: self._solve(False)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        ttk.Button(r, text=t["solve_sync"], command=lambda: self._solve(True)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        r = self._row(f)
        ttk.Button(r, text=t["center"], style="GoTo.TButton", command=self._center).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        self._lbl(r, t["tolerance"], 13)
        self.v_tol = tk.DoubleVar(value=float(self.cfg.get("photo_tolerance", 2.0)))
        self._spin(r, self.v_tol, 0.2, 60, 0.5, 5)
        self.v_auto = tk.BooleanVar(value=self.cfg.get("photo_auto_center", True))
        tk.Checkbutton(f, text=t["auto"], variable=self.v_auto, command=lambda: self.cfg.set("photo_auto_center", self.v_auto.get()),
                       bg=c["BG2"], fg=c["TXT"], selectcolor=c["BG3"], activebackground=c["BG2"], font=c["FS"],
                       wraplength=320, justify="left", anchor="w").pack(fill=tk.X, pady=2)
        self.l_solve = self._note(f, fg=c["TXT"])

        f = self._frame(ast, t["framing"])
        r = self._row(f); self._lbl(r, t["angle"], 17)
        self.v_angle = tk.DoubleVar(value=float(self.cfg.get("photo_frame_angle", 0.0)))
        self._spin(r, self.v_angle, -180, 180, 5, 6)
        ttk.Button(r, text=t["rotate"], command=self._rotate).pack(side=tk.LEFT, padx=2)
        self._note(f, t["framing_note"])

        # Onglet Modèle
        f = self._frame(mod, t["model"])
        r = self._row(f); self._lbl(r, t["points"], 8)
        self.v_npts = tk.IntVar(value=int(self.cfg.get("photo_model_points", 9)))
        self._spin(r, self.v_npts, 3, 30, 1, 4)
        self._lbl(r, t["alt_min"], 16)
        self.v_altmin = tk.DoubleVar(value=float(self.cfg.get("photo_model_alt_min", 25)))
        self._spin(r, self.v_altmin, 10, 60, 5, 4)
        r = self._row(f)
        ttk.Button(r, text=t["build"], style="GoTo.TButton", command=self._build_model).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        ttk.Button(r, text=t["clear"], command=self._clear_model).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        self.lb_model = tk.Listbox(f, height=12, bg=c["BG3"], fg=c["TXT"], font=c["FS"], highlightthickness=0,
                                   relief="flat", activestyle="none", selectbackground=c["BG3"])
        self.lb_model.pack(fill=tk.X, pady=4)
        self.l_model = self._note(f, fg=c["ACC"])
        self._note(f, t["model_note"])

        # Image et barre d'état
        self.canvas = tk.Canvas(right, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.canvas.bind("<Configure>", lambda e: self._show())
        sb = tk.Frame(right, bg=c["BG"]); sb.pack(fill=tk.X)
        ttk.Button(sb, text=t["stop"], style="Stop.TButton", command=self.stop).pack(side=tk.RIGHT, padx=4, pady=2)
        self.l_temp = tk.Label(sb, text="", bg=c["BG"], fg=c["DIM"], font=c["FS"]); self.l_temp.pack(side=tk.RIGHT, padx=8)
        self.l_status = tk.Label(sb, text=t["ready"], bg=c["BG"], fg=c["DIM"], font=c["FS"], anchor="w")
        self.l_status.pack(side=tk.LEFT, padx=8, pady=2)
        self.after(1000, self._tick)

    # ── Caméra ───────────────────────────────────────────────
    def _refresh_cameras(self):
        names = list_cameras() + [self.t["sim"]]
        self.cb_cam.configure(values=names)
        if self.v_cam.get() not in names: self.v_cam.set(names[0])

    def _toggle_camera(self):
        if self.camera:
            self.abort.set(); self.camera.close(); self.camera = None
            self.b_conn.configure(text=self.t["connect"]); self.l_info.configure(text=""); self.app.photo_set_fov(None)
            return
        try:
            name = self.v_cam.get()
            if name == self.t["sim"]:
                self.camera = SimCamera(self._pointing, self._focal, self.app.photo_bright_stars(),
                                        rotation=self.app.photo_rotator_angle)
            else:
                self.camera = ZwoCamera(list_cameras().index(name))
        except Exception as e:
            self.camera = None; messagebox.showerror(self.t["title"], self.t["error"].format(e=e), parent=self); return
        cam = self.camera
        self.cb_bin.configure(values=[str(b) for b in cam.bins])
        if int(self.v_bin.get()) not in cam.bins: self.v_bin.set("1")
        kind = self.t["color"] if cam.color else self.t["mono"]
        self.l_info.configure(text=f"{cam.name} · {cam.max_w} × {cam.max_h} px · {cam.pixel_um:.2f} µm · {kind}")
        self.chk_cool.configure(state="normal" if cam.cooled else "disabled")
        self.b_conn.configure(text=self.t["disconnect"])
        self._update_scale()
        if cam.simulated:
            ra, dec = self._pointing(); e = cam.error(ra, dec)
            self._status(self.t["sim_offset"].format(d=angular_dist(ra, dec, ra + e[0] / 15, dec + e[1]) * 60))

    def _cooler(self):
        if self.camera:
            self.cfg.set("photo_cool_c", self.v_cool_t.get())
            try: self.camera.set_cooler(self.v_cool.get(), self.v_cool_t.get())
            except Exception as e: self._status(self.t["error"].format(e=e))

    def _focal(self):
        try: return max(1.0, float(self.v_focal.get().replace(",", ".")))
        except ValueError: return 600.0

    def _pointing(self):
        """Pointage J2000 : la monture, sinon (caméra simulée) le centre de la carte."""
        return self.app.photo_pointing() or self.app.photo_sky_center()

    def _geometry(self, binning=None, focal=None):
        """(échelle ″/px, largeur °, hauteur °) avec la caméra connectée (ou une ASI174 par défaut)."""
        cam = self.camera or SimCamera
        b = binning or int(self.v_bin.get() or 1)
        return field_of_view(cam.pixel_um, b, cam.max_w // b, cam.max_h // b, focal or self._focal())

    def _update_scale(self):
        self.cfg.set("focal_mm", self._focal())
        sc, w, h = self._geometry()
        self.l_scale.configure(text=self.t["scale"].format(sc=sc, w=w, h=h))
        if self.camera:
            self.app.photo_set_fov((w, h, self.solution["rotation"] if self.solution else 0.0))

    # ── Tâches : un seul fil de travail à la fois ────────────
    def _ui(self, fn):
        """Exécute fn dans le fil de Tk (sans erreur si la fenêtre vient d'être fermée)."""
        try: self.after(0, fn)
        except (tk.TclError, RuntimeError): pass

    def _run(self, job, need_cam=True):
        if self.busy:
            self._status(self.t["busy"]); return False
        if need_cam and not self.camera:
            messagebox.showwarning(self.t["title"], self.t["need_cam"], parent=self); return False
        try:      # réglages figés pour le fil de travail (les variables Tk restent au fil principal)
            self.p = {"exp": float(self.v_exp.get()), "gain": int(self.v_gain.get()), "bin": int(self.v_bin.get()),
                      "focal": self._focal(), "dir": self.v_dir.get(), "tol": float(self.v_tol.get()),
                      "nseq": int(self.v_nseq.get()), "angle": float(self.v_angle.get()),
                      "npts": int(self.v_npts.get()), "altmin": float(self.v_altmin.get()),
                      "dither": bool(self.v_dither.get()), "dither_n": int(self.v_dither_n.get()),
                      "dither_px": float(self.v_dither_px.get())}
        except (tk.TclError, ValueError) as e:
            self._status(self.t["error"].format(e=e)); return False
        for k, v in (("photo_exposure", "exp"), ("photo_gain", "gain"), ("photo_bin", "bin"), ("photo_dir", "dir"),
                     ("photo_tolerance", "tol"), ("photo_seq", "nseq"), ("photo_frame_angle", "angle"),
                     ("photo_model_points", "npts"), ("photo_model_alt_min", "altmin"), ("photo_dither", "dither"),
                     ("photo_dither_every", "dither_n"), ("photo_dither_px", "dither_px")):
            self.cfg.set(k, self.p[v])
        self.busy = True; self.abort.clear()

        def work():
            try:
                job()
            except Exception as e:
                self._ui(lambda err=e: self._status(self.t["error"].format(e=err)))
            finally:
                self.busy = False
                self._ui(lambda: self.b_live.configure(text=self.t["live"]))
        threading.Thread(target=work, daemon=True, name="photo").start()
        return True

    def stop(self):
        self.abort.set()

    def _expose(self):
        """Une pose avec les réglages figés ; affiche et mesure l'image ; None si interrompue."""
        s = self.p["exp"]
        self.camera.setup(self.p["gain"], self.p["bin"])
        self._ui(lambda: self._status(self.t["exposing"].format(s=s)))
        img = self.camera.expose(s, self.abort)
        if img is None:
            return None
        self.image = img
        n, hfr = star_metrics(img)
        self._ui(lambda: (self._show(), self.v_stars.set("—" if n is None else str(n)),
                          self.v_hfr.set("—" if hfr is None else f"{hfr:.2f}")))
        return img

    def _wait_slew(self):
        """Attend la fin du déplacement de la monture, puis la stabilisation ; False si interrompu."""
        time.sleep(2.0)                      # le drapeau de déplacement arrive avec la scrutation suivante
        t0 = time.time()
        while self.app.photo_slewing() and time.time() - t0 < 300:
            if self.abort.is_set(): return False
            time.sleep(0.5)
        time.sleep(1.0)
        return not self.abort.is_set()

    def _live(self):
        if self.busy:
            self.abort.set(); return
        def job():
            while not self.abort.is_set():
                if self._expose() is None: break
            self._ui(lambda: self._status(self.t["stopped"]))
        if self._run(job):
            self.b_live.configure(text=self.t["stop"])

    def _save(self, img, index=None):
        folder = Path(self.p["dir"]) / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        tgt = self.app.photo_target()
        obj = re.sub(r"[^A-Za-z0-9_-]+", "_", tgt[2] if tgt else "image").strip("_") or "image"
        s, b = self.p["exp"], self.p["bin"]
        stamp = datetime.now(timezone.utc)
        path = folder / f"{obj}_{s:g}s_{stamp.strftime('%H%M%S')}{'' if index is None else f'_{index:03d}'}.fits"
        hdr = {"DATE-OBS": (stamp.strftime("%Y-%m-%dT%H:%M:%S"), "UTC, debut de pose"), "EXPTIME": (s, "s"),
               "GAIN": (self.p["gain"], ""), "XBINNING": (b, ""), "YBINNING": (b, ""),
               "XPIXSZ": (self.camera.pixel_um * b, "um"), "YPIXSZ": (self.camera.pixel_um * b, "um"),
               "FOCALLEN": (self.p["focal"], "mm"), "INSTRUME": (self.camera.name, ""), "TELESCOP": ("GotoAndrivet", ""),
               "OBJECT": (tgt[2] if tgt else "", ""), "ROWORDER": ("TOP-DOWN", "ligne 0 en haut de l'image")}
        p = self.app.photo_pointing()
        if p:
            hdr["RA"] = (p[0] * 15, "deg J2000, monture"); hdr["DEC"] = (p[1], "deg J2000, monture")
        t = self.camera.temperature()
        if t is not None: hdr["CCD-TEMP"] = (t, "C")
        write_fits(path, img, hdr)
        return path

    def _shot(self):
        def job():
            img = self._expose()
            if img is not None:
                path = self._save(img)
                self._ui(lambda: self._status(self.t["saved"].format(f=path)))
        self._run(job)

    def _sequence(self):
        def job():
            n, done = self.p["nseq"], 0
            for i in range(1, n + 1):
                img = self._expose()
                if img is None: break
                path = self._save(img, i); done = i
                self._ui(lambda p=path, i=i: self._status(f"{i}/{n} · " + self.t["saved"].format(f=p.name)))
                if self.p["dither"] and i < n and i % self.p["dither_n"] == 0 and self.app.guide_active():
                    self._ui(lambda: self._status(self.t["dithering"]))
                    if not self.app.guide_dither(self.p["dither_px"]):
                        self._ui(lambda: self._status(self.t["dither_fail"]))
            self._ui(lambda: self._status(self.t["seq_done"].format(n=done)))
        self._run(job)

    def _choose_dir(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.v_dir.get())
        if d: self.v_dir.set(d); self.cfg.set("photo_dir", d)

    # ── Astrométrie ──────────────────────────────────────────
    def _solve_frame(self):
        """Pose + astrométrie ; renvoie la solution (J2000) ou None si interrompue."""
        img = self._expose()
        if img is None:
            return None
        fd, tmp = tempfile.mkstemp(suffix=".fits", prefix="gotoandrivet_"); os.close(fd)
        try:
            write_fits(tmp, img, {})
            self._ui(lambda: self._status(self.t["solving"]))
            sc, _, _ = self._geometry(self.p["bin"], self.p["focal"])
            hint = self._pointing() if self.camera.simulated else self.app.photo_pointing()
            sol = plate_solve(tmp, sc, hint=hint, radius_deg=15 if hint else 180, abort=self.abort)
        finally:
            os.unlink(tmp)
        self.solution = sol
        txt = self.t["solved"].format(ra=_fmt_ra(sol["ra_h"]), dec=_fmt_dec(sol["dec_d"]), rot=sol["rotation"],
                                      mir=self.t["mirrored"] if sol.get("mirrored") else "", sc=sol["scale"] or 0)
        tgt = self.app.photo_target()
        if tgt:
            txt += f"\n→ {tgt[2]} : {angular_dist(sol['ra_h'], sol['dec_d'], tgt[0], tgt[1]) * 60:.1f}′"
        self._ui(lambda: (self.l_solve.configure(text=txt), self._status(txt.split("\n")[0]), self._update_scale()))
        return sol

    def _sync(self, sol, err_arcmin):
        """Synchronise la monture sur la position résolue : un point de plus dans le modèle du firmware."""
        r = self.app.photo_sync(sol["ra_h"], sol["dec_d"])
        if self.camera.simulated:
            self.camera.synced()
        if r == "RESET":                     # la monture avait bougé : le firmware repart de ce point
            self.synced_pts.clear()
        elif r not in ("OK", None):          # refusée (GoTo en cours, près du pôle, heure...) : pas de point
            self._ui(lambda: self._status(f"Sync → {r}"))
            return
        az, alt = self.app.photo_radec_to_altaz(sol["ra_h"], sol["dec_d"])
        self.synced_pts.append((az, alt, err_arcmin))
        self._ui(self._model_list)

    def _checks(self, mount=True, target=False, quiet=False):
        """Préalables communs ; avec quiet, refuse sans boîte de dialogue (correction automatique)."""
        msg = None
        if not solver_available(): msg = self.t["no_solver"]
        elif not self.camera: msg = self.t["need_cam"]
        elif mount and not self.app.photo_pointing(): msg = self.t["need_mount"]
        elif target and not self.app.photo_target(): msg = self.t["no_target"]
        if msg and not quiet:
            messagebox.showwarning(self.t["title"], msg, parent=self)
        return msg is None

    def _solve(self, sync):
        if not self._checks(mount=sync): return
        def job():
            sol = self._solve_frame()
            if sol and sync:
                p = self.app.photo_pointing()
                self._sync(sol, angular_dist(sol["ra_h"], sol["dec_d"], p[0], p[1]) * 60)
                self._ui(lambda: self._status(self.t["synced"]))
        self._run(job)

    def _center_loop(self, tgt, tol, tries=5):
        """Comme le « Plate solve and GoTo » d'un ASIAIR : astrométrie, synchro, nouveau GoTo, jusqu'à la tolérance."""
        d = None
        for i in range(1, tries + 1):
            sol = self._solve_frame()
            if sol is None: return
            d = angular_dist(sol["ra_h"], sol["dec_d"], tgt[0], tgt[1]) * 60
            self._ui(lambda i=i, d=d: self._status(self.t["center_try"].format(i=i, d=d)))
            if d <= tol:
                self._ui(lambda d=d: self._status(self.t["centered"].format(d=d))); return
            p = self.app.photo_pointing()
            self._sync(sol, angular_dist(sol["ra_h"], sol["dec_d"], p[0], p[1]) * 60); time.sleep(0.5)
            r = self.app.photo_goto(tgt[0], tgt[1], tgt[2])
            if not r.startswith("0"):
                self._ui(lambda: self._status(self.t["goto_refused"].format(r=r))); return
            if not self._wait_slew(): return
        self._ui(lambda: self._status(self.t["center_fail"].format(n=tries, d=d or 0)))

    def _center(self):
        if not self._checks(target=True): return
        tgt = self.app.photo_target()
        self._run(lambda: self._center_loop(tgt, self.p["tol"]))

    def after_goto(self):
        """Appelé par la carte après chaque GoTo accepté : vérification et correction automatiques."""
        if not (self.v_auto.get() and self._checks(target=True, quiet=True)):
            return
        if self.busy:                        # le GoTo interrompt la vue en continu ou la séquence en cours
            self.abort.set(); self.after(300, self.after_goto); return
        tgt = self.app.photo_target()
        self._status(self.t["auto_start"])
        self._run(lambda: self._wait_slew() and self._center_loop(tgt, self.p["tol"]))

    def _rotate(self):
        """Tourne le dérotateur jusqu'à l'angle de cadrage voulu, mesuré par astrométrie."""
        if not self._checks(mount=False): return
        if not self.app.derot.connected:
            messagebox.showwarning(self.t["title"], self.t["need_derot"], parent=self); return
        def job():
            want, prev = self.p["angle"], None
            sign = self.cfg.get("photo_rotator_sign", 1)
            for i in range(1, 6):
                sol = self._solve_frame()
                if sol is None: return
                d = (want - sol["rotation"] + 180) % 360 - 180
                self._ui(lambda i=i, r=sol["rotation"], d=d: self._status(self.t["rot_try"].format(i=i, r=r, d=d)))
                if abs(d) <= 1.0:
                    self._ui(lambda r=sol["rotation"]: self._status(self.t["rot_done"].format(r=r))); return
                if prev is not None and abs(d) > abs(prev) * 1.3:     # l'écart grandit : rotateur dans l'autre sens
                    sign = -sign; self.cfg.set("photo_rotator_sign", sign)
                self.app.derot.rotate_by(sign * d)
                time.sleep(2.0 + min(60.0, abs(d) * float(self.cfg.get("derot_ppd", 100.0)) / 2000.0))
                while self.app.derot.moving and not self.abort.is_set(): time.sleep(0.3)
                prev = d
            self._ui(lambda: self._status(self.t["rot_fail"].format(d=d)))
        self._run(job)

    # ── Modèle de pointage ───────────────────────────────────
    def _build_model(self):
        if not self._checks(): return
        def job():
            pts = model_points(self.p["npts"], self.p["altmin"])
            ok = 0
            for i, (az, alt) in enumerate(pts, 1):
                if self.abort.is_set(): break
                self._ui(lambda i=i, az=az, alt=alt: self._status(self.t["model_pt"].format(i=i, n=len(pts), az=az, alt=alt)))
                ra, dec = self.app.photo_altaz_to_radec(az, alt)
                r = self.app.photo_goto(ra, dec, f"modèle {i}")
                if not r.startswith("0"):
                    self._ui(lambda i=i, r=r: self.lb_model.insert(tk.END, self.t["model_fail"].format(i=i, e=r))); continue
                if not self._wait_slew(): break
                try:
                    sol = self._solve_frame()
                except RuntimeError as e:
                    self._ui(lambda i=i, e=e: self.lb_model.insert(tk.END, self.t["model_fail"].format(i=i, e=e))); continue
                if sol is None: break
                self._sync(sol, angular_dist(sol["ra_h"], sol["dec_d"], ra, dec) * 60); ok += 1
            self._ui(lambda: self._status(self.t["model_done"].format(ok=ok, n=len(pts))))
        self._run(job)

    def _clear_model(self):
        if not self.app.photo_pointing():
            messagebox.showwarning(self.t["title"], self.t["need_mount"], parent=self); return
        r = self.app.photo_clear_model()
        self.synced_pts.clear(); self._model_list()
        self._status(self.t["model_cleared"].format(r=r or "—"))

    def _model_list(self):
        self.lb_model.delete(0, tk.END)
        for i, (az, alt, e) in enumerate(self.synced_pts, 1):
            self.lb_model.insert(tk.END, f"{i:2d}.  Az {az:5.1f}°  Alt {alt:4.1f}°   {e:6.1f}′")
        if self.synced_pts:
            errs = [e for _, _, e in self.synced_pts]
            self.l_model.configure(text=self.t["model_sum"].format(n=len(errs), m=sum(errs) / len(errs), x=max(errs)))
        else:
            self.l_model.configure(text=self.t["model_empty"])

    # ── Mise en station (mise_en_station_robot.py, carte pcb/mise_en_station) ──
    def _build_polar(self, pol):
        c, t = self.c, self.t
        self.pa_card = None; self.pa = None
        f = self._frame(pol, t["pa_board"])
        r = self._row(f)
        self.v_pa_port = tk.StringVar(value=self.cfg.get("pa_port", ""))
        self.cb_pa_port = ttk.Combobox(r, textvariable=self.v_pa_port, width=21, font=c["FS"])
        self.cb_pa_port.pack(side=tk.LEFT, padx=2)
        ttk.Button(r, text="↺", width=3, command=self._pa_ports).pack(side=tk.LEFT, padx=2)
        self.b_pa_conn = ttk.Button(r, text=t["connect"], command=self._pa_toggle); self.b_pa_conn.pack(side=tk.LEFT, padx=2)
        self.l_pa_board = self._note(f, t["pa_noboard"])
        self.l_pa_calib = self._note(f)
        r = self._row(f); self._lbl(r, t["pa_steps"], 6)
        self.v_pa_jog = tk.IntVar(value=int(self.cfg.get("pa_jog", 200)))
        self._spin(r, self.v_pa_jog, 1, 100000, 50, 6)
        for lbl, axe, sgn in (("Az −", "A", -1), ("Az +", "A", 1), ("Haut −" if self.cfg.get("language", "fr") == "fr"
                              else "Alt −", "L", -1), ("Haut +" if self.cfg.get("language", "fr") == "fr" else "Alt +", "L", 1)):
            ttk.Button(r, text=lbl, width=6, command=lambda a=axe, s=sgn: self._pa_jog(a, s)).pack(side=tk.LEFT, padx=1)

        f = self._frame(pol, t["pa_measure"])
        r = self._row(f); self._lbl(r, t["pa_angle"], 17)
        self.v_pa_angle = tk.DoubleVar(value=float(self.cfg.get("pa_angle", 30.0)))
        self._spin(r, self.v_pa_angle, -60, 60, 5, 5)
        self._lbl(r, t["pa_tol"], 13)
        self.v_pa_tol = tk.DoubleVar(value=float(self.cfg.get("pa_tolerance", 1.0)))
        self._spin(r, self.v_pa_tol, 0.2, 30, 0.1, 4)
        self.v_pa_refr = tk.BooleanVar(value=self.cfg.get("pa_refraction", False))
        tk.Checkbutton(f, text=t["pa_refr"], variable=self.v_pa_refr, bg=c["BG2"], fg=c["TXT"], selectcolor=c["BG3"],
                       activebackground=c["BG2"], font=c["FS"], wraplength=320, justify="left", anchor="w").pack(fill=tk.X)
        r = self._row(f)
        ttk.Button(r, text=t["pa_axis"], command=self._pa_axis).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        ttk.Button(r, text=t["pa_refresh"], command=self._pa_refresh).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        r = self._row(f)
        ttk.Button(r, text=t["pa_auto"], style="GoTo.TButton", command=self._pa_auto).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        ttk.Button(r, text=t["pa_calib"], command=self._pa_recalib).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        self.l_pa_err = tk.Label(f, text="—", bg=c["BG2"], fg=c["GRN"], font=("Helvetica", 16, "bold"))
        self.l_pa_err.pack(fill=tk.X, pady=2)
        self.l_pa_hint = self._note(f, fg=c["TXT"])
        self._note(f, t["pa_note"])

        self.lb_pa = tk.Listbox(pol, height=8, bg=c["BG3"], fg=c["TXT"], font=c["FS"], highlightthickness=0,
                                relief="flat", activestyle="none", selectbackground=c["BG3"])
        self.lb_pa.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self._pa_ports(); self._pa_calib_text()

    def _pa_log(self, txt):
        def f():
            self.lb_pa.insert(tk.END, txt); self.lb_pa.see(tk.END); self._status(txt)
        self._ui(f)

    def _pa_ports(self):
        import mise_en_station_robot as mes
        ports = mes.CarteMES.ports()
        self.cb_pa_port.configure(values=ports)
        if not self.v_pa_port.get() and ports: self.v_pa_port.set(ports[-1])

    def _pa_toggle(self):
        import mise_en_station_robot as mes
        if self.pa_card:
            self.pa_card.fermer(); self.pa_card = None
            if self.pa: self.pa.carte = None
            self.b_pa_conn.configure(text=self.t["connect"]); self.l_pa_board.configure(text=self.t["pa_noboard"])
            return
        port = self.v_pa_port.get()
        self.b_pa_conn.configure(state="disabled")

        def ouvrir():
            try:
                card = mes.CarteMES(port)
            except Exception as e:
                self._ui(lambda err=e: (self.b_pa_conn.configure(state="normal"),
                                        messagebox.showerror(self.t["title"], self.t["error"].format(e=err), parent=self)))
                return
            def ok():
                self.pa_card = card; self.cfg.set("pa_port", port)
                if self.pa: self.pa.carte = card
                self.b_pa_conn.configure(state="normal", text=self.t["disconnect"]); self._pa_board_text()
            self._ui(ok)
        threading.Thread(target=ouvrir, daemon=True).start()

    def _pa_board_text(self):
        card = self.pa_card
        if not card:
            return
        try:
            e = card.etat()
            noms = ("az MIN", "az MAX", "haut MIN", "haut MAX")
            fc = ", ".join(n for n, on in zip(noms, e["fc"]) if on)
            vm = f"{e['vm']:.1f} V".replace(".", ",") if e["vm"] >= 5 else self.t["pa_vm_off"]
            txt = self.t["pa_board_st"].format(v=f"{card.port} v{card.version}", vm=vm, pa=card.position("A"),
                                               pl=card.position("L"), fc=self.t["pa_fc"].format(l=fc) if fc else "")
        except Exception as ex:
            txt = self.t["error"].format(e=ex)
        self.l_pa_board.configure(text=txt)

    def _pa_calib_text(self):
        M = self.pa.M if self.pa is not None and self.pa.M is not None else self.cfg.get("pa_calibration")
        if M is None:
            self.l_pa_calib.configure(text=self.t["pa_calib_none"]); return
        M = np.array(M, dtype=float)
        f = lambda col: f"{1 / math.hypot(*M[:, col]):.0f}" if math.hypot(*M[:, col]) > 0 else "—"
        self.l_pa_calib.configure(text=self.t["pa_calib_st"].format(a=f(0), l=f(1)))

    def _pa_show(self, e):
        import mise_en_station_robot as mes
        fr = self.cfg.get("language", "fr") == "fr"
        col = self.c["GRN"] if e["total"] <= float(self.cfg.get("pa_tolerance", 1.0)) else self.c["ACC"]
        txt = self.t["pa_done"].format(e=e["total"])
        self._ui(lambda: (self.l_pa_err.configure(text=txt.replace(".", ",") if fr else txt, fg=col),
                          self.l_pa_hint.configure(text=mes.sens_en_mots(e, fr)), self._pa_calib_text(),
                          self._pa_board_text()))

    def _pa_engine(self):
        """Déroulement de la mise en station, gardé entre deux boutons (l'axe mesuré reste connu)."""
        import mise_en_station_robot as mes
        lat, lon = float(self.cfg.get("latitude", 45.764)), float(self.cfg.get("longitude", 4.836))
        if self.pa is None or (self.pa.lat, self.pa.lon) != (lat, lon):
            self.pa = mes.MiseEnStation(lat, lon, self._pa_measure, self._pa_turn, self.pa_card,
                                        suivi=self.app.photo_tracking, journal=self._pa_log, abort=self.abort,
                                        calibration=self.cfg.get("pa_calibration"))
        self.pa.carte = self.pa_card
        self.pa.refraction = self.p["pa_refr"]
        return self.pa

    def _pa_measure(self):
        """Pose + astrométrie : (AD, Déc J2000, instant du milieu de pose). Un second essai si l'image n'est pas résolue."""
        from datetime import timedelta
        for essai in (1, 2):
            t = datetime.now(timezone.utc) + timedelta(seconds=self.p["exp"] / 2)
            try:
                sol = self._solve_frame()
            except RuntimeError as e:
                if essai == 2 or self.abort.is_set(): raise
                self._pa_log(self.t["error"].format(e=e)); continue
            return None if sol is None else (sol["ra_h"], sol["dec_d"], t)

    def _pa_turn(self, deg):
        if self.app.photo_pointing():
            self.app.photo_rotate_ra(deg, self.abort)
        else:
            self.app._ui_call(lambda: messagebox.showinfo(self.t["title"], self.t["pa_turn"].format(d=abs(deg)), parent=self))
            time.sleep(0.5)

    def _pa_start(self, work, need_axis=False, need_board=False):
        if self.cfg.get("mount_type", "AltAz") == "AltAz":
            messagebox.showwarning(self.t["title"], self.t["pa_need_eq"], parent=self); return
        if not self._checks(mount=False): return
        if need_axis and (self.pa is None or self.pa.axe is None):
            messagebox.showwarning(self.t["title"], self.t["pa_need_axis"], parent=self); return
        if need_board and not self.pa_card:
            messagebox.showwarning(self.t["title"], self.t["pa_need_board"], parent=self); return
        try:
            extra = {"pa_angle": float(self.v_pa_angle.get()), "pa_tol": float(self.v_pa_tol.get()),
                     "pa_refr": bool(self.v_pa_refr.get())}
        except (tk.TclError, ValueError) as e:
            self._status(self.t["error"].format(e=e)); return
        for k, v in (("pa_angle", "pa_angle"), ("pa_tolerance", "pa_tol"), ("pa_refraction", "pa_refr")):
            self.cfg.set(k, extra[v])

        def job():
            import mise_en_station_robot as mes
            self.p.update(extra)
            m = self._pa_engine()
            try:
                e = work(m)
                if e is not None: self._pa_show(e)
            except mes.Arret:
                self._pa_log(self.t["stopped"])
            except Exception as ex:
                if self.pa_card:
                    try: self.pa_card.stop()
                    except Exception: pass
                self._pa_log(self.t["error"].format(e=ex))
            finally:
                if m.M is not None: self.cfg.set("pa_calibration", m.M.tolist())
                self._ui(self._pa_calib_text)
        self._run(job)

    def _pa_axis(self):
        self._pa_start(lambda m: m.mesurer_axe(self.p["pa_angle"]))

    def _pa_refresh(self):
        self._pa_start(lambda m: m.mesurer_erreur()[1], need_axis=True)

    def _pa_auto(self):
        self._pa_start(lambda m: m.corriger(self.p["pa_tol"]), need_axis=True, need_board=True)

    def _pa_recalib(self):
        def work(m):
            m.calibrer(); return m.erreur()
        self._pa_start(work, need_axis=True, need_board=True)

    def _pa_jog(self, axe, sens):
        if not self.pa_card:
            messagebox.showwarning(self.t["title"], self.t["pa_need_board"], parent=self); return
        try:
            n = int(self.v_pa_jog.get()); self.cfg.set("pa_jog", n)
            self.pa_card.bouger(axe, sens * n)
        except Exception as e:
            self._status(self.t["error"].format(e=e))
        self.after(500, self._pa_board_text)

    # ── Affichage ────────────────────────────────────────────
    def _show(self):
        if self.image is None:
            return
        try:
            from PIL import Image, ImageTk
        except ImportError:
            return
        W, H = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        pic = Image.fromarray(autostretch(self.image))
        k = min(W / pic.width, H / pic.height)
        pic = pic.resize((max(1, int(pic.width * k)), max(1, int(pic.height * k))), Image.LANCZOS)
        self._tkimg = ImageTk.PhotoImage(pic)
        self.canvas.delete("all")
        self.canvas.create_image(W / 2, H / 2, image=self._tkimg)
        for dx, dy in ((-14, 0), (14, 0), (0, -14), (0, 14)):          # croix au centre de l'image
            self.canvas.create_line(W / 2 + dx * 0.4, H / 2 + dy * 0.4, W / 2 + dx, H / 2 + dy, fill="#ff5050")

    def _status(self, txt):
        self.l_status.configure(text=txt)

    def _tick(self):
        if not self.winfo_exists():
            return
        if self.camera:
            t = self.camera.temperature()
            self.l_temp.configure(text="" if t is None else self.t["temp"].format(t=f"{t:.1f} °C"))
        self.l_focuser.configure(text="" if self.app.focuser.connected else self.t["focuser_off"])
        if self.pa_card and not self.busy:
            self._pa_board_text()
        self.after(2000, self._tick)

    def close(self):
        self.abort.set()
        for _ in range(40):                  # laisse la pose ou l'astrométrie en cours s'interrompre
            if not self.busy: break
            self.update(); time.sleep(0.05)
        if self.camera:
            self.camera.close(); self.camera = None
        if self.pa_card:
            try: self.pa_card.stop()
            except Exception: pass
            self.pa_card.fermer(); self.pa_card = None
        self.app.photo_set_fov(None)
        self.destroy()
