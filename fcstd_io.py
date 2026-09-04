# -*- coding: utf-8 -*-
"""Lire la liste de pièces dans le tableur d'un document FreeCAD.

Un ``.FCStd`` est une archive zip ; son ``Document.xml`` porte les cellules
de chaque tableur en clair — contenu, et alias. On les lit donc sans
FreeCAD, comme le site de l'atelier lit ses cotes.

LE CONTRAT est celui du CSV : une feuille dont une ligne d'en-tête porte
au moins une référence (« Rep. », « Désignation »…), une longueur et une
largeur (casse, accents et abréviations tolérés : « Long. », « Ép. »,
« Qté »…), puis les pièces une par ligne. Une ligne qui a une référence
mais pas de longueur est un titre de section, sautée. Les colonnes
facultatives valent ce que vaut le CSV : épaisseur 0, matière vide,
quantité 1, fil longueur. S'il y a à la fois un repère et une
désignation, la pièce s'appelle « Désignation (Rep.) ».

LES FORMULES SE CALCULENT ICI. Une cellule porte sa formule, pas son
résultat, et une vraie feuille de débit est faite de formules —
« =round(Parametres.HautVantail * 10) / 10 » sur la porte de hammam.
L'évaluateur sait : les nombres avec ou sans unité (mm, cm, m), les
alias et les références de cellules, dans la feuille ou dans une autre
(« Parametres.B5 », « Parametres.HautVantail »), + − × ÷ ^, les
parenthèses, round / floor / ceil / abs / min / max. Ce qu'il ne sait
pas, il le refuse en nommant la cellule : rien n'est deviné.

Aucune dépendance : ni Qt, ni FreeCAD.
"""

from __future__ import annotations

import html
import io
import math
import re
import unicodedata
import zipfile

import optimiseur as opt

_BALISE_CELLULE = re.compile(r"<Cell\s([^>]*?)/?>")
_ATTRIBUT = re.compile(r'(\w+)="([^"]*)"')
_OBJET = re.compile(r'<Object name="([^"]+)"')
_FEUILLE = re.compile(r'<Object type="Spreadsheet::Sheet" name="([^"]+)"')
_ADRESSE = re.compile(r"^([A-Z]{1,3})(\d{1,5})$")

# Ce que peut s'appeler chaque colonne, une fois passé par _normaliser.
_ALIAS = {
    "rep": ("rep", "repere", "ref", "reference"),
    "designation": ("designation", "piece", "nom", "libelle", "name"),
    "longueur": ("longueur", "long", "l", "length"),
    "largeur": ("largeur", "larg", "w", "width"),
    "epaisseur": ("epaisseur", "ep", "epais", "e", "thickness"),
    "matiere": ("matiere", "mat", "essence", "bois", "material"),
    "quantite": ("quantite", "qte", "qty", "nombre", "nb", "n"),
    "fil": ("fil", "grain"),
    "composable": ("composable",),
}
_FILS = {"longueur": opt.FIL_LONGUEUR, "largeur": opt.FIL_LARGEUR,
         "indifferent": opt.FIL_INDIFFERENT, "": opt.FIL_LONGUEUR}
_UNITES = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texte.casefold())


# -- le document --------------------------------------------------------------------

class Feuille:
    """Un tableur : ``cellules`` {(colonne, ligne) -> contenu}, ``alias``
    {alias -> (colonne, ligne)}."""

    def __init__(self, nom):
        self.nom = nom
        self.cellules = {}
        self.alias = {}


def feuilles(donnees: bytes) -> dict:
    """{nom -> Feuille} d'un .FCStd en mémoire. Cloisonné par feuille :
    deux tableurs d'un même document ont les mêmes adresses."""
    try:
        with zipfile.ZipFile(io.BytesIO(donnees)) as z:
            if "Document.xml" not in z.namelist():
                raise ValueError("ce fichier n'est pas un document FreeCAD"
                                 " (pas de Document.xml)")
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except zipfile.BadZipFile as erreur:
        raise ValueError("ce fichier n'est pas un document FreeCAD (%s)"
                         % erreur) from erreur
    noms = set(_FEUILLE.findall(xml))
    bornes = [(m.group(1), m.start()) for m in _OBJET.finditer(xml)]
    resultat = {}
    for k, (nom, debut) in enumerate(bornes):
        if nom not in noms:
            continue
        fin = bornes[k + 1][1] if k + 1 < len(bornes) else len(xml)
        feuille = Feuille(nom)
        for m in _BALISE_CELLULE.finditer(xml[debut:fin]):
            attrs = {c: html.unescape(v) for c, v in _ATTRIBUT.findall(m.group(1))}
            adresse = _ADRESSE.match(attrs.get("address", ""))
            if not adresse or "content" not in attrs:
                continue
            cle = (adresse.group(1), int(adresse.group(2)))
            feuille.cellules[cle] = attrs["content"]
            if attrs.get("alias"):
                feuille.alias[attrs["alias"]] = cle
        if feuille.cellules:
            resultat[nom] = feuille
    return resultat


