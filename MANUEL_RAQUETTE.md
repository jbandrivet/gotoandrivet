# Mode d'emploi : Raquette Teensy

Ce document décrit comment naviguer dans l'interface LCD de la raquette Teensy et détaille l'ensemble des menus disponibles.

## Navigation Générale

L'écran d'accueil affiche les coordonnées de la monture (soit en RA/DEC, soit en ALT/AZ). 

Depuis cet écran d'accueil :
- **Touches directionnelles (Haut, Bas, Gauche, Droite)** : Déplacement manuel des moteurs (vitesse de rattrapage).
- **Touche `ENTRÉE` (ou bouton central)** : Ouvre le Menu Principal.

À l'intérieur des menus :
- **Haut / Bas** : Déplacer le curseur de sélection ou modifier une valeur (par exemple changer un chiffre).
- **Entrée (ou Droite)** : Valider un choix ou entrer dans un sous-menu.
- **Gauche** : Annuler, reculer ou retourner au menu précédent.

## Le Menu Principal

En appuyant sur `Entrée` depuis l'écran d'accueil, vous accédez aux options suivantes :

### 1. Catalogues
Permet d'accéder aux catalogues d'objets célestes (Messier, NGC, IC, Système Solaire, Étoiles remarquables). Sélectionnez un catalogue, puis un objet, et faites Entrée pour lancer le **GoTo** automatique vers cet objet.

### 2. Pause Moteurs / Reprendre Suivi
- **Pause Moteurs** : Coupe le suivi et l'alimentation des moteurs (pratique pour économiser la batterie ou manipuler la monture sans forcer). Le télescope retient sa position interne en fonction du temps qui passe.
- **Reprendre Suivi** : Réactive le suivi. Si vous aviez une cible GoTo active, le télescope va recalculer la position actuelle de la cible et s'y recentrer automatiquement.

### 3. Vitesse GoTo
Permet de brider la vitesse maximale des moteurs lors des grands déplacements (GoTo). Utile si votre alimentation est faible ou pour réduire le bruit (en degrés par seconde).

### 4. Buzzer
Active ou désactive les bips de confirmation de la raquette.

### 5. Synchroniser
Procédure d'alignement. Après avoir lancé un GoTo vers une étoile ou une planète, centrez-la parfaitement à l'aide des touches fléchées puis utilisez cette fonction. L'Arduino va alors se "synchroniser" et considérer que sa position mécanique actuelle correspond exactement à cet objet.

L'écran confirme la synchro avec le nombre d'étoiles du modèle et l'erreur restante (monture Teensy). Si la monture la refuse, il dit pourquoi : *GOTO EN COURS*, *TROP PRES DU POLE*, *HEURE NON REGLEE*, ou *REFUSEE : a 3.1 deg*. Ce dernier cas veut dire que la monture pointe loin de l'endroit où le modèle l'attend : ce n'est sans doute pas la bonne étoile qui est centrée. Si c'est bien la bonne (la monture a été bougée), refaites la synchro : elle est acceptée et le modèle repart de zéro.

### 6. Parking
Gère la mise au repos de la monture.
- **Parquer** : Envoie le télescope vers sa position de repos sécurisée et coupe le suivi.
- **Déparquer** : Réveille la monture pour une nouvelle session (sans perdre l'alignement).
- **Définir Position** : Enregistre la position *actuelle* comme étant la future position de parking.

### 7. Type Monture
Définit la géométrie de votre monture :
- Alt-Az (Azimutale)
- Equatorial (Fourche ou Allemande)

### 8. Ratio AZ / Ratio RA
Règle la démultiplication mécanique (ratio des poulies/engrenages) de l'axe Azimut (ou Ascension Droite).

### 9. Ratio ALT / Ratio DEC
Règle la démultiplication mécanique de l'axe Altitude (ou Déclinaison).

### 10. Alim Moteurs
Permet d'allumer ou d'éteindre complètement l'étage de puissance des moteurs manuellement.

### 11. Date / Heure
Règle la date et l'heure locale, ainsi que le décalage UTC. *(L'heure est essentielle pour le calcul des positions célestes).*

### 12. Lieu Obs.
Saisie des coordonnées GPS de votre lieu d'observation (Latitude et Longitude).

### 13. Langue
Bascule l'interface de la raquette entre le **Français** et l'**Anglais**.

### 14. GPS Auto
Active ou désactive la synchronisation automatique de l'heure et du lieu grâce au module GPS matériel (si branché).

### 15. Affichage Coord
Permet de choisir ce que l'écran d'accueil affiche en temps réel :
- Coordonnées équatoriales (Ascension Droite et Déclinaison).
- Coordonnées horizontales (Altitude et Azimut).

### 16. Modèle Pointage (monture Teensy)
Bilan du modèle de pointage, relu toutes les 2 secondes :
- nombre d'étoiles et erreur restante (en minutes d'arc) ;
- en équatoriale, l'erreur de mise en station : *Pole haut 12' O 5'* veut dire axe polaire trop haut de 12′ et trop à l'ouest de 5′ ; en alt-az, le calage : *Calage 8' vers NE* veut dire que l'axe vertical penche de 8′ vers le nord-est.
- **Entrée** retire la dernière étoile synchronisée (par exemple après avoir centré la mauvaise). La monture ne bouge pas.

### 17. PEC (monture Teensy, équatoriales)
Correction de l'erreur périodique de la vis sans fin. L'écran donne l'état (lecture, arrêtée, enregistrement en %, pas de courbe), l'amplitude corrigée et le nombre de dents de la roue AD (à régler dans le configurateur).
- **Haut** lance l'enregistrement : le guidage doit tourner et être stable, en suivi sidéral. Il dure un tour de vis (10 min pour une roue de 144 dents), sans GoTo.
- **Entrée** lance ou arrête la lecture de la courbe.
