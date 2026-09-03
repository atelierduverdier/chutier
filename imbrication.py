# -*- coding: utf-8 -*-
"""Imbrication de contours — le débit à la CNC.

Le chutier place des rectangles en coupes guillotine ; ici, des formes
quelconques (:attr:`optimiseur.Piece.contour`) se rangent sur les mêmes
planches et chutes, à la fraise, sans trait de scie : seule compte la
distance entre contours (diamètre de fraise + jeu) et au bord.

Méthode : un glouton « bas-gauche » rejoué sous plusieurs ordres de
pièces, le meilleur au score du chutier. Pour chaque exemplaire, dans
chaque orientation permise par son fil, les positions candidates sont
les contacts sommet à sommet entre la pièce et ce qui est déjà posé
(l'occupé, élargi de l'écart) ou le bord utile de la planche (rétréci
de la marge) ; elles s'essaient dans l'ordre du plus bas puis du plus à
gauche, la première valide gagne. Un test de validité est un test
shapely : contenu dans le bord utile, disjoint de l'occupé. Les défauts
de la planche (recoupes, zones écartées) sont simplement soustraits du
bord utile — pas de coupe à passer, la fraise contourne.

Ce qui reste : la bande à droite du dernier contour et celle au-dessus,
gardées en chute rectangulaire si elles passent les minis — le chutier
range des rectangles ; le reste du bois est compté perte, même s'il en
reste des morceaux biscornus.

Dépend de shapely (importé ici seulement : le cœur reste sans
dépendance tant qu'aucun contour n'est demandé). Aucun Qt.
"""

from __future__ import annotations

import random

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

import optimiseur as opt

EPS = 1e-6
# En dessous, deux flottants sont le même point : les sommets doublons
# n'apportent aucune position candidate nouvelle.
_GRILLE = 0.01
# Les tests de collision se font sur un contour simplifié à cette flèche
# (un rond aplati à 0,02 mm arrive en 88 points, autant de positions
# candidates par sommet d'en face). La pose exportée garde le contour
# exact ; l'erreur, un cinquième de millimètre au pire, se perd dans
# l'écart de fraise.
_SIMPLIFICATION = 0.2
# Taille des blocs de candidats pré-filtrés d'un coup.
_BLOC = 512


def _polygone(piece: opt.Piece) -> Polygon:
    """La pièce comme polygone exact, coin bas-gauche en (0, 0)."""
    if piece.contour:
        p = Polygon(piece.contour)
        if not p.is_valid:
            p = p.buffer(0)
    else:
        p = box(0, 0, piece.longueur, piece.largeur)
    return p


def _simplifie(p: Polygon) -> Polygon:
    q = p.simplify(_SIMPLIFICATION, preserve_topology=True)
    return q if q.is_valid and not q.is_empty else p


def _au_coin(p: Polygon) -> Polygon:
    minx, miny, _, _ = p.bounds
    return affinity.translate(p, -minx, -miny)


def _orientations(piece: opt.Piece, planche: opt.Planche,
                  params: opt.Parametres) -> list:
    if not planche.fil or piece.fil == opt.FIL_INDIFFERENT:
        return list(range(0, 360, params.pas_rotation))
    if piece.fil == opt.FIL_LONGUEUR:
        return [0, 180]
    return [90, 270]


