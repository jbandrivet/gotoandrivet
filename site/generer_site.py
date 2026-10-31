#!/usr/bin/env python3
"""Génère le site de GotoAndrivet à partir du dépôt : pages HTML statiques sur fond étoilé (titre arc-en-ciel,
texte qui défile, boutons en relief, compteur de visiteurs).

    python3 site/generer_site.py --depot . --sortie /var/www/gotoandrivet [--miroir] [--force]

Les pages reprennent les documents du dépôt (README, manuel de la raquette, fiche technique, guide pour
contribuer), les cartes électroniques et leurs boîtiers (dossier pcb/), et l'historique git du logiciel (les modifications du seul dossier site/ n'y figurent pas). Avec --miroir, les fichiers d'installation publiés sur GitHub sont copiés
dans <sortie>/telechargements, pour que le site reste utilisable même si GitHub ne répond pas ; ils ne sont
retéléchargés que s'ils ont changé. Le compteur de visiteurs lit les journaux de nginx s'ils sont lisibles
(groupe adm). Sans --force, rien n'est réécrit si ni le dépôt ni le compteur n'ont bougé.
Dépendance : python3-markdown.
"""
import argparse
import csv
import gzip
import html
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

import markdown

REPO = "jbandrivet/gotoandrivet"
SITE = "https://goto-andrivet.duckdns.org"          # adresse publique : liens canoniques, plan du site
CONTACT = ("jeanbaptisteandrivet", "gmail.com")    # adresse de contact, en deux morceaux contre les robots
GITHUB = f"https://github.com/{REPO}"
RELEASE = f"{GITHUB}/releases/latest/download"
FIRMWARES = f"{GITHUB}/releases/download/firmwares"
CARTES = (("mega_monture", "Monture, Arduino Mega 2560"), ("teensy_monture", "Monture, Teensy 4.1"),
          ("teensy_raquette", "Raquette, Teensy 4.1"))
# Fichiers copiés sur le site depuis les publications GitHub : nom -> adresse
FICHIERS = {"GotoAndrivet.deb": f"{RELEASE}/GotoAndrivet.deb",
            "Install_Goto_Universal": f"{RELEASE}/Install_Goto_Universal"}
for _carte, _ in CARTES:
    FICHIERS[f"{_carte}.hex"] = f"{FIRMWARES}/{_carte}.hex"
    FICHIERS[f"{_carte}-source.zip"] = f"{FIRMWARES}/{_carte}-source.zip"
COMMANDE = "wget -qO- https://raw.githubusercontent.com/jbandrivet/gotoandrivet/main/installer.sh | sh"
ICI = Path(__file__).resolve().parent

# Documents publiés : fichier du dépôt -> (page, titre du menu)
DOCS = {
    "README.md": ("documentation.html", "Documentation"),
    "MANUEL_RAQUETTE.md": ("raquette.html", "Raquette"),
    "fiche_technique.md": ("fiche-technique.html", "Fiche technique"),
    "CONTRIBUTING.md": ("contribuer.html", "Contribuer"),
    "pcb/LISTE_ACHATS.md": ("liste-achats.html", "Liste d'achat"),
}
MENU = (("index.html", "Accueil"), ("telecharger.html", "Télécharger"), ("documentation.html", "Documentation"),
        ("raquette.html", "Raquette"), ("fiche-technique.html", "Fiche technique"),
        ("materiel.html", "Cartes et boîtiers"), ("liste-achats.html", "Liste d'achat"),
        ("nouveautes.html", "Nouveautés"), ("contribuer.html", "Contribuer"))

LIENS = (("OnStep", "https://onstep.groups.io/g/main/wiki"), ("KStars et Ekos", "https://kstars.kde.org/fr/"),
         ("Stellarium", "https://stellarium.org/fr/"), ("Astrometry.net", "https://astrometry.net/"),
         ("PHD2 Guiding", "https://openphdguiding.org/"), ("INDI", "https://indilib.org/"))
BADGES = (("LINUX", "inside", "#000", "#ffcc00"), ("PYTHON", "powered", "#306998", "#ffd43b"),
          ("GPL v3", "libre !", "#a00", "#fff"), ("ARDUINO", "&amp; Teensy", "#00979d", "#fff"))
JOURNAUX = Path("/var/log/nginx")

# Description de chaque page pour les moteurs de recherche (balise description et aperçus de partage)
DESCRIPTIONS = {
    "index.html": "GotoAndrivet, contrôleur GoTo libre et gratuit pour télescopes : carte du ciel, GoTo, caméra ZWO, "
                  "astrométrie, guidage, dérotateur et focuseur, montures AltAz et équatoriales, Arduino Mega ou Teensy.",
    "telecharger.html": "Télécharger GotoAndrivet pour Linux : paquet .deb pour Ubuntu et Debian, installateur pour les "
                        "autres distributions ou installation en une commande.",
    "documentation.html": "Documentation de GotoAndrivet : installation, structure du projet, câblage de la monture, "
                          "cartes Mega et Teensy, flashage et matériel compatible.",
    "raquette.html": "Mode d'emploi de la raquette Teensy de GotoAndrivet : menus, catalogues, GoTo, parking et suivi "
                     "sans ordinateur.",
    "fiche-technique.html": "Fiche technique de GotoAndrivet : architecture Mega ou Teensy, communication LX200/OnStep, "
                            "schéma de câblage, drivers et paramètres mécaniques.",
    "materiel.html": "Cartes électroniques et boîtiers de GotoAndrivet : fichiers Gerber prêts pour le fabricant, "
                     "projets KiCad, liste des composants et boîtiers à imprimer en 3D (STL et OpenSCAD).",
    "nouveautes.html": "Les dernières nouveautés de GotoAndrivet, contrôleur GoTo libre pour télescopes.",
    "contribuer.html": "Contribuer à GotoAndrivet : signaler un problème, proposer une modification, règles du projet "
                       "et licence GPL v3.",
}

