# -*- coding: utf-8 -*-
"""Les exemples d'accueil — sans Qt, partagés par le bureau et la page web.

Celui des formes biscornues montre l'imbrication CNC : rien que des
contours concaves, un cadre évidé et des anneaux dans lesquels d'autres
pièces peuvent se loger, sur un panneau de contreplaqué sans fil.
"""

from __future__ import annotations

import math

import optimiseur as opt


def _rond(rayon, n=24, cx=None, cy=None):
    cx = rayon if cx is None else cx
    cy = rayon if cy is None else cy
    return tuple((round(cx + rayon * math.cos(2 * math.pi * i / n), 3),
                  round(cy + rayon * math.sin(2 * math.pi * i / n), 3))
                 for i in range(n))


def _etoile(branches, grand, petit):
    pts = []
    for i in range(2 * branches):
        r = grand if i % 2 == 0 else petit
        a = math.pi / 2 + i * math.pi / branches
        pts.append((grand + r * math.cos(a), grand + r * math.sin(a)))
    return _au_coin(pts)


def _coeur(largeur):
    # Deux lobes ronds sur une pointe : le contour d'un cœur, sens direct.
    pts = []
    for i in range(30):
        t = 2 * math.pi * i / 30
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x, y))
    echelle = largeur / 32.0
    return _au_coin([(x * echelle, y * echelle) for x, y in pts])


def _croissant(rayon):
    # Un disque moins un disque décalé : concave, en un seul contour.
    ext = [(rayon * math.cos(a), rayon * math.sin(a))
           for a in (math.pi / 2 - 2 * math.pi * i / 24 for i in range(13))]
    dedans = [(rayon * 0.55 + rayon * 0.75 * math.cos(a),
               rayon * 0.75 * math.sin(a))
              for a in (-math.pi / 2 + 1.2 + (math.pi - 2 * 1.2) * i / 10
                        for i in range(11))]
    ext.reverse()
    return _au_coin(ext + dedans)


def _au_coin(pts):
    x0 = min(p[0] for p in pts)
    y0 = min(p[1] for p in pts)
    pts = [(round(x - x0, 3), round(y - y0, 3)) for x, y in pts]
    if _aire(pts) < 0:
        pts.reverse()
    return tuple(pts)


def _aire(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2.0


def _piece(nom, contour, quantite, trous=()):
    return opt.Piece(nom, max(p[0] for p in contour), max(p[1] for p in contour),
                     15, "contreplaqué", quantite, opt.FIL_INDIFFERENT,
                     contour=contour, trous=trous)


def formes_biscornues():
    """(pieces, stock, parametres) : quatorze pièces, huit formes."""
    cadre = ((0, 0), (180, 0), (180, 180), (0, 180))
    trou_cadre = ((30, 30), (150, 30), (150, 150), (30, 150))
    equerre = ((0, 0), (120, 0), (120, 30), (30, 30), (30, 120), (0, 120))
    cle = ((0, 15), (90, 15), (90, 0), (150, 0), (150, 50), (90, 50), (90, 35),
           (0, 35))
    fleche = ((0, 20), (80, 20), (80, 0), (120, 30), (80, 60), (80, 40),
              (0, 40))
    anneau = _rond(45)
    trou_anneau = _rond(25, n=18, cx=45, cy=45)
    pieces = [
        _piece("cadre", cadre, 1, trous=(trou_cadre,)),
        _piece("cœur", _coeur(100), 2),
        _piece("étoile", _etoile(5, 50, 22), 2),
        _piece("équerre", equerre, 2),
        _piece("croissant", _croissant(45), 2),
        _piece("clé", cle, 2),
        _piece("anneau", anneau, 2, trous=(trou_anneau,)),
        _piece("flèche", fleche, 1),
    ]
    stock = [
        opt.Planche("contreplaqué 1200×600", 1200, 600, 15, "contreplaqué",
                    quantite=1, fil=False),
        opt.Planche("chute contreplaqué", 400, 300, 15, "contreplaqué",
                    chute=True, fil=False),
    ]
    # Deux orientations : avec quatre, huit formes font cinq cents NFP à
    # précalculer — trop long pour un exemple d'accueil, surtout dans le
    # navigateur.
    return pieces, stock, opt.Parametres(ecart_contours=6.0, marge_bord=5.0,
                                        pas_rotation=180)
