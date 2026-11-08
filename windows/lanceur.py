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
MESSAGE_MAJ = ("Une version plus récente existe, mais la version Windows ne se met pas à jour toute seule. "
               "Téléchargez les nouveaux .exe sur https://goto-andrivet.duckdns.org/telecharger.html")


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


def adapter_mises_a_jour():
    """Le bouton dit si une version plus récente existe, mais n'essaie pas de remplacer le .exe."""
    import mise_a_jour

    def check(_app_dir=None):
        distante = mise_a_jour.remote_version()
        return bool(distante) and not distante.startswith(VERSION), distante, VERSION

    def installer(_parent, _app_dir, _sha=None, _lang="fr", _on_ok=None, on_erreur=None):
        if on_erreur:
            on_erreur(MESSAGE_MAJ)

    mise_a_jour.check = check
    mise_a_jour.local_version = lambda *_a, **_k: VERSION
    mise_a_jour.register = lambda *_a, **_k: None
    mise_a_jour.installer_avec_attente = installer


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
    choisir()()
