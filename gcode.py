# -*- coding: utf-8 -*-
"""Le G-code d'une planche débitée, pour sortir les pièces à la fraise.

Le SVG, le DXF et le projet LightBurn décrivent des contours ; il faut
encore une chaîne CAM pour en faire un parcours. Ici, le chutier écrit
directement le programme : il connaît déjà les contours, leurs trous,
l'épaisseur de la planche et la vitesse d'avance.

Ce que ce module fait, et qu'un tracé de contours ne fait pas :

- **Le rayon de la fraise.** Une fraise qui suit le contour enlève son
  rayon de chaque côté : la pièce sort trop petite d'un diamètre. Le
  parcours est donc décalé — vers l'extérieur pour le tour d'une pièce,
  vers l'intérieur pour ses trous. C'est la correction qu'on confie
  d'ordinaire à un G41/G42 fragile ; ici elle est calculée sur la
  géométrie exacte.
- **Le sens de rotation.** En avalant, le tour se parcourt en horaire et
  les trous en anti-horaire ; en opposition, l'inverse. Se tromper de
  sens, sur du contreplaqué, c'est un chant éclaté.
- **Les passes.** On descend de ``profondeur_passe`` par tour, jusqu'à
  traverser la planche et mordre ``depassement`` dans le martyr.
- **Les attaches.** Sans elles, la pièce se libère au dernier tour, la
  fraise la prend et l'envoie. Sur la dernière passe seulement, la fraise
  remonte sur quelques arcs répartis et y laisse un pont de matière.
- **Les rampes.** Une plongée droite à pleine profondeur casse la fraise
  ou brûle le bois : la descente se fait en biais, le long du contour, et
  le morceau parcouru en descendant est repris à plat juste après.
- **L'ordre.** Les trous d'abord, le tour ensuite : l'inverse évide une
  pièce déjà libre.

**Deux dialectes**, comme LaserAtelier : ``linuxcnc`` (RS274, la PrintNC)
et ``grbl`` (la Falcon 2 et les cartes du commerce). Le mélange de
tolérance ``G64``, le changement d'outil ``T``/``M6`` et la correction de
longueur ``G43`` n'existent que sur LinuxCNC — GRBL refuse ces mots.

**Ce module ne fait pas de laser.** Un contour laser, sur la machine de
l'atelier, demande la broche ``$1``, l'armement, l'échelle de puissance
et l'assistance d'air : LaserAtelier s'en charge, et une demi-version ici
produirait un fichier valide qui grave mal — la pire sorte de défaut.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-9

DIALECTES = ("linuxcnc", "grbl")
SENS = ("avalant", "opposition")

#: Hauteur à laquelle on descend en rapide avant d'attaquer, en mm. Assez
#: bas pour ne pas perdre de temps, assez haut pour passer au-dessus d'un
#: copeau resté sur la planche.
APPROCHE = 1.0

#: Segments par quart de cercle dans le décalage : un coin extérieur
#: devient un arc, qu'on approche en polyligne.
_QUARTS = 8


@dataclass(frozen=True)
class Reglages:
    """Tout ce qu'il faut savoir de la machine et de la fraise.

    Les défauts sont ceux d'une fraise de 6 mm à deux dents dans du
    contreplaqué : des points de départ, pas des vérités — c'est le bois
    et la machine qui tranchent.

    - ``dialecte`` : ``linuxcnc`` ou ``grbl``. Il décide du changement
      d'outil, du mélange de tolérance et du code de fin.
    - ``diametre_fraise`` : le diamètre RÉEL, mesuré. Il doit tenir dans
      l'écart entre contours du plan, sinon deux parcours voisins se
      recouvrent — le programme le dit en tête.
    - ``sens`` : ``avalant`` (meilleur état de surface) ou ``opposition``.
    - ``profondeur_passe`` : ce qu'on descend par tour. Une règle qui
      tient : la moitié du diamètre en panneau, le diamètre en tendre.
    - ``depassement`` : ce qu'on mord dans le martyr, pour traverser
      vraiment.
    - ``hauteur_securite`` : la hauteur des déplacements rapides.
    - ``vitesse_avance`` / ``vitesse_plongee`` : mm/min, en XY et en Z.
    - ``vitesse_broche`` : tr/min. Zéro n'écrit ni ``M3`` ni ``M5``.
    - ``outil`` : le numéro du changement ``T<n> M6``. Zéro le saute.
    - ``attaches`` : combien de ponts par contour. Zéro les supprime.
    - ``longueur_attache`` / ``hauteur_attache`` : leur longueur le long du
      contour, et l'épaisseur de bois laissée dessous.
    - ``longueur_rampe`` : la longueur de la descente en biais. Zéro plonge
      droit.
    - ``aspiration`` : ``""``, ``M7`` ou ``M8``. **C'est le câblage qui
      décide**, pas le goût : celui qui n'est pas branché ne fait rien du
      tout, et le fichier tourne sans air sans que rien ne le dise.
    - ``tolerance_melange`` : le ``P`` du ``G64`` de LinuxCNC, en mm.
    """

    dialecte: str = "linuxcnc"
    diametre_fraise: float = 6.0
    sens: str = "avalant"
    profondeur_passe: float = 3.0
    depassement: float = 0.5
    hauteur_securite: float = 5.0
    vitesse_avance: float = 1500.0
    vitesse_plongee: float = 400.0
    vitesse_broche: int = 18000
    outil: int = 1
    attaches: int = 4
    longueur_attache: float = 8.0
    hauteur_attache: float = 1.5
    longueur_rampe: float = 20.0
    aspiration: str = ""
    tolerance_melange: float = 0.05

    def valider(self, epaisseur: float = 0.0) -> None:
        """Lève ``ValueError`` sur un réglage qui ne peut pas produire de
        parcours — mieux vaut le dire ici que devant la machine."""
        if self.dialecte not in DIALECTES:
            raise ValueError("dialecte inconnu : %r (attendu %s)"
                             % (self.dialecte, " ou ".join(DIALECTES)))
        if self.sens not in SENS:
            raise ValueError("sens inconnu : %r (attendu %s)"
                             % (self.sens, " ou ".join(SENS)))
        if self.diametre_fraise <= 0:
            raise ValueError("le diamètre de fraise doit être positif")
        if self.profondeur_passe <= 0:
            raise ValueError("la profondeur de passe doit être positive")
        if self.vitesse_avance <= 0 or self.vitesse_plongee <= 0:
            raise ValueError("les vitesses doivent être positives")
        for nom in ("depassement", "hauteur_securite", "attaches",
                    "longueur_attache", "hauteur_attache", "longueur_rampe",
                    "vitesse_broche", "outil", "tolerance_melange"):
            if getattr(self, nom) < 0:
                raise ValueError("« %s » ne peut pas être négatif" % nom)
        if self.aspiration not in ("", "M7", "M8"):
            raise ValueError('aspiration : "", M7 ou M8 — c\'est le câblage'
                             " qui décide")
        if self.attaches and epaisseur and self.hauteur_attache >= epaisseur:
            raise ValueError(
                "attache de %g mm dans une planche de %g : il ne resterait"
                " rien à couper" % (self.hauteur_attache, epaisseur))


# ---------------------------------------------------------------------------
# Un anneau, parcouru à l'abscisse curviligne
# ---------------------------------------------------------------------------

class _Anneau:
    """Un contour fermé, qu'on parcourt en donnant des longueurs plutôt
    que des indices de sommet : une attache de 8 mm tombe alors où elle
    doit, et non au sommet suivant."""

    __slots__ = ("points", "cumul", "tour")

    def __init__(self, points):
        self.points = list(points)
        self.cumul = [0.0]
        for i in range(len(self.points)):
            a = self.points[i]
            b = self.points[(i + 1) % len(self.points)]
            self.cumul.append(self.cumul[-1] + math.dist(a, b))
        self.tour = self.cumul[-1]

    def point(self, s: float):
        """Le point à l'abscisse ``s`` (repliée sur le tour)."""
        if self.tour <= EPS:
            return self.points[0]
        s = s % self.tour
        for i in range(len(self.points)):
            if self.cumul[i + 1] >= s - EPS:
                a = self.points[i]
                b = self.points[(i + 1) % len(self.points)]
                segment = self.cumul[i + 1] - self.cumul[i]
                if segment <= EPS:
                    return a
                t = (s - self.cumul[i]) / segment
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return self.points[0]

    def entre(self, debut: float, fin: float, forcees=()) -> list:
        """Les ``(s, point)`` de ``debut`` à ``fin``, sommets compris, plus
        les abscisses ``forcees`` qui tombent dedans. Le premier point
        rendu est celui de ``debut``."""
        etapes = {debut, fin}
        etapes.update(s for s in forcees if debut - EPS <= s <= fin + EPS)
        if self.tour > EPS:
            premier = math.floor(debut / self.tour)
            dernier = math.ceil(fin / self.tour)
            for k in range(int(premier), int(dernier) + 1):
                for borne in self.cumul[:-1]:
                    valeur = borne + k * self.tour
                    if debut - EPS <= valeur <= fin + EPS:
                        etapes.add(valeur)
        return [(v, self.point(v)) for v in sorted(etapes)]


