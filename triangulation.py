# -*- coding: utf-8 -*-
"""Triangulation d'un polygone à trous — en Python pur.

Le NFP de l'imbrication (``imbrication.py``) se calcule sur des
triangles : la somme de Minkowski de deux triangles est l'enveloppe
convexe de leurs neuf sommes de sommets. shapely ≥ 2.1 triangule
lui-même (``constrained_delaunay_triangles``) ; mais la version du
navigateur (Pyodide embarque shapely 2.0.7) ne le sait pas, et un poste
avec un shapely plus ancien non plus. Ce module fait le même travail
sans rien d'autre que la bibliothèque standard : découpage en oreilles
(ear clipping), les trous d'abord pontés au contour extérieur par le
sommet le plus à droite de chacun — la méthode d'earcut.

Le résultat n'est pas de Delaunay (les triangles peuvent être effilés),
ce qui n'a aucune importance pour une somme de Minkowski : seule compte
la couverture exacte de la matière, sans chevauchement ni manque — ce
que ``tests/test_triangulation.py`` vérifie contre shapely 2.1.
"""

from __future__ import annotations

EPS = 1e-9


def _aire_signee(anneau) -> float:
    aire = 0.0
    n = len(anneau)
    for i in range(n):
        x1, y1 = anneau[i]
        x2, y2 = anneau[(i + 1) % n]
        aire += x1 * y2 - x2 * y1
    return aire / 2.0


def _nettoyer(anneau, direct: bool) -> list:
    """Sans point de fermeture ni doublon consécutif, orienté dans le sens
    direct (``direct``) ou indirect."""
    pts = []
    for p in anneau:
        q = (float(p[0]), float(p[1]))
        if not pts or abs(q[0] - pts[-1][0]) > EPS or abs(q[1] - pts[-1][1]) > EPS:
            pts.append(q)
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) <= EPS \
            and abs(pts[0][1] - pts[-1][1]) <= EPS:
        pts.pop()
    if (_aire_signee(pts) > 0) != direct:
        pts.reverse()
    return pts


