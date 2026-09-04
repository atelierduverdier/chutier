# -*- coding: utf-8 -*-
"""Imbrication de contours — le débit à la CNC.

Le chutier place des rectangles en coupes guillotine ; ici, des formes
quelconques (:attr:`optimiseur.Piece.contour`) se rangent sur les mêmes
planches et chutes, à la fraise, sans trait de scie : seule compte la
distance entre contours (diamètre de fraise + jeu) et au bord.

Méthode : le no-fit polygon (NFP), comme SVGnest, Deepnest et libnest2d.
Pour une pièce A déjà posée et une pièce B à poser, le NFP est la région
des positions de B où elle recouvre A : la somme de Minkowski de A et de
B retournée. Élargi de l'écart, il devient la région des positions où B
est à moins de l'écart de A. Le bord de la planche se traite de la même
façon — un cadre autour du bord utile est un obstacle comme un autre,
et son NFP laisse libre exactement l'intérieur où B tient (l'inner-fit
polygon). Les positions valides de B sont alors « la planche moins
l'union des NFP », et il n'y a plus rien à tester : les positions
candidates sont les SOMMETS de cette région, toutes valides, toutes en
contact avec un voisin ou le bord. On choisit celle qui rapproche le
plus les pièces : la « gravité » de SVGnest (deux fois la largeur plus
la hauteur de la boîte des pièces posées) ou l'aire de cette boîte, au
choix de la stratégie, puis la plus basse et la plus à gauche.

Le NFP de deux formes concaves se calcule par triangulation contrainte
(shapely ≥ 2.1) : la somme de Minkowski de deux triangles est
l'enveloppe convexe de leurs neuf sommes de sommets, et l'union de ces
enveloppes est le NFP. Mis en cache par couple (forme, angle) : trente
exemplaires de trois formes ne coûtent que quelques NFP.

Les orientations permises viennent du fil ; les défauts de la planche
(recoupes, zones écartées) sont soustraits du bord utile, la fraise
contourne. Ce qui reste : la bande à droite du dernier contour et celle
au-dessus, gardées en chute rectangulaire si elles passent les minis —
le chutier range des rectangles ; le reste est compté perte.

Les stratégies (ordres de pièces × objectifs) sont indépendantes :
elles se répartissent sur les cœurs de la machine, le meilleur au score
du chutier. Déterministe : mêmes entrées, même résultat, en parallèle
ou non.

Dépend de shapely et numpy (importés ici seulement : le cœur reste sans
dépendance tant qu'aucun contour n'est demandé). Aucun Qt.
"""

from __future__ import annotations

import multiprocessing
import os
import random
import sys

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPoint, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

import optimiseur as opt
import triangulation

EPS = 1e-6
# Les NFP se calculent sur un contour simplifié à cette flèche, puis
# élargi d'autant : le simplifié CONTIENT l'exact, donc une position
# valide pour lui l'est pour l'exact. La pose exportée garde le contour
# exact ; le surcroît d'écart, deux dixièmes au pire, se perd dans le
# diamètre de fraise.
_SIMPLIFICATION = 0.2
# Segments par quart de cercle quand un NFP s'élargit de l'écart.
_QUARTS = 4
# Les géométries PRÉCALCULÉES (enveloppes de Minkowski, NFP, cadres du
# bord) sont arrondies sur cette grille (mm) : GEOS bascule alors sur son
# noyau robuste. Sans ça, l'union de centaines d'enveloppes aux arêtes
# colinéaires lève une TopologyException — rattrapée sur le bureau, mais
# fatale en WebAssembly, où elle emportait Python et figeait la page.
# Pas dans les stratégies elles-mêmes : le noyau robuste y coûtait vingt
# fois plus dès que vingt-quatre processus le sollicitaient ensemble
# (4 s par tâche au lieu de 0,15), mesuré.
_PRECISION = 1e-3


def _robuste(g):
    return shapely.set_precision(g, _PRECISION)

