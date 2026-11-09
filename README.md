# GotoAndrivet — Contrôleur Multi-Montures OnStep

**Site du projet : [goto-andrivet.duckdns.org](https://goto-andrivet.duckdns.org)**

**Fonctionne sous Linux et sous Windows** : [installation Linux](#installation-en-un-clic-linux) ·
[installation Windows](#installation-windows). La monture et ses firmwares sont les mêmes : une carte
flashée une fois sert avec les deux.

Ce projet supporte de manière universelle trois types de montures astronomiques :
1. **Alt-Azimutale (AltAz)** : Pour montures Dobson et Alt-Azimutales standards.
2. **Fourche Équatoriale (ForkEq)** : Pour montures équatoriales à fourche ou tables équatoriales (aucun retournement de méridien requis, suivi sidéral direct sur l'angle horaire).
3. **Monture Équatoriale Allemande (GermanEq / GEM)** : Pour montures équatoriales allemandes (gestion automatique du **retournement de méridien** et de la position de pilier *Pier Side* Est/Ouest).

---

## Installation en un clic (Linux)

La carte du ciel et GoTo (**GotoAndrivet**) et le **configurateur** s'installent ensemble, avec leurs raccourcis sur le Bureau et dans le menu des applications. L'installateur prend toujours la dernière version du dépôt ; ensuite, le bouton « Mise à jour » des applications suffit.

**Ubuntu et Debian, le plus simple : [⬇ Télécharger GotoAndrivet.deb](https://github.com/jbandrivet/gotoandrivet/releases/latest/download/GotoAndrivet.deb)**

1. Double-cliquez sur le fichier téléchargé : le Centre d'applications s'ouvre. Cliquez sur **Installer** (votre mot de passe est demandé).
2. Ouvrez **GotoAndrivet - Carte du ciel** depuis le menu des applications. La première fois, GotoAndrivet s'installe dans votre dossier personnel (quelques minutes), puis s'ouvre.

**Autres distributions : [⬇ Télécharger l'installateur Linux](https://github.com/jbandrivet/gotoandrivet/releases/latest/download/Install_Goto_Universal)**, puis, dans le dossier Téléchargements :

1. clic droit sur `Install_Goto_Universal` → **Propriétés** → activez **Exécutable comme programme** ;
2. clic droit → **Exécuter comme un programme**, puis « Installer ».

Le double-clic ne lance pas un programme téléchargé : il propose de chercher une application dans le Centre d'applications, qui ne trouve rien. Passez par le clic droit.

Ou en une seule commande, dans un terminal :

```sh
wget -qO- https://raw.githubusercontent.com/jbandrivet/gotoandrivet/main/installer.sh | sh
```

Prérequis pour l'installateur et la commande (le paquet .deb les installe tout seul) : `sudo apt install python3-venv python3-tk`. Pour le module caméra : `sudo apt install astrometry.net astrometry-data-tycho2` et le SDK caméra de ZWO.

**Connexion de la monture** : dans la carte du ciel, laissez le port sur **Auto** et cliquez sur **Connecter**. La carte du ciel essaie d'abord le dernier port qui a marché, puis les cartes Teensy et Arduino, puis les adaptateurs série USB (CH340, FTDI, CP210x, PL2303), et garde celui où la monture répond. Les ports déjà pris (KStars, dérotateur) sont sautés. Si la recherche ne trouve rien, choisissez le port dans la liste, ou tapez-le, par exemple `/dev/ttyACM0`.

---

## Installation (Windows)

Trois `.exe` autonomes, sans installation : copiez-les dans un dossier à vous (Documents, Bureau) et
double-cliquez.

* **[⬇ GotoAndrivet_Carte_du_ciel.exe](https://github.com/jbandrivet/gotoandrivet/releases/download/windows/GotoAndrivet_Carte_du_ciel.exe)** : la carte du ciel et le GoTo
* **[⬇ GotoAndrivet_Configurateur.exe](https://github.com/jbandrivet/gotoandrivet/releases/download/windows/GotoAndrivet_Configurateur.exe)** : le réglage de la monture
* **[⬇ GotoAndrivet_Raquette.exe](https://github.com/jbandrivet/gotoandrivet/releases/download/windows/GotoAndrivet_Raquette.exe)** : la raquette virtuelle

La monture (Arduino Mega, clone ou Teensy) est trouvée toute seule sur son port COM. Si Windows affiche
« Windows a protégé votre ordinateur » : **Informations complémentaires** → **Exécuter quand même** (les
`.exe` ne sont pas signés).

Les `.exe` sont fabriqués par GitHub à chaque modification du programme
([release `windows`](https://github.com/jbandrivet/gotoandrivet/releases/tag/windows)) ; le bouton
« Mise à jour » passe au rouge quand une nouvelle version existe et les remplace d'un clic. Pas
disponibles sous Windows : caméras ZWO, focuseur EAF, astrométrie et guidage. Fabrication : dossier
[`windows/`](windows/LISEZMOI.txt).

## Structure du Projet

* **`goto_andrivet.py`** : L'application principale en Python (interface graphique Tkinter avec carte du ciel interactive : étoiles, constellations, Soleil, Lune et planètes, catalogues Messier/NGC/IC/Caldwell, dérotateur et mise à jour en ligne).
* **`photo.py`** : Le module caméra de la carte du ciel (caméra ZWO ou simulée, photos FITS, astrométrie locale avec solve-field, correction après GoTo, modèle de pointage, angle de cadrage).
* **`guidage.py`** : Le module de guidage de la carte du ciel (deuxième caméra ZWO ou simulée, calibration automatique, corrections envoyées par le PC à la monture, courbe des erreurs, dithering entre les poses).
* **`goto_andrivet_config_tool.py`** : L'utilitaire de configuration en style Windows 95 permettant de régler les coordonnées, vitesses, rapports d'engrenage et de flasher le firmware.
* **`raquette_virtuelle.py`** : L'émulateur de la raquette Teensy pour piloter le télescope depuis l'ordinateur.
* **`ciel_donnees.py`** : Les données de la carte du ciel : étoiles du Yale Bright Star Catalogue jusqu'à la magnitude 6,5, lignes et noms des 88 constellations (Stellarium, CC BY-SA 4.0), objets Messier, Caldwell, NGC et IC (OpenNGC, CC BY-SA 4.0). Fichier généré par `outils/generer_ciel_donnees.py` : ne pas le modifier à la main.
* **`mise_a_jour.py`** : La mise à jour en ligne depuis GitHub, commune à la carte du ciel et à l'utilitaire de configuration.
* **`outils/`** : Le générateur de `ciel_donnees.py` (il télécharge les catalogues auprès du CDS, de Stellarium et d'OpenNGC).
* **`mega_monture/`** : Le firmware classique (1 étoile) pour le contrôleur Arduino Mega 2560.
* **`teensy_monture/`** : Le nouveau firmware haute performance pour contrôleur Teensy 4.1 (inclut le modèle de pointage : défauts de la monture calculés sur 50 étoiles au plus).
* **`teensy_raquette/`** : Le firmware C++ pour la raquette physique avec écran LCD (sur Teensy 4.1).

---

## Guide d'Installation & Mode d'Emploi

### 1. Prérequis
Pour exécuter les applications graphiques en Python sur votre ordinateur, vous devez disposer de **Python 3**, du module **Tkinter** et de la bibliothèque **pyserial**. La bibliothèque **ephem** est facultative : elle affiche le Soleil, la Lune et les planètes sur la carte du ciel.

Sur Ubuntu / Debian / Raspberry Pi OS, installez-les via votre terminal :
```bash
sudo apt update
sudo apt install python3 python3-tk python3-pip
pip3 install pyserial ephem
```

### 2. Démarrage des Applications
Exécutez les scripts Python correspondants depuis le dossier du projet :

* **Configuration & Flashage** :
  ```bash
  python3 goto_andrivet_config_tool.py
  ```
* **Cartographie du Ciel & Pilotage** :
  ```bash
  python3 goto_andrivet.py
  ```
* **Raquette Virtuelle (Émulateur)** :
  ```bash
  python3 raquette_virtuelle.py
  ```

### 3. Compiler & Flasher sans IDE Arduino
Vous pouvez programmer vos cartes directement depuis l'utilitaire de configuration (sans avoir besoin d'ouvrir l'IDE Arduino classique) :
1. Installez l'utilitaire [arduino-cli](https://arduino.github.io/arduino-cli/latest/) sur votre PC.
2. Ouvrez l'utilitaire de configuration (`python3 goto_andrivet_config_tool.py`).
3. Sélectionnez le **Port** série de votre carte dans les paramètres de connexion.
4. Dans l'encadré **« Téléversement du Firmware »**, cliquez sur le bouton correspondant à votre carte pour compiler et flasher automatiquement.

### 4. Schéma de Câblage Rapide (Monture : Mega ou Teensy)

Câblez votre contrôleur principal en suivant ce schéma (les broches sont identiques pour le Mega et le Teensy, à l'exception du Buzzer, de l'`ENB` du focuseur et du GPS, dont les fils TX/RX sont croisés d'une carte à l'autre) :

| Composant / Axe | Broche Arduino Mega 2560 | Broche Teensy 4.1 | Signal Module / Driver |
| :--- | :--- | :--- | :--- |
| **Moteur Azimut (AZ/RA)** | **Pin 2** | **Pin 2** | `PUL+` (Pulse/Step) |
| | **Pin 3** | **Pin 3** | `DIR+` (Direction) |
| | **Pin 4** | **Pin 4** | `ENB+` (Enable) |
| **Moteur Altitude (ALT/DEC)** | **Pin 5** | **Pin 5** | `PUL+` (Pulse/Step) |
| | **Pin 6** | **Pin 6** | `DIR+` (Direction) |
| | **Pin 7** | **Pin 7** | `ENB+` (Enable) |
| **Moteur Dérotateur** | **Pin 8** | **Pin 8** | `PUL+` (Pulse/Step) |
| | **Pin 9** | **Pin 9** | `DIR+` (Direction) |
| | **Pin 10** | **Pin 10** | `ENB+` (Enable) |
| **Moteur Focuseur** | **Pin 11** | **Pin 11** | `PUL+` (Pulse/Step) |
| | **Pin 12** | **Pin 12** | `DIR+` (Direction) |
| | **Pin 13** | **Pin 21** | `ENB+` (Enable) |
| **Buzzer** | **Pin 49** | **Pin 20** | Mega : borne `+` en direct (buzzer actif). Teensy : par un transistor (voir § 6) |
| **Port Série PC** | **Non dispo** | **Pin 25 (RX6)** | `TX` de l'adaptateur USB/Série TTL (Câble long) |
| | **Non dispo** | **Pin 24 (TX6)** | `RX` de l'adaptateur USB/Série TTL |
| **Raquette Teensy** | **Pin 15 (RX3)** | **Pin 15 (RX3)** | `TX` de la raquette Teensy |
| | **Pin 14 (TX3)** | **Pin 14 (TX3)** | `RX` de la raquette Teensy |
| **Module GPS** | **Pin 17 (RX2)** | **Pin 16 (RX4)** | `TX` du module GPS |
| | **Pin 16 (TX2)** | **Pin 17 (TX4)** | `RX` du module GPS |
| **Drivers TMC5160 (SPI1, PCB)** | **Non dispo** | **Pin 26 (MOSI1)** | `SDI` des modules (ponts SPI fermés) |
| | **Non dispo** | **Pin 27 (SCK1)** | `SCK` des modules |
| | **Non dispo** | **Pin 39 (MISO1)** | `SDO` des modules |
| | **Non dispo** | **Pins 41 / 40 / 38 / 37** | `CSN` AZ / ALT / Dérotateur / Focuseur |

*Note : Les signaux de masse négatifs (`PUL-`, `DIR-`, `ENB-` des drivers, GND du buzzer, du GPS et de la Teensy) doivent tous être connectés à une broche **GND** de votre carte.*
*(Consultez le fichier `fiche_technique.md` pour des explications approfondies).*

### 4.1 Schéma de Câblage de la Raquette (Teensy 4.1)

Si vous fabriquez la raquette physique avec un Teensy 4.1, voici le câblage à effectuer :

| Composant | Broche Teensy 4.1 | Connexion / Signal |
| :--- | :--- | :--- |
| **Écran LCD (I2C)** | **Pin 18 (SDA0)** | `SDA` de l'écran LCD |
| | **Pin 19 (SCL0)** | `SCL` de l'écran LCD |
| | **VIN** | `VCC` (5V) de l'écran LCD |
| | **GND** | `GND` de l'écran LCD |
| **Boutons Poussoirs** | **Pin 6** | Bouton **Haut (UP)** (vers GND) |
| | **Pin 7** | Bouton **Bas (DOWN)** (vers GND) |
| | **Pin 8** | Bouton **Gauche (LEFT)** (vers GND) |
| | **Pin 9** | Bouton **Droite (RIGHT)** (vers GND) |
| | **Pin 10** | Bouton **Validation (ENTER)** (vers GND) |
| **Câble RJ11 (vers Mega)**| **GND** | Pin 1 RJ11 (`GND` de la Monture) |
| | **VIN** | Pin 2 RJ11 (`VIN` / `5V` de la Monture) |
| | **Pin 1 (TX1)** | Pin 3 RJ11 (vers `RX3` Pin 15 Monture) |
| | **Pin 0 (RX1)** | Pin 4 RJ11 (vers `TX3` Pin 14 Monture) |

*ATTENTION : Le Teensy est alimenté par la pin 5V du Mega via VIN. Ne pas brancher l'USB du Teensy en même temps, sauf si le pad VUSB a été coupé au préalable.*

### 5. Arduino Mega 2560 vs Teensy 4.1 (Contrôleur de Monture)

Le projet vous permet de choisir le cerveau principal de la monture. Bien que le câblage soit quasiment identique, voici les différences pour vous aider à choisir :

| Caractéristique | Arduino Mega 2560 | Teensy 4.1 |
| :--- | :--- | :--- |
| **Vitesse de calcul** | 16 MHz (8-bit) | **600 MHz** (32-bit ARM) |
| **Précision (Maths)** | Flottants 32-bit lents | **Flottants 64-bit (double)** natifs ultra-rapides |
| **Microstepping & Vitesse max**| Limité (saturera à très haut microstepping) | **Parfait** (génère des impulsions à plus de 200kHz sans sourciller) |
| **Modèle de pointage** | Synchro à une étoile | **Défauts de la monture** calculés sur 50 étoiles au plus |
| **Evolutivité (Futur)** | Faible | **Très haute** (Port USB Host pour Manette/Gamepad) |
| **Coût** | ~15-20€ (Clones pas chers) | ~35-40€ |

**Recommandation** : Si vous utilisez de petits drivers (1/16 ou 1/32 de pas) et voulez un système économique, le **Mega 2560** fait parfaitement le travail. Si vous utilisez des drivers modernes (TMC2209, M542) à fort microstepping (1/128, 1/256), que vous voulez des déplacements GoTo ultra-rapides et silencieux, et le modèle de pointage multi-étoiles intégré, optez sans hésiter pour le **Teensy 4.1**.

### 6. Matériel Compatible

Pour monter votre système GotoAndrivet, les composants matériels suivants sont compatibles et recommandés :

* **Cartes de Contrôle** :
  * **Arduino Mega 2560** ou **Teensy 4.1** (au choix pour la carte principale de la monture).
  * **Teensy 4.1** (pour la raquette de commande physique - *Optionnelle*).
* **Drivers de Moteurs** :
  * Drivers standard acceptant des entrées `PUL/DIR` (Impulsion/Direction) comme les modèles **M542**, **DM542**, **TB6600**, **TMC2209**, etc.
  * Deux PCB monture (Teensy) au choix : une carte à modules StepStick, dont le **BTT TMC5160 Pro** configuré en SPI, et une carte pour drivers externes (voir *Cartes Monture* plus bas).
* **Moteurs** :
  * Moteurs pas à pas bipolaires (ex. **NEMA 17** ou **NEMA 23** en 200 pas/tour).
* **Module GPS (Optionnel)** :
  * Module **Adafruit Ultimate GPS** (MTK3339) ou tout autre récepteur GPS délivrant des trames NMEA standards à 9600 bauds sur port série.
* **Afficheur Raquette** :
  * Écran **LCD 20x4** caractères équipé d'un adaptateur **I2C** (généralement à l'adresse `0x27`).
* **Boutons Raquette** :
  * 5 boutons poussoirs momentanés (Haut, Bas, Gauche, Droite, Validation).
* **Alerte Sonore** :
  * Un **Buzzer actif 5V** ou un **Buzzer passif**. Sur le Mega, un buzzer actif se câble directement. Sur le Teensy, passez par un transistor : une broche ne fournit que quelques mA, et un buzzer passif en tire 80 à 200. Un NPN (PN2222A) avec 1 kΩ sur la base, le buzzer entre le 5V et le collecteur, en série avec 68 Ω, et une diode 1N4148 à ses bornes : c'est le montage des cartes.

*Note concernant la raquette physique : La construction de la raquette matérielle (carte Teensy, écran LCD et boutons) n'est **pas obligatoire**. Si vous utilisez la monture en mode "remote", ou que vous la pilotez exclusivement depuis un PC, un planétarium, ou un boîtier type ASIAIR, l'Arduino Mega suffit à lui seul pour tout gérer via la connexion USB.*

---

## Fonctionnalités Avancées

* **Modèle de pointage (Teensy Monture uniquement)** : à partir de 50 étoiles de synchro au plus, la carte calcule les défauts de la monture (décalage des axes, mise en station, tube pas d'équerre, axes pas perpendiculaires, flexion), puis interpole ce qui reste pour tomber juste sur chaque étoile. Le modèle est gardé en mémoire d'une soirée à l'autre si la monture est éteinte parquée. Remise à zéro par `:CML#` (bouton « Effacer le modèle » du module caméra).
* **Suivi de la Lune et du Soleil calculé** (les deux cartes) : position de l'astre recalculée en continu, en ascension droite et en déclinaison.
* **Réfraction corrigée** (les deux cartes) : au GoTo et au suivi, réglable depuis Ekos (*Compensation*, `:To#` / `:Tn#`).
* **GoTo anticipé** (les deux cartes) : la carte vise l'endroit où sera l'objet à l'arrivée.
* **Ajout du type de monture `GermanEq`** : Le firmware de l'Arduino Mega calcule automatiquement les inversions d'axes (Ascension Droite et Déclinaison) lors du franchissement du méridien.
* **Commande standard `:Gm#` implémentée** : Renvoie le *Pier Side* (`E#` pour l'Est, `W#` pour l'Ouest, `N#` pour les autres modes) requis pour les logiciels de guidage comme Ekos/INDI.
* **Commande standard `:D#` implémentée** : Permet l'interrogation dynamique du statut de pointage (Slewing), accélérant drastiquement le modèle de pointage automatique ZWO en évitant les pauses fixes.
* **Intégration complète dans les interfaces** : Le sélecteur de monture dans `goto_andrivet_config_tool.py`, `goto_andrivet.py` et la raquette physique Teensy supporte désormais les trois options distinctes (`AltAz`, `ForkEq`, `GermanEq`).

---

## Licence

Ce projet est sous licence **GNU GPL v3**. Consultez le fichier [LICENSE](LICENSE) pour plus de détails.

## Cartes Monture (PCB 36V / 12V)

Il existe deux cartes monture, au choix selon les drivers utilisés. Elles ont les mêmes dimensions (150 × 110 mm), les mêmes fixations, les mêmes connecteurs d'alimentation, de raquette, de GPS et de PC, et le même câblage du Teensy : le firmware est identique.

| Carte | Dossier | Drivers | Boîtier |
|---|---|---|---|
| **StepStick** | `pcb/monture/` | 4 modules au format StepStick sur la carte (A4988, DRV8825, TMC2208/2209, TMC5160 en SPI) | `boitier_monture.scad`, 45 mm de haut |
| **Drivers externes** | `pcb/monture_ext/` | 4 drivers externes (DM542, DM556, TB6600…), signaux 5 V et alimentation par axe | `boitier_monture_ext.scad`, 35 mm de haut |

Sans PCB, câblez vous-même le Mega ou le Teensy en suivant le plan de câblage de la section 4. Dans l'outil de configuration, indiquez votre choix sur la ligne **« Câblage monture »** (PCB StepStick, PCB drivers externes ou câblage manuel). Avec un PCB, l'outil impose le Teensy 4.1, et la section TMC5160 n'est active qu'avec la carte StepStick. Le bouton **« Plan de câblage »** affiche les broches de la carte choisie et les connecteurs du PCB.

### Commun aux deux cartes
- **Alimentation** : un seul bus moteur, alimenté soit par le **bornier 36V**, soit par la **prise jack 12V**. Chaque entrée passe par une des deux diodes Schottky de `D_IN` (MBR20100CT, cathode commune) : des fils inversés ou un jack à centre négatif ne passent pas, et le 36V du bornier ne remonte pas dans le bloc 12V. Vient ensuite le fusible `F_IN` (TR5 temporisé 4 A, sur support), commun aux deux entrées. Toute la carte et tous les drivers reçoivent la tension de l'entrée branchée, moins environ 0,5 V.
  - En 36V, n'utilisez pas d'A4988 (35 V max) ni de TMC2208/TMC2209 (29 V max) : pour ces petits drivers, alimentez la carte uniquement par le jack 12V.
- Le buck LM2596HV (jusqu'à 60 V en entrée) fabrique le 5V à partir de 12V comme de 36V.
- Des résistances de rappel (`RN_EN`) maintiennent EN à l'état haut tant que le Teensy n'a pas démarré : les drivers restent désactivés à la mise sous tension.
- Le Teensy 4.1 de la monture n'a pas de port USB Host câblé.
- Sur le Teensy de la monture, **coupez le pont VUSB-VIN** sous la carte : le Teensy est alimenté par le 5V du PCB (VIN) et reste branché en USB au PC.
- Port **PC SERIAL** (Serial6, broches 24/25) : les repères RX/TX sont donnés côté Teensy (`3 TX6`, `4 RX6`). Il faut donc les croiser vers l'adaptateur, et ne pas brancher son 5V sur la broche `2 +5V`. L'adaptateur USB-série doit travailler en **3,3 V** : un adaptateur 5 V enverrait 5 V sur `RX6`, que le Teensy ne supporte pas.
- Le buzzer est commandé par un transistor (`Q_BUZ`, PN2222A) et alimenté en 5V à travers 68 Ω, avec une diode 1N4148 à ses bornes : un buzzer actif 5V ou un buzzer passif conviennent.

### Carte StepStick (`pcb/monture/`)
- Chaque axe a un support au format **StepStick / Pololu** (2 × 8 broches espacées de 12,7 mm), piloté directement par le Teensy, et un bornier moteur à 4 points (bobine 1 : 1B/1A, bobine 2 : 2A/2B).
- Orientation d'un module StepStick : sa broche **EN** va sur la pastille marquée `EN` (en haut à gauche). **VMOT** se trouve donc en face, sur la pastille marquée `VM`. La logique des modules (VIO) est alimentée en **3,3 V**.
- **Ponts SPI (TMC5160)** : sous chaque support, entre les deux rangées, se trouvent 5 ponts à souder marqués `SPI`. Ils sont en face des broches 2 à 6 du module. De haut en bas : `SDI` vers MOSI1 (broche 26), `SCK` vers SCK1 (27), `CSN` vers le CS de l'axe (41 AZ, 40 ALT, 38 dérotateur, 37 focuseur), `SDO` vers MISO1 (39), et `CLK` vers GND (horloge interne du TMC5160).
  - **Ponts ouverts** (réglage par défaut) : le support accepte les modules STEP/DIR sans SPI, c'est-à-dire TMC2208/TMC2209 en mode autonome, A4988 ou DRV8825.
    - **A4988 et DRV8825 : reliez RESET à SLEEP sur le module** (petit fil ou goutte d'étain entre les deux broches voisines). Le PCB laisse ces broches en l'air : sans ce pont, l'A4988 a un RESET flottant, et le DRV8825, dont RESET a un rappel interne au niveau bas, ne bouge pas du tout.
    - **Micro-pas** : le PCB ne câble pas les broches MS1 à MS3. Elles restent au niveau bas, ce qui donne le pas entier sur un A4988 ou un DRV8825 et 1/8 de pas sur un TMC2208/TMC2209. Pour une autre valeur, reliez les broches MSx voulues à la broche VIO du support (3,3 V) par un fil soudé sur le module, d'après sa table de micro-pas. Le réglage *Microstepping* de l'outil de configuration doit toujours être égal aux micro-pas du module (1, 8, 16…).
  - **Les 5 ponts fermés** (une goutte d'étain chacun) : pour un **BTT TMC5160 Pro**, ou un autre TMC5160 au format StepStick avec le même brochage (EN, SDI, SCK, CSN, SDO, CLK, STEP, DIR).
  - Ne fermez jamais les ponts avec un A4988, un DRV8825 ou un TMC2209 : leurs broches MSx, RESET et SLEEP se retrouveraient sur le bus SPI.
- **Configuration des TMC5160 (firmware Teensy)** : au démarrage, puis chaque seconde, le firmware cherche un TMC5160 sur chaque axe et le configure (courant, micro-pas, stealthChop). Un TMC5160 en SPI garde son étage de puissance coupé tant qu'il n'est pas configuré. Si le 36V n'est pas encore là, le module ne répond pas : il est configuré dès que le 36V arrive, et reconfiguré après une coupure.
  - Micro-pas : AZ/ALT utilisent le réglage *Microstepping*, qui doit être une puissance de 2 (16, 32, 64, 128 ou 256). Une valeur comme 125 est refusée et l'axe reste coupé (état `M`). Le dérotateur et le focuseur sont à 16 micro-pas par défaut : ajustez les *Pas/Deg* du dérotateur en conséquence.
  - Courant : il se règle dans l'outil de configuration, de 100 à 3000 mA RMS par axe (Rsense 0,075 Ω du BTT TMC5160 Pro), avec un courant de maintien en %. Valeurs par défaut : 800 mA pour AZ/ALT, 400 mA pour le dérotateur et le focuseur, maintien à 50 %.
  - Commandes : `:XFS0#` / `:XFS1#` (désactiver / activer, activé par défaut), `:XTS#` (état par axe : `-` SPI désactivé, `0` absent, `1` configuré, `M` micro-pas refusé, `E` défaut driver), `:XTI<a|e|d|f>[mA]#` (courant), `:XTH[%]#` (maintien), `:XTP[0|1]#` (stealthChop), `:XTMd[n]#` / `:XTMf[n]#` (micro-pas dérotateur / focuseur), `:XTC#` (tout reconfigurer). Sans valeur, ces commandes renvoient le réglage en cours.
  - Le firmware Mega n'a pas de SPI : le PCB est prévu pour le Teensy.
  - Hauteur : un TMC5160 avec radiateur est plus haut qu'un StepStick ordinaire. Le boîtier fait donc 45 mm de haut (`box_h` dans `boitier_monture.scad`), ce qui laisse 25,8 mm entre la carte du module et le couvercle. Un BTT TMC5160 Pro (23,2 mm hors tout) passe avec au moins 4 mm de marge, et les grilles du couvercle se trouvent au-dessus des radiateurs.

### Carte drivers externes (`pcb/monture_ext/`)
- Chaque axe a deux borniers sur le bord haut :
  - **`J_VM`** (5,08 mm, fil de 1,5 mm²) : `VM` et `GND`, l'alimentation du driver. `VM` est le bus moteur, donc 36V ou 12V selon l'entrée branchée. Chaque sortie a son condensateur de 220 µF.
  - **`J_SIG`** (3,5 mm) : `EN`, `STEP`, `DIR`, `GND`, en 5 V. Les signaux du Teensy passent par trois 74ACT125, toujours actifs.
- Câblage d'un DM542 (cathode commune) : `STEP` → `PUL+`, `DIR` → `DIR+`, `EN` → `ENA+`, et `GND` → `PUL−`, `DIR−` et `ENA−` reliés ensemble. Le moteur se branche sur le driver. Avec `ENA` câblé, le driver relâche le moteur au parking ; sinon, le moteur reste alimenté en permanence.
- Un plan de cuivre GND (face dessous) et un plan +36V (face dessus, de l'entrée jusqu'aux borniers `J_VM`) portent le courant des drivers.
- Réglages : le *Microstepping* de l'outil de configuration doit être égal au nombre de pas par tour réglé sur le driver divisé par 200 (par exemple 128 pour 25 600 pas/tour). Toutes les valeurs sont acceptées, puissances de 2 ou non. AZ et ALT partagent ce réglage : réglez leurs deux drivers pareil.
- Vitesse de GoTo : le DM542 accepte 200 kHz au plus, avec des impulsions d'au moins 2,5 µs. Restez sous environ 150 kHz, soit une vitesse maximale d'environ 150 000 divisé par le nombre de pas par degré (environ 2,8°/s à 25 600 pas/tour avec une réduction de 750:1).
- Cette carte n'a pas de bus SPI : dans l'outil de configuration, l'état TMC5160 des axes est « absent », ce qui est normal. On peut décocher « Drivers TMC5160 ».
