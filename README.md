# Chutier — feuille de débit et stock de chutes

*[🇬🇧 English version](README.en.md)*

Optimiseur de débit pour l'atelier : il place des pièces rectangulaires
dans un stock de planches **et de chutes**, en coupes guillotine (chaque
trait traverse le morceau de bord à bord, comme à la scie circulaire),
en respectant le trait de scie et le sens du fil. Il rend le plan
complet : poses, traits de coupe, chutes restantes réutilisables,
pertes. Sa raison d'être : le stock de chutes persiste d'un projet à
l'autre et passe **avant** les planches neuves.

## État

Le cœur (`optimiseur.py`, sans aucune dépendance) et l'interface Qt
existent tous les deux, et se lancent par :

```bash
python3 interface.py
```

L'import depuis la feuille de calcul FreeCAD d'un projet est là :
Fichier → **Importer des pièces (FreeCAD .FCStd)**. Le tableur est lu
dans le document sans FreeCAD ; il faut une ligne d'en-tête (Rep. ou
Désignation, Longueur, Largeur, et à volonté Qté, Épaisseur, Matière,
Fil), une pièce par ligne dessous, les titres de section sautés. Les
formules sont calculées (alias, références entre feuilles comme
`Parametres.HautVantail`, unités, `round`…) : une feuille de débit
réelle en est faite. Ce que l'évaluateur ne sait pas, il le refuse en
nommant la cellule.

## La CNC : des formes quelconques, imbriquées