FONCTIONS = (
    ("✦", "Carte du ciel et GoTo", "Étoiles, constellations, planètes, Messier, NGC, IC et Caldwell, précessés à la date. "
     "Un clic sur un objet, et la monture y va."),
    ("◉", "Caméra et astrométrie", "Caméra ZWO, photos FITS, résolution locale du champ : la monture se recale toute seule "
     "après chaque GoTo et construit son modèle de pointage."),
    ("◎", "Guidage", "Deuxième caméra, calibration automatique, corrections envoyées par le PC à la monture, "
     "courbe des erreurs et dithering entre les poses."),
    ("↻", "Dérotateur et focuseur", "Compensation de la rotation de champ en AltAz, angle de cadrage en équatoriale, "
     "focuseur intégré ou ZWO EAF."),
    ("▣", "Deux firmwares", "Arduino Mega 2560 ou Teensy 4.1, protocole LX200/OnStep compatible avec KStars, Ekos et INDI."),
    ("☰", "Raquette physique", "Teensy 4.1 et écran 20 × 4 : catalogues, GoTo, parking, suivi, sans ordinateur."),
    ("⚙", "Configurateur", "Rapports d'engrenage, micro-pas, vitesses, type de monture, et flashage des cartes "
     "sans l'IDE Arduino."),
    ("⌁", "Cartes électroniques", "Deux circuits KiCad : modules StepStick ou drivers externes, TMC5160 en SPI, "
     "alimentation 36 V."),
)


# ── Dépôt ─────────────────────────────────────────────────────
def git(depot, *args):
    r = subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def historique(depot, n=40):
    """[(sha, date jj/mm/aaaa, titre, corps)] des n derniers commits du logiciel : ceux qui ne touchent que
    le dossier site/ concernent le site lui-même, pas les utilisateurs, et ne sont pas listés."""
    out = git(depot, "log", f"-n{n}", "--format=%H%x1f%ad%x1f%s%x1f%b%x1e", "--date=format:%d/%m/%Y",
              "--", ".", ":(exclude)site")
    commits = []
    for bloc in out.split("\x1e"):
        champs = bloc.strip("\n").split("\x1f")
        if len(champs) == 4:
            corps = re.sub(r"\n*Co-Authored-By:.*", "", champs[3], flags=re.S).strip()
            commits.append((champs[0], champs[1], champs[2], corps))
    return commits


