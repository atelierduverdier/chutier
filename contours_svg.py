# -*- coding: utf-8 -*-
"""Contours SVG — lecture pour l'imbrication, écriture du résultat.

La couche d'analyse (grammaire du `d`, aplatissement Bézier/arc,
transformations, parcours de l'arbre) est reprise telle quelle du
``svg_import.py`` de LaserAtelier, même auteur, sans sa partie FreeCAD :
du Python pur sur ``xml.etree``. Y est retourné à la lecture (le SVG
compte Y vers le bas, l'atelier vers le haut) et retourné à l'écriture.

Ce module ajoute deux points d'entrée pour le chutier :

- :func:`formes_depuis_svg` : chaque sous-tracé fermé devient une forme
  à imbriquer (contour en mm, origine au coin bas-gauche de sa boîte) ;
  un sous-tracé fermé contenu dans un autre du même élément est un
  trou, ignoré ; un tracé ouvert est signalé, pas importé.
- :func:`ecrire_svg` : une planche imbriquée en SVG à l'échelle 1 (mm),
  le contour de la planche et chaque pièce en chemin fermé — ce qu'on
  passe à la chaîne CNC.

Aucune dépendance : ni Qt, ni shapely (le point-dans-polygone est écrit
ici, il ne sert qu'à reconnaître les trous).
"""
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter


class SvgParseError(ValueError):
    """Donnée SVG inattendue dans un attribut `d` (position incluse)."""


# ==========================================================================
# A. GRAMMAIRE DU CHEMIN `d` (tokenizer + machine à états)
# ==========================================================================

# Tolérance d'aplatissement par défaut, en mm : c'est une FLÈCHE maximale
# (écart corde/courbe), pas un espacement de points. 0,02 mm reste bien
# sous la largeur de brûlure du trait (~0,1-0,2 mm au foyer) : aucun
# facettage visible, même sur une grande courbe douce. Sans coût aval :
# chain_edges re-densifie de toute façon les segments à 0,3 mm
# d'espacement pour le G-code.
FLATTEN_TOL_MM = 0.02

_ARG_COUNT = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
              "Q": 4, "T": 2, "A": 7, "Z": 0}
_COMMAND_LETTERS = set("MLHVCSQTAZmlhvcsqtaz")
_SEPARATORS = set(" \t\r\n,")

_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def _skip_sep(d, i):
    """Avance le curseur au-delà des espaces/virgules."""
    n = len(d)
    while i < n and d[i] in _SEPARATORS:
        i += 1
    return i


def _read_number(d, i):
    """Lit un nombre SVG à partir de `i` ; retourne (valeur, curseur suivant)."""
    i = _skip_sep(d, i)
    m = _NUMBER_RE.match(d, i)
    if not m:
        raise SvgParseError("nombre attendu à l'offset {}".format(i))
    return float(m.group(0)), m.end()


def _read_flag(d, i):
    """Lit un drapeau d'arc : EXACTEMENT un caractère '0' ou '1'.

    Indispensable en dehors de _read_number : le SVG colle les drapeaux
    large-arc/sweep contre la valeur suivante sans séparateur (« ...,0,111.8 »
    peut signifier drapeau=1, drapeau=1, x=1.8 -- une regex de flottant
    avalerait « 11 » en entier)."""
    i = _skip_sep(d, i)
    if i >= len(d) or d[i] not in "01":
        raise SvgParseError("drapeau 0/1 attendu à l'offset {}".format(i))
    return int(d[i]), i + 1


def _iter_path_tokens(d):
    """Générateur de tokens (lettre, [arguments…]) d'un attribut `d`.

    Gère la règle de répétition implicite : une lettre suivie de plusieurs
    groupes d'arguments (ex. un M puis deux groupes `c` sans re-préfixe).
    Z/z produit toujours exactement ('Z'|'z', []) sans répétition. Lève
    SvgParseError au point d'erreur -- les tokens déjà produits restent
    exploitables par l'appelant (interprétation au fil de l'eau)."""
    i = _skip_sep(d, 0)
    n = len(d)
    while i < n:
        letter = d[i]
        if letter not in _COMMAND_LETTERS:
            raise SvgParseError(
                "commande inconnue « {} » à l'offset {}".format(letter, i))
        i += 1
        arity = _ARG_COUNT[letter.upper()]
        if arity == 0:
            yield letter, []
            i = _skip_sep(d, i)
            continue
        is_arc = letter.upper() == "A"
        emise = letter
        while True:
            group = []
            for pos in range(arity):
                if is_arc and pos in (3, 4):
                    val, i = _read_flag(d, i)
                else:
                    val, i = _read_number(d, i)
                group.append(val)
            yield emise, group
            # Norme SVG : après le PREMIER groupe d'un M/m, les groupes
            # répétés sont des LINETO implicites, pas d'autres déplacements.
            # Les confondre perd le premier segment du sous-tracé ET fausse
            # son point de départ -- donc le retour du Z, donc le départ du
            # sous-tracé suivant : l'erreur s'accumule de glyphe en glyphe.
            # Inkscape écrit systématiquement `m x,y dx,dy …` en convertissant
            # du texte en chemins.
            if emise.upper() == "M":
                emise = "l" if emise.islower() else "L"
            i = _skip_sep(d, i)
            # Répétition implicite : encore des chiffres avant la
            # prochaine lettre ?
            if i >= n or d[i] in _COMMAND_LETTERS:
                break


