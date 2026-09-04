# -*- coding: utf-8 -*-
"""Le pont entre la page web et le cœur : du JSON dedans, du JSON dehors.

La page (JavaScript, Pyodide) ne manipule aucune dataclass : elle envoie
des dictionnaires — la même forme que le fichier de projet — et reçoit
le débit sous forme de dictionnaires, couleurs et fiche d'atelier
comprises. Tout ce qui est ici est du Python pur, testé sans navigateur
(``tests/test_pont_web.py``), puis chargé tel quel dans Pyodide.

Une planche peut arriver avec ``defauts_texte`` (la colonne « Défauts »
telle qu'on la tape) à la place des trois champs : on la traduit ici.
"""

from __future__ import annotations

import dataclasses
import json

import contours_svg
import couleurs
import csv_io
import optimiseur as opt
import projet_io
import saisie
import stock_atelier

_CHAMPS_PIECE = {f.name for f in dataclasses.fields(opt.Piece)}
_CHAMPS_PLANCHE = {f.name for f in dataclasses.fields(opt.Planche)}
_CHAMPS_PARAMS = {f.name for f in dataclasses.fields(opt.Parametres)}


def _nombre(v, defaut=0.0):
    if v is None or v == "":
        return defaut
    if isinstance(v, str):
        v = v.replace(",", ".").strip()
    return float(v)


def _entier(v, defaut=1):
    if v is None or v == "":
        return defaut
    return int(float(str(v).replace(",", ".")))


def _piece(d: dict) -> opt.Piece:
    champs = {k: v for k, v in d.items() if k in _CHAMPS_PIECE}
    for cle in ("longueur", "largeur", "epaisseur"):
        champs[cle] = _nombre(champs.get(cle))
    champs["quantite"] = _entier(champs.get("quantite"))
    champs["composable"] = bool(champs.get("composable", False))
    return opt.Piece(**champs)


def _planche(d: dict) -> opt.Planche:
    champs = {k: v for k, v in d.items() if k in _CHAMPS_PLANCHE}
    for cle in ("longueur", "largeur", "epaisseur", "prix", "recoupe_bouts",
                "recoupe_rives"):
        champs[cle] = _nombre(champs.get(cle))
    champs["quantite"] = _entier(champs.get("quantite"))
    for cle in ("chute", "illimite", "atelier"):
        champs[cle] = bool(champs.get(cle, False))
    champs["fil"] = bool(champs.get("fil", True))
    if "defauts_texte" in d:
        champs.update(saisie.lire_defauts(
            d["defauts_texte"] or "", "« %s »" % champs.get("reference", ""),
            champs["largeur"]))
    return opt.Planche(**champs)


def _parametres(d: dict) -> opt.Parametres:
    defauts = opt.Parametres()
    champs = {}
    for f in dataclasses.fields(opt.Parametres):
        if f.name not in (d or {}):
            continue
        v = d[f.name]
        if isinstance(defauts.__dict__[f.name], bool):
            champs[f.name] = bool(v)
        elif isinstance(defauts.__dict__[f.name], int):
            champs[f.name] = _entier(v, defauts.__dict__[f.name])
        elif isinstance(defauts.__dict__[f.name], float):
            champs[f.name] = _nombre(v, defauts.__dict__[f.name])
        else:
            champs[f.name] = v
    return opt.Parametres(**champs)


def _pose(p: opt.Pose) -> dict:
    return {
        "reference": p.piece.reference, "exemplaire": p.exemplaire,
        "quantite": p.piece.quantite, "epaisseur": p.piece.epaisseur,
        "x": p.x, "y": p.y, "dim_x": p.dim_x, "dim_y": p.dim_y,
        "pivotee": p.pivotee, "angle": p.angle, "aire": p.aire,
        "contour": list(p.contour), "trous": [list(t) for t in p.trous],
    }


def _debit(d: opt.Debit) -> dict:
    pl = d.planche
    return {
        "planche": dataclasses.asdict(pl),
        "exemplaire": d.exemplaire,
        "plusieurs": pl.quantite > 1 or pl.illimite,
        "poses": [_pose(p) for p in d.poses],
        "chutes": [dataclasses.asdict(c) for c in d.chutes],
        "coupes": [dataclasses.asdict(c) for c in d.coupes],
        "imbriquee": d.imbriquee,
        "rendement": d.rendement,
        "perte": d.perte,
        "defauts_texte": saisie.texte_defauts(pl),
        "epingle": dataclasses.asdict(d),      # à renvoyer tel quel pour épingler
    }


def _resultat(r: opt.Resultat, stock: list) -> dict:
    references = {p.piece.reference for d in r.debits for p in d.poses}
    chutes = [{"dim_x": k[0], "dim_y": k[1], "epaisseur": k[2],
               "matiere": k[3], "fil": k[4], "nombre": n}
              for k, n in stock_atelier.chutes_groupees(r).items()]
    return {
        "bilan": dataclasses.asdict(r.bilan),
        "debits": [_debit(d) for d in r.debits],
        "achats": [dataclasses.asdict(a) for a in r.achats],
        "non_placees": [{"reference": n.piece.reference,
                         "exemplaires": n.exemplaires, "raison": n.raison}
                        for n in r.non_placees],
        "couleurs": couleurs.palette_hex(references),
        "chutes_groupees": chutes,
        "cout": sum(a.nombre * a.prix for a in r.achats),
        "fiche": r.texte(),
        "stock_apres": [dataclasses.asdict(s) for s in
                        stock_atelier.stock_apres_debit(stock, r)],
    }