def _aire_signee(points) -> float:
    n = len(points)
    return sum(points[i][0] * points[(i + 1) % n][1]
               - points[(i + 1) % n][0] * points[i][1]
               for i in range(n)) / 2.0


def _orienter(points, horaire: bool) -> list:
    """Le même anneau, parcouru dans le sens demandé."""
    anti_horaire = _aire_signee(points) > 0
    return list(reversed(points)) if anti_horaire == horaire else list(points)


# ---------------------------------------------------------------------------
# La géométrie : décaler les contours du rayon de la fraise
# ---------------------------------------------------------------------------

def _shapely():
    try:
        from shapely.geometry import LineString, Polygon
        from shapely.geometry import box as boite
    except ImportError as erreur:      # pragma: no cover - dépend du poste
        raise ValueError(
            "le G-code demande shapely (paquet python-shapely) : %s" % erreur
        ) from erreur
    return Polygon, boite, LineString


def _anneaux_pose(pose):
    """(extérieur, trous) d'une pose — un rectangle est son rectangle."""
    if pose.contour:
        return pose.contour, [list(t) for t in pose.trous]
    return (((pose.x, pose.y), (pose.x + pose.dim_x, pose.y),
             (pose.x + pose.dim_x, pose.y + pose.dim_y),
             (pose.x, pose.y + pose.dim_y)), [])


