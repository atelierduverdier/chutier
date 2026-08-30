# -*- coding: utf-8 -*-
"""Sauvegarde/chargement de l'état de travail complet (pièces, stock,
paramètres) en JSON — le seul moyen d'enregistrer quoi que ce soit d'une
séance à l'autre. Différent de csv_io.py : le CSV n'échange que la liste
de pièces avec d'autres projets, le JSON ici porte tout ce qu'il faut
pour reprendre exactement où on en était, y compris le stock qu'aucun
projet extérieur n'a de raison de connaître.

Aucune dépendance à Qt : comme optimiseur.py et csv_io.py, cette couche
ne fait que lire/écrire des dataclasses, sans rien savoir de l'interface.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile

import optimiseur as opt


def enregistrer(chemin: str, pieces: list, stock: list,
                parametres: "opt.Parametres") -> None:
    donnees = {
        "pieces": [dataclasses.asdict(p) for p in pieces],
        "stock": [dataclasses.asdict(s) for s in stock],
        "parametres": dataclasses.asdict(parametres),
    }
    # Écriture atomique : un disque plein ou une coupure en plein
    # json.dump laisserait un projet tronqué À LA PLACE du bon. On écrit
    # à côté, puis on remplace d'un seul geste.
    dossier = os.path.dirname(os.path.abspath(chemin))
    fichier = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=dossier, prefix=".chutier-", suffix=".tmp",
        delete=False)
    try:
        with fichier as f:
            json.dump(donnees, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(fichier.name, chemin)
    except BaseException:
        if os.path.exists(fichier.name):
            os.unlink(fichier.name)
        raise


def lire(chemin: str):
    """(pieces, stock, parametres) lus à ``chemin``.

    Lève ``ValueError`` (JSON invalide, champ inconnu ou manquant) ou
    ``OSError`` (fichier introuvable) — à l'appelant de les rattraper.
    """
    with open(chemin, encoding="utf-8") as f:
        try:
            donnees = json.load(f)
        except json.JSONDecodeError as erreur:
            raise ValueError("fichier de projet illisible : %s" % erreur) \
                from erreur

    try:
        pieces = [opt.Piece(**d) for d in donnees["pieces"]]
        stock = [opt.Planche(**d) for d in donnees["stock"]]
        parametres = opt.Parametres(**donnees.get("parametres", {}))
    except (KeyError, TypeError) as erreur:
        raise ValueError("fichier de projet mal formé : %s" % erreur) \
            from erreur
    return pieces, stock, parametres
