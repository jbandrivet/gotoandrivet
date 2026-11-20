# Liste d'achat

Tout ce qu'il faut acheter pour construire une monture GotoAndrivet : une carte monture (drivers externes **ou** StepStick) et, si vous les voulez, la raquette et la carte de mise en station robotisée. Pour chaque carte : les composants à souder dessus, puis les modules, la visserie et les presse-étoupes à prévoir en plus.

Les composants soudés sont repris des listes de fabrication (`pcb/fabrication/*_composants.csv`) par `pcb/liste_achats.py` ; les repères sont ceux de la sérigraphie des cartes.

## Monture : carte drivers externes

Pour des drivers externes (DM542, DM556, TB6600...), un par axe. Boîtier de 202 x 140 x 35 mm.

### Composants à souder sur la carte (39 pièces)

| Désignation | Qté | Repères |
|---|---|---|
| 100nF | 3 | C_DIR C_EN C_STEP |
| 100nF | 1 | C_DEC |
| 100uF 63V | 1 | C_IN |
| 220uF 16V | 1 | C_OUT |
| 220uF 63V | 4 | C_ALT C_AZ C_DEROT C_FOCUS |
| 33uH 3A | 1 | L_BUCK |
| 74ACT125 | 3 | U_DIR U_EN U_STEP |
| Barrette mâle 1 x 4, pas 2,54 mm | 3 | J_GPS J_PC_SERIAL J_RAQUETTE |
| Bornier à vis 2 points, pas 5,08 mm | 5 | J_PWR_36V J_VM_ALT J_VM_AZ J_VM_DEROT J_VM_FOCUS |
| Bornier à vis 4 points, pas 3,5 mm | 4 | J_SIG_ALT J_SIG_AZ J_SIG_DEROT J_SIG_FOCUS |
| Buzzer 12 mm | 1 | BZ1 |
| Diode 1N4148 | 1 | D_BUZ |
| Double diode Schottky MBR20100CT, 100 V 2 x 10 A, cathode commune (TO-220) | 1 | D_IN |
| Fusible TR5 temporisé 4 A (Littelfuse 372) et son support | 1 | F_IN |
| Jack d'alimentation 12 V | 1 | J_12V |
| LM2596HVT-5.0 | 1 | U_LM2596 |
| Réseau de résistances 4 x 10 kOhm, commun broche 1 (SIP5) | 1 | RN_EN |
| Résistance 1 kOhm, 1/4 W | 1 | R_BUZ_B |
| Résistance 10 kOhm, 1/4 W | 1 | R_BUZ_PD |
| Résistance 68 Ohm, 1/4 W | 1 | R_BUZ |
| SB560 (60V 5A) | 1 | D_SCHOTTKY |
| Teensy 4.1 | 1 | U1 |
| Transistor NPN PN2222A (TO-92, brochage E B C) | 1 | Q_BUZ |

### À prévoir en plus

| Désignation | Qté | Pour |
|---|---|---|
| Barrette femelle 1 x 24, pas 2,54 mm | 2 | Support du Teensy (U1) : le Teensy s'enfiche, il n'est pas soudé |
| Barrette mâle 1 x 24, pas 2,54 mm | 2 | À souder sous le Teensy, sauf s'il est vendu avec ses broches |
| Driver de moteur pas à pas externe (DM542, DM556, TB6600...) | 1 par axe (2 à 4) | Branché sur J_VM (alimentation) et J_SIG (EN, STEP, DIR, GND) de son axe |
| Presse-étoupe M20 x 1,5 à joint 2 trous (2 câbles de 4 à 6 mm) | 4 | Un par axe : câble d'alimentation et câble des signaux du driver |
| Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm) | 4 | 36 V, raquette, GPS, PC |
| Vis M3 x 6 | 4 | Carte sur les entretoises du fond (trous de 2,8 mm, la vis taraude le plastique) |
| Vis M3 x 10 à tête fraisée | 4 | Fermeture du couvercle |

Boîtier à imprimer en 3D (PETG conseillé dehors) : boitier_monture_ext_base.stl et boitier_monture_ext_couvercle.stl, dans `pcb/monture_ext/`.

## Monture : carte StepStick

Drivers au format StepStick sur la carte (TMC5160, TMC2209, A4988, DRV8825). Boîtier de 202 x 140 x 45 mm.

### Composants à souder sur la carte (37 pièces)

