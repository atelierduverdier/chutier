# -*- coding: utf-8 -*-
"""Sauvegarde/chargement de l'état de travail complet (pièces, stock,
paramètres) en JSON — le seul moyen d'enregistrer quoi que ce soit d'une
séance à l'autre. Différent de csv_io.py : le CSV n'échange que la liste
de pièces avec d'autres projets, le JSON ici porte tout ce qu'il faut
pour reprendre exactement où on en était, y compris le stock qu'aucun
projet extérieur n'a de raison de connaître.

Deux fichiers, pas un :

- le PROJET (``enregistrer`` / ``lire``) : pièces, planches propres au
  projet, réglages ;
- l'ATELIER (``enregistrer_atelier`` / ``lire_atelier``) : le stock
  commun — chutes rangées, planches en rayon — retrouvé d'un projet à
  l'autre sans le recopier. C'est la raison d'être du chutier, et
  jusqu'ici il n'existait pas : le stock dormait dans chaque projet.

Une :class:`~optimiseur.Planche` dit elle-même où elle vit
(``atelier=True``) ; c'est l'interface qui répartit la liste entre les
deux fichiers, ici on écrit ce qu'on reçoit.

Aucune dépendance à Qt : comme optimiseur.py et csv_io.py, cette couche
ne fait que lire/écrire des dataclasses, sans rien savoir de l'interface.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile

import optimiseur as opt

# Variable d'environnement qui déplace le fichier d'atelier — les tests
# s'en servent pour ne jamais toucher le vrai stock.
VARIABLE_ATELIER = "CHUTIER_ATELIER"


def chemin_atelier() -> str:
    """Le fichier commun de l'atelier : ``$CHUTIER_ATELIER`` s'il est
    posé, sinon ``$XDG_DATA_HOME/chutier/atelier.json`` (soit
    ``~/.local/share/chutier/atelier.json``)."""
    force = os.environ.get(VARIABLE_ATELIER)
    if force:
        return force
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "chutier", "atelier.json")


def _ecrire_atomique(chemin: str, donnees: dict) -> None:
    # Écriture atomique : un disque plein ou une coupure en plein
    # json.dump laisserait un fichier tronqué À LA PLACE du bon. On écrit
    # à côté, puis on remplace d'un seul geste.
    dossier = os.path.dirname(os.path.abspath(chemin))
    os.makedirs(dossier, exist_ok=True)
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


def _lire_json(chemin: str, quoi: str) -> dict:
    with open(chemin, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as erreur:
            raise ValueError("%s illisible : %s" % (quoi, erreur)) from erreur


def _planches(brut: list, quoi: str) -> list:
    try:
        return [opt.Planche(**d) for d in brut]
    except (KeyError, TypeError) as erreur:
        raise ValueError("%s mal formé : %s" % (quoi, erreur)) from erreur


# -- le projet ---------------------------------------------------------------

def enregistrer(chemin: str, pieces: list, stock: list,
                parametres: "opt.Parametres") -> None:
    _ecrire_atomique(chemin, {
        "pieces": [dataclasses.asdict(p) for p in pieces],
        "stock": [dataclasses.asdict(s) for s in stock],
        "parametres": dataclasses.asdict(parametres),
    })


def lire(chemin: str):
    """(pieces, stock, parametres) lus à ``chemin``.

    Lève ``ValueError`` (JSON invalide, champ inconnu ou manquant) ou
    ``OSError`` (fichier introuvable) — à l'appelant de les rattraper.
    """
    donnees = _lire_json(chemin, "fichier de projet")
    try:
        pieces = [opt.Piece(**d) for d in donnees["pieces"]]
        stock = _planches(donnees["stock"], "fichier de projet")
        parametres = opt.Parametres(**donnees.get("parametres", {}))
    except (KeyError, TypeError) as erreur:
        raise ValueError("fichier de projet mal formé : %s" % erreur) \
            from erreur
    return pieces, stock, parametres


# -- l'atelier ---------------------------------------------------------------

def enregistrer_atelier(chemin: str, stock: list) -> None:
    """Écrit le stock commun. Chaque planche y est marquée ``atelier``,
    quoi qu'ait dit l'appelant : relue, elle doit se savoir d'ici."""
    _ecrire_atomique(chemin, {
        "stock": [dataclasses.asdict(dataclasses.replace(s, atelier=True))
                  for s in stock],
    })


def lire_atelier(chemin: str) -> list:
    """Les planches du stock commun, toutes marquées ``atelier``. Un
    fichier absent est un atelier vide, pas une erreur — c'est le cas
    de toute première séance. Lève ``ValueError`` s'il est illisible."""
    if not os.path.exists(chemin):
        return []
    donnees = _lire_json(chemin, "fichier d'atelier")
    try:
        brut = donnees["stock"]
    except (KeyError, TypeError) as erreur:
        raise ValueError("fichier d'atelier mal formé : %s" % erreur) \
            from erreur
    return [dataclasses.replace(s, atelier=True)
            for s in _planches(brut, "fichier d'atelier")]
