#!/bin/sh
# Met à jour le site de GotoAndrivet depuis GitHub. Lancé par la crontab de l'utilisateur du serveur :
#   */15 * * * * $HOME/goto_mega/site/maj_site.sh >> $HOME/maj_site.log 2>&1
# Récupère le dépôt (git pull), copie les fichiers d'installation publiés s'ils ont changé, et régénère
# les pages si quelque chose a bougé. N'écrit rien dans le journal quand rien n'a changé.
set -e
DEPOT=${DEPOT:-$HOME/goto_mega}
SORTIE=${SORTIE:-/var/www/gotoandrivet}
[ -d "$DEPOT/.git" ] || git clone -q https://github.com/jbandrivet/gotoandrivet.git "$DEPOT"
git -C "$DEPOT" pull -q --ff-only
exec python3 "$DEPOT/site/generer_site.py" --depot "$DEPOT" --sortie "$SORTIE" --miroir
