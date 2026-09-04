# -*- coding: utf-8 -*-
"""La couleur d'une pièce, sans Qt : partagée par l'interface de bureau
(qui en fait des QColor) et la page web (qui en fait du CSS).

Douze teintes tenues à l'écart les unes des autres : deux références
voisines ne doivent pas se ressembler. Prises en pastel, elles portent
du texte ardoise sans le noyer. La teinte ne dépend que du NOM de la
référence (crc32, jamais hash() — salé à chaque lancement de Python),
et une palette calculée sur tout un débit garantit des teintes toutes
différentes tant qu'il en reste.
"""

from __future__ import annotations

import colorsys
import zlib

TEINTES = (14, 38, 60, 92, 120, 152, 178, 200, 224, 262, 288, 322)
NUANCES = ((48, 250), (80, 232), (112, 214))     # (saturation, valeur) /255
CASES = len(TEINTES) * len(NUANCES)


def hsv_de_case(case: int) -> tuple:
    """(teinte 0-359, saturation 0-255, valeur 0-255), à la façon Qt."""
    saturation, valeur = NUANCES[case // len(TEINTES)]
    return TEINTES[case % len(TEINTES)], saturation, valeur


def hex_de_case(case: int) -> str:
    h, s, v = hsv_de_case(case)
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 255.0, v / 255.0)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def case_de(reference: str) -> int:
    return zlib.crc32(reference.encode("utf-8")) % CASES


def cases_de(references) -> dict:
    """Une case par référence, toutes DIFFÉRENTES entre elles.

    Le seul hachage ne suffit pas : « montant » et « taquet » tombaient
    sur le même vert. Les collisions se résolvent en sondant les cases
    suivantes, dans l'ordre des références triées — déterministe. Tant
    qu'il reste une teinte inutilisée, on n'en ressert pas une : c'est
    la TEINTE qui distingue à l'œil, pas la nuance."""
    prises, teintes_servies, cases = set(), set(), {}
    for reference in sorted(references):
        depart = case_de(reference)
        case = depart
        for saut in range(CASES):
            candidate = (depart + saut) % CASES
            if candidate in prises:
                continue
            if (len(teintes_servies) < len(TEINTES)
                    and candidate % len(TEINTES) in teintes_servies):
                continue
            case = candidate
            break
        prises.add(case)
        teintes_servies.add(case % len(TEINTES))
        cases[reference] = case
    return cases


def hex_piece(reference: str) -> str:
    return hex_de_case(case_de(reference))


def palette_hex(references) -> dict:
    return {ref: hex_de_case(case) for ref, case in cases_de(references).items()}
