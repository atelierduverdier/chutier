# -*- coding: utf-8 -*-
"""Couleurs, tuiles de bilan et ornements communs à l'interface.

Rien de métier ici : cette couche ne connaît ni l'optimiseur ni les
tables, seulement Qt et le thème du système. Les couleurs de l'IHM se
dérivent de la palette (Christophe travaille sur fond sombre) ; seules
celles du PLAN sont fixes — un plan de découpe est une feuille de
papier, il reste clair pour être imprimé et lu à l'établi.
"""

from __future__ import annotations

import zlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)

# -- couleurs du plan (feuille de papier, indépendantes du thème) --------

PLAN_PAPIER = QColor("#faf8f4")        # le brut non débité : la perte
PLAN_BORD = QColor("#2f3540")          # ardoise maison
PLAN_CHUTE = QColor("#c3c8cf")
PLAN_CHUTE_TRAIT = QColor("#767c85")
PLAN_DEFAUT = QColor("#c98b84")        # nœud, fente, recoupe : bois écarté
PLAN_DEFAUT_TRAIT = QColor("#a85a52")
PLAN_ETABLI_SOMBRE = QColor("#3b4048")  # l'établi, derrière les planches
PLAN_ETABLI_CLAIR = QColor("#cfccc6")
PLAN_TRAIT_SCIE = QColor("#c0392b")
PLAN_CARTOUCHE = QColor("#2f3540")

ORANGE = QColor("#ff8a00")             # l'orange de l'Atelier du Verdier
ALERTE = QColor("#c0392b")

# Douze teintes tenues à l'écart les unes des autres : deux références
# voisines ne doivent pas se ressembler. Prises en pastel, elles portent
# du texte ardoise sans le noyer.
_TEINTES = (14, 38, 60, 92, 120, 152, 178, 200, 224, 262, 288, 322)


_NUANCES = ((48, 250), (80, 232), (112, 214))
_CASES = len(_TEINTES) * len(_NUANCES)


