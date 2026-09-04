# -*- coding: utf-8 -*-
"""Ce qu'on tape dans une cellule et ce qu'on y lit — sans Qt, partagé
par la table de bureau et la page web : l'écriture des nombres sans
zéro décoratif, et la petite syntaxe de la colonne « Défauts ».
"""

from __future__ import annotations

import re


class ErreurSaisie(ValueError):
    pass


def texte_nombre(valeur) -> str:
    """« 1942 » plutôt que « 1942.0 » — une feuille de débit s'écrit
    comme on la lit au mètre, sans zéro décoratif."""
    try:
        flottant = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    if flottant == int(flottant):
        return str(int(flottant))
    return ("%.3f" % flottant).rstrip("0").rstrip(".")


# -- défauts d'une planche : une colonne, une petite syntaxe ---------------

SYNTAXE_DEFAUTS = ("bouts 30 ; rives 8 ; 1200-1280 ; 600,140,60,40")
_NOMBRE = r"\d+(?:[.,]\d+)?"
_RE_BOUTS = re.compile(r"^(?:bouts?|b)\s*[:=]?\s*(%s)$" % _NOMBRE, re.I)
_RE_RIVES = re.compile(r"^(?:rives?|r)\s*[:=]?\s*(%s)$" % _NOMBRE, re.I)
_RE_BANDE = re.compile(r"^(%s)\s*(?:-|–|à|a)\s*(%s)$" % (_NOMBRE, _NOMBRE), re.I)
_RE_ZONE = re.compile(r"^(\d+(?:\.\d+)?)\s*[,x×\s]\s*(\d+(?:\.\d+)?)"
                      r"\s*[,x×\s]\s*(\d+(?:\.\d+)?)\s*[,x×\s]\s*"
                      r"(\d+(?:\.\d+)?)$", re.I)


def lire_defauts(texte: str, ou: str, largeur: float) -> dict:
    """La colonne « Défauts » d'une planche, en trois champs de
    :class:`~optimiseur.Planche` : ``recoupe_bouts``, ``recoupe_rives``,
    ``defauts``. Termes séparés par « ; » :

    - ``bouts 30`` : 30 mm à ôter à chaque bout ;
    - ``rives 8`` : 8 mm à ôter sur chaque rive ;
    - ``1200-1280`` : une bande à écarter sur TOUTE la largeur, de
      1200 à 1280 mm depuis le bout gauche (un nœud traversant) ;
    - ``600,140,60,40`` : une zone x, y, longueur, largeur (x depuis le
      bout gauche, y depuis la rive basse) — un nœud de rive, une poche.

    Dans une zone, les cotes se séparent par une virgule : leurs décimales
    s'écrivent donc avec un point. ``largeur`` sert à donner sa hauteur à
    une bande."""
    bouts, rives, zones = 0.0, 0.0, []
    for terme in re.split(r"[;\n]", texte or ""):
        terme = terme.strip()
        if not terme:
            continue
        m = _RE_BOUTS.match(terme)
        if m:
            bouts = float(m.group(1).replace(",", "."))
            continue
        m = _RE_RIVES.match(terme)
        if m:
            rives = float(m.group(1).replace(",", "."))
            continue
        m = _RE_BANDE.match(terme)
        if m:
            x1, x2 = sorted(float(v.replace(",", ".")) for v in m.groups())
            zones.append((x1, 0.0, x2 - x1, float(largeur)))
            continue
        m = _RE_ZONE.match(terme)
        if m:
            zones.append(tuple(float(v) for v in m.groups()))
            continue
        raise ErreurSaisie("%s : défaut « %s » incompris (attendu, par"
                           " exemple : %s)" % (ou, terme, SYNTAXE_DEFAUTS))
    return {"recoupe_bouts": bouts, "recoupe_rives": rives,
            "defauts": tuple(zones)}


def texte_defauts(planche) -> str:
    """L'inverse de :func:`lire_defauts`, tel qu'on l'affiche."""
    termes = []
    if planche.recoupe_bouts > 0:
        termes.append("bouts %s" % texte_nombre(planche.recoupe_bouts))
    if planche.recoupe_rives > 0:
        termes.append("rives %s" % texte_nombre(planche.recoupe_rives))
    for x, y, dx, dy in planche.defauts:
        if abs(y) < 1e-6 and abs(y + dy - planche.largeur) < 1e-6:
            termes.append("%s-%s" % (texte_nombre(x), texte_nombre(x + dx)))
        else:
            termes.append(",".join(texte_nombre(v) for v in (x, y, dx, dy)))
    return " ; ".join(termes)


def texte_contour(contour, trous=()) -> str:
    """« ◇ 24 pts · 1 trou » : la cellule dit qu'il y a une forme, pas
    laquelle — c'est le plan qui la montre."""
    if not contour:
        return ""
    texte = "◇ %d pts" % len(contour)
    if trous:
        texte += " · %d trou%s" % (len(trous), "s" if len(trous) > 1 else "")
    return texte
