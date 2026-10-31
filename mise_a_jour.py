"""Mise à jour en ligne des applications GotoAndrivet, partagée par la carte du ciel et le configurateur.

Version installée : commit git du dossier si c'est un dépôt, sinon ~/.config/goto_andrivet/version.txt.
Version disponible : dernier commit de la branche main du dépôt GitHub.
Mise à jour : « git pull » pour un dépôt, sinon téléchargement de l'archive de main, recopiée sur
l'installation (le venv et les données d'astrométrie sont conservés).
Raccourcis : entrées du menu des applications (et du Bureau à l'installation), écrites par l'installateur
et rafraîchies au démarrage de chaque application installée.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = "jbandrivet/gotoandrivet"
VERSION_FILE = Path.home() / ".config" / "goto_andrivet" / "version.txt"
KEEP = {"venv", ".git", "__pycache__", "astrometry_data"}
_UA = {"User-Agent": "GotoAndrivet-Updater/1.0"}


def is_git(app_dir):
    return (Path(app_dir) / ".git").exists()


def local_version(app_dir):
    """Commit installé, ou "" s'il est inconnu."""
    if is_git(app_dir):
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(app_dir), capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    return VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""


def remote_version(timeout=5):
    """Dernier commit de main sur GitHub (lève une exception si le réseau ne répond pas).
    L'API de GitHub n'accepte que 60 requêtes par heure et par adresse Internet, partagées par tous les
    appareils de la maison : au-delà, on lit le flux public des commits, qui n'est pas compté."""
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/main", headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())["sha"]
    except Exception:
        req = urllib.request.Request(f"https://github.com/{REPO}/commits/main.atom", headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            m = re.search(r"Commit/([0-9a-f]{40})", r.read().decode(errors="replace"))
        if not m:
            raise RuntimeError("version distante introuvable")
        return m.group(1)


def check(app_dir):
    """(mise à jour disponible, commit distant, commit local). Une installation sans version connue
    est considérée comme à jour : la version distante est alors enregistrée comme version installée."""
    remote = remote_version()
    local = local_version(app_dir)
    if not local:
        save_version(remote)
        return False, remote, remote
    return local != remote, remote, local


def save_version(sha):
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(sha)


def apply(app_dir, remote_sha=None, progress=None):
    """Installe la dernière version dans app_dir. Lève une exception en cas d'échec.
    progress(etape, fraction, octets) est appelé au fil de l'eau (etape = "download" ou "install",
    fraction entre 0 et 1, ou None si la taille n'est pas connue) : voir Attente."""
    def signale(etape, frac=None, octets=0):
        if progress:
            try: progress(etape, frac, octets)
            except Exception: pass
    app_dir = Path(app_dir)
    if is_git(app_dir):
        signale("download")
        r = subprocess.run(["git", "pull"], cwd=str(app_dir), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "git pull a échoué")
        return
    req = urllib.request.Request(f"https://github.com/{REPO}/archive/refs/heads/main.zip", headers=_UA)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "main.zip"
        signale("download", None, 0)
        with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)   # souvent absent : archive produite à la volée
            recu = 0
            while True:
                bloc = r.read(65536)
                if not bloc:
                    break
                f.write(bloc); recu += len(bloc)
                signale("download", recu / total if total else None, recu)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
            comment = z.comment.decode(errors="replace").strip()        # GitHub y met le commit de l'archive
        if not remote_sha and re.fullmatch(r"[0-9a-f]{40}", comment):
            remote_sha = comment
        src = next(p for p in Path(tmp).iterdir() if p.is_dir())       # « gotoandrivet-main » (le nom du dossier n'importe pas)
        items = [item for item in src.iterdir() if item.name not in KEEP]
        for n, item in enumerate(items):
            signale("install", n / max(1, len(items)))
            dest = app_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
        signale("install", 1.0)
    if remote_sha:
        save_version(remote_sha)


_TEXTES = {
    "fr": {"titre": "Mise à jour de GotoAndrivet", "download": "Téléchargement de la nouvelle version…",
           "install": "Installation des fichiers…", "done": "Mise à jour installée : redémarrage…",
           "recu": "{mo:.1f} Mo reçus", "patience": "Merci de patienter, ne fermez pas l'application."},
    "en": {"titre": "Updating GotoAndrivet", "download": "Downloading the new version…",
           "install": "Installing the files…", "done": "Update installed: restarting…",
           "recu": "{mo:.1f} MB received", "patience": "Please wait, do not close the application."},
}