def _couleur_case(case: int) -> QColor:
    saturation, clarte = _NUANCES[case // len(_TEINTES)]
    return QColor.fromHsv(_TEINTES[case % len(_TEINTES)], saturation, clarte)


def couleur_piece(reference: str) -> QColor:
    """La teinte d'une référence prise isolément.

    ``hash()`` d'une chaîne est **salé au démarrage** de Python : il
    donnait une couleur différente à chaque lancement, alors que le
    propos est justement de reconnaître une pièce d'une séance à
    l'autre. ``crc32`` ne bouge pas.
    """
    return _couleur_case(zlib.crc32(reference.encode("utf-8")) % _CASES)


def palette_pieces(references) -> dict:
    """Une teinte par référence, toutes DIFFÉRENTES entre elles.

    Le seul hachage ne suffit pas : « montant » et « taquet » tombaient
    sur le même vert, et deux pièces indiscernables sur le plan valent
    moins qu'un plan en noir et blanc. Les collisions se résolvent en
    sondant les cases suivantes, dans l'ordre des références triées —
    déterministe, donc stable tant que la liste de pièces ne change pas.
    """
    prises, teintes_servies, palette = set(), set(), {}
    for reference in sorted(references):
        depart = zlib.crc32(reference.encode("utf-8")) % _CASES
        case = depart
        for saut in range(_CASES):
            candidate = (depart + saut) % _CASES
            if candidate in prises:
                continue
            # Tant qu'il reste une teinte inutilisée, ne pas en resservir
            # une : c'est la TEINTE qui distingue à l'œil, pas la nuance.
            # Deux verts d'éclat voisin se valent sur le plan — le premier
            # essai ne gardait que la case libre, et « montant » comme
            # « taquet » sortaient du même vert.
            if (len(teintes_servies) < len(_TEINTES)
                    and candidate % len(_TEINTES) in teintes_servies):
                continue
            case = candidate
            break
        prises.add(case)
        teintes_servies.add(case % len(_TEINTES))
        palette[reference] = _couleur_case(case)
    return palette


def fond_etabli(widget=None) -> QColor:
    """Le plan de travail derrière les planches. Le plan lui-même reste
    clair — c'est du papier qu'on imprime — mais ce qui l'entoure suit le
    thème, sinon il pose une tache sombre au milieu d'une interface
    claire (ou l'inverse)."""
    return PLAN_ETABLI_SOMBRE if sombre(widget) else PLAN_ETABLI_CLAIR


def encre_marge(widget=None) -> QColor:
    """L'encre des textes posés SUR l'établi (titres de planche,
    étiquettes qui débordent d'une pièce) — l'ardoise du plan y serait
    illisible sur fond sombre, le papier illisible sur fond clair."""
    return PLAN_PAPIER if sombre(widget) else PLAN_BORD


def pastille(couleur: QColor, hachure: bool = False, taille: int = 14) -> QIcon:
    """Le carré de couleur d'une entrée de légende, dessiné comme sur le
    plan — même teinte, même hachure pour une chute."""
    image = QPixmap(taille, taille)
    image.fill(Qt.GlobalColor.transparent)
    peintre = QPainter(image)
    peintre.setBrush(QBrush(couleur, Qt.BrushStyle.BDiagPattern if hachure
                            else Qt.BrushStyle.SolidPattern))
    if hachure:
        peintre.fillRect(0, 0, taille, taille, PLAN_PAPIER)
        peintre.setBrush(QBrush(couleur, Qt.BrushStyle.BDiagPattern))
    peintre.setPen(QPen(PLAN_BORD, 1))
    peintre.drawRect(0, 0, taille - 1, taille - 1)
    peintre.end()
    return QIcon(image)


def sombre(widget=None) -> bool:
    """Le thème courant est-il sombre ? Mesuré, jamais supposé — le poste
    tourne sur #1a1e23.

    ``widget`` : lire SA palette plutôt que celle de l'application. Un
    thème de bureau peut habiller les widgets un par un au moment où ils
    sont créés, sans que ``QApplication.palette()`` en sache rien — le
    fond du plan se retrouvait alors clair au milieu d'une interface
    sombre.
    """
    palette = widget.palette() if widget is not None else QApplication.palette()
    return palette.window().color().lightness() < 128


def icone(*noms: str) -> QIcon:
    """La première icône du thème système qui existe, sinon rien — les
    boutons portent tous leur texte, l'icône n'est qu'un repère."""
    for nom in noms:
        ico = QIcon.fromTheme(nom)
        if not ico.isNull():
            return ico
    return QIcon()


# -- ornements -----------------------------------------------------------

STYLE_POIGNEE = """
    QSplitter::handle { background: palette(mid); }
    QSplitter::handle:hover { background: palette(highlight); }
"""


def separateur() -> QFrame:
    trait = QFrame()
    trait.setFrameShape(QFrame.Shape.HLine)
    trait.setFrameShadow(QFrame.Shadow.Plain)
    trait.setStyleSheet("color: palette(mid);")
    return trait


def titre(texte: str) -> QLabel:
    etiquette = QLabel(texte)
    police = etiquette.font()
    police.setBold(True)
    etiquette.setFont(police)
    return etiquette


def discret(texte: str) -> QLabel:
    """Une ligne d'explication : lisible, mais qui ne réclame pas l'œil."""
    etiquette = QLabel(texte)
    etiquette.setWordWrap(True)
    etiquette.setStyleSheet("color: palette(mid);")
    police = etiquette.font()
    police.setPointSizeF(max(7.0, police.pointSizeF() - 0.5))
    etiquette.setFont(police)
    return etiquette


class Tuile(QFrame):
    """Un chiffre du bilan : la valeur en grand, son nom en petit.

    Six phrases collées par des tirets cadratins ne se lisent pas d'un
    coup d'œil ; six tuiles, si. Le ton ``alerte`` n'est mis QUE sur ce
    qui demande une décision (des pièces non placées) — colorier un
    rendement reviendrait à juger un débit sans connaître le projet.
    """

    def __init__(self, libelle: str, info: str = ""):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)
        if info:
            self.setToolTip(info)

        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(10, 6, 10, 6)
        colonne.setSpacing(0)

        self._valeur = QLabel("—")
        police = self._valeur.font()
        police.setPointSizeF(police.pointSizeF() + 5)
        police.setWeight(QFont.Weight.DemiBold)
        self._valeur.setFont(police)

        self._libelle = QLabel(libelle.upper())
        petite = self._libelle.font()
        petite.setPointSizeF(max(7.0, petite.pointSizeF() - 1.5))
        petite.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        self._libelle.setFont(petite)
        self._libelle.setStyleSheet("color: palette(mid);")

        self._detail = QLabel("")
        detail = self._detail.font()
        detail.setPointSizeF(max(7.0, detail.pointSizeF() - 1.0))
        self._detail.setFont(detail)
        self._detail.setStyleSheet("color: palette(mid);")

        colonne.addWidget(self._libelle)
        colonne.addWidget(self._valeur)
        colonne.addWidget(self._detail)
        self.ton("neutre")

    def poser(self, valeur: str, detail: str = "", ton: str = "neutre"):
        self._valeur.setText(valeur)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        self.ton(ton)

    def ton(self, ton: str):
        if ton == "alerte":
            couleur = ALERTE.name()
            bord = ALERTE.name()
        elif ton == "accent":
            couleur = (ORANGE.name() if sombre(self)
                       else ORANGE.darker(115).name())
            bord = "palette(mid)"
        else:
            couleur = "palette(text)"
            bord = "palette(mid)"
        self.setStyleSheet(
            "QFrame { background: palette(base); border: 1px solid %s;"
            " border-radius: 5px; }" % bord)
        self._valeur.setStyleSheet("color: %s; border: none;" % couleur)
        self._libelle.setStyleSheet("color: palette(mid); border: none;")
        self._detail.setStyleSheet("color: palette(mid); border: none;")


class BandeauBilan(QFrame):
    """La rangée de tuiles au-dessus du plan."""

    def __init__(self):
        super().__init__()
        ligne = QHBoxLayout(self)
        ligne.setContentsMargins(0, 0, 0, 0)
        ligne.setSpacing(8)

        self.posees = Tuile("Pièces posées",
                            "Exemplaires placés sur les planches, sur le"
                            " total demandé.")
        self.rendement = Tuile("Rendement",
                               "Surface des pièces débitées rapportée à la"
                               " surface des planches entamées.")
        self.planches = Tuile("Planches entamées",
                              "Nombre de morceaux de stock ouverts, et"
                              " combien étaient des chutes.")
        self.pertes = Tuile("Pertes",
                            "Sciure et rebuts trop petits pour faire une"
                            " chute réutilisable.")
        self.chutes = Tuile("Chutes créées",
                            "Restes assez grands pour retourner au stock.")
        self.achat = Tuile("À acheter",
                           "Planches neuves à prendre, et leur coût si les"
                           " prix sont renseignés.")

        for tuile in (self.posees, self.rendement, self.planches,
                      self.pertes, self.chutes, self.achat):
            ligne.addWidget(tuile, stretch=1)

    def vider(self):
        for tuile in (self.posees, self.rendement, self.planches,
                      self.pertes, self.chutes, self.achat):
            tuile.poser("—")
