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


def apply(app_dir, remote_sha=None):
    """Installe la dernière version dans app_dir. Lève une exception en cas d'échec."""
    app_dir = Path(app_dir)
    if is_git(app_dir):
        r = subprocess.run(["git", "pull"], cwd=str(app_dir), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "git pull a échoué")
        return
    req = urllib.request.Request(f"https://github.com/{REPO}/archive/refs/heads/main.zip", headers=_UA)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "main.zip"
        with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
            comment = z.comment.decode(errors="replace").strip()        # GitHub y met le commit de l'archive
        if not remote_sha and re.fullmatch(r"[0-9a-f]{40}", comment):
            remote_sha = comment
        src = next(p for p in Path(tmp).iterdir() if p.is_dir())       # « gotoandrivet-main » (le nom du dossier n'importe pas)
        for item in src.iterdir():
            if item.name in KEEP:
                continue
            dest = app_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
    if remote_sha:
        save_version(remote_sha)


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