def path_d_to_subpaths(d, tol=FLATTEN_TOL_MM):
    """Interprète un attribut `d` en sous-tracés aplatis.

    Retourne (subpaths, warnings) où chaque sous-tracé est
    {"points": [(x, y), …], "closed": bool}. Sur Z/z le point de départ est
    ré-ajouté explicitement s'il n'est pas déjà confondu avec le point
    courant : le pipeline hachures/gravure existant (chain_edges,
    Part.sortEdges) exige une chaîne littéralement fermée. Une donnée
    malformée arrête l'analyse de CE tracé : on retourne les sous-tracés
    déjà complets plus un avertissement, sans jamais lever."""
    subpaths = []
    warnings = []
    current = (0.0, 0.0)
    subpath_start = (0.0, 0.0)
    points = None
    last_control = None       # dernier point de contrôle C/S ou Q/T
    last_cmd = ""

    def _finish(closed=False):
        nonlocal points
        if points is not None and len(points) >= 2:
            if closed:
                fx, fy = points[0]
                lx, ly = points[-1]
                if math.hypot(lx - fx, ly - fy) > 1e-9:
                    points.append((fx, fy))
            subpaths.append({"points": points, "closed": closed})
        points = None

    try:
        for letter, args in _iter_path_tokens(d):
            rel = letter.islower()
            cmd = letter.upper()
            ox, oy = current if rel else (0.0, 0.0)

            if cmd == "M":
                _finish(False)
                current = (args[0] + ox, args[1] + oy)
                subpath_start = current
                points = [current]
            elif cmd == "Z":
                if points is not None:
                    current = subpath_start
                    _finish(True)
                    # Un tracé peut continuer après Z (nouveau sous-tracé
                    # implicite depuis le point de départ).
                    points = [current]
            elif points is None:
                # Commande de dessin sans M préalable : point courant
                # implicite (0,0), rare mais toléré.
                points = [current]

            if cmd == "L":
                current = (args[0] + ox, args[1] + oy)
                points.append(current)
            elif cmd == "H":
                current = (args[0] + ox, current[1])
                points.append(current)
            elif cmd == "V":
                current = (current[0], args[0] + oy)
                points.append(current)
            elif cmd in ("C", "S"):
                if cmd == "C":
                    c1 = (args[0] + ox, args[1] + oy)
                    c2 = (args[2] + ox, args[3] + oy)
                    end = (args[4] + ox, args[5] + oy)
                else:
                    if last_cmd in ("C", "S") and last_control is not None:
                        c1 = (2 * current[0] - last_control[0],
                              2 * current[1] - last_control[1])
                    else:
                        c1 = current
                    c2 = (args[0] + ox, args[1] + oy)
                    end = (args[2] + ox, args[3] + oy)
                points.extend(flatten_cubic_bezier(current, c1, c2, end, tol))
                last_control = c2
                current = end
            elif cmd in ("Q", "T"):
                if cmd == "Q":
                    c1 = (args[0] + ox, args[1] + oy)
                    end = (args[2] + ox, args[3] + oy)
                else:
                    if last_cmd in ("Q", "T") and last_control is not None:
                        c1 = (2 * current[0] - last_control[0],
                              2 * current[1] - last_control[1])
                    else:
                        c1 = current
                    end = (args[0] + ox, args[1] + oy)
                points.extend(flatten_quadratic_bezier(current, c1, end, tol))
                last_control = c1
                current = end
            elif cmd == "A":
                rx, ry, phi_deg, laf, sf = args[0], args[1], args[2], int(args[3]), int(args[4])
                end = (args[5] + ox, args[6] + oy)
                center = svg_arc_to_center(current[0], current[1], rx, ry,
                                           phi_deg, laf, sf, end[0], end[1])
                if center is None:
                    points.append(end)   # dégénéré : trait droit, selon la spec
                else:
                    cx, cy, arx, ary, phi, th1, dth = center
                    points.extend(flatten_arc(cx, cy, arx, ary, phi, th1, dth, tol))
                current = end

            if cmd not in ("C", "S", "Q", "T"):
                last_control = None
            last_cmd = cmd
    except SvgParseError as exc:
        warnings.append("tracé interrompu ({})".format(exc))

    _finish(False)
    return subpaths, warnings


# ==========================================================================
# B. APLATISSEMENT BÉZIER / ARC (mathématiques pures)
# ==========================================================================

