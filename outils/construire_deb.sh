#!/bin/sh
# Construit le paquet Debian de GotoAndrivet : dist/GotoAndrivet.deb
#   sh outils/construire_deb.sh [version]
#
# Le paquet est léger : l'installateur, un lanceur, les icônes et les deux entrées du menu des applications
# (carte du ciel et configurateur). Il dépend de python3-venv et python3-tk, que le Centre d'applications
# ou apt installent au besoin. À la première ouverture d'une des deux applications, le lanceur installe
# GotoAndrivet dans ~/.goto_andrivet (dernière version de GitHub, environnement Python à part) ; ensuite il
# ouvre directement l'application, et les mises à jour passent par le bouton « Mise à jour ».
set -e
umask 022
cd "$(dirname "$0")/.."
version=${1:-$(date +%Y.%m.%d)}
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
chmod 755 "$root"

lib=/usr/lib/gotoandrivet
mkdir -p "$root/DEBIAN" "$root$lib" "$root/usr/share/applications" \
         "$root/usr/share/icons/hicolor/scalable/apps" "$root/usr/share/doc/gotoandrivet"
install -m 644 install_linux.py mise_a_jour.py "$root$lib/"
install -m 644 icons/goto_andrivet.svg "$root/usr/share/icons/hicolor/scalable/apps/gotoandrivet.svg"
install -m 644 icons/goto_andrivet_config.svg "$root/usr/share/icons/hicolor/scalable/apps/gotoandrivet-configurateur.svg"

cat > "$root$lib/lanceur" <<'EOF'
#!/bin/sh
# Lanceur des entrées du menu installées par le paquet gotoandrivet.
#   lanceur carte | lanceur configurateur
# À la première ouverture, installe GotoAndrivet dans ~/.goto_andrivet (fenêtre d'installation), puis
# ouvre l'application. Une fois installées, les entrées de ~/.local/share/applications, qui portent les
# mêmes noms, remplacent celles du paquet et ouvrent directement l'application.
dir="$HOME/.goto_andrivet"
case "$1" in
    configurateur) script=goto_andrivet_config_tool.py ;;
    *)             script=goto_andrivet.py ;;
esac
if [ ! -x "$dir/venv/bin/python3" ] || [ ! -f "$dir/$script" ]; then
    python3 /usr/lib/gotoandrivet/install_linux.py --premier-lancement || exit 1
fi
cd "$dir" && exec "$dir/venv/bin/python3" "$dir/$script"
EOF
chmod 755 "$root$lib/lanceur"

# Mêmes noms de fichiers que les entrées créées par l'installateur dans ~/.local/share/applications
entry() {
    cat > "$root/usr/share/applications/$1" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$2
Comment=$3
Keywords=GotoAndrivet;goto;télescope;telescope;monture;mount;astronomie;astronomy;OnStep;LX200;
Exec=$lib/lanceur $4
Icon=$5
Terminal=false
Categories=Science;Astronomy;
EOF
}
entry GotoAndrivet.desktop "GotoAndrivet - Carte du ciel" \
      "Carte du ciel, GoTo, caméra, astrométrie et guidage pour monture GotoAndrivet" carte gotoandrivet
entry GotoMega.desktop "GotoAndrivet - Configurateur" \
      "Réglage et flashage de la monture et de la raquette GotoAndrivet" configurateur gotoandrivet-configurateur

cat > "$root/usr/share/doc/gotoandrivet/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: GotoAndrivet
Source: https://github.com/jbandrivet/gotoandrivet

Files: *
Copyright: Jean-Baptiste Andrivet
License: GPL-3
 Le texte complet de la licence est dans /usr/share/common-licenses/GPL-3.
EOF

# Droits habituels des paquets : dossiers 755, fichiers 644, le lanceur exécutable
find "$root" -type d -exec chmod 755 {} +
find "$root" -type f -exec chmod 644 {} +
chmod 755 "$root$lib/lanceur"

size=$(du -sk "$root" | cut -f1)
cat > "$root/DEBIAN/control" <<EOF
Package: gotoandrivet
Version: $version
Architecture: all
Maintainer: Jean-Baptiste Andrivet <jbandrivet@users.noreply.github.com>
Installed-Size: $size
Depends: python3 (>= 3.10), python3-venv, python3-tk
Suggests: astrometry.net, astrometry-data-tycho2
Section: science
Priority: optional
Homepage: https://github.com/jbandrivet/gotoandrivet
Description: Carte du ciel, GoTo et configurateur pour monture GotoAndrivet
 GotoAndrivet pilote des montures de télescope AltAz, à fourche équatoriale
 ou équatoriales allemandes (protocole LX200/OnStep, cartes Arduino Mega ou
 Teensy) : carte du ciel avec GoTo, caméra et astrométrie, guidage,
 dérotateur, focuseur, et configurateur de la monture.
 .
 À la première ouverture, l'application s'installe dans le dossier personnel
 (~/.goto_andrivet) avec la dernière version publiée sur GitHub, puis se met
 à jour depuis son bouton « Mise à jour ».
EOF

mkdir -p dist
dpkg-deb --root-owner-group --build "$root" dist/GotoAndrivet.deb >/dev/null
echo "dist/GotoAndrivet.deb ($version)"
