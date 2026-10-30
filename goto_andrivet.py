#!/usr/bin/env python3
# Auteur : Andrivet Jean-Baptiste
"""
╔══════════════════════════════════════════════════════════════╗
║      GotoAndrivet — Carte du ciel et GoTo                    ║
║      Contrôleur Multi-Montures · LX200/OnStep                ║
╚══════════════════════════════════════════════════════════════╝

Lancement :
    python3 goto_andrivet.py

Dépendances :
    pip3 install pyserial ephem      (ephem : Soleil, Lune et planètes, facultatif)

Données du ciel (ciel_donnees.py, généré par outils/generer_ciel_donnees.py) :
    étoiles du Yale Bright Star Catalogue, constellations de Stellarium,
    ciel profond OpenNGC (Messier, Caldwell, NGC, IC). Positions J2000,
    précessées à la date pour la carte et pour la monture.

En mode SIMULATION (case à cocher, décochée par défaut), aucun matériel requis.
En mode réel, brancher l'Arduino Mega sur USB, sélectionner le port.

Fonctions :
  • GoTo catalogue complet (Messier, NGC, IC, PK, Caldwell, Étoiles)
  • Suivi sidéral temps réel
  • Dérotateur de champ ZWO (port série / simulation)
  • Carte du ciel interactive (projection azimutale, zoom, pan, clic→GoTo)
  • Paramètres persistants (lieu, engrenages, vitesses, ports)
  • Protocole LX200/OnStep complet vers Arduino Mega via USB

CORRECTIONS v5.1 (alignement protocoles avec Mega v9.0+) :
  - Polling : :GX# → :GBE# (la commande :GX# entre en collision
    avec l'espace OnStep :GXnn# côté Mega ; le Mega répond 0# et
    on perdait alt/az/speed/limit_hit)
  - set_speed : :SV → :BV (:SV n'est pas géré par le Mega)
  - set_tracking : :T+/:T- → :Te/:Td (:T+/:T- ne font qu'ajuster
    le rate sidéral en spec OnStep, ils n'activent pas le suivi)
  - parking : :hP toujours (le fallback :PK était du code mort)
  - Détection du flag 'F' (time-not-set) du Mega v9.1 :
    interdit goto/sync tant que :SC + :SL n'ont pas été envoyés.
  - Sim _sim_gu retourne maintenant un format OnStep valide
    pour que detect_firmware() fonctionne en mode simulation.
  - Baud par défaut : 19200 (Mega v9.1 passe à 19200 sur USB)
"""

# ── Imports standard ──────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import math
import json
import re
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Callable, List, Dict

import mise_a_jour

# ── Import pyserial (optionnel — mode sim fonctionne sans) ────
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("goto_andrivet")


# ════════════════════════════════════════════════════════════════
#  SECTION 1 : PARAMÈTRES PERSISTANTS
# ════════════════════════════════════════════════════════════════
CONFIG_FILE = Path.home() / ".config" / "goto_andrivet" / "settings.json"

DEFAULTS = {
    "site_name":           "Lyon-Villeurbanne",
    "latitude":            45.764043,
    "longitude":           4.835659,
    "language":            "fr",
    "altitude_m":          200,
    "steps_per_rev_motor": 200,
    "microstep":           125,
    "mount_type":          "AltAz",
    "gear_ratio_az":       750.0,
    "gear_ratio_alt":      750.0,
    "az_reversed":         False,
    "alt_reversed":        False,
    "alt_min_deg":         2.0,
    "alt_max_deg":         88.0,
    "az_limit_deg":        540.0,
    "slew_speed_default":  2.0,
    "slew_speed_max":      25.0,
    "slew_speed_min":      0.5,
    "guide_speed":         0.25,
    "mount_port":          "/dev/ttyUSB0",
    "mount_baud":          38400,                # v5.1 : aligne sur Mega v9.1 (optimisé à 38400)
    "mount_timeout":       0.5,
    "derot_enabled":       False,
    "derot_port":          "/dev/ttyUSB1",
    "derot_baud":          9600,
    "derot_reversed":      False,
    "skymap_fov_deg":      90.0,
    "skymap_mag_limit":    6.5,
}

# GeolocHandler and standard HTTP server imports removed. Using public IP geolocation API instead.


class Settings:
    def __init__(self):
        self._d = dict(DEFAULTS)
        self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                self._d.update(json.loads(CONFIG_FILE.read_text()))
            except Exception:
                pass

    def save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self._d, indent=2, ensure_ascii=False))

    def get(self, k, default=None):
        return self._d.get(k, DEFAULTS.get(k, default))

    def set(self, k, v):
        self._d[k] = v

    def update(self, d):
        self._d.update(d)



    def all(self):
        return dict(self._d)


# ════════════════════════════════════════════════════════════════
#  SECTION 2 : CATALOGUES ASTRONOMIQUES
# ════════════════════════════════════════════════════════════════
GALAXY       = "Gal";  OPEN_CLUSTER = "OC";  GLOB_CLUSTER = "GC"
NEBULA       = "Neb";  PLAN_NEBULA  = "PN";  SUPERNOVA    = "SNR"
DOUBLE_STAR  = "DS";   ASTERISM     = "Ast"; STAR         = "★"

TYPE_NAMES = {
    "Gal":"Galaxie", "OC":"Amas ouvert", "GC":"Amas globulaire",
    "Neb":"Nébuleuse", "PN":"Nébuleuse planétaire", "SNR":"Reste supernova",
    "DS":"Étoile double", "Ast":"Astérisme", "★":"Étoile",
}
TYPE_COLORS = {
    "Gal":"#ff8844", "OC":"#ffdd44", "GC":"#ffaa22", "Neb":"#44aaff",
    "PN":"#44ffaa",  "SNR":"#ff4444","DS":"#aaddff", "Ast":"#dddddd",
    "★":"#ffffff",
}


# Catalogues construits depuis ciel_donnees.py : ciel profond OpenNGC (Messier, Caldwell, NGC, IC)
# et étoiles du Bright Star Catalogue, positions J2000 vérifiées contre SIMBAD et PyEphem.
# Les anciennes listes saisies à la main avaient des positions fausses de plusieurs degrés
# (jusqu'à 92° pour IC 10) et un catalogue Caldwell qui ne correspondait pas au vrai.
try:
    import ciel_donnees as CIEL
except ImportError:              # fichier absent : catalogues vides, carte réduite
    CIEL = None

TYPE_NAMES["Sol"] = "Système solaire"; TYPE_COLORS["Sol"] = "#ffd27a"

def _dso_obj(d, label, short):
    desig, ra, dec, mag, typ, maj, mnr, pa, m, c, fr, en = d
    return {"id": desig, "key": desig, "ra": ra, "dec": dec, "mag": mag, "type": typ, "name": label,
            "short": short, "size": (maj, mnr, pa), "alias": f"{label} {desig} {en}".lower()}

def _build_catalogs():
    if CIEL is None:
        return {"Messier": [], "Caldwell": [], "NGC": [], "IC": [], "Étoiles": []}
    mess, cald, ngc, ic = [], [], [], []
    for d in CIEL.DSO:
        desig, m, c, fr = d[0], d[8], d[9], d[10]
        catalog_name = "" if desig.startswith(("C0", "C1")) else desig     # objets Caldwell hors NGC/IC
        if m:
            mess.append((m, _dso_obj(d, f"M{m}" + (f" {fr}" if fr else f" ({catalog_name})" if catalog_name else ""), f"M{m}")))
        if c:
            cald.append((c, _dso_obj(d, " ".join(x for x in (f"C{c}", catalog_name, fr) if x), f"C{c}")))
        if desig.startswith(("NGC ", "IC ")):
            label = desig + (f" (M{m})" if m else "") + (f" {fr}" if fr else "")
            (ngc if desig.startswith("NGC") else ic).append((int(re.sub(r"\D.*", "", desig.split()[1]) or 0),
                                                             _dso_obj(d, label, f"M{m}" if m else desig)))
    stars = []
    for ra, dec, mag, bv, nm, bay in CIEL.STARS:
        if nm and mag <= 3.5:
            label = f"{nm} ({bay})" if bay else nm
            stars.append({"id": nm, "key": nm, "ra": ra, "dec": dec, "mag": mag, "type": "★", "name": label,
                          "short": nm, "size": (0, 0, None), "alias": f"{nm} {bay}".lower()})
    srt = lambda l: [o for _, o in sorted(l, key=lambda x: x[0])]
    return {"Messier": srt(mess), "Caldwell": srt(cald), "NGC": srt(ngc), "IC": srt(ic), "Étoiles": stars}

ALL_CATALOGS = _build_catalogs()
SOLAR_SYSTEM_CAT = "Système solaire"     # calculé à la demande (positions du moment)

def fmt_mag(m):
    return "—" if m is None else f"{m:.1f}"


# ════════════════════════════════════════════════════════════════
#  SECTION 3 : ASTRONOMIE
# ════════════════════════════════════════════════════════════════
DEG = math.pi / 180
RAD = 180 / math.pi


class Astro:
    @staticmethod
    def julian_day(dt: datetime) -> float:
        y, m, d = dt.year, dt.month, dt.day
        ut = dt.hour + dt.minute/60 + dt.second/3600
        if m <= 2: y -= 1; m += 12
        a = y // 100; b = 2 - a + a//4
        return int(365.25*(y+4716)) + int(30.6001*(m+1)) + d + b - 1524.5 + ut/24

    @staticmethod
    def lst(dt: datetime, lon_deg: float) -> float:
        jd = Astro.julian_day(dt); d = jd - 2451545.0
        gmst = (18.697374558 + 24.06570982441908 * d) % 24
        lst = (gmst + lon_deg/15.0) % 24
        if lst < 0: lst += 24
        return lst

    @staticmethod
    def precession_matrix(jd):
        """Précession IAU 1976 (Lieske) : vecteur J2000 -> vecteur rapporté à l'équinoxe de la date.
        Les catalogues sont en J2000 ; la monture, comme LX200/OnStep, travaille en coordonnées
        de la date. Sans précession, l'écart atteint 0,37° en 2026."""
        T = (jd - 2451545.0) / 36525.0
        zeta = (2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) / 3600 * DEG
        z    = (2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) / 3600 * DEG
        th   = (2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) / 3600 * DEG
        cz_, sz_, cz, sz, ct, st = math.cos(zeta), math.sin(zeta), math.cos(z), math.sin(z), math.cos(th), math.sin(th)
        return ((cz_ * cz * ct - sz_ * sz, -sz_ * cz * ct - cz_ * sz, -st * cz),
                (cz_ * sz * ct + sz_ * cz, -sz_ * sz * ct + cz_ * cz, -st * sz),
                (cz_ * st, -sz_ * st, ct))

    @staticmethod
    def precess(ra_h, dec_d, jd=None, inverse=False):
        """J2000 -> équinoxe de la date (ou l'inverse si inverse=True). jd par défaut : maintenant."""
        if jd is None:
            jd = Astro.julian_day(datetime.now(timezone.utc))
        P = Astro.precession_matrix(jd)
        a = ra_h * 15 * DEG; d = dec_d * DEG
        v = (math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d))
        if inverse:
            w = [P[0][i] * v[0] + P[1][i] * v[1] + P[2][i] * v[2] for i in range(3)]
        else:
            w = [P[i][0] * v[0] + P[i][1] * v[1] + P[i][2] * v[2] for i in range(3)]
        return (math.atan2(w[1], w[0]) * RAD / 15) % 24, math.asin(max(-1.0, min(1.0, w[2]))) * RAD

    @staticmethod
    def eq_to_horiz(ra_h, dec_d, lst_h, lat_d):
        ha  = ((lst_h - ra_h)*15)*DEG; dec = dec_d*DEG; lat = lat_d*DEG
        s = math.sin(dec)*math.sin(lat) + math.cos(dec)*math.cos(lat)*math.cos(ha)
        s = max(-1.0, min(1.0, s)); alt = math.asin(s); ca = math.cos(alt)
        if abs(ca) > 1e-10:
            c = (math.sin(dec)-math.sin(alt)*math.sin(lat))/(ca*math.cos(lat))
            az = math.acos(max(-1.0, min(1.0, c)))
        else: az = 0.0
        if math.sin(ha) > 0: az = 2*math.pi - az
        return az*RAD, alt*RAD

    @staticmethod
    def horiz_to_eq(az_d, alt_d, lst_h, lat_d):
        az = az_d*DEG; alt = alt_d*DEG; lat = lat_d*DEG
        s = math.sin(alt)*math.sin(lat) + math.cos(alt)*math.cos(lat)*math.cos(az)
        s = max(-1.0, min(1.0, s)); dec = math.asin(s); cd = math.cos(dec)
        if abs(cd) > 1e-10:
            c = (math.sin(alt)-math.sin(dec)*math.sin(lat))/(cd*math.cos(lat))
            ha = math.acos(max(-1.0, min(1.0, c)))
        else: ha = 0.0
        if math.sin(az) > 0: ha = 2*math.pi - ha
        ra = (lst_h - ha*RAD/15.0) % 24
        if ra < 0: ra += 24
        return ra, dec*RAD

    @staticmethod
    def parallactic_angle(ra_h, dec_d, lst_h, lat_d):
        ha = ((lst_h - ra_h)*15)*DEG; dec = dec_d*DEG; lat = lat_d*DEG
        return math.atan2(math.sin(ha)*math.cos(lat),
                          math.sin(lat)*math.cos(dec) - math.cos(lat)*math.sin(dec)*math.cos(ha))*RAD

    @staticmethod
    def fmt_ra(ra_h):
        h = int(ra_h); rm = (ra_h-h)*60; m = int(rm); s = int((rm-m)*60)
        return f"{h:02d}h{m:02d}m{s:02d}s"

    @staticmethod
    def fmt_ra_lx(ra_h):
        h = int(ra_h); rm = (ra_h-h)*60; m = int(rm); s = int((rm-m)*60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def fmt_dec(dec_d):
        sg = '+' if dec_d >= 0 else '-'; ad = abs(dec_d)
        d = int(ad); am = (ad-d)*60; m = int(am); s = int((am-m)*60)
        return f"{sg}{d:02d}°{m:02d}'{s:02d}\""

    @staticmethod
    def fmt_dec_lx(dec_d):
        sg = '+' if dec_d >= 0 else '-'; ad = abs(dec_d)
        d = int(ad); am = (ad-d)*60; m = int(am); s = int((am-m)*60)
        return f"{sg}{d:02d}*{m:02d}:{s:02d}"

    @staticmethod
    def angular_dist(ra1_h, dec1_d, ra2_h, dec2_d):
        r1 = (ra1_h * 15) * DEG
        r2 = (ra2_h * 15) * DEG
        d1 = dec1_d * DEG
        d2 = dec2_d * DEG
        cos_d = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1-r2)
        cos_d = max(-1.0, min(1.0, cos_d))
        return math.acos(cos_d) * RAD

    @staticmethod
    def parse_ra(s):
        try:
            p = s.replace('h',':').replace('m',':').replace('s','').split(':')
            return int(p[0]) + int(p[1])/60 + float(p[2])/3600
        except: return 0.0

    @staticmethod
    def parse_dec(s):
        try:
            neg = s[0]=='-'
            t = s[1:].replace('°',':').replace("'",':').replace('"','').replace('*',':').split(':')
            v = int(t[0]) + int(t[1])/60 + (float(t[2]) if len(t)>2 else 0)/3600
            return -v if neg else v
        except: return 0.0


# ════════════════════════════════════════════════════════════════
#  SECTION 4 : COMMUNICATION MONTURE LX200
# ════════════════════════════════════════════════════════════════
class MountState:
    def __init__(self):
        self.ra_h=0.0; self.dec_d=0.0; self.az_d=0.0; self.alt_d=2.0
        self.lst_h=0.0; self.tracking=False; self.slewing=False
        self.limit_hit=False; self.speed_dps=2.0; self.connected=False
        self.sim_mode=False
        # Champs OnStep
        self.firmware_name=""    # ex: "On-Step GotoMega"
        self.firmware_ver=""     # ex: "9.1"
        self.is_onstep=False     # True si firmware OnStep détecté
        self.parked=False        # OnStep :GU# flag P
        self.park_in_progress=False  # OnStep :GU# flag I
        self.at_home=False       # OnStep :GU# flag H
        self.guiding=False       # OnStep :GU# flag G
        self.time_set=True       # v5.1 : flag 'F' absent => OK
        self.rate_index=2        # OnStep :Rn# (0-9)


