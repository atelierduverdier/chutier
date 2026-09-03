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

Remaining task: importing the parts list from a project's FreeCAD
spreadsheet (the CSV is the exchange contract in the meantime).

## CNC: arbitrary shapes, nested

File → **Import contours (SVG)** adds to the parts every closed path of
the file (Inkscape, FreeCAD…; a path contained in another one of the
same element is a hole, ignored). A part with a contour keeps its
bounding-box dimensions in the table, and the Contour column says
"◇ 24 pts". As soon as a material has **one** contour, that whole lot is
**nested** for the router instead of being sawn: rectangles take part as
polygons, on the same boards and offcuts, with the same defects.
Settings "La CNC": gap between contours (bit diameter + clearance),
margin to the edge, number of orientations tried for a part with free
grain. File → **Export the cut (SVG)** writes every nested board as an
SVG at scale 1 (mm), board outline and closed paths of the parts, for
the CNC chain.

The engine (`imbrication.py`, on `shapely`) is a bottom-left greedy:
candidate positions are vertex-to-vertex contacts between the part and
what is already placed, grown by the gap, each projected to the floor
and to the wall; the lowest then leftmost one that overlaps nothing
wins. Replayed under several part orders, the best by the chutier's
score. What remains counts as offcut for the two rectangular strips (to
the right, above) that pass the minima, waste for the rest — the chutier
stores rectangles. Expect one to a few seconds per ten parts.

## The workshop

The shared stock lives in its own file,
`~/.local/share/chutier/atelier.json` (moved by the `CHUTIER_ATELIER`
variable). In the Stock tab, rows ticked **Atelier** live there; the
others belong to the project. "Put these offcuts back in stock" writes
it **at once** — an offcut exists on the shelf whether the project is
saved or not; the rest is written on save, on close, and before any
New / Open, which then re-read the file. A stocked workshop opens the
application on itself, with a blank parts sheet; the example only
serves discovery.

## L'interface

On the left, in the order of the work and one below the other: **Parts**
(what has to be cut), **Stock** (what you have), and **Settings** (how
you saw) folded under both. The row buttons act on the table that has
focus. The result fills the whole right-hand side: a row of key figures,
then the plan, every board stacked — parts coloured by reference,
offcuts hatched, a light background for waste. Part labels are written
on two lines, one line ("montant · 1750 × 60") or the name alone,
depending on room, and grow with the height of the part.

| Raccourci | |
|---|---|
| `F5` | work out the cutting plan |
| `Ctrl+V` / `Ctrl+C` | coller un bloc venu d'un tableur / le recopier |
| `Ctrl+D` | dupliquer les lignes choisies |
| `Suppr` / `Ctrl+Suppr` | clear the cells / remove the rows |
| `Ctrl+M` | hide the entry panel, the whole screen for the plan |
| `Ctrl+molette` | zoom under the pointer (the wheel alone scrolls) |
| `Ctrl+E` / `Ctrl+P` | export the displayed plan as PNG / print it |
| right-click on the plan | pin the board, cut the piece elsewhere |
| `F1` | the reference notes, inside the app |

The colors of the pieces depend only on the **name** of the reference:
the same piece retains its shade from one session to another, and two
references from the same cutting plan never have the same color.

Four ways to output the cutting plan from the screen: the **plan** (PNG
at print resolution, or paginated printing—a handful of boards per page,
not sixty crushed on one, with cutting dimensions under the drawing,
then each board's numbered cut list; on paper, saw kerfs are always
drawn, with their number), the
**workshop sheet** (text: positions and numbered cuts board by board, to
be checked at the saw), the **labels** (one per piece — reference,
dimensions, board, copy, plan colour — 24 per A4 page at 70 × 37 mm, to
stick on the wood) and the **pieces in CSV** (the exchange format,
bidirectional).

**Correcting the plan without cheating on quantities**: right-click a
board to **pin** it — it is taken over as is at the next computation,
the rest arranges itself around it (pins are saved with the project);
right-click a piece to **cut it in** another stock row (the Planche
column of the pieces says the same).

**Wood defects** are declared in the stock's Défauts column, terms
separated by ";": `bouts 30` (30 mm to remove at each end), `rives 8`
(on each edge), `1200-1280` (a through knot, from 1200 to 1280 mm from
the left end), `600,140,60,40` (a zone x, y, length, width). They are
removed by guillotine cuts before any placement, the kerf falling
outside the defect, and are hatched on the plan.

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
- A board declares its defects: `recoupe_bouts`, `recoupe_rives` (mm to
  remove at each end / on each edge) and `defauts`, zones
  `(x, y, dx, dy)` removed by guillotine cuts when the board is opened.
  The declared zone is lost entirely; the kerf falls in sound wood.
- A piece may impose its board through a stock row's reference
  (`Piece.planche`); `optimiser(..., epingles=[Debit])` takes debits
  over as they are, removes their pieces and board from the demand, and
  renumbers everything in sequence.
- Score of a solution, in order: fewer unplaced pieces, cheaper (when
  prices are given), less **new** wood used (destocking first), fewer
  losses then fewer cuts — or the reverse when `Parametres.priorite` is
  `PRIORITE_SCIE` —, finally concentrated remaining offcuts (sum of
  squares: one large rather than three medium).
- The solver replays a greedy under some sixty strategies, then works
  the best one by local search (`passes_amelioration` sweeps: empty a
  board, place its pieces back in the holes of the others).
- A part with a `contour` (mm points, bottom-left corner at (0, 0))
  makes its whole lot nested; its placement then carries the rotated
  and translated contour in board coordinates, and its area is the
  polygon's. No cuts on a nested board.
- **Deterministic**: same inputs, same `graine` → same result.

## Layer Rule

`optimiseur.py` must **never** import Qt (a test ensures this). The
interface calls the core, never the reverse — same sharing as laser_core
/ task_panels in LaserAtelier.

| Module | Role |
|---|---|
| `optimiseur.py` | all geometry and the guillotine solver. No dependencies. |
| `imbrication.py` | contour nesting for CNC. Depends on `shapely`, imported by the core only when a contour is requested. Without Qt. |
| `contours_svg.py` | reading SVG paths (parser taken from LaserAtelier), writing the cut. No dependencies. |
| `csv_io.py`, `projet_io.py` | CSV exchange, project JSON. Without Qt. |
| `apparence.py` | colors, summary tiles. Knows Qt, not cutting. |
| `tables_saisie.py` | the two tables and their delegates. |
| `vue_plan.py` | drawing of cut boards. |
| `interface.py` | the window: menus, tabs, actions, files. |

## License

LGPL-2.1-or-later, like the G-code viewer of the workshop — the
interface is built on PySide6 (Qt), the core has no dependencies;
contour nesting requires `shapely` (`python-shapely` package).

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
overlaps, saw kerf between any pair of rectangles, nothing placed on a
defect, conservation of board = pieces + offcuts + losses, accounting of
copies, local search never degrades, the "saw" priority never cuts more
than the "wood" priority) and exact cases calculated by hand.
