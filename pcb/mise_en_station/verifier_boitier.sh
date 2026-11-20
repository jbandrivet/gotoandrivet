#!/bin/sh
# Contrôle du boîtier de la carte de mise en station : la base et le couvercle ne doivent toucher ni la
# carte, ni ses pièces (gabarits de encombrement() dans le .scad), ni les fiches et les contre-écrous des
# presse-étoupes, ni l'un l'autre. Puis refait les STL et l'image.   Usage : sh verifier_boitier.sh
set -e
cd "$(dirname "$0")"
TMP=$(mktemp -d)
ok=1
for m in verif_base verif_couvercle verif_fermeture; do
    openscad -D "mode=\"$m\"" -o "$TMP/$m.stl" boitier_mise_en_station.scad >"$TMP/$m.log" 2>&1 || true
    vol=$(python3 - "$TMP/$m.stl" <<'PY'
import sys
v, t = [], 0.0
try:
    for l in open(sys.argv[1]):
        l = l.split()
        if l and l[0] == "vertex":
            v.append(tuple(map(float, l[1:])))
            if len(v) == 3:
                a, b, c = v
                t += (a[0]*(b[1]*c[2]-b[2]*c[1]) - a[1]*(b[0]*c[2]-b[2]*c[0]) + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6
                v = []
except FileNotFoundError:
    pass
print(f"{abs(t):.3f}")
PY
)
    echo "$m : chevauchement de $vol mm3"
    [ "$vol" = "0.000" ] || ok=0
done
rm -rf "$TMP"
[ $ok = 1 ] || { echo "COLLISION : voir les modes verif_* dans OpenSCAD"; exit 1; }
openscad -D 'mode="base"' -o boitier_mise_en_station_base.stl boitier_mise_en_station.scad 2>/dev/null
openscad -D 'mode="couvercle"' -o boitier_mise_en_station_couvercle.stl boitier_mise_en_station.scad 2>/dev/null
openscad -D 'mode="vue"' --render --imgsize=1280,720 --viewall --autocenter --camera=0,0,0,60,0,200,0 \
    -o boitier_mise_en_station_3d.png boitier_mise_en_station.scad 2>/dev/null
echo "OK : aucune collision, STL et image refaits"
