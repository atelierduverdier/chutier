# -*- coding: utf-8 -*-
"""Lecture des pièces au format CSV — le contrat d'échange avec les projets
qui produisent une liste de pièces (un modèle FreeCAD, typiquement).

Aucun couplage de code avec ces projets : le format est la seule interface,
documentée ici et dans les README. N'importe quel générateur, dans
n'importe quel dépôt, peut produire ce CSV sans dépendre du chutier — un
``csv.writer`` de la bibliothèque standard suffit.

En-tête attendu :
    reference,longueur,largeur,epaisseur,matiere,quantite,fil

Les six premières colonnes sont obligatoires ; ``fil`` est optionnel, vide
ou absent valant :data:`optimiseur.FIL_LONGUEUR`. Les cotes sont en
millimètres, point décimal. Aucune de ces colonnes n'est Qt ni FreeCAD —
ce module reste, comme ``optimiseur.py``, sans dépendance.
"""

from __future__ import annotations

import csv

import optimiseur as opt

COLONNES_REQUISES = ("reference", "longueur", "largeur", "epaisseur",
                     "matiere", "quantite")
_FILS_VALIDES = (opt.FIL_LONGUEUR, opt.FIL_LARGEUR, opt.FIL_INDIFFERENT)


def lire_pieces(chemin: str) -> list:
    """Les :class:`optimiseur.Piece` décrites par le CSV à ``chemin``.

    Lève ``ValueError`` (colonnes manquantes, ligne mal formée) ou
    ``OSError`` (fichier introuvable) — à l'appelant de les rattraper.
    """
    with open(chemin, newline="", encoding="utf-8") as f:
        lecteur = csv.DictReader(f)
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
        return opt.Piece(
            reference=reference,
            longueur=float(ligne["longueur"]),
            largeur=float(ligne["largeur"]),
            epaisseur=float(ligne["epaisseur"] or 0),
            matiere=(ligne.get("matiere") or "").strip(),
            quantite=int(ligne["quantite"] or 1),
            fil=fil)
    except (TypeError, ValueError) as erreur:
        raise ValueError("ligne %d du CSV : %s" % (num_ligne, erreur)) from erreur
