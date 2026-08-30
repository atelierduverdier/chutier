# -*- coding: utf-8 -*-
"""Optimiseur de débit — le cœur du « chutier ».

Place des pièces rectangulaires dans un stock de planches et de chutes,
en coupes guillotine (chaque trait traverse le morceau de bord à bord),
en respectant le trait de scie et le sens du fil. Rend le plan complet :
poses, traits de coupe, chutes restantes réutilisables, pertes.

Aucune dépendance : bibliothèque standard seulement. JAMAIS de Qt ici —
ce module est la couche géométrie, l'interface viendra au-dessus.

Unités : millimètres partout, surfaces en mm².

Conventions :
- La longueur d'une planche court LE LONG DU FIL. Dans les coordonnées
  d'une planche, x suit la longueur (donc le fil), y suit la largeur,
  origine au coin bas-gauche.
- Une pièce déclare où son fil doit courir : FIL_LONGUEUR (défaut),
  FIL_LARGEUR, ou FIL_INDIFFERENT (rotation libre). Sur un panneau sans
  fil (Planche.fil = False), toute pièce peut pivoter.
- Un trait de coupe est posé au ras de la pièce ; la lame mange la bande
  [position, position + trait_de_scie], du côté opposé à la pièce.
- Une chute créée garde la convention : dim_x court le long du fil de la
  planche d'origine. `ChuteCreee.en_planche()` la reconvertit en stock.

Le solveur est un glouton guillotine (meilleur ajustement) rejoué sous
plusieurs stratégies (ordres de pièces, règles de découpe, chutes
d'abord ou non) ; la meilleure solution gagne au score lexicographique :
  1. le moins de pièces non placées ;
  2. le moins de surface de planches NEUVES entamées (déstockage d'abord) ;
  3. le moins de pertes (sciure + rebuts sous les minis de chute) ;
  4. la plus grande chute subsistante la plus grande possible.
Tout est déterministe : mêmes entrées, même graine → même résultat.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

VERSION = "0.1.0"

EPS = 1e-6

FIL_LONGUEUR = "longueur"
FIL_LARGEUR = "largeur"
FIL_INDIFFERENT = "indifferent"
_FILS_VALIDES = (FIL_LONGUEUR, FIL_LARGEUR, FIL_INDIFFERENT)

DELIGNAGE = "delignage"      # trait à y constant, le long du fil
TRONCONNAGE = "tronconnage"  # trait à x constant, en travers du fil

RAISON_INCOMPATIBLE = "aucune planche de cette matière dans le stock"
RAISON_TROP_GRANDE = "trop grande pour les formats du stock (fil compris)"
RAISON_TROP_EPAISSE = "aucune planche assez épaisse pour cette pièce"
RAISON_PLUS_DE_PLACE = "plus de place dans le stock fourni"


# ---------------------------------------------------------------------------
# Entrées
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Piece:
    """Une pièce à débiter (``quantite`` exemplaires identiques).

    ``composable`` : trop large pour tout brut du stock, cette pièce
    peut se reconstituer en collant plusieurs lames côte à côte (ou en
    tenon-rainure) plutôt que de rester non placée — voir
    :func:`_decomposer_composables`. Ne s'applique qu'à la largeur (le
    sens du fil ne change pas d'une lame à l'autre) ; sans effet sur une
    pièce ``FIL_LARGEUR``, ni sur une pièce qui logerait déjà telle
    quelle (moins de joints, plus solide).
    """

    reference: str
    longueur: float
    largeur: float
    epaisseur: float = 0.0
    matiere: str = ""
    quantite: int = 1
    fil: str = FIL_LONGUEUR
    composable: bool = False

    @property
    def aire(self) -> float:
        return self.longueur * self.largeur


@dataclass(frozen=True)
class Planche:
    """Un rectangle de stock — planche neuve ou chute réinjectée.

    ``longueur`` court le long du fil. ``fil = False`` décrit un panneau
    sans fil (MDF, contreplaqué pris comme tel) : rotation libre dedans.

    ``illimite`` : un profil de CATALOGUE (une section qu'on peut acheter),
    pas des planches déjà en atelier — ``quantite`` ne borne alors plus
    rien, le solveur en prend autant que le débit en demande. Combiné à
    plusieurs profils, il choisit lui-même dans lequel tailler chaque
    pièce ; :meth:`Resultat.achats` compte ensuite, par profil, combien en
    acheter. Sans effet sur une chute (déjà possédée, jamais à acheter).

    ``prix`` : coût d'UNE planche à ces cotes (ce que le marchand facture
    pour une longueur de ``longueur``), pas un prix au mètre. Départage le
    choix entre plusieurs profils illimités par le coût réel plutôt que
    par la seule surface neuve entamée — mettre un prix à zéro (le
    défaut) revient à ne pas en tenir compte pour cette planche. À
    renseigner pour TOUS les profils comparés : un mélange de planches
    prisées et non prisées dans le même choix n'a pas de sens.
    """

    reference: str
    longueur: float
    largeur: float
    epaisseur: float = 0.0
    matiere: str = ""
    quantite: int = 1
    chute: bool = False
    fil: bool = True
    illimite: bool = False
    prix: float = 0.0

    @property
    def aire(self) -> float:
        return self.longueur * self.largeur


@dataclass(frozen=True)
class Parametres:
    """Réglages du débit.

    - ``trait_de_scie`` : largeur de matière mangée par chaque coupe.
    - ``chute_mini_longueur`` / ``chute_mini_largeur`` : un reste n'est
      compté chute réutilisable que si son grand côté et son petit côté
      atteignent ces seuils ; en dessous il part dans les pertes.
    - ``surcote_longueur`` / ``surcote_largeur`` : marge de recoupe
      ajoutée à chaque pièce au débit (les dimensions posées la
      comprennent, la pièce garde ses cotes nominales).
    - ``tolerance_epaisseur`` : marge de mesure sur la règle « la planche
      doit être au moins aussi épaisse que la pièce » (le brut se rabote
      à la cote voulue, jamais l'inverse) ; ne sert qu'à absorber le
      bruit de mesure (18,0 mesuré contre 18,05 demandé), pas à faire
      passer une pièce plus épaisse que le stock.
    - ``surcote_joint`` : largeur perdue à chaque collage entre deux
      lames d'une pièce ``composable`` (équerrage des deux rives à
      coller) — ne joue aucun rôle pour une pièce qui loge d'un seul
      tenant.
    - ``essais_melanges`` : nombre d'ordres de pièces tirés au hasard en
      plus des stratégies déterministes (0 pour s'en passer) ;
      ``graine`` fixe le hasard, le résultat reste reproductible.
    """

    trait_de_scie: float = 3.0
    chute_mini_longueur: float = 200.0
    chute_mini_largeur: float = 40.0
    surcote_longueur: float = 0.0
    surcote_largeur: float = 0.0
    tolerance_epaisseur: float = 0.1
    surcote_joint: float = 3.0
    essais_melanges: int = 8
    graine: int = 0


# ---------------------------------------------------------------------------
# Sorties
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pose:
    """Un exemplaire de pièce posé sur une planche.

    ``dim_x`` / ``dim_y`` sont les dimensions réellement débitées
    (surcote comprise) ; ``pivotee`` vaut True si la longueur de la
    pièce est posée sur y.
    """

    piece: Piece
    exemplaire: int
    x: float
    y: float
    dim_x: float
    dim_y: float
    pivotee: bool

    @property
    def aire(self) -> float:
        return self.dim_x * self.dim_y


@dataclass(frozen=True)
class Coupe:
    """Un trait de scie. ``position`` est la coordonnée constante du
    trait (y pour un délignage, x pour un tronçonnage), posée au ras de
    la pièce ; la lame mange [position, position + trait_de_scie]. Le
    trait s'étend de ``de`` à ``a`` sur l'autre axe. Les coupes d'une
    planche, prises dans l'ordre de ``ordre``, sont exécutables telles
    quelles : chaque trait traverse de bord à bord le morceau courant.
    """

    sens: str
    position: float
    de: float
    a: float
    ordre: int


@dataclass(frozen=True)
class ChuteCreee:
    """Un rectangle restant réutilisable, en coordonnées de sa planche.

    ``dim_x`` court le long du fil de la planche d'origine — une chute
    peut donc avoir dim_x < dim_y, c'est physique, pas une erreur.
    """

    dim_x: float
    dim_y: float
    x: float
    y: float
    epaisseur: float
    matiere: str
    fil: bool

    @property
    def aire(self) -> float:
        return self.dim_x * self.dim_y

    def en_planche(self, reference: str) -> Planche:
        """La chute prête à retourner au stock."""
        return Planche(reference, self.dim_x, self.dim_y, self.epaisseur,
                       self.matiere, quantite=1, chute=True, fil=self.fil)


@dataclass
class Debit:
    """Une planche du stock entamée, avec son plan de découpe."""

    planche: Planche
    exemplaire: int
    poses: list = field(default_factory=list)
    chutes: list = field(default_factory=list)
    coupes: list = field(default_factory=list)

    @property
    def surface(self) -> float:
        return self.planche.aire

    @property
    def surface_poses(self) -> float:
        return sum(p.aire for p in self.poses)

    @property
    def surface_chutes(self) -> float:
        return sum(c.aire for c in self.chutes)

    @property
    def perte(self) -> float:
        """Sciure + rebuts sous les minis de chute (par conservation)."""
        return self.surface - self.surface_poses - self.surface_chutes

    @property
    def rendement(self) -> float:
        return self.surface_poses / self.surface if self.surface > EPS else 0.0


@dataclass(frozen=True)
class NonPlacee:
    piece: Piece
    exemplaires: int
    raison: str


@dataclass(frozen=True)
class Bilan:
    nb_demandees: int
    nb_posees: int
    nb_non_placees: int
    nb_planches_entamees: int
    nb_chutes_consommees: int
    surface_pieces: float
    surface_entamee: float
    surface_neuve_entamee: float
    surface_chutes_creees: float
    surface_perdue: float
    rendement: float


@dataclass(frozen=True)
class Achat:
    """Combien acheter d'un profil de catalogue réellement entamé.

    ``prix`` reprend ``Planche.prix`` (coût d'UNE planche, pas au
    mètre) ; ``nombre * prix`` donne le coût de ce profil."""

    reference: str
    longueur: float
    largeur: float
    epaisseur: float
    matiere: str
    nombre: int
    prix: float = 0.0


@dataclass
class Resultat:
    debits: list
    non_placees: list
    bilan: Bilan

    @property
    def chutes_creees(self) -> list:
        return [c for d in self.debits for c in d.chutes]

    @property
    def achats(self) -> list:
        """Un :class:`Achat` par planche NEUVE réellement entamée — les
        chutes n'y figurent jamais (déjà en atelier, jamais à acheter).
        Utile surtout avec des ``Planche(illimite=True)`` : le solveur a
        choisi lui-même dans quel profil tailler chaque pièce, ceci
        compte ce qu'il en a réellement pris."""
        compte, ordre = {}, []
        for d in self.debits:
            pl = d.planche
            if pl.chute:
                continue
            if pl.reference not in compte:
                compte[pl.reference] = 0
                ordre.append(pl)
            compte[pl.reference] += 1
        return [Achat(pl.reference, pl.longueur, pl.largeur, pl.epaisseur,
                      pl.matiere, compte[pl.reference], pl.prix)
                for pl in ordre]

    def texte(self) -> str:
        """Résumé lisible, pour la démo et le débogage."""
        b = self.bilan
        lignes = [
            "Feuille de débit — %d/%d pièce(s) posée(s), rendement %s %%"
            % (b.nb_posees, b.nb_demandees, _pct(b.rendement)),
            "Stock entamé : %d planche(s) dont %d chute(s) · pertes %s m² · "
            "chutes créées : %d (%s m²)"
            % (b.nb_planches_entamees, b.nb_chutes_consommees,
               _m2(b.surface_perdue), len(self.chutes_creees),
               _m2(b.surface_chutes_creees)),
        ]
        if self.achats:
            lignes.append("")
            lignes.append("À acheter :")
            for a in self.achats:
                cout = " — %s" % _prix(a.nombre * a.prix) if a.prix else ""
                lignes.append(
                    "  %d × « %s » (%s × %s × %s mm, %s)%s"
                    % (a.nombre, a.reference, _mm(a.longueur),
                       _mm(a.largeur), _mm(a.epaisseur), a.matiere, cout))
            cout_total = sum(a.nombre * a.prix for a in self.achats)
            if cout_total:
                lignes.append("  Total : %s" % _prix(cout_total))
        for i, d in enumerate(self.debits, 1):
            # illimite : quantite ne dit rien du nombre reellement pris
            plusieurs = d.planche.quantite > 1 or d.planche.illimite
            ex = " (ex. %d)" % d.exemplaire if plusieurs else ""
            lignes.append("")
            lignes.append(
                "Planche %d — « %s »%s, %s × %s mm, %s — %d pièce(s), "
                "%d coupe(s), perte %s m²"
                % (i, d.planche.reference, ex, _mm(d.planche.longueur),
                   _mm(d.planche.largeur),
                   "chute du stock" if d.planche.chute else "neuve",
                   len(d.poses), len(d.coupes), _m2(d.perte)))
            for p in d.poses:
                pivot = ", pivotée" if p.pivotee else ""
                lignes.append(
                    "  pièce « %s » (%d/%d) : %s × %s en (%s, %s)%s"
                    % (p.piece.reference, p.exemplaire, p.piece.quantite,
                       _mm(p.dim_x), _mm(p.dim_y), _mm(p.x), _mm(p.y), pivot))
            for c in d.chutes:
                lignes.append("  chute : %s × %s en (%s, %s)"
                              % (_mm(c.dim_x), _mm(c.dim_y), _mm(c.x), _mm(c.y)))
        if self.non_placees:
            lignes.append("")
            lignes.append("Non placées :")
            for n in self.non_placees:
                lignes.append("  « %s » ×%d — %s"
                              % (n.piece.reference, n.exemplaires, n.raison))
        return "\n".join(lignes)


def _mm(v: float) -> str:
    return "%g" % round(v, 2)


def _m2(v: float) -> str:
    return ("%.3f" % (v / 1e6)).replace(".", ",")


def _pct(v: float) -> str:
    return ("%.1f" % (100.0 * v)).replace(".", ",")


def _prix(v: float) -> str:
    # aucune devise imposée : celle dans laquelle Planche.prix a été saisi
    return ("%.2f" % v).replace(".", ",")


# ---------------------------------------------------------------------------
# Solveur interne
# ---------------------------------------------------------------------------

@dataclass
class _Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def aire(self) -> float:
        return self.w * self.h


class _Ouverte:
    """Une planche en cours de découpe : ses rectangles libres."""

    __slots__ = ("planche", "exemplaire", "libres", "poses", "coupes")

    def __init__(self, planche: Planche, exemplaire: int):
        self.planche = planche
        self.exemplaire = exemplaire
        self.libres = [_Rect(0.0, 0.0, planche.longueur, planche.largeur)]
        self.poses = []
        self.coupes = []


@dataclass
class _Solution:
    debits: list
    non_placees: list
    dispo_restant: list


@dataclass(frozen=True)
class _Strategie:
    cle: str              # ordre des pièces
    fit: str              # bssf (meilleur petit côté) | baf (meilleure aire)
    split: str            # h | v | auto — règle de partage du reste
    chutes_d_abord: bool
    melange: "int | None" = None


_CLES_TRI = {
    "cote": lambda u: (-max(u[0].longueur, u[0].largeur),
                       -min(u[0].longueur, u[0].largeur)),
    "aire": lambda u: (-u[0].longueur * u[0].largeur,),
    "perimetre": lambda u: (-(u[0].longueur + u[0].largeur),),
    "largeur": lambda u: (-min(u[0].longueur, u[0].largeur),
                          -max(u[0].longueur, u[0].largeur)),
}


def _orientations(piece: Piece, planche: Planche, params: Parametres):
    """Les couples (dim_x, dim_y, pivotee) permis par le fil, surcote
    comprise. La surcote suit la pièce : elle pivote avec elle."""
    dx = piece.longueur + params.surcote_longueur
    dy = piece.largeur + params.surcote_largeur
    if not planche.fil or piece.fil == FIL_INDIFFERENT:
        couples = [(dx, dy, False)]
        if abs(dx - dy) > EPS:
            couples.append((dy, dx, True))
        return couples
    if piece.fil == FIL_LONGUEUR:
        return [(dx, dy, False)]
    return [(dy, dx, True)]


def _score_pose(rect: _Rect, dx: float, dy: float, fit: str):
    """Plus petit = meilleur ajustement dans ce rectangle libre."""
    rx = rect.w - dx
    ry = rect.h - dy
    if fit == "bssf":
        return (min(rx, ry), max(rx, ry))
    return (rect.aire - dx * dy, min(rx, ry))


def _meilleure_dans(o: _Ouverte, piece: Piece, params: Parametres, fit: str):
    """La meilleure pose possible dans cette planche ouverte, ou None."""
    meilleur = None
    for ir, r in enumerate(o.libres):
        for ior, (dx, dy, piv) in enumerate(_orientations(piece, o.planche,
                                                          params)):
            if dx <= r.w + EPS and dy <= r.h + EPS:
                cle = (_score_pose(r, dx, dy, fit), ir, ior)
                if meilleur is None or cle < meilleur[0]:
                    meilleur = (cle, ir, dx, dy, piv)
    return meilleur


def _couper(o: _Ouverte, sens: str, position: float, de: float, a: float):
    o.coupes.append(Coupe(sens, position, de, a, len(o.coupes) + 1))


def _liberer(o: _Ouverte, x: float, y: float, w: float, h: float):
    if w > EPS and h > EPS:
        o.libres.append(_Rect(x, y, w, h))


def _poser(o: _Ouverte, i_libre: int, piece: Piece, exemplaire: int,
           dx: float, dy: float, pivotee: bool, params: Parametres,
           split: str):
    """Pose la pièce au coin bas-gauche du rectangle libre choisi, trace
    les coupes et remplace le rectangle par le ou les restes."""
    r = o.libres.pop(i_libre)
    trait = params.trait_de_scie
    o.poses.append(Pose(piece, exemplaire, r.x, r.y, dx, dy, pivotee))
    reste_x = r.w - dx
    reste_y = r.h - dy
    coupe_x = reste_x > EPS
    coupe_y = reste_y > EPS

    if coupe_x and coupe_y:
        regle = split
        if regle == "auto":
            # garder d'un seul tenant le plus grand des deux restes
            aire_droite_pleine = max(0.0, reste_x - trait) * r.h
            aire_haut_plein = r.w * max(0.0, reste_y - trait)
            regle = "v" if aire_droite_pleine >= aire_haut_plein else "h"
        if regle == "v":
            _couper(o, TRONCONNAGE, r.x + dx, r.y, r.y + r.h)
            _liberer(o, r.x + dx + trait, r.y, reste_x - trait, r.h)
            _couper(o, DELIGNAGE, r.y + dy, r.x, r.x + dx)
            _liberer(o, r.x, r.y + dy + trait, dx, reste_y - trait)
        else:
            _couper(o, DELIGNAGE, r.y + dy, r.x, r.x + r.w)
            _liberer(o, r.x, r.y + dy + trait, r.w, reste_y - trait)
            _couper(o, TRONCONNAGE, r.x + dx, r.y, r.y + dy)
            _liberer(o, r.x + dx + trait, r.y, reste_x - trait, dy)
    elif coupe_x:
        _couper(o, TRONCONNAGE, r.x + dx, r.y, r.y + r.h)
        _liberer(o, r.x + dx + trait, r.y, reste_x - trait, r.h)
    elif coupe_y:
        _couper(o, DELIGNAGE, r.y + dy, r.x, r.x + r.w)
        _liberer(o, r.x, r.y + dy + trait, r.w, reste_y - trait)


def _ouvrir(ouvertes: list, dispo: list, piece: Piece, params: Parametres,
            strat: _Strategie):
    """Entame le stock le moins coûteux où la pièce loge, assez épais
    pour elle (chutes d'abord si la stratégie le demande). Le prix
    départage s'il est renseigné ; sinon, le moins de rabotage perdu
    (une planche à peine plus épaisse que la pièce avant une bien plus
    épaisse), puis la plus petite surface. Une chute vaut toujours 0,
    déjà possédée. Rend l'indice de la planche ouverte, ou None."""
    candidats = []
    for idx, (pl, _ex) in enumerate(dispo):
        if not _epaisseur_compatible(piece.epaisseur, pl.epaisseur, params):
            continue
        if any(dx <= pl.longueur + EPS and dy <= pl.largeur + EPS
               for dx, dy, _ in _orientations(piece, pl, params)):
            prio = 0 if (pl.chute and strat.chutes_d_abord) else 1
            if pl.chute:
                cout, gaspillage = 0.0, 0.0
            else:
                cout = pl.prix
                gaspillage = (0.0 if pl.prix > 0
                             else max(0.0, pl.epaisseur - piece.epaisseur))
            candidats.append((prio, cout, gaspillage, pl.aire, idx))
    if not candidats:
        return None
    candidats.sort()
    pl, ex = dispo.pop(candidats[0][4])
    ouvertes.append(_Ouverte(pl, ex))
    return len(ouvertes) - 1


def _logerait_dims(piece: Piece, stock_unites: list,
                   params: Parametres) -> bool:
    """La pièce logerait-elle (longueur/largeur/fil) dans au moins un
    format du stock vierge, épaisseur mise à part ?"""
    return any(dx <= pl.longueur + EPS and dy <= pl.largeur + EPS
               for pl, _ex in stock_unites
               for dx, dy, _ in _orientations(piece, pl, params))


def _logerait_a_neuf(piece: Piece, stock_unites: list,
                     params: Parametres) -> bool:
    """La pièce logerait-elle dans au moins un format du stock vierge,
    assez épais pour elle ?"""
    return any(_epaisseur_compatible(piece.epaisseur, pl.epaisseur, params)
               and dx <= pl.longueur + EPS and dy <= pl.largeur + EPS
               for pl, _ex in stock_unites
               for dx, dy, _ in _orientations(piece, pl, params))


def _resoudre(unites: list, stock_unites: list, params: Parametres,
              strat: _Strategie) -> _Solution:
    """Un passage glouton complet sous une stratégie donnée."""
    if strat.melange is None:
        ordre = sorted(unites, key=_CLES_TRI[strat.cle])
    else:
        ordre = list(unites)
        random.Random(strat.melange).shuffle(ordre)

    ouvertes = []
    dispo = list(stock_unites)
    non = {}

    for piece, exemplaire in ordre:
        choix = None
        for io, o in enumerate(ouvertes):
            if not _epaisseur_compatible(piece.epaisseur, o.planche.epaisseur,
                                         params):
                continue                  # planche déjà ouverte, trop mince
            local = _meilleure_dans(o, piece, params, strat.fit)
            if local is not None:
                score, ir, dx, dy, piv = local
                cle = (score, io)
                if choix is None or cle < choix[0]:
                    choix = (cle, io, ir, dx, dy, piv)
        if choix is None:
            io = _ouvrir(ouvertes, dispo, piece, params, strat)
            if io is None:
                if _logerait_a_neuf(piece, stock_unites, params):
                    raison = RAISON_PLUS_DE_PLACE
                elif _logerait_dims(piece, stock_unites, params):
                    raison = RAISON_TROP_EPAISSE
                else:
                    raison = RAISON_TROP_GRANDE
                cle_np = (piece, raison)
                non[cle_np] = non.get(cle_np, 0) + 1
                continue
            score, ir, dx, dy, piv = _meilleure_dans(ouvertes[io], piece,
                                                     params, strat.fit)
            choix = ((score, io), io, ir, dx, dy, piv)
        _, io, ir, dx, dy, piv = choix
        _poser(ouvertes[io], ir, piece, exemplaire, dx, dy, piv, params,
               strat.split)

    return _finaliser(ouvertes, dispo, non, params)


def _finaliser(ouvertes: list, dispo: list, non: dict,
               params: Parametres) -> _Solution:
    debits = []
    for o in ouvertes:
        chutes = []
        for r in o.libres:
            grand, petit = max(r.w, r.h), min(r.w, r.h)
            if (grand >= params.chute_mini_longueur - EPS
                    and petit >= params.chute_mini_largeur - EPS):
                chutes.append(ChuteCreee(r.w, r.h, r.x, r.y,
                                         o.planche.epaisseur,
                                         o.planche.matiere, o.planche.fil))
        debits.append(Debit(o.planche, o.exemplaire, o.poses, chutes,
                            o.coupes))
    non_placees = [NonPlacee(p, n, raison)
                   for (p, raison), n in non.items()]
    return _Solution(debits, non_placees, dispo)


def _score_solution(sol: _Solution):
    """Le score lexicographique documenté en tête de module (plus petit
    = meilleur). Arrondis pour que les égalités flottantes en soient.

    Le coût passe juste après les pièces non placées : entre deux
    stratégies qui placent tout, la moins chère gagne avant même de
    regarder le volume neuf. Un prix à 0 partout (le défaut) rend ce
    critère toujours nul — le volume neuf reste alors seul à décider.

    « Neuve » et « perte » comptent un VOLUME (surface × épaisseur), pas
    une simple surface : une planche deux fois plus épaisse représente
    deux fois plus de bois pour la même surface de face, et l'ignorer
    faisait gagner à tort le brut le plus épais dès qu'il était un peu
    moins large qu'un brut plus mince pourtant suffisant (signalé par
    Christophe : une pièce à 11,5 tirée d'un 65 alors qu'un 32 suffisait
    largement, sans aucun prix pour trancher)."""
    nb_non = sum(n.exemplaires for n in sol.non_placees)
    cout = sum(d.planche.prix for d in sol.debits if not d.planche.chute)
    neuve = sum(d.planche.aire * d.planche.epaisseur for d in sol.debits
               if not d.planche.chute)
    perte = sum(d.perte * d.planche.epaisseur for d in sol.debits)
    subsistantes = [c.aire for d in sol.debits for c in d.chutes]
    subsistantes += [pl.aire for pl, _ex in sol.dispo_restant if pl.chute]
    plus_grande = max(subsistantes, default=0.0)
    return (nb_non, round(cout, 2), round(neuve, 3), round(perte, 3),
            -round(plus_grande, 3))


def _strategies(params: Parametres):
    for cle in ("cote", "aire", "perimetre", "largeur"):
        for fit in ("bssf", "baf"):
            for split in ("auto", "h", "v"):
                for chutes in (True, False):
                    yield _Strategie(cle, fit, split, chutes)
    rng = random.Random(params.graine)
    for _ in range(params.essais_melanges):
        graine = rng.randrange(2 ** 30)
        for fit in ("bssf", "baf"):
            yield _Strategie("cote", fit, "auto", True, melange=graine)


# ---------------------------------------------------------------------------
# Groupement par matière ; l'épaisseur se vérifie pièce à pièce
# ---------------------------------------------------------------------------

def _cle_matiere(matiere: str) -> str:
    return " ".join(matiere.split()).casefold()


def _epaisseur_compatible(epaisseur_piece: float, epaisseur_planche: float,
                          params: Parametres) -> bool:
    """La planche peut-elle donner cette pièce ? Le brut se rabote, jamais
    ne s'épaissit : il doit être au moins aussi épais que la pièce, à la
    tolérance de mesure (``tolerance_epaisseur``) près. Une planche plus
    épaisse convient toujours — un même brut peut ainsi fournir des
    pièces de finitions différentes, chacune rabotée à sa propre cote
    après le débit en longueur/largeur."""
    return epaisseur_planche + params.tolerance_epaisseur >= epaisseur_piece - EPS


def _grouper(pieces: list, stock: list) -> dict:
    """Un lot par matière : au sein d'un lot, l'éligibilité d'une planche
    pour une pièce se décide au débit (dimensions ET épaisseur), pas ici
    — deux pièces de finitions différentes peuvent venir du même brut."""
    groupes = {}
    for p in pieces:
        cle = _cle_matiere(p.matiere)
        groupes.setdefault(cle, ([], []))[0].append(p)
    for s in stock:
        cle = _cle_matiere(s.matiere)
        groupes.setdefault(cle, ([], []))[1].append(s)
    return groupes


# ---------------------------------------------------------------------------
# Pièces composables : décomposition en lames à coller
# ---------------------------------------------------------------------------

def _plus_large_compatible(piece: Piece, stock: list,
                           params: Parametres) -> "float | None":
    """La plus grande largeur de brut compatible (matière, épaisseur)
    pour cette pièce — celle qui limite la largeur d'une lame. ``None``
    si aucune planche de cette matière n'est même assez épaisse."""
    candidats = [s.largeur for s in stock
                if _cle_matiere(s.matiere) == _cle_matiere(piece.matiere)
                and _epaisseur_compatible(piece.epaisseur, s.epaisseur,
                                          params)]
    return max(candidats) if candidats else None


def _nombre_de_lames(largeur_totale: float, largeur_max: float,
                     surcote_joint: float) -> int:
    """Le plus petit nombre de lames, chacune ≤ ``largeur_max`` une fois
    collées (chaque joint entre deux lames mange ``surcote_joint``), qui
    reconstitue ``largeur_totale``. 1 si une seule lame suffit déjà."""
    n = 1
    while (largeur_totale + (n - 1) * surcote_joint) / n > largeur_max + EPS:
        n += 1
        if n > 50:            # garde-fou : rien de sensé ne demande autant
            break
    return n


def _decomposer_composables(pieces: list, stock: list,
                            params: Parametres) -> list:
    """Remplace chaque pièce ``composable`` trop large pour tout brut par
    N lames à coller (ou à assembler tenon-rainure), chacune une pièce
    ordinaire pour le solveur — qui n'a rien à savoir de plus. Une pièce
    qui logerait déjà telle quelle n'est jamais décomposée (moins de
    joints, plus solide) ; le fil ``FIL_LARGEUR`` n'est pas concerné, la
    largeur n'y est pas l'axe qu'on élargirait par collage."""
    resultat = []
    for p in pieces:
        if not p.composable or p.fil == FIL_LARGEUR:
            resultat.append(p)
            continue
        largeur_max = _plus_large_compatible(p, stock, params)
        if largeur_max is None:
            resultat.append(p)      # aucun brut compatible : le débit le dira
            continue
        n = _nombre_de_lames(p.largeur, largeur_max, params.surcote_joint)
        if n <= 1:
            resultat.append(p)
            continue
        largeur_lame = (p.largeur + (n - 1) * params.surcote_joint) / n
        for i in range(1, n + 1):
            resultat.append(Piece(
                "%s (lame %d/%d)" % (p.reference, i, n), p.longueur,
                largeur_lame, p.epaisseur, p.matiere, p.quantite, p.fil))
    return resultat


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def _valider(pieces: list, stock: list, params: Parametres):
    for p in pieces:
        if p.longueur <= EPS or p.largeur <= EPS or p.epaisseur < 0:
            raise ValueError("pièce « %s » : dimensions invalides"
                             % p.reference)
        if p.quantite < 1:
            raise ValueError("pièce « %s » : quantité invalide (%r)"
                             % (p.reference, p.quantite))
        if p.fil not in _FILS_VALIDES:
            raise ValueError(
                "pièce « %s » : fil inconnu « %s » (attendu : %s)"
                % (p.reference, p.fil, ", ".join(_FILS_VALIDES)))
    for s in stock:
        if s.longueur <= EPS or s.largeur <= EPS or s.epaisseur < 0:
            raise ValueError("planche « %s » : dimensions invalides"
                             % s.reference)
        if s.quantite < 1:
            raise ValueError("planche « %s » : quantité invalide (%r)"
                             % (s.reference, s.quantite))
    if (params.trait_de_scie < 0 or params.chute_mini_longueur < 0
            or params.chute_mini_largeur < 0 or params.surcote_longueur < 0
            or params.surcote_largeur < 0 or params.tolerance_epaisseur < 0
            or params.surcote_joint < 0 or params.essais_melanges < 0):
        raise ValueError("paramètres : valeurs négatives interdites")


def optimiser(pieces: list, stock: list,
              parametres: "Parametres | None" = None) -> Resultat:
    """Calcule la feuille de débit.

    ``pieces`` : liste de :class:`Piece` ; ``stock`` : liste de
    :class:`Planche` (neuves et chutes mêlées). Les lots sont formés par
    matière et résolus séparément ; au sein d'un lot, une planche ne
    convient à une pièce que si elle est au moins aussi épaisse (le brut
    se rabote, jamais ne s'épaissit) — deux pièces de finitions
    différentes peuvent donc venir du même brut. Une pièce ``composable``
    trop large pour tout brut se décompose d'abord en lames à coller
    (:func:`_decomposer_composables`) ; le solveur ne voit ensuite que
    des pièces ordinaires.

    Exemple::

        stock = [Planche("sapin", 2400, 200, 18, "sapin", quantite=4)]
        pieces = [Piece("montant", 1750, 60, 18, "sapin", quantite=4)]
        resultat = optimiser(pieces, stock)
        print(resultat.texte())
    """
    params = parametres or Parametres()
    _valider(pieces, stock, params)
    pieces = _decomposer_composables(pieces, stock, params)

    groupes = _grouper(pieces, stock)
    debits, non_placees = [], []
    for cle in sorted(groupes):
        pieces_g, stock_g = groupes[cle]
        if not pieces_g:
            continue
        if not stock_g:
            # repr(), pas la chaine telle quelle : un espace en trop ou un
            # caractere invisible rend deux matieres visuellement identiques
            # mais jamais appariees — ca doit se voir ICI, pas se deviner
            # (piege reel, 30/08/2026 : "Douglas" partout, incompatible
            # quand meme sur une partie des pieces).
            dispo = sorted({s.matiere for s in stock})
            raison = "%s (matière lue : %r%s)" % (
                RAISON_INCOMPATIBLE, pieces_g[0].matiere,
                " — en stock : %s" % ", ".join(map(repr, dispo)) if dispo
                else "")
            non_placees.extend(NonPlacee(p, p.quantite, raison)
                               for p in pieces_g)
            continue
        unites = [(p, ex) for p in pieces_g
                  for ex in range(1, p.quantite + 1)]
        # Un profil de catalogue (illimite) n'a pas de nombre d'exemplaires
        # à respecter : jamais besoin de plus de planches que de pièces à
        # tailler, la borne reste donc sûre sans grossir inutilement le
        # rangement à résoudre. Sans effet sur une chute : déjà possédée,
        # on n'en « achète » jamais plus qu'il n'en existe réellement.
        stock_unites = [(pl, ex) for pl in stock_g
                        for ex in range(1, (len(unites)
                                            if pl.illimite and not pl.chute
                                            else pl.quantite) + 1)]
        meilleure = None
        for strat in _strategies(params):
            sol = _resoudre(unites, stock_unites, params, strat)
            score = _score_solution(sol)
            if meilleure is None or score < meilleure[0]:
                meilleure = (score, sol)
        debits.extend(meilleure[1].debits)
        non_placees.extend(meilleure[1].non_placees)

    return Resultat(debits, non_placees, _bilan(debits, non_placees))


def _bilan(debits: list, non_placees: list) -> Bilan:
    surface_pieces = sum(d.surface_poses for d in debits)
    entamee = sum(d.surface for d in debits)
    nb_posees = sum(len(d.poses) for d in debits)
    nb_non = sum(n.exemplaires for n in non_placees)
    return Bilan(
        nb_demandees=nb_posees + nb_non,
        nb_posees=nb_posees,
        nb_non_placees=nb_non,
        nb_planches_entamees=len(debits),
        nb_chutes_consommees=sum(1 for d in debits if d.planche.chute),
        surface_pieces=surface_pieces,
        surface_entamee=entamee,
        surface_neuve_entamee=sum(d.surface for d in debits
                                  if not d.planche.chute),
        surface_chutes_creees=sum(d.surface_chutes for d in debits),
        surface_perdue=sum(d.perte for d in debits),
        rendement=surface_pieces / entamee if entamee > EPS else 0.0,
    )


# ---------------------------------------------------------------------------
# Démonstration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    stock_demo = [
        Planche("sapin 2400×200", 2400, 200, 18, "sapin", quantite=4),
        Planche("chute étagère", 800, 180, 18, "sapin", chute=True),
        Planche("chute courte", 400, 120, 18, "sapin", chute=True),
    ]
    pieces_demo = [
        Piece("montant", 1750, 60, 18, "sapin", quantite=4),
        Piece("traverse", 560, 60, 18, "sapin", quantite=6),
        Piece("tablette", 560, 180, 18, "sapin", quantite=3),
        Piece("taquet", 120, 40, 18, "sapin", quantite=8,
              fil=FIL_INDIFFERENT),
    ]
    print(optimiser(pieces_demo, stock_demo).texte())