class Mount:
    def __init__(self, cfg: Settings, on_state=None):
        self.cfg = cfg; self.on_state = on_state
        self.state = MountState()
        self._ser = None; self._lock = threading.Lock()
        self._poll_th = None; self._running = False
        # Simulation interne
        self._saz=0.0; self._salt=2.0; self._staz=0.0; self._stalt=2.0
        self._spark=None   # position de parking definie par :hQ (az, alt)
        self._sslewing=False; self._stracking=False; self._sspd=2.0
        self._stra=0.0; self._stdec=0.0

    # ── Connexion ─────────────────────────────────────────────
    def connect(self, port, baud=9600, sim=False):
        self.state.sim_mode = sim
        if sim:
            self.state.connected = True; self._start_poll(); return True
        if not HAS_SERIAL:
            log.error("pyserial non installé — pip3 install pyserial"); return False
        try:
            self._ser = serial.Serial(port, baud,
                timeout=self.cfg.get("mount_timeout",0.5), write_timeout=1.0)
            time.sleep(2)
            self.state.connected = True
            
            # Mécanique de la monture (type, rapports, pas, micro-pas) : c'est le
            # configurateur qui la règle. On la lit au lieu de la réécrire : nos
            # propres réglages (AltAz, 750:1 par défaut) écrasaient les siens.
            self.read_mechanics()
            
            # Vitesse par défaut
            try:
                spd = self.cfg.get("slew_speed_default", 2.0)
                self.set_speed(spd)
            except Exception as e:
                log.warning(f"Impossible d'envoyer la vitesse initiale : {e}")
                
            time.sleep(0.1)

            # Détection automatique du firmware
            try: self.detect_firmware()
            except: pass
            self._start_poll(); return True
        except Exception as e:
            log.error(f"Connexion : {e}"); return False

    def read_mechanics(self):
        """Recopie dans les réglages la mécanique enregistrée dans la monture."""
        gm = self._cmd(":GM")
        if gm not in ("AltAz", "ForkEq", "GermanEq"):
            return   # firmware autre que GotoAndrivet : :GGa/:GSp n'y ont pas ce sens
        self.cfg.set("mount_type", gm)
        for cmd, key, conv in ((":GGa", "gear_ratio_az", float), (":GGe", "gear_ratio_alt", float),
                               (":GSp", "steps_per_rev_motor", int), (":GSm", "microstep", int)):
            try: self.cfg.set(key, conv(float(self._cmd(cmd))))
            except ValueError: pass
        self.cfg.save()
        log.info(f"Mécanique lue : {gm}, rapports {self.cfg.get('gear_ratio_az')}/{self.cfg.get('gear_ratio_alt')}, "
                 f"{self.cfg.get('steps_per_rev_motor')} pas x {self.cfg.get('microstep')}")

    def disconnect(self):
        self._running = False
        if self._poll_th: self._poll_th.join(timeout=3)
        if self._ser and self._ser.is_open: self._ser.close()
        self.state.connected = False

    @staticmethod
    def list_ports():
        if not HAS_SERIAL: return []
        return [p.device for p in serial.tools.list_ports.comports()]

    # ── LX200 bas niveau ──────────────────────────────────────
    def _cmd(self, cmd, reply=True):
        if self.state.sim_mode: return self._sim(cmd)
        if not self._ser or not self._ser.is_open: return ""
        with self._lock:
            try:
                self._ser.reset_input_buffer()
                self._ser.write((cmd+"#").encode())
                if not reply: return ""
                if cmd.startswith((":Sr", ":Sd", ":St", ":Sg", ":SG", ":SL", ":Bv", ":BV", ":U", ":Rg", ":hQ")):
                    return self._ser.read(1).decode(errors='replace').strip()
                r=b""; dl=time.time()+self.cfg.get("mount_timeout",0.5)
                while time.time()<dl:
                    c=self._ser.read(1)
                    if c==b'#': break
                    r+=c
                return r.decode(errors='replace').strip()
            except Exception as e:
                log.error(f"Série: {e}"); return ""

    # ── Simulation LX200 ─────────────────────────────────────
    def _sim(self, cmd):
        lat=self.cfg.get("latitude",45.764); lon=self.cfg.get("longitude",4.836)
        now=datetime.now(timezone.utc); lst=Astro.lst(now,lon)
        if cmd==":GVP": return "On-Step GoTo Mega#"
        if cmd==":GVN": return "9.1#"
        if cmd==":GU":
            # v5.1 : format OnStep correct pour que detect_firmware reussisse.
            # [n/N][p/P][H][S][G][F]/[A][T/L/S][rate]#
            f = ""
            f += "n" if self._sslewing else "N"
            f += "p"                                   # jamais parke en sim
            f += "/A"
            if self._stracking: f += "T"
            f += "3"                                   # rate par defaut
            return f + "#"
        if cmd==":GR":
            ra,_=Astro.horiz_to_eq(self._saz,self._salt,lst,lat)
            return Astro.fmt_ra_lx(ra)+"#"
        if cmd==":GD":
            _,dec=Astro.horiz_to_eq(self._saz,self._salt,lst,lat)
            return Astro.fmt_dec_lx(dec)+"#"
        if cmd==":GS": return Astro.fmt_ra_lx(lst)+"#"
        # v5.1 : :GBE remplace :GX (format GotoMega prive, identique)
        if cmd==":GBE":
            return (f"{int(self._stracking)},{int(self._sslewing)},0,"
                    f"{int(self._sspd*10)},{self._salt:.2f},{self._saz:.2f},"
                    f"0,1#")
        if cmd==":Bv":  return f"{int(self._sspd*10)}#"
        if cmd.startswith(":Sr"):
            self._stra=Astro.parse_ra(cmd[3:]); return "1"
        if cmd.startswith(":Sd"):
            self._stdec=Astro.parse_dec(cmd[3:]); return "1"
        if cmd==":MS":
            az,alt=Astro.eq_to_horiz(self._stra,self._stdec,lst,lat)
            amin=self.cfg.get("alt_min_deg",2.0)
            if alt<amin: return f"1Objet sous horizon Alt={alt:.1f}#"
            self._staz=az; self._stalt=max(amin,min(self.cfg.get("alt_max_deg",88),alt))
            self._sslewing=True; self._stracking=True; return "0"
        if cmd==":Q":
            self._sslewing=False
            return ""    # :Q ne coupe PAS le tracking (conforme spec OnStep v9.0+)
        # v5.1 : :Te/:Td remplace :T+/:T-
        if cmd==":Te": self._stracking=True;  return "1"
        if cmd==":Td": self._stracking=False; return "1"
        if cmd==":TQ": self._stracking=True;  return "1"
        # v5.1 : :BV remplace :SV
        if cmd.startswith(":BV"):
            try:
                self._sspd = max(0.5, min(25.0, int(cmd[3:].strip())/10.0))
            except: pass
            return "1"
        if cmd==":CM":
            now2=datetime.now(timezone.utc); lst2=Astro.lst(now2,lon)
            az,alt=Astro.eq_to_horiz(self._stra,self._stdec,lst2,lat)
            self._saz=az; self._salt=alt; return "Synced#"
        if cmd==":hP":
            if self._spark: self._staz, self._stalt = self._spark
            else: self._staz=0.0; self._stalt=self.cfg.get("alt_min_deg",2.0)
            self._sslewing=True; self._stracking=False
            return "1"
        if cmd==":hR": self._stracking=True; return "1"
        if cmd==":hQ": self._spark=(self._saz,self._salt); return "1"
        if cmd.startswith(":R") and len(cmd)==3: return ""
        if cmd.startswith(":Mg"): return ""
        # v5.1 : :SC / :SL passent timeSet a True (dans ce sim, on l'ignore)
        if cmd.startswith(":SC") or cmd.startswith(":SL"): return "1"
        if cmd.startswith(":SG") or cmd.startswith(":St") or cmd.startswith(":Sg"): return "1"
        return ""

    def _sim_step(self, dt):
        lat=self.cfg.get("latitude",45.764); lon=self.cfg.get("longitude",4.836)
        spd=self._sspd
        if self._sslewing:
            def adiff(a,b): return (b-a+180)%360-180
            daz=adiff(self._saz,self._staz); dalt=self._stalt-self._salt; step=spd*dt
            if abs(daz)<=step and abs(dalt)<=step:
                self._saz=self._staz; self._salt=self._stalt; self._sslewing=False
            else:
                if abs(daz)>step: self._saz+=math.copysign(step,daz)
                else: self._saz=self._staz
                if abs(dalt)>step: self._salt+=math.copysign(step,dalt)
                else: self._salt=self._stalt
        elif self._stracking:
            now=datetime.now(timezone.utc); lst=Astro.lst(now,lon)
            taz,talt=Astro.eq_to_horiz(self._stra,self._stdec,lst,lat)
            self._saz=taz
            self._salt=max(self.cfg.get("alt_min_deg",2),min(self.cfg.get("alt_max_deg",88),talt))

    # ── Poll thread ───────────────────────────────────────────
    def _start_poll(self):
        self._running=True
        self._poll_th=threading.Thread(target=self._poll_loop,daemon=True,name="mount-poll")
        self._poll_th.start()

    def _poll_loop(self):
        lon=self.cfg.get("longitude",4.836); last_t=time.time()
        while self._running:
            now_t=time.time(); dt=now_t-last_t; last_t=now_t
            if self.state.sim_mode: self._sim_step(dt)
            now=datetime.now(timezone.utc); lst=Astro.lst(now,lon)
            self.state.lst_h=lst

            # v5.1 : :GBE# remplace :GX# (qui collisionnait avec OnStep :GXnn#).
            # Format Mega v9.0+ : tracking,slewing,limit,rate*10,alt,az,parked,aligned#
            gbe=self._cmd(":GBE")
            if gbe and ',' in gbe:
                p=gbe.rstrip('#').split(',')
                if len(p)>=6:
                    try:
                        self.state.tracking =bool(int(p[0]))
                        self.state.slewing  =bool(int(p[1]))
                        self.state.limit_hit=bool(int(p[2]))
                        self.state.speed_dps=int(p[3])/10.0
                        self.state.alt_d    =float(p[4])
                        self.state.az_d     =float(p[5])
                        if len(p) >= 8:
                            self.state.parked = bool(int(p[6]))
                            # p[7] = aligned/synced (déjà couvert par :GU)
                    except: pass

            # OnStep : :GU# pour les flags étendus (parked, home, guiding, time-not-set...)
            if self.state.is_onstep:
                gu=self._cmd(":GU")
                if gu:
                    f=gu.rstrip('#')
                    # 'P'/'G' ne sont plus ambigus : les lettres de type de
                    # monture sont passées à 'E'/'K'/'A' côté firmware. Avant,
                    # une ForkEq (lettre 'P') paraissait parquée en permanence
                    # et une GermanEq (lettre 'G') paraissait guider sans fin.
                    self.state.parked            = 'P' in f
                    self.state.park_in_progress  = 'I' in f
                    self.state.at_home           = 'H' in f
                    self.state.guiding           = 'G' in f
                    # Heure non réglée : '?' depuis le firmware v9.3. C'était
                    # 'F', que le driver INDI lisait comme "Parking Failed" et
                    # qui corrompait son code d'erreur en fin de chaîne.
                    self.state.time_set          = '?' not in f
                    if 'N' in f: self.state.slewing = False

            gr=self._cmd(":GR"); gd=self._cmd(":GD")
            if gr: self.state.ra_h =Astro.parse_ra(gr.rstrip('#'))
            if gd: self.state.dec_d=Astro.parse_dec(gd.rstrip('#'))
            self.state.connected=True
            if self.on_state:
                try: self.on_state(self.state)
                except Exception as e: log.error(f"Callback: {e}")
            time.sleep(0.8)

    # ── API publique ──────────────────────────────────────────
    def goto(self, ra, dec):
        """GoTo vers (ra, dec) J2000 : la monture reçoit les coordonnées de la date (LX200/OnStep)."""
        # v5.1 : interdit le goto si l'heure n'a pas été réglée côté Mega
        if not self.state.time_set and not self.state.sim_mode:
            log.warning("Goto refusé : régler date/heure d'abord (:SC + :SL)")
            return "5Time not set"
        ra, dec = Astro.precess(ra, dec)
        self._cmd(f":Sr{Astro.fmt_ra_lx(ra)}", reply=True)
        self._cmd(f":Sd{Astro.fmt_dec_lx(dec)}", reply=True)
        return self._cmd(":MS").rstrip('#')

    def stop(self):          self._cmd(":Q",  reply=False)

    # v5.1 : :Te/:Td (vrai enable/disable) au lieu de :T+/:T- (rate adjust seulement)
    def set_tracking(self, on):
        self._cmd(":Te" if on else ":Td", reply=True)

    # v5.1 : :BV (GotoMega Velocity, namespace privé) au lieu de :SV (non géré par Mega)
    # Le Mega clamp en runtime à [0.5, 25.0] deg/s par sécurité.
    def set_speed(self, dps):
        n = max(5, min(250, int(dps * 10)))
        self._cmd(f":BV {n}", reply=True)

    def sync(self, ra, dec):
        """Synchronisation sur (ra, dec) J2000, envoyés en coordonnées de la date."""
        # v5.1 : interdit la sync si l'heure n'a pas été réglée
        if not self.state.time_set and not self.state.sim_mode:
            log.warning("Sync refusée : régler date/heure d'abord")
            return ""
        ra, dec = Astro.precess(ra, dec)
        self._cmd(f":Sr{Astro.fmt_ra_lx(ra)}", reply=False)
        self._cmd(f":Sd{Astro.fmt_dec_lx(dec)}", reply=False)
        return self._cmd(":CM").rstrip('#')

    def parking(self):
        # v5.1 : :hP toujours (le fallback :PK n'est plus géré par aucune
        # version du Mega depuis v9.0, c'était du code mort)
        return self._cmd(":hP", reply=True)

    def unpark(self):
        return self._cmd(":hR", reply=True)

    def set_park_position(self):
        return self._cmd(":hQ", reply=True)

    def set_datetime_now(self, utc_offset=None):
        """v5.1 : envoie :SC + :SL + :SG pour régler le Mega à l'heure courante.
        À appeler au moins une fois après chaque connexion, sinon le flag 'F'
        empêche les goto."""
        now = datetime.now()
        if utc_offset is None:
            utc_offset = -time.timezone / 3600.0
            if time.daylight and time.localtime().tm_isdst:
                utc_offset = -time.altzone / 3600.0
        self._cmd(f":SC{now.month:02d}/{now.day:02d}/{now.year%100:02d}", reply=True)
        self._cmd(f":SL{now.hour:02d}:{now.minute:02d}:{now.second:02d}", reply=True)
        sign = '+' if utc_offset >= 0 else '-'
        # :SG (LX200) : heures à ajouter à l'heure locale pour obtenir l'UTC, donc UTC+2 -> :SG-02
        self._cmd(f":SG{'-' if utc_offset >= 0 else '+'}{int(abs(utc_offset)):02d}", reply=True)
        log.info(f"Date/heure envoyées : {now.strftime('%Y-%m-%d %H:%M:%S')} "
                 f"(UTC{sign}{int(abs(utc_offset))})")
        return True

    def lst_offset_min(self, lon):
        """Écart (minutes) entre l'heure sidérale de la monture (:GS) et celle du PC, ou None.
        Un écart révèle une heure, un fuseau ou une longitude mal compris par le firmware
        (par exemple un firmware antérieur au fuseau :SG en convention LX200 : 4 h l'été)."""
        r = self._cmd(":GS").rstrip("#")
        try:
            h, m, sec = (int(x) for x in r.split(":"))
        except ValueError:
            return None
        d = (h + m / 60 + sec / 3600 - Astro.lst(datetime.now(timezone.utc), lon)) % 24
        return (d - 24 if d > 12 else d) * 60

    def set_location(self, lat, lon):
        """Envoie la latitude et la longitude à l'Arduino Mega."""
        # Latitude
        sg_lat = '+' if lat >= 0 else '-'
        ad_lat = abs(lat)
        d_lat = int(ad_lat); am_lat = (ad_lat-d_lat)*60; m_lat = int(am_lat); s_lat = int((am_lat-m_lat)*60)
        self._cmd(f":St{sg_lat}{d_lat:02d}*{m_lat:02d}:{s_lat:02d}", reply=True)
        
        # Longitude : LX200 = Ouest positif (le firmware fait siteLon = -val), nos réglages sont en Est positif
        sg_lon = '-' if lon >= 0 else '+'
        ad_lon = abs(lon)
        d_lon = int(ad_lon); am_lon = (ad_lon-d_lon)*60; m_lon = int(am_lon); s_lon = int((am_lon-m_lon)*60)
        self._cmd(f":Sg{sg_lon}{d_lon:03d}*{m_lon:02d}:{s_lon:02d}", reply=True)
        
        log.info(f"Coordonnées site envoyées : Lat {lat:+.4f}, Lon {lon:+.4f} (Est positif)")
        return True

    def set_rate(self, n):
        """Régler la vitesse OnStep R0-R9 (n=0..9). En plus, ajuste la vitesse
        slew runtime via :BV pour que le Mega prenne aussi en compte le réglage."""
        n = max(0, min(9, int(n)))
        self._cmd(f":R{n}", reply=False)
        # Calcul vitesse équivalente pour :BV (clamp [0.5, 25.0] côté Mega)
        sidereal = 360.0 / 86164.09
        rates = [0.25, 0.5, 1, 2, 4, 8, 16, 24, 40, 1437]
        max_s = self.cfg.get("slew_speed_max", 6.0)
        spd = sidereal * rates[n] if n < 9 else max_s
        self.set_speed(min(max_s, max(0.5, spd)))
        self.state.rate_index = n

    def pulse_guide(self, direction, ms):
        """Guidage impulsion OnStep :Mgdnnnn# (d=n/s/e/w, ms=20-16399)."""
        if direction not in 'nsew': return
        ms = max(20, min(16399, int(ms)))
        self._cmd(f":Mg{direction}{ms:04d}", reply=False)

    def guide_rate(self):
        """Vitesse de guidage en × sidéral (:GX90#), 0,5 si la monture ne la donne pas."""
        try: return float(self._cmd(":GX90"))
        except ValueError: return 0.5

    def set_guide_rate(self, r):
        """:Rg<x.xx># (extension GotoAndrivet), entre 0,1 et 1 × sidéral."""
        return self._cmd(f":Rg{max(0.1, min(1.0, r)):.2f}")

    def detect_firmware(self):
        """Détecte le firmware (OnStep ou LX200 générique) à la connexion.

        Critère : le format :GU# d'OnStep porte toujours le flag de parking,
        'p' (non parqué) ou 'P' (parqué). Un firmware non-OnStep répond
        généralement '0#' ou rien.
        """
        name = self._cmd(":GVP")
        ver  = self._cmd(":GVN")
        if name:
            self.state.firmware_name = name.rstrip('#').strip()
            self.state.firmware_ver  = ver.rstrip('#').strip() if ver else ""

        gu = self._cmd(":GU")
        if gu:
            f = gu.rstrip('#')
            # Le flag de parking est le seul toujours émis : 'N' (pas de GOTO)
            # et 'n' (suivi coupé) sont tous deux absents pendant un GOTO en
            # suivi. L'ancien test exigeait [Nn] puis [Pp] en positions 0 et 1,
            # ce qui échouait dès que le suivi était coupé — cas normal à la
            # connexion : la chaîne commence alors par "nNp", donc f[1] valait
            # 'N' et non 'p'.
            self.state.is_onstep = any(c in f for c in 'pP')
        else:
            self.state.is_onstep = False

        # Le nom du firmware est l'indicateur le plus fiable. Le test cherchait
        # "on-step" dans le nom mis en minuscules, ce qui ne pouvait pas
        # matcher "OnStep" (sans tiret) — la valeur que renvoie :GVP#.
        if "onstep" in self.state.firmware_name.lower().replace('-', ''):
            self.state.is_onstep = True

        log.info(f"Firmware: {self.state.firmware_name} v{self.state.firmware_ver} "
                 f"({'OnStep' if self.state.is_onstep else 'LX200 générique'})")
        return self.state.is_onstep

    def get_firmware_label(self):
        """Retourne le label à afficher dans l'UI."""
        if not self.state.connected:
            return "Déconnecté"
        if self.state.sim_mode:
            return "Simulation"
        if self.state.firmware_name:
            proto = "OnStep" if self.state.is_onstep else "LX200"
            return f"{self.state.firmware_name} v{self.state.firmware_ver} [{proto}]"
        return "Connecté"

    def parallactic_angle(self):
        lat=self.cfg.get("latitude",45.764)
        return Astro.parallactic_angle(
            self.state.ra_h,self.state.dec_d,self.state.lst_h,lat)


# ════════════════════════════════════════════════════════════════
#  SECTION 5 : DÉROTATEUR ZWO
# ════════════════════════════════════════════════════════════════
class Derotator:
    """Dérotateur de champ. Types : « integre » (axe DEROT de la monture, commandes :XDe/:XDp/:XDa,
    sans retour de position, en AltAz seulement), « zwo » (ZWO CAA par son SDK), « serie »
    (protocole SETPOS sur un port série) et « sim » (simulation)."""
    KINDS = ("integre", "zwo", "serie", "sim")

    def __init__(self, cfg, on_state=None):
        self.cfg=cfg; self.on_state=on_state
        self.angle=0.0; self.target=0.0; self.pa=0.0
        self.moving=False; self.enabled=False; self.connected=False
        self.offset=0.0; self._mount=None
        self._ser=None; self._th=None; self._running=False
        self._rev=False; self._force=False
        self._zwo_caa=None
        self.kind=cfg.get("derot_type","integre")

    def set_mount(self, m): self._mount=m

    def set_offset(self, o): self.offset=o; self._force=True

    def compensating(self):
        """La rotation de champ n'existe qu'en AltAz. En équatoriale le champ ne tourne pas : le dérotateur
        n'est plus qu'un rotateur de cadrage, commandé à la main ou par le module photo."""
        return self.enabled and self.cfg.get("mount_type", "AltAz") == "AltAz"

    def _mount_ok(self):
        return self._mount is not None and self._mount.state.connected

    def connect(self, kind, port="", baud=9600):
        """Connecte le dérotateur choisi. Renvoie (réussi, message d'erreur)."""
        self.disconnect()
        self.kind=kind; self._rev=self.cfg.get("derot_reversed",False)
        if kind == "integre":
            if not self._mount_ok():
                return False, "need_mount"
            ppd = float(self.cfg.get("derot_ppd", 100.0))
            self._mount._cmd(f":XDp{ppd:.4f}", reply=False)     # pas par degré de l'axe DEROT
            self._mount._cmd(":XDe1", reply=False)               # axe actif : il suit :XDa (compensation en AltAz seulement)
        elif kind == "zwo":
            try:
                import zwocaa
                self._zwo_caa = zwocaa.CAA(0); self._zwo_caa.open()
                self.angle = self._zwo_caa.get_degree()
            except Exception as e:
                self._zwo_caa = None
                return False, str(e)
        elif kind == "serie":
            if not HAS_SERIAL: return False, "pyserial"
            try:
                self._ser=serial.Serial(port,baud,timeout=1); time.sleep(1)
            except Exception as e:
                return False, str(e)
        self.connected=True; self._running=True
        self._th=threading.Thread(target=self._run,daemon=True,name="derot")
        self._th.start(); return True, ""

    def disconnect(self):
        self._running=False
        if self._th: self._th.join(timeout=2); self._th=None
        if self._ser and self._ser.is_open: self._ser.close()
        self._ser=None
        if self._zwo_caa:
            try: self._zwo_caa.close()
            except Exception: pass
            self._zwo_caa=None
        if self.connected and self.kind == "integre" and self._mount_ok():
            self._mount._cmd(":XDe0", reply=False)
        self.connected=False

    def _send(self, cmd):
        if self.kind != "serie" or not self._ser: return
        try: self._ser.write(cmd.encode())
        except Exception: pass

    def _apply(self, a):
        """Envoie l'angle cible au dérotateur."""
        if self.kind == "zwo" and self._zwo_caa:
            try: self._zwo_caa.move_to(a)
            except Exception: pass
        elif self.kind == "integre" and self._mount_ok():
            self._mount._cmd(f":XDa{a:.2f}", reply=False)
            self.angle = a                     # pas de retour de position : on affiche l'angle commandé
        elif self.kind == "serie":
            self._send(f"SETPOS:{a:.2f}\r\n")

    def _run(self):
        last_pa=None
        while self._running:
            if self._mount_ok():
                self.pa=self._mount.parallactic_angle()
                if self.compensating():
                    if self._rev: tgt = (self.pa + self.offset) % 360
                    else: tgt = (-(self.pa + self.offset)) % 360
                    if self._force or last_pa is None or abs(self.pa-last_pa)>0.1:
                        self._force=False
                        self.target=tgt; self.moving=True
                        self._apply(tgt)
                        last_pa=self.pa
            if self._zwo_caa:
                try:
                    self.angle = self._zwo_caa.get_degree()
                    self.moving = self._zwo_caa.is_moving()
                except Exception: pass
            elif self.kind == "sim" and self.moving:
                d=(self.target-self.angle+180)%360-180
                if abs(d)<0.2: self.angle=self.target; self.moving=False
                else: self.angle+=math.copysign(min(2.0,abs(d)),d); self.angle%=360
            elif self.kind == "integre":
                self.moving = False
            if self.on_state:
                try: self.on_state(self)
                except Exception: pass
            time.sleep(0.5)

    def enable(self, on):
        self.enabled=on
        if not on: self.moving=False

    def goto_angle(self, a):
        self.target=a%360; self.moving=True
        self._apply(a%360)

    def stop(self):
        self.moving=False
        if self._zwo_caa:
            try: self._zwo_caa.stop()
            except Exception: pass
        self._send("STOP\r\n")

    def home(self): self.goto_angle(0)

    def rotate_by(self, d):
        """Tourne l'angle commandé de d degrés : par le décalage pendant la compensation, sinon directement."""
        if self.compensating():
            self.offset += d if self._rev else -d
            self._force = True
        else:
            self.goto_angle(self.target + d)

    def nudge(self, d): self.rotate_by(d)


class Focuser:
    """Focuseur. Types : « integre » (axe FOCUS de la monture, commandes :XFe/:XF+/:XF-/:XFQ,
    déplacement continu à deux vitesses, sans retour de position) et « eaf » (ZWO EAF par son
    SDK, position absolue en pas)."""
    KINDS = ("integre", "eaf")

    def __init__(self, cfg, on_state=None):
        self.cfg=cfg; self.on_state=on_state
        self.kind=cfg.get("focus_type","integre")
        self.connected=False; self.moving=False
        self.position=None; self.max_step=None; self.temp=None
        self._mount=None; self._eaf=None; self._th=None; self._running=False

    def set_mount(self, m): self._mount=m

    def _mount_ok(self):
        return self._mount is not None and self._mount.state.connected

    def connect(self, kind):
        """Connecte le focuseur choisi. Renvoie (réussi, message d'erreur)."""
        self.disconnect()
        self.kind=kind
        if kind == "integre":
            if not self._mount_ok():
                return False, "need_mount"
            self._mount._cmd(":XFe1", reply=False)               # le firmware ignore :XF+/:XF- sans :XFe1
        else:
            try:
                import zwoeaf
                self._eaf = zwoeaf.EAF(0); self._eaf.open()
                self.max_step = self._eaf.max_step()
            except Exception as e:
                self._eaf = None
                return False, str(e)
        self.connected=True; self._running=True
        self._th=threading.Thread(target=self._run,daemon=True,name="focus")
        self._th.start(); return True, ""

    def disconnect(self):
        if self.connected: self.stop()
        self._running=False
        if self._th: self._th.join(timeout=2); self._th=None
        if self._eaf:
            try: self._eaf.close()
            except Exception: pass
            self._eaf=None
        self.connected=False; self.position=None; self.temp=None

    def start(self, direction, fast=False):
        """Mouvement continu tant que le bouton reste enfoncé : +1 sortir, -1 rentrer."""
        if not self.connected: return
        if self.kind == "integre":
            if not self._mount_ok(): return
            self._mount._cmd(":XFf" if fast else ":XFs", reply=False)
            self._mount._cmd(":XF+" if direction > 0 else ":XF-", reply=False)
        elif self._eaf:
            try: self._eaf.move_to(self.max_step if direction > 0 else 0)   # vers la butée, arrêté au relâchement
            except Exception: return
        self.moving=True

    def stop(self):
        if self.kind == "integre":
            if self._mount_ok(): self._mount._cmd(":XFQ", reply=False)
        elif self._eaf:
            try: self._eaf.stop()
            except Exception: pass
        self.moving=False

    def move_by(self, steps):
        """Déplacement relatif en pas (EAF seulement : le focuseur intégré n'a pas de position)."""
        if self._eaf and self.position is not None:
            self.move_to(self.position + steps)

    def move_to(self, pos):
        if not self._eaf: return
        pos = max(0, min(int(pos), self.max_step or int(pos)))
        try: self._eaf.move_to(pos); self.moving=True
        except Exception: pass

    def _run(self):
        while self._running:
            if self._eaf:
                try:
                    self.position = self._eaf.position()
                    self.moving = self._eaf.is_moving()
                    self.temp = self._eaf.temperature()
                except Exception: pass
            if self.on_state:
                try: self.on_state(self)
                except Exception: pass
            time.sleep(0.5)


# ════════════════════════════════════════════════════════════════
#  SECTION 6 : CARTE DU CIEL — Style Stellarium
# ════════════════════════════════════════════════════════════════
# Repère horizontal : x = Est, y = Nord, z = Zénith ; azimut compté depuis le Nord vers l'Est.
# Les positions des catalogues sont en J2000 : elles passent par la précession (équinoxe de
# la date) puis par la matrice horizontale du lieu et de l'heure sidérale, comme dans la monture.

def _vec(ra_h, dec_d):
    a = ra_h * 15 * DEG; d = dec_d * DEG; c = math.cos(d)
    return (c * math.cos(a), c * math.sin(a), math.sin(d))

def _mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))

def _bv_color(bv, dim=1.0):
    """Couleur d'une étoile d'après son indice B-V (bleu-blanc -> orangé), assombrie de dim."""
    pts = ((-0.4, (155, 176, 255)), (0.0, (202, 216, 255)), (0.4, (248, 247, 255)), (0.7, (255, 242, 228)),
           (1.0, (255, 226, 190)), (1.4, (255, 204, 150)), (2.0, (255, 170, 110)))
    bv = max(-0.4, min(2.0, bv))
    for (b0, c0), (b1, c1) in zip(pts, pts[1:]):
        if bv <= b1:
            f = (bv - b0) / (b1 - b0)
            return "#%02x%02x%02x" % tuple(int((c0[i] + (c1[i] - c0[i]) * f) * dim) for i in range(3))
    return "#ffaa6e"

# Points du plan galactique (b = 0 et bandes à ±4°, ±8°) en vecteurs J2000, pour la Voie lactée.
_GAL_TO_EQ = ((-0.0548755604, 0.4941094279, -0.8676661490),
              (-0.8734370902, -0.4448296300, -0.1980763734),
              (-0.4838350155, 0.7469822445, 0.4559837762))
def _galactic_band(b_deg):
    out = []
    for l_deg in range(0, 362, 3):
        l = l_deg * DEG; b = b_deg * DEG
        g = (math.cos(b) * math.cos(l), math.cos(b) * math.sin(l), math.sin(b))
        out.append(tuple(sum(_GAL_TO_EQ[i][k] * g[k] for k in range(3)) for i in range(3)))
    return out
_MILKY_WAY = [(b / 2, _galactic_band(b / 2)) for b in sorted(range(-18, 19, 3), key=lambda b: -abs(b))]

# Étoiles et constellations en vecteurs J2000, calculés une fois
if CIEL is not None:
    _STARS = [(_vec(ra, dec), mag, bv, nm, bay, ra, dec) for ra, dec, mag, bv, nm, bay in CIEL.STARS]
    _CONSTS = []
    for abbr, latin, fr, en, lines in CIEL.CONSTELLATIONS:
        vl = [[_vec(ra, dec) for ra, dec in line] for line in lines]
        sx = sum(v[0] for l in vl for v in l); sy = sum(v[1] for l in vl for v in l); sz = sum(v[2] for l in vl for v in l)
        n = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
        _CONSTS.append((abbr, fr, en, vl, (sx / n, sy / n, sz / n)))