class _Plateau:
    """Une planche ouverte : son bord utile, ce qui y est posé."""

    def __init__(self, planche: opt.Planche, exemplaire: int,
                 params: opt.Parametres):
        self.planche = planche
        self.exemplaire = exemplaire
        self.poses = []
        pl = planche
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
        # La marge au bord rétrécit le bord utile ; un contour posé au
        # ras de ce bord rétréci est donc à `marge_bord` du vrai bord.
        self.utile = utile.buffer(-params.marge_bord, join_style="mitre")
        # Préparée EN PLACE : contains_xy / intersects_xy préparent sinon
        # la géométrie à chaque appel — 0,4 ms par bloc de candidats,
        # plus que le test lui-même.
        shapely.prepare(self.utile)
        self._utile_prep = prep(self.utile)
        self.occupe = None
        self._occupe_prep = None
        self._sommets_occupe = []
        self.polygones = []
        self.ecart = params.ecart_contours

    def sommets(self):
        return list(self._sommets_bord()) + self._sommets_occupe

    def _sommets_bord(self):
        if self.utile.is_empty:
            return []
        geoms = (self.utile.geoms if hasattr(self.utile, "geoms")
                 else [self.utile])
        for g in geoms:
            for anneau in [g.exterior] + list(g.interiors):
                for x, y in anneau.coords[:-1]:
                    yield (x, y)

    def survivants(self, candidats, coins):
        """``candidats`` : tableau (N, 2) ; rend les couples retenus."""
        if len(candidats) == 0:
            return []
        c = candidats                                      # (N, 2)
        k = np.asarray(coins, dtype=float)                 # (V, 2)
        pts = (c[:, None, :] + k[None, :, :]).reshape(-1, 2)
        # intersects, pas contains : un sommet posé AU RAS du bord utile
        # (le cas du premier coin, en bas à gauche) est sur la frontière,
        # que contains exclut — et plus rien ne se posait.
        dedans = shapely.intersects_xy(self.utile, pts[:, 0], pts[:, 1])
        ok = dedans.reshape(len(c), -1).all(axis=1)
        if self.occupe is not None:
            dehors = ~shapely.contains_xy(self.occupe, pts[:, 0], pts[:, 1])
            ok &= dehors.reshape(len(c), -1).all(axis=1)
        return [(float(c[i, 0]), float(c[i, 1])) for i in np.flatnonzero(ok)]

    def convient(self, p: Polygon) -> bool:
        if not self._utile_prep.contains(p):
            return False
        if self._occupe_prep is not None and self._occupe_prep.intersects(p):
            # Toucher l'élargi par un sommet ou une arête, c'est être
            # exactement à l'écart de la pièce voisine : permis. Seul un
            # recouvrement de surface interdit. (intersects seul refusait
            # tout contact, et les pièces fuyaient aux quatre coins.)
            return self.occupe.intersection(p).area <= 1e-6
        return True

    def poser(self, piece, exemplaire, p: Polygon, angle: float):
        self.polygones.append(p)
        # L'occupé est l'union des pièces élargies de l'écart : un contour
        # posé au ras de l'occupé est à `ecart` de la pièce voisine. Le
        # coin en onglet (mitre) garde peu de sommets, donc peu de
        # positions candidates à essayer.
        elargi = p.buffer(self.ecart, join_style="mitre", mitre_limit=2.0)
        self.occupe = (elargi if self.occupe is None
                       else unary_union([self.occupe, elargi]))
        shapely.prepare(self.occupe)
        self._occupe_prep = prep(self.occupe)
        geoms = (self.occupe.geoms if hasattr(self.occupe, "geoms")
                 else [self.occupe])
        self._sommets_occupe = [
            (x, y) for g in geoms
            for anneau in [g.exterior] + list(g.interiors)
            for x, y in anneau.coords[:-1]]
        minx, miny, maxx, maxy = p.bounds
        self.poses.append(opt.Pose(
            piece, exemplaire, minx, miny, maxx - minx, maxy - miny,
            angle % 180 == 90,
            contour=tuple((round(x, 4), round(y, 4))
                          for x, y in p.exterior.coords[:-1]),
            angle=float(angle)))

    def rendement(self) -> float:
        return sum(q.area for q in self.polygones) / max(self.planche.aire, EPS)


def _essayer(plateau: _Plateau, piece: opt.Piece, params: opt.Parametres):
    """La meilleure position (la plus basse, puis la plus à gauche) de la
    pièce sur ce plateau, ou None : (polygone posé, angle)."""
    exact = _polygone(piece)
    base = _simplifie(exact)
    utile = plateau.utile
    if utile.is_empty:
        return None
    uminx, uminy, umaxx, umaxy = utile.bounds
    sommets = plateau.sommets()
    meilleur = None
    for angle in _orientations(piece, plateau.planche, params):
        tourne = affinity.rotate(base, angle, origin=(0, 0))
        q = _au_coin(tourne)
        qminx, qminy, qmaxx, qmaxy = q.bounds
        if qmaxx > umaxx - uminx + EPS or qmaxy > umaxy - uminy + EPS:
            continue
        coins = list(q.exterior.coords[:-1])
        ordonnes = _candidats(sommets, coins, (uminx, uminy, umaxx, umaxy),
                              (qmaxx, qmaxy))
        # Pré-filtre vectoriel par blocs, dans l'ordre du plus bas : tous
        # les sommets de la pièce translatée doivent être dans le bord
        # utile et hors de l'occupé (sa frontière compte dehors : toucher
        # est permis). Nécessaire, pas suffisant — une arête peut encore
        # croiser — d'où l'essai exact sur les survivants. Par blocs,
        # parce que seul le premier valide compte : pré-filtrer les
        # vingt mille candidats d'une planche bien remplie coûtait plus
        # que d'en essayer deux cents.
        trouve = None
        for debut in range(0, len(ordonnes), _BLOC):
            bloc = ordonnes[debut:debut + _BLOC]
            if meilleur is not None and (float(bloc[0, 1]), float(bloc[0, 0])) >= meilleur[0]:
                break
            for tx, ty in plateau.survivants(bloc, coins):
                if meilleur is not None and (ty, tx) >= meilleur[0]:
                    break
                p = affinity.translate(q, tx, ty)
                if plateau.convient(p):
                    trouve = (tx, ty)
                    break
            if trouve is not None:
                break
        if trouve is not None:
            tx, ty = trouve
            # La pose garde le contour EXACT, déplacé du même vecteur
            # que le simplifié (même rotation, même mise au coin).
            bminx, bminy, _, _ = tourne.bounds
            place = affinity.translate(
                affinity.rotate(exact, angle, origin=(0, 0)),
                tx - bminx, ty - bminy)
            meilleur = ((ty, tx), place, angle)
    if meilleur is None:
        return None
    return meilleur[1], meilleur[2]


