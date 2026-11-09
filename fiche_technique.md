# FICHE TECHNIQUE : SYSTÈME DE COMMANDE GOTO-ANDRIVET
*Version 9.2 (Dual Architecture : Mega & Teensy) — Juin 2026*

Ce document regroupe les spécifications électriques, le schéma de câblage des drivers **M542**, les paramètres mécaniques et les protocoles de communication pour le système de commande motorisé GoTo universel (GotoAndrivet).

---

## 1. Choix de l'Architecture (Monture Mega vs Teensy)

Le projet **Goto-Andrivet** propose désormais deux versions différentes pour le "cerveau" de la monture (le contrôleur moteur principal). Le choix de la carte affecte directement la puissance de calcul pour le suivi et les modèles de pointage.

### Option A : Contrôleur Arduino Mega 2560 (Dossier `mega_monture`)
* **Processeur :** 8-bit AVR @ 16 MHz.
* **Avantage :** Matériel très standard, robuste et peu cher.
* **Inconvénient :** Puissance de calcul très limitée. Il effectue d'excellents suivis basiques (1 étoile), mais il est incapable de faire fonctionner des modèles de pointage complexes (multi-étoiles) sans perdre la fluidité des moteurs.

### Option B : Contrôleur Teensy 4.1 (Dossier `teensy_monture`)
* **Processeur :** 32-bit ARM Cortex-M7 @ 600 MHz avec coprocesseur mathématique (FPU).
* **Avantage :** Une puissance phénoménale. Il génère des pas moteurs d'une fluidité parfaite même à très haute vitesse et permet les calculs matriciels complexes requis pour l'alignement multi-étoiles sans aucune saccade.
* **Inconvénient :** Plus coûteux.

> [!NOTE]
> Quel que soit le contrôleur choisi pour la monture, la télécommande (**Raquette**) reste toujours propulsée par un Teensy 4.1 (Dossier `teensy_raquette`) en raison de l'affichage graphique LCD et des calculs d'éphémérides requis.

---

## 2. Caractéristiques de Communication

*   **Liaison USB (PC / ASIAir / INDI) :** **38 400 bauds** (Vitesse optimisée pour la télémétrie en temps réel).
*   **Liaison Série PC (Connecteur PCB 4 broches / Serial6) :** **38 400 bauds** (Idéal pour câbles très longs avec adaptateur TTL/RS485).
*   **Liaison Raquette (Connecteur DIN 4 broches / Serial3) :** **38 400 bauds**.
*   **Protocole :** Meade LX200 avec extensions OnStep (supporté par KStars/Ekos, Stellarium, SkySafari).

---

## 3. Schéma de Câblage Électrique (Côté Monture)

Le câblage des drivers moteurs vers le contrôleur reste quasiment identique quelle que soit la carte utilisée. Les drivers M542 sont raccordés en configuration **Cathode Commune (GND commun)**.

### Broches selon le contrôleur choisi :

| Composant | Broche Arduino Mega 2560 | Broche Teensy 4.1 |
|---|---|---|
| **Moteur AZ (Step)** | Pin 2 | Pin 2 |
| **Moteur AZ (Dir)** | Pin 3 | Pin 3 |
| **Moteur ALT (Step)** | Pin 5 | Pin 5 |
| **Moteur ALT (Dir)** | Pin 6 | Pin 6 |
| **Buzzer (Actif ou Passif)** | Pin 49 | Pin 20 |
| **GPS (RX / TX)** | Pin 17 / Pin 16 (Serial2) | Pin 16 / Pin 17 (Serial4) |
| **Raquette (RX / TX)** | Pin 15 / Pin 14 (Serial3) | Pin 15 / Pin 14 (Serial3) |
| **TMC5160 SPI (MOSI / SCK / MISO)** | — | Pin 26 / Pin 27 / Pin 39 (SPI1) |
| **TMC5160 CS (AZ / ALT / Dérot. / Focus)** | — | Pin 41 / Pin 40 / Pin 38 / Pin 37 |

