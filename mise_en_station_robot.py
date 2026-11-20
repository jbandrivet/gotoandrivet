"""Mise en station robotisée de GotoAndrivet.

La carte pcb/mise_en_station (Arduino Nano, firmware mise_en_station/mise_en_station.ino) tourne
les deux vis de réglage de la monture : azimut et hauteur. Ce module :

- parle à la carte par l'USB (classe CarteMES) ;
- mesure l'axe de la monture avec la caméra : trois images en tournant seulement l'axe d'AD, l'axe
  est la normale au plan des trois pointages, dans le repère du lieu (Est, Nord, Zénith) ;
- compare cet axe au pôle (vrai, ou relevé par la réfraction) : erreur en azimut et en hauteur ;
- calibre les moteurs (un petit mouvement de chacun, mesuré par la caméra) puis corrige en boucle
  jusqu'à ce que l'erreur passe sous la tolérance. Après chaque mouvement, une nouvelle image donne la
  rotation réellement faite par la monture : l'axe est mis à jour sans refaire les trois images.

Sans carte, la même mesure sert à régler les vis à la main (bouton « Mesurer l'erreur »).
Le suivi peut rester en marche : la rotation de l'axe d'AD entre deux images est prise en compte.

Tout le calcul est fait sans interface : essai_mise_en_station.py le vérifie face à l'émulateur de la
carte et à une monture simulée. L'onglet « Mise en station » du module photo (photo.py) s'en sert.
"""
import math
import time
from datetime import datetime, timezone

import numpy as np

OMEGA_SID = 2 * math.pi / 86164.0905          # rad/s
ARCMIN = math.pi / (180 * 60)


def _n(x, d=1, signe=False):
    """Nombre à la française : virgule décimale."""
    return (f"{x:+.{d}f}" if signe else f"{x:.{d}f}").replace(".", ",")

# ════════════════════════════════════════════════════════════════
#  GÉOMÉTRIE
# ════════════════════════════════════════════════════════════════

def jour_julien(t):
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp() / 86400.0 + 2440587.5


def temps_sideral(t, lon_est_deg):
    """Temps sidéral local en radians (GMST de l'UAI 1982, UT1 ≈ UTC)."""
    jd = jour_julien(t)
    T = (jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T * T - T ** 3 / 38710000.0
    return math.radians((gmst + lon_est_deg) % 360.0)


def precession(t):
    """Matrice J2000 -> équateur moyen de la date (UAI 1976)."""
    T = (jour_julien(t) - 2451545.0) / 36525.0
    a = math.radians(1 / 3600)
    zeta = (2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) * a
    z = (2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) * a
    theta = (2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) * a

    def rz(x):
        c, s = math.cos(x), math.sin(x)
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

    def ry(x):
        c, s = math.cos(x), math.sin(x)
        return np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])

    return rz(z) @ ry(theta) @ rz(zeta)


def vecteur(ra_h, dec_d):
    a, d = math.radians(ra_h * 15), math.radians(dec_d)
    return np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])


def radec(v):
    v = v / np.linalg.norm(v)
    return (math.degrees(math.atan2(v[1], v[0])) / 15) % 24, math.degrees(math.asin(max(-1, min(1, v[2]))))


def base_locale(t, lat_d, lon_d):
    """Lignes : vecteurs Est, Nord, Zénith exprimés dans l'équateur de la date."""
    th, ph = temps_sideral(t, lon_d), math.radians(lat_d)
    return np.array([[-math.sin(th), math.cos(th), 0.0],
                     [-math.sin(ph) * math.cos(th), -math.sin(ph) * math.sin(th), math.cos(ph)],
                     [math.cos(ph) * math.cos(th), math.cos(ph) * math.sin(th), math.sin(ph)]])


def j2000_vers_local(ra_h, dec_d, t, lat_d, lon_d):
    """AD/Déc J2000 (astrométrie) -> vecteur unitaire (Est, Nord, Zénith) à l'instant t."""
    return base_locale(t, lat_d, lon_d) @ (precession(t) @ vecteur(ra_h, dec_d))


