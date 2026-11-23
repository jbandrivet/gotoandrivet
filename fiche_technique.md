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
*   **Protocole :** Meade LX200 avec extensions OnStep, réponses identiques à celles d'un vrai OnStep. Sous Linux : KStars/Ekos, PHD2 et tous les logiciels INDI (pilote *LX200 OnStep*). Sous Windows : NINA, PHD2 et tous les logiciels ASCOM (pilote *ASCOM OnStep*, réglé sur 38 400 bauds). Aussi Stellarium et SkySafari.

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
*   **Réfraction :** L'air remonte les astres (29′ à l'horizon, 5,4′ à 10° de hauteur, 1′ à 45°). Elle est corrigée au GoTo comme au suivi, sur les deux axes. Sur la Teensy, elle tient compte de la température et de la pression du lieu, données par `:SX9A,<°C>#` et `:SX9B,<hPa>#` (commandes OnStep) : la carte du ciel les envoie à chaque connexion (onglet *Précision* ; pression d'après l'altitude du lieu si on ne la donne pas), et Ekos peut le faire (onglet *Environment* du pilote). Sans elles : 1010 hPa et 10 °C. La Mega garde ces valeurs fixes. Active par défaut ; `:Tn#` la coupe, `:To#` ou `:Tr#` la remettent (dans Ekos : réglage *Compensation*). Le statut `:GU#` porte alors la lettre `t`, qu'Ekos affiche « Full Comp ». Elle s'efface tout près du pôle céleste (au-delà de 89,8° de déclinaison), où elle ferait tourner l'axe horaire pour rien.
*   **GoTo anticipé :** Le ciel tourne de 15″ par seconde. La carte vise donc l'endroit où sera l'objet à l'arrivée du GoTo : la durée du trajet est calculée d'après la rampe des moteurs, puis corrigée par ce qu'ont duré les GoTo précédents. À l'arrivée, l'écart est de l'ordre de 0,1′ (contre 3 à 10′ avant).

### Modèle de pointage (Teensy uniquement)

Chaque synchro (`:CM#`, par exemple après une photo résolue par astrométrie) enregistre un point, jusqu'à 50 ; au-delà, le plus ancien est oublié. La carte en déduit les défauts de la monture, par moindres carrés :