else:
    _STARS, _CONSTS = [], []

# Système solaire (si PyEphem est installé)
try:
    import ephem as _ephem
except ImportError:
    _ephem = None
_PLANETS = (("Soleil", "Sun", "Sun", "#ffd84a", 7), ("Lune", "Moon", "Moon", "#e8e8dc", 6),
            ("Mercure", "Mercury", "Mercury", "#c9b8a0", 3), ("Vénus", "Venus", "Venus", "#fff4d0", 4),
            ("Mars", "Mars", "Mars", "#ff8a5c", 3.5), ("Jupiter", "Jupiter", "Jupiter", "#ffe2b0", 4.5),
            ("Saturne", "Saturn", "Saturn", "#f2dca0", 4), ("Uranus", "Uranus", "Uranus", "#b8f0f0", 3),
            ("Neptune", "Neptune", "Neptune", "#a8c0ff", 3))

def solar_system(lat, lon, when=None):
    """Positions du Soleil, de la Lune et des planètes : liste de dict (ra/dec J2000, ra/dec de la date)."""
    if _ephem is None:
        return []
    obs = _ephem.Observer(); obs.lat = str(lat); obs.lon = str(lon); obs.pressure = 0; obs.elevation = 0
    obs.date = when or datetime.now(timezone.utc)
    out = []
    for fr, en, cls, col, r in _PLANETS:
        b = getattr(_ephem, cls)(); b.compute(obs)
        ra_d = float(b.ra) * 12 / math.pi; dec_d = math.degrees(float(b.dec))     # apparente topocentrique, de la date
        ra2, dec2 = Astro.precess(ra_d, dec_d, Astro.julian_day(obs.date.datetime()), inverse=True)
        out.append({"id": en, "key": en, "name": fr, "name_en": en, "type": "Sol", "mag": round(float(b.mag), 1),
                    "ra": ra2, "dec": dec2, "ra_date": ra_d, "dec_date": dec_d, "color": col, "r": r,
                    "alias": f"{fr} {en}".lower(), "size": (0, 0, None)})
    return out


class SkyMap(tk.Canvas):
    """Carte du ciel style Stellarium — projection stéréographique, vue de l'intérieur de la sphère."""

    LAYERS = ("milky_way", "eq_grid", "az_grid", "const_lines", "const_names", "star_names", "dso", "planets")

    def __init__(self, parent, cfg: Settings, **kw):
        kw.setdefault("bg", "#03050c")
        super().__init__(parent, highlightthickness=0, takefocus=1, **kw)
        self.cfg = cfg
        # Vue : centre en Az/Alt, FOV = demi-angle en degrés
        self._fov   = min(90.0, max(1.0, cfg.get("skymap_fov_deg", 60.0)))
        self._caz   = 180.0   # regarder vers le Sud par défaut
        self._calt  = 40.0
        self._mag   = cfg.get("skymap_mag_limit", 6.5)
        # Monture
        self._saz=0.0; self._salt=2.0; self._sra=0.0; self._sdec=0.0
        self._tracking=False; self._slewing=False; self._connected=False
        self._cam_fov=None        # (largeur °, hauteur °, rotation ° vers l'Est) du module photo
        self._lst=0.0
        self._lat=cfg.get("latitude",45.764); self._lon=cfg.get("longitude",4.836)
        # Données
        self._dso: List[Dict] = []
        self._selected: Optional[Dict] = None
        self._planets: List[Dict] = []; self._planets_t = 0.0
        self._hits = []           # (px, py, rayon, objet) des objets dessinés, pour le survol et le clic
        self._fast = False        # rendu allégé pendant un glisser
        self._last_full = 0.0
        self._pending = None
        # Callbacks
        self.on_obj_click: Optional[Callable] = None
        self.on_sky_click: Optional[Callable] = None
        # Drag
        self._drag0=None; self._dc0=None
        # Bind
        self.bind("<Configure>",      lambda e: self.redraw_later())
        self.bind("<MouseWheel>",     self._wheel)
        self.bind("<Button-4>",       self._wheel)
        self.bind("<Button-5>",       self._wheel)
        self.bind("<ButtonPress-1>",  self._press)
        self.bind("<B1-Motion>",      self._drag)
        self.bind("<ButtonRelease-1>",self._release)
        self.bind("<Motion>",         self._motion)
        self.bind("<Leave>",          lambda e: self.delete("tip"))
        for key, d in (("<Left>", (-1, 0)), ("<Right>", (1, 0)), ("<Up>", (0, 1)), ("<Down>", (0, -1))):
            self.bind(key, lambda e, d=d: self.pan(*d))
        for key in ("<plus>", "<KP_Add>", "<equal>"):
            self.bind(key, lambda e: self.zoom(0.8))
        for key in ("<minus>", "<KP_Subtract>"):
            self.bind(key, lambda e: self.zoom(1.25))

    # ──────────────────────────────────────────────────────────
    # Réglages d'affichage (persistants)
    # ──────────────────────────────────────────────────────────
    def layer(self, name):
        return bool(self.cfg.get("skymap_show_" + name, name != "eq_grid"))

    def set_layer(self, name, on):
        self.cfg.set("skymap_show_" + name, bool(on)); self.redraw()

    def _lang(self):
        return self.cfg.get("language", "fr")

    # ──────────────────────────────────────────────────────────
    # PROJECTION STÉRÉOGRAPHIQUE (comme Stellarium)
    # ──────────────────────────────────────────────────────────
    def _setup_view(self):
        """Matrices et constantes de la vue courante (une fois par dessin)."""
        W = self.winfo_width() or 800; H = self.winfo_height() or 600
        self._W, self._H = W, H; self._cx, self._cy = W / 2, H / 2
        self._R = min(W, H) / 2 * 0.93
        self._K = self._R / math.tan(math.radians(self._fov) / 2)
        a = math.radians(self._caz); e = math.radians(self._calt)
        c = (math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))
        r = (c[1], -c[0], 0.0); n = math.hypot(r[0], r[1])
        r = (r[0] / n, r[1] / n, 0.0) if n > 1e-9 else (-1.0, 0.0, 0.0)   # droite de l'écran (Ouest face au Sud)
        u = (r[1] * c[2] - r[2] * c[1], r[2] * c[0] - r[0] * c[2], r[0] * c[1] - r[1] * c[0])
        self._c, self._r, self._u = c, r, u
        # Limite angulaire : coins du canevas (au plus 150° du centre)
        rmax = math.hypot(W, H) / 2 + 20
        self._cos_max = math.cos(min(math.radians(150), 2 * math.atan(rmax / self._K)))
        # Équatorial de la date -> horizontal, et J2000 -> horizontal (précession incluse)
        lst = self._lst * 15 * DEG; lat = self._lat * DEG
        sl, cl, sp, cp = math.sin(lst), math.cos(lst), math.sin(lat), math.cos(lat)
        self._H_mat = ((-sl, cl, 0.0), (-sp * cl, -sp * sl, cp), (cp * cl, cp * sl, sp))
        self._jd = Astro.julian_day(datetime.now(timezone.utc))
        self._M = _mat_mul(self._H_mat, Astro.precession_matrix(self._jd))
        self._pxdeg = self._K * DEG / 2      # pixels par degré au centre

    def _hz(self, v, m=None):
        m = m or self._M
        return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
                m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
                m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])

    def _pv(self, s):
        """Vecteur horizontal unitaire -> (px, py), ou None hors champ."""
        c = self._c
        dot = s[0] * c[0] + s[1] * c[1] + s[2] * c[2]
        if dot < self._cos_max:
            return None
        k = self._K / (1.0 + dot)
        r, u = self._r, self._u
        return (self._cx + k * (s[0] * r[0] + s[1] * r[1] + s[2] * r[2]),
                self._cy - k * (s[0] * u[0] + s[1] * u[1] + s[2] * u[2]))

    def _proj(self, az, alt):
        """(az,alt) degrés → (px,py) canvas. None si hors champ."""
        if not hasattr(self, "_c"): self._setup_view()
        a = math.radians(az); e = math.radians(alt)
        return self._pv((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))

    def _unproj(self, px, py):
        """(px,py) canvas → (az,alt) degrés ou (None,None)."""
        if not hasattr(self, "_c"): self._setup_view()
        x = (px - self._cx) / self._K; y = -(py - self._cy) / self._K
        q = x * x + y * y
        c, r, u = self._c, self._r, self._u
        s = [((1 - q) * c[i] + 2 * x * r[i] + 2 * y * u[i]) / (1 + q) for i in range(3)]
        if s[0] * c[0] + s[1] * c[1] + s[2] * c[2] < self._cos_max:
            return None, None
        return math.degrees(math.atan2(s[0], s[1])) % 360, math.degrees(math.asin(max(-1, min(1, s[2]))))

    def radec_to_screen(self, ra_h, dec_d):
        """Position J2000 -> écran (et altitude), ou (None, alt)."""
        s = self._hz(_vec(ra_h, dec_d))
        return self._pv(s), math.degrees(math.asin(max(-1, min(1, s[2]))))

    # ──────────────────────────────────────────────────────────
    # DESSIN
    # ──────────────────────────────────────────────────────────
    def redraw(self):
        try:
            self._draw()
        except Exception:
            log.exception("Carte du ciel")

    def redraw_later(self, delay=30):
        """Regroupe les demandes de dessin rapprochées (glisser, redimensionnement)."""
        if self._pending is None:
            def run():
                self._pending = None; self.redraw()
            self._pending = self.after(delay, run)

    def refresh(self, follow=False):
        """Appelé à chaque interrogation de la monture : dessin complet toutes les 5 s (le ciel
        tourne de 1,25' en 5 s), sinon seulement le réticule et l'horloge."""
        if follow and self._connected:
            self._caz, self._calt = self._saz % 360, max(1.0, min(89.0, self._salt))
            self.redraw(); return
        if time.time() - self._last_full > 5.0:
            self.redraw(); return
        try:
            self.delete("scope"); self._draw_reticule()
            self.itemconfigure("clock", text=self._clock_text())
        except Exception:
            log.exception("Carte du ciel")

    def _mag_limit(self):
        """Magnitude limite des étoiles : réglage de l'utilisateur, plafonné selon le champ."""
        f = self._fov
        dyn = 4.6 if f >= 80 else 5.2 if f >= 50 else 5.8 if f >= 30 else 6.5
        if self._fast: dyn -= 1.2
        return min(self._mag, dyn)

    def _draw(self):
        self.delete("all")
        self._setup_view()
        self._last_full = time.time()
        self._hits = []
        lang = self._lang()

        self._draw_ground()
        if self.layer("milky_way"): self._draw_milky_way()
        if self.layer("eq_grid"):   self._draw_eq_grid()
        if self.layer("az_grid"):   self._draw_az_grid()
        if self.layer("const_lines") or self.layer("const_names"): self._draw_constellations(lang)
        self._draw_stars()
        if self.layer("dso"):       self._draw_dso()
        if self.layer("planets"):   self._draw_planets(lang)
        self._draw_horizon(lang)
        self._draw_selection()
        self._draw_reticule()
        self._draw_hud(lang)

    def _polyline(self, vecs, m, fill, width, horizon_cut=True, **kw):
        """Polyligne coupée hors champ et (option) sous l'horizon."""
        pts = []
        for v in vecs:
            s = self._hz(v, m)
            p = self._pv(s) if (not horizon_cut or s[2] > -0.005) else None
            if p:
                pts.extend(p)
            else:
                if len(pts) >= 4: self.create_line(pts, fill=fill, width=width, **kw)
                pts = []
        if len(pts) >= 4: self.create_line(pts, fill=fill, width=width, **kw)

    def _draw_ground(self):
        """Sol. En projection stéréographique, l'horizon est un cercle à l'écran : le sol est
        l'intérieur ou l'extérieur de ce cercle. Le centre de l'écran est toujours dans le ciel
        (la vue ne descend pas sous 1° d'altitude) : c'est lui qui désigne le côté du ciel."""
        c, r, u = self._c, self._r, self._u
        lim = 15000.0                       # coordonnées X11 sur 16 bits
        pts = []
        for az in range(0, 360):
            a = math.radians(az); sv = (math.sin(a), math.cos(a), 0.0)
            dot = sv[0] * c[0] + sv[1] * c[1]
            if dot < -0.995: continue       # voisinage du point opposé au centre de la vue
            k = self._K / (1.0 + dot)
            pts.append((max(-lim, min(lim, self._cx + k * (sv[0] * r[0] + sv[1] * r[1]))),
                        max(-lim, min(lim, self._cy - k * (sv[0] * u[0] + sv[1] * u[1] + sv[2] * u[2])))))
        if len(pts) < 3: return
        zx, zy = self._cx, self._cy
        inside = False                       # centre de l'écran (ciel) à l'intérieur du cercle de l'horizon ?
        j = len(pts) - 1
        for i in range(len(pts)):
            (xi, yi), (xj, yj) = pts[i], pts[j]
            if (yi > zy) != (yj > zy) and zx < (xj - xi) * (zy - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        flat = [v for p in pts for v in p]
        ground, sky = "#0b150d", self.cget("bg")
        if inside:
            self.create_rectangle(-10, -10, self._W + 10, self._H + 10, fill=ground, outline="")
            self.create_polygon(flat, fill=sky, outline="")
        else:
            self.create_polygon(flat, fill=ground, outline="")

    def _draw_milky_way(self):
        """Bande de ±9° autour du plan galactique, plus claire au centre."""
        w = max(3, 3.4 * self._pxdeg)
        for b, band in _MILKY_WAY:
            f = 1 - abs(b) / 10
            col = "#%02x%02x%02x" % (int(8 + 12 * f), int(12 + 16 * f), int(22 + 26 * f))
            self._polyline(band, self._M, col, w, smooth=True, capstyle="round")

    def _draw_eq_grid(self):
        """Grille équatoriale de la date."""
        step = 10 if self._fov < 25 else 30
        for dec_d in range(-80, 90, step):
            self._polyline([_vec(h / 4, dec_d) for h in range(0, 97)], self._H_mat,
                           "#1f3a5c" if dec_d == 0 else "#122438", 1.2 if dec_d == 0 else 0.6, smooth=True)
        for ra_h in range(0, 24, 1 if self._fov < 25 else 2):
            self._polyline([_vec(ra_h, d) for d in range(-85, 86, 5)], self._H_mat, "#122438", 0.6, smooth=True)

    def _line_azalt(self, pairs, **kw):
        """Ligne en (az, alt), coupée aux points hors champ."""
        pts = []
        for az, alt in pairs:
            p = self._proj(az, alt)
            if p:
                pts.extend(p)
            else:
                if len(pts) >= 4: self.create_line(pts, **kw)
                pts = []
        if len(pts) >= 4: self.create_line(pts, **kw)

    def _draw_az_grid(self):
        step = 10 if self._fov < 25 else 15
        for alt_d in range(step, 90, step):
            self._line_azalt([(az, alt_d) for az in range(0, 362, 3)], fill="#14301a", width=0.6, smooth=True)
        for az_d in range(0, 360, 30):
            self._line_azalt([(az_d, alt) for alt in range(0, 91, 3)], fill="#11281a", width=0.6)

    def _draw_constellations(self, lang):
        lines, names = self.layer("const_lines"), self.layer("const_names") and not self._fast
        fs = 9 if self._fov > 40 else 10
        for abbr, fr, en, vl, centre in _CONSTS:
            if lines:
                for line in vl:
                    self._polyline(line, self._M, "#26476a", 1.0)
            if names:
                s = self._hz(centre)
                p = self._pv(s) if s[2] > 0.02 else None
                if p:
                    self.create_text(p[0], p[1], text=(fr if lang == "fr" else en).upper(),
                                     fill="#36597e", font=("Helvetica", fs))

    def _draw_stars(self):
        lim = self._mag_limit()
        names = self.layer("star_names") and not self._fast
        name_lim = 1.6 if self._fov >= 70 else 2.6 if self._fov >= 35 else 3.6 if self._fov >= 15 else 9
        bayer = names and self._fov < 12
        M, c, cmax = self._M, self._c, self._cos_max
        m00, m01, m02, m10, m11, m12, m20, m21, m22 = (M[0][0], M[0][1], M[0][2], M[1][0], M[1][1], M[1][2],
                                                       M[2][0], M[2][1], M[2][2])
        zoom = 1.0 + max(0.0, (40 - self._fov) / 60)
        for v, mag, bv, nm, bay, ra, dec in _STARS:          # triées par magnitude
            if mag > lim: break
            x, y, z = v
            sz = m20 * x + m21 * y + m22 * z
            if sz < -0.002: continue
            s = (m00 * x + m01 * y + m02 * z, m10 * x + m11 * y + m12 * z, sz)
            p = self._pv(s)
            if not p: continue
            r = max(0.7, (lim + 1.0 - mag) * 0.62 * zoom)
            dim = max(0.45, min(1.0, 1.15 - (mag - 1.0) / (lim + 1.0) * 0.7))
            col = _bv_color(bv, dim)
            px, py = p
            if mag < 1.0:
                self.create_oval(px - r * 1.9, py - r * 1.9, px + r * 1.9, py + r * 1.9, fill=_bv_color(bv, 0.22), outline="")
            self.create_oval(px - r, py - r, px + r, py + r, fill=col, outline="")
            if nm or mag < 4.5:
                obj = {"id": nm or bay, "key": nm or bay, "name": nm or bay, "type": "★", "mag": mag, "ra": ra, "dec": dec,
                       "alias": f"{nm} {bay}".lower(), "size": (0, 0, None), "bayer": bay}
                self._hits.append((px, py, max(r, 4), obj))
            if names and ((nm and mag < name_lim) or (bayer and bay and mag < 5.0)):
                self.create_text(px + r + 3, py - 1, text=nm or bay, anchor="w",
                                 fill="#7f9fc4" if nm else "#56708f", font=("Helvetica", 9))

    def _draw_dso(self):
        if self._fast: return
        f = self._fov
        lim = 7.5 if f >= 70 else 8.5 if f >= 45 else 10.0 if f >= 20 else 99
        for obj in self._dso:
            t = obj["type"]
            if t in ("★", "Sol"): continue
            mag = obj["mag"]
            short = obj.get("short", "")
            famous = short[:1] in ("M", "C")
            if not famous and ((mag is None and f >= 30) or (mag is not None and mag > lim)):
                continue
            s = self._hz(_vec(obj["ra"], obj["dec"]))
            if s[2] < -0.01: continue
            p = self._pv(s)
            if not p: continue
            px, py = p
            col = TYPE_COLORS.get(t, "#88aacc")
            maj = (obj.get("size") or (0, 0, None))[0] or 0
            sz = max(4.0, min(10.0, 12 - (mag if mag is not None else 10)), maj / 60 * self._pxdeg / 2)
            if t == "Gal":
                mn = (obj.get("size") or (0, 0, None))[1] or maj
                h = max(2.0, sz * (mn / maj if maj else 0.5))
                self.create_oval(px - sz, py - h, px + sz, py + h, outline=col, width=1)
                self.create_oval(px - 1, py - 1, px + 1, py + 1, fill=col, outline="")
            elif t == "OC":
                self.create_oval(px - sz, py - sz, px + sz, py + sz, outline=col, width=1, dash=(3, 2))
            elif t == "GC":
                self.create_oval(px - sz, py - sz, px + sz, py + sz, outline=col, width=1.4)
                self.create_line(px - sz, py, px + sz, py, fill=col, width=0.8)
                self.create_line(px, py - sz, px, py + sz, fill=col, width=0.8)
            elif t == "PN":
                self.create_oval(px - sz / 2, py - sz / 2, px + sz / 2, py + sz / 2, outline=col, width=1.4)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    self.create_line(px + dx * sz / 2, py + dy * sz / 2, px + dx * sz, py + dy * sz, fill=col)
            elif t in ("Neb", "SNR"):
                self.create_rectangle(px - sz, py - sz, px + sz, py + sz, outline=col, width=1)
            else:
                self.create_oval(px - 3, py - 3, px + 3, py + 3, outline=col, width=1)
            self._hits.append((px, py, max(sz, 6), obj))
            if short[:1] == "M" or (famous and f < 70) or f < 30:
                self.create_text(px + sz + 3, py, text=obj.get("short") or obj["name"].split()[0],
                                 fill=col, font=("Helvetica", 8), anchor="w")

    def _draw_planets(self, lang):
        if time.time() - self._planets_t > 60:          # positions recalculées chaque minute
            self._planets = solar_system(self._lat, self._lon); self._planets_t = time.time()
        for b in self._planets:
            s = self._hz(_vec(b["ra_date"], b["dec_date"]), self._H_mat)
            if s[2] < -0.01: continue
            p = self._pv(s)
            if not p: continue
            px, py = p; r = b["r"]
            if b["id"] == "Sun":
                self.create_oval(px - r * 2.2, py - r * 2.2, px + r * 2.2, py + r * 2.2, fill="#3a3010", outline="")
            self.create_oval(px - r, py - r, px + r, py + r, fill=b["color"], outline="")
            self.create_text(px + r + 4, py, text=b["name"] if lang == "fr" else b["name_en"], anchor="w",
                             fill="#ffd27a", font=("Helvetica", 10, "bold"))
            self._hits.append((px, py, max(r, 6), b))

    def _draw_horizon(self, lang):
        self._line_azalt([(az, 0.0) for az in range(0, 362, 2)], fill="#3d7a46", width=1.6, smooth=True)
        names = (("N", "N"), ("NE", "NE"), ("E", "E"), ("SE", "SE"), ("S", "S"), ("SO", "SW"), ("O", "W"), ("NO", "NW"))
        for i, (fr, en) in enumerate(names):
            p = self._proj(i * 45, -2.5)
            if p:
                main = i % 2 == 0
                self.create_text(p[0], p[1], text=fr if lang == "fr" else en,
                                 fill="#e05a4a" if i == 0 else "#7fb0e0" if main else "#4f7aa8",
                                 font=("Helvetica", 14 if main else 10, "bold"))

    def _draw_selection(self):
        o = self._selected
        if not o: return
        if o.get("type") == "Sol" and "ra_date" in o:
            s = self._hz(_vec(o["ra_date"], o["dec_date"]), self._H_mat)
        else:
            s = self._hz(_vec(o["ra"], o["dec"]))
        p = self._pv(s)
        if not p: return
        px, py = p
        for r, w in ((16, 2), (21, 1)):
            self.create_oval(px - r, py - r, px + r, py + r, outline="#ffd400", width=w)
        self.create_text(px, py - 26, text=o["name"], fill="#ffd400", font=("Helvetica", 10, "bold"))

    def _draw_camera_fov(self):
        """Champ de la caméra du module photo, centré sur l'AD/Déc de la monture (coordonnées de la date),
        orienté par la rotation de la dernière astrométrie ; le petit trait marque le haut de l'image."""
        if not self._cam_fov: return
        w, h, rot = self._cam_fov
        a = self._sra * 15 * DEG; d = self._sdec * DEG
        c = _vec(self._sra, self._sdec)
        e = (-math.sin(a), math.cos(a), 0.0)
        n = (-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d))
        t = rot * DEG
        up = [math.sin(t) * e[i] + math.cos(t) * n[i] for i in range(3)]
        right = [-math.cos(t) * e[i] + math.sin(t) * n[i] for i in range(3)]   # Est à gauche, Nord en haut si rot = 0
        hw, hh = math.tan(w / 2 * DEG), math.tan(h / 2 * DEG)

        def pt(x, y):   # (x, y) dans [-1, 1] : bords de l'image (projection gnomonique inverse)
            v = [c[i] + x * hw * right[i] + y * hh * up[i] for i in range(3)]
            k = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
            return self._pv(self._hz((v[0] / k, v[1] / k, v[2] / k), self._H_mat))

        corners = ((-1, 1), (1, 1), (1, -1), (-1, -1), (-1, 1))
        pts = []
        for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
            pts += [pt(x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8) for i in range(8)]
        if any(p is None for p in pts): return
        col = "#d77dff"; kw = {"tags": ("scope",)}
        flat = [v for p in pts + pts[:1] for v in p]
        self.create_line(*flat, fill=col, width=1.4, **kw)
        top, tip = pt(0, 1), pt(0, 1.18)
        if top and tip: self.create_line(*top, *tip, fill=col, width=2, **kw)
        x0, y0 = pts[0]
        if math.hypot(pts[8][0] - x0, pts[8][1] - y0) < 70: return     # cadre plus petit que le réticule
        fr = self._lang() == "fr"
        size = f"{w * 60:.0f}′ × {h * 60:.0f}′" if w < 2 else f"{w:.1f}° × {h:.1f}°"
        self.create_text(x0, y0 - 4, text=("Caméra  " if fr else "Camera  ") + size, fill=col,
                         font=("Helvetica", 9), anchor="sw", **kw)

    def _draw_reticule(self):
        """Réticule du télescope."""
        if not self._connected: return
        self._draw_camera_fov()
        p = self._proj(self._saz, self._salt)
        if not p: return
        px, py = p
        col = "#ff7a1a" if self._slewing else ("#2ee86a" if self._tracking else "#c0c8d0")
        R1, R2, gap = 26, 6, 9
        kw = {"tags": ("scope",)}
        self.create_oval(px-R1, py-R1, px+R1, py+R1, outline=col, width=1.6, **kw)
        self.create_oval(px-R2, py-R2, px+R2, py+R2, outline=col, width=1, **kw)
        for x1, y1, x2, y2 in ((px-R1-6, py, px-gap, py), (px+gap, py, px+R1+6, py),
                               (px, py-R1-6, px, py-gap), (px, py+gap, px, py+R1+6)):
            self.create_line(x1, y1, x2, y2, fill=col, width=1.6, **kw)
        fr = self._lang() == "fr"
        lbl = ("GOTO…" if self._slewing else "SUIVI" if self._tracking else "ARRÊT") if fr else \
              ("SLEWING…" if self._slewing else "TRACKING" if self._tracking else "STOPPED")
        self.create_text(px+R1+8, py-9, text=("Télescope  " if fr else "Telescope  ") + lbl,
                         fill=col, font=("Helvetica", 10, "bold"), anchor="w", **kw)
        self.create_text(px+R1+8, py+8, text=f"Az {self._saz:.1f}°  Alt {self._salt:.1f}°",
                         fill=col, font=("Helvetica", 9), anchor="w", **kw)

    def _clock_text(self):
        now = datetime.now()
        return f"{now:%d/%m/%Y  %H:%M:%S}   TSL {Astro.fmt_ra_lx(self._lst)}"

    def _draw_hud(self, lang):
        W, H = self._W, self._H
        fr = lang == "fr"
        site = self.cfg.get("site_name", "Obs.")
        ns = "N" if self._lat >= 0 else "S"; ew = "E" if self._lon >= 0 else ("O" if fr else "W")
        self.create_rectangle(4, 4, 330, 48, fill="#050a14", outline="#16304c")
        self.create_text(10, 10, text=f"{site}   {abs(self._lat):.3f}° {ns}  {abs(self._lon):.3f}° {ew}",
                         fill="#8fb3d9", font=("Helvetica", 10, "bold"), anchor="nw")
        self.create_text(10, 28, text=self._clock_text(), fill="#6f93b9", font=("Helvetica", 10),
                         anchor="nw", tags=("clock",))
        # Légende
        items = [("Gal", "Galaxie" if fr else "Galaxy"), ("OC", "Amas ouvert" if fr else "Open cluster"),
                 ("GC", "Amas globulaire" if fr else "Globular cluster"), ("PN", "Nébuleuse planétaire" if fr else "Planetary nebula"),
                 ("Neb", "Nébuleuse" if fr else "Nebula")]
        lx, ly = 10, H - 18 * len(items) - 12
        self.create_rectangle(4, ly - 12, 190, H - 6, fill="#050a14", outline="#16304c")
        for i, (t, lbl) in enumerate(items):
            c = TYPE_COLORS.get(t, "#888")
            self.create_oval(lx, ly + i * 18 - 4, lx + 8, ly + i * 18 + 4, outline=c)
            self.create_text(lx + 14, ly + i * 18, text=lbl, fill="#7f98b4", font=("Helvetica", 9), anchor="w")
        champ = f"Champ {self._fov * 2:.0f}°" if fr else f"Field {self._fov * 2:.0f}°"
        self.create_text(W - 10, H - 10, text=f"{champ}   ·   mag ≤ {self._mag_limit():.1f}",
                         fill="#6f8aa8", font=("Helvetica", 9), anchor="se")

    # ──────────────────────────────────────────────────────────
    # INTERACTIONS
    # ──────────────────────────────────────────────────────────
    def zoom(self, factor):
        self._fov = max(1.0, min(90.0, self._fov * factor))
        self.cfg.set("skymap_fov_deg", self._fov)
        self.redraw()

    def pan(self, dx, dy):
        step = self._fov / 3
        self._caz = (self._caz + dx * step / max(0.2, math.cos(math.radians(self._calt)))) % 360
        self._calt = max(1.0, min(89.0, self._calt + dy * step))
        self.redraw()

    def _wheel(self, e):
        zoom_in = (e.num == 4 or e.delta > 0)
        self.zoom(0.82 if zoom_in else 1.22)

    def _press(self, e):
        self.focus_set()
        self._drag0 = (e.x, e.y)
        self._dc0   = (self._caz, self._calt)

    def _drag(self, e):
        if not self._drag0: return
        dx = e.x - self._drag0[0]; dy = e.y - self._drag0[1]
        if abs(dx) + abs(dy) < 4 and not self._fast: return
        sc = self._fov * 2 / max(self._R * 2, 1)        # degrés par pixel
        self._caz  = (self._dc0[0] - dx * sc / max(0.2, math.cos(math.radians(self._dc0[1])))) % 360
        self._calt = max(1.0, min(89.0, self._dc0[1] + dy * sc))
        self._fast = True
        self.redraw_later(25)

    def _release(self, e):
        if not self._drag0: return
        moved = self._fast
        self._drag0 = None; self._fast = False
        if moved:
            self.redraw()
        else:
            self._on_click(e)

    def _hit(self, x, y):
        best, bd = None, 1e9
        for px, py, r, obj in self._hits:
            d = math.hypot(px - x, py - y)
            if d < r + 4 and d < bd:
                best, bd = obj, d
        return best

    def _on_click(self, e):
        """Clic sur un objet (étoile, planète, ciel profond) ou dans le ciel."""
        obj = self._hit(e.x, e.y)
        if obj and self.on_obj_click:
            self.on_obj_click(obj)
        elif self.on_sky_click:
            az, alt = self._unproj(e.x, e.y)
            if az is not None:
                ra, dec = Astro.horiz_to_eq(az, alt, self._lst, self._lat)
                ra, dec = Astro.precess(ra, dec, self._jd, inverse=True)
                self.on_sky_click(az, alt, ra, dec)

    def _motion(self, e):
        """Info-bulle au survol d'un objet."""
        self.delete("tip")
        if self._drag0: return
        obj = self._hit(e.x, e.y)
        if not obj: return
        fr = self._lang() == "fr"
        nm = TYPE_NAMES_BILINGUAL["fr" if fr else "en"].get(obj["type"], obj["type"])
        mag = "" if obj.get("mag") is None else f"   mag {obj['mag']:.1f}"
        extra = f"   {obj['bayer']}" if obj.get("bayer") and obj.get("bayer") != obj["name"] else ""
        t = self.create_text(e.x + 16, e.y - 14, text=f" {obj['name']}{extra}{mag}   {nm} ",
                             fill="#e8f4ff", font=("Helvetica", 10), anchor="w", tags=("tip",))
        bb = self.bbox(t)
        if bb:
            bg = self.create_rectangle(bb[0] - 3, bb[1] - 2, bb[2] + 3, bb[3] + 2, fill="#0b1a2c",
                                       outline="#2f5f8f", tags=("tip",))
            self.tag_lower(bg, t)

    # ──────────────────────────────────────────────────────────
    # API publique
    # ──────────────────────────────────────────────────────────
    def update_mount(self, az, alt, ra, dec, tracking, slewing, lst=None, connected=True):
        self._saz=az; self._salt=alt; self._sra=ra; self._sdec=dec
        self._tracking=tracking; self._slewing=slewing; self._connected=connected
        if lst is not None: self._lst=lst

    def set_objects(self, lst):  self._dso=lst;  self.redraw()
    def set_mag(self, m):        self._mag=m;    self.redraw()
    def set_selected(self, obj): self._selected=obj; self.redraw()
    def set_camera_fov(self, fov): self._cam_fov=fov; self.redraw()
    def center_radec(self):
        """AD/Déc J2000 du centre de la carte."""
        if not hasattr(self, "_c"): self._setup_view()
        c = self._c; m = self._M      # horizontal = M · J2000, M orthogonale : J2000 = Mᵀ · horizontal
        v = [m[0][i] * c[0] + m[1][i] * c[1] + m[2][i] * c[2] for i in range(3)]
        return (math.atan2(v[1], v[0]) * RAD / 15) % 24, math.asin(max(-1.0, min(1.0, v[2]))) * RAD
    def center_on(self, az, alt):
        self._caz=az%360; self._calt=max(1.0,min(89.0,alt)); self.redraw()