| Désignation | Qté | Repères |
|---|---|---|
| 100nF | 1 | C_DEC |
| 100uF 63V | 1 | C_IN |
| 220uF 16V | 1 | C_OUT |
| 220uF 63V | 4 | C_ALT C_AZ C_DEROT C_FOCUS |
| 33uH 3A | 1 | L_BUCK |
| Barrette femelle 1 x 8, pas 2,54 mm (support StepStick) | 8 | DRV_ALT_L DRV_ALT_R DRV_AZ_L DRV_AZ_R DRV_DEROT_L DRV_DEROT_R DRV_FOCUS_L DRV_FOCUS_R |
| Barrette mâle 1 x 4, pas 2,54 mm | 3 | J_GPS J_PC_SERIAL J_RAQUETTE |
| Bornier à vis 2 points, pas 5,08 mm | 1 | J_PWR_36V |
| Bornier à vis 4 points, pas 5,08 mm | 4 | M_ALT M_AZ M_DEROT M_FOCUS |
| Buzzer 12 mm | 1 | BZ1 |
| Diode 1N4148 | 1 | D_BUZ |
| Double diode Schottky MBR20100CT, 100 V 2 x 10 A, cathode commune (TO-220) | 1 | D_IN |
| Fusible TR5 temporisé 4 A (Littelfuse 372) et son support | 1 | F_IN |
| Jack d'alimentation 12 V | 1 | J_12V |
| LM2596HVT-5.0 | 1 | U_LM2596 |
| Réseau de résistances 4 x 10 kOhm, commun broche 1 (SIP5) | 1 | RN_EN |
| Résistance 1 kOhm, 1/4 W | 1 | R_BUZ_B |
| Résistance 10 kOhm, 1/4 W | 1 | R_BUZ_PD |
| Résistance 68 Ohm, 1/4 W | 1 | R_BUZ |
| SB560 (60V 5A) | 1 | D_SCHOTTKY |
| Teensy 4.1 | 1 | U1 |
| Transistor NPN PN2222A (TO-92, brochage E B C) | 1 | Q_BUZ |

### À prévoir en plus

| Désignation | Qté | Pour |
|---|---|---|
| Barrette femelle 1 x 24, pas 2,54 mm | 2 | Support du Teensy (U1) : le Teensy s'enfiche, il n'est pas soudé |
| Barrette mâle 1 x 24, pas 2,54 mm | 2 | À souder sous le Teensy, sauf s'il est vendu avec ses broches |
| Module driver StepStick (TMC5160, TMC2209, A4988 ou DRV8825) | 1 par axe (2 à 4) | Sur les supports de la carte ; TMC5160 réglé en SPI après fermeture des ponts à souder |
| Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm) | 8 | 4 moteurs, 36 V, raquette, GPS, PC |
| Vis M3 x 6 | 4 | Carte sur les entretoises du fond (trous de 2,8 mm, la vis taraude le plastique) |
| Vis M3 x 10 à tête fraisée | 4 | Fermeture du couvercle |

Boîtier à imprimer en 3D (PETG conseillé dehors) : boitier_monture_base.stl et boitier_monture_couvercle.stl, dans `pcb/monture/`.

## Raquette

Télécommande à écran LCD 20 x 4. Facultative : la monture se pilote aussi depuis le PC. Boîtier de 113 x 158 x 39 mm.

### Composants à souder sur la carte (14 pièces)

| Désignation | Qté | Repères |
|---|---|---|
| Barrette mâle 1 x 4, pas 2,54 mm | 2 | J_GROVE J_LCD_I2C |
| Bouton poussoir 6 x 6 mm, 4,3 mm de haut (boutons imprimés calés dessus) | 5 | SW_DOWN SW_ENTER SW_LEFT SW_RIGHT SW_UP |
| MOSFET canal N BSS138 (SOT-23) | 2 | Q_SCL Q_SDA |
| Résistance 10 kOhm, 1/4 W | 4 | R_SCL_3V3 R_SCL_5V R_SDA_3V3 R_SDA_5V |
| Teensy 4.1 | 1 | U1 |

### À prévoir en plus

| Désignation | Qté | Pour |
|---|---|---|
| Barrette femelle 1 x 24, pas 2,54 mm | 2 | Support du Teensy (U1) : le Teensy s'enfiche, il n'est pas soudé |
| Barrette mâle 1 x 24, pas 2,54 mm | 2 | À souder sous le Teensy, sauf s'il est vendu avec ses broches |
| Écran LCD 2004 I2C (20 x 4, adaptateur PCF8574 au dos, 98 ou 99 x 60 mm) | 1 | Freenove ou équivalent, trous M3 à 93 x 55 mm, adresse 0x27 ou 0x3F |
| Entretoise M3 x 15 mm femelle-femelle | 4 | Écran sur la carte : plus longues que l'adaptateur I2C (12 mm s'il descend de moins de 11 mm) |
| Vis M3 x 6 | 12 | 8 pour l'écran sur ses entretoises, 4 pour la carte sur le fond |
| Vis M3 x 10 à tête fraisée | 4 | Fermeture de la face avant |
| Câble Dupont femelle-femelle 4 fils | 1 | Écran vers J_LCD_I2C (GND, 5V, SDA, SCL) |
| Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm) | 1 | Câble vers la monture |

Boîtier à imprimer en 3D (PETG conseillé dehors) : boitier_raquette_base.stl, boitier_raquette_face_avant.stl et boitier_raquette_boutons.stl (les 5 boutons), dans `pcb/raquette/`.

## Mise en station robotisée

Facultative, pour les montures équatoriales : deux moteurs tournent les vis de réglage en azimut et en hauteur, commandés par le PC (onglet Mise en station du module Caméra). Carte de 110 x 85 mm, reliée au PC par l'USB de son Arduino Nano, moteurs en 12 V.

### Composants à souder sur la carte (28 pièces)