def local_vers_j2000(v, t, lat_d, lon_d):
    return radec(precession(t).T @ (base_locale(t, lat_d, lon_d).T @ v))


def az_haut(v):
    """(azimut depuis le Nord vers l'Est, hauteur) en degrés d'un vecteur (Est, Nord, Zénith)."""
    v = v / np.linalg.norm(v)
    return math.degrees(math.atan2(v[0], v[1])) % 360, math.degrees(math.asin(max(-1, min(1, v[2]))))


def depuis_az_haut(az_d, h_d):
    a, h = math.radians(az_d), math.radians(h_d)
    return np.array([math.cos(h) * math.sin(a), math.cos(h) * math.cos(a), math.sin(h)])


def refraction_arcmin(h_d):
    """Réfraction (formule de Saemundsson, 10 °C, 1010 hPa) en minutes d'arc."""
    return 1.02 / math.tan(math.radians(h_d + 10.3 / (h_d + 5.11)))


def pole_vise(lat_d, refraction=False):
    """Direction visée pour l'axe : pôle céleste visible, relevé de la réfraction si demandé."""
    h = abs(lat_d) + (refraction_arcmin(abs(lat_d)) / 60 if refraction else 0.0)
    return depuis_az_haut(0.0 if lat_d >= 0 else 180.0, h)


def rotation(axe, angle):
    """Matrice de rotation (Rodrigues) d'angle `angle` (rad) autour de `axe`."""
    k = axe / np.linalg.norm(axe)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * K @ K


ZENITH = np.array([0.0, 0.0, 1.0])
EST = np.array([1.0, 0.0, 0.0])


def charniere(axe):
    """Axe de la vis de hauteur : horizontal et perpendiculaire à l'azimut de l'axe d'AD (la monture
    pivote sur sa charnière de latitude, qui n'est Est-Ouest qu'une fois l'azimut réglé)."""
    c = np.cross(axe, ZENITH)
    n = np.linalg.norm(c)
    return c / n if n > 1e-9 else EST


def reglage(a_arcmin, b_arcmin, axe):
    """Rotation de la monture : a autour de la verticale (vis d'azimut), b autour de la charnière
    (vis de hauteur, charniere(axe) avant le réglage). a > 0 tourne vers l'Ouest (vu de dessus) ;
    b > 0 relève l'axe."""
    return rotation(ZENITH, a_arcmin * ARCMIN) @ rotation(charniere(axe), b_arcmin * ARCMIN)


def _jacobien(v, axe):
    return np.column_stack([np.cross(ZENITH, v), np.cross(charniere(axe), v)]) * ARCMIN


def axe_par_plan(points):
    """Normale au plan des pointages (au moins 3), orientée vers le Nord céleste local (z > 0 au Nord)."""
    P = np.array(points)
    if len(P) < 3:
        raise ValueError("il faut au moins 3 images")
    c = P.mean(axis=0)
    _, s, vt = np.linalg.svd(P - c)
    n = vt[-1]
    if s[1] < 1e-3:
        raise ValueError("les images sont presque alignées : tournez davantage l'axe d'AD")
    return n / np.linalg.norm(n), s


def oriente(axe, lat_d):
    """L'axe pointé vers le pôle visible (au-dessus de l'horizon côté pôle)."""
    cible = pole_vise(lat_d)
    return axe if float(axe @ cible) > 0 else -axe