def _exterieurs(geometrie) -> list:
    """Les anneaux extérieurs d'une géométrie shapely. Un décalage peut
    couper une forme en plusieurs morceaux — un contour étranglé plus
    mince que la fraise — et on les rend tous."""
    morceaux = geometrie.geoms if hasattr(geometrie, "geoms") else [geometrie]
    anneaux = []
    for g in morceaux:
        if g.is_empty or g.geom_type != "Polygon":
            continue
        anneaux.append([(round(x, 4), round(y, 4))
                        for x, y in g.exterior.coords[:-1]])
    return anneaux


def _nom(pose) -> str:
    return "%s %d" % (pose.piece.reference, pose.exemplaire)


def _parcours(pose, reglages: Reglages, avertissements: list) -> list:
    """Les contours à fraiser pour cette pose : ``(anneau, genre)``, les
    trous d'abord, le tour ensuite."""
    Polygon, _boite, _ligne = _shapely()
    exterieur, trous = _anneaux_pose(pose)
    rayon = reglages.diametre_fraise / 2.0
    horaire_dehors = reglages.sens == "avalant"
    chemins = []

    # Coins arrondis, et non en onglet : une fraise ronde NE PEUT PAS
    # faire un angle vif extérieur. L'onglet dessinait une pointe que la
    # machine ne peut pas atteindre, qui débordait sur la pièce voisine et
    # hors de la planche — le décalage rond est le vrai chemin de l'outil.
    for trou in trous:
        creux = Polygon(trou).buffer(-rayon, quad_segs=_QUARTS)
        anneaux = _exterieurs(creux)
        if not anneaux:
            avertissements.append(
                "« %s » : un trou est plus petit que la fraise (Ø %s mm),"
                " il n'est pas percé" % (_nom(pose),
                                         _n(reglages.diametre_fraise)))
            continue
        for anneau in anneaux:
            chemins.append((_orienter(anneau, not horaire_dehors), "trou"))

    piece = Polygon(exterieur, holes=trous or None)
    dehors = piece.buffer(rayon, quad_segs=_QUARTS)
    anneaux = _exterieurs(dehors)
    if not anneaux:
        avertissements.append("« %s » : contour introuvable après décalage"
                              % _nom(pose))
    for anneau in anneaux:
        chemins.append((_orienter(anneau, horaire_dehors), "tour"))
    return chemins


