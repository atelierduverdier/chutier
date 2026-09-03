# Chutier — Cutting Plan and Scrap Stock

*[🇫🇷 Version française](README.md)*

Optimizer for the workshop: it places rectangular pieces in a stock of
**boards and scraps**, using guillotine cuts (each cut passes through
the edge from one side to the other, like with a circular saw),
respecting the saw kerf and grain direction. It provides a complete
plan: poses, cutting lines, reusable remaining scraps, and losses. Its
purpose: the scrap stock persists from one project to the next and comes
**before** new boards.

## Status

The core (`optimiseur.py`, with no dependencies) and the Qt interface
both exist and launch via:

```bash
python3 interface.py
```

Remaining tasks:

- an offcut stock that lives **outside the project**: today the stock is
  saved inside the project, and "Put these offcuts back in stock" updates
  the workshop within the current entry; what is missing is the shared
  file that would be found again from one project to the next without
  copying it;
- importing the parts list from a project's FreeCAD spreadsheet (the CSV
  is the exchange contract in the meantime);
- numbering the cuts on paper: the saw kerfs are drawn in the order they
  are made, but their rank can only be read in the tooltip.

## L'interface

Three tabs on the left, in the order of the work: **Parts** (what has to
be cut), **Stock** (what you have), **Settings** (how you saw). The
result fills the whole right-hand side: a row of key figures, then the
plan, every board stacked — parts coloured by reference, offcuts
hatched, a light background for waste.

| Raccourci | |
|---|---|
| `F5` | work out the cutting plan |
| `Ctrl+V` / `Ctrl+C` | coller un bloc venu d'un tableur / le recopier |
| `Ctrl+D` | dupliquer les lignes choisies |
| `Suppr` / `Ctrl+Suppr` | clear the cells / remove the rows |
| `Ctrl+M` | hide the entry panel, the whole screen for the plan |
| `Ctrl+molette` | zoom under the pointer (the wheel alone scrolls) |
| `Ctrl+E` / `Ctrl+P` | export the displayed plan as PNG / print it |
| `F1` | the reference notes, inside the app |

The colors of the pieces depend only on the **name** of the reference:
the same piece retains its shade from one session to another, and two
references from the same cutting plan never have the same color.

Three ways to output the cutting plan from the screen: the **plan** (PNG
at print resolution, or paginated printing—a handful of boards per page,
not sixty crushed on one, with cutting dimensions under the drawing),
the **workshop sheet** (text: positions and cuts board by board, to be
checked at the saw), and the **pieces in CSV** (the exchange format, now
bidirectional).

The text sizes of the plan are set for a rendering of approximately 1600
px wide and **scaled proportionally** beyond: set in pixels, they output
at 0.4 mm high on a page at 1200 dots per inch.

The saw kerf, overcuts, and drop thresholds are **retained from one
session to the next**—these are properties of the saw and the workshop,
not the project. A saved project keeps its own and reapplies them upon
opening.

## Usage

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

`python3 optimiseur.py` runs this demonstration.

## Conventions (to read before building around)

- **Millimeters** everywhere, surfaces in mm².
- The **length of a board runs along the grain**; in its coordinates, x
  follows the length, y the width, origin at the bottom left. A created
  offcut keeps this convention (it can therefore have `dim_x < dim_y`,
  it's physical).
- A piece declares its grain: `FIL_LONGUEUR` (default), `FIL_LARGEUR`,
  `FIL_INDIFFERENT`. A panel without a grain (`Planche(fil=False)`)
  frees rotation.
- A cut line is placed **flush with the piece**; the blade eats
  `[position, position + trait_de_scie]` on the opposite side.
- A remainder is a reusable offcut only if its long side reaches
  `chute_mini_longueur` and its short side `chute_mini_largeur`;
  otherwise, it goes to waste.
- Pieces and stock are matched by **material** (separate solved lots);
  within a lot, a board only fits a piece if it is **at least as
  thick**—the rough is planed down, never thickened.
  `tolerance_epaisseur` only absorbs measurement noise, not a real lack
  of thickness. A single board can therefore provide different finishing
  pieces.
- The `surcote` (overlap margin) is added to the cut dimensions; the
  piece keeps its nominal dimensions.
- A `composable` piece too wide for all rough is first decomposed into
  glued-together boards (or tenon-and-mortise assembled)—never if it
  could already fit as is. `surcote_joint`: width lost per gluing. No
  effect on `FIL_LARGEUR` (width is not the axis that would be widened
  by gluing).
- A `illimite=True` board is a **catalog profile** (a section you can
  buy), not boards already in the workshop—its `quantite` no longer
  bounds anything, the solver takes as many as the cut requires.
  `Resultat.achats` then counts, per profile, how many to buy. No effect
  on an offcut (already owned, never to be bought). Among several
  compatible profiles, `Planche.prix` (cost of ONE board, not per meter)
  splits the choice by the actual cost rather than just the new surface
  area used—to be filled out for ALL compared profiles. Without a price
  (the default, 0 everywhere), the least amount of planing lost decides
  (a piece at 20 prefers a rough at 30 over one at 65, even if its
  surface is larger), the smallest surface only deciding at equality.
- Score of a solution, in order: fewer unplaced pieces, fewer **new**
  surfaces used (stockout first), fewer losses, the largest possible
  remaining offcut.
- **Deterministic**: same inputs, same `graine` → same result.

## Layer Rule

`optimiseur.py` must **never** import Qt (a test ensures this). The
interface calls the core, never the reverse — same sharing as laser_core
/ task_panels in LaserAtelier.

| Module | Role |
|---|---|
| `optimiseur.py` | all geometry and solver. No dependencies. |
| `csv_io.py`, `projet_io.py` | CSV exchange, project JSON. Without Qt. |
| `apparence.py` | colors, summary tiles. Knows Qt, not cutting. |
| `tables_saisie.py` | the two tables and their delegates. |
| `vue_plan.py` | drawing of cut boards. |
| `interface.py` | the window: menus, tabs, actions, files. |

## License

LGPL-2.1-or-later, like the G-code viewer of the workshop — the
interface is built on PySide6 (Qt), the core has no dependencies.

## Tests

```bash
python3 tests/lancer.py
```

Interface tests run without a display (`QT_QPA_PLATFORM=offscreen`) and
divert Qt settings to a disposable folder. They keep what the eye
doesn't verify alone: that a table renders exactly the pieces given to
it, that a color doesn't move from one launch to another, that "putting
offcuts in stock" doesn't lose or invent wood. That the plan is
**readable**, on the other hand, is judged by screenshot.

Properties verified on random instances with a fixed seed (boundaries,
overlaps, saw kerf between any pair of rectangles, conservation of board
= pieces + offcuts + losses, accounting of copies) and exact cases
calculated by hand.
