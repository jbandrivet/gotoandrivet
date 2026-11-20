#!/usr/bin/env python3
"""
Liste d'achat complète, carte par carte : écrit pcb/LISTE_ACHATS.md.

Les composants soudés viennent des listes de fabrication (pcb/fabrication/<carte>_composants.csv,
écrites par fabrication.py) ; le reste (modules, supports, boîtier, visserie, presse-étoupes, câbles)
est décrit ici, d'après les boîtiers .scad et la fiche technique. fabrication.py relance ce script.
"""

import csv
from pathlib import Path

ICI = Path(__file__).resolve().parent

CARTES = (
    ("monture_ext", "Monture : carte drivers externes",
     "Pour des drivers externes (DM542, DM556, TB6600...), un par axe. Boîtier de 202 x 140 x 35 mm."),
    ("monture", "Monture : carte StepStick",
     "Drivers au format StepStick sur la carte (TMC5160, TMC2209, A4988, DRV8825). "
     "Boîtier de 202 x 140 x 45 mm."),
    ("raquette", "Raquette",
     "Télécommande à écran LCD 20 x 4. Facultative : la monture se pilote aussi depuis le PC. "
     "Boîtier de 113 x 158 x 39 mm."),
    ("mise_en_station", "Mise en station robotisée",
     "Facultative, pour les montures équatoriales : deux moteurs tournent les vis de réglage en azimut "
     "et en hauteur, commandés par le PC (onglet Mise en station du module Caméra). Carte de 110 x 85 mm, "
     "reliée au PC par l'USB de son Arduino Nano, moteurs en 12 V."),
)

TEENSY = [
    ("Barrette femelle 1 x 24, pas 2,54 mm", 2, "Support du Teensy (U1) : le Teensy s'enfiche, il n'est pas soudé"),
    ("Barrette mâle 1 x 24, pas 2,54 mm", 2, "À souder sous le Teensy, sauf s'il est vendu avec ses broches"),
]
BOITIER_MONTURE = [
    ("Vis M3 x 6", 4, "Carte sur les entretoises du fond (trous de 2,8 mm, la vis taraude le plastique)"),
    ("Vis M3 x 10 à tête fraisée", 4, "Fermeture du couvercle"),
]

EN_PLUS = {
    "monture_ext": TEENSY + [
        ("Driver de moteur pas à pas externe (DM542, DM556, TB6600...)", "1 par axe (2 à 4)",
         "Branché sur J_VM (alimentation) et J_SIG (EN, STEP, DIR, GND) de son axe"),
        ("Presse-étoupe M20 x 1,5 à joint 2 trous (2 câbles de 4 à 6 mm)", 4,
         "Un par axe : câble d'alimentation et câble des signaux du driver"),
        ("Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm)", 4, "36 V, raquette, GPS, PC"),
    ] + BOITIER_MONTURE,
    "monture": TEENSY + [
        ("Module driver StepStick (TMC5160, TMC2209, A4988 ou DRV8825)", "1 par axe (2 à 4)",
         "Sur les supports de la carte ; TMC5160 réglé en SPI après fermeture des ponts à souder"),
        ("Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm)", 8,
         "4 moteurs, 36 V, raquette, GPS, PC"),
    ] + BOITIER_MONTURE,
    "raquette": TEENSY + [
        ("Écran LCD 2004 I2C (20 x 4, adaptateur PCF8574 au dos, 98 ou 99 x 60 mm)", 1,
         "Freenove ou équivalent, trous M3 à 93 x 55 mm, adresse 0x27 ou 0x3F"),
        ("Entretoise M3 x 15 mm femelle-femelle", 4,
         "Écran sur la carte : plus longues que l'adaptateur I2C (12 mm s'il descend de moins de 11 mm)"),
        ("Vis M3 x 6", 12, "8 pour l'écran sur ses entretoises, 4 pour la carte sur le fond"),
        ("Vis M3 x 10 à tête fraisée", 4, "Fermeture de la face avant"),
        ("Câble Dupont femelle-femelle 4 fils", 1, "Écran vers J_LCD_I2C (GND, 5V, SDA, SCL)"),
        ("Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm)", 1, "Câble vers la monture"),
    ],
}

EN_PLUS["mise_en_station"] = [
    ("Barrette femelle 1 x 15, pas 2,54 mm", 2, "Support de l'Arduino Nano (A1) : il s'enfiche, il n'est pas soudé"),
    ("Module driver StepStick TMC2209 (ou A4988, DRV8825)", 2,
     "Sur DRV_AZ et DRV_ALT ; pour un A4988 ou un DRV8825, fermer le pont RS sous le module"),
    ("Moteur pas à pas NEMA 14 ou 17, avec réducteur si la vis est dure", 2,
     "Un par vis de réglage (azimut, hauteur), relié à la vis par un accouplement ou une courroie"),
    ("Micro-rupteur de fin de course", "0 à 4 (facultatif)",
     "Contact entre MIN ou MAX et GND : arrête le moteur en bout de course de la vis"),
    ("Bloc d'alimentation 12 V, 2 A, jack 5,5 x 2,1 mm (centre +)", 1, "Moteurs ; le Nano est alimenté aussi par l'USB"),
    ("Câble USB mini-B (ou USB-C selon le Nano)", 1, "Nano vers le PC"),
    ("Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm)", "4 (5 avec l'I2C)",
     "2 moteurs, 2 câbles de fins de course ; le 5e trou, fermé par une fine peau, se perce pour l'I2C"),
] + BOITIER_MONTURE + [
    ("Vis M5 (ou M4) et rondelles", 4, "Boîtier sur la monture, par ses 4 pattes"),
]

