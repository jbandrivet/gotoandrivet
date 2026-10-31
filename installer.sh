#!/bin/sh
# Installation de GotoAndrivet en une commande (Linux) :
#   wget -qO- https://raw.githubusercontent.com/jbandrivet/gotoandrivet/main/installer.sh | sh
# Installe la carte du ciel et GoTo (goto_andrivet.py) et le configurateur dans ~/.goto_andrivet,
# avec leur environnement Python, et met leurs raccourcis sur le Bureau. Rien n'est installé dans le système.
set -e
BASE=https://raw.githubusercontent.com/jbandrivet/gotoandrivet/main

fetch() {
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"; else wget -qO "$2" "$1"; fi
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 est nécessaire : sudo apt install python3 python3-venv python3-tk"; exit 1
fi
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "Tk est nécessaire : sudo apt install python3-tk"; exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if ! python3 -m venv "$tmp/essai" >/dev/null 2>&1; then
    echo "Le module venv est nécessaire : sudo apt install python3-venv"; exit 1
fi
rm -rf "$tmp/essai"
echo "Téléchargement de l'installateur GotoAndrivet..."
fetch "$BASE/install_linux.py" "$tmp/install_linux.py"
fetch "$BASE/mise_a_jour.py" "$tmp/mise_a_jour.py"
python3 "$tmp/install_linux.py" --auto