def _point_line_dist(p, a, b):
    """Distance perpendiculaire de p à la droite (a, b)."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    length = math.hypot(abx, aby)
    if length < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(abx * (p[1] - a[1]) - aby * (p[0] - a[0])) / length


def _mid(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def flatten_cubic_bezier(p0, p1, p2, p3, tol=FLATTEN_TOL_MM, depth=0, max_depth=24):
    """Aplati une Bézier cubique en points (p0 exclu, p3 inclus).

    Test de platitude : distance des points de contrôle à la corde ;
    subdivision de De Casteljau à t=0.5 sinon."""
    if depth >= max_depth or max(_point_line_dist(p1, p0, p3),
                                 _point_line_dist(p2, p0, p3)) <= tol:
        return [p3]
    p01, p12, p23 = _mid(p0, p1), _mid(p1, p2), _mid(p2, p3)
    p012, p123 = _mid(p01, p12), _mid(p12, p23)
    p0123 = _mid(p012, p123)
    return (flatten_cubic_bezier(p0, p01, p012, p0123, tol, depth + 1, max_depth)
            + flatten_cubic_bezier(p0123, p123, p23, p3, tol, depth + 1, max_depth))


def flatten_quadratic_bezier(p0, p1, p2, tol=FLATTEN_TOL_MM, depth=0, max_depth=24):
    """Aplati une Bézier quadratique en points (p0 exclu, p2 inclus)."""
    if depth >= max_depth or _point_line_dist(p1, p0, p2) <= tol:
        return [p2]
    p01, p12 = _mid(p0, p1), _mid(p1, p2)
    p012 = _mid(p01, p12)
    return (flatten_quadratic_bezier(p0, p01, p012, tol, depth + 1, max_depth)
            + flatten_quadratic_bezier(p012, p12, p2, tol, depth + 1, max_depth))


def svg_arc_to_center(x1, y1, rx, ry, phi_deg, large_arc_flag, sweep_flag, x2, y2):
    """Paramétrisation centrale W3C d'un arc SVG.

    Retourne (cx, cy, rx, ry, phi, theta1, delta_theta) ou None si l'arc
    est dégénéré (rayon nul ou extrémités confondues : trait droit)."""
    if abs(x1 - x2) < 1e-12 and abs(y1 - y2) < 1e-12:
        return None
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return None
    phi = math.radians(phi_deg)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    # Correction des rayons trop petits (fréquent dans les fichiers réels).
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1.0:
        s = math.sqrt(lam)
        rx *= s
        ry *= s

    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    co = math.sqrt(max(0.0, num / den))   # clamp : le flottant peut passer sous 0
    if large_arc_flag == sweep_flag:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = co * (-ry) * x1p / rx

    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    theta1 = ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = ang((x1p - cxp) / rx, (y1p - cyp) / ry,
                (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep_flag and delta > 0:
        delta -= 2 * math.pi
    elif sweep_flag and delta < 0:
        delta += 2 * math.pi
    return cx, cy, rx, ry, phi, theta1, delta


def flatten_arc(cx, cy, rx, ry, phi, theta1, delta_theta, tol=FLATTEN_TOL_MM):
    """Échantillonne un arc d'ellipse en points (theta1 exclu, fin incluse)."""
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    r = max(rx, ry, 1e-6)
    max_step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tol / r)))
    if max_step < 1e-6:
        max_step = 1e-6
    n = max(2, min(1000, int(math.ceil(abs(delta_theta) / max_step))))
    pts = []
    for k in range(1, n + 1):
        t = theta1 + delta_theta * k / n
        ct, st = math.cos(t), math.sin(t)
        pts.append((cx + rx * cos_phi * ct - ry * sin_phi * st,
                    cy + rx * sin_phi * ct + ry * cos_phi * st))
    return pts


# ==========================================================================
# C. COMPOSITION DE TRANSFORMATIONS (matrices affines 2D)
# ==========================================================================

