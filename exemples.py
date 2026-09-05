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
    """Un disque moins un disque décalé : concave, en un seul contour.
    Les deux arcs se rejoignent EXACTEMENT aux deux points où les cercles
    se coupent — le premier tracé faisait déborder l'arc intérieur et le
    contour se croisait aux pointes ; shapely le réparait en silence, et
    la validation du 05/09/2026 le refuse désormais."""
    centre, petit = rayon * 0.55, rayon * 0.75
    # Intersection des deux cercles : x commun, puis les angles vus de
    # chaque centre.
    x = (rayon ** 2 - petit ** 2 + centre ** 2) / (2 * centre)
    y = math.sqrt(rayon ** 2 - x ** 2)
    phi = math.atan2(y, x)                      # sur le grand cercle
    theta = math.atan2(y, x - centre)           # sur le petit cercle
    ext = [(rayon * math.cos(a), rayon * math.sin(a))
           for a in (phi + (2 * math.pi - 2 * phi) * i / 14 for i in range(15))]
    dedans = [(centre + petit * math.cos(a), petit * math.sin(a))
              for a in ((2 * math.pi - theta) - (2 * math.pi - 2 * theta) * i / 10
                        for i in range(1, 10))]
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
    # Marge au bord de 8 : au moins le DIAMÈTRE de la fraise, sans quoi
    # l'export G-code signale à juste titre que le flanc de l'outil
    # dépasse l'arête de la planche. Le plan est le même à trois
    # millimètres près — les pièces se décalent, rien d'autre.
    return pieces, stock, opt.Parametres(ecart_contours=6.0, marge_bord=8.0,
                                        pas_rotation=180)


def volets_battants():
    """Débit réel d'une paire de volets battants (projet Christophe,
    29/08/2026) : cotes de débit en douglas 27 mm (finies + surcotes de
    corroyage) sorties du modèle FreeCAD AtelierVolets. Le couvre-joint
    (15 mm) vient d'une autre section, il n'est pas ici.

    Partagé entre le bureau et la page web depuis le 05/09/2026 — il ne
    vivait qu'au bureau, alors que le README promettait les trois
    exemples des deux côtés."""
    # 4 mm : le TRAIT_DE_SCIE du projet volets. 5 mm de tolérance
    # d'épaisseur : les planches sont du brut (30) à raboter à la cote
    # finie (27) — sans cet écart, le stock et les pièces ne se rangent
    # pas dans le même lot (par matière + épaisseur À LA TOLÉRANCE PRÈS).
    pieces = [
        opt.Piece("Lame 1 G", 1140, 119, 27, "douglas", 1),
        opt.Piece("Lame 2 G", 1140, 119, 27, "douglas", 1),
        opt.Piece("Lame 3 G", 1140, 119, 27, "douglas", 1),
        opt.Piece("Lame 4 G", 1140, 119, 27, "douglas", 1),
        opt.Piece("Lame 5 G", 1140, 105, 27, "douglas", 1),
        opt.Piece("Traverse haute G", 550, 125, 27, "douglas", 1),
        opt.Piece("Barre du Z G", 515, 105, 27, "douglas", 2),
        opt.Piece("Echarpe G", 829.6857318589343, 105, 27, "douglas", 1),
        opt.Piece("Lame 1 D", 1140, 117, 27, "douglas", 1),
        opt.Piece("Lame 2 D", 1140, 117, 27, "douglas", 1),
        opt.Piece("Lame 3 D", 1140, 117, 27, "douglas", 1),
        opt.Piece("Lame 4 D", 1140, 117, 27, "douglas", 1),
        opt.Piece("Lame 5 D", 1140, 103, 27, "douglas", 1),
        opt.Piece("Traverse haute D", 540, 125, 27, "douglas", 1),
        opt.Piece("Barre du Z D", 505, 105, 27, "douglas", 2),
        opt.Piece("Echarpe D", 824.9482377125985, 105, 27, "douglas", 1),
    ]
    stock = [
        opt.Planche("douglas 150x30 -- 3 m", 3000, 150, 30, "douglas",
                    quantite=3),
        opt.Planche("douglas 150x30 -- 4 m", 4000, 150, 30, "douglas",
                    quantite=2),
    ]
    return pieces, stock, opt.Parametres(trait_de_scie=4.0,
                                         tolerance_epaisseur=5.0)