# ════════════════════════════════════════════════════════════════
#  SECTION 7 : THÈME SOMBRE
# ════════════════════════════════════════════════════════════════
BG="#0a0f1a"; BG2="#0d1520"; BG3="#101d2a"; BD="#1a2840"
ACC="#0099cc"; AC2="#ff6622"; GRN="#00cc66"; AMB="#ffaa00"; RED="#ff3344"
TXT="#c8dff0"; DIM="#4a6a8a"
FM=("Courier",10); FS=("Courier",9); FL=("Courier",12)

def _theme(root):
    s=ttk.Style(root); s.theme_use("clam")
    base={"background":BG2,"foreground":TXT,"fieldbackground":BG3,
          "selectbackground":ACC,"selectforeground":"white","troughcolor":BG,
          "darkcolor":BD,"lightcolor":BD,"bordercolor":BD,"relief":"flat"}
    for w in("TFrame","TLabel","TButton","TEntry","TCombobox","TSpinbox",
              "TCheckbutton","TLabelframe","TLabelframe.Label","TNotebook",
              "TNotebook.Tab","TScrollbar","TPanedwindow"):
        try: s.configure(w,**base)
        except: pass
    s.configure("TButton",background=BG3,foreground=TXT,padding=4,relief="flat")
    s.map("TButton",background=[("active","#1a3050"),("pressed",ACC)],
          foreground=[("active","white")])
    s.configure("Acc.TButton",background=ACC,foreground="white",padding=6)
    s.map("Acc.TButton",background=[("active","#00bbee"),("pressed","#007799")])
    s.configure("GoTo.TButton",background="#0d3020",foreground=GRN,padding=8,
                font=("Courier",10,"bold"))
    s.map("GoTo.TButton",background=[("active","#1a5040"),("pressed","#004422")])
    s.configure("Stop.TButton",background="#2a0a10",foreground=RED,padding=6)
    s.map("Stop.TButton",background=[("active","#4a1020")])
    s.map("TCombobox",fieldbackground=[("readonly",BG3),("disabled",BG)],foreground=[("readonly",TXT),("disabled",DIM)],
          selectbackground=[("readonly",BG3)],selectforeground=[("readonly",TXT)])
    root.option_add("*TCombobox*Listbox.background",BG3); root.option_add("*TCombobox*Listbox.foreground",TXT)
    root.option_add("*TCombobox*Listbox.selectBackground",ACC); root.option_add("*TCombobox*Listbox.selectForeground","white")
    s.configure("TNotebook.Tab",background=BG3,foreground=DIM,padding=(10,4))
    s.map("TNotebook.Tab",background=[("selected",BG2)],foreground=[("selected",ACC)])
    s.configure("Treeview",background=BG3,foreground=TXT,fieldbackground=BG3,rowheight=22)
    s.configure("Treeview.Heading",background=BG,foreground=DIM)
    s.map("Treeview",background=[("selected","#0d3050")],foreground=[("selected",ACC)])
    root.configure(bg=BG)


TYPE_NAMES_BILINGUAL = {
    "en": {
        "Gal": "Galaxy", "OC": "Open cluster", "GC": "Globular cluster",
        "Neb": "Nebula", "PN": "Planetary nebula", "SNR": "Supernova remnant",
        "DS": "Double star", "Ast": "Asterism", "★": "Star", "Sol": "Solar System",
    },
    "fr": {
        "Gal": "Galaxie", "OC": "Amas ouvert", "GC": "Amas globulaire",
        "Neb": "Nébuleuse", "PN": "Nébuleuse planétaire", "SNR": "Reste supernova",
        "DS": "Étoile double", "Ast": "Astérisme", "★": "Étoile", "Sol": "Système solaire",
    }
}

TRANSLATIONS = {
    "en": {
        # App Title
        "title": "GotoAndrivet — Sky map and GoTo  |  LX200 · OnStep",
        
        # Menu Bar
        "file": "File",
        "settings_menu": "Parameters…",
        "quit": "Quit",
        "mount_menu": "Mount",
        "connect": "Connect…",
        "disconnect": "Disconnect",
        "stop": "Stop",
        "parking": "Park the mount",
        "help": "Help",
        "about": "About",
        "lang_submenu": "Language / Langue",
        
        # Notebook Tab Titles
        "control_tab": " Control ",
        "cat_tab": " Catalog ",
        "goto_tab": " GoTo/Sync ",
        "derot_tab": " Derotator ",
        "focus_tab": " Focuser ",
        "log_tab": " Log LX200 ",
        
        # Connection Frame
        "conn_frame": "Connection",
        "port": "Port :",
        "baud": "Baud :",
        "simulation": "Simulation",
        "btn_connect": "⬡ Connect",
        "btn_disconnect": "Disconnect",
        
        # Position Frame
        "curr_pos_frame": "Current position",
        "pos_ra": "RA",
        "pos_dec": "DEC",
        "pos_az": "Azimuth",
        "pos_alt": "Altitude",
        "pos_lst": "LST",
        
        # Commands Frame
        "commands_frame": "Commands",
        "btn_track_off": "⬡ TRACKING OFF",
        "btn_track_on": "⬡ TRACKING ON",
        "btn_stop": "■ STOP",
        "speed": "Speed :",
        "parking_north": "Park the mount",
        "set_park_here": "Set park position here",
        
        # Mount Status Frame
        "mount_state_frame": "Mount status",
        "ready": "Ready.",
        "state_slewing": "GOTO IN PROGRESS",
        "state_tracking": "Sidereal tracking",
        "state_limit": "⚠ CABLE LIMIT",
        "state_idle": "Idle",
        
        # Catalog Search Frame
        "search_cat_frame": "Catalog search",
        "search": "Search :",
        "type_filter": "Type filter :",
        "mag_limit": "Limit Mag :",
        "cat_filter": "Catalog :",
        "mag_limit_lbl": "Max Mag :",
        "col_name": "Name",
        "col_type": "Type",
        "col_mag": "Mag",
        "col_ra": "RA",
        "col_dec": "Dec",
        "btn_goto_sel": "▶  GOTO selected object",
        
        # Target coordinates Frame
        "tgt_coords_frame": "Target coordinates",
        "ra_label": "RA (hh:mm:ss) :",
        "dec_label": "DEC (dd:mm:ss) :",
        "lbl_tgt_ra_lbl": "RA   hh:mm:ss",
        "lbl_tgt_dec_lbl": "DEC  ±dd:mm:ss",
        "btn_goto": "▶  GOTO",
        
        # Object description
        "obj_desc_frame": "Selected object",
        "info_type": "Type  : ",
        "info_mag": "Mag   : ",
        "info_dbl_click": "Double-click → GoTo",
        "visible": "✓ Visible",
        "below_horizon": "✗ Below horizon",
        
        # Synchronize Frame
        "sync_frame": "Synchronization (star alignment)",
        "sync_desc": "Center a known star in\nthe eyepiece then synchronize.",
        "btn_sync": "⊕ Synchronize on coords above",
        
        # Sky map Frame
        "sky_title": "Wheel: zoom  ·  drag or arrows: move  ·  click: select / GoTo  ·  Esc: STOP",
        "sky_mag_lbl": "Mag :",
        "btn_zenith": "Zenith",
        "btn_scope": "Telescope",
        "btn_photo": "◉ Camera",
        "btn_guide": "◎ Guiding",
        "photo_missing": "The photo module needs numpy and Pillow (installed by install_linux.py):\n{err}",
        
        # Derotator Connection Frame
        "derot_conn_frame": "Derotator",
        "type_lbl": "Type:", "ppd_lbl": "Steps/degree:",
        "kind_integre": "Built-in (mount)", "kind_zwo": "ZWO CAA (USB)", "kind_serie": "Serial (SETPOS)",
        "kind_sim": "Simulation", "kind_eaf": "ZWO EAF (USB)",
        "dev_connected": "Connected", "dev_disconnected": "Not connected",
        "need_mount": "Connect the mount first: this device is driven through it.",
        "ppd_invalid": "Steps per degree: enter a number.",
        "derot_note_integre": "DEROT axis of the mount (mount connected).",
        "derot_eq_note": "Equatorial: the axis is a framing rotator (firmware of 2026-10-21 or later).",
        "derot_eq_rotator": "Equatorial mount: the field does not rotate, nothing to compensate. Set the framing angle with the manual control below.",
        "focus_frame": "Focuser", "focus_pos": "Position:", "focus_temp": "Temperature:",
        "focus_move_frame": "Move", "focus_steps": "Steps:", "focus_goto": "Go to:",
        "focus_hold_integre": "Hold a button to move (◀◀ ▶▶: fast). FOCUS axis of the mount, no position readout.",
        "focus_hold_eaf": "Hold a button to move, or move by steps.",
        "no_feedback": "— (no readout)",
        "btn_connect_derot": "Connect",
        
        # Derotator State Frame
        "derot_state_frame": "Status",
        "phys_angle": "Physical angle :",
        "field_angle": "Field angle :",
        
        # Derotator Compensation Frame
        "derot_comp_frame": "Field rotation compensation",
        "derot_comp_desc": "Compensates for field rotation\nin Alt-Az mount (imaging).",
        "derot_comp_enable": "✓  Enable compensation",
        
        # Derotator Manual Control Frame
        "derot_ctrl_manual": "Manual control",
        "derot_goto": "Goto angle :",
        "derot_offset": "Sensor offset (°) :",
        
        # Log Frame
        "log_frame": "LX200 serial log (USB)",
        "btn_clear": "Clear",
        "btn_save": "Save…",
        
        # Settings Dialog Strings
        "settings_title": "Parameters — GotoMega",
        "tab_site": " Site ",
        "tab_mech": " Mechanics ",
        "tab_conn": " Connection ",
        "set_site_name": "Site name",
        "set_latitude": "Latitude °N",
        "set_longitude": "Longitude °E",
        "set_altitude": "Altitude m",
        "set_auto_gps": "Automatic location via Internet 🛰",
        "set_steps_per_rev": "Motor steps/rev",
        "set_microstep": "Microstepping",
        "set_mount_type": "Mount Type",
        "set_gear_az": "Gear ratio AZ / RA",
        "set_gear_alt": "Gear ratio ALT / DEC",
        "set_slew_speed": "GoTo speed °/s",
        "set_max_speed": "Max speed °/s",
        "set_min_alt": "Min Alt °",
        "set_max_alt": "Max Alt °",
        "set_limit_az": "Az limit °",
        "set_steps_deg": "Steps/deg :",
        "set_port_mount": "Mount port",
        "set_baud_mount": "Mount baudrate",
        "set_port_derot": "Derotator port",
        "set_baud_derot": "Derotator baudrate",
        "set_rev_az": "Reverse Az",
        "set_rev_alt": "Reverse Alt",
        "set_rev_derot": "Reverse derotator",
        "set_btn_save": "✓ Save",
        "set_btn_cancel": "Cancel",
        "set_gps_ok": "Position detected automatically!\n\nLat: {lat:.6f}\nLon: {lon:.6f}",
        "set_gps_err": "Unable to detect position automatically. Check your internet connection.",
        
        # Messageboxes & Alerts
        "msg_conn_err": "Unable to connect to {port}",
        "msg_lst_offset": "The mount's sidereal time differs from the PC's by {off:+.0f} min: GoTos will miss their targets.\n\n"
                          "Flash the mount with the latest firmware (Configurator > Firmware), then reconnect. "
                          "If it persists, check the site longitude and the PC time.",
        "msg_parking_confirm": "Send the mount to its park position?",
        "msg_set_park_confirm": "Save the current position as the park position?",
        "msg_set_park_ok": "Park position saved.",
        "msg_set_park_fail": "Park position refused: mount slewing, on the flipped side of the pier, or not connected.",
        "msg_sync_invalid": "Invalid coordinates.",
        "msg_goto_not_connected": "Mount not connected.",
        "msg_goto_below_horizon": "{name}\nBelow horizon (Alt={alt:.1f}°)",
        "msg_goto_rejected": "Rejected: {resp}",
        "msg_goto_invalid_format": "Invalid format",
        "msg_goto_select_obj": "Select an object.",
        "msg_goto_confirm": "GoTo {name} ?",
        "msg_saved": "Parameters saved.",
        "all_filter": "All",
        "msg_goto_sun": "Pointing at the Sun is refused: without a solar filter it destroys the eye and the equipment.",
        "view_menu": "View",
        "layer_milky_way": "Milky Way", "layer_eq_grid": "Equatorial grid", "layer_az_grid": "Alt-azimuth grid",
        "layer_const_lines": "Constellation lines", "layer_const_names": "Constellation names",
        "layer_star_names": "Star names", "layer_dso": "Deep sky objects", "layer_planets": "Sun, Moon and planets",
        "follow_scope": "Follow the telescope", "follow_short": "Follow", "center_scope": "Center on the telescope",
        "view_zenith": "Look at the zenith", "view_north": "Look north", "view_east": "Look east",
        "view_south": "Look south", "view_west": "Look west",
        "search_lbl": "Search:",
        "shortcuts": "Keyboard shortcuts",
        "shortcuts_text": "Esc: STOP the mount (anywhere)\nArrows: move the map\n+ / -: zoom in / out\n"
                          "Mouse wheel: zoom   ·   drag: move the map\nClick an object: select it, then confirm the GoTo",
        "check_updates": "Check for updates…",
        "update_available": "● Update available (click)",
        "update_btn": "Update", "update_btn_new": "Update available",
        "update_none": "GotoAndrivet is up to date.",
        "update_confirm": "A new version is available on GitHub.\nDownload it and restart?",
        "update_running": "Downloading the update…",
        "update_done": "Update installed. The application will restart.",
        "update_error": "Update failed:\n{err}",
        "about_text": "GotoAndrivet — sky map and GoTo\nVersion {version}\n\nAndrivet Jean-Baptiste · GNU GPL v3\n"
                      "Stars: Yale Bright Star Catalogue (CDS) · Deep sky: OpenNGC (CC BY-SA 4.0)\n"
                      "Constellations: Stellarium (CC BY-SA 4.0)"
    },
    "fr": {
        # App Title
        "title": "GotoAndrivet — Carte du ciel et GoTo  |  LX200 · OnStep",
        
        # Menu Bar
        "file": "Fichier",
        "settings_menu": "Paramètres…",
        "quit": "Quitter",
        "mount_menu": "Monture",
        "connect": "Connecter…",
        "disconnect": "Déconnecter",
        "stop": "Stop",
        "parking": "Parquer la monture",
        "help": "Aide",
        "about": "À propos",
        "lang_submenu": "Langue / Language",
        
        # Notebook Tab Titles
        "control_tab": " Contrôle ",
        "cat_tab": " Catalogue ",
        "goto_tab": " GoTo/Sync ",
        "derot_tab": " Dérotateur ",
        "focus_tab": " Focuseur ",
        "log_tab": " Log LX200 ",
        
        # Connection Frame
        "conn_frame": "Connexion",
        "port": "Port :",
        "baud": "Baud :",
        "simulation": "Simulation",
        "btn_connect": "⬡ Connecter",
        "btn_disconnect": "Déconnecter",
        
        # Position Frame
        "curr_pos_frame": "Position actuelle",
        "pos_ra": "RA",
        "pos_dec": "DEC",
        "pos_az": "Azimut",
        "pos_alt": "Altitude",
        "pos_lst": "LST",
        
        # Commands Frame
        "commands_frame": "Commandes",
        "btn_track_off": "⬡ SUIVI OFF",
        "btn_track_on": "⬡ SUIVI ON",
        "btn_stop": "■ STOP",
        "speed": "Vitesse :",
        "parking_north": "Parquer la monture",
        "set_park_here": "Définir le parking ici",
        
        # Mount Status Frame
        "mount_state_frame": "État monture",
        "ready": "Prêt.",
        "state_slewing": "GOTO EN COURS",
        "state_tracking": "Suivi sidéral",
        "state_limit": "⚠ LIMITE CÂBLES",
        "state_idle": "En attente",
        
        # Catalog Search Frame
        "search_cat_frame": "Recherche catalogue",
        "search": "Rechercher :",
        "type_filter": "Filtre type :",
        "mag_limit": "Mag limite :",
        "cat_filter": "Catalogue :",
        "mag_limit_lbl": "Mag max :",
        "col_name": "Nom",
        "col_type": "Type",
        "col_mag": "Mag",
        "col_ra": "RA",
        "col_dec": "Dec",
        "btn_goto_sel": "▶  GOTO  objet sélectionné",
        
        # Target coordinates Frame
        "tgt_coords_frame": "Coordonnées cible",
        "ra_label": "RA (hh:mm:ss) :",
        "dec_label": "DEC (dd:mm:ss) :",
        "lbl_tgt_ra_lbl": "RA   hh:mm:ss",
        "lbl_tgt_dec_lbl": "DEC  ±dd:mm:ss",
        "btn_goto": "▶  GOTO",
        
        # Object description
        "obj_desc_frame": "Objet sélectionné",
        "info_type": "Type  : ",
        "info_mag": "Mag   : ",
        "info_dbl_click": "Dbl-clic → GoTo",
        "visible": "✓ Visible",
        "below_horizon": "✗ Sous horizon",
        
        # Synchronize Frame
        "sync_frame": "Synchronisation (alignement étoile)",
        "sync_desc": "Centrer une étoile connue dans\nl'oculaire puis synchroniser.",
        "btn_sync": "⊕ Synchroniser sur coordonnées ci-dessus",
        
        # Sky map Frame
        "sky_title": "Molette : zoom  ·  glisser ou flèches : déplacer  ·  clic : choisir / GoTo  ·  Échap : STOP",
        "sky_mag_lbl": "Mag :",
        "btn_zenith": "Zénith",
        "btn_scope": "Télescope",
        "btn_photo": "◉ Caméra",
        "btn_guide": "◎ Guidage",
        "photo_missing": "Le module photo demande numpy et Pillow (installés par install_linux.py) :\n{err}",
        
        # Derotator Connection Frame
        "derot_conn_frame": "Dérotateur",
        "type_lbl": "Type :", "ppd_lbl": "Pas/degré :",
        "kind_integre": "Intégré (monture)", "kind_zwo": "ZWO CAA (USB)", "kind_serie": "Série (SETPOS)",
        "kind_sim": "Simulation", "kind_eaf": "ZWO EAF (USB)",
        "dev_connected": "Connecté", "dev_disconnected": "Non connecté",
        "need_mount": "Connectez d'abord la monture : ce périphérique passe par elle.",
        "ppd_invalid": "Pas par degré : entrez un nombre.",
        "derot_note_integre": "Axe DEROT de la monture (monture connectée).",
        "derot_eq_note": "Équatoriale : l'axe sert de rotateur de cadrage (firmware du 21/10/2026 ou plus récent).",
        "derot_eq_rotator": "Monture équatoriale : le champ ne tourne pas, rien à compenser. Réglez l'angle de cadrage avec le contrôle manuel ci-dessous.",
        "focus_frame": "Focuseur", "focus_pos": "Position :", "focus_temp": "Température :",
        "focus_move_frame": "Déplacement", "focus_steps": "Pas :", "focus_goto": "Aller à :",
        "focus_hold_integre": "Maintenez un bouton pour déplacer (◀◀ ▶▶ : rapide). Axe FOCUS de la monture, sans lecture de position.",
        "focus_hold_eaf": "Maintenez un bouton pour déplacer, ou avancez d'un nombre de pas.",
        "no_feedback": "— (pas de lecture)",
        "btn_connect_derot": "Connecter",
        
        # Derotator State Frame
        "derot_state_frame": "État",
        "phys_angle": "Angle physique :",
        "field_angle": "Angle de champ :",
        
        # Derotator Compensation Frame
        "derot_comp_frame": "Compensation rotation de champ",
        "derot_comp_desc": "Compense la rotation du champ\nen montage Alt-Az (imagerie).",
        "derot_comp_enable": "✓  Activer compensation",
        
        # Derotator Manual Control Frame
        "derot_ctrl_manual": "Contrôle manuel",
        "derot_goto": "Aller à l'angle :",
        "derot_offset": "Offset capteur (°) :",
        
        # Log Frame
        "log_frame": "Log série LX200 (USB)",
        "btn_clear": "Effacer",
        "btn_save": "Sauvegarder…",
        
        # Settings Dialog Strings
        "settings_title": "Paramètres — GotoMega",
        "tab_site": " Site ",
        "tab_mech": " Mécanique ",
        "tab_conn": " Connexion ",
        "set_site_name": "Nom du site",
        "set_latitude": "Latitude °N",
        "set_longitude": "Longitude °E",
        "set_altitude": "Altitude m",
        "set_auto_gps": "Localisation automatique via Internet 🛰",
        "set_steps_per_rev": "Pas moteur/tour",
        "set_microstep": "Microstepping",
        "set_mount_type": "Type de Monture",
        "set_gear_az": "Réduction AZ / RA",
        "set_gear_alt": "Réduction ALT / DEC",
        "set_slew_speed": "Vitesse GoTo °/s",
        "set_max_speed": "Vitesse max °/s",
        "set_min_alt": "Alt min °",
        "set_max_alt": "Alt max °",
        "set_limit_az": "Az limite °",
        "set_steps_deg": "Pas/deg :",
        "set_port_mount": "Port monture",
        "set_baud_mount": "Baud monture",
        "set_port_derot": "Port dérotateur",
        "set_baud_derot": "Baud dérotateur",
        "set_rev_az": "Inverser Az",
        "set_rev_alt": "Inverser Alt",
        "set_rev_derot": "Inverser dérotateur",
        "set_btn_save": "✓ Enregistrer",
        "set_btn_cancel": "Annuler",
        "set_gps_ok": "Position détectée automatiquement !\n\nLat: {lat:.6f}\nLon: {lon:.6f}",
        "set_gps_err": "Impossible de détecter la position automatiquement. Vérifiez votre connexion Internet.",
        
        # Messageboxes & Alerts
        "msg_conn_err": "Impossible de se connecter à {port}",
        "msg_lst_offset": "L'heure sidérale de la monture diffère de celle du PC de {off:+.0f} min : les GoTo vont manquer leur cible.\n\n"
                          "Flashez la monture avec le dernier firmware (configurateur, section Firmware), puis reconnectez. "
                          "Si l'écart persiste, vérifiez la longitude du site et l'heure du PC.",
        "msg_parking_confirm": "Envoyer la monture à sa position de parking ?",
        "msg_set_park_confirm": "Enregistrer la position actuelle comme position de parking ?",
        "msg_set_park_ok": "Position de parking enregistrée.",
        "msg_set_park_fail": "Position de parking refusée : monture en mouvement, du côté retourné du pilier, ou non connectée.",
        "msg_sync_invalid": "Coordonnées invalides.",
        "msg_goto_not_connected": "Monture non connectée.",
        "msg_goto_below_horizon": "{name}\nSous l'horizon (Alt={alt:.1f}°)",
        "msg_goto_rejected": "Refusé : {resp}",
        "msg_goto_invalid_format": "Format invalide",
        "msg_goto_select_obj": "Sélectionnez un objet.",
        "msg_goto_confirm": "GoTo {name} ?",
        "msg_saved": "Paramètres sauvegardés.",
        "all_filter": "Tous",
        "msg_goto_sun": "Pointer le Soleil est refusé : sans filtre solaire, il détruit l'œil et le matériel.",
        "view_menu": "Affichage",
        "layer_milky_way": "Voie lactée", "layer_eq_grid": "Grille équatoriale", "layer_az_grid": "Grille altazimutale",
        "layer_const_lines": "Lignes des constellations", "layer_const_names": "Noms des constellations",
        "layer_star_names": "Noms des étoiles", "layer_dso": "Objets du ciel profond", "layer_planets": "Soleil, Lune et planètes",
        "follow_scope": "Suivre le télescope", "follow_short": "Suivre", "center_scope": "Centrer sur le télescope",
        "view_zenith": "Regarder le zénith", "view_north": "Regarder au nord", "view_east": "Regarder à l'est",
        "view_south": "Regarder au sud", "view_west": "Regarder à l'ouest",
        "search_lbl": "Chercher :",
        "shortcuts": "Raccourcis clavier",
        "shortcuts_text": "Échap : STOP de la monture (partout)\nFlèches : déplacer la carte\n+ / - : zoomer / dézoomer\n"
                          "Molette : zoom   ·   glisser : déplacer la carte\nClic sur un objet : le choisir, puis confirmer le GoTo",
        "check_updates": "Rechercher une mise à jour…",
        "update_available": "● Mise à jour disponible (cliquer)",
        "update_btn": "Mise à jour", "update_btn_new": "Mise à jour disponible",
        "update_none": "GotoAndrivet est à jour.",
        "update_confirm": "Une nouvelle version est disponible sur GitHub.\nLa télécharger et redémarrer ?",
        "update_running": "Téléchargement de la mise à jour…",
        "update_done": "Mise à jour installée. L'application va redémarrer.",
        "update_error": "Échec de la mise à jour :\n{err}",
        "about_text": "GotoAndrivet — carte du ciel et GoTo\nVersion {version}\n\nAndrivet Jean-Baptiste · GNU GPL v3\n"
                      "Étoiles : Yale Bright Star Catalogue (CDS) · Ciel profond : OpenNGC (CC BY-SA 4.0)\n"
                      "Constellations : Stellarium (CC BY-SA 4.0)"
    }
}