# (a, b, c, d, e, f) représente [[a, c, e], [b, d, f], [0, 0, 1]],
# le même ordre que matrix(a,b,c,d,e,f) en SVG.
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def matrix_mul(m1, m2):
    """Produit m1 · m2 (appliquer m2 d'abord, puis m1)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + c1 * b2,
            b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1,
            b1 * e2 + d1 * f2 + f1)


def matrix_apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def matrix_translate(tx, ty=0.0):
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def matrix_scale(sx, sy=None):
    if sy is None:
        sy = sx
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)


def matrix_rotate(deg, cx=0.0, cy=0.0):
    rad = math.radians(deg)
    co, si = math.cos(rad), math.sin(rad)
    m = (co, si, -si, co, 0.0, 0.0)
    if cx or cy:
        m = matrix_mul(matrix_mul(matrix_translate(cx, cy), m),
                       matrix_translate(-cx, -cy))
    return m


def matrix_skew_x(deg):
    return (1.0, 0.0, math.tan(math.radians(deg)), 1.0, 0.0, 0.0)


def matrix_skew_y(deg):
    return (1.0, math.tan(math.radians(deg)), 0.0, 1.0, 0.0, 0.0)


_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")


def parse_transform(s):
    """Compose un attribut transform="…" en une seule matrice.

    Les opérations sont multipliées à gauche dans l'ordre du document :
    transform="A B" équivaut à A(B(point))."""
    m = IDENTITY
    if not s:
        return m
    for name, raw_args in _TRANSFORM_RE.findall(s):
        args = [float(v) for v in _NUMBER_RE.findall(raw_args)]
        if name == "matrix" and len(args) == 6:
            op = tuple(args)
        elif name == "translate" and args:
            op = matrix_translate(args[0], args[1] if len(args) > 1 else 0.0)
        elif name == "scale" and args:
            op = matrix_scale(args[0], args[1] if len(args) > 1 else None)
        elif name == "rotate" and args:
            if len(args) >= 3:
                op = matrix_rotate(args[0], args[1], args[2])
            else:
                op = matrix_rotate(args[0])
        elif name == "skewX" and args:
            op = matrix_skew_x(args[0])
        elif name == "skewY" and args:
            op = matrix_skew_y(args[0])
        else:
            continue
        m = matrix_mul(m, op)
    return m


# ==========================================================================
# D. VIEWBOX / ÉCHELLE MM, ET COULEUR DE REMPLISSAGE
# ==========================================================================

_MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "in": 25.4,
                "pt": 25.4 / 72.0, "pc": 25.4 / 6.0, "px": 25.4 / 96.0}


def parse_length_mm(s):
    """Convertit une longueur SVG (avec suffixe éventuel) en millimètres."""
    s = (s or "").strip()
    m = _NUMBER_RE.match(s)
    if not m:
        raise SvgParseError("longueur illisible : {!r}".format(s))
    value = float(m.group(0))
    unit = s[m.end():].strip().lower()
    if unit == "%":
        raise SvgParseError("longueur en % non prise en charge")
    # SANS SUFFIXE, ce sont des unités utilisateur : px CSS à 96 dpi, et
    # c'est la règle. Avec un suffixe INCONNU (« 10em », « 10qq »), le
    # repli silencieux sur px inventait une taille : on refuse, et
    # compute_svg_scale se rabat alors sur l'autre attribut.
    if unit and unit not in _MM_PER_UNIT:
        raise SvgParseError("unité de longueur inconnue : {!r}".format(unit))
    return value * _MM_PER_UNIT.get(unit, 25.4 / 96.0)


def parse_viewbox(s):
    vals = [float(v) for v in _NUMBER_RE.findall(s or "")]
    if len(vals) != 4 or vals[2] <= 0 or vals[3] <= 0:
        return None
    return tuple(vals)


def compute_svg_scale(root):
    """(échelle mm/unité, minx, miny, hauteur du viewBox ou None).

    Sans width/height (cas des exports Illustrator décoratifs), la taille
    intrinsèque vaut le viewBox en px CSS à 96 dpi -> 25.4/96 mm/unité.
    La hauteur sert à retourner l'axe Y (SVG : Y vers le bas ; FreeCAD :
    Y vers le haut) pour garder l'orientation vue dans Inkscape."""
    default = 25.4 / 96.0
    vb = parse_viewbox(root.get("viewBox"))
    if vb is None:
        # SANS viewBox, LA HAUTEUR SE LIT QUAND MÊME dans `height`, et sans
        # elle le retournement de l'axe Y n'avait aucun repère : le dessin
        # atterrissait SOUS l'origine, en Y négatif, alors que le même
        # fichier réenregistré avec un viewBox arrivait dans le quadrant
        # positif. Mesuré sur un 100 × 50 mm : y de -7,94 à -2,65 mm au lieu
        # de 42,06 à 47,35 -- deux placements pour un seul dessin, et l'un
        # des deux hors table. Le repli sur None ne vaut plus que pour un
        # SVG qui ne dit ni viewBox ni hauteur : là, on ne SAIT pas.
        try:
            hauteur = parse_length_mm(root.get("height") or "")
        except SvgParseError:
            hauteur = None
        return (default, 0.0, 0.0,
                hauteur / default if hauteur and hauteur > 0 else None)
    minx, miny, vbw, vbh = vb
    # LE PLUS PETIT DES DEUX RAPPORTS, et non le premier trouvé. Quand
    # width et height ne concordent pas avec le viewBox, le SVG applique
    # preserveAspectRatio="xMidYMid meet" par défaut : il RÉDUIT pour
    # faire tenir. Prendre celui de width -- testé en premier -- rendait
    # une échelle de 1,000 là où la norme dit 0,500 sur un viewBox 100×100
    # affiché en 100 × 50 mm : le dessin arrivait DEUX FOIS TROP GRAND, et
    # se gravait à cette taille sans qu'un mot le signale.
    rapports = []
    for attr, vb_dim in (("width", vbw), ("height", vbh)):
        raw = root.get(attr)
        if raw:
            try:
                rapports.append(parse_length_mm(raw) / vb_dim)
            except SvgParseError:
                continue
    # `> 0` N'EST PAS DÉCORATIF : `width="0"` rendait une échelle nulle, et
    # parse_svg_root divisait par elle -- ZeroDivisionError, tout l'import
    # perdu sur un seul attribut aberrant. Écarté, on retombe sur le défaut.
    rapports = [r for r in rapports if r > 0]
    if rapports:
        return min(rapports), minx, miny, vbh
    return default, minx, miny, vbh


_NAMED_COLORS = {
    "black": (0.0, 0.0, 0.0), "white": (1.0, 1.0, 1.0),
    "red": (1.0, 0.0, 0.0), "green": (0.0, 0.5, 0.0),
    "lime": (0.0, 1.0, 0.0), "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0), "cyan": (0.0, 1.0, 1.0),
    "aqua": (0.0, 1.0, 1.0), "magenta": (1.0, 0.0, 1.0),
    "fuchsia": (1.0, 0.0, 1.0), "gray": (0.5, 0.5, 0.5),
    "grey": (0.5, 0.5, 0.5), "silver": (0.75, 0.75, 0.75),
    "orange": (1.0, 0.647, 0.0), "purple": (0.5, 0.0, 0.5),
    "brown": (0.647, 0.165, 0.165), "maroon": (0.5, 0.0, 0.0),
    "navy": (0.0, 0.0, 0.5), "olive": (0.5, 0.5, 0.0),
    "teal": (0.0, 0.5, 0.5), "pink": (1.0, 0.753, 0.796),
}

_RGB_FUNC_RE = re.compile(r"rgb\s*\(\s*([^)]*)\)", re.IGNORECASE)


def parse_color(value):
    """#rgb, #rrggbb, rgb(...), ou mot-clé -> (r, g, b) en 0..1, sinon None."""
    if not value:
        return None
    v = value.strip().lower()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            try:
                return tuple(int(h[k:k + 2], 16) / 255.0 for k in (0, 2, 4))
            except ValueError:
                return None
        return None
    m = _RGB_FUNC_RE.match(v)
    if m:
        # VIRGULES OU ESPACES : « rgb(255 0 0) » est la forme moderne
        # (CSS Color 4), et le découpage sur la seule virgule en faisait un
        # seul morceau -- couleur illisible, repli sur le NOIR. Un tracé
        # rouge arrivait noir dans l'arbre.
        parts = [p for p in re.split(r"[,\s]+", m.group(1).strip()) if p]
        if len(parts) == 3:
            try:
                out = []
                for p in parts:
                    if p.endswith("%"):
                        out.append(max(0.0, min(1.0, float(p[:-1]) / 100.0)))
                    else:
                        out.append(max(0.0, min(1.0, float(p) / 255.0)))
                return tuple(out)
            except ValueError:
                return None
        return None
    return _NAMED_COLORS.get(v)