OBJECTIF_GRAVITE = "gravite"     # 2 × largeur + hauteur de la boîte posée
OBJECTIF_BOITE = "boite"         # aire de la boîte posée
_OBJECTIFS = (OBJECTIF_GRAVITE, OBJECTIF_BOITE)


# ---------------------------------------------------------------------------
# Formes, variantes tournées, NFP — en cache par processus
# ---------------------------------------------------------------------------

def _cle_forme(piece: opt.Piece):
    if piece.contour:
        return ("c", piece.contour, piece.trous)
    return ("r", float(piece.longueur), float(piece.largeur))


def _polygone(piece: opt.Piece) -> Polygon:
    """La pièce comme polygone exact, trous compris, coin bas-gauche en
    (0, 0). Le NFP d'un polygone à trous laisse libre, de lui-même,
    l'intérieur d'un trou où une autre pièce tient : la triangulation
    ne couvre que la matière."""
    if piece.contour:
        p = Polygon(piece.contour, [list(t) for t in piece.trous])
        if not p.is_valid:
            p = p.buffer(0)
            if p.geom_type != "Polygon":
                p = max(p.geoms, key=lambda g: g.area)
    else:
        p = box(0, 0, piece.longueur, piece.largeur)
    return p


def _au_coin(p):
    minx, miny, _, _ = p.bounds
    return affinity.translate(p, -minx, -miny)


# shapely ≥ 2.1 triangule en C ; sinon — le navigateur, Pyodide embarquant
# shapely 2.0 — la triangulation maison fait le même travail. Un drapeau,
# pour que les tests éprouvent le repli sur un poste qui a les deux.
TRIANGULATION_SHAPELY = hasattr(shapely, "constrained_delaunay_triangles")


def _triangles(p) -> list:
    """Les triangles qui couvrent la matière de ``p`` (trous exclus)."""
    if TRIANGULATION_SHAPELY:
        t = shapely.constrained_delaunay_triangles(p)
        return [g for g in t.geoms if g.area > EPS]
    tris = triangulation.trianguler(p.exterior.coords, [r.coords for r in p.interiors])
    return [g for g in (Polygon(t) for t in tris) if g.area > EPS]


def _minkowski(a, b_retournee):
    """A ⊕ B, B déjà retournée (−B) : l'union des enveloppes convexes des
    sommes de triangles. Exact pour des polygones concaves, sans
    l'algorithme d'orbite et ses cas dégénérés."""
    ta = [np.asarray(t.exterior.coords[:-1]) for t in _triangles(a)]
    tb = [np.asarray(t.exterior.coords[:-1]) for t in _triangles(b_retournee)]
    enveloppes = []
    for pa in ta:
        for pb in tb:
            sommes = (pa[:, None, :] + pb[None, :, :]).reshape(-1, 2)
            # Sommets arrondis sur la grille ; l'union se fait avec
            # grid_size, c'est-à-dire par le noyau robuste de GEOS, sans
            # avoir à poser un modèle de précision sur chaque enveloppe
            # (14 000 appels, qui se ralentissaient dix fois entre
            # processus). L'union flottante, elle, lève une
            # TopologyException en WebAssembly — essayé, deux fois.
            sommes = np.round(sommes / _PRECISION) * _PRECISION
            enveloppes.append(MultiPoint(sommes).convex_hull)
    return _robuste(shapely.union_all(enveloppes, grid_size=_PRECISION))


# Les caches vivent au niveau du module, pas de la stratégie : un NFP
# vaut pour toutes les stratégies. Le précalcul se fait une fois, en
# parallèle, avant de lancer les stratégies ; les processus fils
# reçoivent les caches par l'initialiseur du pool (_recevoir_caches),
# quel que soit le mode de démarrage — forkserver de préférence : un
# fork depuis un processus Qt, avec ses fils C++, peut se bloquer.
_VARIANTES = {}        # (cle forme, angle) -> (exact, simplifié élargi, w, h)
_NFPS = {}             # (ecart, cle_a, cle_b) -> NFP, cle_a <= cle_b
_CADRES = {}           # (wkb du bord utile, cle_b) -> NFP du bord


