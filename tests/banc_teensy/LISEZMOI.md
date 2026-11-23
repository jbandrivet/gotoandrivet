# Banc d'essai PC du firmware Teensy (`teensy_monture`)

Le firmware est compilé tel quel sur le PC, avec une horloge simulée, une ISR
déclenchée par cette horloge, des ports série et une EEPROM en mémoire
(`arduino_shim.h`, `stubs/`). Une monture virtuelle compte les vraies
impulsions STEP/DIR des moteurs.

    sh lancer.sh          # tous les tests
    sh lancer.sh modele   # tableau du modèle de pointage seul (ESSAIS=16 pour plus de tirages)

| Test | Ce qu'il vérifie |
| :--- | :--- |
| `banc_synchro` | refus d'une synchro sur la mauvaise étoile puis confirmation, `:CMU#`, tableau plein (50 points), sens des valeurs de mise en station (`:GXMS#`) dans les deux hémisphères et pour les trois montures |
| `banc_guidage` | impulsions `:Mg` de 0,5 à 5 s dans les 4 directions : déplacement = vitesse de guidage × durée, qui reste après l'impulsion (le servo du suivi ne doit pas le défaire), autre axe immobile. Argument : 1 = fourche, 2 = allemande |
| `banc_pec` | vis à erreur périodique (15″ + 5″), autoguideur simulé (impulsions `:Mg`) : enregistrement, lecture sans guidage, arrêt, redémarrage parqué, synchro `:CS#`, effacement. Argument : 1 = fourche, 2 = allemande |
| `banc_modele` | monture simulée par sa vraie géométrie (décalages, mise en station, cône, axes, flexion, roues décentrées), étoiles centrées à 0,5′ près, erreur mesurée sur 300 cibles. Comparer deux firmwares : `FIRMWARE=ancien.ino sh lancer.sh modele` |
| `banc_pty <lien> [type]` | firmware branché sur un pseudo-terminal, en temps réel, pour un vrai logiciel (pilote INDI `indi_lx200_OnStep`, carte du ciel). `BANC_DENTS=144` règle la roue au démarrage. Journal des synchros, PEC et météo sur la sortie d'erreur |

Pour INDI, lancer `indiserver` avec un HOME à part, et régler le port du pilote
sur le lien **avant** de connecter : sinon il prend le vrai Teensy s'il est branché.

Sur le PC, `long` fait 8 octets (4 sur le Teensy) : les valeurs écrites en EEPROM
avec la taille de `long` n'ont pas la même place que sur la carte. Le code
nouveau écrit des `int32_t`.
