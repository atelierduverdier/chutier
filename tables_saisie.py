# -*- coding: utf-8 -*-
"""Les deux tables de saisie — pièces à débiter et stock.

Une table décrit ses colonnes une fois (:class:`Colonne`), le reste
suit : édition, validation, collage depuis un tableur, et la
construction des dataclasses de l'optimiseur. La clé de chaque colonne
porte le nom du champ correspondant, si bien qu'une ligne se convertit
en ``opt.Piece(**valeurs)`` sans table de correspondance à tenir.

Les colonnes « oui/non » et « choix » se dessinent par des délégués, pas
par un widget posé dans chaque cellule : trois widgets par ligne, c'était
soixante-douze widgets pour un débit de vingt-quatre pièces — lourd à
peupler, et une forêt de menus déroulants là où l'œil attend un tableur.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QHeaderView, QLineEdit,
    QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem,
)

import optimiseur as opt

TEXTE, NOMBRE, ENTIER, CHOIX, BOOLEEN, MATIERE = (
    "texte", "nombre", "entier", "choix", "booleen", "matiere")

ROLE_VALEUR = Qt.ItemDataRole.UserRole + 1

FILS_PIECE = (
    (opt.FIL_LONGUEUR, "Longueur"),
    (opt.FIL_LARGEUR, "Largeur"),
    (opt.FIL_INDIFFERENT, "Indifférent"),
)


class Colonne:
    def __init__(self, titre, cle, genre, info="", defaut=None, choix=()):
        self.titre = titre
        self.cle = cle
        self.genre = genre
        self.info = info
        self.defaut = defaut
        self.choix = choix


class ErreurSaisie(ValueError):
    pass


def texte_nombre(valeur) -> str:
    """« 1942 » plutôt que « 1942.0 » — une feuille de débit s'écrit
    comme on la lit au mètre, sans zéro décoratif."""
    try:
        flottant = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    if flottant == int(flottant):
        return str(int(flottant))
    return ("%.3f" % flottant).rstrip("0").rstrip(".")


def _lire_flottant(texte: str, ou: str) -> float:
    try:
        return float(texte.replace(",", ".").strip() or 0)
    except ValueError:
        raise ErreurSaisie("%s : nombre attendu, « %s » lu" % (ou, texte))


def _lire_entier(texte: str, ou: str) -> int:
    try:
        return int(float(texte.replace(",", ".").strip() or 1))
    except ValueError:
        raise ErreurSaisie("%s : entier attendu, « %s » lu" % (ou, texte))


def _vers_booleen(texte: str) -> bool:
    return texte.strip().casefold() in ("1", "x", "vrai", "true", "oui",
                                        "✓", "o")


# -- délégués ------------------------------------------------------------

class DelegateNombre(QStyledItemDelegate):
    """Saisie libre, mais alignée à droite et sans le pinceau du thème
    qui déborde — la validation, elle, est faite par la table (fond rouge
    à la frappe) plutôt qu'en interdisant la touche : refuser un caractère
    silencieusement laisse croire au clavier cassé."""

    def createEditor(self, parent, option, index):
        editeur = QLineEdit(parent)
        editeur.setAlignment(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter)
        return editeur


class DelegateChoix(QStyledItemDelegate):
    """Menu déroulant fermé — il n'apparaît qu'à l'édition de la cellule."""

    def __init__(self, choix, parent=None):
        super().__init__(parent)
        self._choix = list(choix)

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for cle, libelle in self._choix:
            combo.addItem(libelle, cle)
        return combo

    def setEditorData(self, editeur, index):
        cle = index.data(ROLE_VALEUR)
        position = editeur.findData(cle)
        editeur.setCurrentIndex(max(0, position))

    def setModelData(self, editeur, modele, index):
        modele.setData(index, editeur.currentText(),
                       Qt.ItemDataRole.DisplayRole)
        modele.setData(index, editeur.currentData(), ROLE_VALEUR)