def _produit(a, b, c) -> float:
    """> 0 si a, b, c tournent dans le sens direct."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _dans_triangle(p, a, b, c) -> bool:
    """p strictement dans le triangle direct abc (ou sur un bord)."""
    return (_produit(a, b, p) >= -EPS and _produit(b, c, p) >= -EPS
            and _produit(c, a, p) >= -EPS)


def _segments_se_croisent(p1, p2, q1, q2) -> bool:
    """Croisement franc de [p1 p2] et [q1 q2] (extrémités exclues)."""
    d1 = _produit(q1, q2, p1)
    d2 = _produit(q1, q2, p2)
    d3 = _produit(p1, p2, q1)
    d4 = _produit(p1, p2, q2)
    return ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
           ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS))


def _dans_angle(prec, sommet, suiv, p) -> bool:
    """La direction ``sommet → p`` tombe-t-elle dans l'angle intérieur
    (à gauche, sens direct) du contour au ``sommet`` ?"""
    convexe = _produit(prec, sommet, suiv) > EPS
    gauche_sortante = _produit(sommet, suiv, p) > EPS
    gauche_entrante = _produit(prec, sommet, p) > EPS
    if convexe:
        return gauche_sortante and gauche_entrante
    return gauche_sortante or gauche_entrante


def _ponter(exterieur: list, trou: list, autres: tuple = ()) -> list:
    """Relie un trou (sens indirect) au contour (sens direct) par un
    pont aller-retour depuis le sommet du trou le plus à droite vers un
    sommet visible du contour — le polygone reste simple, faiblement.
    ``autres`` : les trous pas encore pontés, que le pont ne doit pas
    traverser non plus — il ne les regardait pas, et dès deux trous le
    découpage recouvrait un trou sur huit (audit du 05/09/2026)."""
    i_t = max(range(len(trou)), key=lambda i: (trou[i][0], trou[i][1]))
    pt = trou[i_t]
    # Candidats : les sommets du contour à droite du point, du plus
    # proche au plus loin ; on garde le premier dont le pont ne croise
    # aucune arête du contour ni du trou.
    candidats = sorted(range(len(exterieur)),
                       key=lambda j: ((exterieur[j][0] - pt[0]) ** 2
                                      + (exterieur[j][1] - pt[1]) ** 2))
    n = len(exterieur)
    m = len(trou)
    for j in candidats:
        pe = exterieur[j]
        # Le pont doit partir DANS l'angle intérieur du contour à ce
        # sommet — sinon il sort de la matière sans croiser d'arête (par
        # un sommet rentrant), ou, quand le sommet a déjà servi de pont à
        # un autre trou et figure deux fois dans l'anneau, le nouveau tour
        # s'insère à la mauvaise occurrence et l'anneau se recouvre.
        if not _dans_angle(exterieur[j - 1], pe, exterieur[(j + 1) % n], pt):
            continue
        croise = False
        for k in range(n):
            a, b = exterieur[k], exterieur[(k + 1) % n]
            if a is pe or b is pe:
                continue
            if _segments_se_croisent(pt, pe, a, b):
                croise = True
                break
        if not croise:
            for k in range(m):
                a, b = trou[k], trou[(k + 1) % m]
                if a is pt or b is pt:
                    continue
                if _segments_se_croisent(pt, pe, a, b):
                    croise = True
                    break
        if not croise:
            for autre in autres:
                for k in range(len(autre)):
                    a, b = autre[k], autre[(k + 1) % len(autre)]
                    if _segments_se_croisent(pt, pe, a, b):
                        croise = True
                        break
                if croise:
                    break
        if not croise:
            # exterieur[..j] + pe, trou à partir de pt (tour complet), pt, pe…
            tour = [trou[(i_t + k) % m] for k in range(m)] + [pt]
            return exterieur[:j + 1] + tour + exterieur[j:]
    # Aucun pont sans croisement (polygone tordu) : on ponte au plus
    # proche quand même, le découpage en oreilles fera ce qu'il peut.
    j = candidats[0]
    tour = [trou[(i_t + k) % m] for k in range(m)] + [pt]
    return exterieur[:j + 1] + tour + exterieur[j:]


def _oreilles(anneau: list) -> list:
    """Découpage en oreilles d'un polygone simple (sens direct)."""
    pts = list(anneau)
    triangles = []
    garde = 0
    while len(pts) > 3 and garde < 10 * len(anneau) + 10:
        garde += 1
        n = len(pts)
        trouvee = False
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            if _produit(a, b, c) <= EPS:
                continue                      # sommet rentrant ou plat
            if any(_dans_triangle(p, a, b, c) for p in pts
                   if p is not a and p is not b and p is not c
                   and not (abs(p[0] - a[0]) <= EPS and abs(p[1] - a[1]) <= EPS)
                   and not (abs(p[0] - c[0]) <= EPS and abs(p[1] - c[1]) <= EPS)):
                continue
            triangles.append((a, b, c))
            del pts[i]
            trouvee = True
            break
        if not trouvee:
            # Plus d'oreille propre : polygone dégénéré ou tordu ; on
            # retire le sommet le plus plat pour avancer quand même.
            i = min(range(len(pts)),
                    key=lambda i: abs(_produit(pts[i - 1], pts[i],
                                               pts[(i + 1) % len(pts)])))
            del pts[i]
    if len(pts) == 3 and _produit(*pts) > EPS:
        triangles.append(tuple(pts))
    return triangles


def trianguler(exterieur, trous=()) -> list:
    """Les triangles ``((x, y), (x, y), (x, y))`` qui couvrent exactement
    le polygone ``exterieur`` moins ses ``trous``. Sens direct."""
    anneau = _nettoyer(exterieur, direct=True)
    if len(anneau) < 3:
        return []
    # Les trous se pontent du plus à droite au moins à droite : chaque
    # pont part vers le contour courant, déjà augmenté des précédents.
    propres = [_nettoyer(t, direct=False) for t in trous]
    propres = [t for t in propres if len(t) >= 3]
    propres.sort(key=lambda t: -max(p[0] for p in t))
    for k, trou in enumerate(propres):
        anneau = _ponter(anneau, trou, tuple(propres[k + 1:]))
    return _oreilles(anneau)