| Désignation | Qté | Repères |
|---|---|---|
| 100nF | 5 | C_FC1 C_FC2 C_FC3 C_FC4 C_VS |
| 100uF 35V | 2 | C_ALT C_AZ |
| 470uF 35V | 1 | C_IN |
| Arduino Nano (ATmega328P, 5 V) : enfiché sur 2 barrettes femelles 1 x 15 | 1 | A1 |
| Barrette femelle 1 x 8, pas 2,54 mm (support StepStick) | 4 | DRV_ALT_L DRV_ALT_R DRV_AZ_L DRV_AZ_R |
| Barrette mâle 1 x 4, pas 2,54 mm | 1 | J_I2C |
| Bornier à vis 3 points, pas 3,5 mm | 2 | J_FC_ALT J_FC_AZ |
| Bornier à vis 4 points, pas 5,08 mm | 2 | M_ALT M_AZ |
| Diode Schottky 1N5822 (40 V, 3 A, DO-201AD) | 1 | D_IN |
| Fusible TR5 temporisé 2 A (Littelfuse 372) et son support | 1 | F_IN |
| Jack d'alimentation 12 V | 1 | J_12V |
| LED verte 3 mm | 1 | D_ACT |
| Réseau de résistances 4 x 10 kOhm, commun broche 1 (SIP5) | 1 | RN_FC |
| Résistance 1 kOhm, 1/4 W | 1 | R_LED |
| Résistance 10 kOhm, 1/4 W | 3 | R_EN_ALT R_EN_AZ R_VS2 |
| Résistance 47 kOhm, 1/4 W | 1 | R_VS1 |

### À prévoir en plus

| Désignation | Qté | Pour |
|---|---|---|
| Barrette femelle 1 x 15, pas 2,54 mm | 2 | Support de l'Arduino Nano (A1) : il s'enfiche, il n'est pas soudé |
| Module driver StepStick TMC2209 (ou A4988, DRV8825) | 2 | Sur DRV_AZ et DRV_ALT ; pour un A4988 ou un DRV8825, fermer le pont RS sous le module |
| Moteur pas à pas NEMA 14 ou 17, avec réducteur si la vis est dure | 2 | Un par vis de réglage (azimut, hauteur), relié à la vis par un accouplement ou une courroie |
| Micro-rupteur de fin de course | 0 à 4 (facultatif) | Contact entre MIN ou MAX et GND : arrête le moteur en bout de course de la vis |
| Bloc d'alimentation 12 V, 2 A, jack 5,5 x 2,1 mm (centre +) | 1 | Moteurs ; le Nano est alimenté aussi par l'USB |
| Câble USB mini-B (ou USB-C selon le Nano) | 1 | Nano vers le PC |
| Presse-étoupe PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm) | 4 (5 avec l'I2C) | 2 moteurs, 2 câbles de fins de course ; le 5e trou, fermé par une fine peau, se perce pour l'I2C |
| Vis M3 x 6 | 4 | Carte sur les entretoises du fond (trous de 2,8 mm, la vis taraude le plastique) |
| Vis M3 x 10 à tête fraisée | 4 | Fermeture du couvercle |
| Vis M5 (ou M4) et rondelles | 4 | Boîtier sur la monture, par ses 4 pattes |

Boîtier à imprimer en 3D (PETG conseillé dehors) : boitier_mise_en_station_base.stl et boitier_mise_en_station_couvercle.stl, dans `pcb/mise_en_station/`.

## Câbles, alimentation et moteurs

| Désignation | Qté | Pour |
|---|---|---|
| Câble 4 conducteurs (GND, +5 V, TX, RX), 3 à 6,5 mm de diamètre | longueur au choix | Monture vers raquette : soudé sur J_DIN côté raquette |
| Boîtier Dupont femelle 1 x 4 et ses contacts | 1 par câble | Côté monture : J_RAQUETTE, J_GPS et J_PC_SERIAL sont des barrettes mâles 1 x 4 |
| Module GPS série alimenté en 5 V, sorties 3,3 V (type NEO-6M) | 1 (facultatif) | Sur J_GPS : heure et position automatiques |
| Adaptateur USB-série en 3,3 V (CP2102, FT232...) | 1 (facultatif) | Sur J_PC_SERIAL ; le port USB du Teensy suffit en général |
| Alimentation 36 V continu, 4 A au moins, ou bloc 12 V à jack | 1 | 36 V sur le bornier J_PWR_36V, ou 12 V sur le jack J_12V (pas les deux à la fois) |
| Moteurs pas à pas | 1 par axe | Selon la monture ; courant compatible avec les drivers choisis |

## Où acheter

- Composants des cartes, barrettes, borniers, presse-étoupes, visserie : LCSC (envoyé avec les cartes si elles sont commandées chez JLCPCB), Mouser, Farnell, Reichelt...
- Teensy 4.1 : PJRC ou ses revendeurs.
- Écran LCD 2004 I2C, drivers, modules StepStick, GPS : revendeurs Arduino, Amazon, AliExpress.

Au montage, coupez à ras les pattes de la double diode D_IN et du régulateur (TO-220) : sinon elles touchent le fond du boîtier.