def _verifier(debit, parcours, reglages: Reglages,
              avertissements: list) -> None:
    """La vraie question n'est pas « deux tracés se croisent-ils », mais
    « la fraise entre-t-elle dans la pièce d'à côté ». On compare donc ce
    que l'outil BALAYE — le parcours élargi de son rayon — à la matière
    finie des autres pièces. Une pièce imbriquée dans le trou d'une autre
    est ainsi comptée juste, là où comparer les tracés pleins la donnait
    toujours en conflit.

    Sans cela le fichier reste valide et deux pièces se mangent l'une
    l'autre : la fraise est plus large que l'écart entre contours du plan,
    et rien ne le dit."""
    Polygon, boite, LineString = _shapely()
    pl = debit.planche
    planche = boite(0, 0, pl.longueur, pl.largeur)
    rayon = reglages.diametre_fraise / 2.0
    matiere, balaye, noms = [], [], []
    for pose, chemins in parcours:
        exterieur, trous = _anneaux_pose(pose)
        piece = Polygon(exterieur, holes=trous or None)
        if not piece.is_valid:
            piece = piece.buffer(0)
        passages = [LineString(list(points) + [points[0]]).buffer(rayon,
                                                                  quad_segs=4)
                    for points, _genre in chemins]
        if not passages:
            continue
        noms.append(_nom(pose))
        matiere.append(piece)
        balaye.append(passages[0] if len(passages) == 1
                      else passages[0].union(_union(passages[1:])))
    for i, nom_a in enumerate(noms):
        if not planche.buffer(1e-6).contains(balaye[i]):
            avertissements.append(
                "« %s » : la fraise sort de la planche — la marge au bord"
                " doit valoir au moins le diamètre (%s mm), ou prenez une"
                " fraise plus fine" % (nom_a, _n(reglages.diametre_fraise)))
        for j, nom_b in enumerate(noms):
            if i == j:
                continue
            if balaye[i].intersection(matiere[j]).area > 0.01:
                avertissements.append(
                    "« %s » : la fraise mord dans « %s » — l'écart entre"
                    " contours du plan doit valoir au moins le diamètre"
                    " (%s mm), plus un jeu"
                    % (nom_a, nom_b, _n(reglages.diametre_fraise)))


def _union(formes):
    resultat = formes[0]
    for forme in formes[1:]:
        resultat = resultat.union(forme)
    return resultat


# ---------------------------------------------------------------------------
# Le programme
# ---------------------------------------------------------------------------

def _n(v: float) -> str:
    """Un nombre pour la machine : point décimal, pas de zéros inutiles."""
    texte = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if texte in ("", "-0") else texte


def _sans_parentheses(texte: str) -> str:
    """Une parenthèse dans un commentaire le referme : c'est un programme
    qui ne se charge plus, pour une référence de pièce."""
    return str(texte).replace("(", "[").replace(")", "]")