> [!NOTE]
> Les lignes SPI ne rejoignent les supports StepStick du PCB que par les ponts à souder `SPI` (5 par support, à fermer uniquement pour un TMC5160). Le firmware Teensy configure alors les modules au démarrage : courant, micro-pas (puissance de 2 obligatoire), stealthChop. Voir la section matérielle du README.
>
> Deux PCB monture existent, avec le même brochage du Teensy : la carte **StepStick** (`pcb/monture/`, supports de modules et bus SPI ci-dessus) et la carte **drivers externes** (`pcb/monture_ext/`, sans SPI), qui sort EN/STEP/DIR en 5 V et l'alimentation VM pour chaque axe. Voir la section *Cartes Monture* du README.

> [!IMPORTANT]
> Sur le Teensy 4.1, le GPS utilise toujours les broches 16 et 17, mais elles correspondent au port matériel `Serial4` (au lieu du `Serial2` sur le Mega), et **leurs rôles sont inversés** :
> - sur le Mega, la broche 17 est RX2 : le TX du GPS va sur la broche 17 ;
> - sur le Teensy, la broche 16 est RX4 : le TX du GPS va sur la broche 16.
>
> Il faut donc **croiser les deux fils GPS** quand on passe d'un Mega à un Teensy. Le PCB monture (Teensy) est déjà câblé ainsi.

---

## 4. Paramètres Mécaniques et Résolutions

La résolution de déplacement (PPD - Pas par Degré) de la monture est calculée selon la formule :

$$PPD = \frac{\text{Pas Moteur} \times \text{Microstepping} \times \text{Rapport Réduction}}{360}$$

### Valeurs (À configurer par l'utilisateur) :
*   **Pas moteur par tour :** Généralement 200 pas (pour des moteurs 1.8°).
*   **Microstepping :** À configurer selon votre driver (ex: 16, 32, 64, 128). Avec des TMC5160 en SPI, le firmware règle lui-même les micro-pas du driver : la valeur doit être une puissance de 2 (16 à 256).
*   **Rapport de réduction (AZ/ALT) :** Défini par l'utilisateur (à configurer impérativement via l'utilitaire selon votre mécanique propre).
*   **Résolution calculée (PPD) :** Calculée automatiquement par l'utilitaire en fonction des trois valeurs ci-dessus.

---

## 5. Modes de Suivi (Tracking)

