#!/usr/bin/env python3
"""Essai complet de la mise en station robotisée, sans matériel.

- le firmware mise_en_station.ino tourne dans l'émulateur PC (emulateur/emulateur.cpp, compilé ici),
  avec du jeu dans les vis et un 12 V réglable ;
- une monture simulée : axe d'AD mal réglé, vis reliées aux moteurs (pas par minute d'arc différents,
  signe inversé sur la hauteur, charnière de latitude faussée de 0,3°) ;
- l'« astrométrie » rend la vraie position du centre de l'image (J2000) avec 1″ de bruit.

On vérifie que mise_en_station_robot.py amène le VRAI axe sous la tolérance, avec ou sans suivi,
au Nord et au Sud, et que la carte refuse de bouger sans 12 V.

    python3 mise_en_station/essai_mise_en_station.py
"""
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))
import mise_en_station_robot as mes  # noqa: E402

ARCMIN = mes.ARCMIN


def compiler():
    sortie = os.path.join(tempfile.gettempdir(), f"mes_emulateur_{os.getuid()}")
    src = [os.path.join(ICI, "emulateur", "emulateur.cpp"), os.path.join(ICI, "mise_en_station.ino")]
    if not os.path.exists(sortie) or any(os.path.getmtime(f) > os.path.getmtime(sortie) for f in src):
        subprocess.run(["g++", "-O2", "-I", os.path.join(ICI, "emulateur"), "-o", sortie, src[0]], check=True)
    return sortie


class Emulateur:
    def __init__(self, exe, vm=12.0, jeu="A:30,L:20", fc=""):
        self.dir = tempfile.mkdtemp(prefix="mes_")
        self.etat = os.path.join(self.dir, "etat")
        env = dict(os.environ, MES_VM=str(vm), MES_JEU=jeu, MES_FC=fc, MES_ETAT=self.etat, MES_ACCEL="20",
                   MES_EEPROM=os.path.join(self.dir, "eeprom"))
        self.p = subprocess.Popen([exe], env=env, stderr=subprocess.PIPE, text=True)
        ligne = self.p.stderr.readline().split()
        self.port = ligne[1]

    def sorties(self):
        """Pas vus par la monture (après le jeu) : azimut, hauteur."""
        v = open(self.etat).read().split()
        return int(v[1]), int(v[3])

    def fermer(self):
        self.p.kill()
        self.p.wait()


class MontureSimulee:
    """Monture équatoriale : axe d'AD, télescope, et deux vis de réglage reliées aux moteurs. La vis
    d'azimut tourne toute la monture autour de la verticale ; celle de hauteur autour de la charnière."""

    def __init__(self, lat, lon, emu, err_az=55.0, err_haut=-35.0, suivi=True, pas_az=120.0, pas_haut=-85.0):
        self.lat, self.lon, self.emu, self.suivi_on = lat, lon, emu, suivi
        self.t0 = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)
        self.t = self.t0
        # axe réel : pôle visé, décalé de err_az (sur le ciel) et err_haut (′)
        pole = mes.pole_vise(lat)
        az, h = mes.az_haut(pole)
        self.axe0 = mes.depuis_az_haut(az + err_az / 60 / math.cos(math.radians(h)), h + err_haut / 60)
        self.pas_az, self.pas_haut = pas_az, pas_haut       # pas moteur par minute d'arc de réglage
        # charnière de latitude : perpendiculaire à l'azimut de l'axe, plus un défaut de 0,3° (monture imparfaite)
        self.charniere = mes.rotation(mes.ZENITH, math.radians(0.3)) @ mes.charniere(self.axe0)
        # télescope : vers le méridien, 40° au-dessus de l'équateur céleste côté pôle visible
        self.tel0 = mes.depuis_az_haut(180.0 if lat >= 0 else 0.0, 90 - abs(lat) + 10)
        self.ad = 0.0                                       # angle de l'axe d'AD tourné par les GoTo (rad)
        self.rng = np.random.default_rng(1)

    def reglage(self):
        sa, sl = self.emu.sorties()
        a = sa / self.pas_az * ARCMIN
        b = sl / self.pas_haut * ARCMIN
        return mes.rotation(mes.ZENITH, a) @ mes.rotation(self.charniere, b)

    def axe(self):
        return self.reglage() @ self.axe0

    def pointage(self):
        nord = self.axe0 if float(self.axe0 @ mes.pole_nord_local(self.lat)) > 0 else -self.axe0
        dt = (self.t - self.t0).total_seconds()
        ang = self.ad - (mes.OMEGA_SID * dt if self.suivi_on else 0.0)
        return self.reglage() @ (mes.rotation(nord, ang) @ self.tel0)

    # ── fonctions données au déroulement ──
    def mesurer(self):
        self.t += timedelta(seconds=25)                     # pose + astrométrie
        v = self.pointage()
        ra, dec = mes.local_vers_j2000(v, self.t, self.lat, self.lon)
        b = self.rng.normal(0, 1 / 3600, 2)
        return ra + b[0] / 15 / max(0.2, math.cos(math.radians(dec))), dec + b[1], self.t

    def tourner_ad(self, deg):
        self.ad += math.radians(deg)
        self.t += timedelta(seconds=deg / 2)

    def erreur_vraie(self, refraction=False):
        return mes.erreur(self.axe(), self.lat, refraction)