def erreur(axe, lat_d, refraction=False):
    """Erreur de l'axe par rapport au pôle visé.

    Renvoie un dictionnaire : az (′, > 0 = axe trop à l'Est), haut (′, > 0 = axe trop haut),
    total (′, angle entre l'axe et le pôle visé), et besoin = (a, b) en ′, la rotation de la
    monture (voir reglage) qui amène l'axe sur le pôle."""
    cible = pole_vise(lat_d, refraction)
    az_a, h_a = az_haut(axe)
    az_c, h_c = az_haut(cible)
    daz = ((az_a - az_c + 180) % 360) - 180
    total = math.degrees(math.acos(max(-1, min(1, float(axe @ cible))))) * 60
    # a, b tels que reglage(a, b) @ axe ≈ cible : moindres carrés sur la petite rotation, puis itération
    besoin = np.zeros(2)
    v = axe.copy()
    for _ in range(4):
        d, *_ = np.linalg.lstsq(_jacobien(v, axe), cible - v, rcond=None)
        besoin += d
        v = reglage(*besoin, axe) @ axe
    return {"az": daz * 60 * math.cos(math.radians(h_c)), "haut": (h_a - h_c) * 60, "total": total,
            "besoin": besoin, "az_axe": az_a, "haut_axe": h_a}


def pole_nord_local(lat_d):
    """Pôle Nord céleste dans le repère (Est, Nord, Zénith), sous l'horizon dans l'hémisphère Sud."""
    ph = math.radians(lat_d)
    return np.array([0.0, math.cos(ph), math.sin(ph)])


def rotation_mesuree(avant, apres, axe, dt, suivi, lat_d):
    """Rotation de la monture (a, b) en ′ entre deux pointages (vecteurs locaux) pris à dt secondes
    d'écart. Avec le suivi en marche, le télescope a aussi tourné autour de l'axe d'AD pendant dt,
    comme le ciel autour du pôle : −ω·dt autour de l'axe orienté vers le Nord céleste."""
    if suivi:
        nord = axe if float(axe @ pole_nord_local(lat_d)) > 0 else -axe
        avant = rotation(nord, -OMEGA_SID * dt) @ avant
    ab = np.zeros(2)
    for _ in range(4):          # petite rotation, puis affinage (mouvements de plusieurs degrés)
        v = reglage(*ab, axe) @ avant
        d, *_ = np.linalg.lstsq(_jacobien(v, axe), apres - v, rcond=None)
        ab = ab + d
    return ab


def conditionnement(pointage, axe):
    """Qualité de la mesure d'une rotation de la monture depuis ce pointage (1 = idéal, 0 = impossible).
    Près du zénith on ne voit pas la rotation en azimut, près de l'Est ou de l'Ouest pas celle en hauteur."""
    J = _jacobien(pointage, axe)
    s = np.linalg.svd(J, compute_uv=False)
    return float(s[-1] / s[0]) if s[0] > 0 else 0.0


def sens_en_mots(err, fr=True):
    """Conseil de réglage lisible : "Azimut : tourner vers l'Ouest de 12,3′ · Hauteur : descendre de 4,1′"."""
    def f(x):
        return f"{_n(abs(x), 1)}" + "′" if fr else f"{abs(x):.1f}′"
    if fr:
        az = "vers l'Ouest" if err["az"] > 0 else "vers l'Est"
        h = "descendre" if err["haut"] > 0 else "monter"
        return f"Azimut : tourner l'axe {az} de {f(err['az'])} · Hauteur : {h} de {f(err['haut'])}"
    az = "West" if err["az"] > 0 else "East"
    h = "lower" if err["haut"] > 0 else "raise"
    return f"Azimuth: turn the axis {az} by {f(err['az'])} · Altitude: {h} by {f(err['haut'])}"


# ════════════════════════════════════════════════════════════════
#  CARTE DE MISE EN STATION (USB)
# ════════════════════════════════════════════════════════════════

class ErreurCarte(RuntimeError):
    pass


REFUS = {"A": "12 V moteurs absent", "B": "fin de course de ce côté", "M": "axe déjà en mouvement",
         "P": "commande refusée"}
ARRETS = {0: "fin normale", 1: "fin de course", 2: "arrêt demandé", 3: "12 V moteurs perdu"}