def _variante(piece: opt.Piece, angle: float):
    """(clé, exact, simplifié élargi, largeur, hauteur) de la pièce
    tournée de ``angle`` degrés, coin bas-gauche de la boîte en (0, 0)."""
    cle = (_cle_forme(piece), angle)
    if cle not in _VARIANTES:
        exact = _au_coin(affinity.rotate(_polygone(piece), angle,
                                         origin=(0, 0)))
        simp = exact.simplify(_SIMPLIFICATION, preserve_topology=True)
        simp = simp.buffer(_SIMPLIFICATION, join_style="mitre",
                           mitre_limit=2.0)
        if simp.geom_type != "Polygon" or simp.is_empty:
            simp = exact.buffer(_SIMPLIFICATION, join_style="mitre")
        simp = _robuste(simp)
        if simp.geom_type != "Polygon":
            simp = max(simp.geoms, key=lambda g: g.area)
        _, _, w, h = exact.bounds
        _VARIANTES[cle] = (exact, simp, w, h)
    exact, simp, w, h = _VARIANTES[cle]
    return cle, exact, simp, w, h


def _simplifiee(cle):
    return _VARIANTES[cle][1]


def _calculer_nfp(forme_a, forme_b, ecart):
    retournee = affinity.scale(forme_b, -1, -1, origin=(0, 0))
    nfp = _minkowski(forme_a, retournee)
    if ecart > EPS:
        nfp = _robuste(nfp.buffer(ecart, quad_segs=_QUARTS))
    return nfp


def _cle_paire(cle_a, cle_b):
    return (cle_a, cle_b) if repr(cle_a) <= repr(cle_b) else (cle_b, cle_a)


class _Formes:
    """L'accès aux caches, pour un écart donné."""

    def __init__(self, params: opt.Parametres):
        self.ecart = params.ecart_contours

    def variante(self, piece, angle):
        return _variante(piece, angle)

    def simplifiee(self, cle):
        return _simplifiee(cle)

    def nfp(self, cle_a, cle_b):
        """Le NFP de B (référence : son coin bas-gauche) autour de A posée
        avec son coin en (0, 0), élargi de l'écart. NFP(B, A) est le
        symétrique central de NFP(A, B) : on n'en calcule qu'un."""
        paire = _cle_paire(cle_a, cle_b)
        cle = (self.ecart, *paire)
        if cle not in _NFPS:
            _NFPS[cle] = _calculer_nfp(_simplifiee(paire[0]),
                                       _simplifiee(paire[1]), self.ecart)
        nfp = _NFPS[cle]
        if paire != (cle_a, cle_b):
            nfp = affinity.scale(nfp, -1, -1, origin=(0, 0))
        return nfp

    def cadre(self, utile, cle_b):
        """Le NFP du bord : un cadre épais autour du bord utile (trous et
        échancrures compris) est un obstacle comme un autre. Ce qu'il
        laisse libre est exactement l'intérieur où B tient."""
        cle = (utile.wkb, cle_b)
        if cle not in _CADRES:
            _CADRES[cle] = _calculer_cadre(utile, _simplifiee(cle_b))
        return _CADRES[cle]


def _calculer_cadre(utile, forme_b):
    _, _, w, h = forme_b.bounds
    minx, miny, maxx, maxy = utile.bounds
    enveloppe = box(minx - w - 2, miny - h - 2, maxx + w + 2, maxy + h + 2)
    cadre = enveloppe.difference(utile, grid_size=_PRECISION)
    retournee = affinity.scale(forme_b, -1, -1, origin=(0, 0))
    morceaux = [_minkowski(g, retournee) for g in
                (cadre.geoms if hasattr(cadre, "geoms") else [cadre])
                if not g.is_empty and g.geom_type == "Polygon"]
    return _robuste(shapely.union_all(morceaux, grid_size=_PRECISION))


