#!/bin/bash
# Prépare la fabrication des .exe Windows dans la machine VirtualBox « vm windows » (qui doit être allumée).
# Tout vient du dernier commit du dépôt (git archive HEAD), rien n'est écrit dans le dépôt.
# Ensuite, dans Windows : Win+R, puis  cmd /c T:\fabrication\fabriquer.bat
# Les .exe arrivent dans ~/.cache/gotoandrivet-windows/partage/sortie (journal : partage/journal.txt).
# Python pour Windows : un Python 3.12 Windows sans installation, dossier donné par PY312
# (par défaut celui du préfixe Wine du Cahier juridique).
set -e
ICI=$(cd "$(dirname "$0")" && pwd)
DEPOT=${1:-$(cd "$ICI/.." && pwd)}
PY312=${PY312:-$HOME/.cache/cahier-juridique/wine/drive_c/Py312}
CACHE=$HOME/.cache/gotoandrivet-windows
P=$CACHE/partage
mkdir -p "$CACHE"; cd "$CACHE"
rm -rf "$P" src; mkdir -p "$P/src" "$P/fabrication" "$P/sortie" src
git -C "$DEPOT" archive HEAD | tar -x -C src
for d in mega_monture teensy_monture teensy_raquette icons; do cp -r "src/$d" "$P/src/"; done
cp src/*.py "$P/src/"
cp src/windows/lanceur.py src/windows/gotoandrivet.spec src/windows/fabriquer.bat "$P/fabrication/"
git -C "$DEPOT" rev-parse --short=7 HEAD > "$P/fabrication/version_git.txt"
cp src/windows/carte.ico src/windows/config.ico "$P/fabrication/"     # refaites par icones.py si les .svg changent
cp -r "$PY312" "$P/Py312"
VBoxManage sharedfolder remove "vm windows" --name goto --transient 2>/dev/null || true   # partage d'une fabrication précédente
VBoxManage sharedfolder add "vm windows" --name goto --hostpath "$P" --transient --automount --auto-mount-point "T:"
echo "Prêt (version $(cat "$P/fabrication/version_git.txt")). Dans Windows : cmd /c T:\\fabrication\\fabriquer.bat"