class CarteMES:
    """Carte de mise en station : Arduino Nano à 38400 bauds, commandes :...# (voir le firmware)."""
    NOM = "GotoAndrivet-MES"

    def __init__(self, port, baud=38400, attente_reset=2.0, serie=None):
        import threading
        if serie is None:
            import serial
            serie = serial.Serial(port, baud, timeout=1.0)
            time.sleep(attente_reset)          # le Nano redémarre à l'ouverture du port
        self.s = serie
        self.port = port
        self._verrou = threading.Lock()
        self.s.reset_input_buffer()
        nom = ""
        for _ in range(3):
            nom = self.cmd(":GVP#")
            if nom == self.NOM:
                break
            time.sleep(0.3)
        if nom != self.NOM:
            self.s.close()
            raise ErreurCarte(f"{port} : ce n'est pas la carte de mise en station (réponse « {nom} »)")
        self.version = self.cmd(":GVN#")

    @staticmethod
    def ports():
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    def fermer(self):
        try:
            self.s.close()
        except Exception:
            pass

    def cmd(self, c, reponse=True):
        with self._verrou:
            self.s.write(c.encode("ascii"))
            if not reponse:
                return ""
            r = self.s.read_until(b"#")
        if not r.endswith(b"#"):
            raise ErreurCarte(f"pas de réponse de la carte à {c}")
        return r[:-1].decode("ascii", errors="replace")

    def etat(self):
        p = self.cmd(":GS#").split(",")
        if len(p) != 5:
            raise ErreurCarte(f"état illisible : {','.join(p)}")
        fc = tuple(ch == "1" for ch in p[2])
        return {"az": p[0] == "1", "haut": p[1] == "1", "fc": fc, "vm": int(p[3]) / 10.0, "arret": int(p[4])}

    def position(self, axe):
        return int(self.cmd(f":GP{axe}#"))

    def bouger(self, axe, pas):
        pas = int(pas)
        if pas == 0:
            return
        r = self.cmd(f":MR{axe}{pas:+d}#")
        if r != "1":
            raise ErreurCarte(f"mouvement {'azimut' if axe == 'A' else 'hauteur'} refusé : "
                              f"{REFUS.get(r[1:2], r)}")

    def stop(self):
        self.cmd(":Q#", reponse=False)

    def attendre(self, abort=None, delai=600.0):
        """Attend la fin des deux axes ; lève ErreurCarte si l'arrêt n'est pas normal."""
        t0 = time.time()
        while True:
            e = self.etat()
            if not e["az"] and not e["haut"]:
                if e["arret"] not in (0,):
                    raise ErreurCarte(f"mouvement interrompu : {ARRETS.get(e['arret'], e['arret'])}")
                return e
            if abort is not None and abort.is_set():
                self.stop()
                raise ErreurCarte("arrêté")
            if time.time() - t0 > delai:
                self.stop()
                raise ErreurCarte("mouvement trop long")
            time.sleep(0.15)

    def lire(self, axe, cle):
        return self.cmd(f":GC{axe}{cle}#")

    def ecrire(self, axe, cle, valeur):
        if self.cmd(f":SC{axe}{cle}{valeur}#") != "1":
            raise ErreurCarte(f"réglage {axe}{cle}={valeur} refusé")


# ════════════════════════════════════════════════════════════════
#  DÉROULEMENT
# ════════════════════════════════════════════════════════════════

class Arret(Exception):
    pass