def _orientations(piece: opt.Piece, planche: opt.Planche,
                  params: opt.Parametres) -> list:
    if not planche.fil or piece.fil == opt.FIL_INDIFFERENT:
        angles = list(range(0, 360, params.pas_rotation))
    elif piece.fil == opt.FIL_LONGUEUR:
        angles = [0, 180]
    else:
        angles = [90, 270]
    if not piece.contour:
        # Un rectangle n'a que deux orientations distinctes.
        vues, garde = set(), []
        for a in angles:
            if a % 180 not in vues:
                vues.add(a % 180)
                garde.append(a)
        angles = garde
    return angles


# ---------------------------------------------------------------------------
# Une planche ouverte
# ---------------------------------------------------------------------------

def _bord_utile(pl: opt.Planche, params: opt.Parametres):
    """Le rectangle de la planche moins recoupes, défauts et marge."""
    utile = box(0, 0, pl.longueur, pl.largeur)
    if pl.recoupe_bouts > EPS:
        utile = utile.intersection(box(pl.recoupe_bouts, -1,
                                       pl.longueur - pl.recoupe_bouts,
                                       pl.largeur + 1))
    if pl.recoupe_rives > EPS:
        utile = utile.intersection(box(-1, pl.recoupe_rives,
                                       pl.longueur + 1,
                                       pl.largeur - pl.recoupe_rives))
    for x, y, dx, dy in pl.defauts:
        utile = utile.difference(box(x, y, x + dx, y + dy))
    return utile.buffer(-params.marge_bord, join_style="mitre")


class _Plateau:
    """Une planche ouverte : son bord utile, ce qui y est posé, et pour
    chaque variante de pièce déjà vue, l'union des NFP des pièces posées
    — tenue à jour à chaque pose, pour ne pas la refaire à chaque
    essai."""

    def __init__(self, planche: opt.Planche, exemplaire: int,
                 params: opt.Parametres, formes: _Formes):
        self.planche = planche
        self.exemplaire = exemplaire
        self.formes = formes
        self.poses = []
        self.polygones = []               # exacts, posés
        self.posees = []                  # (cle variante, tx, ty)
        self.utile = _bord_utile(planche, params)
        self._utile_prep = prep(self.utile)
        self.ecart = params.ecart_contours
        self.occupe = None                # union des exacts élargis
        self._bloques = {}                # cle variante -> union des NFP
        self.boite = None                 # (minx, miny, maxx, maxy) des posées

    # -- obstacles ----------------------------------------------------------

    def _cadre(self, cle_b):
        return self.formes.cadre(self.utile, cle_b)

    def _bloque(self, cle_b):
        if cle_b not in self._bloques:
            nfps = [affinity.translate(self.formes.nfp(cle_a, cle_b), tx, ty)
                    for cle_a, tx, ty in self.posees]
            self._bloques[cle_b] = unary_union(nfps) if nfps else None
        return self._bloques[cle_b]

    def libre(self, cle_b):
        """La région des positions valides du coin de B."""
        forme_b = self.formes.simplifiee(cle_b)
        _, _, w, h = forme_b.bounds
        minx, miny, maxx, maxy = self.utile.bounds
        region = box(minx - 1, miny - 1, maxx - w + 1, maxy - h + 1)
        region = region.difference(self._cadre(cle_b))
        bloque = self._bloque(cle_b)
        if bloque is not None:
            region = region.difference(bloque)
        return region

    # -- pose -----------------------------------------------------------------

    def convient(self, p) -> bool:
        """Garde-fou numérique sur le contour exact : dans le bord, sans
        recouvrement. Les sommets de la région libre sont valides par
        construction ; ceci rattrape un flottant récalcitrant."""
        if not self._utile_prep.contains(p):
            return False
        if self.occupe is not None and self.occupe.intersects(p):
            return self.occupe.intersection(p).area <= 1e-3
        return True

    def poser(self, piece, exemplaire, cle_b, exact, angle, tx, ty):
        p = affinity.translate(exact, tx, ty)
        self.polygones.append(p)
        # L'occupé sert au garde-fou : les exacts élargis d'un peu moins
        # que l'écart (le simplifié en a déjà pris deux dixièmes).
        marge = max(0.0, self.ecart - 2 * _SIMPLIFICATION)
        elargi = p.buffer(marge, join_style="mitre", mitre_limit=2.0)
        self.occupe = (elargi if self.occupe is None
                       else unary_union([self.occupe, elargi]))
        shapely.prepare(self.occupe)
        self.posees.append((cle_b, tx, ty))
        # Les unions déjà bâties s'enrichissent du NFP de la nouvelle
        # pièce ; les autres se bâtiront à la demande.
        for cle_v, bloque in list(self._bloques.items()):
            nfp = affinity.translate(self.formes.nfp(cle_b, cle_v), tx, ty)
            self._bloques[cle_v] = (nfp if bloque is None
                                    else unary_union([bloque, nfp]))
        minx, miny, maxx, maxy = p.bounds
        if self.boite is None:
            self.boite = (minx, miny, maxx, maxy)
        else:
            b = self.boite
            self.boite = (min(b[0], minx), min(b[1], miny),
                          max(b[2], maxx), max(b[3], maxy))
        self.poses.append(opt.Pose(
            piece, exemplaire, minx, miny, maxx - minx, maxy - miny,
            angle % 180 == 90,
            contour=tuple((round(x, 4), round(y, 4))
                          for x, y in p.exterior.coords[:-1]),
            angle=float(angle),
            trous=tuple(tuple((round(x, 4), round(y, 4))
                              for x, y in anneau.coords[:-1])
                        for anneau in p.interiors)))