| Terme | Défaut | Pris à partir de |
| :--- | :--- | :--- |
| IH, ID | Décalage des deux codeurs (zéro des axes) | 1 étoile |
| P, Q | Inclinaison de l'axe principal : mise en station (équatoriale) ou calage du trépied (alt-az) | 2 étoiles |
| CH | Tube pas d'équerre avec l'axe de déclinaison (ou d'altitude) | 3 étoiles |
| NP | Les deux axes ne sont pas perpendiculaires | 3 étoiles |
| TF | Flexion du tube, qui pique vers l'horizon (toutes les montures) | 4 étoiles |
| FO | Flexion des bras de la fourche (fourche seulement) | 5 étoiles |
| A1S, A1C, A2S, A2C | Roues dentées décentrées (une erreur par tour d'axe ; en alt-az, l'axe 1 seulement) | 12 étoiles |

Ce qui reste à chaque étoile est ensuite interpolé, pour tomber juste sur les étoiles de synchro ; loin d'elles (au-delà d'une vingtaine de degrés), seuls les défauts calculés servent. La distance entre étoiles est la vraie distance sur le ciel (avant, elle était prise à plat en angles d'axes : près du zénith ou du pôle, deux étoiles voisines paraissaient très éloignées). En allemande, les deux côtés du pilier sont séparés : le cône et la non-perpendicularité y changent de signe.

Le banc d'essai `tests/banc_teensy/` simule une monture par sa vraie géométrie (pas par les formules du modèle), centre les étoiles à 0,5′ près et mesure l'erreur sur 300 cibles du ciel. Erreur médiane, en minutes d'arc :

| Monture simulée | 4 étoiles avant → après | 8 étoiles avant → après | 12 étoiles avant → après |
| :--- | :---: | :---: | :---: |
| Fourche, avec flexion | 8,8 → 5,5 | 3,6 → 1,6 | 2,7 → 1,1 |
| Allemande, avec flexion | 6,6 → 4,1 | 4,3 → 1,9 | 3,3 → 1,8 |
| Alt-az, roues décentrées | 2,8 → 2,7 | 1,8 → 1,8 | 1,4 → 0,9 |
| Allemande sans flexion | 3,5 → 3,5 | 1,7 → 2,0 | 1,7 → 1,9 |

Une monture sans aucune flexion perd un peu (0,1 à 0,3′) : la flexion calculée absorbe une partie du bruit de centrage. Un vrai tube a toujours de la flexion. Le détail complet : `banc_modele` (voir `tests/banc_teensy/LISEZMOI.md`).

**Synchro ratée.** À partir de 3 étoiles, une synchro qui tombe à plus de 1,5° de l'endroit où le modèle attend la monture (ou à plus de 5 fois son erreur habituelle) est refusée : `:CM#` répond `E9,<écart en °>#`. C'est presque toujours la mauvaise étoile qui est centrée. Ekos l'affiche comme « Unspecified Error ». Refaite au même endroit, elle est acceptée : la monture a vraiment bougé (choc, embrayage qui a glissé), l'ancien modèle est effacé et l'on repart de cette étoile. La carte du ciel le fait seule pour une position résolue par astrométrie, qui ne se trompe pas d'étoile. Une synchro pendant un GoTo est refusée (`E5#`, comme OnStep) : la monture est alors entre deux positions.

**Commandes.** `:CML#` efface le modèle. `:CMU#` retire la dernière étoile (`1#`, ou `0#` s'il n'y en a plus) : la monture ne bouge pas, sa position se relit sans ce point. `:GXMS#` donne le bilan : `n,termes,erreur,haut,est,cône,NP,TF,FO,dernière#`, angles en minutes d'arc ; `erreur` vaut −1 tant qu'il y a trop peu d'étoiles pour la mesurer. En équatoriale, `haut` > 0 = axe polaire trop haut, `est` > 0 = axe polaire trop à l'est (dans l'hémisphère du lieu). En alt-az, `haut` est l'inclinaison de l'axe vertical et `est` la direction vers laquelle il penche (degrés, 0 = nord, 90 = est). La carte du ciel l'affiche dans l'onglet *Précision*, la raquette dans *Réglages → Modèle Pointage*.

Le modèle est gardé en mémoire : après une extinction en position de parking, la monture pointe comme avant. Il est oublié si elle a été éteinte hors du parking (sa position n'est plus connue), si la mécanique change (type de monture, rapports, micro-pas, sens d'un axe), et si la première synchro après le démarrage tombe à plus de 15′ du modèle (monture remontée ou déplacée). La Mega garde la synchro à une étoile (elle recale les axes).

### PEC : erreur périodique de la vis (Teensy, équatoriales)

Une vis sans fin un peu voilée ou décentrée fait avancer la roue trop vite puis trop lentement, à chaque tour de vis : l'étoile oscille en AD de quelques secondes à quelques dizaines de secondes d'arc, toujours de la même façon. Le PEC l'enregistre une fois, puis la corrige d'avance.

* **Réglage** : nombre de dents de la roue AD dans le configurateur (onglet *Mécanique*, `:XPW<n>#`, 0 = pas de PEC). Un tour de vis dure 1436 / dents minutes (10 min pour 144 dents).
* **Enregistrer** : suivi sidéral, guidage en marche et stable (PHD2, Ekos ou la fenêtre *Guidage*), puis *Enregistrer* (onglet *Précision* de la carte du ciel, onglet *PEC* d'Ekos, ou *Réglages → PEC* de la raquette, touche Haut). Pendant un tour de vis, la carte note l'écart réel entre l'axe et la position qu'il aurait avec le seul suivi, case par case du tour de vis ; la dérive lente (mise en station) est retirée. Un GoTo ou l'arrêt du suivi abandonne l'enregistrement. À la fin, la courbe est rangée en mémoire et la lecture démarre.
* **Lire / Arrêter** : `:$QZ+#` / `:$QZ-#`. La courbe corrige la lecture de l'axe AD, et le suivi la suit d'avance : positions, synchros et GoTo voient le même angle corrigé.
* Commandes OnStep, comprises par le pilote INDI (onglet *PEC*) : `:$QZ/#` enregistrer, `:$QZZ#` effacer, `:$QZ!#` écrire en mémoire, `:$QZ?#` état ; l'état est aussi dans `:GU#` (`/` arrêté, `~` lecture, `^` enregistrement, `R` courbe enregistrée). `:GXPE#` donne `état,dents,avancement %,amplitude ″,courbe#`.
* Sans capteur de repère, la position dans le tour de vis vient du compteur de pas : elle reste juste si la monture est éteinte parquée (comme le modèle). Une synchro `:CS#`, qui recale le compteur, ne la perd pas. La courbe est effacée si la mécanique change.
* Banc d'essai (`banc_pec`) : vis simulée à 15″ + 5″, autoguideur simulé. Sans PEC et sans guidage, 11,2″ d'erreur efficace ; avec le PEC, sans guidage, 1,5″ (0,9″ après un redémarrage parqué et une synchro `:CS#`).

### Défauts corrigés en préparant ces fonctions (Teensy)

* **L'heure reculait d'une seconde, une seconde sur trois environ.** Le calcul de l'heure UTC en heures décimales tronquait parfois les secondes (2/3600 h × 3600 = 1,999… → 1). La cible du suivi sautait alors de 15″ en AD et la monture courait après. Le calcul se fait maintenant en secondes entières. Sur le banc, avec une vis parfaite, l'écart de suivi maximal sur 5 minutes est passé de 15″ à 0,5″.
* **Le guidage recalait la cible à 15″ près.** Après chaque impulsion de guidage, la cible du suivi était reprise de la position en secondes d'AD entières (15″) : elle sautait au hasard de ±7,5″, et l'autoguideur se battait contre ces sauts. Elle est reprise en pleine précision. Sur le banc, le guidage simulé tient maintenant à 0,3″ au lieu de 8 à 10″.
* Ces deux défauts existent aussi dans le firmware Mega, qui n'a pas été modifié.

En monture équatoriale, une synchro à plus de 85° de déclinaison est refusée, comme dans OnStepX : `:CM#` répond `E6#` (hors limites) et `:CS#` ne fait rien. Près du pôle, l'AD ne dit pas où est l'axe AD. Une synchro sur DEC 90° et AD = heure sidérale, que proposent par défaut certains logiciels, faisait tourner l'axe AD de 6 h dans la mémoire de la monture, et tous les GoTo tombaient à 90° de la cible. Il n'y a pas besoin de synchroniser au départ : la monture démarre sur sa position de parking (en allemande, contrepoids en bas, AD = heure sidérale − 6 h). Pour affiner, synchroniser sur une étoile plus basse.

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
