#!/bin/sh
# Compile le firmware teensy_monture sur le PC et lance les tests du banc.
#   sh lancer.sh           synchros, guidage (Teensy et Mega), PEC (fourche et allemande), modele
#   sh lancer.sh modele    le tableau du modele seul (ESSAIS=16 pour 16 tirages)
#   FIRMWARE=autre.ino sh lancer.sh modele   compare avec un autre firmware
set -e
cd "$(dirname "$0")"
FW="${FIRMWARE:-$PWD/../../teensy_monture/teensy_monture.ino}"
OUT="${TMPDIR:-/tmp}/banc_teensy"
mkdir -p "$OUT"
for t in synchro guidage pec modele pty; do
  g++ -O2 -w -std=c++17 -Istubs -DFIRMWARE="\"$FW\"" "banc_$t.cpp" -o "$OUT/banc_$t"
done
# Firmware Mega, en flottant 32 bits comme sur la carte (voir mega_shim.h).
FWM="${FIRMWARE_MEGA:-$PWD/../../mega_monture/mega_monture.ino}"
g++ -O2 -w -std=c++17 -fsingle-precision-constant -DBANC_MEGA -Istubs -DFIRMWARE="\"$FWM\"" banc_guidage.cpp -o "$OUT/banc_guidage_mega"
case "$1" in
  modele) "$OUT/banc_modele" "mediane/90 % de l'erreur (arcmin) selon le nombre d'etoiles" ;;
  *) "$OUT/banc_synchro" && "$OUT/banc_guidage" 2 && "$OUT/banc_guidage" 1 && "$OUT/banc_guidage_mega" 2 && "$OUT/banc_pec" 1 && "$OUT/banc_pec" 2 && "$OUT/banc_modele" "modele" ;;
esac
