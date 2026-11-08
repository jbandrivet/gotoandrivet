# -*- coding: utf-8 -*-
"""Point d'entrée des .exe Windows de GotoAndrivet.

Cette couche n'est utilisée que par les .exe : le code du dépôt et la version Linux ne changent pas.
Le nom du .exe choisit le programme. Le configurateur relance son propre .exe avec le chemin
d'un script, comme il le ferait avec Python : ce chemin choisit alors le programme à ouvrir.
"""
import os
import subprocess
import sys
from pathlib import Path

ICI = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
VERSION = (ICI / "version_git.txt").read_text().strip()
OUTILS_CAMERA = {"auto_model_zwo", "autoguide_spectro_zwo", "measure_backlash_zwo", "polar_alignment_ui"}
SITE = "https://goto-andrivet.duckdns.org/telecharger.html"
RELEASE = "https://github.com/jbandrivet/gotoandrivet/releases/download/windows"
EXE = ("GotoAndrivet_Carte_du_ciel.exe", "GotoAndrivet_Configurateur.exe", "GotoAndrivet_Raquette.exe")
_UA = {"User-Agent": "GotoAndrivet-Windows/1.0"}


def adapter_subprocess():
    """Pas de fenêtre noire ; git n'est pas utile ici ; une relance du .exe doit être indépendante."""
    popen, run = subprocess.Popen, subprocess.run

    class Popen(popen):
        def __init__(self, args, *a, **k):
            k.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
            if isinstance(args, (list, tuple)) and args and args[0] == sys.executable:
                # Sans cela, le nouveau programme dépendrait du dossier temporaire de celui qui l'a lancé.
                k["env"] = dict(k.get("env") or os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
            super().__init__(args, *a, **k)

    def run_adapte(args, *a, **k):
        if isinstance(args, (list, tuple)) and list(args[:2]) == ["git", "pull"]:
            return subprocess.CompletedProcess(args, 0, "", "")     # les firmwares sont dans le .exe
        return run(args, *a, **k)

    subprocess.Popen, subprocess.run = Popen, run_adapte


# ── Mise à jour des .exe ──────────────────────────────────────
# La release « windows » de GitHub est refaite par le workflow windows.yml à chaque commit qui touche
# le programme : les .exe, SHA256SUMS.txt, puis version.txt (le commit des .exe), publié en dernier.
# Windows interdit d'écraser un .exe qui tourne, mais permet de le renommer : l'ancien devient
# « .old » (effacé au démarrage suivant) et le nouveau prend sa place. Les .exe GotoAndrivet rangés
# dans le même dossier sont mis à jour ensemble.

def _lire(url, timeout=10):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return r.read()


def version_publiee():
    return _lire(f"{RELEASE}/version.txt").decode("ascii", "replace").strip()[:7]


def nettoyer_anciens():
    """Efface les .old d'une mise à jour précédente (encore verrouillés si l'ancien programme tourne)."""
    dossier = Path(sys.executable).parent
    for nom in EXE:
        try: (dossier / (nom + ".old")).unlink()
        except OSError: pass


def appliquer(_app_dir=None, _sha=None, progress=None):
    """Remplace les .exe du dossier par ceux de la release. Lève une exception en cas d'échec,
    sans rien changer tant que tous les fichiers ne sont pas téléchargés et vérifiés."""
    import hashlib, urllib.request
    def signale(etape, frac=None, octets=0):
        if progress:
            try: progress(etape, frac, octets)
            except Exception: pass
    moi = Path(sys.executable)
    dossier = moi.parent
    noms = [n for n in EXE if (dossier / n).exists() or n == moi.name]
    if moi.name not in EXE:
        raise RuntimeError(f"Ce programme a été renommé ({moi.name}) : téléchargez les nouveaux .exe sur {SITE}")
    sommes = {}
    for ligne in _lire(f"{RELEASE}/SHA256SUMS.txt").decode("ascii", "replace").splitlines():
        morceaux = ligne.split()
        if len(morceaux) == 2:
            sommes[morceaux[1].lstrip("*")] = morceaux[0].lower()
    signale("download", 0, 0)
    recu, nouveaux = 0, []
    try:
        for n in noms:
            neuf = dossier / (n + ".new")
            h = hashlib.sha256()
            try:
                f = open(neuf, "wb")
            except PermissionError:
                raise RuntimeError(f"Le dossier {dossier} est protégé en écriture. Copiez les .exe dans un dossier "
                                   f"à vous (Documents, Bureau) ou téléchargez-les sur {SITE}")
            with f, urllib.request.urlopen(urllib.request.Request(f"{RELEASE}/{n}", headers=_UA), timeout=120) as r:
                while True:
                    bloc = r.read(262144)
                    if not bloc:
                        break
                    f.write(bloc); h.update(bloc); recu += len(bloc)
                    signale("download", None, recu)
            nouveaux.append(neuf)
            if sommes.get(n) != h.hexdigest():
                raise RuntimeError(f"{n} : fichier téléchargé abîmé (somme de contrôle), rien n'a été changé")
        signale("install", 0.5)
        for n in noms:
            exe, neuf, vieux = dossier / n, dossier / (n + ".new"), dossier / (n + ".old")
            try: vieux.unlink()
            except FileNotFoundError: pass
            if exe.exists():
                os.replace(exe, vieux)                  # permis même si ce .exe est ouvert
            try:
                os.replace(neuf, exe)
            except OSError:
                if vieux.exists() and not exe.exists():
                    os.replace(vieux, exe)              # on remet l'ancien
                raise
        signale("install", 1.0)
    finally:
        for neuf in nouveaux:
            try: neuf.unlink()
            except OSError: pass


def relancer():
    """Démarre le nouveau .exe et quitte celui-ci (son port série est libéré en sortant)."""
    subprocess.Popen([sys.executable] + sys.argv[1:], cwd=str(Path(sys.executable).parent))
    os._exit(0)


def adapter_mises_a_jour():
    """Le bouton de mise à jour compare ce .exe à la release « windows » et la recopie d'un clic."""
    import mise_a_jour

    def check(_app_dir=None):
        distante = version_publiee()
        return bool(distante) and distante != VERSION[:7], distante, VERSION

    mise_a_jour.check = check
    mise_a_jour.apply = appliquer
    mise_a_jour.restart = relancer
    mise_a_jour.local_version = lambda *_a, **_k: VERSION
    mise_a_jour.register = lambda *_a, **_k: None


def outil_camera_absent():
    import tkinter as tk
    from tkinter import messagebox
    racine = tk.Tk()
    racine.withdraw()
    messagebox.showinfo("GotoAndrivet", "Cet outil a besoin d'une caméra ZWO et de solve-field. "
                                        "Il n'est pas disponible dans la version Windows : utilisez la version Linux.")
    racine.destroy()


def lancer_carte():
    import goto_andrivet as m
    m.DEFAULTS["derot_port"] = "COM4"
    m.App().mainloop()


def lancer_configurateur():
    import goto_andrivet_config_tool as m
    m.DEFAULTS["mount_port"] = "COM3"
    balayer = m.ConfigToolApp.scan_ports
    m.ConfigToolApp.scan_ports = lambda self: [p for p in balayer(self) if not p.startswith("/dev/")] or ["COM3"]
    m.ConfigToolApp().mainloop()


def lancer_raquette():
    import raquette_virtuelle as m
    m.VirtualTeensyApp().mainloop()


PROGRAMMES = {"goto_andrivet": lancer_carte, "goto_andrivet_config_tool": lancer_configurateur,
              "raquette_virtuelle": lancer_raquette}


def choisir():
    if len(sys.argv) > 1:
        demande = sys.argv[1]
        if demande == "-c" or demande.startswith("/tmp/"):
            sys.exit(1)                     # script caméra écrit pour Linux
        nom = Path(demande).stem
        if nom in OUTILS_CAMERA:
            return outil_camera_absent
        if nom in PROGRAMMES:
            return PROGRAMMES[nom]
    exe = Path(sys.executable).stem.lower()
    if "config" in exe:
        return lancer_configurateur
    if "raquette" in exe:
        return lancer_raquette
    return lancer_carte


if __name__ == "__main__":
    adapter_subprocess()
    adapter_mises_a_jour()
    nettoyer_anciens()
    choisir()()