class DelegateMatiere(QStyledItemDelegate):
    """Les matières déjà connues du stock, relues à l'ouverture du menu —
    une liste figée à la création de la ligne serait périmée dès le stock
    modifié. Éditable : une matière neuve se tape directement."""

    def __init__(self, matieres_connues, parent=None):
        super().__init__(parent)
        self._matieres = matieres_connues

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.addItems(self._matieres())
        return combo

    def setEditorData(self, editeur, index):
        editeur.setCurrentText(index.data(Qt.ItemDataRole.DisplayRole) or "")

    def setModelData(self, editeur, modele, index):
        modele.setData(index, editeur.currentText().strip(),
                       Qt.ItemDataRole.DisplayRole)


class DelegateBooleen(QStyledItemDelegate):
    """Une case à cocher CENTRÉE, dessinée par le thème.

    La valeur vit dans ``ROLE_VALEUR``, pas dans ``CheckStateRole`` : Qt
    dessinerait alors sa propre case collée au bord gauche, en plus de
    celle-ci.
    """

    def paint(self, peintre, option, index):
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        style_option.text = ""
        widget = style_option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,
                          style_option, peintre, widget)

        bouton = QStyleOptionButton()
        etat = QStyle.StateFlag.State_Enabled
        etat |= (QStyle.StateFlag.State_On if index.data(ROLE_VALEUR)
                 else QStyle.StateFlag.State_Off)
        bouton.state = etat
        taille = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth,
                                   None, widget)
        boite = QRect(0, 0, taille, taille)
        boite.moveCenter(option.rect.center())
        bouton.rect = boite
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                            bouton, peintre, widget)

    def editorEvent(self, evenement, modele, option, index):
        bascule = False
        if evenement.type() == QEvent.Type.MouseButtonRelease:
            bascule = option.rect.contains(evenement.position().toPoint())
        elif evenement.type() == QEvent.Type.KeyPress:
            bascule = evenement.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select)
        if bascule:
            modele.setData(index, not bool(index.data(ROLE_VALEUR)),
                           ROLE_VALEUR)
            return True
        return False


# -- table ---------------------------------------------------------------