def essai(exe, lat, lon, suivi, tol=1.0, refraction=False, err=(55.0, -35.0)):
    emu = Emulateur(exe)
    try:
        carte = mes.CarteMES(emu.port, attente_reset=0.0)
        mont = MontureSimulee(lat, lon, emu, *err, suivi=suivi)
        lignes = []
        m = mes.MiseEnStation(lat, lon, mont.mesurer, mont.tourner_ad, carte, suivi=lambda: suivi,
                              journal=lignes.append, refraction=refraction)
        e0 = m.mesurer_axe(30.0)
        vrai0 = mont.erreur_vraie(refraction)
        assert abs(e0["total"] - vrai0["total"]) < 0.3, (e0["total"], vrai0["total"])
        m.calibrer(pas_essai=300)
        fin = m.corriger(tolerance=tol, iterations=10)
        vrai = mont.erreur_vraie(refraction)
        ok = vrai["total"] <= tol * 1.15 and fin["total"] <= tol
        n_corr = sum(1 for l in lignes if l.startswith("Correction"))
        print(f"  lat {lat:+.0f}°, suivi {'oui' if suivi else 'non'}, réfraction {'oui' if refraction else 'non'} : "
              f"départ {vrai0['total']:.1f}′ (mesuré {e0['total']:.1f}′) → {vrai['total']:.2f}′ vrai, "
              f"{fin['total']:.2f}′ estimé, {n_corr} corrections  {'OK' if ok else 'ÉCHEC'}")
        if not ok:
            print("\n".join("    " + l for l in lignes))
        carte.fermer()
        return ok
    finally:
        emu.fermer()


def essai_sans_12v(exe):
    emu = Emulateur(exe, vm=0.0)
    try:
        carte = mes.CarteMES(emu.port, attente_reset=0.0)
        try:
            carte.bouger("A", 100)
            ok = False
        except mes.ErreurCarte as e:
            ok = "12 V" in str(e)
        print(f"  sans 12 V : mouvement refusé  {'OK' if ok else 'ÉCHEC'}")
        carte.fermer()
        return ok
    finally:
        emu.fermer()


def essai_fin_de_course(exe):
    emu = Emulateur(exe, fc="A+:150")
    try:
        carte = mes.CarteMES(emu.port, attente_reset=0.0)
        carte.bouger("A", 1000)
        try:
            carte.attendre()
            ok = False
        except mes.ErreurCarte as e:
            ok = "fin de course" in str(e) and carte.position("A") <= 151
        try:
            carte.bouger("A", 10)
            ok = False
        except mes.ErreurCarte as e:
            ok = ok and "fin de course" in str(e)
        carte.bouger("A", -50)          # on peut repartir de l'autre côté
        carte.attendre()
        print(f"  fin de course : arrêt à {carte.position('A') + 50} pas, repartir dans l'autre sens possible  "
              f"{'OK' if ok else 'ÉCHEC'}")
        carte.fermer()
        return ok
    finally:
        emu.fermer()


def essai_geometrie():
    """Aller-retour J2000 <-> local, et pôle de la date : le pôle J2000 précessé n'est plus au zénith local."""
    t = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)
    v = mes.j2000_vers_local(5.5, 22.0, t, 43.5, 6.9)
    ra, dec = mes.local_vers_j2000(v, t, 43.5, 6.9)
    ok = abs(ra - 5.5) * 15 * 3600 < 0.01 and abs(dec - 22.0) * 3600 < 0.01
    # le pôle de la date est à ~0,2° du pôle J2000 en 2026 (précession 20″/an)
    p = mes.local_vers_j2000(mes.pole_vise(43.5), t, 43.5, 6.9)
    d = (90 - p[1]) * 60
    ok = ok and 8.0 < d < 10.0
    print(f"  géométrie : aller-retour exact, pôle de la date à {d:.1f}′ du pôle J2000  {'OK' if ok else 'ÉCHEC'}")
    return ok


def main():
    exe = compiler()
    print("Mise en station robotisée : essais sur émulateur")
    res = [essai_geometrie(), essai_sans_12v(exe), essai_fin_de_course(exe),
           essai(exe, 43.43, 6.77, suivi=True),
           essai(exe, 43.43, 6.77, suivi=False),
           essai(exe, 43.43, 6.77, suivi=True, tol=0.5, refraction=True, err=(-140.0, 95.0)),
           essai(exe, -33.9, 18.4, suivi=True)]
    print(f"{sum(res)}/{len(res)} essais réussis")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