def _sommets(region):
    geoms = region.geoms if hasattr(region, "geoms") else [region]
    pts = []
    for g in geoms:
        if g.is_empty or g.geom_type != "Polygon":
            continue
        for anneau in [g.exterior] + list(g.interiors):
            pts.extend(anneau.coords[:-1])
    return pts


def _essayer(plateau: _Plateau, piece: opt.Piece, params: opt.Parametres,
             objectif: str):
    """La meilleure pose de la pièce sur ce plateau selon l'objectif, ou
    None : (cle, exact, angle, tx, ty)."""
    formes = plateau.formes
    meilleur = None
    for angle in _orientations(piece, plateau.planche, params):
        cle, exact, _simp, w, h = formes.variante(piece, angle)
        pts = _sommets(plateau.libre(cle))
        if not pts:
            continue
        c = np.asarray(pts, dtype=float)
        if plateau.boite is None:
            bminx, bminy = c[:, 0], c[:, 1]
            bmaxx, bmaxy = c[:, 0] + w, c[:, 1] + h
        else:
            b = plateau.boite
            bminx = np.minimum(b[0], c[:, 0])
            bminy = np.minimum(b[1], c[:, 1])
            bmaxx = np.maximum(b[2], c[:, 0] + w)
            bmaxy = np.maximum(b[3], c[:, 1] + h)
        largeur, hauteur = bmaxx - bminx, bmaxy - bminy
        if objectif == OBJECTIF_BOITE:
            score = largeur * hauteur
        else:
            score = 2 * largeur + hauteur
        score = np.round(score, 3)
        ordre = np.lexsort((c[:, 0], c[:, 1], score))
        for i in ordre:
            tx, ty = float(c[i, 0]), float(c[i, 1])
            cle_score = (float(score[i]), ty, tx)
            if meilleur is not None and cle_score >= meilleur[0]:
                break
            if plateau.convient(affinity.translate(exact, tx, ty)):
                meilleur = (cle_score, cle, exact, angle, tx, ty)
                break
    if meilleur is None:
        return None
    return meilleur[1:]


# ---------------------------------------------------------------------------
# Le glouton, une stratégie
# ---------------------------------------------------------------------------