def _texte(contenu: str) -> str:
    """Un contenu de cellule en texte : l'apostrophe de tête qui force le
    texte dans FreeCAD s'enlève, une formule garde son signe égal."""
    contenu = (contenu or "").strip()
    return contenu[1:] if contenu.startswith("'") else contenu


# -- l'évaluateur de formules ------------------------------------------------------

_JETON = re.compile(r"\s*(?:(?P<nombre>\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)"
                    r"|(?P<nom>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)"
                    r"|(?P<op>[-+*/^(),]))")
def _arrondi(x: float, chiffres: int = 0) -> float:
    """L'arrondi de FreeCAD, pas celui de Python.

    ``round`` en Python arrondit au PAIR : round(2.5) vaut 2, round(0.5)
    vaut 0. Le moteur d'expressions de FreeCAD s'appuie sur ``std::round``,
    qui arrondit à l'écart de zéro : 3 et 1. Une feuille de débit qui
    montre 3 et qu'on lit 2, c'est un millimètre de bois en moins, sans
    rien pour le signaler — et ``=round(x * 10) / 10`` est la forme la plus
    courante d'une telle feuille."""
    facteur = 10.0 ** int(chiffres)
    v = x * facteur
    entier = math.floor(v + 0.5) if v >= 0 else math.ceil(v - 0.5)
    return float(entier) / facteur


_FONCTIONS = {
    "round": _arrondi,
    "floor": lambda x: float(math.floor(x)), "ceil": lambda x: float(math.ceil(x)),
    "abs": lambda x: abs(x), "min": lambda *a: min(a), "max": lambda *a: max(a),
    "sqrt": math.sqrt, "int": lambda x: float(int(x)), "trunc": lambda x: float(int(x)),
}