# ================================================================
#  SECTION 8 : APPLICATION PRINCIPALE
# ================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1420x900"); self.minsize(1100,700); self.configure(bg=BG)

        self.cfg = Settings()
        self.mount = Mount(self.cfg, on_state=self._on_mount)
        self.derot = Derotator(self.cfg, on_state=self._on_derot)
        self.derot.set_mount(self.mount)
        self.focuser = Focuser(self.cfg, on_state=self._on_focus)
        self.focuser.set_mount(self.mount)

        # Variables Tk
        self._rv  = {k: tk.StringVar(value="---") for k in
                     ("ra","dec","az","alt","lst","state","conn","derot_ang","derot_pa",
                      "derot_status","focus_status","focus_pos","focus_temp")}
        self._bv  = {k: tk.BooleanVar() for k in ("track","sim","derot_en","follow")}
        self._bv["sim"].set(False)
        self._bv["follow"].set(self.cfg.get("skymap_follow", False))
        self._update_sha = None
        self._dv  = {"speed": tk.DoubleVar(value=self.cfg.get("slew_speed_default", 2.0)), "mag": tk.DoubleVar(value=10.0),
                     "mapm": tk.DoubleVar(value=6.5)}
        self._sv  = {"port": tk.StringVar(value=self.cfg.get("mount_port","/dev/ttyUSB0")),
                     "baud": tk.StringVar(value=str(self.cfg.get("mount_baud",38400))),
                     "dport":tk.StringVar(value=self.cfg.get("derot_port","/dev/ttyUSB1")),
                     "filt": tk.StringVar(value="Tous"),
                     "type_f":tk.StringVar(value="Tous"),
                     "search":tk.StringVar(),
                     "tgt_ra":tk.StringVar(value="00:00:00"),
                     "tgt_dec":tk.StringVar(value="+00:00:00")}
        self._all_objs = []
        self._goto_target = None      # (ra, dec J2000, nom) du dernier GoTo, pour le centrage du module photo
        self._derot_eq = False
        self._photo_win = None
        self._guide_win = None

        _theme(self)
        self._build()
        self._translate_ui()
        self._sv["search"].trace_add("write", lambda *a: self._load_cat())
        self.bind_all("<Key>", self._on_key)
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        threading.Thread(target=self._check_update, daemon=True).start()

    # ============================================================
    #  CONSTRUCTION UI
    # ============================================================
    def _build(self):
        # Menu is built by _build_menu dynamically called from _translate_ui/startup
        self._build_menu()

        # Layout 3 colonnes
        pw=tk.PanedWindow(self,orient=tk.HORIZONTAL,bg=BD,sashwidth=4,sashrelief="flat")
        pw.pack(fill=tk.BOTH,expand=True,padx=2,pady=2)
        left=tk.Frame(pw,bg=BG2,width=370); left.pack_propagate(False)
        center=tk.Frame(pw,bg=BG)
        right=tk.Frame(pw,bg=BG2,width=310); right.pack_propagate(False)
        pw.add(left,minsize=320,width=360); pw.add(center,minsize=400,stretch="always")
        pw.add(right,minsize=290,width=320)
        def place_sashes(e=None):
            W = pw.winfo_width()
            if W > 1100:
                pw.sash_place(0, 362, 1); pw.sash_place(1, W - 330, 1)
        pw.bind("<Map>", lambda e: self.after(50, place_sashes))

        self._build_left(left)
        self._build_center(center)
        self._build_right(right)

        # Status bar
        sb=tk.Frame(self,bg=BG,height=24); sb.pack(fill=tk.X,side=tk.BOTTOM)
        tk.Frame(sb,bg=BD,height=1).pack(fill=tk.X)
        self._slbl=tk.Label(sb,text="Prêt.",bg=BG,fg=DIM,font=FS,anchor="w")
        self._slbl.pack(side=tk.LEFT,padx=8)
        tk.Label(sb,textvariable=self._rv["conn"],bg=BG,fg=DIM,font=FS).pack(side=tk.RIGHT,padx=8)

    def _build_menu(self):
        lang = self.cfg.get("language", "fr")
        mb=tk.Menu(self,bg=BG2,fg=TXT,activebackground=ACC,activeforeground="white")
        mf=tk.Menu(mb,tearoff=0,bg=BG2,fg=TXT)
        mf.add_command(label=TRANSLATIONS[lang]["settings_menu"],command=self._settings)
        
        ml=tk.Menu(mf,tearoff=0,bg=BG2,fg=TXT)
        ml.add_command(label="Français",command=lambda: self.change_language("fr"))
        ml.add_command(label="English",command=lambda: self.change_language("en"))
        mf.add_cascade(label=TRANSLATIONS[lang]["lang_submenu"],menu=ml)
        
        mf.add_separator(); mf.add_command(label=TRANSLATIONS[lang]["quit"],command=self._quit)
        mb.add_cascade(label=TRANSLATIONS[lang]["file"],menu=mf)
        
        mm=tk.Menu(mb,tearoff=0,bg=BG2,fg=TXT)
        mm.add_command(label=TRANSLATIONS[lang]["connect"],command=self._connect)
        mm.add_command(label=TRANSLATIONS[lang]["disconnect"],command=self._disconnect)
        mm.add_separator()
        mm.add_command(label=TRANSLATIONS[lang]["stop"],command=self._stop)
        mm.add_command(label=TRANSLATIONS[lang]["parking"],command=self._parking)
        mb.add_cascade(label=TRANSLATIONS[lang]["mount_menu"],menu=mm)
        
        t = TRANSLATIONS[lang]
        mv=tk.Menu(mb,tearoff=0,bg=BG2,fg=TXT)
        self._layer_vars = {}
        for name in SkyMap.LAYERS:
            v = tk.BooleanVar(value=self._sky.layer(name) if hasattr(self, "_sky") else True)
            self._layer_vars[name] = v
            mv.add_checkbutton(label=t["layer_" + name], variable=v,
                               command=lambda n=name, v=v: self._sky.set_layer(n, v.get()))
        mv.add_separator()
        mv.add_checkbutton(label=t["follow_scope"], variable=self._bv["follow"], command=self._toggle_follow)
        mv.add_command(label=t["center_scope"], command=self._center_scope)
        mv.add_command(label=t["view_zenith"], command=lambda: self._sky.center_on(180, 89))
        for az, key in ((0, "view_north"), (90, "view_east"), (180, "view_south"), (270, "view_west")):
            mv.add_command(label=t[key], command=lambda az=az: self._sky.center_on(az, 35))
        mb.add_cascade(label=t["view_menu"],menu=mv)

        mh=tk.Menu(mb,tearoff=0,bg=BG2,fg=TXT)
        mh.add_command(label=t["shortcuts"],command=lambda: messagebox.showinfo(t["shortcuts"], t["shortcuts_text"]))
        mh.add_command(label=t["check_updates"],command=lambda: threading.Thread(
            target=self._check_update, args=(True,), daemon=True).start())
        mh.add_separator()
        mh.add_command(label=t["about"],command=self._about)
        mb.add_cascade(label=t["help"],menu=mh)
        self.config(menu=mb)

    # ── Panneau gauche ────────────────────────────────────────
    def _build_left(self, p):
        self._nb_left=ttk.Notebook(p); self._nb_left.pack(fill=tk.BOTH,expand=True,padx=4,pady=4)

        t1=tk.Frame(self._nb_left,bg=BG2); self._nb_left.add(t1,text=" Contrôle ")
        t2=tk.Frame(self._nb_left,bg=BG2); self._nb_left.add(t2,text=" Catalogue ")
        t3=tk.Frame(self._nb_left,bg=BG2); self._nb_left.add(t3,text=" GoTo/Sync ")

        self._build_ctrl(t1)
        self._build_cat_tab(t2)
        self._build_goto_tab(t3)

    def _frm(self, p, title):
        f=ttk.LabelFrame(p,text=f" {title} ",padding=4); return f

    def _build_ctrl(self, p):
        # Connexion
        self._frm_conn=self._frm(p,"Connexion"); self._frm_conn.pack(fill=tk.X,padx=6,pady=4)
        r=tk.Frame(self._frm_conn,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_port=tk.Label(r,text="Port :",bg=BG2,fg=DIM,font=FS)
        self._lbl_port.pack(side=tk.LEFT)
        ports=Mount.list_ports() or ["/dev/ttyUSB0","/dev/ttyACM0","/dev/ttyUSB1"]
        self._pcb=ttk.Combobox(r,textvariable=self._sv["port"],values=ports,width=14,font=FS)
        self._pcb.pack(side=tk.LEFT,padx=4)
        ttk.Button(r,text="↺",width=3,command=self._refresh_ports).pack(side=tk.LEFT)

        r2=tk.Frame(self._frm_conn,bg=BG2); r2.pack(fill=tk.X,pady=2)
        self._lbl_baud=tk.Label(r2,text="Baud :",bg=BG2,fg=DIM,font=FS)
        self._lbl_baud.pack(side=tk.LEFT)
        ttk.Combobox(r2,textvariable=self._sv["baud"],
                     values=["9600","19200","38400","115200"],width=8,font=FS).pack(side=tk.LEFT,padx=4)
        self._chk_sim=tk.Checkbutton(r2,text="Simulation",variable=self._bv["sim"],
                       bg=BG2,fg=DIM,selectcolor=BG3,activebackground=BG2,font=FS)
        self._chk_sim.pack(side=tk.LEFT,padx=6)

        r3=tk.Frame(self._frm_conn,bg=BG2); r3.pack(fill=tk.X,pady=4)
        self._btn_connect=ttk.Button(r3,text="⬡ Connecter",style="Acc.TButton",command=self._connect)
        self._btn_connect.pack(side=tk.LEFT,padx=2)
        self._btn_disconnect=ttk.Button(r3,text="Déconnecter",command=self._disconnect)
        self._btn_disconnect.pack(side=tk.LEFT,padx=2)

        # Position
        self._frm_pos=self._frm(p,"Position actuelle"); self._frm_pos.pack(fill=tk.X,padx=6,pady=4)
        self._pos_lbl_widgets = {}
        for lbl,key,col in [("RA","ra",ACC),("DEC","dec",ACC),
                              ("Azimut","az",AC2),("Altitude","alt",AC2),("LST","lst",GRN)]:
            r=tk.Frame(self._frm_pos,bg=BG2); r.pack(fill=tk.X,pady=1)
            lbl_widget=tk.Label(r,text=f"{lbl:<7}",bg=BG2,fg=DIM,font=FS,width=8)
            lbl_widget.pack(side=tk.LEFT)
            self._pos_lbl_widgets[key] = lbl_widget
            tk.Label(r,textvariable=self._rv[key],bg=BG3,fg=col,font=FL,
                     width=14,anchor="w",padx=6,pady=2).pack(side=tk.LEFT,fill=tk.X,expand=True)

        # Commandes
        self._frm_cmd=self._frm(p,"Commandes"); self._frm_cmd.pack(fill=tk.X,padx=6,pady=4)
        r=tk.Frame(self._frm_cmd,bg=BG2); r.pack(fill=tk.X,pady=3)
        self._tbtn=ttk.Button(r,text="⬡ SUIVI OFF",command=self._toggle_track)
        self._tbtn.pack(side=tk.LEFT,padx=2,fill=tk.X,expand=True)
        self._btn_stop=ttk.Button(r,text="■ STOP",style="Stop.TButton",command=self._stop)
        self._btn_stop.pack(side=tk.LEFT,padx=2)

        r=tk.Frame(self._frm_cmd,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_speed=tk.Label(r,text="Vitesse :",bg=BG2,fg=DIM,font=FS)
        self._lbl_speed.pack(side=tk.LEFT)
        spd = self.cfg.get("slew_speed_default", 2.0)
        self._splbl=tk.Label(r,text=f"{spd:.1f}°/s",bg=BG2,fg=ACC,font=FS,width=7); self._splbl.pack(side=tk.RIGHT)
        ttk.Scale(self._frm_cmd,from_=0.5,to=self.cfg.get("slew_speed_max", 25.0),orient=tk.HORIZONTAL,
                  variable=self._dv["speed"],command=self._spd_change).pack(fill=tk.X,pady=2,padx=2)

        self._btn_park=ttk.Button(self._frm_cmd,text="Parquer la monture",command=self._parking)
        self._btn_park.pack(fill=tk.X,pady=2)
        self._btn_setpark=ttk.Button(self._frm_cmd,text="Définir le parking ici",command=self._set_park_here)
        self._btn_setpark.pack(fill=tk.X,pady=2)

        # État
        self._frm_state=self._frm(p,"État monture"); self._frm_state.pack(fill=tk.X,padx=6,pady=4)
        self._stlbl=tk.Label(self._frm_state,textvariable=self._rv["state"],bg=BG3,fg=DIM,
                              font=FS,anchor="w",padx=6,pady=4); self._stlbl.pack(fill=tk.X)

    def _build_cat_tab(self, p):
        # Filtres
        r=tk.Frame(p,bg=BG2); r.pack(fill=tk.X,padx=6,pady=4)
        self._lbl_cat=tk.Label(r,text="Catalogue :",bg=BG2,fg=DIM,font=FS)
        self._lbl_cat.pack(side=tk.LEFT)
        cats=["Tous"]+list(ALL_CATALOGS.keys())
        self._cb_cat=ttk.Combobox(r,textvariable=self._sv["filt"],values=cats,width=11,font=FS)
        self._cb_cat.pack(side=tk.LEFT,padx=4); self._cb_cat.bind("<<ComboboxSelected>>",lambda e:self._load_cat())

        r2=tk.Frame(p,bg=BG2); r2.pack(fill=tk.X,padx=6)
        self._lbl_mag_max=tk.Label(r2,text="Mag max :",bg=BG2,fg=DIM,font=FS)
        self._lbl_mag_max.pack(side=tk.LEFT)
        ttk.Scale(r2,from_=5,to=14,orient=tk.HORIZONTAL,variable=self._dv["mag"],
                  command=lambda v:self._load_cat()).pack(side=tk.LEFT,fill=tk.X,expand=True,padx=4)
        self._maglbl=tk.Label(r2,text="10.0",bg=BG2,fg=ACC,font=FS,width=5); self._maglbl.pack(side=tk.LEFT)

        r3=tk.Frame(p,bg=BG2); r3.pack(fill=tk.X,padx=6,pady=2)
        self._lbl_search_icon=tk.Label(r3,text="Chercher :",bg=BG2,fg=DIM,font=FS)
        self._lbl_search_icon.pack(side=tk.LEFT)
        ttk.Entry(r3,textvariable=self._sv["search"],font=FS).pack(side=tk.LEFT,fill=tk.X,expand=True,padx=4)

        # Treeview
        fr=tk.Frame(p,bg=BG2); fr.pack(fill=tk.BOTH,expand=True,padx=6,pady=4)
        cols=("Nom","Type","Mag","RA","Dec"); widths=(170,96,40,80,80)
        # RA/Dec restent dans les données (tri, recherche) mais ne sont pas affichées : elles
        # débordaient du panneau ; la fiche de l'objet sélectionné les donne.
        self._tree=ttk.Treeview(fr,columns=cols,displaycolumns=("Nom","Type","Mag"),show="headings",height=16)
        for c,w in zip(cols,widths):
            self._tree.heading(c,text=c,command=lambda cc=c:self._sort(cc))
            self._tree.column(c,width=w,anchor="w",stretch=(c=="Nom"))
        vsb=ttk.Scrollbar(fr,orient=tk.VERTICAL,command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT,fill=tk.Y); self._tree.pack(fill=tk.BOTH,expand=True)
        self._tree.bind("<Double-1>",lambda e:self._goto_sel())
        self._tree.bind("<<TreeviewSelect>>",self._on_sel)

        self._btn_goto_sel=ttk.Button(p,text="▶  GOTO  objet sélectionné",style="GoTo.TButton",
                   command=self._goto_sel)
        self._btn_goto_sel.pack(fill=tk.X,padx=6,pady=4)

    def _build_goto_tab(self, p):
        self._frm_manual=self._frm(p,"Coordonnées manuelles"); self._frm_manual.pack(fill=tk.X,padx=6,pady=8)
        self._lbl_manual_coords = []
        for lbl,key in [("RA   hh:mm:ss","tgt_ra"),("DEC  ±dd:mm:ss","tgt_dec")]:
            r=tk.Frame(self._frm_manual,bg=BG2); r.pack(fill=tk.X,pady=4)
            l=tk.Label(r,text=lbl,bg=BG2,fg=DIM,font=FS,width=15)
            l.pack(side=tk.LEFT)
            self._lbl_manual_coords.append((l, key))
            ttk.Entry(r,textvariable=self._sv[key],font=FL,width=12).pack(side=tk.LEFT,padx=4)
        self._btn_goto_manual=ttk.Button(self._frm_manual,text="▶  GOTO",style="GoTo.TButton",command=self._goto_manual)
        self._btn_goto_manual.pack(fill=tk.X,pady=8)

        self._frm_sel_obj=self._frm(p,"Objet sélectionné"); self._frm_sel_obj.pack(fill=tk.X,padx=6,pady=4)
        self._info=tk.Text(self._frm_sel_obj,bg=BG3,fg=TXT,font=FS,height=9,relief="flat",state="disabled")
        self._info.pack(fill=tk.X,padx=4,pady=4)

        self._frm_sync=self._frm(p,"Synchronisation (alignement étoile)"); self._frm_sync.pack(fill=tk.X,padx=6,pady=4)
        self._lbl_sync=tk.Label(self._frm_sync,text="Centrer une étoile connue dans\nl'oculaire puis synchroniser.",
                 bg=BG2,fg=DIM,font=FS,justify="left")
        self._lbl_sync.pack(anchor="w",pady=4)
        self._btn_sync=ttk.Button(self._frm_sync,text="⊕ Synchroniser sur coordonnées ci-dessus",
                   command=self._sync)
        self._btn_sync.pack(fill=tk.X,pady=2)

    # ── Centre : carte du ciel ─────────────────────────────────
    def _build_center(self, p):
        hdr=tk.Frame(p,bg=BG); hdr.pack(fill=tk.X)
        self._lbl_sky_title=tk.Label(hdr,text="",bg=BG,fg="#6a8aaa",font=("Helvetica",9),anchor="w")
        ctrl=tk.Frame(hdr,bg=BG); ctrl.pack(side=tk.RIGHT,padx=6)
        self._lbl_sky_title.pack(side=tk.LEFT,padx=8,pady=4,fill=tk.X,expand=True)
        self._lbl_sky_mag=tk.Label(ctrl,text="Mag :",bg=BG,fg=DIM,font=FS)
        self._lbl_sky_mag.pack(side=tk.LEFT)
        ttk.Spinbox(ctrl,from_=3,to=12,increment=0.5,textvariable=self._dv["mapm"],
                    width=5,font=FS,command=self._map_mag).pack(side=tk.LEFT,padx=4)
        self._btn_zenith=ttk.Button(ctrl,text="Zénith",command=lambda:self._sky.center_on(180,89))
        self._btn_zenith.pack(side=tk.LEFT,padx=2)
        self._btn_scope=ttk.Button(ctrl,text="Télescope",command=self._center_scope)
        self._btn_scope.pack(side=tk.LEFT,padx=2)
        self._chk_follow=tk.Checkbutton(ctrl,text="Suivre",variable=self._bv["follow"],command=self._toggle_follow,
                                        bg=BG,fg=DIM,selectcolor=BG3,activebackground=BG,font=FS)
        self._chk_follow.pack(side=tk.LEFT,padx=6)
        self._btn_photo=ttk.Button(ctrl,text="Photo",command=self._open_photo)
        self._btn_photo.pack(side=tk.LEFT,padx=2)
        self._btn_guide=ttk.Button(ctrl,text="Guidage",command=self._open_guide)
        self._btn_guide.pack(side=tk.LEFT,padx=2)
        # Mise à jour : bouton toujours visible, pastille rouge quand une version plus récente existe
        self._upd_dot=tk.PhotoImage(width=12,height=12)
        for x in range(12):
            for y in range(12):
                if (x-5.5)**2+(y-5.5)**2 <= 30: self._upd_dot.put("#e53935",(x,y))
        self._upd_nodot=tk.PhotoImage(width=1,height=12)
        self._btn_update=tk.Button(ctrl,text=" Mise à jour",image=self._upd_nodot,compound="left",
                                   command=self._update_clicked,bg=BG3,fg=TXT,activebackground=BD,
                                   activeforeground=TXT,relief="flat",bd=0,padx=8,pady=3,
                                   font=("Helvetica",9),cursor="hand2")
        self._btn_update.pack(side=tk.LEFT,padx=(6,2))

        self._sky=SkyMap(p,self.cfg,bg=BG)
        self._sky.pack(fill=tk.BOTH,expand=True,padx=2,pady=2)
        self._sky.on_obj_click=self._map_obj_click
        self._sky.on_sky_click=self._map_sky_click

    # ── Panneau droit : dérotateur + log ──────────────────────
    def _build_right(self, p):
        self._nb_right=ttk.Notebook(p); self._nb_right.pack(fill=tk.BOTH,expand=True,padx=4,pady=4)
        self._td=tk.Frame(self._nb_right,bg=BG2); self._nb_right.add(self._td,text=" Dérotateur ")
        self._tf=tk.Frame(self._nb_right,bg=BG2); self._nb_right.add(self._tf,text=" Focuseur ")
        self._tl=tk.Frame(self._nb_right,bg=BG2); self._nb_right.add(self._tl,text=" Log LX200 ")
        self._build_derot(self._td)
        self._build_focus(self._tf)
        self._build_log(self._tl)

    def _build_derot(self, p):
        self._frm_derot_conn=self._frm(p,"Dérotateur"); self._frm_derot_conn.pack(fill=tk.X,padx=6,pady=4)
        r=tk.Frame(self._frm_derot_conn,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_derot_type=tk.Label(r,text="Type :",bg=BG2,fg=DIM,font=FS,width=11,anchor="w")
        self._lbl_derot_type.pack(side=tk.LEFT)
        self._sv["dtype"]=tk.StringVar()
        self._cb_derot_type=ttk.Combobox(r,textvariable=self._sv["dtype"],state="readonly",width=19,font=FS)
        self._cb_derot_type.pack(side=tk.LEFT,padx=4)
        self._cb_derot_type.bind("<<ComboboxSelected>>",lambda e:self._derot_type_changed())
        r=tk.Frame(self._frm_derot_conn,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_derot_ppd=tk.Label(r,text="Pas/degré :",bg=BG2,fg=DIM,font=FS,width=11,anchor="w")
        self._lbl_derot_ppd.pack(side=tk.LEFT)
        self._sv["dppd"]=tk.StringVar(value=str(self.cfg.get("derot_ppd",100.0)))
        self._ent_derot_ppd=ttk.Entry(r,textvariable=self._sv["dppd"],width=10,font=FS)
        self._ent_derot_ppd.pack(side=tk.LEFT,padx=4)
        r=tk.Frame(self._frm_derot_conn,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_derot_port=tk.Label(r,text="Port :",bg=BG2,fg=DIM,font=FS,width=11,anchor="w")
        self._lbl_derot_port.pack(side=tk.LEFT)
        self._ent_derot_port=ttk.Entry(r,textvariable=self._sv["dport"],width=14,font=FS)
        self._ent_derot_port.pack(side=tk.LEFT,padx=4)
        r2=tk.Frame(self._frm_derot_conn,bg=BG2); r2.pack(fill=tk.X,pady=2)
        self._btn_derot_connect=ttk.Button(r2,text="Connecter",command=self._connect_derot)
        self._btn_derot_connect.pack(side=tk.LEFT)
        tk.Label(r2,textvariable=self._rv["derot_status"],bg=BG2,fg=DIM,font=FS).pack(side=tk.LEFT,padx=8)
        self._lbl_derot_note=tk.Label(self._frm_derot_conn,text="",bg=BG2,fg=DIM,font=FS,justify="left",
                                      wraplength=270,anchor="w")
        self._lbl_derot_note.pack(fill=tk.X,pady=(2,0))

        self._frm_derot_state=self._frm(p,"État"); self._frm_derot_state.pack(fill=tk.X,padx=6,pady=4)
        
        r_ang=tk.Frame(self._frm_derot_state,bg=BG2); r_ang.pack(fill=tk.X,pady=2)
        self._lbl_derot_ang=tk.Label(r_ang,text="Angle actuel :",bg=BG2,fg=DIM,font=FS)
        self._lbl_derot_ang.pack(side=tk.LEFT)
        tk.Label(r_ang,textvariable=self._rv["derot_ang"],bg=BG3,fg=ACC,font=FL,width=8,anchor="w",padx=6).pack(side=tk.LEFT)
        
        r_pa=tk.Frame(self._frm_derot_state,bg=BG2); r_pa.pack(fill=tk.X,pady=2)
        self._lbl_derot_pa=tk.Label(r_pa,text="Angle parallact. :",bg=BG2,fg=DIM,font=FS)
        self._lbl_derot_pa.pack(side=tk.LEFT)
        tk.Label(r_pa,textvariable=self._rv["derot_pa"],bg=BG3,fg=AC2,font=FL,width=8,anchor="w",padx=6).pack(side=tk.LEFT)

        self._frm_derot_comp=self._frm(p,"Compensation rotation de champ"); self._frm_derot_comp.pack(fill=tk.X,padx=6,pady=4)
        self._lbl_derot_comp_desc=tk.Label(self._frm_derot_comp,text="Compense la rotation du champ\nen montage Alt-Az (imagerie).",
                 bg=BG2,fg=DIM,font=FS,justify="left",wraplength=260)
        self._lbl_derot_comp_desc.pack(anchor="w",pady=2)
        self._chk_derot_en=tk.Checkbutton(self._frm_derot_comp,text="✓  Activer compensation",variable=self._bv["derot_en"],
                       bg=BG2,fg=GRN,disabledforeground=DIM,selectcolor=BG3,activebackground=BG2,
                       font=("Courier",10,"bold"),command=self._toggle_derot)
        self._chk_derot_en.pack(anchor="w",pady=4)

        self._frm_derot_manual=self._frm(p,"Contrôle manuel"); self._frm_derot_manual.pack(fill=tk.X,padx=6,pady=4)
        self._dtgt=tk.DoubleVar(value=0.0)
        r=tk.Frame(self._frm_derot_manual,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_derot_goto=tk.Label(r,text="Goto angle :",bg=BG2,fg=DIM,font=FS)
        self._lbl_derot_goto.pack(side=tk.LEFT)
        ttk.Spinbox(r,from_=-360,to=360,increment=1,textvariable=self._dtgt,
                    width=7,font=FS).pack(side=tk.LEFT,padx=4)
        ttk.Button(r,text="→",command=lambda:self.derot.goto_angle(self._dtgt.get())).pack(side=tk.LEFT)

        r2=tk.Frame(self._frm_derot_manual,bg=BG2); r2.pack(fill=tk.X,pady=2)
        for i,(lbl,d) in enumerate([("◀ -5°",-5),("-1°",-1),("0°",None),("+1°",+1),("+5° ▶",+5)]):
            r2.columnconfigure(i,weight=1,uniform="derot")
            if d is None:
                ttk.Button(r2,text=lbl,width=4,command=self.derot.home).grid(row=0,column=i,sticky="ew",padx=1)
            else:
                ttk.Button(r2,text=lbl,width=4,command=lambda dv=d:self.derot.nudge(dv)).grid(row=0,column=i,sticky="ew",padx=1)

        r3=tk.Frame(self._frm_derot_manual,bg=BG2); r3.pack(fill=tk.X,pady=4)
        self._lbl_derot_offset=tk.Label(r3,text="Offset capteur (°) :",bg=BG2,fg=DIM,font=FS)
        self._lbl_derot_offset.pack(side=tk.LEFT)
        self._doff=tk.DoubleVar(value=0.0)
        ttk.Spinbox(r3,from_=-180,to=180,increment=0.5,textvariable=self._doff,
                    width=7,font=FS,command=lambda:self.derot.set_offset(self._doff.get())).pack(side=tk.LEFT,padx=4)

    def _build_focus(self, p):
        self._frm_focus_conn=self._frm(p,"Focuseur"); self._frm_focus_conn.pack(fill=tk.X,padx=6,pady=4)
        r=tk.Frame(self._frm_focus_conn,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_focus_type=tk.Label(r,text="Type :",bg=BG2,fg=DIM,font=FS,width=11,anchor="w")
        self._lbl_focus_type.pack(side=tk.LEFT)
        self._sv["ftype"]=tk.StringVar()
        self._cb_focus_type=ttk.Combobox(r,textvariable=self._sv["ftype"],state="readonly",width=19,font=FS)
        self._cb_focus_type.pack(side=tk.LEFT,padx=4)
        self._cb_focus_type.bind("<<ComboboxSelected>>",lambda e:self._focus_type_changed())
        r2=tk.Frame(self._frm_focus_conn,bg=BG2); r2.pack(fill=tk.X,pady=2)
        self._btn_focus_connect=ttk.Button(r2,text="Connecter",command=self._connect_focus)
        self._btn_focus_connect.pack(side=tk.LEFT)
        tk.Label(r2,textvariable=self._rv["focus_status"],bg=BG2,fg=DIM,font=FS).pack(side=tk.LEFT,padx=8)

        self._frm_focus_state=self._frm(p,"État"); self._frm_focus_state.pack(fill=tk.X,padx=6,pady=4)
        self._lbl_focus_pos_w=[]
        for key in ("focus_pos","focus_temp"):
            r=tk.Frame(self._frm_focus_state,bg=BG2); r.pack(fill=tk.X,pady=2)
            l=tk.Label(r,text="",bg=BG2,fg=DIM,font=FS,width=13,anchor="w"); l.pack(side=tk.LEFT)
            self._lbl_focus_pos_w.append(l)
            tk.Label(r,textvariable=self._rv[key],bg=BG3,fg=ACC,font=FL,anchor="w",padx=6).pack(side=tk.LEFT,fill=tk.X,expand=True)

        self._frm_focus_move=self._frm(p,"Déplacement"); self._frm_focus_move.pack(fill=tk.X,padx=6,pady=4)
        r=tk.Frame(self._frm_focus_move,bg=BG2); r.pack(fill=tk.X,pady=2)
        # Maintenir appuyé : le focuseur bouge jusqu'au relâchement (◀◀ ▶▶ : vitesse rapide)
        for i,(lbl,d,fast) in enumerate((("◀◀",-1,True),("◀",-1,False),("▶",1,False),("▶▶",1,True))):
            r.columnconfigure(i,weight=1,uniform="focus")
            b=ttk.Button(r,text=lbl,width=4); b.grid(row=0,column=i,sticky="ew",padx=1)
            b.bind("<ButtonPress-1>",lambda e,d=d,f=fast:self.focuser.start(d,f))
            b.bind("<ButtonRelease-1>",lambda e:self.focuser.stop())
        self._lbl_focus_hold=tk.Label(self._frm_focus_move,text="",bg=BG2,fg=DIM,font=FS,justify="left",
                                      wraplength=270,anchor="w")
        self._lbl_focus_hold.pack(fill=tk.X,pady=(0,4))
        r=tk.Frame(self._frm_focus_move,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_focus_steps=tk.Label(r,text="Pas :",bg=BG2,fg=DIM,font=FS,width=9,anchor="w")
        self._lbl_focus_steps.pack(side=tk.LEFT)
        self._fstep=tk.IntVar(value=int(self.cfg.get("focus_step",50)))
        self._eaf_widgets=[ttk.Spinbox(r,from_=1,to=10000,increment=10,textvariable=self._fstep,width=6,font=FS)]
        self._eaf_widgets[-1].pack(side=tk.LEFT,padx=4)
        for txt,sign in (("−",-1),("+",1)):
            b=ttk.Button(r,text=txt,width=3,command=lambda sg=sign:self._focus_step(sg)); b.pack(side=tk.LEFT,padx=1)
            self._eaf_widgets.append(b)
        r=tk.Frame(self._frm_focus_move,bg=BG2); r.pack(fill=tk.X,pady=2)
        self._lbl_focus_goto=tk.Label(r,text="Aller à :",bg=BG2,fg=DIM,font=FS,width=9,anchor="w")
        self._lbl_focus_goto.pack(side=tk.LEFT)
        self._sv["fgoto"]=tk.StringVar()
        self._eaf_widgets.append(ttk.Entry(r,textvariable=self._sv["fgoto"],width=8,font=FS))
        self._eaf_widgets[-1].pack(side=tk.LEFT,padx=4)
        self._eaf_widgets.append(ttk.Button(r,text="→",width=3,command=self._focus_goto))
        self._eaf_widgets[-1].pack(side=tk.LEFT)
        self._btn_focus_stop=ttk.Button(self._frm_focus_move,text="■ Stop",style="Stop.TButton",command=self.focuser.stop)
        self._btn_focus_stop.pack(fill=tk.X,pady=(6,2))

    def _build_log(self, p):
        self._frm_log=self._frm(p,"Log série LX200 (USB)"); self._frm_log.pack(fill=tk.BOTH,expand=True,padx=6,pady=4)
        self._log=tk.Text(self._frm_log,bg="#04080f",fg="#00cc66",font=("Courier",8),
                          state="disabled",wrap="word",height=30)
        self._log.tag_configure("tx",foreground="#0099cc")
        self._log.tag_configure("rx",foreground="#00cc66")
        self._log.tag_configure("err",foreground="#ff3344")
        self._log.tag_configure("info",foreground="#ffaa00")
        vsb=ttk.Scrollbar(self._frm_log,orient=tk.VERTICAL,command=self._log.yview)
        self._log.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT,fill=tk.Y); self._log.pack(fill=tk.BOTH,expand=True)
        r=tk.Frame(p,bg=BG2); r.pack(fill=tk.X,padx=6,pady=2)
        self._btn_clear_log=ttk.Button(r,text="Effacer",command=self._clear_log)
        self._btn_clear_log.pack(side=tk.LEFT)
        self._btn_save_log=ttk.Button(r,text="Sauvegarder…",command=self._save_log)
        self._btn_save_log.pack(side=tk.LEFT,padx=4)

    # ============================================================
    #  HELPERS
    # ============================================================
    def _logw(self, msg, tag="info"):
        def _do():
            self._log.configure(state="normal")
            ts=datetime.now().strftime("%H:%M:%S")
            pre={"tx":"→ ","rx":"← ","err":"✗ "}.get(tag,"  ")
            self._log.insert("end",f"{ts} {pre}{msg}\n",tag)
            self._log.see("end"); self._log.configure(state="disabled")
        self.after(0,_do)

    def _status(self, msg, col=None):
        def _do():
            self._slbl.configure(text=msg)
            if col: self._slbl.configure(fg=col)
        self.after(0,_do)

    def _clear_log(self):
        self._log.configure(state="normal"); self._log.delete("1.0","end")
        self._log.configure(state="disabled")

    def _save_log(self):
        lang = self.cfg.get("language", "fr")
        txt_type = "Texte" if lang == "fr" else "Text"
        all_type = "Tous" if lang == "fr" else "All"
        path=filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[(txt_type,"*.txt"),(all_type,"*.*")])
        if path:
            with open(path,"w") as f: f.write(self._log.get("1.0","end"))

    def _set_info(self, txt):
        self._info.configure(state="normal"); self._info.delete("1.0","end")
        self._info.insert("end",txt); self._info.configure(state="disabled")

    # ============================================================
    #  CONNEXION
    # ============================================================
    def _connect(self):
        port=self._sv["port"].get(); baud=int(self._sv["baud"].get())
        sim=self._bv["sim"].get()
        lang = self.cfg.get("language", "fr")
        conn_msg = f"Connexion {port} @ {baud} {'(SIM)' if sim else ''}" if lang == "fr" else f"Connection {port} @ {baud} {'(SIM)' if sim else ''}"
        self._logw(conn_msg,"info")
        threading.Thread(target=self._conn_worker,args=(port,baud,sim),daemon=True).start()

    def _conn_worker(self, port, baud, sim):
        ok=self.mount.connect(port,baud,sim=sim)
        # v5.1 : envoyer automatiquement la date/heure courante après connexion
        # pour que le Mega lève son flag 'F' (time-not-set) et autorise les goto.
        if ok and not sim:
            try:
                self.mount.set_datetime_now()
                self._logw("Date/heure envoyée au Mega","tx")
                
                # Envoyer aussi la position GPS configurée au démarrage
                lat = self.cfg.get("latitude", 45.764)
                lon = self.cfg.get("longitude", 4.836)
                self.mount.set_location(lat, lon)
                self._logw(f"GPS envoyé au Mega (Lat:{lat:.4f}, Lon:{lon:.4f})","tx")
                off = self.mount.lst_offset_min(lon)
                if off is not None and abs(off) > 2:
                    self._logw(f"Heure sidérale de la monture décalée de {off:+.0f} min","err")
                    self.after(0, lambda o=off: messagebox.showwarning(
                        "GotoAndrivet", TRANSLATIONS[self.cfg.get("language", "fr")]["msg_lst_offset"].format(off=o)))
            except Exception as e:
                log.error(f"Erreur d'initialisation site/temps : {e}")
        def _ui():
            lang = self.cfg.get("language", "fr")
            if ok:
                self._rv["conn"].set("⬤ CONNECTÉ" if lang == "fr" else "⬤ CONNECTED")
                conn_lbl = f"Connecté {'(simulation)' if sim else port}" if lang == "fr" else f"Connected {'(simulation)' if sim else port}"
                self._status(conn_lbl,GRN)
                self._logw(f"Monture {'sim' if sim else port}","rx")
            else:
                self._rv["conn"].set("⬤ ERREUR" if lang == "fr" else "⬤ ERROR")
                self._status("Connexion échouée" if lang == "fr" else "Connection failed",RED)
                messagebox.showerror(TRANSLATIONS[lang]["conn_frame"], TRANSLATIONS[lang]["msg_conn_err"].format(port=port))
                self._logw(f"Échec connexion {port}","err")
        self.after(0,_ui)

    def _disconnect(self):
        lang = self.cfg.get("language", "fr")
        self.mount.disconnect()
        self._rv["conn"].set("⬤ DÉCONNECTÉ" if lang == "fr" else "⬤ DISCONNECTED")
        self._status("Déconnecté." if lang == "fr" else "Disconnected.",DIM)
        self._logw("Déconnecté." if lang == "fr" else "Disconnected.","info")

    def _refresh_ports(self):
        ports=Mount.list_ports() or ["/dev/ttyUSB0","/dev/ttyACM0"]
        self._pcb["values"]=ports

    # ── Dérotateur et focuseur : type choisi, connexion ─────────
    def _kinds(self, which):
        t = TRANSLATIONS[self.cfg.get("language", "fr")]
        kinds = Derotator.KINDS if which == "derot" else Focuser.KINDS
        return kinds, [t["kind_" + k] for k in kinds]

    def _cur_kind(self, which):
        kinds, labels = self._kinds(which)
        v = self._sv["dtype" if which == "derot" else "ftype"].get()
        return kinds[labels.index(v)] if v in labels else kinds[0]

    def _refresh_devices(self):
        """Libellés, champs actifs et état des boutons du dérotateur et du focuseur."""
        t = TRANSLATIONS[self.cfg.get("language", "fr")]
        for which, dev, cb, var in (("derot", self.derot, self._cb_derot_type, "dtype"),
                                    ("focus", self.focuser, self._cb_focus_type, "ftype")):
            kinds, labels = self._kinds(which)
            cb.configure(values=labels)
            kind = dev.kind if dev.kind in kinds else kinds[0]
            self._sv[var].set(labels[kinds.index(kind)])
            cb.configure(state="disabled" if dev.connected else "readonly")
        dk = self._cur_kind("derot")
        self._ent_derot_ppd.configure(state="normal" if dk == "integre" and not self.derot.connected else "disabled")
        self._ent_derot_port.configure(state="normal" if dk == "serie" and not self.derot.connected else "disabled")
        eq = self.cfg.get("mount_type", "AltAz") != "AltAz"
        self._derot_eq = eq
        note = ""
        if dk == "integre":
            note = t["derot_note_integre"]
            if eq: note += "\n" + t["derot_eq_note"]
        self._lbl_derot_note.configure(text=note)
        self._chk_derot_en.configure(state="disabled" if eq else "normal")
        self._lbl_derot_comp_desc.configure(text=t["derot_eq_rotator"] if eq else t["derot_comp_desc"])
        self._btn_derot_connect.configure(text=t["btn_disconnect"] if self.derot.connected else t["btn_connect_derot"])
        self._rv["derot_status"].set(t["dev_connected"] if self.derot.connected else t["dev_disconnected"])
        fk = self._cur_kind("focus")
        for w in self._eaf_widgets:
            w.configure(state="normal" if fk == "eaf" and self.focuser.connected else "disabled")
        self._btn_focus_connect.configure(text=t["btn_disconnect"] if self.focuser.connected else t["btn_connect_derot"])
        self._rv["focus_status"].set(t["dev_connected"] if self.focuser.connected else t["dev_disconnected"])
        self._lbl_focus_hold.configure(text=t["focus_hold_" + fk])
        if not (self.focuser.connected and fk == "eaf"):
            self._rv["focus_pos"].set(t["no_feedback"] if self.focuser.connected else "---")
            self._rv["focus_temp"].set("---")

    def _derot_type_changed(self):
        self.derot.kind = self._cur_kind("derot"); self.cfg.set("derot_type", self.derot.kind)
        self._refresh_devices()

    def _focus_type_changed(self):
        self.focuser.kind = self._cur_kind("focus"); self.cfg.set("focus_type", self.focuser.kind)
        self._refresh_devices()

    def _device_error(self, msg):
        t = TRANSLATIONS[self.cfg.get("language", "fr")]
        messagebox.showerror("GotoAndrivet", t["need_mount"] if msg == "need_mount" else msg)

    def _connect_derot(self):
        if self.derot.connected:
            self.derot.disconnect(); self._logw("Dérotateur déconnecté","info")
        else:
            kind = self._cur_kind("derot")
            if kind == "integre":
                try: self.cfg.set("derot_ppd", float(self._sv["dppd"].get().replace(",", ".")))
                except ValueError:
                    self._device_error(TRANSLATIONS[self.cfg.get("language", "fr")]["ppd_invalid"]); return
            ok, msg = self.derot.connect(kind, port=self._sv["dport"].get())
            self._logw(f"Dérotateur {kind} {'OK' if ok else 'ERREUR ' + msg}", "rx" if ok else "err")
            if not ok: self._device_error(msg)
            elif self._bv["derot_en"].get(): self.derot.enable(True)
        self._refresh_devices()

    def _connect_focus(self):
        if self.focuser.connected:
            self.focuser.disconnect(); self._logw("Focuseur déconnecté","info")
        else:
            kind = self._cur_kind("focus")
            ok, msg = self.focuser.connect(kind)
            self._logw(f"Focuseur {kind} {'OK' if ok else 'ERREUR ' + msg}", "rx" if ok else "err")
            if not ok: self._device_error(msg)
        self._refresh_devices()

    def _focus_step(self, sign):
        try: n = int(self._fstep.get())
        except (ValueError, tk.TclError): return
        self.cfg.set("focus_step", n)
        self.focuser.move_by(sign * n)

    def _focus_goto(self):
        try: self.focuser.move_to(int(self._sv["fgoto"].get()))
        except ValueError: pass

    def _on_focus(self, fo):
        def _ui():
            if fo.kind == "eaf" and fo.position is not None:
                mx = f" / {fo.max_step}" if fo.max_step else ""
                self._rv["focus_pos"].set(f"{fo.position}{mx}" + ("  ▸" if fo.moving else ""))
                self._rv["focus_temp"].set("---" if fo.temp is None else f"{fo.temp:.1f} °C")
        self.after(0,_ui)

    # ============================================================
    #  MONTURE
    # ============================================================
    def _toggle_track(self):
        lang = self.cfg.get("language", "fr")
        new=not self.mount.state.tracking
        self.mount.set_tracking(new)
        suivi_str = "Suivi ON" if new else "Suivi OFF"
        if lang == "en":
            suivi_str = "Tracking ON" if new else "Tracking OFF"
        self._logw(f":{'T+' if new else 'T-'}# {suivi_str}","tx")

    def _stop(self):
        lang = self.cfg.get("language", "fr")
        self.mount.stop(); self._logw(":Q#  STOP","tx")
        if self.focuser.moving: self.focuser.stop()
        if self._photo_win: self._photo_win.stop()
        if self._guide_win: self._guide_win.stop()
        self._status("Arrêt." if lang == "fr" else "Stopped.")

    def _parking(self):
        lang = self.cfg.get("language", "fr")
        if messagebox.askyesno(TRANSLATIONS[lang]["parking"], TRANSLATIONS[lang]["msg_parking_confirm"]):
            self.mount.parking()
            self._logw(":hP#  Parking","tx")
            self._status("Parking…" if lang == "fr" else "Parking...")

    def _set_park_here(self):
        lang = self.cfg.get("language", "fr")
        t = TRANSLATIONS[lang]
        if not messagebox.askyesno(t["set_park_here"], t["msg_set_park_confirm"]):
            return
        r = self.mount.set_park_position()
        self._logw(f":hQ#  -> {r}","tx")
        if r == "1":
            self._status(t["msg_set_park_ok"])
        else:
            messagebox.showwarning(t["set_park_here"], t["msg_set_park_fail"])

    def _sync(self):
        lang = self.cfg.get("language", "fr")
        try:
            ra=Astro.parse_ra(self._sv["tgt_ra"].get())
            dec=Astro.parse_dec(self._sv["tgt_dec"].get())
        except:
            messagebox.showwarning(TRANSLATIONS[lang]["sync_frame"], TRANSLATIONS[lang]["msg_sync_invalid"]); return
        resp=self.mount.sync(ra,dec)
        self._logw(f"Sync RA{Astro.fmt_ra(ra)} → {resp}","tx")
        self._status("Synchronisation effectuée." if lang == "fr" else "Synchronization completed.")

    def _spd_change(self, v):
        spd=round(float(v)*2)/2; self._splbl.configure(text=f"{spd:.1f}°/s")
        self.mount.set_speed(spd)

    def _do_goto(self, ra, dec, name=""):
        lang = self.cfg.get("language", "fr")
        if not self.mount.state.connected:
            messagebox.showwarning("GoTo", TRANSLATIONS[lang]["msg_goto_not_connected"]); return
        if name.split()[0] in ("Soleil", "Sun"):
            messagebox.showerror("GoTo", TRANSLATIONS[lang]["msg_goto_sun"]); return
        lat=self.cfg.get("latitude",45.764); lon=self.cfg.get("longitude",4.836)
        lst=Astro.lst(datetime.now(timezone.utc),lon)
        az,alt=Astro.eq_to_horiz(*Astro.precess(ra,dec),lst,lat)
        if alt<self.cfg.get("alt_min_deg",2.0):
            messagebox.showwarning("GoTo", TRANSLATIONS[lang]["msg_goto_below_horizon"].format(name=name, alt=alt)); return
        self._sv["tgt_ra"].set(Astro.fmt_ra_lx(ra))
        self._sv["tgt_dec"].set(Astro.fmt_dec_lx(dec))
        self._logw(f"GoTo {name}  RA{Astro.fmt_ra(ra)} Dec{Astro.fmt_dec(dec)}","tx")
        self._status(f"GoTo {name}…")
        if self._guide_win: self._guide_win.pause_for_goto()
        resp=self.mount.goto(ra,dec)
        if resp.startswith("0"):
            self._goto_target=(ra,dec,name)
            self._logw(f"GoTo accepté  Az{az:.1f}° Alt{alt:.1f}°","rx")
            self._sky.center_on(az,alt)
            if self._photo_win: self._photo_win.after_goto()   # astrométrie et correction si l'option est cochée
        else:
            self._logw(f"GoTo refusé : {resp}","err")
            messagebox.showwarning("GoTo", TRANSLATIONS[lang]["msg_goto_rejected"].format(resp=resp))

    def _goto_manual(self):
        lang = self.cfg.get("language", "fr")
        try:
            ra=Astro.parse_ra(self._sv["tgt_ra"].get())
            dec=Astro.parse_dec(self._sv["tgt_dec"].get())
        except:
            messagebox.showerror("GoTo", TRANSLATIONS[lang]["msg_goto_invalid_format"]); return
        self._do_goto(ra,dec,"Manuel" if lang == "fr" else "Manual")

    def _goto_sel(self):
        lang = self.cfg.get("language", "fr")
        obj=self._sel_obj()
        if not obj: messagebox.showwarning("GoTo", TRANSLATIONS[lang]["msg_goto_select_obj"]); return
        self._do_goto(obj["ra"],obj["dec"],obj["name"])

    # ════════════════════════════════════════════════════════════
    #  CATALOGUE
    # ════════════════════════════════════════════════════════════
    def _load_cat(self):
        lang = self.cfg.get("language", "fr")
        cat_f=self._sv["filt"].get(); mag=self._dv["mag"].get()
        srch=self._sv["search"].get().lower().strip()
        self._maglbl.configure(text=f"{mag:.1f}")
        objs=[]
        lat=self.cfg.get("latitude",45.764); lon=self.cfg.get("longitude",4.836)
        cats=dict(ALL_CATALOGS); cats[SOLAR_SYSTEM_CAT]=solar_system(lat,lon)
        if cat_f in ("Tous", "All"):
            seen=set()
            for n,lst in cats.items():
                for o in lst:
                    if o["key"] in seen: continue      # M31 = NGC 224 = ... : une seule ligne
                    seen.add(o["key"]); objs.append((n,o))
        else:
            for o in cats.get(cat_f,[]):
                objs.append((cat_f,o))
        filt=[(n,o) for n,o in objs if (o["mag"] is None or o["mag"]<=mag or o["type"]=="Sol")
              and (not srch or srch in o["name"].lower() or srch in o.get("alias",""))]
        self._all_objs=filt
        self._tree.delete(*self._tree.get_children())
        
        type_names_map = TYPE_NAMES_BILINGUAL.get(lang, TYPE_NAMES_BILINGUAL["fr"])
        for n,o in filt:
            self._tree.insert("","end",iid=str(id(o)),
                values=(o["name"],type_names_map.get(o["type"],o["type"]),
                        fmt_mag(o["mag"]),Astro.fmt_ra_lx(o["ra"])[:8],
                        Astro.fmt_dec_lx(o["dec"])[:9]),tags=(o["type"],))
        for t,c in TYPE_COLORS.items(): self._tree.tag_configure(t,foreground=c)
        self._sky.set_objects([o for _,o in filt])
        self._sky.set_mag(mag)
        
        obj_count_str = f"{len(filt)} objets" if lang == "fr" else f"{len(filt)} objects"
        self._status(obj_count_str)

    def _sort(self, col):
        data=[(self._tree.set(k,col),k) for k in self._tree.get_children("")]
        try: data.sort(key=lambda x:float(x[0]))
        except: data.sort(key=lambda x:x[0].lower())
        for i,(_,k) in enumerate(data): self._tree.move(k,"",i)

    def _sel_obj(self):
        sel=self._tree.selection()
        if not sel: return None
        iid=sel[0]
        for _,o in self._all_objs:
            if str(id(o))==iid: return o
        return None

    def _on_sel(self, event):
        lang = self.cfg.get("language", "fr")
        obj=self._sel_obj()
        if not obj: return
        self._sv["tgt_ra"].set(Astro.fmt_ra_lx(obj["ra"]))
        self._sv["tgt_dec"].set(Astro.fmt_dec_lx(obj["dec"]))
        lat=self.cfg.get("latitude",45.764); lon=self.cfg.get("longitude",4.836)
        lst=Astro.lst(datetime.now(timezone.utc),lon)
        az,alt=Astro.eq_to_horiz(*Astro.precess(obj["ra"],obj["dec"]),lst,lat)
        self._sky.set_selected(obj)
        
        vis = (TRANSLATIONS[lang]["visible"] if alt > self.cfg.get("alt_min_deg", 2.0)
               else TRANSLATIONS[lang]["below_horizon"])
        
        type_names_map = TYPE_NAMES_BILINGUAL.get(lang, TYPE_NAMES_BILINGUAL["fr"])
        type_name = type_names_map.get(obj["type"], obj["type"])
        self._set_info(
            f"{obj['name']}\n"
            f"{TRANSLATIONS[lang]['info_type']}{type_name}\n"
            f"{TRANSLATIONS[lang]['info_mag']}{fmt_mag(obj['mag'])}\n"
            f"RA    : {Astro.fmt_ra(obj['ra'])}  (J2000)\n"
            f"Dec   : {Astro.fmt_dec(obj['dec'])}\n"
            f"Az    : {az:.1f}°   Alt : {alt:.1f}°\n"
            f"{vis}\n{TRANSLATIONS[lang]['info_dbl_click']}")

    # ════════════════════════════════════════════════════════════
    #  CARTE DU CIEL — clics
    # ════════════════════════════════════════════════════════════
    def _map_obj_click(self, obj):
        lang = self.cfg.get("language", "fr")
        self._on_sel_obj(obj)
        if messagebox.askyesno("GoTo", TRANSLATIONS[lang]["msg_goto_confirm"].format(name=obj['name'])):
            self._do_goto(obj["ra"],obj["dec"],obj["name"])

    def _on_sel_obj(self, obj):
        lang = self.cfg.get("language", "fr")
        lat=self.cfg.get("latitude",45.764); lon=self.cfg.get("longitude",4.836)
        lst=Astro.lst(datetime.now(timezone.utc),lon)
        az,alt=Astro.eq_to_horiz(*Astro.precess(obj["ra"],obj["dec"]),lst,lat)
        type_names_map = TYPE_NAMES_BILINGUAL.get(lang, TYPE_NAMES_BILINGUAL["fr"])
        self._sv["tgt_ra"].set(Astro.fmt_ra_lx(obj["ra"]))
        self._sv["tgt_dec"].set(Astro.fmt_dec_lx(obj["dec"]))
        self._sky.set_selected(obj)
        self._set_info(f"{obj['name']}\nAz {az:.1f}°  Alt {alt:.1f}°\n"
                       f"Mag {fmt_mag(obj['mag'])}  {type_names_map.get(obj['type'],'')}\n"
                       f"RA {Astro.fmt_ra(obj['ra'])}  Dec {Astro.fmt_dec(obj['dec'])} (J2000)")

    def _map_sky_click(self, az, alt, ra, dec):
        self._sv["tgt_ra"].set(Astro.fmt_ra_lx(ra))
        self._sv["tgt_dec"].set(Astro.fmt_dec_lx(dec))
        self._status(f"Az {az:.1f}°  Alt {alt:.1f}°  |  RA {Astro.fmt_ra(ra)}  Dec {Astro.fmt_dec(dec)}")

    def _map_mag(self):
        m=self._dv["mapm"].get(); self._sky.set_mag(m); self.cfg.set("skymap_mag_limit",m)

    # ════════════════════════════════════════════════════════════
    #  DÉROTATEUR
    # ════════════════════════════════════════════════════════════
    def _toggle_derot(self):
        self.derot.enable(self._bv["derot_en"].get())

    # ════════════════════════════════════════════════════════════
    #  CALLBACKS ÉTAT
    # ════════════════════════════════════════════════════════════
    def _on_mount(self, st):
        def _ui():
            lang = self.cfg.get("language", "fr")
            ra2000, dec2000 = Astro.precess(st.ra_h, st.dec_d, inverse=True)
            self._rv["ra"].set(Astro.fmt_ra(ra2000))
            self._rv["dec"].set(Astro.fmt_dec(dec2000))
            az, alt = self._scope_altaz(st)
            self._rv["az"].set(f"{az:06.2f}°")
            self._rv["alt"].set(f"{alt:+06.2f}°")
            self._rv["lst"].set(Astro.fmt_ra_lx(st.lst_h))
            if st.tracking: self._tbtn.configure(text=TRANSLATIONS[lang]["btn_track_on"],style="GoTo.TButton")
            else:           self._tbtn.configure(text=TRANSLATIONS[lang]["btn_track_off"],style="TButton")
            parts=[]; col=DIM
            if st.slewing:   parts.append(TRANSLATIONS[lang]["state_slewing"]); col=ACC
            if st.tracking:  parts.append(TRANSLATIONS[lang]["state_tracking"]); col=GRN
            if st.limit_hit: parts.append(TRANSLATIONS[lang]["state_limit"]); col=RED
            self._rv["state"].set(" | ".join(parts) or TRANSLATIONS[lang]["state_idle"])
            self._stlbl.configure(fg=col)
            self._sky.update_mount(az,alt,st.ra_h,st.dec_d,
                                   st.tracking,st.slewing,st.lst_h,connected=st.connected)
            self._sky.refresh(follow=self._bv["follow"].get())
        self.after(0,_ui)

    def _on_derot(self, dr):
        def _ui():
            self._rv["derot_ang"].set(f"{dr.angle:+.1f}°")
            self._rv["derot_pa"].set(f"{dr.pa:+.1f}°" if not self._derot_eq else "—")
        self.after(0,_ui)

    # ════════════════════════════════════════════════════════════
    #  PARAMÈTRES
    # ════════════════════════════════════════════════════════════
    def _settings(self):
        lang = self.cfg.get("language", "fr")
        win=tk.Toplevel(self); win.title(TRANSLATIONS[lang]["settings_title"])
        win.geometry("520x640"); win.configure(bg=BG2); win.grab_set()
        nb=ttk.Notebook(win); nb.pack(fill=tk.BOTH,expand=True,padx=8,pady=8)

        # Onglet Site
        ts=tk.Frame(nb,bg=BG2); nb.add(ts,text=TRANSLATIONS[lang]["tab_site"])
        fs=[(TRANSLATIONS[lang]["set_site_name"],"site_name",str),
            (TRANSLATIONS[lang]["set_latitude"],"latitude",float),
            (TRANSLATIONS[lang]["set_longitude"],"longitude",float),
            (TRANSLATIONS[lang]["set_altitude"],"altitude_m",int)]
        svs={}
        for i,(lbl,k,t) in enumerate(fs):
            tk.Label(ts,text=lbl+" :",bg=BG2,fg=DIM,font=FS).grid(row=i,column=0,sticky="w",padx=10,pady=7)
            v=tk.StringVar(value=str(self.cfg.get(k,"")));svs[k]=(v,t)
            ttk.Entry(ts,textvariable=v,font=FL,width=20).grid(row=i,column=1,padx=10,pady=7,sticky="ew")
        ts.columnconfigure(1,weight=1)

        def auto_detect_gps():
            btn_gps.config(state="disabled")
            import urllib.request
            import json
            
            lat, lon = None, None
            # Essai 1 : ip-api.com
            try:
                req = urllib.request.Request("http://ip-api.com/json/", headers={"User-Agent": "GotoMega/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    data = json.loads(response.read().decode())
                    if data.get("status") == "success":
                        lat = float(data["lat"])
                        lon = float(data["lon"])
            except:
                pass

            # Essai 2 (fallback) : ipapi.co
            if lat is None or lon is None:
                try:
                    req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "GotoMega/1.0"})
                    with urllib.request.urlopen(req, timeout=3.0) as response:
                        data = json.loads(response.read().decode())
                        if "latitude" in data and "longitude" in data:
                            lat = float(data["latitude"])
                            lon = float(data["longitude"])
                except:
                    pass

            if lat is not None and lon is not None:
                svs["latitude"][0].set(f"{lat:.6f}")
                svs["longitude"][0].set(f"{lon:.6f}")
                messagebox.showinfo(TRANSLATIONS[lang]["set_auto_gps"].replace(" 🛰", ""), TRANSLATIONS[lang]["set_gps_ok"].format(lat=lat, lon=lon))
            else:
                messagebox.showerror(TRANSLATIONS[lang]["set_auto_gps"].replace(" 🛰", ""), TRANSLATIONS[lang]["set_gps_err"])
            
            btn_gps.config(state="normal")

        gps_frame = tk.Frame(ts, bg=BG2)
        gps_frame.grid(row=len(fs), column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        btn_gps = ttk.Button(gps_frame, text=TRANSLATIONS[lang]["set_auto_gps"], command=auto_detect_gps)
        btn_gps.pack(fill="x", pady=4)

        # Onglet Mécanique
        tm=tk.Frame(nb,bg=BG2); nb.add(tm,text=TRANSLATIONS[lang]["tab_mech"])
        fm=[(TRANSLATIONS[lang]["set_steps_per_rev"],"steps_per_rev_motor",int),
            (TRANSLATIONS[lang]["set_microstep"],"microstep",int),
            (TRANSLATIONS[lang]["set_mount_type"],"mount_type",str),
            (TRANSLATIONS[lang]["set_gear_az"],"gear_ratio_az",float),
            (TRANSLATIONS[lang]["set_gear_alt"],"gear_ratio_alt",float),
            (TRANSLATIONS[lang]["set_slew_speed"],"slew_speed_default",float),
            (TRANSLATIONS[lang]["set_max_speed"],"slew_speed_max",float),
            (TRANSLATIONS[lang]["set_min_alt"],"alt_min_deg",float),
            (TRANSLATIONS[lang]["set_max_alt"],"alt_max_deg",float),
            (TRANSLATIONS[lang]["set_limit_az"],"az_limit_deg",float)]
        mms={}
        self._spdinf_az=None
        self._spdinf_alt=None
        for i,(lbl,k,t) in enumerate(fm):
            tk.Label(tm,text=lbl+" :",bg=BG2,fg=DIM,font=FS).grid(row=i,column=0,sticky="w",padx=10,pady=5)
            v=tk.StringVar(value=str(self.cfg.get(k,"")));mms[k]=(v,t)
            if k == "mount_type":
                cb = ttk.Combobox(tm, textvariable=v, values=["AltAz", "ForkEq", "GermanEq"], state="readonly", font=FL, width=12)
                cb.grid(row=i,column=1,padx=10,pady=5,sticky="ew")
            elif k == "microstep":
                cb = ttk.Combobox(tm, textvariable=v, values=["1", "2", "4", "8", "10", "16", "20", "25", "32", "40", "50", "64", "80", "100", "125", "128", "250", "256"], state="readonly", font=FL, width=12)
                cb.grid(row=i,column=1,padx=10,pady=5,sticky="ew")
            else:
                ttk.Entry(tm,textvariable=v,font=FL,width=12).grid(row=i,column=1,padx=10,pady=5,sticky="ew")
            if k in ("gear_ratio_az", "gear_ratio_alt"):
                tk.Label(tm,text=TRANSLATIONS[lang]["set_steps_deg"],bg=BG2,fg=DIM,font=FS).grid(row=i,column=2,padx=4)
                gr_val = self.cfg.get(k, 750.0)
                s = self.cfg.get("steps_per_rev_motor", 200)
                ms = self.cfg.get("microstep", 32)
                lbl_obj = tk.Label(tm,text=f"{s * ms * gr_val / 360.0:.0f}", bg=BG2,fg=ACC,font=FS)
                lbl_obj.grid(row=i,column=3,padx=4)
                if k == "gear_ratio_az":
                    self._spdinf_az = lbl_obj
                else:
                    self._spdinf_alt = lbl_obj
        tm.columnconfigure(1,weight=1)

        # Onglet Connexion
        tc=tk.Frame(nb,bg=BG2); nb.add(tc,text=TRANSLATIONS[lang]["tab_conn"])
        fc=[(TRANSLATIONS[lang]["set_port_mount"],"mount_port",str),
            (TRANSLATIONS[lang]["set_baud_mount"],"mount_baud",int),
            (TRANSLATIONS[lang]["set_port_derot"],"derot_port",str),
            (TRANSLATIONS[lang]["set_baud_derot"],"derot_baud",int)]
        ccs={}
        for i,(lbl,k,t) in enumerate(fc):
            tk.Label(tc,text=lbl+" :",bg=BG2,fg=DIM,font=FS).grid(row=i,column=0,sticky="w",padx=10,pady=8)
            v=tk.StringVar(value=str(self.cfg.get(k,"")));ccs[k]=(v,t)
            ttk.Entry(tc,textvariable=v,font=FL,width=16).grid(row=i,column=1,padx=10,pady=8,sticky="ew")
        rav=tk.BooleanVar(value=self.cfg.get("az_reversed",False))
        raltv=tk.BooleanVar(value=self.cfg.get("alt_reversed",False))
        rdv=tk.BooleanVar(value=self.cfg.get("derot_reversed",False))
        for i,(lbl,v) in enumerate([(TRANSLATIONS[lang]["set_rev_az"],rav),
                                    (TRANSLATIONS[lang]["set_rev_alt"],raltv),
                                    (TRANSLATIONS[lang]["set_rev_derot"],rdv)]):
            tk.Checkbutton(tc,text=lbl,variable=v,bg=BG2,fg=TXT,
                           selectcolor=BG3,activebackground=BG2).grid(
                row=len(fc)+i,column=0,columnspan=2,sticky="w",padx=10,pady=4)
        tc.columnconfigure(1,weight=1)

        def upd_spd(*_):
            try:
                s=int(mms["steps_per_rev_motor"][0].get())
                ms=int(mms["microstep"][0].get())
                if self._spdinf_az:
                    graz=float(mms["gear_ratio_az"][0].get())
                    self._spdinf_az.configure(text=f"{s*ms*graz/360:.0f}")
                if self._spdinf_alt:
                    gralt=float(mms["gear_ratio_alt"][0].get())
                    self._spdinf_alt.configure(text=f"{s*ms*gralt/360:.0f}")
            except: pass
        for k in ("steps_per_rev_motor","microstep","gear_ratio_az","gear_ratio_alt"):
            mms[k][0].trace_add("write",upd_spd)

        def save():
            for k,(v,t) in {**svs,**mms,**ccs}.items():
                try: self.cfg.set(k,t(v.get()))
                except: pass
            self.cfg.set("az_reversed",rav.get())
            self.cfg.set("alt_reversed",raltv.get())
            self.cfg.set("derot_reversed",rdv.get())
            # Mettre à jour lat/lon dans la carte
            self._sky._lat=self.cfg.get("latitude",45.764)
            self._sky._lon=self.cfg.get("longitude",4.836)
            self.cfg.save()
            self._logw(TRANSLATIONS[lang]["msg_saved"],"info")
            spd = self.cfg.get("slew_speed_default", 2.0)
            self._dv["speed"].set(spd)
            self._splbl.configure(text=f"{spd:.1f}°/s")
            if self.mount.state.connected:
                try: self.mount.set_speed(spd)
                except: pass
            win.destroy()

        bf=tk.Frame(win,bg=BG2); bf.pack(fill=tk.X,padx=8,pady=8)
        ttk.Button(bf,text=TRANSLATIONS[lang]["set_btn_save"],style="Acc.TButton",command=save).pack(side=tk.LEFT,padx=4)
        ttk.Button(bf,text=TRANSLATIONS[lang]["set_btn_cancel"],command=win.destroy).pack(side=tk.LEFT)

    # ════════════════════════════════════════════════════════════
    #  TICK HORLOGE
    # ════════════════════════════════════════════════════════════
    def _tick(self):
        lon=self.cfg.get("longitude",4.836)
        lst=Astro.lst(datetime.now(timezone.utc),lon)
        self._rv["lst"].set(Astro.fmt_ra_lx(lst))
        self._sky._lst=lst
        # Rafraîchir la carte seulement si la monture n'est pas connectée
        # (sinon _on_mount le fait)
        if not self.mount.state.connected:
            self._sky.update_mount(0, 0, 0, 0, False, False, lst, connected=False)
            self._sky.refresh()
        if (self.cfg.get("mount_type", "AltAz") != "AltAz") != self._derot_eq:
            self._refresh_devices()           # type de monture lu à la connexion ou changé dans les paramètres
        self.after(1000,self._tick)

    # ════════════════════════════════════════════════════════════
    #  FERMETURE
    # ════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════
    #  MODULE PHOTO (photo.py) : caméra, astrométrie, centrage
    # ════════════════════════════════════════════════════════════
    def _open_photo(self):
        if self._photo_win and self._photo_win.winfo_exists():
            self._photo_win.deiconify(); self._photo_win.lift(); return
        try:
            import photo
        except ImportError as e:
            messagebox.showerror("Photo", TRANSLATIONS[self.cfg.get("language", "fr")]["photo_missing"].format(err=e))
            return
        self._photo_win = photo.PhotoWindow(self, {"BG": BG, "BG2": BG2, "BG3": BG3, "TXT": TXT, "DIM": DIM,
                                                   "ACC": ACC, "GRN": GRN, "FS": FS})
        self._photo_win.bind("<Destroy>", lambda e: setattr(self, "_photo_win", None)
                             if e.widget is self._photo_win else None)

    def photo_pointing(self):
        """AD/Déc J2000 de la monture, ou None si elle n'est pas connectée."""
        st = self.mount.state
        return Astro.precess(st.ra_h, st.dec_d, inverse=True) if st.connected else None

    def photo_sky_center(self):
        return self._sky.center_radec()

    def photo_altaz_to_radec(self, az, alt):
        """Az/Alt maintenant -> AD/Déc J2000."""
        lst = Astro.lst(datetime.now(timezone.utc), self.cfg.get("longitude", 4.836))
        return Astro.precess(*Astro.horiz_to_eq(az, alt, lst, self.cfg.get("latitude", 45.764)), inverse=True)

    def photo_radec_to_altaz(self, ra, dec):
        """AD/Déc J2000 -> Az/Alt maintenant."""
        lst = Astro.lst(datetime.now(timezone.utc), self.cfg.get("longitude", 4.836))
        return Astro.eq_to_horiz(*Astro.precess(ra, dec), lst, self.cfg.get("latitude", 45.764))

    def photo_clear_model(self):
        """:CML efface les points de synchronisation du modèle (firmware Teensy)."""
        resp = self.mount._cmd(":CML")
        self.after(0, lambda: self._logw(f":CML  modèle de pointage effacé → {resp}", "tx"))
        return resp

    def photo_rotator_angle(self):
        return self.derot.angle if self.derot.connected else 0.0

    def photo_target(self):
        return self._goto_target

    def photo_slewing(self):
        return self.mount.state.slewing

    def photo_bright_stars(self):
        return [(ra, dec, mag) for ra, dec, mag, *_ in (CIEL.STARS if CIEL else [])]

    def photo_set_fov(self, fov):
        self._sky.set_camera_fov(fov)

    def photo_sync(self, ra, dec):
        """Synchronisation sur la position résolue (J2000), appelée depuis le fil du module photo."""
        resp = self.mount.sync(ra, dec)
        self.after(0, lambda: self._logw(f"Sync astrométrie  RA{Astro.fmt_ra(ra)} Dec{Astro.fmt_dec(dec)} → {resp}", "tx"))
        return resp

    def photo_goto(self, ra, dec, name):
        if self._guide_win: self._ui_call(self._guide_win.pause_for_goto)
        resp = self.mount.goto(ra, dec)
        self.after(0, lambda: self._logw(f"GoTo {name} (centrage)  RA{Astro.fmt_ra(ra)} Dec{Astro.fmt_dec(dec)} → {resp}",
                                         "tx" if resp.startswith("0") else "err"))
        return resp

    def photo_camera_name(self):
        w = self._photo_win
        return w.camera.name if w and w.camera else None

    def _ui_call(self, fn):
        """Appelle fn dans le fil de Tk et attend qu'elle soit faite (appel depuis un fil de travail)."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        done = threading.Event()
        self.after(0, lambda: (fn(), done.set()))
        done.wait(5)

    # ════════════════════════════════════════════════════════════
    #  MODULE DE GUIDAGE (guidage.py) : deuxième caméra, impulsions :Mg envoyées par le PC
    # ════════════════════════════════════════════════════════════
    def _open_guide(self):
        if self._guide_win and self._guide_win.winfo_exists():
            self._guide_win.deiconify(); self._guide_win.lift(); return
        try:
            import guidage
        except ImportError as e:
            messagebox.showerror("Guidage", TRANSLATIONS[self.cfg.get("language", "fr")]["photo_missing"].format(err=e))
            return
        self._guide_win = guidage.GuideWindow(self, {"BG": BG, "BG2": BG2, "BG3": BG3, "TXT": TXT, "DIM": DIM,
                                                     "ACC": ACC, "GRN": GRN, "FS": FS})
        self._guide_win.bind("<Destroy>", lambda e: setattr(self, "_guide_win", None)
                             if e.widget is self._guide_win else None)

    def guide_active(self):
        return bool(self._guide_win and self._guide_win.is_guiding())

    def guide_dither(self, px):
        return bool(self._guide_win and self._guide_win.dither(px))

    def guide_pulse(self, direction, ms):
        self.mount.pulse_guide(direction, ms)

    def guide_rate(self):
        return self.mount.guide_rate() if self.mount.state.connected else None

    def set_guide_rate(self, r):
        resp = self.mount.set_guide_rate(r) if self.mount.state.connected else ""
        self._logw(f":Rg{r:.2f}  vitesse de guidage → {resp}", "tx")
        return resp

    def guide_pier_side(self):
        """Côté du pilier (monture allemande seulement), pour savoir si la calibration vaut encore."""
        if self.cfg.get("mount_type", "AltAz") != "GermanEq" or not self.mount.state.connected:
            return None
        return self.mount._cmd(":Gm") or None

    def _quit(self):
        if self._guide_win: self._guide_win.close()
        if self._photo_win: self._photo_win.close()
        self.cfg.save(); self.focuser.disconnect(); self.derot.disconnect(); self.mount.disconnect()
        self.destroy()

    # ════════════════════════════════════════════════════════════
    #  DYNAMICAL UI TRANSLATION
    # ════════════════════════════════════════════════════════════
    def _translate_ui(self):
        lang = self.cfg.get("language", "fr")
        
        # 1. Window Title
        self.title(TRANSLATIONS[lang]["title"])
        
        # 2. Menu bar
        self._build_menu()
        
        # 3. Notebooks tabs
        self._nb_left.tab(0, text=TRANSLATIONS[lang]["control_tab"])
        self._nb_left.tab(1, text=TRANSLATIONS[lang]["cat_tab"])
        self._nb_left.tab(2, text=TRANSLATIONS[lang]["goto_tab"])
        
        self._nb_right.tab(0, text=TRANSLATIONS[lang]["derot_tab"])
        self._nb_right.tab(1, text=TRANSLATIONS[lang]["focus_tab"])
        self._nb_right.tab(2, text=TRANSLATIONS[lang]["log_tab"])
        
        # 4. Left Panel - Connexion / Control
        self._frm_conn.configure(text=f" {TRANSLATIONS[lang]['conn_frame']} ")
        self._lbl_port.configure(text=TRANSLATIONS[lang]["port"])
        self._lbl_baud.configure(text=TRANSLATIONS[lang]["baud"])
        self._chk_sim.configure(text=TRANSLATIONS[lang]["simulation"])
        self._btn_connect.configure(text=TRANSLATIONS[lang]["btn_connect"])
        self._btn_disconnect.configure(text=TRANSLATIONS[lang]["btn_disconnect"])
        
        # Position
        self._frm_pos.configure(text=f" {TRANSLATIONS[lang]['curr_pos_frame']} ")
        self._pos_lbl_widgets["ra"].configure(text=f"{TRANSLATIONS[lang]['pos_ra']:<7}")
        self._pos_lbl_widgets["dec"].configure(text=f"{TRANSLATIONS[lang]['pos_dec']:<7}")
        self._pos_lbl_widgets["az"].configure(text=f"{TRANSLATIONS[lang]['pos_az']:<7}")
        self._pos_lbl_widgets["alt"].configure(text=f"{TRANSLATIONS[lang]['pos_alt']:<7}")
        self._pos_lbl_widgets["lst"].configure(text=f"{TRANSLATIONS[lang]['pos_lst']:<7}")
        
        # Commandes
        self._frm_cmd.configure(text=f" {TRANSLATIONS[lang]['commands_frame']} ")
        if self.mount.state.tracking:
            self._tbtn.configure(text=TRANSLATIONS[lang]["btn_track_on"], style="GoTo.TButton")
        else:
            self._tbtn.configure(text=TRANSLATIONS[lang]["btn_track_off"], style="TButton")
        self._btn_stop.configure(text=TRANSLATIONS[lang]["btn_stop"])
        self._lbl_speed.configure(text=TRANSLATIONS[lang]["speed"])
        self._btn_park.configure(text=TRANSLATIONS[lang]["parking_north"])
        self._btn_setpark.configure(text=TRANSLATIONS[lang]["set_park_here"])
        
        # État monture
        self._frm_state.configure(text=f" {TRANSLATIONS[lang]['mount_state_frame']} ")
        if not self.mount.state.connected:
            self._rv["state"].set(TRANSLATIONS[lang]["ready"])
        
        # 5. Left Panel - Catalog Tab
        self._lbl_cat.configure(text=TRANSLATIONS[lang]["cat_filter"])
        self._lbl_mag_max.configure(text=TRANSLATIONS[lang]["mag_limit_lbl"])
        
        # Combobox of filter update
        cats = [TRANSLATIONS[lang]["all_filter"]] + list(ALL_CATALOGS.keys())
        current_val = self._sv["filt"].get()
        if current_val in ("Tous", "All"):
            self._sv["filt"].set(TRANSLATIONS[lang]["all_filter"])
        self._cb_cat.configure(values=cats)
        
        # Treeview Headings
        self._tree.heading("Nom", text=TRANSLATIONS[lang]["col_name"])
        self._tree.heading("Type", text=TRANSLATIONS[lang]["col_type"])
        self._tree.heading("Mag", text=TRANSLATIONS[lang]["col_mag"])
        self._tree.heading("RA", text=TRANSLATIONS[lang]["col_ra"])
        self._tree.heading("Dec", text=TRANSLATIONS[lang]["col_dec"])
        
        # Treeview content reload to translate types in-place
        self._load_cat()
        
        self._btn_goto_sel.configure(text=TRANSLATIONS[lang]["btn_goto_sel"])
        
        # 6. Left Panel - GoTo/Sync Tab
        self._frm_manual.configure(text=f" {TRANSLATIONS[lang]['tgt_coords_frame']} ")
        self._lbl_manual_coords[0][0].configure(text=TRANSLATIONS[lang]["lbl_tgt_ra_lbl"])
        self._lbl_manual_coords[1][0].configure(text=TRANSLATIONS[lang]["lbl_tgt_dec_lbl"])
        self._btn_goto_manual.configure(text=TRANSLATIONS[lang]["btn_goto"])
        
        self._frm_sel_obj.configure(text=f" {TRANSLATIONS[lang]['obj_desc_frame']} ")
        self._frm_sync.configure(text=f" {TRANSLATIONS[lang]['sync_frame']} ")
        self._lbl_sync.configure(text=TRANSLATIONS[lang]["sync_desc"])
        self._btn_sync.configure(text=TRANSLATIONS[lang]["btn_sync"])
        
        # 7. Center Panel
        self._lbl_sky_title.configure(text=TRANSLATIONS[lang]["sky_title"])
        self._lbl_sky_mag.configure(text=TRANSLATIONS[lang]["sky_mag_lbl"])
        self._btn_zenith.configure(text=TRANSLATIONS[lang]["btn_zenith"])
        self._btn_scope.configure(text=TRANSLATIONS[lang]["btn_scope"])
        self._btn_photo.configure(text=TRANSLATIONS[lang]["btn_photo"])
        self._btn_guide.configure(text=TRANSLATIONS[lang]["btn_guide"])
        self._chk_follow.configure(text=TRANSLATIONS[lang]["follow_short"])
        self._lbl_search_icon.configure(text=TRANSLATIONS[lang]["search_lbl"])
        self._set_update_badge()
        self._sky.redraw()
        
        # 8. Right Panel - Derotator
        self._frm_derot_conn.configure(text=f" {TRANSLATIONS[lang]['derot_conn_frame']} ")
        self._lbl_derot_port.configure(text=TRANSLATIONS[lang]["port"])
        self._lbl_derot_type.configure(text=TRANSLATIONS[lang]["type_lbl"])
        self._lbl_derot_ppd.configure(text=TRANSLATIONS[lang]["ppd_lbl"])
        self._frm_focus_conn.configure(text=f" {TRANSLATIONS[lang]['focus_frame']} ")
        self._lbl_focus_type.configure(text=TRANSLATIONS[lang]["type_lbl"])
        self._frm_focus_state.configure(text=f" {TRANSLATIONS[lang]['derot_state_frame']} ")
        self._lbl_focus_pos_w[0].configure(text=TRANSLATIONS[lang]["focus_pos"])
        self._lbl_focus_pos_w[1].configure(text=TRANSLATIONS[lang]["focus_temp"])
        self._frm_focus_move.configure(text=f" {TRANSLATIONS[lang]['focus_move_frame']} ")
        self._lbl_focus_steps.configure(text=TRANSLATIONS[lang]["focus_steps"])
        self._lbl_focus_goto.configure(text=TRANSLATIONS[lang]["focus_goto"])
        self._refresh_devices()
        
        self._frm_derot_state.configure(text=f" {TRANSLATIONS[lang]['derot_state_frame']} ")
        self._lbl_derot_ang.configure(text=TRANSLATIONS[lang]["phys_angle"])
        self._lbl_derot_pa.configure(text=TRANSLATIONS[lang]["field_angle"])
        
        self._frm_derot_comp.configure(text=f" {TRANSLATIONS[lang]['derot_comp_frame']} ")
        self._chk_derot_en.configure(text=TRANSLATIONS[lang]["derot_comp_enable"])
        
        self._frm_derot_manual.configure(text=f" {TRANSLATIONS[lang]['derot_ctrl_manual']} ")
        self._lbl_derot_goto.configure(text=TRANSLATIONS[lang]["derot_goto"])
        self._lbl_derot_offset.configure(text=TRANSLATIONS[lang]["derot_offset"])
        
        # 9. Right Panel - Log
        self._frm_log.configure(text=f" {TRANSLATIONS[lang]['log_frame']} ")
        self._btn_clear_log.configure(text=TRANSLATIONS[lang]["btn_clear"])
        self._btn_save_log.configure(text=TRANSLATIONS[lang]["btn_save"])

    # ════════════════════════════════════════════════════════════
    #  CLAVIER, VUE, MISE À JOUR
    # ════════════════════════════════════════════════════════════
    def _on_key(self, e):
        """Échap : STOP partout. Flèches et +/- : déplacer et zoomer la carte, hors champs de saisie."""
        if e.keysym == "Escape":
            self._stop(); return
        cls = e.widget.winfo_class() if hasattr(e.widget, "winfo_class") else ""
        if cls in ("Entry", "TEntry", "TSpinbox", "Spinbox", "TCombobox", "Text", "Treeview", "Canvas"):
            return          # la carte gère elle-même ses touches quand elle a le focus
        moves = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, 1), "Down": (0, -1)}
        if e.keysym in moves: self._sky.pan(*moves[e.keysym])
        elif e.keysym in ("plus", "KP_Add", "equal"): self._sky.zoom(0.8)
        elif e.keysym in ("minus", "KP_Subtract"): self._sky.zoom(1.25)

    def _toggle_follow(self):
        self.cfg.set("skymap_follow", self._bv["follow"].get())
        if self._bv["follow"].get(): self._center_scope()

    def _center_scope(self):
        st = self.mount.state
        if st.connected: self._sky.center_on(*self._scope_altaz(st))

    def _scope_altaz(self, st):
        """Azimut et hauteur du télescope. En AltAz, :GBE les donne directement. En équatorial
        (ForkEq, GermanEq), :GBE donne les angles des axes (angle horaire, déclinaison) : on
        repart alors de l'AD/Déc de la monture (coordonnées de la date). Sans cela, le réticule
        partait loin de l'objet pointé et le GoTo semblait ne pas marcher."""
        if self.cfg.get("mount_type", "AltAz") == "AltAz" or st.sim_mode:
            return st.az_d, st.alt_d
        return Astro.eq_to_horiz(st.ra_h, st.dec_d, st.lst_h, self.cfg.get("latitude", 45.764))

    def _check_update(self, manual=False):
        """Vérifie en arrière-plan si une version plus récente est sur GitHub."""
        app_dir = Path(__file__).resolve().parent
        if not manual:
            mise_a_jour.register(app_dir)          # entrées du menu des applications
        try:
            available, remote, _ = mise_a_jour.check(app_dir)
        except Exception as e:
            if manual:
                self.after(0, lambda err=str(e): messagebox.showerror(
                    "GotoAndrivet", TRANSLATIONS[self.cfg.get("language", "fr")]["update_error"].format(err=err)))
            return
        def _ui():
            t = TRANSLATIONS[self.cfg.get("language", "fr")]
            self._update_sha = remote if available else None
            self._set_update_badge()
            if manual and available: self._do_update()
            elif manual: messagebox.showinfo("GotoAndrivet", t["update_none"])
        self.after(0, _ui)

    def _set_update_badge(self):
        t = TRANSLATIONS[self.cfg.get("language", "fr")]
        if self._update_sha:
            self._btn_update.configure(image=self._upd_dot, text=" " + t["update_btn_new"], fg="#ff9a90")
        else:
            self._btn_update.configure(image=self._upd_nodot, text=" " + t["update_btn"], fg=TXT)

    def _update_clicked(self):
        """Pastille rouge : installer la mise à jour. Sinon : vérifier tout de suite sur GitHub."""
        if self._update_sha:
            self._do_update()
        else:
            threading.Thread(target=self._check_update, args=(True,), daemon=True).start()

    def _do_update(self):
        if not self._update_sha: return
        t = TRANSLATIONS[self.cfg.get("language", "fr")]
        if not messagebox.askyesno("GotoAndrivet", t["update_confirm"]): return
        self._status(t["update_running"]); self.update()
        try:
            mise_a_jour.apply(Path(__file__).resolve().parent, self._update_sha)
        except Exception as e:
            messagebox.showerror("GotoAndrivet", t["update_error"].format(err=e)); return
        messagebox.showinfo("GotoAndrivet", t["update_done"])
        self.mount.disconnect(); self.cfg.save()
        mise_a_jour.restart()

    def _about(self):
        t = TRANSLATIONS[self.cfg.get("language", "fr")]
        ver = mise_a_jour.local_version(Path(__file__).resolve().parent)[:7] or "?"
        messagebox.showinfo(t["about"], t["about_text"].format(version=ver))

    def change_language(self, lang):
        self.cfg.set("language", lang)
        self.cfg.save()
        self._translate_ui()


# ================================================================
#  POINT D'ENTRÉE
# ================================================================
if __name__ == "__main__":
    app = App()
    app.mainloop()
