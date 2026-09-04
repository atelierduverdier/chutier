# -*- coding: utf-8 -*-
"""Ce que devient le stock une fois le débit fait — sans Qt, partagé par
le bureau et la page web. C'est la seule opération du chutier qui
réécrive une saisie de l'utilisateur : elle vit ici, séparée de la boîte
de dialogue qui la propose, pour être vérifiable par un test.
"""

from __future__ import annotations

import dataclasses

import optimiseur as opt


def chutes_groupees(resultat) -> dict:
    """Les chutes créées rassemblées par cotes identiques, la plus grande
    d'abord. Deux chutes de 505 × 41 sont un lot de deux, pas deux lignes."""
    groupes = {}
    for c in resultat.chutes_creees:
        cle = (round(c.dim_x, 1), round(c.dim_y, 1), round(c.epaisseur, 1),
               c.matiere, c.fil, c.contour_origine(), c.trous_origine())
        groupes[cle] = groupes.get(cle, 0) + 1
    return dict(sorted(groupes.items(), key=lambda kv: -kv[0][0] * kv[0][1]))


def planches_consommees(resultat) -> dict:
    """Combien d'exemplaires de chaque planche le débit a entamés.

    La clé est la :class:`~optimiseur.Planche` ENTIÈRE, pas sa seule
    référence : rien n'interdit deux lignes de stock du même nom à des
    cotes différentes (« chute douglas » deux fois), et décompter sur le
    nom seul aurait retiré les exemplaires de la mauvaise.

    Un profil de catalogue n'y figure pas : il ne sort pas de l'atelier,
    il s'achète — c'est ``Resultat.achats`` qui le compte."""
    consommees = {}
    for debit in resultat.debits:
        if debit.planche.illimite:
            continue
        consommees[debit.planche] = consommees.get(debit.planche, 0) + 1
    return consommees


def stock_apres_debit(stock: list, resultat) -> list:
    """Le stock tel qu'il sera une fois le débit fait à l'établi : les
    planches entamées en moins, les chutes créées en plus — à l'ATELIER,
    pas au projet : c'est là qu'on les retrouvera au débit suivant."""
    restant = dict(planches_consommees(resultat))
    nouveau = []
    for planche in stock:
        pris = min(restant.get(planche, 0), planche.quantite)
        if pris and not planche.illimite:
            restant[planche] -= pris
            reste = planche.quantite - pris
            if reste <= 0:
                continue          # tout ce lot est passé sous la scie
            planche = dataclasses.replace(planche, quantite=reste)
        nouveau.append(planche)

    for (dim_x, dim_y, epaisseur, matiere, fil, contour, trous), nombre in \
            chutes_groupees(resultat).items():
        modele = opt.ChuteCreee(dim_x, dim_y, 0, 0, epaisseur, matiere, fil,
                                contour, trous)
        reference = "Chute %s%s %s×%s" % ("biscornue " if contour else "",
                                          matiere, opt._mm(dim_x), opt._mm(dim_y))
        nouveau.append(dataclasses.replace(modele.en_planche(reference),
                                           quantite=nombre, atelier=True))
    return nouveau
