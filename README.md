# Chutier — feuille de débit et stock de chutes

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

Restent à faire :

- un stock de chutes qui vive **hors projet** : aujourd'hui le stock est
  enregistré dans le projet, et « Ranger ces chutes au stock » remet
  l'atelier à jour dans la saisie courante ; il manque le fichier commun
  qu'on retrouverait d'un projet à l'autre sans le recopier ;
- l'import de la liste de pièces depuis la feuille de calcul FreeCAD
  d'un projet (le CSV est le contrat d'échange en attendant) ;
- numéroter les coupes sur le papier : les traits de scie se dessinent
  dans leur ordre d'exécution, mais leur rang n'est lisible qu'en
  info-bulle.

## L'interface

Trois onglets à gauche, dans l'ordre du geste : **Pièces** (ce qu'il faut
débiter), **Stock** (ce qu'on a), **Réglages** (comment on scie). Le
résultat occupe toute la droite : une rangée de chiffres-clés, puis le
plan, toutes les planches empilées — pièces colorées par référence,
chutes hachurées, fond clair pour la perte.

| Raccourci | |
|---|---|
| `F5` | calculer le débit |
| `Ctrl+V` / `Ctrl+C` | coller un bloc venu d'un tableur / le recopier |
| `Ctrl+D` | dupliquer les lignes choisies |
| `Suppr` / `Ctrl+Suppr` | vider les cellules / ôter les lignes |
| `Ctrl+M` | masquer la saisie, tout l'écran au plan |
| `Ctrl+molette` | zoomer sous la souris (la molette seule fait défiler) |
| `Ctrl+E` / `Ctrl+P` | exporter le plan affiché en PNG / l'imprimer |
| `F1` | les repères, dans l'appli |

Les couleurs des pièces ne dépendent que du **nom** de la référence : la
même pièce garde sa teinte d'une séance à l'autre, et deux références
d'un même débit n'ont jamais la même.

Trois façons de sortir le débit de l'écran : le **plan** (PNG à
résolution d'impression, ou impression paginée — une poignée de planches
par page, pas soixante écrasées sur une, avec les cotes de débit sous le
dessin), la **fiche d'atelier** (texte : poses et coupes planche par
planche, à cocher à la scie) et les **pièces en CSV** (le format
d'échange, désormais dans les deux sens).

Les tailles de texte du plan sont réglées pour un rendu d'environ
1600 px de large et **grossies à proportion** au-delà : réglées en
pixels, elles sortaient à 0,4 mm de haut sur une page à 1200 points par
pouce.

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
- Score d'une solution, dans l'ordre : moins de pièces non placées,
  moins de surface **neuve** entamée (déstockage d'abord), moins de
  pertes, plus grande chute subsistante la plus grande possible.
- **Déterministe** : mêmes entrées, même `graine` → même résultat.

## Règle de couches

`optimiseur.py` ne doit **jamais** importer Qt (un test y veille).
L'interface appelle le cœur, jamais l'inverse — même partage que
laser_core / task_panels dans LaserAtelier.

| Module | Rôle |
|---|---|
| `optimiseur.py` | toute la géométrie et le solveur. Aucune dépendance. |
| `csv_io.py`, `projet_io.py` | échange CSV, projet JSON. Sans Qt. |
| `apparence.py` | couleurs, tuiles de bilan. Connaît Qt, pas le débit. |
| `tables_saisie.py` | les deux tables et leurs délégués. |
| `vue_plan.py` | le dessin des planches débitées. |
| `interface.py` | la fenêtre : menus, onglets, actions, fichiers. |

## Licence

LGPL-2.1-or-later, comme le visualiseur G-code de l'atelier — l'interface
est bâtie sur PySide6 (Qt), le cœur n'a aucune dépendance.

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
chevauchements, trait de scie entre toute paire de rectangles,
conservation planche = pièces + chutes + pertes, comptabilité des
exemplaires) et cas exacts calculés à la main.
