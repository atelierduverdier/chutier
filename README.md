# Chutier — feuille de débit et stock de chutes

Optimiseur de débit pour l'atelier : il place des pièces rectangulaires
dans un stock de planches **et de chutes**, en coupes guillotine (chaque
trait traverse le morceau de bord à bord, comme à la scie circulaire),
en respectant le trait de scie et le sens du fil. Il rend le plan
complet : poses, traits de coupe, chutes restantes réutilisables,
pertes. Sa raison d'être : le stock de chutes persiste d'un projet à
l'autre et passe **avant** les planches neuves.

## État

**Seul le cœur existe** : `optimiseur.py`, sans aucune dépendance, testé.
Restent à faire (sessions suivantes) :

- l'interface Qt (PySide6) : saisie des pièces, du stock, dessin du plan ;
- la persistance du stock de chutes (JSON) et la réinjection des chutes
  créées via `ChuteCreee.en_planche()` ;
- l'import de la liste de pièces depuis la feuille de calcul FreeCAD
  d'un projet ;
- le plan de découpe imprimable (les `Coupe` sont des segments prêts à
  dessiner, dans un ordre exécutable à l'établi).

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
- Score d'une solution, dans l'ordre : moins de pièces non placées,
  moins de surface **neuve** entamée (déstockage d'abord), moins de
  pertes, plus grande chute subsistante la plus grande possible.
- **Déterministe** : mêmes entrées, même `graine` → même résultat.

## Règle de couches

`optimiseur.py` ne doit **jamais** importer Qt (un test y veille).
L'interface appellera le cœur, pas l'inverse — même partage que
laser_core / task_panels dans LaserAtelier.

## Tests

```bash
python3 tests/test_optimiseur.py
```

Propriétés vérifiées sur instances aléatoires à graine fixe (bornes,
chevauchements, trait de scie entre toute paire de rectangles,
conservation planche = pièces + chutes + pertes, comptabilité des
exemplaires) et cas exacts calculés à la main.