class _Evaluateur:
    """Calcule le nombre d'une cellule, formules et références comprises,
    en mémoire de ce qui est déjà calculé, et refuse les cycles."""

    def __init__(self, document: dict):
        self.document = document
        self.valeurs = {}
        self.en_cours = set()

    def cellule(self, feuille: Feuille, cle, ou: str) -> float:
        contenu = feuille.cellules.get(cle)
        if contenu is None:
            raise ValueError("%s : cellule %s%d vide" % (ou, cle[0], cle[1]))
        return self.contenu(feuille, contenu, "%s!%s%d" % (feuille.nom, *cle))

    def contenu(self, feuille: Feuille, contenu: str, ou: str) -> float:
        cle = (feuille.nom, contenu, ou)
        if cle in self.valeurs:
            return self.valeurs[cle]
        if cle in self.en_cours:
            raise ValueError("%s : formule circulaire" % ou)
        self.en_cours.add(cle)
        try:
            texte = _texte(contenu)
            if texte.startswith("="):
                valeur = self._formule(feuille, texte[1:], ou)
            else:
                valeur = self._litteral(texte, ou)
        finally:
            self.en_cours.discard(cle)
        self.valeurs[cle] = valeur
        return valeur

    def _litteral(self, texte: str, ou: str) -> float:
        m = re.match(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\s*$", texte, re.I)
        if not m:
            raise ValueError("%s : « %s » n'est pas un nombre" % (ou, texte))
        return float(m.group(1).replace(",", ".")) * _UNITES[(m.group(2) or "mm").lower()]

    def _reference(self, feuille: Feuille, nom: str, ou: str) -> float:
        if "." in nom:
            nom_feuille, reste = nom.split(".", 1)
            cible = self.document.get(nom_feuille)
            if cible is None:
                raise ValueError("%s : feuille « %s » inconnue" % (ou, nom_feuille))
        else:
            cible, reste = feuille, nom
        adresse = _ADRESSE.match(reste.upper())
        if adresse and (adresse.group(1), int(adresse.group(2))) in cible.cellules:
            cle = (adresse.group(1), int(adresse.group(2)))
        elif reste in cible.alias:
            cle = cible.alias[reste]
        else:
            raise ValueError("%s : « %s » n'est ni une cellule ni un alias de"
                             " la feuille %s" % (ou, reste, cible.nom))
        return self.cellule(cible, cle, ou)

    def _formule(self, feuille: Feuille, texte: str, ou: str) -> float:
        jetons = []
        pos = 0
        while pos < len(texte):
            m = _JETON.match(texte, pos)
            if not m or m.end() == pos:
                if texte[pos:].strip():
                    raise ValueError("%s : formule illisible à « %s »"
                                     % (ou, texte[pos:pos + 12]))
                break
            pos = m.end()
            if m.group("nombre"):
                jetons.append(("n", float(m.group("nombre").replace(",", "."))))
            elif m.group("nom"):
                jetons.append(("id", m.group("nom")))
            else:
                jetons.append(("op", m.group("op")))
        # Réentrant : une référence relance un parse au milieu de celui-ci,
        # on met le nôtre de côté le temps qu'il finisse.
        sauvegarde = (getattr(self, "_jetons", None), getattr(self, "_i", 0),
                      getattr(self, "_feuille", None), getattr(self, "_ou", ""))
        self._jetons, self._i = jetons, 0
        self._feuille, self._ou = feuille, ou
        try:
            valeur = self._somme()
            if self._i != len(jetons):
                raise ValueError("%s : formule illisible" % ou)
        finally:
            self._jetons, self._i, self._feuille, self._ou = sauvegarde
        return valeur

    def _regarder(self):
        return self._jetons[self._i] if self._i < len(self._jetons) else (None, None)

    def _prendre(self, genre=None, valeur=None):
        g, v = self._regarder()
        if g is None or (genre and g != genre) or (valeur and v != valeur):
            raise ValueError("%s : formule illisible" % self._ou)
        self._i += 1
        return v

    def _somme(self):
        valeur = self._produit()
        while self._regarder() == ("op", "+") or self._regarder() == ("op", "-"):
            op = self._prendre("op")
            droite = self._produit()
            valeur = valeur + droite if op == "+" else valeur - droite
        return valeur

    def _produit(self):
        valeur = self._puissance()
        while self._regarder() == ("op", "*") or self._regarder() == ("op", "/"):
            op = self._prendre("op")
            droite = self._puissance()
            if op == "/":
                if droite == 0:
                    raise ValueError("%s : division par zéro" % self._ou)
                valeur = valeur / droite
            else:
                valeur = valeur * droite
        return valeur

    def _puissance(self):
        # 2^3^2 vaut 2^(3^2) : l'exposant s'associe à DROITE. Une seule
        # puissance était lue, et « formule illisible » suivait.
        base = self._unaire()
        if self._regarder() == ("op", "^"):
            self._prendre("op")
            return base ** self._puissance()
        return base

    def _unaire(self):
        if self._regarder() == ("op", "-"):
            self._prendre("op")
            return -self._unaire()
        if self._regarder() == ("op", "+"):
            self._prendre("op")
            return self._unaire()
        return self._atome()

    def _atome(self):
        genre, valeur = self._regarder()
        if genre == "n":
            self._prendre()
            suivant = self._regarder()
            if suivant[0] == "id" and suivant[1].lower() in _UNITES:
                self._prendre()
                return valeur * _UNITES[suivant[1].lower()]
            return valeur
        if genre == "op" and valeur == "(":
            self._prendre()
            v = self._somme()
            self._prendre("op", ")")
            return v
        if genre == "id":
            self._prendre()
            if valeur.lower() in _FONCTIONS and self._regarder() == ("op", "("):
                self._prendre()
                args = [self._somme()]
                while self._regarder() == ("op", ","):
                    self._prendre()
                    args.append(self._somme())
                self._prendre("op", ")")
                try:
                    return float(_FONCTIONS[valeur.lower()](*args))
                except (TypeError, ValueError) as erreur:
                    raise ValueError("%s : %s(…) refusé (%s)" % (self._ou, valeur,
                                                                 erreur))
            if valeur.lower() in _UNITES:
                return _UNITES[valeur.lower()]
            return self._reference(self._feuille, valeur, self._ou)
        raise ValueError("%s : formule illisible" % self._ou)


# -- la liste de pièces ---------------------------------------------------------------

def _entete(feuille: Feuille):
    """(numéro de ligne, {champ -> colonne}) de la ligne d'en-tête, ou
    None si cette feuille n'en a pas."""
    par_ligne = {}
    for (col, lig), contenu in feuille.cellules.items():
        par_ligne.setdefault(lig, {})[col] = _normaliser(_texte(contenu))
    for lig in sorted(par_ligne):
        colonnes = {}
        for col in sorted(par_ligne[lig]):
            mot = par_ligne[lig][col]
            for champ, alias in _ALIAS.items():
                if mot in alias and champ not in colonnes:
                    colonnes[champ] = col
        if ("rep" in colonnes or "designation" in colonnes) \
                and {"longueur", "largeur"} <= set(colonnes):
            return lig, colonnes
    return None


def lire_pieces(donnees: bytes, feuille: str = None) -> list:
    """Les :class:`~optimiseur.Piece` du tableur ``feuille`` (ou de la
    première feuille qui porte l'en-tête attendu). Lève ``ValueError`` si
    aucune feuille ne convient ou si une cellule ne se lit pas."""
    document = feuilles(donnees)
    if not document:
        raise ValueError("ce document FreeCAD n'a aucun tableur")
    candidates = [feuille] if feuille else sorted(document)
    for nom in candidates:
        if nom not in document:
            raise ValueError("pas de tableur « %s » dans ce document (il y a :"
                             " %s)" % (nom, ", ".join(sorted(document))))
        trouve = _entete(document[nom])
        if trouve:
            return _lire(document, document[nom], *trouve)
    raise ValueError(
        "aucun tableur (%s) n'a de ligne d'en-tête avec une référence, une"
        " longueur et une largeur" % ", ".join(sorted(document)))


def _lire(document: dict, feuille: Feuille, lig_entete: int,
          colonnes: dict) -> list:
    evaluateur = _Evaluateur(document)

    def cellule(champ, lig):
        col = colonnes.get(champ)
        return feuille.cellules.get((col, lig)) if col else None

    def nombre(champ, lig, defaut=None):
        contenu = cellule(champ, lig)
        if contenu is None or not _texte(contenu):
            if defaut is None:
                raise ValueError("%s!%s%d : %s manquante"
                                 % (feuille.nom, colonnes[champ], lig, champ))
            return defaut
        return evaluateur.contenu(feuille, contenu,
                                  "%s!%s%d" % (feuille.nom, colonnes[champ], lig))

    pieces = []
    derniere = max(lig for _, lig in feuille.cellules)
    for lig in range(lig_entete + 1, derniere + 1):
        rep = _texte(cellule("rep", lig) or "")
        designation = _texte(cellule("designation", lig) or "")
        if not rep and not designation:
            continue
        if not _texte(cellule("longueur", lig) or ""):
            continue                  # un titre de section, pas une pièce
        if rep and designation:
            reference = "%s (%s)" % (designation, rep)
        else:
            reference = designation or rep
        fil = _normaliser(_texte(cellule("fil", lig) or ""))
        if fil not in _FILS:
            raise ValueError("%s!%s%d : fil « %s » inconnu (longueur, largeur"
                             " ou indifferent)" % (feuille.nom, colonnes["fil"],
                                                   lig, fil))
        composable = _normaliser(_texte(cellule("composable", lig) or ""))
        pieces.append(opt.Piece(
            reference=reference,
            longueur=nombre("longueur", lig),
            largeur=nombre("largeur", lig),
            epaisseur=nombre("epaisseur", lig, 0.0),
            matiere=_texte(cellule("matiere", lig) or ""),
            quantite=max(1, int(round(nombre("quantite", lig, 1.0)))),
            fil=_FILS[fil],
            composable=composable in ("1", "x", "oui", "vrai", "true", "o")))
    if not pieces:
        raise ValueError("%s : l'en-tête est là, mais aucune pièce dessous"
                         % feuille.nom)
    return pieces


def lire_fichier(chemin: str, feuille: str = None) -> list:
    with open(chemin, "rb") as f:
        return lire_pieces(f.read(), feuille)


def fabriquer(feuilles_: dict) -> bytes:
    """Un .FCStd minimal en mémoire, pour les tests et pour montrer ce que
    le chutier attend. ``feuilles_`` : {nom -> lignes}, chaque ligne une
    liste de cellules (texte, nombre, ou ``(valeur, alias)``)."""
    objets, declarations = [], []
    for nom, lignes in feuilles_.items():
        cellules = []
        for l, ligne in enumerate(lignes, 1):
            for c, valeur in enumerate(ligne):
                alias = None
                if isinstance(valeur, tuple):
                    valeur, alias = valeur
                if valeur is None or valeur == "":
                    continue
                col = chr(ord("A") + c)
                contenu = (str(valeur) if isinstance(valeur, (int, float))
                           or str(valeur).startswith("=") else "'" + str(valeur))
                cellules.append('<Cell address="%s%d" content="%s"%s />' % (
                    col, l, html.escape(contenu, quote=True),
                    ' alias="%s"' % alias if alias else ""))
        objets.append('<Object name="%s">\n<Properties>\n<Property name="cells"'
                      ' type="Spreadsheet::PropertySheet">\n<Cells Count="%d">\n'
                      '%s\n</Cells>\n</Property>\n</Properties>\n</Object>'
                      % (nom, len(cellules), "\n".join(cellules)))
        declarations.append('<Object type="Spreadsheet::Sheet" name="%s" />' % nom)
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<Document>\n'
           '<Objects Count="%d">\n%s\n</Objects>\n<ObjectData Count="%d">\n%s\n'
           '</ObjectData>\n</Document>\n'
           % (len(objets), "\n".join(declarations), len(objets),
              "\n".join(objets)))
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Document.xml", xml)
    return tampon.getvalue()