class TableEditable(QTableWidget):
    """Table à colonnes déclarées, éditable comme un tableur.

    Ce qu'elle ajoute à QTableWidget : le collage d'un bloc venu d'un
    tableur (le vrai chemin d'entrée d'une feuille de débit), la copie
    dans l'autre sens, la duplication de ligne (cinq lames identiques se
    saisissent une fois), et le fond rouge sur un nombre illisible dès la
    frappe plutôt qu'un message au moment du calcul.
    """

    COLONNES: tuple = ()

    def __init__(self):
        super().__init__(0, len(self.COLONNES))
        self.setHorizontalHeaderLabels([c.titre for c in self.COLONNES])
        for i, colonne in enumerate(self.COLONNES):
            if colonne.info:
                self.horizontalHeaderItem(i).setToolTip(colonne.info)
        entete = self.horizontalHeader()
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(self.COLONNES)):
            entete.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        entete.setHighlightSections(False)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.SelectedClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)

        for i, colonne in enumerate(self.COLONNES):
            if colonne.genre in (NOMBRE, ENTIER):
                self.setItemDelegateForColumn(i, DelegateNombre(self))
            elif colonne.genre == BOOLEEN:
                self.setItemDelegateForColumn(i, DelegateBooleen(self))
            elif colonne.genre == CHOIX:
                self.setItemDelegateForColumn(
                    i, DelegateChoix(colonne.choix, self))

        self.itemChanged.connect(self._verifier_cellule)

    # -- lecture ---------------------------------------------------------

    def lignes_selectionnees(self) -> list:
        return sorted({i.row() for i in self.selectedIndexes()})

    def texte(self, ligne: int, colonne: int) -> str:
        item = self.item(ligne, colonne)
        return item.text().strip() if item is not None else ""

    def valeurs_ligne(self, ligne: int) -> dict:
        """Les champs de la ligne, prêts pour la dataclass du cœur."""
        reference = self.texte(ligne, 0)
        ou = "« %s »" % reference if reference else "ligne %d" % (ligne + 1)
        valeurs = {}
        for i, colonne in enumerate(self.COLONNES):
            item = self.item(ligne, i)
            if colonne.genre in (BOOLEEN,):
                valeurs[colonne.cle] = bool(item.data(ROLE_VALEUR)) if item else False
            elif colonne.genre == CHOIX:
                valeurs[colonne.cle] = (item.data(ROLE_VALEUR) if item
                                        else colonne.defaut)
            elif colonne.genre == NOMBRE:
                valeurs[colonne.cle] = _lire_flottant(self.texte(ligne, i), ou)
            elif colonne.genre == ENTIER:
                valeurs[colonne.cle] = _lire_entier(self.texte(ligne, i) or "1", ou)
            else:
                valeurs[colonne.cle] = self.texte(ligne, i)
        return valeurs

    def lignes_utiles(self) -> list:
        """Les numéros des lignes qui portent une référence — une ligne
        vide n'est pas une erreur, c'est une ligne qu'on n'a pas remplie."""
        return [l for l in range(self.rowCount()) if self.texte(l, 0)]

    # -- écriture --------------------------------------------------------

    def ajouter_ligne(self, **valeurs):
        ligne = self.rowCount()
        self.insertRow(ligne)
        self.poser_ligne(ligne, valeurs)
        return ligne

    def poser_ligne(self, ligne: int, valeurs: dict):
        precedent = self.blockSignals(True)
        for i, colonne in enumerate(self.COLONNES):
            valeur = valeurs.get(colonne.cle, colonne.defaut)
            item = QTableWidgetItem()
            if colonne.info:
                item.setToolTip(colonne.info)
            if colonne.genre == BOOLEEN:
                item.setData(ROLE_VALEUR, bool(valeur))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
            elif colonne.genre == CHOIX:
                libelles = dict(colonne.choix)
                cle = valeur if valeur in libelles else colonne.defaut
                item.setData(ROLE_VALEUR, cle)
                item.setText(libelles.get(cle, ""))
            elif colonne.genre in (NOMBRE, ENTIER):
                item.setText(texte_nombre(valeur if valeur is not None else ""))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            else:
                item.setText("" if valeur is None else str(valeur))
            self.setItem(ligne, i, item)
        self.blockSignals(precedent)
        self._verifier_ligne(ligne)

    def remplir(self, objets: list):
        precedent = self.blockSignals(True)
        self.setRowCount(0)
        self.blockSignals(precedent)
        for objet in objets:
            self.ajouter_ligne(**{c.cle: getattr(objet, c.cle)
                                  for c in self.COLONNES})

    # -- actions de ligne ------------------------------------------------

    def dupliquer_selection(self):
        """Cinq lames identiques : on en saisit une, on duplique."""
        lignes = self.lignes_selectionnees()
        if not lignes:
            return
        for decalage, source in enumerate(lignes):
            cible = lignes[-1] + 1 + decalage
            self.insertRow(cible)
            copie = {}
            for i, colonne in enumerate(self.COLONNES):
                item = self.item(source, i)
                if item is None:
                    continue
                copie[colonne.cle] = (item.data(ROLE_VALEUR)
                                      if colonne.genre in (BOOLEEN, CHOIX)
                                      else item.text())
            self.poser_ligne(cible, copie)
        self.selectRow(lignes[-1] + 1)

    def supprimer_selection(self):
        for ligne in reversed(self.lignes_selectionnees()):
            self.removeRow(ligne)

    def vider_cellules(self):
        for index in self.selectedIndexes():
            colonne = self.COLONNES[index.column()]
            item = self.item(index.row(), index.column())
            if item is None or colonne.genre == BOOLEEN:
                continue
            if colonne.genre == CHOIX:
                continue
            item.setText("")

    # -- presse-papiers --------------------------------------------------

    def copier(self):
        index = self.selectedIndexes()
        if not index:
            return
        lignes = sorted({i.row() for i in index})
        colonnes = sorted({i.column() for i in index})
        bloc = []
        for ligne in lignes:
            bloc.append("\t".join(self._texte_cellule(ligne, c)
                                  for c in colonnes))
        QApplication.clipboard().setText("\n".join(bloc))

    def _texte_cellule(self, ligne: int, colonne: int) -> str:
        item = self.item(ligne, colonne)
        if item is None:
            return ""
        if self.COLONNES[colonne].genre == BOOLEEN:
            return "1" if item.data(ROLE_VALEUR) else "0"
        return item.text()

    def coller(self, texte: str = None):
        """Un bloc venu d'un tableur, collé à partir de la cellule
        courante. C'est le vrai chemin d'entrée d'une feuille de débit :
        elle existe presque toujours ailleurs avant d'arriver ici.

        ``texte`` n'est fourni que par les tests ; l'interface colle ce
        qu'il y a dans le presse-papiers."""
        if texte is None:
            texte = QApplication.clipboard().text()
        if not texte.strip():
            return
        depart = self.currentIndex()
        ligne0 = max(0, depart.row())
        colonne0 = max(0, depart.column())
        for decalage_l, ligne_texte in enumerate(texte.rstrip("\n").split("\n")):
            cellules = (ligne_texte.split("\t") if "\t" in ligne_texte
                        else ligne_texte.split(";"))
            ligne = ligne0 + decalage_l
            while ligne >= self.rowCount():
                self.ajouter_ligne()
            for decalage_c, cellule in enumerate(cellules):
                colonne = colonne0 + decalage_c
                if colonne >= self.columnCount():
                    break
                self._poser_cellule(ligne, colonne, cellule.strip())
        self._verifier_tout()

    def _poser_cellule(self, ligne: int, colonne: int, texte: str):
        descripteur = self.COLONNES[colonne]
        item = self.item(ligne, colonne)
        if item is None:
            return
        if descripteur.genre == BOOLEEN:
            item.setData(ROLE_VALEUR, _vers_booleen(texte))
        elif descripteur.genre == CHOIX:
            for cle, libelle in descripteur.choix:
                if texte.casefold() in (cle.casefold(), libelle.casefold()):
                    item.setData(ROLE_VALEUR, cle)
                    item.setText(libelle)
                    break
        else:
            item.setText(texte)

    def keyPressEvent(self, evenement):
        if evenement.matches(QKeySequence.StandardKey.Paste):
            self.coller()
            return
        if evenement.matches(QKeySequence.StandardKey.Copy):
            self.copier()
            return
        if evenement.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if evenement.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.supprimer_selection()
            else:
                self.vider_cellules()
            return
        super().keyPressEvent(evenement)

    # -- validation ------------------------------------------------------

    def _verifier_cellule(self, item):
        self._verifier_ligne(item.row())

    def _verifier_ligne(self, ligne: int):
        precedent = self.blockSignals(True)
        for i, colonne in enumerate(self.COLONNES):
            if colonne.genre not in (NOMBRE, ENTIER):
                continue
            item = self.item(ligne, i)
            if item is None:
                continue
            texte = item.text().strip()
            valide = True
            if texte:
                try:
                    float(texte.replace(",", "."))
                except ValueError:
                    valide = False
            item.setBackground(QColor(0, 0, 0, 0) if valide
                               else QColor(192, 57, 43, 90))
            item.setToolTip(colonne.info if valide
                            else "« %s » n'est pas un nombre." % texte)
        self.blockSignals(precedent)

    def _verifier_tout(self):
        for ligne in range(self.rowCount()):
            self._verifier_ligne(ligne)