def _ouvrir(plateaux, dispo, piece, params, formes, objectif):
    """Entame la planche la moins coûteuse où la pièce loge — chutes
    d'abord, puis le prix, puis le moins de rabotage, puis la plus
    petite. Rend l'indice du plateau ouvert, ou None."""
    candidats = []
    for idx, (pl, _ex) in enumerate(dispo):
        if not opt._epaisseur_compatible(piece.epaisseur, pl.epaisseur, params):
            continue
        if not opt._admise(piece, pl):
            continue
        prio = 0 if pl.chute else 1
        cout = 0.0 if pl.chute else pl.prix
        gaspillage = (0.0 if pl.chute or pl.prix > 0
                      else max(0.0, pl.epaisseur - piece.epaisseur))
        candidats.append((prio, cout, gaspillage, pl.aire, idx))
    candidats.sort()
    for *_, idx in candidats:
        pl, ex = dispo[idx]
        plateau = _Plateau(pl, ex, params, formes)
        if _essayer(plateau, piece, params, objectif) is not None:
            dispo.pop(idx)
            plateaux.append(plateau)
            return len(plateaux) - 1
    return None


def _raison(piece, stock_unites, params):
    admises = [(pl, ex) for pl, ex in stock_unites if opt._admise(piece, pl)]
    if piece.planche and not admises:
        return opt.RAISON_PLANCHE_INCONNUE
    if opt._logerait_a_neuf(piece, admises, params):
        return (opt.RAISON_PLANCHE_PLEINE if piece.planche
                else opt.RAISON_PLUS_DE_PLACE)
    if piece.planche:
        return opt.RAISON_PLANCHE_IMPOSEE
    if opt._logerait_dims(piece, admises, params):
        return opt.RAISON_TROP_EPAISSE
    return opt.RAISON_TROP_GRANDE


def _resoudre(ordre, stock_unites, params, objectif) -> "opt._Solution":
    formes = _Formes(params)
    plateaux, dispo, non = [], list(stock_unites), []
    for piece, exemplaire in ordre:
        pose = None
        for plateau in plateaux:
            if not opt._epaisseur_compatible(piece.epaisseur,
                                             plateau.planche.epaisseur, params):
                continue
            if not opt._admise(piece, plateau.planche):
                continue
            essai = _essayer(plateau, piece, params, objectif)
            if essai is not None:
                pose = (plateau, essai)
                break
        if pose is None:
            io = _ouvrir(plateaux, dispo, piece, params, formes, objectif)
            if io is None:
                non.append((piece, exemplaire, _raison(piece, stock_unites,
                                                      params)))
                continue
            pose = (plateaux[io], _essayer(plateaux[io], piece, params,
                                           objectif))
        plateau, (cle, exact, angle, tx, ty) = pose
        plateau.poser(piece, exemplaire, cle, exact, angle, tx, ty)
    return _finaliser(plateaux, dispo, non, params)


def _chutes(plateau: _Plateau, params: opt.Parametres) -> list:
    """Les bandes rectangulaires qui restent : à droite du dernier
    contour, et au-dessus (sur la largeur restante), si elles passent
    les minis de chute."""
    pl = plateau.planche
    if not plateau.polygones:
        return []
    ecart = params.ecart_contours
    uminx, uminy, umaxx, umaxy = plateau.utile.bounds
    _, _, maxx, maxy = plateau.boite
    chutes = []
    x0 = maxx + ecart
    if umaxx - x0 > EPS:
        chutes.append(opt.ChuteCreee(umaxx - x0, umaxy - uminy, x0, uminy,
                                     pl.epaisseur, pl.matiere, pl.fil))
    y0 = maxy + ecart
    if umaxy - y0 > EPS and maxx - uminx > EPS:
        chutes.append(opt.ChuteCreee(maxx - uminx, umaxy - y0, uminx, y0,
                                     pl.epaisseur, pl.matiere, pl.fil))
    return [c for c in chutes
            if max(c.dim_x, c.dim_y) >= params.chute_mini_longueur - EPS
            and min(c.dim_x, c.dim_y) >= params.chute_mini_largeur - EPS]


