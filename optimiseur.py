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
  2. le moins cher, si les prix sont renseignés ;
  3. le moins de bois NEUF entamé (déstockage d'abord) ;
  4. le moins de pertes (sciure + rebuts sous les minis de chute) ;
  5. le moins de coupes — ou l'inverse de 4 et 5 quand la priorité est
     donnée au temps de scie (``Parametres.priorite``) ;
  6. des chutes subsistantes concentrées : une grande plutôt que trois
     moyennes de même surface.
Tout est déterministe : mêmes entrées, même graine → même résultat.
"""

from __future__ import annotations

import dataclasses
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
RAISON_PLANCHE_INCONNUE = "sa planche imposée n'est pas dans le stock"
RAISON_PLANCHE_IMPOSEE = "sa planche imposée ne peut pas la recevoir"
RAISON_PLANCHE_PLEINE = "plus de place sur sa planche imposée"

PRIORITE_BOIS = "bois"   # moins de pertes d'abord, puis moins de coupes
PRIORITE_SCIE = "scie"   # moins de coupes d'abord, puis moins de pertes
_PRIORITES_VALIDES = (PRIORITE_BOIS, PRIORITE_SCIE)


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

    ``planche`` : la référence d'une ligne de stock où tailler cette
    pièce, imposée — vide, le chutier choisit. C'est le geste « non, pas
    celle-là, prends-la dans la chute du fond » ; le reste du plan se
    recalcule autour.
    """

    reference: str
    longueur: float
    largeur: float
    epaisseur: float = 0.0
    matiere: str = ""
    quantite: int = 1
    fil: str = FIL_LONGUEUR
    composable: bool = False
    planche: str = ""

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

    ``atelier`` : ce morceau vit dans le stock COMMUN de l'atelier (le
    fichier retrouvé d'un projet à l'autre), pas dans le projet. Sans
    effet sur le débit : c'est la persistance qui s'en sert pour savoir
    où réécrire la ligne.

    Les défauts du bois — ce que la planche a de moins que son rectangle :

    - ``recoupe_bouts`` : millimètres à ôter à CHAQUE bout (fendu, sale,
      pas d'équerre). Le trait de scie tombe juste au-delà, dans le bon
      bois : la zone déclarée est perdue en entier.
    - ``recoupe_rives`` : idem sur CHAQUE rive (flache, rive brute à
      dresser). Une flache d'un seul côté se déclare plutôt en zone.
    - ``defauts`` : zones à écarter, ``((x, y, dx, dy), …)`` dans les
      coordonnées de la planche — un nœud, une fente, une poche de
      résine. Chacune est retirée par des coupes guillotine AVANT de poser
      la moindre pièce (deux traits en travers, puis deux le long dans la
      bande, ou l'inverse selon la stratégie) ; ce qui l'entoure reste
      disponible, la zone part aux pertes.
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
    atelier: bool = False
    recoupe_bouts: float = 0.0
    recoupe_rives: float = 0.0
    defauts: tuple = ()

    def __post_init__(self):
        # Relu d'un JSON, ``defauts`` arrive en listes : on le remet en
        # tuples, sans quoi la planche n'est plus hachable (elle sert de
        # clé pour décompter les exemplaires entamés) ni égale à elle-même.
        object.__setattr__(self, "defauts",
                           tuple(tuple(float(v) for v in zone)
                                 for zone in self.defauts))

    @property
    def aire(self) -> float:
        return self.longueur * self.largeur

    @property
    def a_des_defauts(self) -> bool:
        return bool(self.defauts or self.recoupe_bouts > EPS
                    or self.recoupe_rives > EPS)


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
    - ``priorite`` : entre deux plans qui placent tout dans le même bois
      neuf, ``PRIORITE_BOIS`` (défaut) garde celui qui perd le moins de
      matière, ``PRIORITE_SCIE`` celui qui demande le moins de coupes —
      à la circulaire, un plan qui range les pièces de même largeur en
      bandes se scie deux fois plus vite qu'un plan éparpillé de même
      rendement.
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
    priorite: str = PRIORITE_BOIS


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
    nb_coupes: int = 0


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
            "Stock entamé : %d planche(s) dont %d chute(s) · %d coupe(s) · "
            "pertes %s m² · chutes créées : %d (%s m²)"
            % (b.nb_planches_entamees, b.nb_chutes_consommees, b.nb_coupes,
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


def _admise(piece: Piece, planche: Planche) -> bool:
    """La pièce accepte-t-elle cette planche ? Toujours, sauf si elle en
    impose une autre par sa référence."""
    return (not piece.planche
            or _cle_matiere(piece.planche) == _cle_matiere(planche.reference))


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


# -- défauts du bois : recoupes et zones à écarter -----------------------------

def _dims_utiles(pl: Planche, params: Parametres):
    """(longueur, largeur) qui restent une fois les bouts et les rives
    recoupés, traits de scie compris — ce dans quoi une pièce doit loger
    pour qu'on entame cette planche. Les zones de défaut ne sont pas
    comptées ici : elles ne bornent pas un rectangle, elles le trouent."""
    trait = params.trait_de_scie
    lg = pl.longueur - (2 * (pl.recoupe_bouts + trait)
                        if pl.recoupe_bouts > EPS else 0.0)
    la = pl.largeur - (2 * (pl.recoupe_rives + trait)
                       if pl.recoupe_rives > EPS else 0.0)
    return lg, la


def _intersection(r: _Rect, zone) -> "_Rect | None":
    x, y, dx, dy = zone
    x0, y0 = max(r.x, x), max(r.y, y)
    x1, y1 = min(r.x + r.w, x + dx), min(r.y + r.h, y + dy)
    if x1 - x0 <= EPS or y1 - y0 <= EPS:
        return None
    return _Rect(x0, y0, x1 - x0, y1 - y0)


def _autour_en_travers(r: _Rect, d: _Rect, trait: float):
    """Retire ``d`` de ``r`` en tronçonnant d'abord (deux traits en
    travers, de bord à bord), puis en délignant la bande du milieu. Rend
    (rectangles gardés, coupes) — les coupes en ``(sens, position, de,
    a)``, dans l'ordre où on les passe. Le trait de scie tombe TOUJOURS
    hors de la zone, dans le bon bois : ce qui est déclaré défaut est
    perdu en entier, jamais rogné d'un trait."""
    rects, coupes = [], []
    ml, mr = r.x, r.x + r.w
    if d.x - trait > r.x + EPS:
        coupes.append((TRONCONNAGE, d.x - trait, r.y, r.y + r.h))
        rects.append(_Rect(r.x, r.y, d.x - trait - r.x, r.h))
        ml = d.x
    if d.x + d.w + trait < r.x + r.w - EPS:
        coupes.append((TRONCONNAGE, d.x + d.w, r.y, r.y + r.h))
        rects.append(_Rect(d.x + d.w + trait, r.y,
                           r.x + r.w - (d.x + d.w + trait), r.h))
        mr = d.x + d.w
    if d.y - trait > r.y + EPS:
        coupes.append((DELIGNAGE, d.y - trait, ml, mr))
        rects.append(_Rect(ml, r.y, mr - ml, d.y - trait - r.y))
    if d.y + d.h + trait < r.y + r.h - EPS:
        coupes.append((DELIGNAGE, d.y + d.h, ml, mr))
        rects.append(_Rect(ml, d.y + d.h + trait, mr - ml,
                           r.y + r.h - (d.y + d.h + trait)))
    return rects, coupes


def _autour_en_long(r: _Rect, d: _Rect, trait: float):
    """Même chose en délignant d'abord (deux traits le long, de bord à
    bord), puis en tronçonnant la bande du milieu — l'ordre qui garde des
    brins pleine longueur de part et d'autre d'une fente."""
    rects, coupes = [], []
    mb, mh = r.y, r.y + r.h
    if d.y - trait > r.y + EPS:
        coupes.append((DELIGNAGE, d.y - trait, r.x, r.x + r.w))
        rects.append(_Rect(r.x, r.y, r.w, d.y - trait - r.y))
        mb = d.y
    if d.y + d.h + trait < r.y + r.h - EPS:
        coupes.append((DELIGNAGE, d.y + d.h, r.x, r.x + r.w))
        rects.append(_Rect(r.x, d.y + d.h + trait, r.w,
                           r.y + r.h - (d.y + d.h + trait)))
        mh = d.y + d.h
    if d.x - trait > r.x + EPS:
        coupes.append((TRONCONNAGE, d.x - trait, mb, mh))
        rects.append(_Rect(r.x, mb, d.x - trait - r.x, mh - mb))
    if d.x + d.w + trait < r.x + r.w - EPS:
        coupes.append((TRONCONNAGE, d.x + d.w, mb, mh))
        rects.append(_Rect(d.x + d.w + trait, mb,
                           r.x + r.w - (d.x + d.w + trait), mh - mb))
    return rects, coupes


def _retirer_zone(o: _Ouverte, zone, trait: float, split: str):
    """Écarte une zone de défaut de tous les rectangles libres qu'elle
    touche, par des coupes guillotine. ``split`` choisit l'ordre des
    traits : « v » tronçonne d'abord, « h » déligne d'abord, « auto »
    garde l'ordre qui laisse le plus grand rectangle d'un seul tenant."""
    for r in list(o.libres):
        d = _intersection(r, zone)
        if d is None:
            continue
        o.libres.remove(r)
        travers = _autour_en_travers(r, d, trait)
        long_ = _autour_en_long(r, d, trait)
        if split == "v":
            rects, coupes = travers
        elif split == "h":
            rects, coupes = long_
        else:
            def merite(choix):
                aires = sorted((x.aire for x in choix[0]), reverse=True)
                return (aires[0] if aires else 0.0,
                        sum(a * a for a in aires))
            rects, coupes = max((travers, long_), key=merite)
        for sens, position, de, a in coupes:
            _couper(o, sens, position, de, a)
        for x in rects:
            _liberer(o, x.x, x.y, x.w, x.h)


def _preparer(o: _Ouverte, params: Parametres, split: str):
    """Applique les défauts de la planche AVANT toute pose : recoupe des
    bouts (deux tronçonnages), des rives (deux délignages), puis chaque
    zone à écarter. Une planche sans défaut ressort intacte."""
    pl = o.planche
    if not pl.a_des_defauts:
        return
    trait = params.trait_de_scie
    x0, x1 = 0.0, pl.longueur
    y0, y1 = 0.0, pl.largeur
    if pl.recoupe_bouts > EPS:
        _couper(o, TRONCONNAGE, pl.recoupe_bouts, y0, y1)
        _couper(o, TRONCONNAGE, pl.longueur - pl.recoupe_bouts - trait, y0, y1)
        x0 = pl.recoupe_bouts + trait
        x1 = pl.longueur - pl.recoupe_bouts - trait
    if pl.recoupe_rives > EPS:
        _couper(o, DELIGNAGE, pl.recoupe_rives, x0, x1)
        _couper(o, DELIGNAGE, pl.largeur - pl.recoupe_rives - trait, x0, x1)
        y0 = pl.recoupe_rives + trait
        y1 = pl.largeur - pl.recoupe_rives - trait
    o.libres = []
    _liberer(o, x0, y0, x1 - x0, y1 - y0)
    for zone in pl.defauts:
        _retirer_zone(o, zone, trait, split)


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
        if not _admise(piece, pl):
            continue
        lg, la = _dims_utiles(pl, params)
        if any(dx <= lg + EPS and dy <= la + EPS
               for dx, dy, _ in _orientations(piece, pl, params)):
            prio = 0 if (pl.chute and strat.chutes_d_abord) else 1
            if pl.chute:
                cout, gaspillage = 0.0, 0.0
            else:
                cout = pl.prix
                gaspillage = (0.0 if pl.prix > 0
                             else max(0.0, pl.epaisseur - piece.epaisseur))
            candidats.append((prio, cout, gaspillage, pl.aire, idx))
    candidats.sort()
    for *_, idx in candidats:
        pl, ex = dispo[idx]
        o = _Ouverte(pl, ex)
        # Les défauts se retirent à l'ouverture : une planche trouée d'un
        # nœud peut ne plus loger la pièce qui entrait dans son rectangle
        # — on passe alors à la candidate suivante.
        _preparer(o, params, strat.split)
        if _meilleure_dans(o, piece, params, strat.fit) is not None:
            dispo.pop(idx)
            ouvertes.append(o)
            return len(ouvertes) - 1
    return None


def _logerait_dims(piece: Piece, stock_unites: list,
                   params: Parametres) -> bool:
    """La pièce logerait-elle (longueur/largeur/fil) dans au moins un
    format du stock vierge, épaisseur mise à part ?"""
    return any(dx <= _dims_utiles(pl, params)[0] + EPS
               and dy <= _dims_utiles(pl, params)[1] + EPS
               for pl, _ex in stock_unites
               for dx, dy, _ in _orientations(piece, pl, params))


def _logerait_a_neuf(piece: Piece, stock_unites: list,
                     params: Parametres) -> bool:
    """La pièce logerait-elle dans au moins un format du stock vierge,
    assez épais pour elle ?"""
    return any(_epaisseur_compatible(piece.epaisseur, pl.epaisseur, params)
               and dx <= _dims_utiles(pl, params)[0] + EPS
               and dy <= _dims_utiles(pl, params)[1] + EPS
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
            if not _admise(piece, o.planche):
                continue
            local = _meilleure_dans(o, piece, params, strat.fit)
            if local is not None:
                score, ir, dx, dy, piv = local
                cle = (score, io)
                if choix is None or cle < choix[0]:
                    choix = (cle, io, ir, dx, dy, piv)
        if choix is None:
            io = _ouvrir(ouvertes, dispo, piece, params, strat)
            if io is None:
                admises = [(pl, ex) for pl, ex in stock_unites
                           if _admise(piece, pl)]
                if piece.planche and not admises:
                    raison = RAISON_PLANCHE_INCONNUE
                elif _logerait_a_neuf(piece, admises, params):
                    raison = (RAISON_PLANCHE_PLEINE if piece.planche
                              else RAISON_PLUS_DE_PLACE)
                elif piece.planche:
                    raison = RAISON_PLANCHE_IMPOSEE
                elif _logerait_dims(piece, admises, params):
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


def _score_solution(sol: _Solution, params: Parametres):
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
    largement, sans aucun prix pour trancher).

    Les chutes subsistantes comptent par la somme de leurs CARRÉS : « la
    plus grande chute » ne distinguait pas une grande de trois moyennes
    de même surface totale — or une grande resservira, trois moyennes
    encombrent."""
    nb_non = sum(n.exemplaires for n in sol.non_placees)
    cout = sum(d.planche.prix for d in sol.debits if not d.planche.chute)
    neuve = sum(d.planche.aire * d.planche.epaisseur for d in sol.debits
               if not d.planche.chute)
    perte = round(sum(d.perte * d.planche.epaisseur for d in sol.debits), 3)
    coupes = sum(len(d.coupes) for d in sol.debits)
    subsistantes = [c.aire for d in sol.debits for c in d.chutes]
    subsistantes += [pl.aire for pl, _ex in sol.dispo_restant if pl.chute]
    concentration = round(sum(a * a for a in subsistantes), 3)
    if params.priorite == PRIORITE_SCIE:
        milieu = (coupes, perte)
    else:
        milieu = (perte, coupes)
    return (nb_non, round(cout, 2), round(neuve, 3)) + milieu \
        + (-concentration,)


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
    si aucune planche de cette matière n'est même assez épaisse.

    Largeur BRUTE de la planche : c'est l'appelant qui en retire la
    surcote de largeur, puisque c'est lui qui sait qu'une lame sera
    débitée surcotée."""
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
        # Une lame est débitée SURCOTÉE comme n'importe quelle pièce : ce
        # qu'elle peut mesurer une fois finie, c'est la largeur du brut
        # moins cette surcote. L'oublier taillait des lames larges
        # d'exactement la planche, qui ne rentraient plus une fois la
        # surcote ajoutée — et la pièce composable ressortait « trop
        # grande », précisément ce qu'être composable devait éviter.
        utile = largeur_max - params.surcote_largeur
        if utile <= EPS:
            resultat.append(p)      # la surcote mange toute la planche
            continue
        n = _nombre_de_lames(p.largeur, utile, params.surcote_joint)
        if n <= 1:
            resultat.append(p)
            continue
        largeur_lame = (p.largeur + (n - 1) * params.surcote_joint) / n
        for i in range(1, n + 1):
            resultat.append(Piece(
                "%s (lame %d/%d)" % (p.reference, i, n), p.longueur,
                largeur_lame, p.epaisseur, p.matiere, p.quantite, p.fil,
                planche=p.planche))
    return resultat


# ---------------------------------------------------------------------------
# Épingles : des débits repris tels quels
# ---------------------------------------------------------------------------

def _meme(objet):
    """L'identité d'une pièce ou d'une planche, quantité mise à part :
    c'est à elle qu'on reconnaît, dans la saisie courante, ce qu'une
    épingle désigne."""
    return dataclasses.replace(objet, quantite=1)


def _appliquer_epingles(pieces: list, stock: list, epingles: list):
    """Retire de la demande et du stock ce que les débits épinglés
    consomment déjà. Rend (pièces restantes, stock restant, débits
    fixés) — les débits fixés pointant sur les objets de la saisie
    COURANTE, pour que le reste de la chaîne (décompte des planches
    entamées, achats) les reconnaisse.

    Lève ``ValueError`` si une épingle ne colle plus à la saisie : sa
    planche a disparu du stock, une de ses pièces de la liste, ou il n'y
    en a plus assez d'exemplaires. Une épingle ne se rattrape pas à peu
    près : c'est le plan qu'on a validé à l'œil, ou rien."""
    pieces_par = {}
    for p in pieces:
        pieces_par.setdefault(_meme(p), []).append(p)
    stock_par = {}
    for pl in stock:
        stock_par.setdefault(_meme(pl), []).append(pl)
    besoin_pieces, besoin_stock, fixes = {}, {}, []
    for d in epingles:
        cle_pl = _meme(d.planche)
        if cle_pl not in stock_par:
            raise ValueError("épingle : la planche « %s » n'est plus dans"
                             " le stock" % d.planche.reference)
        planche = stock_par[cle_pl][0]
        if not planche.illimite:
            besoin_stock[cle_pl] = besoin_stock.get(cle_pl, 0) + 1
        poses = []
        for pose in d.poses:
            cle_p = _meme(pose.piece)
            if cle_p not in pieces_par:
                raise ValueError("épingle : la pièce « %s » n'est plus dans"
                                 " la liste, ou plus aux mêmes cotes"
                                 % pose.piece.reference)
            besoin_pieces[cle_p] = besoin_pieces.get(cle_p, 0) + 1
            poses.append(dataclasses.replace(pose, piece=pieces_par[cle_p][0]))
        fixes.append(Debit(planche, d.exemplaire, poses, list(d.chutes),
                           list(d.coupes)))

    restantes = []
    for p in pieces:
        cle = _meme(p)
        pris = min(besoin_pieces.get(cle, 0), p.quantite)
        besoin_pieces[cle] = besoin_pieces.get(cle, 0) - pris
        if p.quantite - pris > 0:
            restantes.append(dataclasses.replace(p, quantite=p.quantite - pris))
    for cle, reste in besoin_pieces.items():
        if reste > 0:
            raise ValueError("épingle : plus assez d'exemplaires de « %s »"
                             " (%d de plus que la liste n'en compte)"
                             % (cle.reference, reste))
    restant = []
    for pl in stock:
        cle = _meme(pl)
        pris = min(besoin_stock.get(cle, 0), pl.quantite)
        besoin_stock[cle] = besoin_stock.get(cle, 0) - pris
        if pl.quantite - pris > 0:
            restant.append(dataclasses.replace(pl, quantite=pl.quantite - pris))
    for cle, reste in besoin_stock.items():
        if reste > 0:
            raise ValueError("épingle : plus assez d'exemplaires de la"
                             " planche « %s »" % cle.reference)
    return restantes, restant, fixes


def _renumeroter(debits: list, pieces: list, stock: list) -> list:
    """Après un débit à épingles, deux numérotations se chevauchent :
    les exemplaires de pièces (« montant 1/4 ») et de planches (« ex. 2 »)
    des débits fixés, et ceux du reste, reparti de 1. On renumérote tout
    à la suite, et chaque pose retrouve la pièce de la saisie ENTIÈRE
    (celle du solveur avait sa quantité amputée des exemplaires
    épinglés)."""
    pieces_par = {_meme(p): p for p in pieces}
    stock_par = {_meme(pl): pl for pl in stock}
    compte_pieces, compte_planches, resultat = {}, {}, []
    for d in debits:
        cle_pl = _meme(d.planche)
        compte_planches[cle_pl] = compte_planches.get(cle_pl, 0) + 1
        poses = []
        for pose in d.poses:
            cle = _meme(pose.piece)
            compte_pieces[cle] = compte_pieces.get(cle, 0) + 1
            poses.append(dataclasses.replace(
                pose, piece=pieces_par.get(cle, pose.piece),
                exemplaire=compte_pieces[cle]))
        resultat.append(Debit(stock_par.get(cle_pl, d.planche),
                              compte_planches[cle_pl], poses, d.chutes,
                              d.coupes))
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
        if s.recoupe_bouts < 0 or s.recoupe_rives < 0:
            raise ValueError("planche « %s » : recoupe négative"
                             % s.reference)
        if (2 * s.recoupe_bouts >= s.longueur - EPS
                or 2 * s.recoupe_rives >= s.largeur - EPS):
            raise ValueError("planche « %s » : les recoupes mangent toute"
                             " la planche" % s.reference)
        for zone in s.defauts:
            if len(zone) != 4:
                raise ValueError("planche « %s » : une zone de défaut se"
                                 " donne en x, y, longueur, largeur"
                                 % s.reference)
            x, y, dx, dy = zone
            if (dx <= EPS or dy <= EPS or x < -EPS or y < -EPS
                    or x + dx > s.longueur + EPS or y + dy > s.largeur + EPS):
                raise ValueError("planche « %s » : zone de défaut %s hors"
                                 " de la planche ou vide"
                                 % (s.reference, tuple(_mm(v) for v in zone)))
    if (params.trait_de_scie < 0 or params.chute_mini_longueur < 0
            or params.chute_mini_largeur < 0 or params.surcote_longueur < 0
            or params.surcote_largeur < 0 or params.tolerance_epaisseur < 0
            or params.surcote_joint < 0 or params.essais_melanges < 0):
        raise ValueError("paramètres : valeurs négatives interdites")
    if params.priorite not in _PRIORITES_VALIDES:
        raise ValueError("paramètres : priorité inconnue « %s » (attendu :"
                         " %s)" % (params.priorite,
                                   ", ".join(_PRIORITES_VALIDES)))


def optimiser(pieces: list, stock: list,
              parametres: "Parametres | None" = None,
              epingles: list = ()) -> Resultat:
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

    ``epingles`` : des :class:`Debit` d'un calcul précédent à reprendre
    TELS QUELS — la planche qu'on a validée à l'œil. Leurs pièces et
    leur planche sortent de la demande, le reste se recalcule autour ;
    ils ouvrent la liste des débits rendus. Lève ``ValueError`` si une
    épingle ne colle plus à la saisie (planche ou pièce disparue).

    Exemple::

        stock = [Planche("sapin", 2400, 200, 18, "sapin", quantite=4)]
        pieces = [Piece("montant", 1750, 60, 18, "sapin", quantite=4)]
        resultat = optimiser(pieces, stock)
        print(resultat.texte())
    """
    params = parametres or Parametres()
    _valider(pieces, stock, params)
    pieces_saisies, stock_saisi = list(pieces), list(stock)
    pieces = _decomposer_composables(pieces, stock, params)
    pieces, stock, debits = _appliquer_epingles(pieces, stock, list(epingles))

    groupes = _grouper(pieces, stock)
    non_placees = []
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
            score = _score_solution(sol, params)
            if meilleure is None or score < meilleure[0]:
                meilleure = (score, sol)
        debits.extend(meilleure[1].debits)
        non_placees.extend(meilleure[1].non_placees)

    if epingles:
        debits = _renumeroter(debits, _decomposer_composables(
            pieces_saisies, stock_saisi, params), stock_saisi)
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
        nb_coupes=sum(len(d.coupes) for d in debits),
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
