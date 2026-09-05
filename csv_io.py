# -*- coding: utf-8 -*-
"""Lecture des pièces au format CSV — le contrat d'échange avec les projets
qui produisent une liste de pièces (un modèle FreeCAD, typiquement).

Aucun couplage de code avec ces projets : le format est la seule interface,
documentée ici et dans les README. N'importe quel générateur, dans
n'importe quel dépôt, peut produire ce CSV sans dépendre du chutier — un
``csv.writer`` de la bibliothèque standard suffit.

En-tête attendu :
    reference,longueur,largeur,epaisseur,matiere,quantite,fil,composable

Les six premières colonnes sont obligatoires ; ``fil`` est optionnel, vide
ou absent valant :data:`optimiseur.FIL_LONGUEUR`. ``composable`` est
optionnel, vide ou absent valant faux — voir :class:`optimiseur.Piece`
pour ce que ça change. Les cotes sont en millimètres, point décimal.
Aucune de ces colonnes n'est Qt ni FreeCAD — ce module reste, comme
``optimiseur.py``, sans dépendance.
"""

from __future__ import annotations

import csv
import io

import optimiseur as opt

COLONNES_REQUISES = ("reference", "longueur", "largeur", "epaisseur",
                     "matiere", "quantite")
_FILS_VALIDES = (opt.FIL_LONGUEUR, opt.FIL_LARGEUR, opt.FIL_INDIFFERENT)


def ecrire_pieces(chemin: str, pieces: list) -> None:
    """Écrit la liste de pièces au format lu par :func:`lire_pieces`.

    Le contrat d'échange ne servait que dans un sens : on pouvait
    importer une feuille de débit produite ailleurs, jamais ressortir
    celle qu'on venait de saisir pour la porter dans un autre projet ou
    un tableur.
    """
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        f.write(texte_pieces(pieces))


def texte_pieces(pieces: list) -> str:
    """Le CSV en mémoire — la page web n'écrit pas de fichier."""
    tampon = io.StringIO()
    graveur = csv.writer(tampon)
    graveur.writerow(COLONNES_REQUISES + ("fil", "composable"))
    for p in pieces:
        graveur.writerow([p.reference, _nombre(p.longueur),
                          _nombre(p.largeur), _nombre(p.epaisseur),
                          p.matiere, p.quantite, p.fil,
                          "1" if p.composable else "0"])
    return tampon.getvalue()


def _nombre(valeur: float) -> str:
    """Sans zéro décoratif : 1750 plutôt que 1750.0, mais 829.686 entier."""
    if float(valeur) == int(valeur):
        return str(int(valeur))
    return ("%.3f" % valeur).rstrip("0").rstrip(".")


def lire_pieces(chemin: str) -> list:
    """Les :class:`optimiseur.Piece` décrites par le CSV à ``chemin``.

    Lève ``ValueError`` (colonnes manquantes, ligne mal formée) ou
    ``OSError`` (fichier introuvable) — à l'appelant de les rattraper.
    """
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        return lire_pieces_texte(f.read())


def lire_pieces_texte(texte: str) -> list:
    """Comme :func:`lire_pieces`, sur un CSV déjà en mémoire."""
    # Excel écrit « CSV UTF-8 » avec une marque d'ordre d'octets, qui se
    # colle au premier nom de colonne : « reference » devenait
    # « \ufeffreference » et le fichier était refusé pour une colonne
    # manquante qui, elle, était bien là.
    lecteur = csv.DictReader(io.StringIO(texte.lstrip("\ufeff")))
    manquantes = set(COLONNES_REQUISES) - set(lecteur.fieldnames or [])
    if manquantes:
        raise ValueError(
            "colonnes manquantes dans le CSV : %s (attendu : %s)"
            % (", ".join(sorted(manquantes)), ", ".join(COLONNES_REQUISES)))
    return [_ligne_vers_piece(ligne, num)
            for num, ligne in enumerate(lecteur, start=2)]


def _ligne_vers_piece(ligne: dict, num_ligne: int):
    reference = (ligne.get("reference") or "").strip()
    try:
        if not reference:
            raise ValueError("référence vide")
        fil = (ligne.get("fil") or "").strip() or opt.FIL_LONGUEUR
        if fil not in _FILS_VALIDES:
            raise ValueError("fil « %s » inconnu (attendu : %s)"
                             % (fil, ", ".join(_FILS_VALIDES)))
        composable = (ligne.get("composable") or "").strip().casefold()
        if composable not in ("", "0", "1", "vrai", "faux", "true", "false"):
            raise ValueError("composable « %s » inconnu (attendu : vide,"
                             " 0, 1, vrai ou faux)" % composable)
        piece = opt.Piece(
            reference=reference,
            longueur=float(ligne["longueur"]),
            largeur=float(ligne["largeur"]),
            epaisseur=float(ligne["epaisseur"] or 0),
            matiere=(ligne.get("matiere") or "").strip(),
            quantite=int(ligne["quantite"] or 1),
            fil=fil,
            composable=composable in ("1", "vrai", "true"))
        # Une quantité négative, une longueur infinie (float("inf") ne
        # lève rien) : rien ne les arrêtait avant le prochain calcul —
        # ou jamais, si le CSV n'est que réexporté (audit du
        # 05/09/2026). Les mêmes règles qu'au calcul, rejouées ICI.
        opt._valider_piece(piece)
        return piece
    except (TypeError, ValueError) as erreur:
        raise ValueError("ligne %d du CSV : %s" % (num_ligne, erreur)) from erreur