def calculer(entree: str) -> str:
    """``entree`` : JSON ``{"pieces", "stock", "parametres", "epingles"}``.
    Rend ``{"ok": true, "resultat": …, "epingles_relachees": bool}`` ou
    ``{"ok": false, "erreur": "…"}``."""
    try:
        donnees = json.loads(entree)
        pieces = [_piece(d) for d in donnees.get("pieces", [])
                  if (d.get("reference") or "").strip()]
        stock = [_planche(d) for d in donnees.get("stock", [])
                 if (d.get("reference") or "").strip()]
        params = _parametres(donnees.get("parametres") or {})
        if not pieces:
            raise ValueError("aucune pièce à débiter")
        epingles = [projet_io._debit(d) for d in donnees.get("epingles", [])]
        relachees = False
        try:
            r = opt.optimiser(pieces, stock, params, epingles=epingles)
        except ValueError as erreur:
            if not epingles or not str(erreur).startswith("épingle"):
                raise
            relachees = True
            r = opt.optimiser(pieces, stock, params)
        return json.dumps({"ok": True, "resultat": _resultat(r, stock),
                           "epingles_relachees": relachees},
                          ensure_ascii=False)
    except (ValueError, TypeError, KeyError) as erreur:
        return json.dumps({"ok": False, "erreur": str(erreur)},
                          ensure_ascii=False)


def depuis_svg(texte: str) -> str:
    """Les formes d'un SVG : ``{"formes": [...], "avertissements": [...]}``
    ou ``{"erreur": …}``."""
    try:
        formes, avertissements = contours_svg.formes_depuis_texte(texte)
    except Exception as erreur:                       # XML illisible, etc.
        return json.dumps({"erreur": str(erreur)}, ensure_ascii=False)
    for f in formes:
        f["contour"] = list(f["contour"])
        f["trous"] = [list(t) for t in f["trous"]]
    return json.dumps({"formes": formes, "avertissements": avertissements},
                      ensure_ascii=False)


def svg_planche(debit_json: str, numero: int = 1, titre: str = "") -> str:
    """Le SVG de découpe d'une planche (son dictionnaire ``epingle``)."""
    debit = projet_io._debit(json.loads(debit_json))
    return contours_svg.svg_planche(debit, numero, titre)


def depuis_csv(texte: str) -> str:
    try:
        pieces = csv_io.lire_pieces_texte(texte)
    except ValueError as erreur:
        return json.dumps({"erreur": str(erreur)}, ensure_ascii=False)
    return json.dumps({"pieces": [dataclasses.asdict(p) for p in pieces]},
                      ensure_ascii=False)


def vers_csv(pieces_json: str) -> str:
    pieces = [_piece(d) for d in json.loads(pieces_json)
              if (d.get("reference") or "").strip()]
    return csv_io.texte_pieces(pieces)


def depuis_projet(texte: str) -> str:
    """Le projet en dictionnaires, épingles comprises, ou ``{"erreur"}``."""
    try:
        donnees = json.loads(texte)
        pieces, stock, parametres, epingles = projet_io.depuis_donnees(donnees)
    except (ValueError, TypeError) as erreur:
        return json.dumps({"erreur": str(erreur)}, ensure_ascii=False)
    sortie = projet_io.donnees_projet(pieces, stock, parametres, epingles)
    for s in sortie["stock"]:
        s["defauts_texte"] = saisie.texte_defauts(opt.Planche(**s))
    return json.dumps(sortie, ensure_ascii=False)


def vers_projet(entree: str) -> str:
    """Le fichier de projet, à télécharger, depuis les dictionnaires de la
    page (planches avec ``defauts_texte`` acceptées)."""
    donnees = json.loads(entree)
    pieces = [_piece(d) for d in donnees.get("pieces", [])
              if (d.get("reference") or "").strip()]
    stock = [_planche(d) for d in donnees.get("stock", [])
             if (d.get("reference") or "").strip()]
    params = _parametres(donnees.get("parametres") or {})
    epingles = [projet_io._debit(d) for d in donnees.get("epingles", [])]
    return json.dumps(projet_io.donnees_projet(pieces, stock, params, epingles),
                      ensure_ascii=False, indent=2)


def exemple() -> str:
    pieces = [opt.Piece("montant", 1750, 60, 18, "sapin", quantite=4),
              opt.Piece("traverse", 560, 60, 18, "sapin", quantite=6),
              opt.Piece("tablette", 560, 180, 18, "sapin", quantite=3),
              opt.Piece("taquet", 120, 40, 18, "sapin", quantite=8,
                        fil=opt.FIL_INDIFFERENT)]
    stock = [opt.Planche("sapin 2400×200", 2400, 200, 18, "sapin", quantite=4),
             opt.Planche("chute étagère", 800, 180, 18, "sapin", chute=True,
                         defauts=((740, 0, 60, 180),)),
             opt.Planche("chute courte", 400, 120, 18, "sapin", chute=True,
                         recoupe_bouts=15)]
    donnees = projet_io.donnees_projet(pieces, stock, opt.Parametres())
    for s in donnees["stock"]:
        s["defauts_texte"] = saisie.texte_defauts(opt.Planche(**s))
    return json.dumps(donnees, ensure_ascii=False)


def parametres_defaut() -> str:
    return json.dumps(dataclasses.asdict(opt.Parametres()))
