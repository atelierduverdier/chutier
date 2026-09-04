# -*- coding: utf-8 -*-
"""Le chutier sait-il s'il est à jour ?

La page web publie ``version.json`` à côté d'elle ; l'application de
bureau l'interroge au démarrage, dans un fil, sans jamais bloquer — et
sans rien affirmer si le réseau ne répond pas. Un clone git se met à jour
par ``git pull`` ; une archive se retélécharge depuis la page du projet.

Sans Qt ni dépendance : la fenêtre s'en sert, les tests aussi.
"""

from __future__ import annotations

import json
import re
import urllib.request

ADRESSE = "https://atelierduverdier.github.io/chutier/version.json"
PAGE_PROJET = "https://github.com/atelierduverdier/chutier"

A_JOUR, EN_RETARD, INCONNUE = "à jour", "en retard", "inconnue"


def _clef(version: str):
    """« 1.2.10 » → (1, 2, 10), pour comparer numériquement — « 1.10 »
    est après « 1.9 », ce qu'une comparaison de textes ne sait pas."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def plus_recente(candidate: str, reference: str) -> bool:
    """La candidate est-elle strictement plus récente que la référence ?"""
    return _clef(candidate) > _clef(reference)


def comparer(locale: str, en_ligne) -> str:
    """A_JOUR, EN_RETARD ou INCONNUE (pas de réponse du réseau)."""
    if not en_ligne:
        return INCONNUE
    return EN_RETARD if plus_recente(en_ligne, locale) else A_JOUR


def version_en_ligne(adresse: str = None, delai: float = 3.0):
    """La version publiée (à ADRESSE par défaut, lue à l'appel pour qu'on
    puisse la détourner vers un serveur d'essai), ou None si le réseau ne
    répond pas ou répond n'importe quoi — on ne lève jamais : ne pas
    savoir n'est pas une erreur."""
    if adresse is None:
        adresse = ADRESSE
    try:
        requete = urllib.request.Request(
            adresse, headers={"Cache-Control": "no-store",
                              "User-Agent": "chutier"})
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            donnees = json.loads(reponse.read().decode("utf-8"))
        version = donnees.get("version")
        return version if isinstance(version, str) and _clef(version) else None
    except Exception:
        return None