class MiseEnStation:
    """Mesure et correction de la mise en station.

    mesurer()        -> (ra_h, dec_d J2000, datetime UTC du milieu de pose), ou None si interrompu
    tourner_ad(deg)  -> tourne l'axe d'AD seul d'environ deg degrés (le signe donne le sens)
    carte            -> CarteMES, ou None (réglage à la main guidé par « mesurer_erreur »)
    suivi()          -> True si le suivi sidéral est en marche (lu à chaque mesure)
    journal(texte)   -> affichage
    calibration      -> matrice 2 x 2 : (a, b) en ′ = M @ (pas azimut, pas hauteur), ou None
    """

    def __init__(self, lat, lon, mesurer, tourner_ad, carte=None, suivi=lambda: True,
                 journal=print, abort=None, refraction=False, calibration=None):
        self.lat, self.lon = lat, lon
        self.mesurer, self.tourner_ad, self.carte = mesurer, tourner_ad, carte
        self.suivi, self.journal, self.abort = suivi, journal, abort
        self.refraction = refraction
        self.M = None if calibration is None else np.array(calibration, dtype=float)
        self.axe = None
        self.dernier = None          # (vecteur local, datetime) du dernier pointage mesuré
        self.angle = 30.0            # rotation d'AD entre les images de la dernière mesure de l'axe
        self.historique = []         # erreurs totales successives (′)

    # ── outils ──
    def _stop(self):
        if self.abort is not None and self.abort.is_set():
            raise Arret()

    def _pointage(self):
        self._stop()
        m = self.mesurer()
        if m is None:
            raise Arret()
        ra, dec, t = m
        return j2000_vers_local(ra, dec, t, self.lat, self.lon), t

    def erreur(self):
        return erreur(self.axe, self.lat, self.refraction)

    def _dire_erreur(self, prefixe=""):
        e = self.erreur()
        self.historique.append(e["total"])
        self.journal(f"{prefixe}erreur {_n(e['total'], 1)}′ (azimut {_n(e['az'], 1, True)}′, hauteur {_n(e['haut'], 1, True)}′)")
        return e

    # ── 1. axe par trois images ──
    def mesurer_axe(self, angle=30.0, n=3):
        self.angle = angle
        pts = []
        for i in range(n):
            if i:
                self.journal(f"Rotation de l'axe d'AD de {angle:.0f}°…")
                self._stop()
                self.tourner_ad(angle)
            self.journal(f"Image {i + 1}/{n}…")
            v, t = self._pointage()
            pts.append(v)
        axe, s = axe_par_plan(pts)
        self.axe = oriente(axe, self.lat)
        self.dernier = (pts[-1], t)
        q, q0 = conditionnement(pts[-1], self.axe), conditionnement(pts[0], self.axe)
        if q < 0.25 and q0 > q + 0.1:
            # Vers l'Est ou l'Ouest, une image ne voit plus les réglages : retour au pointage de départ
            self.journal(f"Retour de l'axe d'AD au pointage de départ ({-angle * (n - 1):+.0f}°)…")
            self.tourner_ad(-angle * (n - 1))
            self.dernier = self._pointage()
            q = q0
        if q < 0.25:
            self.journal("Attention : ce pointage mesure mal les réglages (trop près du zénith, de l'Est ou de "
                         "l'Ouest). Mieux vaut commencer vers le méridien, entre 30° et 70° de hauteur.")
        return self._dire_erreur("Axe mesuré : ")

    # ── mise à jour après un réglage (moteurs ou à la main) ──
    def mesurer_erreur(self):
        """Nouvelle image : rotation faite par la monture depuis la précédente, axe mis à jour."""
        if self.axe is None:
            raise RuntimeError("mesurez d'abord l'axe (trois images)")
        v, t = self._pointage()
        v0, t0 = self.dernier
        ab = rotation_mesuree(v0, v, self.axe, (t - t0).total_seconds(), self.suivi(), self.lat)
        self.axe = reglage(*ab, self.axe) @ self.axe
        self.dernier = (v, t)
        return ab, self._dire_erreur()

    # ── 2. calibration des moteurs ──
    def calibrer(self, pas_essai=400, pas_max=200000, mesure_min=2.0):
        """Un mouvement de chaque moteur, mesuré par la caméra : M = rotation (′) par pas."""
        if self.carte is None:
            raise RuntimeError("carte de mise en station non connectée")
        if self.axe is None:
            raise RuntimeError("mesurez d'abord l'axe (trois images)")
        cols = []
        for axe, nom in (("A", "azimut"), ("L", "hauteur")):
            pas = int(pas_essai)
            while True:
                self.journal(f"Calibration {nom} : {pas} pas…")
                self.carte.bouger(axe, pas)
                self.carte.attendre(self.abort)
                time.sleep(1.0)
                ab, _ = self.mesurer_erreur()
                vu = math.hypot(*ab)
                if vu >= mesure_min or pas * 4 > pas_max:
                    break
                self.journal(f"Rotation trop petite ({_n(vu, 2)}′) : essai plus grand.")
                pas *= 4
            if vu < 0.2:
                raise RuntimeError(f"le moteur {nom} ne fait pas bouger la monture "
                                   f"(câblage, courant du driver, ou vis bloquée)")
            cols.append(ab / pas)
            self.journal(f"  {nom} : {_n(abs(1 / math.hypot(*(ab / pas))), 1)} pas par minute d'arc")
        self.M = np.column_stack(cols)
        if abs(np.linalg.det(self.M)) < 1e-12:
            raise RuntimeError("les deux moteurs font tourner la monture dans le même sens : vérifier le montage")
        try:      # gardé aussi dans la carte (pas par minute d'arc, signe compris)
            self.carte.ecrire("A", "K", f"{1 / self.M[0, 0]:.4f}" if self.M[0, 0] else "0")
            self.carte.ecrire("L", "K", f"{1 / self.M[1, 1]:.4f}" if self.M[1, 1] else "0")
        except Exception:
            pass
        return self.M

    # ── 3. correction automatique ──
    def corriger(self, tolerance=1.0, iterations=10, pas_max_arcmin=90.0, verifications=2):
        """Boucle : mouvement des deux moteurs vers le pôle, image, mise à jour. Renvoie l'erreur finale.

        Une image seule ne voit pas tout (charnière de latitude pas tout à fait perpendiculaire à l'axe,
        vis qui ne pousse pas exactement dans l'axe prévu) : sous la tolérance, l'axe est re-mesuré par
        trois images (en tournant l'AD dans l'autre sens, pour revenir près du départ) et la correction
        reprend si besoin."""
        if self.carte is None:
            raise RuntimeError("carte de mise en station non connectée")
        if self.axe is None:
            raise RuntimeError("mesurez d'abord l'axe (trois images)")
        if self.M is None:
            self.calibrer()
        e = self.erreur()
        for it in range(1, iterations + 1):
            if e["total"] <= tolerance and verifications > 0:
                verifications -= 1
                self.journal("Vérification : nouvelle mesure de l'axe par trois images…")
                e = self.mesurer_axe(-self.angle)
            if e["total"] <= tolerance:
                self.journal(f"Mise en station terminée : {_n(e['total'], 2)}′ (tolérance {format(tolerance, 'g').replace('.', ',')}′).")
                return e
            besoin = e["besoin"].copy()
            n = math.hypot(*besoin)
            if n > pas_max_arcmin:
                besoin *= pas_max_arcmin / n
            pas = np.linalg.solve(self.M, besoin)
            pa, pl = int(round(pas[0])), int(round(pas[1]))
            if pa == 0 and pl == 0:
                self.journal("Correction plus petite qu'un pas moteur : arrêt.")
                return e
            self.journal(f"Correction {it} : azimut {pa:+d} pas, hauteur {pl:+d} pas")
            if pa:
                self.carte.bouger("A", pa)
            if pl:
                self.carte.bouger("L", pl)
            self.carte.attendre(self.abort)
            time.sleep(1.0)            # vibrations
            ab, e = self.mesurer_erreur()
            # Mise à jour de Broyden : la calibration suit les vis (jeu, pas non linéaire)
            s = np.array([pa, pl], dtype=float)
            self.M = self.M + np.outer(ab - self.M @ s, s) / float(s @ s)
        self.journal(f"Tolérance non atteinte après {iterations} corrections : {_n(e['total'], 1)}′.")
        return e