def _finaliser(plateaux, dispo, non, params) -> "opt._Solution":
    debits = [opt.Debit(pt.planche, pt.exemplaire, pt.poses,
                        _chutes(pt, params), [])
              for pt in plateaux]
    comptes = {}
    for piece, _ex, raison in non:
        comptes[(piece, raison)] = comptes.get((piece, raison), 0) + 1
    non_placees = [opt.NonPlacee(p, n, raison)
                   for (p, raison), n in comptes.items()]
    return opt._Solution(debits, non_placees, dispo, [], list(non))


# ---------------------------------------------------------------------------
# Les stratégies, sur tous les cœurs
# ---------------------------------------------------------------------------

_CLES = {
    "aire": lambda u: (-u[0].aire, -max(u[0].longueur, u[0].largeur)),
    "cote": lambda u: (-max(u[0].longueur, u[0].largeur),
                       -min(u[0].longueur, u[0].largeur)),
    "hauteur": lambda u: (-u[0].largeur, -u[0].longueur),
    "boite": lambda u: (-u[0].longueur * u[0].largeur,),
}


def _strategies(unites, params):
    ordres = [sorted(unites, key=cle) for cle in _CLES.values()]
    rng = random.Random(params.graine)
    for _ in range(params.essais_melanges):
        ordre = list(unites)
        rng.shuffle(ordre)
        ordres.append(ordre)
    return [(ordre, objectif) for ordre in ordres for objectif in _OBJECTIFS]


def _tache(args):
    ordre, stock_unites, params, objectif = args
    sol = _resoudre(ordre, stock_unites, params, objectif)
    return opt._score_solution(sol, params), sol


def _emballer_caches():
    """Les caches en WKB, transportables vers un processus fils."""
    return ({cle: (e.wkb, s.wkb, w, h) for cle, (e, s, w, h)
             in _VARIANTES.items()},
            {cle: g.wkb for cle, g in _NFPS.items()},
            {cle: g.wkb for cle, g in _CADRES.items()})


def _recevoir_caches(variantes, nfps, cadres):
    """Initialiseur des fils : reconstruit les caches du parent."""
    for cle, (e, s, w, h) in variantes.items():
        _VARIANTES[cle] = (shapely.from_wkb(e), shapely.from_wkb(s), w, h)
    for cle, wkb in nfps.items():
        _NFPS[cle] = shapely.from_wkb(wkb)
    for cle, wkb in cadres.items():
        _CADRES[cle] = shapely.from_wkb(wkb)


def _tache_nfp(args):
    genre, cle, ecart = args
    if genre == "nfp":
        cle_a, cle_b = cle
        return genre, cle, _calculer_nfp(_simplifiee(cle_a), _simplifiee(cle_b),
                                         ecart).wkb
    utile_wkb, cle_b = cle
    return genre, cle, _calculer_cadre(shapely.from_wkb(utile_wkb),
                                       _simplifiee(cle_b)).wkb


def _taches_nfp(unites, stock_unites, params):
    """Calcule toutes les variantes (dans le processus parent, AVANT de
    forker : les fils en héritent) et rend la liste des NFP de couples
    et de bords qui manquent au cache."""
    pieces = list({id(p): p for p, _ in unites}.values())
    planches = list({pl: pl for pl, _ in stock_unites}.values())
    variantes = []
    for piece in pieces:
        angles = set()
        for pl in planches:
            angles.update(_orientations(piece, pl, params))
        for angle in sorted(angles):
            cle, *_ = _variante(piece, angle)
            variantes.append(cle)
    variantes = list(dict.fromkeys(variantes))
    ecart = params.ecart_contours
    taches = []
    vues = set()
    for a in variantes:
        for b in variantes:
            paire = _cle_paire(a, b)
            cle = (ecart, *paire)
            if cle in _NFPS or paire in vues:
                continue
            vues.add(paire)
            taches.append(("nfp", paire, ecart))
    bords = {}
    for pl in planches:
        utile = _bord_utile(pl, params)
        bords[utile.wkb] = utile
    for wkb in bords:
        for b in variantes:
            if (wkb, b) not in _CADRES:
                taches.append(("cadre", (wkb, b), ecart))
    return taches