def _style_prop(style_attr, prop):
    """Extrait la valeur de `prop` d'un attribut style="a:b;c:d"."""
    for chunk in (style_attr or "").split(";"):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            if k.strip().lower() == prop:
                return v.strip()
    return None


def _propriete(elem, nom):
    """La valeur d'une propriété de présentation portée par l'élément :
    `style=` d'abord, l'attribut de même nom ensuite.

    Une valeur VIDE (`fill=""`) n'est pas une valeur : sans ce filtre, le
    `or` la confondait avec l'absence et faisait hériter du parent. La
    règle valait pour `fill` seul ; elle vaut pour toutes."""
    for v in (_style_prop(elem.get("style"), nom), elem.get(nom)):
        if v is not None and str(v).strip():
            return v
    return None


def own_fill_string(elem):
    """Remplissage propre à l'élément (style= prioritaire sur fill=)."""
    return _propriete(elem, "fill")


def own_stroke_string(elem):
    return _propriete(elem, "stroke")


# CE QUI EST MASQUÉ DANS INKSCAPE NE DOIT PAS PARTIR SUR LE BOIS.
# `display:none` et `visibility:hidden` n'étaient pas lus : un calque
# masqué -- le geste le plus ordinaire d'Inkscape, le calque de
# construction qu'on éteint avant d'exporter -- revenait entier dans le
# document et se gravait. Mesuré sur un fichier montrant UN rectangle à
# l'écran : quatre tracés importés, zéro avertissement. L'en-tête de ce
# module promet de ne jamais amputer en silence ; ajouter en silence est
# le même défaut par l'autre bout, et celui-là se paie sur la planche.
#
# LES DEUX RÈGLES NE SONT PAS LA MÊME, et les confondre ferait disparaître
# du dessin légitime : `display:none` retire l'élément ET tout son
# sous-arbre, sans recours ; `visibility` s'hérite mais un descendant peut
# la reprendre (`visibility:visible`).


def est_hors_rendu(elem):
    """`display:none` : l'élément et tout son sous-arbre sortent du rendu."""
    return (_propriete(elem, "display") or "").strip().lower() == "none"


def visibilite(elem, heritee=True):
    """`visibility` résolue pour cet élément : héritée, mais reprenable."""
    v = (_propriete(elem, "visibility") or "").strip().lower()
    if v in ("hidden", "collapse"):
        return False
    if v == "visible":
        return True
    return heritee


def resolve_fill_color(elem, inherited_fill):
    """Couleur de remplissage résolue en (r, g, b) 0..1.

    Priorité : fill propre > hérité > noir (défaut SVG). fill="none"
    retombe sur le stroke PROPRE de l'élément, sinon noir. Une valeur
    non analysable (dégradé url(#…), currentColor…) retombe sur noir."""
    raw = own_fill_string(elem)
    if raw is None:
        raw = inherited_fill
    if raw is None:
        return (0.0, 0.0, 0.0)
    if raw.strip().lower() == "none":
        stroke = own_stroke_string(elem)
        if stroke and stroke.strip().lower() != "none":
            return parse_color(stroke) or (0.0, 0.0, 0.0)
        return (0.0, 0.0, 0.0)
    return parse_color(raw) or (0.0, 0.0, 0.0)


# ==========================================================================
# D bis. LES FORMES QUI NE SONT PAS DES <path>
# ==========================================================================
# Seul <path> était lu. Les six autres formes de base du SVG -- rect,
# circle, ellipse, line, polyline, polygon -- tombaient dans la branche
# « balise inconnue mais inoffensive » et n'en ressortaient jamais : ni
# géométrie, ni avertissement. Mesuré sur un fichier portant les sept
# formes : 1 tracé importé sur 7, zéro avertissement. Un fichier tout en
# rectangles n'importait RIEN ; un fichier mixte arrivait amputé sans que
# rien ne le dise -- exactement ce que l'en-tête de ce module promet de ne
# jamais faire.
#
# On les traduit en `d`, plutôt que de les signaler : la grammaire du `d`
# est déjà là, éprouvée, et un rectangle rendu en quatre segments EST le
# rectangle. La conversion vit dans la couche pure, donc s'éprouve sans
# FreeCAD.


def _nombre_attr(elem, nom, defaut=0.0):
    """Un attribut numérique, ou le défaut s'il manque ou se lit mal."""
    brut = elem.get(nom)
    if brut is None or not str(brut).strip():
        return defaut
    brut = str(brut).strip()
    # UN POURCENTAGE N'EST PAS UNE LONGUEUR. `width="100%"` rendait 100
    # unités utilisateur : un rectangle inventé, gravé sans un mot. On rend
    # le défaut -- la forme devient dégénérée, donc COMPTÉE et annoncée,
    # ce que ce module promet de faire de tout ce qu'il ne sait pas lire.
    if brut.endswith("%"):
        return defaut
    m = _NUMBER_RE.match(brut)
    return float(m.group(0)) if m else defaut