class Attente:
    """Petite fenêtre animée pendant la mise à jour (ciel étoilé, télescope qui pivote, étoile filante).
    Le téléchargement tourne dans un fil à part : l'interface ne se fige plus. Le fil ne touche jamais
    Tk : il écrit l'état dans self._etat, que l'animation relit toutes les 40 ms."""
    L, H = 380, 150

    def __init__(self, parent, lang="fr"):
        import math, random, tkinter as tk
        from tkinter import ttk
        self.tk, self.math, self.rnd = tk, math, random
        self.t = _TEXTES.get(lang, _TEXTES["fr"])
        self.parent = parent
        self._etat = {"etape": "download", "frac": None, "octets": 0}
        self._fin = None; self._t0 = None; self._frame = 0
        w = self.w = tk.Toplevel(parent)
        w.title(self.t["titre"]); w.resizable(False, False); w.configure(bg="#0b1020")
        w.transient(parent); w.protocol("WM_DELETE_WINDOW", lambda: None)   # pas de fermeture en cours de route
        self.c = tk.Canvas(w, width=self.L, height=self.H, bg="#0b1020", highlightthickness=0)
        self.c.pack(padx=0, pady=0)
        def ciel(y):                                           # bleu nuit, plus clair vers l'horizon
            k = max(0.0, min(1.0, y / (self.H - 22)))
            return f"#{int(10 + 22 * k):02x}{int(14 + 34 * k):02x}{int(30 + 52 * k):02x}"
        self._fond = tk.PhotoImage(width=self.L, height=self.H)  # dégradé d'une seule pièce (pas de jointures)
        for y in range(self.H):
            self._fond.put(ciel(y), to=(0, y, self.L, y + 1))
        self.c.create_image(0, 0, image=self._fond, anchor="nw")
        self.c.create_oval(self.L - 70, 14, self.L - 44, 40, fill="#f4f1d6", width=0)      # la Lune,
        self.c.create_oval(self.L - 63, 11, self.L - 37, 37, fill=ciel(24), width=0)       # en croissant
        self.etoiles = []
        for _ in range(55):
            x, y = random.uniform(0, self.L), random.uniform(0, self.H - 30)
            r = random.choice((1, 1, 1, 1.5, 2))
            self.etoiles.append((self.c.create_oval(x - r, y - r, x + r, y + r, fill="#ffffff", width=0),
                                 random.uniform(0, 6.28), random.uniform(0.04, 0.12)))
        self.c.create_rectangle(0, self.H - 22, self.L, self.H, fill="#05070f", width=0)       # le sol
        self.cx, self.cy = self.L / 2, self.H - 22
        for dx in (-22, 0, 22):                                                               # trépied
            self.c.create_line(self.cx, self.cy - 30, self.cx + dx, self.cy, fill="#8a93b8", width=2)
        self.tube = self.c.create_polygon(0, 0, 0, 0, 0, 0, 0, 0, fill="#c9cfe8", outline="#ffffff")
        self.filante = self.c.create_line(0, 0, 0, 0, fill="#ffffff", width=2, capstyle="round")
        self.f_pos = None
        self.msg = tk.Label(w, text=self.t["download"], bg="#0b1020", fg="#e8ecff", font=("Sans", 11, "bold"))
        self.msg.pack(pady=(8, 2))
        self.barre = ttk.Progressbar(w, length=self.L - 40, mode="indeterminate")
        self.barre.pack(pady=4)
        self.detail = tk.Label(w, text=self.t["patience"], bg="#0b1020", fg="#8a93b8", font=("Sans", 9))
        self.detail.pack(pady=(0, 10))
        w.update_idletasks()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - w.winfo_width()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - w.winfo_height()) // 3
            w.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        try: w.grab_set()
        except Exception: pass
        self._anime()

    def progress(self, etape, frac=None, octets=0):          # appelé depuis le fil de téléchargement
        self._etat = {"etape": etape, "frac": frac, "octets": octets}

    def _anime(self):
        import time
        if self._t0 is None: self._t0 = time.time()
        m, c, f = self.math, self.c, self._frame
        self._frame += 1
        for oid, ph, v in self.etoiles:                         # scintillement
            g = int(150 + 105 * (0.5 + 0.5 * m.sin(ph + f * v)))
            c.itemconfigure(oid, fill=f"#{g:02x}{g:02x}{min(255, g + 20):02x}")
        a = m.radians(55 + 25 * m.sin(f * 0.035))               # le télescope balaie le ciel
        ux, uy = m.cos(a), -m.sin(a); px, py = -uy, ux
        bx, by = self.cx - ux * 18, self.cy - 30 - uy * 18
        ex, ey = self.cx + ux * 46, self.cy - 30 + uy * 46
        c.coords(self.tube, bx + px * 5, by + py * 5, ex + px * 7, ey + py * 7,
                 ex - px * 7, ey - py * 7, bx - px * 5, by - py * 5)
        if self.f_pos is None and self.rnd.random() < 0.02:     # étoile filante
            self.f_pos = [self.rnd.uniform(40, self.L - 40), self.rnd.uniform(8, 40), 0]
        if self.f_pos:
            x, y, k = self.f_pos
            c.coords(self.filante, x + k * 9, y + k * 4, x + k * 9 - 28, y + k * 4 - 12)
            self.f_pos[2] += 1
            if k > 14: self.f_pos = None; c.coords(self.filante, 0, 0, 0, 0)
        e = self._etat                                          # état écrit par le fil
        if self._fin == "ok":
            self.msg.configure(text=self.t["done"]); self.barre.stop()
            self.barre.configure(mode="determinate", value=100); self.detail.configure(text="")
        elif e["etape"] == "install":
            self.msg.configure(text=self.t["install"])
            if str(self.barre["mode"]) != "determinate": self.barre.stop(); self.barre.configure(mode="determinate")
            self.barre.configure(value=100 * (e["frac"] or 0))
        else:
            self.msg.configure(text=self.t["download"])
            if e["frac"] is None:
                if str(self.barre["mode"]) != "indeterminate": self.barre.configure(mode="indeterminate")
                self.barre.step(2)
            else:
                self.barre.configure(mode="determinate", value=100 * e["frac"])
            if e["octets"]: self.detail.configure(text=self.t["recu"].format(mo=e["octets"] / 1e6))
        try: self._apres = self.w.after(40, self._anime)
        except Exception: pass

    def fermer(self):
        try: self.w.after_cancel(self._apres)
        except Exception: pass
        try: self.w.grab_release(); self.w.destroy()
        except Exception: pass