def _ranger_nfp(resultats, ecart):
    for genre, cle, wkb in resultats:
        geom = shapely.from_wkb(wkb)
        if genre == "nfp":
            _NFPS[(ecart, *cle)] = geom
        else:
            _CADRES[cle] = geom


def _contexte():
    """forkserver de préférence : un fork depuis un processus Qt, avec
    ses fils C++, peut se bloquer, et Python le dénonce. Mais forkserver
    réimporte le module principal, ce qu'un script lu sur l'entrée
    standard n'a pas — fork alors, et séquentiel en dernier recours."""
    try:
        methodes = multiprocessing.get_all_start_methods()
    except (AttributeError, OSError, ValueError):
        return None                     # pas de processus ici (navigateur)
    principal = sys.modules.get("__main__")
    fichier = getattr(principal, "__file__", None)
    reimportable = bool(fichier) and os.path.exists(fichier)
    if "forkserver" in methodes and reimportable:
        return multiprocessing.get_context("forkserver")
    if "fork" in methodes:
        return multiprocessing.get_context("fork")
    return None


def _attendre(pool, asynchrone):
    """Attend le résultat d'un pool en surveillant la demande
    d'interruption : un pool.map bloquant ne la verrait qu'à la fin."""
    while not asynchrone.ready():
        asynchrone.wait(0.1)
        if opt.ANNULATION.is_set():
            pool.terminate()
            raise opt.Annulation()
    return asynchrone.get()


def _nb_processus(params, nb_taches):
    voulu = params.processus if params.processus > 0 else (os.cpu_count() or 1)
    return max(1, min(voulu, nb_taches))


def imbriquer(unites: list, stock_unites: list,
              params: opt.Parametres) -> "opt._Solution":
    """Le meilleur rangement, au score du chutier, parmi les stratégies
    (ordres de pièces × objectifs), réparties sur les cœurs. Le score
    départage, puis le rang de la stratégie : déterministe, en parallèle
    ou non."""
    strategies = _strategies(unites, params)
    taches = [(ordre, stock_unites, params, objectif)
              for ordre, objectif in strategies]
    nb = _nb_processus(params, max(len(taches), os.cpu_count() or 1))
    taches_nfp = _taches_nfp(unites, stock_unites, params)
    ecart = params.ecart_contours
    resultats = None
    contexte = _contexte() if nb > 1 and len(unites) >= 6 else None
    if contexte is not None:
        try:
            # Deux pools, dans l'ordre : les NFP d'abord ; les fils du
            # second reçoivent le cache rempli, sans rien recalculer.
            if taches_nfp:
                with contexte.Pool(min(nb, len(taches_nfp)), _recevoir_caches,
                                   _emballer_caches()) as pool:
                    _ranger_nfp(_attendre(pool, pool.map_async(_tache_nfp, taches_nfp)), ecart)
                taches_nfp = []
            with contexte.Pool(min(nb, len(taches)), _recevoir_caches,
                               _emballer_caches()) as pool:
                resultats = _attendre(pool, pool.map_async(_tache, taches))
        except (OSError, RuntimeError, ValueError, ImportError):
            resultats = None            # on repasse en séquentiel
    if resultats is None:
        if taches_nfp:
            _ranger_nfp(map(_tache_nfp, taches_nfp), ecart)
        resultats = []
        for t in taches:
            if opt.ANNULATION.is_set():
                raise opt.Annulation()
            resultats.append(_tache(t))
    meilleure = min(range(len(resultats)), key=lambda i: (resultats[i][0], i))
    return resultats[meilleure][1]