def _d_rect(elem):
    """Un <rect>, coins arrondis compris.

    Les arrondis ne sont pas décoratifs : rendre un rectangle arrondi à
    angles vifs serait une géométrie FAUSSE, et silencieuse."""
    x, y = _nombre_attr(elem, "x"), _nombre_attr(elem, "y")
    w, h = _nombre_attr(elem, "width"), _nombre_attr(elem, "height")
    if w <= 0 or h <= 0:
        return None
    # Règle SVG : rx seul vaut ry, et réciproquement ; chacun est borné à
    # la moitié du côté correspondant.
    rx_brut, ry_brut = elem.get("rx"), elem.get("ry")
    rx = _nombre_attr(elem, "rx", -1.0)
    ry = _nombre_attr(elem, "ry", -1.0)
    if rx_brut is None and ry_brut is None:
        rx = ry = 0.0
    elif rx < 0:
        rx = ry
    elif ry < 0:
        ry = rx
    rx, ry = max(0.0, min(rx, w / 2.0)), max(0.0, min(ry, h / 2.0))
    if rx <= 0 or ry <= 0:
        return "M{} {}H{}V{}H{}Z".format(x, y, x + w, y + h, x)
    return ("M{} {}H{}A{} {} 0 0 1 {} {}V{}A{} {} 0 0 1 {} {}"
            "H{}A{} {} 0 0 1 {} {}V{}A{} {} 0 0 1 {} {}Z").format(
        x + rx, y, x + w - rx,
        rx, ry, x + w, y + ry, y + h - ry,
        rx, ry, x + w - rx, y + h, x + rx,
        rx, ry, x, y + h - ry, y + ry,
        rx, ry, x + rx, y)


def _d_ellipse(cx, cy, rx, ry):
    """Une ellipse en deux demi-arcs -- un seul arc de 360° est dégénéré."""
    if rx <= 0 or ry <= 0:
        return None
    return ("M{} {}A{} {} 0 1 0 {} {}A{} {} 0 1 0 {} {}Z"
            .format(cx - rx, cy, rx, ry, cx + rx, cy, rx, ry, cx - rx, cy))


def _points_attr(elem):
    """La liste `points` d'un <polyline>/<polygon>, en couples."""
    vals = [float(v) for v in _NUMBER_RE.findall(elem.get("points") or "")]
    return list(zip(vals[0::2], vals[1::2]))


def forme_en_d(tag, elem):
    """Traduit une forme de base en attribut `d`, ou None.

    Rend None pour tout ce qui n'est pas une forme de base, et pour une
    forme dégénérée (rayon nul, moins de deux points) -- l'appelant sait
    alors qu'il n'y a rien à importer, sans avoir à le deviner."""
    if tag == "rect":
        return _d_rect(elem)
    if tag == "circle":
        r = _nombre_attr(elem, "r")
        return _d_ellipse(_nombre_attr(elem, "cx"), _nombre_attr(elem, "cy"), r, r)
    if tag == "ellipse":
        return _d_ellipse(_nombre_attr(elem, "cx"), _nombre_attr(elem, "cy"),
                          _nombre_attr(elem, "rx"), _nombre_attr(elem, "ry"))
    if tag == "line":
        return "M{} {}L{} {}".format(
            _nombre_attr(elem, "x1"), _nombre_attr(elem, "y1"),
            _nombre_attr(elem, "x2"), _nombre_attr(elem, "y2"))
    if tag in ("polyline", "polygon"):
        pts = _points_attr(elem)
        if len(pts) < 2:
            return None
        d = "M{} {}".format(*pts[0]) + "".join("L{} {}".format(x, y) for x, y in pts[1:])
        return d + "Z" if tag == "polygon" else d
    return None


FORMES_DE_BASE = ("rect", "circle", "ellipse", "line", "polyline", "polygon")


# ==========================================================================
# E. PARCOURS DE L'ARBRE XML ET POINT D'ENTRÉE D'ANALYSE
# ==========================================================================

_SKIP_DESCEND = {"defs"}
_UNSUPPORTED = {"use", "image", "linearGradient", "radialGradient", "pattern",
                "clipPath", "mask", "filter", "text", "symbol", "marker",
                "style"}

_UNSUPPORTED_LABELS = {
    "use": "réutilisation <use>",
    "image": "image matricielle",
    "linearGradient": "dégradé linéaire",
    "radialGradient": "dégradé radial",
    "pattern": "motif <pattern>",
    "clipPath": "découpe <clipPath>",
    "mask": "masque <mask>",
    "filter": "filtre graphique",
    "text": "texte <text> (convertir en tracés dans Inkscape)",
    "symbol": "symbole <symbol>",
    "marker": "marqueur <marker>",
    "style": "feuille de style CSS (classes non résolues)",
}


def _local_tag(elem):
    """Nom de balise sans le préfixe {namespace}."""
    tag = elem.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _walk(elem, matrix, inherited_fill, tol, records, skipped,
          groupe=None, visible=True):
    for child in elem:
        tag = _local_tag(child)
        if tag in _SKIP_DESCEND:
            continue
        if tag in _UNSUPPORTED:
            skipped[tag] += 1
            continue
        if est_hors_rendu(child):
            # `display:none` emporte le sous-arbre entier : on ne descend
            # même pas, la norme ne laisse aucun descendant le reprendre.
            skipped["_masque"] += 1
            continue
        vu = visibilite(child, visible)
        child_matrix = matrix_mul(matrix, parse_transform(child.get("transform")))
        # Les formes de base deviennent un `d` : la grammaire du chemin est
        # déjà là et éprouvée, et un rectangle rendu en quatre segments EST
        # le rectangle. Une forme dégénérée (rayon nul, moins de deux
        # points) rend None -- elle est alors comptée, non perdue en
        # silence.
        d_forme = child.get("d") if tag == "path" else forme_en_d(tag, child)
        if tag in FORMES_DE_BASE and not d_forme:
            skipped["_degenere"] += 1
        if d_forme and not vu:
            skipped["_masque"] += 1
        elif d_forme:
            subpaths, warns = path_d_to_subpaths(d_forme, tol)
            if warns:
                skipped["_malformed"] += len(warns)
            transformed = []
            for sp in subpaths:
                pts = [matrix_apply(child_matrix, x, y) for x, y in sp["points"]]
                transformed.append({"points": pts, "closed": sp["closed"]})
            if transformed:
                records.append({
                    "subpaths": transformed,
                    "fill_rgb": resolve_fill_color(child, inherited_fill),
                    "svg_id": child.get("id"),
                    # Le <g> qui le contient : un fichier LightBurn traduit
                    # y met « calque_9 », un SVG d'illustrateur y met le nom
                    # de son calque. C'est le rangement voulu par celui qui
                    # a dessiné -- le perdre oblige à le refaire à la main.
                    "groupe": groupe,
                })
        else:
            # <g>, <svg> imbriqué (traité comme un simple groupe), ou
            # balise inconnue mais inoffensive : on descend toujours,
            # pour ne jamais perdre de géométrie par excès de rigueur.
            child_fill = own_fill_string(child) or inherited_fill
            _walk(child, child_matrix, child_fill, tol, records, skipped,
                  child.get("id") or groupe, vu)


