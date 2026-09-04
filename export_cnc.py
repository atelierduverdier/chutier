# -*- coding: utf-8 -*-
"""La découpe d'une planche pour la chaîne CNC, en DXF et en LightBurn.

Le SVG (``contours_svg.svg_planche``) reste le format premier ; mais une
fraiseuse s'alimente souvent en DXF, et un laser en projet LightBurn.
Les deux s'écrivent ici, à l'échelle 1 en millimètres, Y vers le haut
comme sur la machine, sans rien d'autre que la bibliothèque standard :

- **DXF** en dialecte R12 (AC1009), le plus lu : une POLYLINE fermée par
  contour, calque ``PIECES`` pour les pièces (leurs trous compris),
  ``PLANCHE`` pour le tour de la planche, ``NOMS`` pour un TEXT au centre
  de chaque pièce — à éteindre avant de générer le parcours.
- **LightBurn** (.lbrn) : un ``<Shape Type="Path">`` par contour, sommets
  ``V`` et segments ``L`` comme LaserAtelier les relit, deux calques de
  coupe (0 les pièces, 1 le tour de planche, à désactiver dans
  LightBurn si on ne veut pas le brûler).

Une pose sans contour (un rectangle) s'écrit comme son rectangle.
"""

from __future__ import annotations

from xml.sax.saxutils import escape


def _nombre(v: float) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".") or "0"


def _anneaux(pose):
    """Les contours fermés d'une pose : l'extérieur, puis ses trous."""
    if pose.contour:
        return [pose.contour] + list(pose.trous)
    return [((pose.x, pose.y), (pose.x + pose.dim_x, pose.y),
             (pose.x + pose.dim_x, pose.y + pose.dim_y),
             (pose.x, pose.y + pose.dim_y))]


# -- DXF ---------------------------------------------------------------------

def _dxf_polyline(points, calque: str) -> list:
    lignes = ["0", "POLYLINE", "8", calque, "66", "1", "70", "1",
              "10", "0", "20", "0", "30", "0"]
    for x, y in points:
        lignes += ["0", "VERTEX", "8", calque, "10", _nombre(x),
                   "20", _nombre(y), "30", "0"]
    lignes += ["0", "SEQEND", "8", calque]
    return lignes


def dxf_planche(debit, numero: int = 1, titre: str = "") -> str:
    """Le DXF (R12) d'une planche débitée."""
    pl = debit.planche
    lignes = [
        "999", "%s — planche %d : %s (chutier, mm)" % (titre or "Chutier", numero,
                                                       pl.reference),
        "0", "SECTION", "2", "HEADER",
        "9", "$ACADVER", "1", "AC1009",
        "9", "$INSUNITS", "70", "4",
        "9", "$EXTMIN", "10", "0", "20", "0", "30", "0",
        "9", "$EXTMAX", "10", _nombre(pl.longueur), "20", _nombre(pl.largeur),
        "30", "0",
        "0", "ENDSEC",
        "0", "SECTION", "2", "TABLES",
        "0", "TABLE", "2", "LAYER", "70", "3",
        "0", "LAYER", "2", "PLANCHE", "70", "0", "62", "5", "6", "CONTINUOUS",
        "0", "LAYER", "2", "PIECES", "70", "0", "62", "7", "6", "CONTINUOUS",
        "0", "LAYER", "2", "NOMS", "70", "0", "62", "8", "6", "CONTINUOUS",
        "0", "ENDTAB",
        "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
    ]
    lignes += _dxf_polyline(((0, 0), (pl.longueur, 0), (pl.longueur, pl.largeur),
                             (0, pl.largeur)), "PLANCHE")
    for pose in debit.poses:
        for anneau in _anneaux(pose):
            lignes += _dxf_polyline(anneau, "PIECES")
        hauteur = max(2.0, min(6.0, pose.dim_y * 0.2))
        lignes += ["0", "TEXT", "8", "NOMS",
                   "10", _nombre(pose.x + pose.dim_x / 2),
                   "20", _nombre(pose.y + pose.dim_y / 2), "30", "0",
                   "40", _nombre(hauteur), "72", "1", "73", "2",
                   "11", _nombre(pose.x + pose.dim_x / 2),
                   "21", _nombre(pose.y + pose.dim_y / 2), "31", "0",
                   "1", "%s %d" % (pose.piece.reference, pose.exemplaire)]
    lignes += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(lignes) + "\n"


# -- LightBurn ----------------------------------------------------------------

def _lbrn_chemin(points, indice_coupe: int) -> str:
    n = len(points)
    sommets = "".join("V%s %s" % (_nombre(x), _nombre(y)) for x, y in points)
    segments = "".join("L%d %d" % (i, (i + 1) % n) for i in range(n))
    return ('  <Shape Type="Path" CutIndex="%d">\n'
            '    <XForm>1 0 0 1 0 0</XForm>\n'
            '    <VertList>%s</VertList>\n'
            '    <PrimList>%s</PrimList>\n'
            '  </Shape>' % (indice_coupe, sommets, segments))


def lightburn_planche(debit, numero: int = 1, titre: str = "") -> str:
    """Le projet LightBurn (.lbrn) d'une planche débitée : calque 0 les
    pièces, calque 1 le tour de la planche — un repère, à désactiver
    avant de lancer si on ne veut pas le découper."""
    pl = debit.planche
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<LightBurnProject AppVersion="1.4.00" FormatVersion="1"'
        ' MaterialHeight="0" MirrorX="False" MirrorY="False">',
        '  <!-- %s — planche %d : %s (chutier, mm, Y vers le haut) -->'
        % (escape(titre or "Chutier"), numero, escape(pl.reference)),
        '  <CutSetting type="Cut">',
        '    <index Value="0"/>',
        '    <name Value="Pièces"/>',
        '    <priority Value="0"/>',
        '  </CutSetting>',
        '  <CutSetting type="Cut">',
        '    <index Value="1"/>',
        '    <name Value="Tour de planche (repère)"/>',
        '    <priority Value="1"/>',
        '  </CutSetting>',
        _lbrn_chemin(((0, 0), (pl.longueur, 0), (pl.longueur, pl.largeur),
                      (0, pl.largeur)), 1),
    ]
    for pose in debit.poses:
        for anneau in _anneaux(pose):
            lignes.append(_lbrn_chemin(anneau, 0))
    lignes.append('</LightBurnProject>')
    return "\n".join(lignes) + "\n"


FORMATS = {
    "svg": ("SVG (*.svg)", ".svg"),
    "dxf": ("DXF (*.dxf)", ".dxf"),
    "lbrn": ("LightBurn (*.lbrn)", ".lbrn"),
}


def decoupe(format_: str, debit, numero: int = 1, titre: str = "") -> str:
    """Le texte de la découpe dans le format demandé (svg, dxf, lbrn)."""
    if format_ == "svg":
        import contours_svg
        return contours_svg.svg_planche(debit, numero, titre)
    if format_ == "dxf":
        return dxf_planche(debit, numero, titre)
    if format_ == "lbrn":
        return lightburn_planche(debit, numero, titre)
    raise ValueError("format de découpe inconnu : %s" % format_)