*   **Suivi Sidéral (Ciel profond) :** Calculé en temps réel à partir du Temps Sidéral Local (LST) de l'horloge : position complète toutes les 5 s, correction toutes les 200 ms.
*   **Suivi Lunaire (`:TL#`) :** La carte calcule elle-même le déplacement de la Lune (formules abrégées de Meeus, vue depuis le lieu d'observation, parallaxe comprise) et la suit en ascension droite **et en déclinaison**. La Lune change de déclinaison jusqu'à 6° par jour : une simple vitesse ralentie (l'ancien facteur `0.963499`) la laissait sortir du champ de 15 à 25′ par heure. Sur le banc d'essai, l'écart reste sous 0,3′ en 3 heures.
*   **Suivi Solaire (`:TS#`) :** Même principe pour le Soleil (sa déclinaison varie jusqu'à 0,4° par jour).
*   **Réfraction :** L'air remonte les astres (29′ à l'horizon, 5,4′ à 10° de hauteur, 1′ à 45°). Elle est corrigée au GoTo comme au suivi, sur les deux axes, avec 1010 hPa et 10 °C. Active par défaut ; `:Tn#` la coupe, `:To#` ou `:Tr#` la remettent (dans Ekos : réglage *Compensation*). Le statut `:GU#` porte alors la lettre `t`, qu'Ekos affiche « Full Comp ». Elle s'efface tout près du pôle céleste (au-delà de 89,8° de déclinaison), où elle ferait tourner l'axe horaire pour rien.
*   **GoTo anticipé :** Le ciel tourne de 15″ par seconde. La carte vise donc l'endroit où sera l'objet à l'arrivée du GoTo : la durée du trajet est calculée d'après la rampe des moteurs, puis corrigée par ce qu'ont duré les GoTo précédents. À l'arrivée, l'écart est de l'ordre de 0,1′ (contre 3 à 10′ avant).

### Modèle de pointage (Teensy uniquement)

Chaque synchro (`:CM#`, par exemple après une photo résolue par astrométrie) enregistre un point, jusqu'à 50. La carte en déduit les défauts de la monture, par moindres carrés :

| Terme | Défaut |
| :--- | :--- |
| IH, ID | Décalage des deux codeurs (zéro des axes) |
| P, Q | Inclinaison de l'axe principal : mise en station (équatoriale) ou calage du trépied (alt-az) |
| CH | Tube pas d'équerre avec l'axe de déclinaison (ou d'altitude) |
| NP | Les deux axes ne sont pas perpendiculaires |
| TF | Flexion du tube (alt-az seulement) |

Avec 1 étoile, seul le décalage est corrigé ; avec 2, la mise en station s'ajoute ; à partir de 3, tous les termes. Ce qui reste à chaque étoile est ensuite interpolé, pour tomber juste sur les étoiles de synchro ; loin d'elles, seuls les défauts calculés servent. Sur monture simulée (décalages de 2°, mise en station fausse de 1°), 5 étoiles donnent 0,3 à 1,8′ d'erreur médiane sur tout le ciel, contre 11 à 56′ avec l'ancienne interpolation seule. `:CML#` efface le modèle. La Mega garde la synchro à une étoile (elle recale les axes).

---

## 6. Câblage de la Raquette Physique (Teensy 4.1)

La raquette physique est articulée autour d'une carte **Teensy 4.1**.

### 1. Connecteur DIN 4 broches (Communication + Alimentation depuis la Monture)

| Pin DIN | Signal | Broche Teensy |
|---|---|---|
| **1** | GND | **GND** |
| **2** | 5V (alimentation) | **VIN** |
| **3** | TX (Teensy → Monture) | **Pin 1 (TX1)** |
| **4** | RX (Monture → Teensy) | **Pin 0 (RX1)** |

> [!WARNING]
> La monture doit fournir assez de courant au Teensy via la pin VIN. Ne pas alimenter le Teensy par son port USB si le câble DIN l'alimente déjà, sauf si le pad `VUSB` sous le Teensy a été physiquement sectionné.

### 2. Écran LCD 20x4 I2C (module PCF8574, adresse `0x27` ou `0x3F`)
L'adaptateur I2C de l'écran répond en `0x27` avec une puce PCF8574T, en `0x3F` avec une PCF8574AT (Freenove et d'autres livrent l'une ou l'autre) : la raquette essaie les deux au démarrage.

* **SDA** $\rightarrow$ Broche **Pin 18 (SDA0)** de la Teensy
* **SCL** $\rightarrow$ Broche **Pin 19 (SCL0)** de la Teensy
* **VCC** $\rightarrow$ Broche **5V** (VIN)
* **GND** $\rightarrow$ Broche **GND**

> [!WARNING]
> Le Teensy 4.1 **ne tolère pas le 5V** sur ses broches. Or le module PCF8574 alimenté en 5V tire SDA et SCL vers 5V par ses résistances de rappel. Pour protéger le Teensy, intercalez un adaptateur de niveau I2C 3,3V ↔ 5V (type BSS138) entre le Teensy et l'écran. À défaut, dessoudez les résistances de rappel du module. La carte raquette (`pcb/raquette/`) a déjà cet adaptateur (`Q_SDA`, `Q_SCL`) : l'écran et la prise Grove s'y branchent en 5V sans rien modifier.

### 3. Boutons Poussoirs (Clavier directionnel)
Les boutons sont câblés en **INPUT_PULLUP** (reliés entre la broche et le GND). Aucun besoin de résistance externe !

* **Haut (UP)** $\rightarrow$ Broche **Pin 6**
* **Bas (DOWN)** $\rightarrow$ Broche **Pin 7**
* **Gauche (LEFT)** $\rightarrow$ Broche **Pin 8**
* **Droite (RIGHT)** $\rightarrow$ Broche **Pin 9**
* **Entrée/OK (ENTER)** $\rightarrow$ Broche **Pin 10**