def _candidats(sommets, coins, bornes, taille):
    """Les positions à essayer, du plus bas puis du plus à gauche.

    Contacts sommet à sommet entre la pièce et l'occupé ou le bord, ET
    chaque abscisse de contact projetée au sol, chaque ordonnée projetée
    au mur gauche — même quand le contact d'origine sort de la planche :
    « posée au sol juste à droite de la cale » vient du coin de l'élargi
    de la cale qui, lui, est SOUS le sol. Sans cette projection, la
    position n'existait pas et les pièces s'égaillaient aux coins.
    Vectorisé : une boucle Python sur sommets × coins coûtait vingt
    millions de tours sur soixante pièces."""
    uminx, uminy, umaxx, umaxy = bornes
    qmaxx, qmaxy = taille
    s = np.asarray(sommets, dtype=float)
    k = np.asarray(coins, dtype=float)
    t = (s[:, None, :] - k[None, :, :]).reshape(-1, 2)
    t = np.round(t / _GRILLE) * _GRILLE
    ok_x = (t[:, 0] >= uminx - EPS) & (t[:, 0] + qmaxx <= umaxx + EPS)
    ok_y = (t[:, 1] >= uminy - EPS) & (t[:, 1] + qmaxy <= umaxy + EPS)
    xs = np.unique(np.concatenate([t[ok_x, 0], [uminx]]))
    ys = np.unique(np.concatenate([t[ok_y, 1], [uminy]]))
    contacts = t[ok_x & ok_y]
    sol = np.column_stack([xs, np.full(len(xs), uminy)])
    mur = np.column_stack([np.full(len(ys), uminx), ys])
    tous = np.concatenate([contacts, sol, mur])
    # Dédoublonner ET trier (y puis x) en un seul appel : unique() sur
    # un complexe dont la partie réelle est y — quatre fois plus vite
    # que unique(axis=0) suivi d'un lexsort, sur 18 000 candidats.
    cle = np.unique(tous[:, 1] + 1j * tous[:, 0])
    return np.column_stack([cle.imag, cle.real])


def _ouvrir(plateaux, dispo, piece, params):
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
        plateau = _Plateau(pl, ex, params)
        if _essayer(plateau, piece, params) is not None:
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


def _resoudre(ordre, stock_unites, params) -> "opt._Solution":
    plateaux, dispo, non = [], list(stock_unites), []
    for piece, exemplaire in ordre:
        pose = None
        for plateau in plateaux:
            if not opt._epaisseur_compatible(piece.epaisseur,
                                             plateau.planche.epaisseur, params):
                continue
            if not opt._admise(piece, plateau.planche):
                continue
            essai = _essayer(plateau, piece, params)
            if essai is not None:
                pose = (plateau, essai)
                break
        if pose is None:
            io = _ouvrir(plateaux, dispo, piece, params)
            if io is None:
                non.append((piece, exemplaire, _raison(piece, stock_unites,
                                                      params)))
                continue
            pose = (plateaux[io], _essayer(plateaux[io], piece, params))
        plateau, (p, angle) = pose
        plateau.poser(piece, exemplaire, p, angle)
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
    tous = unary_union(plateau.polygones)
    _, _, maxx, maxy = tous.bounds
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


_CLES = {
    "aire": lambda u: (-u[0].aire, -max(u[0].longueur, u[0].largeur)),
    "cote": lambda u: (-max(u[0].longueur, u[0].largeur),
                       -min(u[0].longueur, u[0].largeur)),
    "hauteur": lambda u: (-u[0].largeur, -u[0].longueur),
    "boite": lambda u: (-u[0].longueur * u[0].largeur,),
}


def imbriquer(unites: list, stock_unites: list,
              params: opt.Parametres) -> "opt._Solution":
    """Le meilleur rangement, au score du chutier, parmi les ordres de
    pièces essayés (les quatre tris, puis ``essais_melanges`` ordres
    tirés au hasard à graine fixe). Déterministe."""
    ordres = [sorted(unites, key=cle) for cle in _CLES.values()]
    rng = random.Random(params.graine)
    # Un ordre imbriqué coûte cent fois un passage guillotine : un quart
    # des essais de mélange réglés, pas tous.
    for _ in range(params.essais_melanges // 4):
        ordre = list(unites)
        rng.shuffle(ordre)
        ordres.append(ordre)
    meilleure = None
    for ordre in ordres:
        sol = _resoudre(ordre, stock_unites, params)
        score = opt._score_solution(sol, params)
        if meilleure is None or score < meilleure[0]:
            meilleure = (score, sol)
    return meilleure[1]