class TablePieces(TableEditable):
    COLONNES = (
        Colonne("Référence", "reference", TEXTE,
                "Nom de la pièce. C'est lui qui lui donne sa couleur sur"
                " le plan — deux pièces de même nom sont de même teinte.",
                ""),
        Colonne("Longueur", "longueur", NOMBRE,
                "En mm, le long du fil du bois.", 0),
        Colonne("Largeur", "largeur", NOMBRE, "En mm, en travers du fil.", 0),
        Colonne("Épaisseur", "epaisseur", NOMBRE,
                "En mm, cote FINIE. Le brut se rabote : une planche plus"
                " épaisse convient, jamais une plus mince.", 18),
        Colonne("Matière", "matiere", MATIERE,
                "Doit correspondre à une matière du stock — pièces et"
                " planches sont appariées par matière.", ""),
        Colonne("Qté", "quantite", ENTIER, "Nombre d'exemplaires.", 1),
        Colonne("Fil", "fil", CHOIX,
                "Où court le fil du bois dans la pièce. « Indifférent »"
                " autorise le chutier à la pivoter.",
                opt.FIL_LONGUEUR, FILS_PIECE),
        Colonne("Composable", "composable", BOOLEEN,
                "Trop large pour tout brut, cette pièce peut se"
                " reconstituer en collant plusieurs lames côte à côte"
                " (ou en tenon-rainure) plutôt que de rester non placée.",
                False),
    )

    def __init__(self, matieres_connues):
        super().__init__()
        self.setItemDelegateForColumn(4, DelegateMatiere(matieres_connues, self))

    def pieces(self) -> list:
        return [opt.Piece(**self.valeurs_ligne(l)) for l in self.lignes_utiles()]

    def resume(self) -> str:
        try:
            pieces = self.pieces()
        except ErreurSaisie as erreur:
            return "⚠ %s" % erreur
        if not pieces:
            return "Aucune pièce — ajoutez une ligne, collez un tableau" \
                   " (Ctrl+V) ou importez un CSV."
        exemplaires = sum(p.quantite for p in pieces)
        matieres = sorted({p.matiere for p in pieces if p.matiere})
        surface = sum(p.aire * p.quantite for p in pieces)
        return ("%d référence(s), %d exemplaire(s) · %s · surface des"
                " pièces %s m²" % (len(pieces), exemplaires,
                            ", ".join(matieres) or "matière non renseignée",
                            opt._m2(surface)))