def parse_svg_root(root):
    """Analyse un arbre SVG déjà chargé -> (records, warnings).

    L'axe Y est retourné (miroir dans le viewBox) : le SVG compte Y vers
    le bas, FreeCAD vers le haut -- sans ce retournement le dessin gravé
    serait en miroir vertical par rapport à ce qu'affiche Inkscape."""
    scale, minx, miny, vbh = compute_svg_scale(root)
    tol_user_units = FLATTEN_TOL_MM / abs(scale)
    if vbh is not None:
        initial = matrix_mul(matrix_scale(scale, -scale),
                             matrix_translate(-minx, -(miny + vbh)))
    else:
        initial = matrix_scale(scale, -scale)
    initial = matrix_mul(initial, parse_transform(root.get("transform")))
    records = []
    skipped = Counter()
    _walk(root, initial, own_fill_string(root), tol_user_units, records, skipped)
    warnings = []
    # preserveAspectRatio="none" DEMANDE DEUX ÉCHELLES, une par axe : le
    # dessin est alors ÉTIRÉ pour remplir le cadre. On n'en applique qu'une
    # (le plus petit rapport, la règle « meet » par défaut), donc le dessin
    # arrive au bon rapport mais pas à la taille demandée. Ce module ne
    # devine rien en silence : on le dit, comme les autres hors-périmètre.
    if (root.get("preserveAspectRatio") or "").strip().lower().startswith("none"):
        warnings.append(
            "preserveAspectRatio=\"none\" (étirement par axe) non pris en "
            "charge : le dessin garde ses proportions, sa taille peut "
            "différer du cadre annoncé")
    for tag, count in sorted(skipped.items()):
        if tag == "_malformed":
            warnings.append(
                "{} tracé(s) partiellement illisible(s) (donnée malformée)".format(count))
        elif tag == "_degenere":
            warnings.append(
                "{} forme(s) sans géométrie (rayon nul, largeur nulle…)".format(count))
        elif tag == "_masque":
            warnings.append(
                "{} élément(s) masqué(s) dans le dessin (display:none / "
                "visibility:hidden) : non importés, comme à l'écran".format(count))
        else:
            warnings.append("{} élément(s) <{}> ignoré(s) : {}".format(
                count, tag, _UNSUPPORTED_LABELS.get(tag, "non pris en charge")))
    return records, warnings


def parse_svg_file(filepath):
    return parse_svg_root(ET.parse(filepath).getroot())


def parse_svg_texte(texte):
    return parse_svg_root(ET.fromstring(texte))


# ==========================================================================
# CONSTRUCTION FREECAD (imports locaux uniquement)
# ==========================================================================

_GENERIC_ID_RE = re.compile(r"^(path|rect|circle|ellipse|polygon|polyline|g|svg)[-_]?\d*$",
                            re.IGNORECASE)



# ==========================================================================
# F. LE CHUTIER : formes à imbriquer, écriture du résultat
# ==========================================================================

def _aire_signee(points):
    aire = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        aire += x1 * y2 - x2 * y1
    return aire / 2.0


def _dedans(point, polygone):
    """Point dans polygone (rayon horizontal), pour reconnaître un trou."""
    x, y = point
    dedans = False
    n = len(polygone)
    for i in range(n):
        x1, y1 = polygone[i]
        x2, y2 = polygone[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                dedans = not dedans
    return dedans


def _nettoyer(points, tol=1e-6):
    """Ôte les doublons consécutifs et le point de fermeture, oriente
    dans le sens direct. Vide si moins de trois points restent."""
    pts = []
    for p in points:
        if not pts or abs(p[0] - pts[-1][0]) > tol or abs(p[1] - pts[-1][1]) > tol:
            pts.append((float(p[0]), float(p[1])))
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) <= tol \
            and abs(pts[0][1] - pts[-1][1]) <= tol:
        pts.pop()
    if len(pts) < 3:
        return []
    if _aire_signee(pts) < 0:
        pts.reverse()
    return pts


def _normaliser(points, trous=()):
    """Le contour nettoyé, ramené au coin bas-gauche de sa boîte en
    (0, 0), et ses trous déplacés d'autant : (contour, trous)."""
    pts = _nettoyer(points)
    if not pts:
        return (), ()
    x0 = min(p[0] for p in pts)
    y0 = min(p[1] for p in pts)

    def deplacer(anneau):
        return tuple((round(x - x0, 4), round(y - y0, 4)) for x, y in anneau)
    propres = [_nettoyer(t) for t in trous]
    return deplacer(pts), tuple(deplacer(t) for t in propres if t)