def installer_avec_attente(parent, app_dir, remote_sha=None, lang="fr", on_ok=None, on_erreur=None):
    """Installe la mise à jour dans un fil à part, derrière la fenêtre Attente. Ensuite, dans le fil de
    Tk : on_ok() (par défaut : redémarrage) ou on_erreur(exception). La fenêtre reste au moins 2 s,
    pour qu'on ait le temps de lire ce qui se passe."""
    import threading, time
    att = Attente(parent, lang)
    res = {}
    def travail():
        t0 = time.time()
        try:
            apply(app_dir, remote_sha, progress=att.progress)
            att._fin = "ok"
        except Exception as e:
            res["err"] = e
        time.sleep(max(0.0, 2.0 - (time.time() - t0)) + (1.2 if "err" not in res else 0))
        res["fini"] = True
    def surveille():
        if not res.get("fini"):
            parent.after(100, surveille); return
        att.fermer()
        if "err" in res:
            (on_erreur or (lambda e: None))(res["err"])
        else:
            (on_ok or restart)()
    threading.Thread(target=travail, daemon=True).start()
    parent.after(100, surveille)
    return att

# Fichier, nom, description, script, icône, icône de secours. Les noms de fichiers restent ceux des
# premières installations, pour remplacer leurs raccourcis au lieu de les doubler.
APPS = (
    ("GotoAndrivet.desktop", "GotoAndrivet - Carte du ciel",
     "Carte du ciel, GoTo, caméra, astrométrie et guidage pour monture GotoAndrivet",
     "goto_andrivet.py", "goto_andrivet.svg", "applications-science"),
    ("GotoMega.desktop", "GotoAndrivet - Configurateur",
     "Réglage et flashage de la monture et de la raquette GotoAndrivet",
     "goto_andrivet_config_tool.py", "goto_andrivet_config.svg", "utilities-terminal"),
)
KEYWORDS = "GotoAndrivet;goto;télescope;telescope;monture;mount;astronomie;astronomy;OnStep;LX200;"


def desktop_dir():
    for name in ("Bureau", "Desktop"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home() / "Desktop"


def shortcuts(app_dir, desktop="existing"):
    """Raccourcis des deux applications dans le menu des applications (c'est là que la recherche de GNOME
    les trouve). Bureau : "create" les crée, "existing" ne met à jour que ceux qui y sont déjà, None n'y
    touche pas. Renvoie les fichiers écrits."""
    app_dir = Path(app_dir)
    python = app_dir / "venv" / "bin" / "python3"
    if not python.exists():
        python = Path(sys.executable)
    menu = Path.home() / ".local" / "share" / "applications"
    written = []
    for file_name, name, comment, script, icon_file, fallback in APPS:
        icon = app_dir / "icons" / icon_file
        content = (f"[Desktop Entry]\nVersion=1.0\nType=Application\nName={name}\nComment={comment}\n"
                   f'Keywords={KEYWORDS}\nExec="{python}" "{app_dir / script}"\n'
                   f"Icon={icon if icon.exists() else fallback}\nPath={app_dir}\nTerminal=false\n"
                   "Categories=Science;Astronomy;\n")
        targets = [menu / file_name]
        if desktop == "create" or (desktop == "existing" and (desktop_dir() / file_name).exists()):
            targets.append(desktop_dir() / file_name)
        for f in targets:
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.exists() and f.read_text(errors="replace") == content:
                continue
            f.write_text(content)
            os.chmod(f, 0o755)
            written.append(f)
            if f.parent != menu:          # GNOME : sans ce drapeau, le Bureau demande d'autoriser le lancement
                try:
                    subprocess.run(["gio", "set", str(f), "metadata::trusted", "true"], capture_output=True)
                except OSError:
                    pass
    return written


def register(app_dir):
    """Au démarrage d'une application installée (dossier avec son venv, hors dépôt git) : entrées du menu
    des applications créées ou mises à jour. Les installations d'avant le 21/10/2026 n'en avaient pas."""
    app_dir = Path(app_dir)
    if is_git(app_dir) or not (app_dir / "venv").exists():
        return []
    try:
        return shortcuts(app_dir)
    except OSError:
        return []


def restart():
    """Relance le programme courant (même interpréteur, mêmes arguments)."""
    os.execv(sys.executable, [sys.executable] + sys.argv)