class TableStock(TableEditable):
    """Le stock. Sa colonne Matière propose ses PROPRES matières : c'est
    ici qu'on les invente, mais une fois « douglas » écrit sur une ligne,
    le retaper à la main sur les suivantes est l'occasion rêvée d'écrire
    « Douglas » ou « douglas » avec une espace de trop — deux matières
    qui ne s'apparient plus."""

    COLONNES = (
        Colonne("Référence", "reference", TEXTE,
                "Nom du morceau de stock, tel qu'il est repéré à"
                " l'atelier.", ""),
        Colonne("Longueur", "longueur", NOMBRE,
                "En mm, le long du fil.", 0),
        Colonne("Largeur", "largeur", NOMBRE, "En mm, en travers du fil.", 0),
        Colonne("Épaisseur", "epaisseur", NOMBRE,
                "En mm, épaisseur BRUTE disponible.", 18),
        Colonne("Matière", "matiere", MATIERE,
                "Le même mot que dans les pièces, sinon rien ne s'apparie.",
                ""),
        Colonne("Qté", "quantite", ENTIER,
                "Combien de morceaux identiques. Sans effet sur un profil"
                " de catalogue, qui n'est pas borné.", 1),
        Colonne("Chute", "chute", BOOLEEN,
                "Un morceau déjà en atelier, à écouler EN PRIORITÉ sur"
                " les planches neuves. Jamais compté à l'achat.", False),
        Colonne("A un fil", "fil", BOOLEEN,
                "Décocher pour un panneau (contreplaqué, MDF) : le"
                " chutier peut alors pivoter librement les pièces.", True),
        Colonne("Catalogue", "illimite", BOOLEEN,
                "Une section qu'on peut ACHETER, pas des planches déjà"
                " là : la quantité ne borne plus rien, le chutier en"
                " prend autant qu'il faut et compte l'achat.", False),
        Colonne("Prix", "prix", NOMBRE,
                "Coût d'UNE planche à ces cotes, pas un prix au mètre."
                " Départage plusieurs profils de catalogue par le coût"
                " réel — laisser à 0 pour ne pas en tenir compte.", 0),
    )

    def __init__(self):
        super().__init__()
        self.setItemDelegateForColumn(4, DelegateMatiere(self.matieres, self))

    def stock(self) -> list:
        return [opt.Planche(**self.valeurs_ligne(l))
                for l in self.lignes_utiles()]

    def matieres(self) -> list:
        return sorted({self.texte(l, 4) for l in range(self.rowCount())
                       if self.texte(l, 4)})

    def resume(self) -> str:
        try:
            stock = self.stock()
        except ErreurSaisie as erreur:
            return "⚠ %s" % erreur
        if not stock:
            return "Stock vide — le débit n'aura rien où se poser."
        chutes = sum(s.quantite for s in stock if s.chute)
        catalogue = sum(1 for s in stock if s.illimite)
        surface = sum(s.aire * s.quantite for s in stock if not s.illimite)
        details = ["%d référence(s)" % len(stock)]
        if chutes:
            details.append("%d chute(s) à écouler d'abord" % chutes)
        if catalogue:
            details.append("%d profil(s) de catalogue" % catalogue)
        details.append("surface en atelier %s m²" % opt._m2(surface))
        return " · ".join(details)