IMPRESSION = {
    "monture_ext": "boitier_monture_ext_base.stl et boitier_monture_ext_couvercle.stl",
    "monture": "boitier_monture_base.stl et boitier_monture_couvercle.stl",
    "raquette": "boitier_raquette_base.stl, boitier_raquette_face_avant.stl et boitier_raquette_boutons.stl "
                "(les 5 boutons)",
    "mise_en_station": "boitier_mise_en_station_base.stl et boitier_mise_en_station_couvercle.stl",
}

COMMUN = [
    ("Câble 4 conducteurs (GND, +5 V, TX, RX), 3 à 6,5 mm de diamètre", "longueur au choix",
     "Monture vers raquette : soudé sur J_DIN côté raquette"),
    ("Boîtier Dupont femelle 1 x 4 et ses contacts", "1 par câble",
     "Côté monture : J_RAQUETTE, J_GPS et J_PC_SERIAL sont des barrettes mâles 1 x 4"),
    ("Module GPS série alimenté en 5 V, sorties 3,3 V (type NEO-6M)", "1 (facultatif)",
     "Sur J_GPS : heure et position automatiques"),
    ("Adaptateur USB-série en 3,3 V (CP2102, FT232...)", "1 (facultatif)",
     "Sur J_PC_SERIAL ; le port USB du Teensy suffit en général"),
    ("Alimentation 36 V continu, 4 A au moins, ou bloc 12 V à jack", 1,
     "36 V sur le bornier J_PWR_36V, ou 12 V sur le jack J_12V (pas les deux à la fois)"),
    ("Moteurs pas à pas", "1 par axe", "Selon la monture ; courant compatible avec les drivers choisis"),
]


def tableau(lignes, entete):
    sortie = ["| " + " | ".join(entete) + " |", "|" + "---|" * len(entete)]
    sortie += ["| " + " | ".join(str(c).replace("|", "/") for c in l) + " |" for l in lignes]
    return sortie


def composants(carte):
    f = ICI / "fabrication" / f"{carte}_composants.csv"
    lignes = list(csv.reader(f.read_text(encoding="utf-8").splitlines(), delimiter=";"))[1:]
    return [(d, q, r) for d, q, r, _ in lignes]


def ecrire():
    md = ["# Liste d'achat", "",
          "Tout ce qu'il faut acheter pour construire une monture GotoAndrivet : une carte monture (drivers "
          "externes **ou** StepStick) et, si vous les voulez, la raquette et la carte de mise en station robotisée. Pour chaque carte : les composants "
          "à souder dessus, puis les modules, la visserie et les presse-étoupes à prévoir en plus.", "",
          "Les composants soudés sont repris des listes de fabrication (`pcb/fabrication/*_composants.csv`) "
          "par `pcb/liste_achats.py` ; les repères sont ceux de la sérigraphie des cartes.", ""]
    for carte, titre, texte in CARTES:
        lignes = composants(carte)
        md += [f"## {titre}", "", texte, "",
               f"### Composants à souder sur la carte ({sum(int(q) for _, q, _ in lignes)} pièces)", ""]
        md += tableau(lignes, ("Désignation", "Qté", "Repères")) + [""]
        md += ["### À prévoir en plus", ""]
        md += tableau(EN_PLUS[carte], ("Désignation", "Qté", "Pour")) + [""]
        if carte in IMPRESSION:
            md += [f"Boîtier à imprimer en 3D (PETG conseillé dehors) : {IMPRESSION[carte]}, "
                   f"dans `pcb/{carte}/`.", ""]
    md += ["## Câbles, alimentation et moteurs", ""]
    md += tableau(COMMUN, ("Désignation", "Qté", "Pour")) + [""]
    md += ["## Où acheter", "",
           "- Composants des cartes, barrettes, borniers, presse-étoupes, visserie : LCSC (envoyé avec les "
           "cartes si elles sont commandées chez JLCPCB), Mouser, Farnell, Reichelt...",
           "- Teensy 4.1 : PJRC ou ses revendeurs.",
           "- Écran LCD 2004 I2C, drivers, modules StepStick, GPS : revendeurs Arduino, Amazon, AliExpress.",
           "", "Au montage, coupez à ras les pattes de la double diode D_IN et du régulateur (TO-220) : "
           "sinon elles touchent le fond du boîtier.", ""]
    (ICI / "LISTE_ACHATS.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    ecrire()
    print("pcb/LISTE_ACHATS.md écrit")