def formes_depuis_svg(chemin):
    """(formes, avertissements) lues dans le fichier ``chemin``."""
    return _formes(*parse_svg_file(chemin))


def formes_depuis_texte(texte):
    """(formes, avertissements) lues dans un SVG déjà en mémoire — la
    page web n'a pas de fichier, elle a le texte."""
    return _formes(*parse_svg_texte(texte))


def _formes(records, avertissements):
    """(formes, avertissements). Une forme : ``{"nom", "contour",
    "trous", "longueur", "largeur", "groupe"}``, le contour en mm, sens
    direct, coin bas-gauche en (0, 0), les trous déplacés d'autant."""
    formes = []
    ouverts = 0
    for index, record in enumerate(records, 1):
        fermes = [sp["points"] for sp in record["subpaths"]
                  if sp["closed"] and len(sp["points"]) >= 3]
        ouverts += sum(1 for sp in record["subpaths"] if not sp["closed"])
        # Un sous-tracé contenu dans un autre du même élément est un TROU
        # de celui-ci : on peut y imbriquer une pièce plus petite. (Un
        # trou dans un trou, l'îlot, redevient une forme à part — rare,
        # et c'est ce que le pair-impair du SVG en fait aussi.)
        parents = []
        for i, pts in enumerate(fermes):
            contenants = [j for j, autre in enumerate(fermes)
                          if j != i and _dedans(pts[0], autre)]
            parents.append(contenants)
        exterieurs = [i for i, c in enumerate(parents) if len(c) % 2 == 0]
        trous_de = {i: [] for i in exterieurs}
        for i, contenants in enumerate(parents):
            if len(contenants) % 2 == 1:
                # son parent direct : le contenant le plus petit
                parent = min(contenants,
                             key=lambda j: abs(_aire_signee(fermes[j])))
                if parent in trous_de:
                    trous_de[parent].append(fermes[i])
        base = record.get("svg_id") or "forme %d" % index
        for k, i in enumerate(exterieurs, 1):
            contour, trous = _normaliser(fermes[i], trous_de[i])
            if not contour:
                continue
            nom = base if len(exterieurs) == 1 else "%s (%d)" % (base, k)
            formes.append({
                "nom": nom,
                "contour": contour,
                "trous": trous,
                "longueur": round(max(p[0] for p in contour), 2),
                "largeur": round(max(p[1] for p in contour), 2),
                "groupe": record.get("groupe"),
            })
    if ouverts:
        avertissements.append(
            "%d tracé(s) ouvert(s) non importé(s) : une forme à découper"
            " est un contour fermé" % ouverts)
    return formes, avertissements


def _nombre(v):
    return ("%.3f" % v).rstrip("0").rstrip(".")


def _chemin_d(points, hauteur, trous=()):
    # Y retourné : le SVG compte vers le bas. Les trous suivent en
    # sous-tracés du même chemin : à la CNC ils se fraisent d'abord.
    anneaux = [points] + list(trous)
    return " ".join(
        "M" + " L".join("%s %s" % (_nombre(x), _nombre(hauteur - y))
                        for x, y in anneau) + " Z"
        for anneau in anneaux)


def ecrire_svg(chemin, debit, numero=1, titre=""):
    """Écrit :func:`svg_planche` dans le fichier ``chemin``."""
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(svg_planche(debit, numero, titre))


def svg_planche(debit, numero=1, titre=""):
    """Une planche imbriquée, à l'échelle 1 (unités mm), pour la CNC :
    le contour de la planche en bleu fin, chaque pièce en chemin fermé
    noir, son nom en <text> dans un calque à part (à masquer avant de
    générer le parcours). Une pose sans contour (un rectangle) s'écrit
    comme son rectangle. Rend le texte du SVG."""
    pl = debit.planche
    L, H = pl.longueur, pl.largeur
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="%smm" height="%smm"'
        ' viewBox="0 0 %s %s">' % (_nombre(L), _nombre(H), _nombre(L), _nombre(H)),
        '  <title>%s — planche %d : %s</title>' % (titre or "Chutier", numero,
                                                    pl.reference),
        '  <g id="planche" fill="none" stroke="#1f5fbf" stroke-width="0.3">',
        '    <rect x="0" y="0" width="%s" height="%s"/>' % (_nombre(L), _nombre(H)),
        '  </g>',
        '  <g id="pieces" fill="none" stroke="#000000" stroke-width="0.3">',
    ]
    for pose in debit.poses:
        if pose.contour:
            points, trous = pose.contour, pose.trous
        else:
            points = ((pose.x, pose.y), (pose.x + pose.dim_x, pose.y),
                      (pose.x + pose.dim_x, pose.y + pose.dim_y),
                      (pose.x, pose.y + pose.dim_y))
            trous = ()
        lignes.append('    <path id="%s-%d" fill-rule="evenodd" d="%s"/>'
                      % (pose.piece.reference.replace('"', "'"),
                         pose.exemplaire, _chemin_d(points, H, trous)))
    lignes.append('  </g>')
    lignes.append('  <g id="noms" font-family="sans-serif" font-size="6"'
                  ' fill="#555555">')
    for pose in debit.poses:
        cx = pose.x + pose.dim_x / 2
        cy = pose.y + pose.dim_y / 2
        lignes.append('    <text x="%s" y="%s" text-anchor="middle">%s %d</text>'
                      % (_nombre(cx), _nombre(H - cy),
                         pose.piece.reference.replace("&", "&amp;")
                         .replace("<", "&lt;"), pose.exemplaire))
    lignes.append('  </g>')
    lignes.append('</svg>')
    return "\n".join(lignes) + "\n"