def _profondeurs(epaisseur: float, reglages: Reglages) -> list:
    """Les profondeurs successives, la dernière traversant la planche."""
    fond = epaisseur + reglages.depassement
    profondeurs = []
    z = reglages.profondeur_passe
    while z < fond - EPS:
        profondeurs.append(-z)
        z += reglages.profondeur_passe
    profondeurs.append(-fond)
    return profondeurs


def _attaches(anneau: _Anneau, reglages: Reglages, depart: float) -> list:
    """Les intervalles d'abscisse où la fraise remonte, répartis après la
    rampe pour qu'aucun ne soit traversé en descendant."""
    if reglages.attaches <= 0 or reglages.longueur_attache <= EPS:
        return []
    if anneau.tour <= EPS:
        return []
    pas = anneau.tour / reglages.attaches
    longueur = min(reglages.longueur_attache, pas / 2.0)
    if longueur <= EPS:
        return []
    return [(depart + i * pas + (pas - longueur) / 2.0,
             depart + i * pas + (pas + longueur) / 2.0)
            for i in range(reglages.attaches)]


def _passe(anneau: _Anneau, reglages: Reglages, z_haut: float, z_bas: float,
           z_attache: float, derniere: bool) -> list:
    """Un tour complet à la profondeur ``z_bas`` : la rampe descend de
    ``z_haut`` à ``z_bas`` sur les premiers millimètres, puis le tour se
    ferme à plat en repassant sur la rampe. Rend des ``(x, y, z)``."""
    rampe = min(reglages.longueur_rampe, anneau.tour)
    if anneau.tour <= EPS:
        return []
    attaches = _attaches(anneau, reglages, rampe) if derniere else []
    bornes = [s for paire in attaches for s in paire]

    def hauteur(s: float) -> float:
        for debut, fin in attaches:
            if debut - EPS <= s <= fin + EPS:
                return z_attache
        return z_bas

    sortie = []
    if rampe > EPS:
        for s, (x, y) in anneau.entre(0.0, rampe):
            sortie.append((x, y, z_haut + (z_bas - z_haut) * (s / rampe)))
    else:
        x, y = anneau.point(0.0)
        sortie.append((x, y, z_bas))
    # Le tour complet à partir du bout de la rampe : il repasse dessus, ce
    # qui coupe à plat le morceau parcouru en descendant.
    for s, (x, y) in anneau.entre(rampe, rampe + anneau.tour, bornes):
        if s <= rampe + EPS:
            continue
        milieu = s - 1e-6
        sortie.append((x, y, hauteur(milieu)))
    return sortie


