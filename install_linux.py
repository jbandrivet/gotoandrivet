"""Installateur de GotoAndrivet pour Linux : carte du ciel et GoTo (goto_andrivet.py) et configurateur
(goto_andrivet_config_tool.py), dans ~/.goto_andrivet avec leur propre environnement Python, et deux
raccourcis sur le Bureau.

Lancé depuis le dossier du projet, il installe les fichiers de ce dossier. Lancé seul (téléchargé depuis
la page GitHub, ou par la commande de installer.sh), il télécharge la dernière version de la branche main,
comme le bouton « Mise à jour » des applications.

    python3 install_linux.py                       fenêtre d'installation
    python3 install_linux.py --auto                installation dans le terminal, sans fenêtre
    python3 install_linux.py --premier-lancement   fenêtre qui installe seule (lanceur du paquet .deb)
"""
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import mise_a_jour

INSTALL_DIR = Path.home() / ".goto_andrivet"
REQS = ["pyserial", "pillow", "zwoasi", "numpy", "requests", "ephem", "opencv-python-headless"]


def source_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def install(status):
    """Installe tout ; status(texte, pourcentage) suit l'avancement. Lève une exception en cas d'échec."""
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    venv_dir = INSTALL_DIR / "venv"
    src = source_dir()

    # 0. Les fichiers : ceux du dossier du projet, sinon la dernière version sur GitHub
    if (src / "goto_andrivet.py").exists():
        status("Copie des fichiers dans le dossier personnel...", 5)
        for f in src.glob("*.py"):
            shutil.copy2(f, INSTALL_DIR)
        for d in ["mega_monture", "teensy_monture", "teensy_raquette", "mise_en_station", "icons"]:
            if (src / d).exists():
                shutil.copytree(src / d, INSTALL_DIR / d, dirs_exist_ok=True)
        if mise_a_jour.is_git(src):
            sha = mise_a_jour.local_version(src)
            if sha:
                mise_a_jour.save_version(sha)
    else:
        status("Téléchargement de la dernière version depuis GitHub...", 5)
        mise_a_jour.apply(INSTALL_DIR)          # version lue dans l'archive : pas de requête à l'API

    # 1. L'environnement Python, à part du système
    status("Création de l'environnement virtuel...", 15)
    python_bin = shutil.which("python3") or "python3"
    r = subprocess.run([python_bin, "-m", "venv", "--copies", str(venv_dir)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Python ne peut pas créer d'environnement virtuel. Installez d'abord :\n"
                           "sudo apt install python3-venv python3-tk\n\n" + r.stderr.strip()[-400:])

    # 2. Les dépendances
    status("Installation des dépendances (cela peut prendre un moment)...", 25)
    pip_exe = venv_dir / "bin" / "pip"
    subprocess.run([str(pip_exe), "install", "--upgrade", "pip"], capture_output=True, text=True, check=True)
    for i, req in enumerate(REQS):
        status(f"Installation de {req}...", 25 + i * 9)
        r = subprocess.run([str(pip_exe), "install", req], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"pip install {req} a échoué :\n" + r.stderr.strip()[-400:])

    # 3. Les raccourcis : menu des applications et Bureau
    status("Création des raccourcis...", 92)
    mise_a_jour.shortcuts(INSTALL_DIR, desktop="create")
    status("Installation terminée avec succès !", 100)


def run_terminal():
    def status(text, val):
        print(f"[{val:3d} %] {text}", flush=True)
    try:
        install(status)
    except Exception as e:
        print(f"\nErreur : {e}", file=sys.stderr)
        return 1
    print("\nLa carte du ciel (GotoAndrivet) et le configurateur sont sur le Bureau et dans le menu des applications.")
    return 0


def run_window(first_launch=False):
    """Fenêtre d'installation. first_launch : appelée par le lanceur du paquet .deb à la première ouverture
    d'une application ; l'installation démarre seule et la fenêtre se ferme à la fin. Renvoie 0 si installé."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    class InstallerApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.done = False
            self.title("Installation de GotoAndrivet (Linux)")
            self.geometry("520x360")
            self.configure(bg="#f0f0f0")
            tk.Label(self, text="Installation de GotoAndrivet", font=("Arial", 16, "bold"), bg="#f0f0f0").pack(pady=20)
            if first_launch:
                text = ("Première ouverture : GotoAndrivet s'installe dans votre dossier personnel,\n"
                        "avec la dernière version depuis GitHub.\n\nCela prend quelques minutes, "
                        "puis l'application s'ouvre.")
            else:
                origin = "les fichiers de ce dossier" if (source_dir() / "goto_andrivet.py").exists() \
                    else "la dernière version depuis GitHub"
                text = ("Cet assistant installe " + origin + "\ndans un environnement isolé, sans modifier "
                        "votre système.\n\nIl crée deux raccourcis sur votre bureau :\nla carte du ciel et le configurateur.")
            tk.Label(self, text=text, bg="#f0f0f0", justify="center").pack(pady=10)
            self.progress = ttk.Progressbar(self, orient="horizontal", length=400, mode="determinate")
            self.progress.pack(pady=20)
            self.status_lbl = tk.Label(self, text="Prêt à installer.", bg="#f0f0f0")
            self.status_lbl.pack(pady=5)
            self.btn_install = tk.Button(self, text="Installer", command=self.start_install, font=("Arial", 12, "bold"))
            self.btn_install.pack(pady=20)
            if first_launch:
                self.after(300, self.start_install)

        def start_install(self):
            self.btn_install.config(state="disabled")
            threading.Thread(target=self.run_install, daemon=True).start()

        def run_install(self):
            try:
                install(self.update_status)
                self.done = True
                def on_success():
                    if not first_launch:
                        messagebox.showinfo("Succès", "L'installation est terminée.\n"
                                            "Vous pouvez maintenant lancer l'application depuis votre Bureau !")
                    self.destroy()
                self.after(0, on_success)
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Erreur", f"Une erreur est survenue:\n{err}"))
                self.after(0, lambda: self.btn_install.config(state="normal"))
                self.update_status("Erreur d'installation.", 0)

        def update_status(self, text, val):
            self.after(0, lambda: self.status_lbl.config(text=text))
            self.after(0, lambda: self.progress.config(value=val))

    app = InstallerApp()
    app.mainloop()
    return 0 if app.done else 1


if __name__ == "__main__":
    if "--auto" in sys.argv:
        sys.exit(run_terminal())
    sys.exit(run_window(first_launch="--premier-lancement" in sys.argv))