# ── Miroir des fichiers d'installation ────────────────────────
def miroir(sortie):
    """Copie locale des fichiers publiés sur GitHub, retéléchargés seulement s'ils ont changé
    (taille et date annoncées par le serveur). Renvoie les fichiers mis à jour."""
    dossier = sortie / "telechargements"
    dossier.mkdir(parents=True, exist_ok=True)
    etat_path = dossier / ".etat.json"
    try:
        etat = json.loads(etat_path.read_text())
    except (OSError, ValueError):
        etat = {}
    changes = []
    for nom, url in FICHIERS.items():
        req = urllib.request.Request(url, headers={"User-Agent": "GotoAndrivet-Site/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                signe = [r.headers.get("Content-Length"), r.headers.get("Last-Modified")]
                if signe == etat.get(nom) and (dossier / nom).exists():
                    continue                       # inchangé : on ferme sans lire le contenu
                tmp = dossier / f".{nom}.part"
                with open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
            os.replace(tmp, dossier / nom)
            etat[nom] = signe
            changes.append(nom)
        except Exception as e:
            print(f"miroir : {nom} non mis à jour ({e})", file=sys.stderr)
    etat_path.write_text(json.dumps(etat))
    return changes


# ── Fond étoilé et compteur de visiteurs ─────────────────────
def fond_etoiles(chemin, cote=200, graine=1996):
    """Motif de ciel étoilé à répéter en mosaïque. PNG écrit à la main (zlib) : aucune image à maintenir
    dans le dépôt."""
    rnd = random.Random(graine)
    px = [[(0, 0, 0)] * cote for _ in range(cote)]
    def met(x, y, c):
        px[y % cote][x % cote] = c
    for _ in range(90):                                        # petites étoiles, plus ou moins brillantes
        g = rnd.choice((70, 110, 150, 200, 255))
        met(rnd.randrange(cote), rnd.randrange(cote), (g, g, min(255, g + 30)))
    for _ in range(9):                                         # étoiles brillantes en croix
        x, y = rnd.randrange(cote), rnd.randrange(cote)
        c = rnd.choice(((255, 255, 255), (255, 255, 150), (170, 210, 255), (255, 190, 255)))
        met(x, y, c)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            met(x + dx, y + dy, tuple(v * 3 // 5 for v in c))
        for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
            met(x + dx, y + dy, tuple(v // 4 for v in c))
    brut = b"".join(b"\x00" + bytes(v for p in ligne for v in p) for ligne in px)
    def bloc(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    chemin.write_bytes(b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", cote, cote, 8, 2, 0, 0, 0))
                       + bloc(b"IDAT", zlib.compress(brut, 9)) + bloc(b"IEND", b""))


LIGNE_LOG = re.compile(r'^(\S+) \S+ \S+ \[(\d{2}/\w{3}/\d{4}):[^\]]*\] "GET (?:/|/index\.html)(?:\?\S*)? HTTP/[\d.]+" 200 .*"([^"]*)"$')
ROBOTS = re.compile(r"bot|crawl|spider|slurp|curl|wget|python|headless|monitor", re.I)


def compteur(sortie, journaux=None):
    """Visiteurs de l'accueil : adresses distinctes par jour (robots et scripts exclus), d'après les journaux
    de nginx. Les jours déjà comptés sont gardés après la rotation des journaux : le total ne redescend jamais.
    None si les journaux ne sont pas lisibles."""
    journaux = journaux or JOURNAUX
    vus, lisible = {}, False
    for f in sorted(journaux.glob("access.log*")) if journaux.is_dir() else []:
        try:
            with (gzip.open if f.suffix == ".gz" else open)(f, "rt", errors="replace") as fh:
                lisible = True
                for ligne in fh:
                    m = LIGNE_LOG.match(ligne.rstrip("\n"))
                    if m and not ROBOTS.search(m.group(3)):
                        vus.setdefault(m.group(2), set()).add(m.group(1))
        except OSError:
            continue
    if not lisible:
        return None
    chemin = sortie / ".compteur.json"
    try:
        jours = json.loads(chemin.read_text())
    except (OSError, ValueError):
        jours = {}
    for jour, adresses in vus.items():
        jours[jour] = max(jours.get(jour, 0), len(adresses))
    chemin.write_text(json.dumps(jours))
    return sum(jours.values())


# ── Mise en page ──────────────────────────────────────────────
def courriel():
    """(lien mailto, adresse affichée) en entités HTML : le navigateur les montre et les suit normalement,
    les robots qui ramassent les adresses dans le texte des pages ne les reconnaissent pas."""
    adresse = "@".join(CONTACT)
    code = lambda t: "".join(f"&#{ord(c)};" for c in t)
    return code("mailto:" + adresse), code(adresse)


def url_page(href):
    return f"{SITE}/" if href == "index.html" else f"{SITE}/{href}"


def donnees_structurees():
    """Fiche « logiciel » lisible par les moteurs de recherche (schema.org, JSON-LD)."""
    return json.dumps({
        "@context": "https://schema.org", "@type": "SoftwareApplication", "name": "GotoAndrivet",
        "description": DESCRIPTIONS["index.html"], "url": f"{SITE}/", "inLanguage": "fr",
        "applicationCategory": "UtilitiesApplication", "operatingSystem": "Linux",
        "downloadUrl": f"{SITE}/telecharger.html", "softwareHelp": f"{SITE}/documentation.html",
        "license": "https://www.gnu.org/licenses/gpl-3.0.html", "sameAs": GITHUB,
        "author": {"@type": "Person", "name": "Jean-Baptiste Andrivet"},
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
    }, ensure_ascii=False)


def page(titre, actif, contenu, version):
    sha, date, dernier, visiteurs = version
    titre_complet = "GotoAndrivet : contrôleur GoTo libre pour télescopes" if actif == "index.html" \
        else f"{titre} · GotoAndrivet"
    description = DESCRIPTIONS.get(actif, DESCRIPTIONS["index.html"])
    if actif:
        tete = (f'<link rel="canonical" href="{url_page(actif)}">\n'
                f'<meta property="og:type" content="website">\n'
                f'<meta property="og:site_name" content="GotoAndrivet">\n'
                f'<meta property="og:title" content="{html.escape(titre_complet)}">\n'
                f'<meta property="og:description" content="{html.escape(description)}">\n'
                f'<meta property="og:url" content="{url_page(actif)}">\n'
                f'<meta property="og:locale" content="fr_FR">')
        if actif == "index.html":
            tete += f'\n<script type="application/ld+json">{donnees_structurees()}</script>'
    else:
        tete = '<meta name="robots" content="noindex">'          # page d'erreur
    nav = "\n".join(f'<a class="bouton95{" actif" if href == actif else ""}" href="{href}">► {html.escape(nom)}</a>'
                    for href, nom in MENU)
    liens = "\n".join(f'<li><a href="{u}">{html.escape(n)}</a></li>' for n, u in LIENS)
    badges = "\n".join(f'<span class="badge"><b style="background:{fond};color:{texte}">{a}</b><i>{b}</i></span>'
                        for a, b, fond, texte in BADGES)
    mailto, adresse = courriel()
    compte = ""
    if visiteurs is not None:
        chiffres = "".join(f"<span>{c}</span>" for c in f"{visiteurs:06d}")
        compte = f'<div class="compteur"><p>Vous êtes le visiteur n°</p><p class="chiffres">{chiffres}</p></div>'
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre_complet)}</title>
<meta name="description" content="{html.escape(description)}">
{tete}
<link rel="icon" href="statique/icone.svg" type="image/svg+xml">
<link rel="stylesheet" href="statique/style.css">
</head>
<body>
<div class="page">
<header class="entete">
  <p class="scintille" aria-hidden="true"><span>★</span> <span>☆</span> <span>★</span> <span>☆</span> <span>★</span></p>
  <p class="titre"><a href="index.html">GotoAndrivet</a></p>
  <p class="sous-titre">~&nbsp;Le contrôleur GoTo libre pour télescopes&nbsp;~</p>
  <marquee class="defile" scrollamount="5">★ Bienvenue sur le site de GotoAndrivet ! ★ Dernière nouveauté, le {date} : {html.escape(dernier)} ★ Logiciel libre et gratuit, sous licence GPL v3 ★ Bon ciel à toutes et à tous ! ★</marquee>
</header>
<div class="mise-en-page">
<aside class="menu">
  <nav>
{nav}
<a class="bouton95" href="{GITHUB}">► GitHub</a>
  </nav>
  {compte}
  <div class="cadre contact">
    <p class="titre-cadre">Contact</p>
    <p>✉ <a href="{mailto}">Écrivez-moi !</a><br><span class="adresse">{adresse}</span></p>
  </div>
  <div class="cadre">
    <p class="titre-cadre">Mes liens astro</p>
    <ul>
{liens}
    </ul>
  </div>
  <div class="badges">
{badges}
  </div>
</aside>
<main class="contenu">
{contenu}
</main>
</div>
<hr class="arc-en-ciel">
<footer>
  <p>GotoAndrivet est un logiciel libre sous licence <a href="{GITHUB}/blob/main/LICENSE">GNU GPL v3</a>
  · code source sur <a href="{GITHUB}">GitHub</a></p>
  <p>Contact : <a href="{mailto}">{adresse}</a></p>
  <p class="petit">Site mis à jour automatiquement depuis GitHub · version <a href="{GITHUB}/commit/{sha}">{sha[:7]}</a> du {date}</p>
</footer>
</div>
<script src="statique/etoiles.js"></script>
</body>
</html>
"""


def lien_local(m):
    """Liens relatifs des documents : vers la page du site si elle existe, sinon vers GitHub."""
    texte, cible = m.group(1), m.group(2)
    if re.match(r"^[a-z]+:|^#", cible):
        return m.group(0)
    chemin, _, ancre = cible.partition("#")
    if chemin in DOCS:
        return f"[{texte}]({DOCS[chemin][0]}{'#' + ancre if ancre else ''})"
    return f"[{texte}]({GITHUB}/blob/main/{chemin}{'#' + ancre if ancre else ''})"


CITATION = re.compile(r"^((?:>\s?)*)")
PUCE = re.compile(r"^\s*(\d+\.|[-*+])\s")
ALERTES = {"NOTE": "Note", "TIP": "Conseil", "IMPORTANT": "Important", "WARNING": "Attention", "CAUTION": "Prudence"}


def listes_comme_github(texte):
    """GitHub accepte une liste collée à la ligne qui la précède, y compris dans une citation ;
    python-markdown veut une ligne vide avant."""
    lignes, dans_code = [], False
    for ligne in texte.split("\n"):
        q = CITATION.match(ligne).group(1)
        corps = ligne[len(q):]
        if corps.lstrip().startswith("```"):
            dans_code = not dans_code
        prec = lignes[-1] if lignes else ""
        pq = CITATION.match(prec).group(1)
        pcorps = prec[len(pq):]
        if (not dans_code and PUCE.match(corps) and pcorps.strip() and q.strip() == pq.strip()
                and not PUCE.match(pcorps) and not pcorps.startswith((" ", "\t"))):
            lignes.append(q.rstrip())
        lignes.append(ligne)
    return "\n".join(lignes)


def alertes_github(texte):
    """Encadrés de GitHub (« > [!NOTE] », « > [!IMPORTANT] »…) changés en blocs du site. Sans cela,
    python-markdown affiche la balise telle quelle et fusionne deux encadrés qui se suivent."""
    lignes, out, i = texte.split("\n"), [], 0
    while i < len(lignes):
        m = re.match(r"^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", lignes[i])
        if not m:
            out.append(lignes[i]); i += 1
            continue
        bloc, i = [], i + 1
        while i < len(lignes) and lignes[i].startswith(">"):
            bloc.append(re.sub(r"^> ?", "", lignes[i])); i += 1
        genre = m.group(1)
        out += ["", f'<div class="alerte {genre.lower()}" markdown="1">', "",
                f'<p class="titre-alerte">{ALERTES[genre]}</p>', ""] + bloc + ["", "</div>", ""]
    return "\n".join(out)


# Formules LaTeX des documents (GitHub les affiche, python-markdown non) : quelques commandes en texte.
SYMBOLES_LATEX = {"rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔", "times": "×", "cdot": "·",
                  "approx": "≈", "le": "≤", "ge": "≥", "pm": "±", "degree": "°"}

def latex_en_html(f):
    f = re.sub(r"\\text\{([^{}]*)\}", r"\1", f)
    f = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}",
               r'<span class="fraction"><span>\1</span><span>\2</span></span>', f)
    f = re.sub(r"\\([a-zA-Z]+)", lambda m: SYMBOLES_LATEX.get(m.group(1), m.group(0)), f)
    return f.strip()

def formules(texte):
    """$$...$$ (bloc centré) et $...$ contenant une commande \\..., hors blocs et extraits de code."""
    morceaux = re.split(r"(```.*?```|`[^`\n]*`)", texte, flags=re.S)
    for i in range(0, len(morceaux), 2):
        m = re.sub(r"\$\$(.+?)\$\$", lambda x: f'\n<div class="formule">{latex_en_html(x.group(1))}</div>\n',
                   morceaux[i], flags=re.S)
        morceaux[i] = re.sub(r"\$([^$\n]*\\[a-zA-Z]+[^$\n]*)\$", lambda x: latex_en_html(x.group(1)), m)
    return "".join(morceaux)


def rendre_md(texte):
    texte = formules(listes_comme_github(alertes_github(texte)))
    texte = re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", lien_local, texte)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists", "md_in_html"],
                           extension_configs={"toc": {"permalink": False}})
    corps = md.convert(texte)
    corps = corps.replace("<table>", '<div class="tableau"><table>').replace("</table>", "</table></div>")
    return corps, md.toc


def page_doc(depot, fichier, version):
    href, nom = DOCS[fichier]
    corps, toc = rendre_md((depot / fichier).read_text(encoding="utf-8"))
    sommaire = f'<details class="sommaire panneau"><summary>Sommaire</summary>{toc}</details>' if toc.count("<li>") > 3 else ""
    contenu = f"""<article class="document panneau">
{sommaire}
{corps}
<p class="source">Source : <a href="{GITHUB}/blob/main/{fichier}">{fichier}</a> sur GitHub</p>
</article>"""
    return href, page(nom, href, contenu, version)


def taille(p):
    n = p.stat().st_size
    return f"{n / 1e6:.1f} Mo" if n >= 1e6 else f"{max(1, round(n / 1e3))} ko"


def page_telecharger(sortie, version):
    local = sortie / "telechargements"
    def lien(nom, texte):
        f = local / nom
        if f.exists():
            return f'<a href="telechargements/{nom}" download>{texte}</a> <span class="petit">({taille(f)})</span>'
        return f'<a href="{FICHIERS[nom]}">{texte}</a>'
    lignes_firmwares = "\n".join(
        f"<tr><td>{html.escape(carte)}</td><td>{lien(f'{nom}.hex', f'{nom}.hex')}</td>"
        f"<td>{lien(f'{nom}-source.zip', 'sources .zip')}</td></tr>" for nom, carte in CARTES)
    def bouton(nom, texte):
        f = local / nom
        if f.exists():
            date = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y")
            return (f'<a class="bouton" href="telechargements/{nom}" download>► {texte}</a>'
                    f'<p class="petit">{taille(f)}, publié le {date} · '
                    f'<a href="{FICHIERS[nom]}">ou depuis GitHub</a></p>')
        return f'<a class="bouton" href="{FICHIERS[nom]}">► {texte}</a><p class="petit">depuis GitHub</p>'
    contenu = f"""<section class="panneau">
<h1>Télécharger</h1>
<p>La carte du ciel avec le GoTo, la caméra et le guidage, et le configurateur de la monture s'installent
ensemble, dans votre dossier personnel, sans toucher au système. Ensuite, le bouton « Mise à jour » des
applications suffit.</p>
</section>
<section class="panneau choix">
<h2><span class="pastille">1</span> Ubuntu et Debian : le paquet .deb</h2>
<p>Le plus simple.</p>
{bouton("GotoAndrivet.deb", "GotoAndrivet.deb")}
<ol>
<li>Double-cliquez sur le fichier téléchargé : le Centre d'applications s'ouvre. Cliquez sur
<strong>Installer</strong> (votre mot de passe est demandé).</li>
<li>Ouvrez <strong>GotoAndrivet - Carte du ciel</strong> depuis le menu des applications. La première fois,
GotoAndrivet s'installe dans votre dossier personnel (quelques minutes), puis s'ouvre.</li>
</ol>
</section>
<section class="panneau choix">
<h2><span class="pastille">2</span> Autres distributions : l'installateur</h2>
{bouton("Install_Goto_Universal", "Install_Goto_Universal")}
<ol>
<li>Clic droit sur le fichier → <strong>Propriétés</strong> → activez <strong>Exécutable comme programme</strong>.</li>
<li>Clic droit → <strong>Exécuter comme un programme</strong>, puis « Installer ».</li>
</ol>
<p class="petit">Le double-clic ne lance pas un programme téléchargé : passez par le clic droit.</p>
</section>
<section class="panneau choix">
<h2><span class="pastille">3</span> En une commande</h2>
<p>Dans un terminal :</p>
<pre><code>{html.escape(COMMANDE)}</code></pre>
</section>
<section class="panneau">
<h2>Firmwares des cartes</h2>
<p>Normalement, le configurateur compile et flashe les cartes lui-même. Si jamais vous ne pouvez pas l'utiliser,
voici les firmwares prêts à flasher, et leurs sources pour l'IDE Arduino.</p>
<div class="tableau"><table>
<tr><th>Carte</th><th>Fichier à flasher</th><th>Sources</th></tr>
{lignes_firmwares}
</table></div>
<ul>
<li><strong>Arduino Mega</strong> : <code>avrdude -p atmega2560 -c wiring -P /dev/ttyACM0 -b 115200 -D -U flash:w:mega_monture.hex:i</code></li>
<li><strong>Teensy</strong> : avec <a href="https://www.pjrc.com/teensy/loader.html">Teensy Loader</a>,
« File → Open HEX File », puis appui sur le bouton de la carte.</li>
<li><strong>Sources</strong> : installez les bibliothèques TinyGPSPlus et LiquidCrystal I2C dans l'IDE Arduino.</li>
</ul>
<p class="petit">Après un premier flashage, réglez la monture avec le configurateur : type de monture, rapports
d'engrenage, micro-pas.</p>
</section>
<section class="panneau">
<h2>Prérequis</h2>
<ul>
<li>Installateur et commande : <code>sudo apt install python3-venv python3-tk</code> (le paquet .deb s'en charge).</li>
<li>Module caméra : <code>sudo apt install astrometry.net astrometry-data-tycho2</code> et le SDK caméra de ZWO.</li>
<li>Flashage des cartes : <a href="https://arduino.github.io/arduino-cli/latest/">arduino-cli</a>.</li>
</ul>
</section>"""
    return page("Télécharger", "telecharger.html", contenu, version)


# ── Cartes électroniques et boîtiers ─────────────────────────
# (dossier dans pcb/, titre, la carte, pièces du boîtier à imprimer, le boîtier)
MATERIEL = (
    ("monture", "Carte monture : drivers StepStick",
     "150 x 110 mm, deux couches. Un Teensy 4.1 et quatre supports StepStick (azimut, hauteur, dérotateur, "
     "focuseur) pour TMC5160, TMC2209, A4988 ou DRV8825 ; les TMC5160 se règlent en SPI une fois les ponts à "
     "souder fermés. Alimentation 36 V par le bornier ou 12 V par le jack, protégée contre l'inversion des fils "
     "et par un fusible, convertisseur 5 V sur la carte.",
     ("base", "couvercle"),
     "Boîtier de 202 x 140 x 45 mm, couvercle ajouré au-dessus des drivers. Une chambre de câblage de 22 mm "
     "entoure la carte côté moteurs et sur les deux flancs : un presse-étoupe par élément : huit trous de 12,5 mm "
     "pour des PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm), un par moteur, un pour le 36 V, la raquette, le GPS et le PC. "
     "Le jack 12 V et le micro-USB gardent leur ouverture."),
    ("monture_ext", "Carte monture : drivers externes",
     "150 x 110 mm, deux couches. Le même Teensy et la même alimentation, avec des borniers vers des drivers "
     "externes (DM542, DM556, TB6600...) : signaux EN, STEP et DIR en 5 V, et alimentation de chaque driver.",
     ("base", "couvercle"),
     "Boîtier de 202 x 140 x 35 mm, avec la même chambre de câblage de 22 mm et un presse-étoupe par élément. "
     "Pour chaque axe, un trou de 20,5 mm pour un M20 x 1,5 à joint 2 trous : les câbles d'alimentation et de "
     "signaux du driver y passent ensemble. Pour le 36 V, la raquette, le GPS et le PC, un trou de 12,5 mm "
     "(PG7 ou M12 x 1,5)."),
    ("raquette", "Carte raquette",
     "105 x 150 mm, deux couches. Un Teensy 4.1, l'afficheur LCD 20 x 4 en I2C, cinq boutons et une prise "
     "Grove I2C, avec un adaptateur de niveau qui protège le Teensy du 5 V de l'I2C.",
     ("base", "face_avant", "boutons"),
     "Boîtier de 113 x 158 x 39 mm en deux parties : le fond, et la face avant avec la fenêtre de l'afficheur. "
     "L'écran LCD 2004 I2C (98 x 60 mm, Freenove ou équivalent, adresse 0x27 ou 0x3F reconnue toute seule) se "
     "visse sur quatre entretoises M3 de 15 mm, plus longues que l'adaptateur I2C de son dos : son cadre arrive "
     "juste sous la fenêtre. Le fond a un trou "
     "de 12,5 mm en bas pour le presse-étoupe du câble de la monture (PG7 ou M12 x 1,5, câble de 3 à 6,5 mm) ; "
     "l'écran est câblé à l'intérieur. Les cinq boutons "
     "s'impriment tête en bas, sans support ; ils sont calés pour des poussoirs 6 x 6 mm de 4,3 mm de haut "
     "(pour d'autres poussoirs, changez leur hauteur dans le script FreeCAD et relancez-le)."),
)

# Schéma de branchement, affiché sous les fichiers de la carte concernée
CABLAGE = {"monture": """<h3>Câblage d'un moteur</h3>
<div class="vues"><figure><a href="statique/cablage_moteur_stepstick.svg"><img src="statique/cablage_moteur_stepstick.svg"
alt="Schéma : bornes 1B et 1A du bornier moteur vers la bobine 1, bornes 2A et 2B vers la bobine 2 ; module StepStick
avec EN en haut à gauche et VMOT en haut à droite" loading="lazy"></a>
<figcaption>Cliquez pour agrandir</figcaption></figure></div>
<ul>
<li><strong>Bornier de l'axe</strong> (M_AZ, M_ALT, M_DEROT, M_FOCUS) : 1B et 1A pour la bobine 1, 2A et 2B pour
la bobine 2.</li>
<li><strong>Trouver les paires</strong> : au multimètre, 1 à 3 ohms entre les deux fils d'une même bobine, rien
entre deux fils de bobines différentes. Les couleurs des fils ne sont pas les mêmes d'un moteur à l'autre.</li>
<li><strong>Sens du module</strong> : la broche EN en haut à gauche, en face du repère EN, et VMOT en haut à droite,
en face de VM. Un module monté à l'envers est détruit à la mise sous tension.</li>
<li><strong>Ponts SPI</strong> (5 par axe, entre les barrettes) : à fermer seulement pour un TMC5160 réglé en SPI.
Laissez-les ouverts pour un A4988, un DRV8825 ou un TMC2209, dont ces broches ont d'autres fonctions. Les noms
des broches sur le schéma sont ceux du TMC5160.</li>
<li><strong>Moteur qui tourne à l'envers</strong> : inversez les deux fils d'une seule bobine, 1A et 1B.</li>
</ul>
<p class="petit">Coupez l'alimentation avant de brancher ou de débrancher un moteur : le module peut griller.</p>""",
           "monture_ext": """<h3>Branchement d'un driver externe</h3>
<div class="vues"><figure><a href="statique/cablage_driver_externe.svg"><img src="statique/cablage_driver_externe.svg"
alt="Schéma : VM et GND de J_VM vers +VDC et GND du driver ; EN, STEP, DIR de J_SIG vers ENA+, PUL+, DIR+ ;
GND de J_SIG vers ENA-, PUL- et DIR-" loading="lazy"></a>
<figcaption>Cliquez pour agrandir</figcaption></figure></div>
<p>Chaque axe a deux borniers, et donc deux GND. Ils sont reliés sur la carte, mais ne vont pas au même endroit
sur le driver :</p>
<ul>
<li><strong>J_VM</strong> (gros bornier) : VM vers +VDC et GND vers le GND d'alimentation du driver. C'est le
retour du courant des moteurs, plusieurs ampères : prenez du fil épais.</li>
<li><strong>J_SIG</strong> (petit bornier) : EN vers ENA+, STEP vers PUL+, DIR vers DIR+, et GND vers ENA-, PUL- et
DIR- reliés ensemble.</li>
</ul>
<p>Les entrées du driver sont des optocoupleurs, isolés de son alimentation : sans le GND de J_SIG, le courant des
signaux n'a pas de retour et le moteur ne bouge pas. Ce fil ne transporte que quelques milliampères ; séparé du
gros fil, il garde une référence propre, sans pas perdus ni parasites.</p>
<p class="petit">Driver alimenté par sa propre alimentation : laissez J_VM vide pour cet axe, mais gardez le GND de
J_SIG. L'ordre des bornes change d'un modèle de driver à l'autre : fiez-vous aux noms.</p>"""}


def page_materiel(depot, sortie, version):
    """Vues, fichiers de fabrication et liste des composants des cartes, et boîtiers à imprimer,
    recopiés du dossier pcb/ du dépôt dans <sortie>/materiel."""
    pcb, dossier = depot / "pcb", sortie / "materiel"
    if dossier.exists():
        shutil.rmtree(dossier)
    dossier.mkdir(parents=True)

    def fichier(source, texte):
        if not source.exists():
            return ""
        shutil.copy2(source, dossier / source.name)
        return (f'<li><a href="materiel/{source.name}" download>{html.escape(texte)}</a> '
                f'<span class="petit">({taille(source)})</span></li>')

    def vue(source, legende):
        if not source.exists():
            return ""
        shutil.copy2(source, dossier / source.name)
        return (f'<figure><a href="materiel/{source.name}"><img src="materiel/{source.name}" '
                f'alt="{html.escape(legende)}" loading="lazy"></a><figcaption>{html.escape(legende)}</figcaption></figure>')

    def projet_kicad(carte):
        zip_path = dossier / f"{carte}_kicad.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for ext in ("kicad_pcb", "kicad_pro"):
                z.write(pcb / carte / f"{carte}.{ext}", f"{carte}/{carte}.{ext}")
        return (f'<li><a href="materiel/{zip_path.name}" download>Projet KiCad 10 (.zip)</a> '
                f'<span class="petit">({taille(zip_path)})</span></li>')

    def composants(carte):
        source = pcb / "fabrication" / f"{carte}_composants.csv"
        if not source.exists():
            return ""
        lignes = list(csv.reader(source.read_text(encoding="utf-8").splitlines(), delimiter=";"))[1:]
        corps = "\n".join(f"<tr><td>{html.escape(d)}</td><td>{q}</td><td>{html.escape(r)}</td></tr>"
                          for d, q, r, _ in lignes)
        return (f'<details><summary>Liste des composants ({sum(int(l[1]) for l in lignes)} pièces)</summary>\n'
                f'<div class="tableau"><table>\n<tr><th>Désignation</th><th>Qté</th><th>Repères</th></tr>\n'
                f"{corps}\n</table></div></details>")

    sections = []
    for carte, titre, texte, pieces, texte_boitier in MATERIEL:
        rep, boitier = pcb / carte, f"boitier_{carte}"
        fichiers_carte = "\n".join(filter(None, (
            fichier(pcb / "fabrication" / f"{carte}_gerber.zip", "Gerber et perçages (.zip), pour le fabricant"),
            projet_kicad(carte),
            fichier(pcb / "fabrication" / f"{carte}_composants.csv", "Liste des composants (.csv)"),
            fichier(pcb / "fabrication" / f"{carte}_jlc_bom.csv", "Montage par JLCPCB : nomenclature BOM (.csv)"),
            fichier(pcb / "fabrication" / f"{carte}_jlc_cpl.csv", "Montage par JLCPCB : positions CPL (.csv)"),
            fichier(rep / f"{carte}.glb", "Modèle 3D de la carte (.glb)"))))
        fichiers_boitier = "\n".join(filter(None, [
            *(fichier(rep / f"{boitier}_{p}.stl", f"{p.replace('_', ' ').capitalize()} (.stl)") for p in pieces),
            fichier(rep / f"{boitier}.scad", "Source OpenSCAD (.scad)"),
            fichier(rep / f"boutons_{carte}.py", "Source FreeCAD des boutons (.py)")]))
        sections.append(f"""<section class="panneau">
<h2>{html.escape(titre)}</h2>
<p>{html.escape(texte)}</p>
<div class="vues">
{vue(rep / f"{carte}_perspective.jpg", "Vue en perspective")}
{vue(rep / f"{carte}_3d.png", "Vue de dessus")}
</div>
<h3>Fichiers de la carte</h3>
<ul class="fichiers">
{fichiers_carte}
</ul>
{composants(carte)}
{CABLAGE.get(carte, "")}
<h3>Boîtier à imprimer</h3>
<div class="vues">
{vue(rep / f"{boitier}_3d.png", "Le boîtier ouvert")}
{vue(rep / f"{boitier}_boutons_3d.png", "Les boutons sur leurs poussoirs")}
</div>
<p>{html.escape(texte_boitier)}</p>
<ul class="fichiers">
{fichiers_boitier}
</ul>
</section>""")
    contenu = f"""<section class="panneau">
<h1>Cartes et boîtiers</h1>
<p>GotoAndrivet a ses propres cartes électroniques : une pour la monture, en deux versions selon les drivers
des moteurs, et une pour la raquette. Ce sont des circuits à deux couches, à faire fabriquer, et chacune a son
boîtier à imprimer en 3D.</p>
<ul>
<li><strong>Faire fabriquer une carte</strong> : envoyez le fichier « Gerber et perçages » tel quel au
fabricant (JLCPCB, PCBWay, Aisler...), en épaisseur 1,6 mm.</li>
<li><strong>Acheter les pièces</strong> : la <a href="liste-achats.html">liste d'achat</a> donne, carte par
carte, les composants à souder et tout le reste (Teensy, écran, drivers, presse-étoupes, visserie, câbles).</li>
<li><strong>Câbler</strong> : les branchements des moteurs, du GPS et de la raquette sont dans la
<a href="fiche-technique.html">fiche technique</a> et la <a href="documentation.html">documentation</a>.</li>
<li><strong>Modifier</strong> : les cartes s'ouvrent dans <a href="https://www.kicad.org/">KiCad</a> 10, les
boîtiers dans <a href="https://openscad.org/">OpenSCAD</a>.</li>
</ul>
</section>
{chr(10).join(sections)}"""
    return page("Cartes et boîtiers", "materiel.html", contenu, version)


def page_accueil(commits, version):
    lignes = "\n".join(f'<tr><td class="symbole">{sym}</td><td><strong>{html.escape(t)}</strong><br>{html.escape(d)}</td></tr>'
                        for sym, t, d in FONCTIONS)
    recents = []
    for i, (_, d, t, _) in enumerate(commits[:5]):
        nouveau = ' <span class="clignote">NOUVEAU !</span>' if i == 0 else ""
        recents.append(f'<li><span class="date">{d}</span> {html.escape(t)}{nouveau}</li>')
    recents = "\n".join(recents)
    contenu = f"""<section class="panneau">
<h1>Bienvenue sur le site de GotoAndrivet !</h1>
<p>GotoAndrivet pilote votre télescope : monture <strong>AltAz</strong>, à <strong>fourche équatoriale</strong>
ou <strong>équatoriale allemande</strong>, avec une carte <strong>Arduino Mega</strong> ou <strong>Teensy</strong>.
Sur l'ordinateur, une carte du ciel envoie la monture sur n'importe quel objet, et s'occupe de la caméra,
de l'astrométrie et du guidage.</p>
<p class="centre"><a class="bouton" href="telecharger.html">► Télécharger GotoAndrivet</a></p>
</section>
<section class="panneau">
<h2>★ Ce que fait GotoAndrivet ★</h2>
<table class="fonctions">
{lignes}
</table>
</section>
<section class="panneau">
<h2>★ Quoi de neuf ? ★</h2>
<ul class="journal court">
{recents}
</ul>
<p><a href="nouveautes.html">Tout l'historique →</a></p>
</section>"""
    return page("Accueil", "index.html", contenu, version)


def page_nouveautes(commits, version):
    items = []
    for sha, d, titre, corps in commits:
        detail = ""
        if corps:
            detail = f"<details><summary>Détails</summary><pre class=\"corps\">{html.escape(corps)}</pre></details>"
        nouveau = ' <span class="clignote">NOUVEAU !</span>' if not items else ""
        items.append(f'<li><span class="date">{d}</span> <a class="sha" href="{GITHUB}/commit/{sha}">{sha[:7]}</a> '
                     f'<strong>{html.escape(titre)}</strong>{nouveau}{detail}</li>')
    contenu = f"""<section class="panneau">
<h1>Nouveautés</h1>
<p>Les dernières modifications du projet, les plus récentes en premier. Elles arrivent chez les utilisateurs
par le bouton « Mise à jour » des applications.</p>
<ul class="journal">
{chr(10).join(items)}
</ul>
</section>"""
    return page("Nouveautés", "nouveautes.html", contenu, version)


def page_404(version):
    contenu = """<section class="panneau centre">
<h1>Erreur 404 !</h1>
<p>Cette page a été aspirée par un trou noir.</p>
<p><a class="bouton" href="index.html">► Retour à l'accueil</a></p>
</section>"""
    return page("Page introuvable", "", contenu, version)


# ── Plan du site et consignes aux robots ──────────────────────
def plan_du_site(depot):
    """sitemap.xml : les pages publiques, datées par la dernière modification de leur source."""
    sources = {"index.html": None, "telecharger.html": None, "materiel.html": "pcb", "nouveautes.html": None}
    sources.update({href: fichier for fichier, (href, _) in DOCS.items() if (depot / fichier).exists()})
    lignes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for href, fichier in sources.items():
        args = ["log", "-1", "--format=%cs", "--"] + ([fichier] if fichier else [".", ":(exclude)site"])
        date = git(depot, *args)
        lignes.append(f"  <url><loc>{url_page(href)}</loc>" + (f"<lastmod>{date}</lastmod>" if date else "") + "</url>")
    lignes.append("</urlset>")
    return "\n".join(lignes) + "\n"


ROBOTS_TXT = f"""User-agent: *
Allow: /
Disallow: /telechargements/

Sitemap: {SITE}/sitemap.xml
"""


# ── Écriture ──────────────────────────────────────────────────
def versionner(texte, sortie):
    """Ajoute à chaque lien vers statique/ ou materiel/ une empreinte du fichier (?v=…). Le navigateur
    garde ces fichiers en cache (7 jours pour statique/) : un fichier modifié change ainsi d'adresse et
    il est rechargé tout de suite."""
    def remplace(m):
        f = sortie / m.group(2)
        if not f.is_file():
            return m.group(0)
        return f'{m.group(1)}="{m.group(2)}?v={zlib.crc32(f.read_bytes()):08x}"'
    return re.sub(r'(src|href)="((?:statique|materiel)/[^"?#]+)"', remplace, texte)


def ecrire(chemin, texte):
    if chemin.suffix == ".html":
        texte = versionner(texte, chemin.parent)
    tmp = chemin.with_name(f".{chemin.name}.tmp")
    tmp.write_text(texte, encoding="utf-8")
    os.replace(tmp, chemin)


def generer(depot, sortie, avec_miroir=False, force=False):
    """Régénère le site si besoin. Renvoie None (rien à faire), "compteur" (seul le compteur a changé)
    ou "contenu"."""
    depot, sortie = Path(depot).resolve(), Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    changes = miroir(sortie) if avec_miroir else []
    sha = git(depot, "rev-parse", "HEAD") or "inconnu"
    visiteurs = compteur(sortie)
    tampon = sortie / ".version"
    ancien = tampon.read_text().split() if tampon.exists() else []
    if not force and not changes and ancien[:2] == [sha, str(visiteurs)]:
        return None
    raison = "compteur" if not force and not changes and ancien[:1] == [sha] else "contenu"
    date = git(depot, "log", "-1", "--format=%ad", "--date=format:%d/%m/%Y") or "?"
    commits = historique(depot)
    version = (sha, date, commits[0][2] if commits else "", visiteurs)

    statique = sortie / "statique"
    if statique.exists():
        shutil.rmtree(statique)
    shutil.copytree(ICI / "statique", statique)
    shutil.copy2(depot / "icons" / "goto_andrivet.svg", statique / "icone.svg")
    fond_etoiles(statique / "fond-etoiles.png")

    ecrire(sortie / "index.html", page_accueil(commits, version))
    ecrire(sortie / "telecharger.html", page_telecharger(sortie, version))
    ecrire(sortie / "materiel.html", page_materiel(depot, sortie, version))
    ecrire(sortie / "nouveautes.html", page_nouveautes(commits, version))
    ecrire(sortie / "404.html", page_404(version))
    ecrire(sortie / "sitemap.xml", plan_du_site(depot))
    ecrire(sortie / "robots.txt", ROBOTS_TXT)
    for fichier in DOCS:
        if (depot / fichier).exists():
            href, texte = page_doc(depot, fichier, version)
            ecrire(sortie / href, texte)
    ecrire(tampon, f"{sha} {visiteurs}")
    return raison


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depot", default=str(ICI.parent), help="dossier du dépôt git (par défaut : celui de ce script)")
    ap.add_argument("--sortie", required=True, help="dossier du site généré")
    ap.add_argument("--miroir", action="store_true", help="copier aussi les fichiers d'installation publiés")
    ap.add_argument("--force", action="store_true", help="tout régénérer même si rien n'a changé")
    a = ap.parse_args()
    if generer(a.depot, a.sortie, a.miroir, a.force) == "contenu":      # le compteur seul ne remplit pas le journal
        print(f"{datetime.now():%d/%m/%Y %H:%M} site régénéré ({git(a.depot, 'rev-parse', '--short', 'HEAD')})")