Fichier → **Importer des contours (SVG)** ajoute aux pièces chaque
tracé fermé du fichier (Inkscape, FreeCAD… ; un tracé contenu dans un
autre du même élément est un **trou** de celui-ci, et une pièce plus
petite peut s'y imbriquer — le NFP d'un polygone à trous laisse libre
l'intérieur du trou de lui-même). Une pièce à contour garde
ses cotes de boîte englobante dans la table, et la colonne Contour dit
« ◇ 24 pts ». Dès qu'une matière compte **un** contour, tout ce lot est
**imbriqué** à la fraise au lieu d'être scié : les rectangles y
participent comme des polygones, sur les mêmes planches et chutes, avec
les mêmes défauts. Réglages « La CNC » : écart entre contours (diamètre
de fraise + jeu), marge au bord, nombre d'orientations essayées pour une
pièce à fil indifférent. Fichier → **Exporter la découpe** sort chaque
planche à l'échelle 1 (mm), contour de la planche et contours fermés des
pièces, en **SVG**, en **DXF** (R12, calques PIECES, PLANCHE, NOMS) ou en
projet **LightBurn** (.lbrn, calque 0 les pièces, calque 1 le tour de
planche), pour la chaîne CNC ou le laser. Le DXF est relu sans une
correction par l'audit d'`ezdxf`, et le .lbrn a été ouvert dans un vrai
**LightBurn, en 1.3.01 et en 1.7** : aucun avertissement au chargement,
géométrie à l'échelle 1 en millimètres, trous compris, origine en bas à
gauche, les deux calques nommés. Le .lbrn ne
porte pas les noms des pièces — pour eux, le SVG ou le calque NOMS du
DXF.

Le moteur (`imbrication.py`, sur `shapely` ≥ 2.1) est un vrai
**no-fit polygon**, comme SVGnest, Deepnest et libnest2d : pour chaque
pièce posée A et pièce à poser B, le NFP est la région des positions de
B qui recouvrent A (somme de Minkowski de A et de B retournée, calculée
par triangulation contrainte : l'union des enveloppes convexes des
sommes de triangles), élargi de l'écart de fraise ; le bord de la
planche est un obstacle comme un autre. Les positions valides sont « la
planche moins l'union des NFP », et les candidates en sont les sommets,
toutes en contact avec un voisin ou le bord. On garde celle qui serre
le plus les pièces (la gravité de SVGnest, 2 × largeur + hauteur de la
boîte posée, ou l'aire de cette boîte), puis la plus basse et la plus à
gauche. Les NFP sont en cache par couple (forme, angle). Les stratégies
(ordres de pièces × objectifs) se répartissent sur **tous les cœurs**
(réglage Processus) ; le résultat ne dépend pas du nombre de cœurs,
seule la durée change — soixante pièces en un quart de seconde sur une
machine à trente-deux cœurs, deux secondes en séquentiel. Ce qui reste
est compté chute
pour les deux bandes rectangulaires (à droite, au-dessus) qui passent
les minis, perte pour le reste — le chutier range des rectangles.

**Déplacer une pièce à la main.** Sur une planche imbriquée, glisser une
pièce la déplace — au bureau comme sur le web. Le cœur valide le geste
(dans le bois, à l'écart des autres du même écart de fraise) et refait
les chutes ; la planche s'épingle d'elle-même, sinon le prochain calcul
déferait la main. Un déplacement impossible est refusé, avec sa raison.

**Les chutes biscornues.** Ce qui reste d'une planche imbriquée garde
sa forme : la planche moins les pièces élargies du passage de la fraise,
morceau par morceau. Un morceau rectangulaire à un demi pour cent près
redevient un rectangle qu'une scie saura reprendre ; les autres sont des
**chutes biscornues**, polygone et trous compris, hachurées sur le plan et
rangées au stock telles quelles par « Ranger les chutes au stock »
(colonne avancée Contour du stock, ramenées à l'origine, leurs cotes
étant leur boîte). On y imbrique à nouveau au débit suivant — dans le
bois, pas dans sa boîte. Un lot de rectangles à scier les ignore, et le
dit si le stock n'a plus qu'elles.

**Le temps de fraisage.** Une planche imbriquée n'a pas de coupes à
compter mais des contours à suivre : la tuile Pertes, le cartouche de
chaque planche et la fiche d'atelier donnent la **longueur de fraisage**
(contours et trous) et le temps qu'elle demande à la vitesse d'avance du
réglage (1 500 mm/min par défaut), sans les déplacements à vide.

## L'atelier

Le stock commun vit dans un fichier à part,
`~/.local/share/chutier/atelier.json` (déplaçable par la variable
`CHUTIER_ATELIER`). Dans l'onglet Stock, les lignes cochées **Atelier**
y vivent ; les autres appartiennent au projet. « Ranger ces chutes au
stock » y écrit **aussitôt** — une chute existe sur l'étagère que le
projet soit enregistré ou non ; le reste s'y écrit à l'enregistrement, à
la fermeture, et avant tout Nouveau / Ouvrir, qui relisent ensuite le
fichier. Un atelier garni ouvre l'application sur lui, feuille de pièces
blanche ; l'exemple ne sert qu'à la découverte.

## L'interface

Le menu Exemples en propose trois : les panneaux (guillotine), les
volets battants (un débit réel) et les **formes biscornues** — cadre
évidé, cœurs, étoiles, croissants, anneaux… imbriqués à la fraise sur du
contreplaqué. La page web les a aussi, dans « Plus… ».

À gauche, dans l'ordre du geste et l'un sous l'autre : **Pièces** (ce
qu'il faut débiter), **Stock** (ce qu'on a), et **Réglages** (comment on
scie) repliés sous les deux. Les boutons de ligne agissent sur la table
qui a le focus. Le résultat occupe toute la droite : une rangée de
chiffres-clés, puis le plan, toutes les planches empilées — pièces
colorées par référence, chutes hachurées, fond clair pour la perte.
Les étiquettes des pièces s'écrivent sur deux lignes, une ligne
(« montant · 1750 × 60 ») ou le seul nom, selon la place, et grandissent
avec la hauteur de la pièce.

| Raccourci | |
|---|---|
| `F5` | calculer le débit |
| `Ctrl+V` / `Ctrl+C` | coller un bloc venu d'un tableur / le recopier |
| `Ctrl+D` | dupliquer les lignes choisies |
| `Suppr` / `Ctrl+Suppr` | vider les cellules / ôter les lignes |
| `Ctrl+M` | masquer la saisie, tout l'écran au plan |
| `Ctrl+molette` | zoomer sous la souris (la molette seule fait défiler) |
| `Ctrl+E` / `Ctrl+P` | exporter le plan affiché en PNG / l'imprimer |
| clic droit sur le plan | épingler la planche, tailler la pièce ailleurs |
| `F1` | les repères, dans l'appli |

Les couleurs des pièces ne dépendent que du **nom** de la référence : la
même pièce garde sa teinte d'une séance à l'autre, et deux références
d'un même débit n'ont jamais la même.

Quatre façons de sortir le débit de l'écran : le **plan** (PNG à
résolution d'impression, ou impression paginée — une poignée de planches
par page, pas soixante écrasées sur une, avec les cotes de débit sous le
dessin, puis la liste des coupes numérotées de chaque planche ; sur le
papier, les traits de scie se dessinent toujours, avec leur numéro), la
**fiche d'atelier** (texte : poses et coupes numérotées
planche par planche, à cocher à la scie), les **étiquettes** (une par
pièce — référence, cotes, planche, exemplaire, couleur du plan — 24 par
page A4 en 70 × 37 mm, à coller sur le bois) et les **pièces en CSV** (le
format d'échange, dans les deux sens).

**Corriger le plan sans tricher sur les quantités** : clic droit sur une
planche pour l'**épingler** — elle est reprise telle quelle au prochain
calcul, le reste se range autour (les épingles s'enregistrent avec le
projet) ; clic droit sur une pièce pour la **tailler dans** une autre
ligne de stock (la colonne Planche des pièces dit la même chose).

**Les défauts du bois** se déclarent dans la colonne Défauts du stock,
termes séparés par « ; » : `bouts 30` (30 mm à ôter à chaque bout),
`rives 8` (sur chaque rive), `1200-1280` (un nœud traversant, de 1200 à
1280 mm du bout gauche), `600,140,60,40` (une zone x, y, longueur,
largeur). Elles sont écartées par des coupes guillotine avant toute
pose, le trait de scie tombant hors du défaut, et se hachurent sur le
plan.

Les tailles de texte du plan sont réglées pour un rendu d'environ
1600 px de large et **grossies à proportion** au-delà : réglées en
pixels, elles sortaient à 0,4 mm de haut sur une page à 1200 points par
pouce.

**Coupe en bandes** (réglages de la scie) : pour une scie à panneaux ou
à format, qui déligne d'abord la planche en bandes pleine longueur puis
tronçonne chaque bande. Le plan ne comporte alors que ces coupes en deux
étapes — une recoupe de largeur dans la bande à la rigueur, jamais une
recoupe de longueur —, là où le guillotine libre produit des plans
qu'une telle scie exécute mal. Ça coûte en général un peu de bois.

Le trait de scie, les surcotes et les seuils de chute sont **retenus
d'une séance à l'autre** — ce sont des propriétés de la scie et de
l'atelier, pas du projet. Un projet enregistré garde les siens et les
réimpose à son ouverture.

## Utilisation

```python
from optimiseur import Piece, Planche, Parametres, optimiser

stock = [
    Planche("sapin 2400×200", 2400, 200, 18, "sapin", quantite=4),
    Planche("chute étagère", 800, 180, 18, "sapin", chute=True),
]
pieces = [
    Piece("montant", 1750, 60, 18, "sapin", quantite=4),
    Piece("tablette", 560, 180, 18, "sapin", quantite=3),
]
resultat = optimiser(pieces, stock)   # Parametres() en option
print(resultat.texte())               # résumé lisible
```

`python3 optimiseur.py` déroule cette démonstration.

## Conventions (à lire avant de bâtir autour)

- **Millimètres** partout, surfaces en mm².
- La **longueur d'une planche court le long du fil** ; dans ses
  coordonnées, x suit la longueur, y la largeur, origine en bas à
  gauche. Une chute créée garde cette convention (elle peut donc avoir
  `dim_x < dim_y`, c'est physique).
- Une pièce déclare son fil : `FIL_LONGUEUR` (défaut), `FIL_LARGEUR`,
  `FIL_INDIFFERENT`. Un panneau sans fil (`Planche(fil=False)`) libère
  la rotation.
- Un trait de coupe est posé **au ras de la pièce** ; la lame mange
  `[position, position + trait_de_scie]` du côté opposé.
- Un reste n'est une chute réutilisable que si son grand côté atteint
  `chute_mini_longueur` et son petit côté `chute_mini_largeur` ; sinon
  il part dans les pertes.
- Les pièces et le stock sont appariés par **matière** (lots résolus
  séparément) ; au sein d'un lot, une planche ne convient à une pièce
  que si elle est **au moins aussi épaisse** — le brut se rabote,
  jamais ne s'épaissit. `tolerance_epaisseur` n'absorbe que le bruit de
  mesure, pas un vrai manque d'épaisseur. Une même planche peut donc
  fournir des pièces de finitions différentes.
- La `surcote` (marge de recoupe) s'ajoute aux dimensions débitées ;
  la pièce garde ses cotes nominales.
- Une pièce `composable` trop large pour tout brut se décompose
  d'abord en lames à coller (ou à assembler tenon-rainure) — jamais si
  elle logerait déjà telle quelle. `surcote_joint` : largeur perdue à
  chaque collage. Sans effet sur `FIL_LARGEUR` (la largeur n'y est pas
  l'axe qu'on élargirait par collage).
- Une planche `illimite=True` est un **profil de catalogue** (une
  section qu'on peut acheter), pas des planches déjà en atelier — sa
  `quantite` ne borne plus rien, le solveur en prend autant que le
  débit demande. `Resultat.achats` compte ensuite, par profil,
  combien en acheter. Sans effet sur une chute (déjà possédée, jamais
  à acheter). Entre plusieurs profils compatibles, `Planche.prix`
  (coût d'UNE planche, pas au mètre) départage le choix par le coût
  réel plutôt que la seule surface neuve entamée — à renseigner sur
  TOUS les profils comparés. Sans prix (le défaut, 0 partout), c'est
  le moins de rabotage perdu qui décide (une pièce à 20 préfère un
  brut à 30 plutôt qu'un brut à 65, même si sa surface est plus
  grande), la plus petite surface ne tranchant qu'à égalité.
- Une planche déclare ses défauts : `recoupe_bouts`, `recoupe_rives`
  (mm à ôter à chaque bout / sur chaque rive) et `defauts`, des zones
  `(x, y, dx, dy)` écartées par des coupes guillotine à l'ouverture de
  la planche. La zone déclarée est perdue en entier, le trait tombe dans
  le bon bois.
- Une pièce peut imposer sa planche par la référence d'une ligne de
  stock (`Piece.planche`) ; `optimiser(..., epingles=[Debit])` reprend
  des débits tels quels, retire leurs pièces et leur planche de la
  demande, et renumérote le tout à la suite.
- Score d'une solution, dans l'ordre : moins de pièces non placées,
  moins cher (si les prix sont renseignés), moins de bois **neuf**
  entamé (déstockage d'abord), moins de pertes puis moins de coupes —
  ou l'inverse quand `Parametres.priorite` vaut `PRIORITE_SCIE` —,
  enfin des chutes subsistantes concentrées (somme des carrés : une
  grande plutôt que trois moyennes).
- Le solveur rejoue un glouton sous une soixantaine de stratégies, puis
  travaille la meilleure par recherche locale (`passes_amelioration`
  balayages : vider une planche, replacer ses pièces dans les trous des
  autres).
- Une pièce à `contour` (points mm, coin bas-gauche en (0, 0)) fait
  imbriquer tout son lot ; sa pose porte alors le contour tourné et
  déplacé, en coordonnées de la planche, et son aire est celle du
  polygone. Pas de coupes sur une planche imbriquée.
- **Déterministe** : mêmes entrées, même `graine` → même résultat.

## Règle de couches

`optimiseur.py` ne doit **jamais** importer Qt (un test y veille).
L'interface appelle le cœur, jamais l'inverse — même partage que
laser_core / task_panels dans LaserAtelier.

| Module | Rôle |
|---|---|
| `optimiseur.py` | toute la géométrie et le solveur guillotine. Aucune dépendance. |
| `imbrication.py` | l'imbrication de contours pour la CNC. Dépend de `shapely`, importé par le cœur seulement quand un contour est demandé. Sans Qt. |
| `contours_svg.py` | lecture des tracés SVG (parseur repris de LaserAtelier), écriture de la découpe. Sans dépendance. |
| `triangulation.py` | découpage en oreilles d'un polygone à trous, pour le NFP quand `shapely` < 2.1 (le navigateur). Sans dépendance. |
| `csv_io.py`, `projet_io.py` | échange CSV, projet JSON. Sans Qt. |
| `apparence.py` | couleurs, tuiles de bilan. Connaît Qt, pas le débit. |
| `tables_saisie.py` | les deux tables et leurs délégués. |
| `vue_plan.py` | le dessin des planches débitées. |
| `interface.py` | la fenêtre : menus, onglets, actions, fichiers. |

## Licence

LGPL-2.1-or-later, comme le visualiseur G-code de l'atelier — l'interface
est bâtie sur PySide6 (Qt), le cœur n'a aucune dépendance ; l'imbrication
de contours demande `shapely` (paquet `python-shapely`), en 2.1 pour la
triangulation en C, sinon la triangulation maison prend le relais.

## Dans le navigateur

**<https://atelierduverdier.github.io/chutier/>** — la même application,
sans rien installer : `index.html` et `web/` chargent le cœur Python
entier (guillotine, imbrication, trous, SVG, projet) dans le navigateur
par **Pyodide** (Python en WebAssembly), avec `shapely` et `numpy`.
Rien n'est envoyé nulle part : le calcul a lieu dans un Web Worker de la
page, le stock de l'atelier vit dans le stockage local du navigateur, et
les fichiers (projet .json, pièces .csv, contours et découpe .svg) sont
les mêmes que ceux de l'application de bureau, dans les deux sens. Le
premier chargement télécharge une quinzaine de Mo (ensuite en cache).
Le calcul y est **réparti sur plusieurs Web Workers** : 86 % du temps
d'une imbrication part dans les no-fit polygons, indépendants les uns des
autres, et la page en confie une tranche à chacun de trois workers de
plus. Sur l'exemple des formes biscornues, un premier calcul passe de 7 à
4 secondes ; ce qu'un calcul a déjà mis en cache n'est jamais redistribué,
le refaire à plusieurs coûterait plus cher que de ne rien faire. Sans
impression d'étiquettes : pour celle-là, le bureau. Pour l'essayer en local : `python3 -m http.server` à la racine,
puis <http://localhost:8000/>.

Entre la saisie et le plan, une **poignée** règle la largeur des deux
moitiés, comme la séparation de l'application de bureau : douze colonnes
de stock ne tiennent pas dans un tiers d'écran, et la table défilait en
travers sous une barre qui venait buter sur sa ligne de résumé. Le
navigateur retient la largeur ; un double-clic rend celle d'origine.

La page est **bilingue** : un bouton « EN / FR » près du titre bascule
toute l'interface, et le choix est retenu dans le navigateur (au premier
passage, la langue du navigateur décide). Le dictionnaire est
`web/langue.js`, dont la clé EST le texte français : un texte sans
traduction s'affiche en français plutôt que de disparaître, et
`tests/test_langue.py` refuse qu'une chaîne de `web/app.js` ou
d'`index.html` n'ait pas sa traduction, ou qu'une traduction ne serve
plus. L'application de bureau, elle, reste en français.

La page **fonctionne hors-ligne** après une première visite : un
service worker (`sw.js`) garde la page, les modules Python et les
fichiers de Pyodide — réseau d'abord quand il répond, cache sinon. Elle
s'installe comme une application (manifeste) depuis le menu du
navigateur. La **pastille de version** près du titre dit si c'est bien
la dernière : verte à jour, orange avec « ⟳ » quand `version.json` en
ligne annonce plus récent — la toucher recharge tout ; neutre
hors-ligne, elle n'affirme rien. L'application de bureau porte la même
pastille dans sa barre d'état, et interroge la même adresse au
démarrage (`CHUTIER_SANS_RESEAU=1` la coupe) ; un clone git se met à
jour par `git pull`.

## Tests

```bash
python3 tests/lancer.py
```

Les tests d'interface tournent sans écran (`QT_QPA_PLATFORM=offscreen`)
et détournent les réglages Qt vers un dossier jetable. Ils gardent ce que
l'œil ne vérifie pas seul : qu'une table rende exactement les pièces
qu'on lui a données, qu'une couleur ne bouge pas d'un lancement à
l'autre, que « ranger les chutes au stock » ne perde ni n'invente de
bois. Que le plan se **lise**, en revanche, se juge sur capture.

Propriétés vérifiées sur instances aléatoires à graine fixe (bornes,
chevauchements, trait de scie entre toute paire de rectangles, rien de
posé sur un défaut, conservation planche = pièces + chutes + pertes,
comptabilité des exemplaires, la recherche locale ne dégrade jamais, la
priorité « scie » ne coupe jamais plus que la priorité « bois ») et cas
exacts calculés à la main.