def programme(debit, reglages: "Reglages | None" = None, numero: int = 1,
              titre: str = "") -> tuple:
    """Le programme G-code d'une planche débitée, et ses avertissements.

    Rend ``(texte, avertissements)``. Les avertissements sont recopiés en
    commentaires en tête du fichier : celui qui l'ouvre à la machine ne
    lit pas forcément l'écran d'où il sort.
    """
    reglages = reglages or Reglages()
    pl = debit.planche
    if pl.epaisseur <= 0:
        raise ValueError(
            "l'épaisseur de la planche « %s » n'est pas renseignée : le"
            " G-code ne saurait pas jusqu'où descendre" % pl.reference)
    reglages.valider(pl.epaisseur)
    avertissements = []

    # Les pièces du bas vers le haut, de gauche à droite : on suit le
    # programme des yeux, à la machine, sans chercher où il en est.
    poses = sorted(debit.poses, key=lambda p: (round(p.y, 3), round(p.x, 3)))
    parcours = [(pose, _parcours(pose, reglages, avertissements))
                for pose in poses]
    _verifier(debit, parcours, reglages, avertissements)

    haut = reglages.hauteur_securite
    minutes = debit.longueur_fraisage / reglages.vitesse_avance
    lignes = [
        "(%s — planche %d : %s)" % (_sans_parentheses(titre or "Chutier"),
                                    numero, _sans_parentheses(pl.reference)),
        "(planche %s x %s x %s mm, %s)"
        % (_n(pl.longueur), _n(pl.largeur), _n(pl.epaisseur),
           _sans_parentheses(pl.matiere or "matiere non renseignee")),
        "(%d piece[s], %s m de contours, environ %d min d'avance)"
        % (len(debit.poses), _n(debit.longueur_fraisage / 1000.0),
           round(minutes)),
        "(fraise D%s mm, %s, passes de %s mm, depassement %s mm)"
        % (_n(reglages.diametre_fraise), reglages.sens,
           _n(reglages.profondeur_passe), _n(reglages.depassement)),
        "(avance %s mm/min, plongee %s mm/min, broche %d tr/min)"
        % (_n(reglages.vitesse_avance), _n(reglages.vitesse_plongee),
           reglages.vitesse_broche),
    ]
    if reglages.attaches:
        lignes.append("(%d attache[s] par contour, %s mm de long, %s mm"
                      " laisses dessous)"
                      % (reglages.attaches, _n(reglages.longueur_attache),
                         _n(reglages.hauteur_attache)))
    lignes.append("(origine en bas a gauche de la planche, Z0 = dessus)")
    for mot in avertissements:
        lignes.append("(ATTENTION : %s)" % _sans_parentheses(mot))

    lignes.append("G21 G90 G94 G17")
    if reglages.dialecte == "linuxcnc":
        # G64 mélange les segments dans une tolérance : sans lui, la
        # machine marque un arrêt à chaque sommet d'une polyligne. GRBL
        # le fait nativement ($11) et refuse le mot, comme T/M6 et G43.
        lignes.append("G64 P%s" % _n(reglages.tolerance_melange))
        if reglages.outil:
            lignes.append("T%d M6" % reglages.outil)
            lignes.append("G43 H%d" % reglages.outil)
    lignes.append("G0 Z%s" % _n(haut))
    if reglages.aspiration:
        lignes.append(reglages.aspiration)
    if reglages.vitesse_broche:
        lignes.append("M3 S%d" % reglages.vitesse_broche)

    profondeurs = _profondeurs(pl.epaisseur, reglages)
    z_attache = -(pl.epaisseur - reglages.hauteur_attache)
    for pose, chemins in parcours:
        if not chemins:
            continue
        lignes.append("(piece %s %d/%d)"
                      % (_sans_parentheses(pose.piece.reference),
                         pose.exemplaire, pose.piece.quantite))
        for points, genre in chemins:
            anneau = _Anneau(points)
            if anneau.tour <= EPS:
                continue
            lignes.append("(%s)" % ("trou" if genre == "trou"
                                    else "tour de piece"))
            debut = anneau.point(0.0)
            lignes.append("G0 X%s Y%s" % (_n(debut[0]), _n(debut[1])))
            lignes.append("G0 Z%s" % _n(APPROCHE))
            z_precedent = APPROCHE
            for indice, z in enumerate(profondeurs):
                derniere = indice == len(profondeurs) - 1
                chemin = _passe(anneau, reglages, z_precedent, z, z_attache,
                                derniere)
                if not chemin:
                    continue
                if reglages.longueur_rampe <= EPS:
                    lignes.append("G1 Z%s F%s"
                                  % (_n(z), _n(reglages.vitesse_plongee)))
                lignes.append("F%s" % _n(reglages.vitesse_avance))
                dernier_z = None
                for x, y, zz in chemin:
                    if dernier_z is not None and abs(zz - dernier_z) <= EPS:
                        lignes.append("G1 X%s Y%s" % (_n(x), _n(y)))
                    else:
                        lignes.append("G1 X%s Y%s Z%s"
                                      % (_n(x), _n(y), _n(zz)))
                    dernier_z = zz
                z_precedent = z
            lignes.append("G0 Z%s" % _n(haut))

    if reglages.vitesse_broche:
        lignes.append("M5")
    if reglages.aspiration:
        lignes.append("M9")
    lignes.append("G0 Z%s" % _n(haut))
    lignes.append("M2" if reglages.dialecte == "linuxcnc" else "M30")
    return "\n".join(lignes) + "\n", avertissements
