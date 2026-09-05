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
    QAbstractItemDelegate, QAbstractItemView, QApplication, QComboBox, QHeaderView, QLineEdit,
    QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem,
)

import optimiseur as opt
from saisie import (  # noqa: F401 — réexportés, l'interface les prend ici
    SYNTAXE_DEFAUTS, ErreurSaisie, lire_defauts, texte_contour,
    texte_defauts, texte_nombre,
)

TEXTE, NOMBRE, ENTIER, CHOIX, BOOLEEN, MATIERE, DEFAUTS, PLANCHE, CONTOUR = (
    "texte", "nombre", "entier", "choix", "booleen", "matiere", "defauts",
    "planche", "contour")

ROLE_VALEUR = Qt.ItemDataRole.UserRole + 1
ROLE_TROUS = Qt.ItemDataRole.UserRole + 2      # les trous d'un contour

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


class DelegateListe(QStyledItemDelegate):
    """Un texte libre, avec sous la main une liste relue à l'ouverture du
    menu — les matières connues du stock, ou ses références. Une liste
    figée à la création de la ligne serait périmée dès le stock modifié.
    Éditable : une valeur neuve se tape directement."""

    def __init__(self, source, parent=None, vide=""):
        super().__init__(parent)
        self._source = source
        self._vide = vide

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        if self._vide:
            combo.addItem(self._vide, "")
        combo.addItems(self._source())
        return combo

    def setEditorData(self, editeur, index):
        editeur.setCurrentText(index.data(Qt.ItemDataRole.DisplayRole) or "")

    def setModelData(self, editeur, modele, index):
        texte = editeur.currentText().strip()
        if self._vide and texte == self._vide:
            texte = ""
        modele.setData(index, texte, Qt.ItemDataRole.DisplayRole)


DelegateMatiere = DelegateListe


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
    # Colonnes rarement remplies, repliables — jamais si une ligne s'en
    # sert : on ne cache pas une valeur saisie.
    AVANCEES: tuple = ()

    def valider_edition(self):
        """Pousse dans la cellule ce que l'éditeur ouvert contient, et le
        ferme — ce qu'Entrée aurait fait. À appeler avant de LIRE la
        table pour calculer, enregistrer ou fermer : sans quoi la valeur
        en cours de frappe n'existe que dans l'éditeur."""
        if self.state() != QAbstractItemView.State.EditingState:
            return
        editeur = self.focusWidget()
        if editeur is None or editeur is self:
            return
        self.commitData(editeur)
        self.closeEditor(editeur, QAbstractItemDelegate.EndEditHint.NoHint)

    def montrer_avancees(self, montrer: bool):
        for i in self.AVANCEES:
            utilisee = any(self._valeur_non_defaut(l, i)
                           for l in range(self.rowCount()))
            self.setColumnHidden(i, not (montrer or utilisee))

    def _valeur_non_defaut(self, ligne: int, colonne: int) -> bool:
        descripteur = self.COLONNES[colonne]
        item = self.item(ligne, colonne)
        if item is None:
            return False
        if descripteur.genre == BOOLEEN:
            return bool(item.data(ROLE_VALEUR)) != bool(descripteur.defaut)
        if descripteur.genre == CHOIX:
            return item.data(ROLE_VALEUR) != descripteur.defaut
        if descripteur.genre == CONTOUR:
            return bool(item.data(ROLE_VALEUR))
        texte = item.text().strip()
        if descripteur.genre in (NOMBRE, ENTIER):
            try:
                return float(texte.replace(",", ".") or 0) != float(
                    descripteur.defaut or 0)
            except ValueError:
                return True
        return bool(texte)

    def __init__(self):
        super().__init__(0, len(self.COLONNES))
        self.setHorizontalHeaderLabels([c.titre for c in self.COLONNES])
        for i, colonne in enumerate(self.COLONNES):
            if colonne.info:
                self.horizontalHeaderItem(i).setToolTip(colonne.info)
        entete = self.horizontalHeader()
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        entete.setMinimumSectionSize(28)
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

    # Largeur en dessous de laquelle la référence ne se lit plus.
    REFERENCE_MINI = 100

    #: Pixels ajoutés à ce que Qt calcule, pour les colonnes de texte.
    #: « ResizeToContents » dimensionne au plus juste — et selon le thème,
    #: le cadre de la cellule mange les derniers pixels : « Douglas »
    #: s'affichait « Doug… » dans une colonne pourtant taillée sur lui
    #: (Breeze sombre, 4 septembre 2026). Les colonnes de nombres et de
    #: cases n'en ont pas besoin, et treize colonnes élargies pour rien
    #: feraient défiler la table en travers.
    AIR_TEXTE = 12

    #: Les genres dont le contenu est du texte à lire en entier.
    _GENRES_TEXTE = (TEXTE, MATIERE, CHOIX, PLANCHE, DEFAUTS, CONTOUR)

    def sizeHintForColumn(self, colonne: int) -> int:
        largeur = super().sizeHintForColumn(colonne)
        if largeur <= 0 or not 0 <= colonne < len(self.COLONNES):
            return largeur
        if self.COLONNES[colonne].genre in self._GENRES_TEXTE:
            return largeur + self.AIR_TEXTE
        return largeur

    def resizeEvent(self, evenement):
        """Onze colonnes dans un panneau de 560 px : étirée, la référence
        — la seule qu'on lise pour se repérer — tombait à « sap… » pendant
        que les cases à cocher gardaient leur aise. Quand la place manque,
        elle passe en largeur fixe et la table défile."""
        super().resizeEvent(evenement)
        entete = self.horizontalHeader()
        autres = sum(self.columnWidth(i) for i in range(1, self.columnCount()))
        if self.viewport().width() - autres < self.REFERENCE_MINI:
            entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(0, self.REFERENCE_MINI)
        else:
            entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    # -- annuler / refaire ------------------------------------------------

    def instantane(self) -> list:
        """La table telle qu'elle est, cellule par cellule, texte ou donnée
        — y compris ce qui n'est pas (encore) un nombre valide. C'est ce
        qu'Annuler restaure : la saisie, pas une interprétation."""
        lignes = []
        for l in range(self.rowCount()):
            valeurs = {}
            for i, colonne in enumerate(self.COLONNES):
                item = self.item(l, i)
                if item is None:
                    continue
                if colonne.genre in (BOOLEEN, CHOIX):
                    valeurs[colonne.cle] = item.data(ROLE_VALEUR)
                elif colonne.genre == CONTOUR:
                    valeurs[colonne.cle] = item.data(ROLE_VALEUR)
                    valeurs["trous"] = item.data(ROLE_TROUS)
                else:
                    valeurs[colonne.cle] = item.text()
            lignes.append(valeurs)
        return lignes

    def restaurer(self, instantane: list):
        precedent = self.blockSignals(True)
        self.setRowCount(0)
        for valeurs in instantane:
            ligne = self.rowCount()
            self.insertRow(ligne)
            self.poser_ligne(ligne, valeurs)
        self.blockSignals(precedent)

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
            elif colonne.genre == DEFAUTS:
                # trois champs d'un coup ; la largeur, lue plus tôt dans la
                # ligne, donne sa hauteur à une bande « 1200-1280 »
                valeurs.update(lire_defauts(self.texte(ligne, i), ou,
                                            valeurs.get("largeur", 0.0)))
            elif colonne.genre == CONTOUR:
                valeurs[colonne.cle] = tuple(item.data(ROLE_VALEUR) or ()) \
                    if item else ()
                valeurs["trous"] = tuple(item.data(ROLE_TROUS) or ()) \
                    if item else ()
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
            elif colonne.genre == CONTOUR:
                # Le contour vit dans la donnée de la cellule, pas dans son
                # texte : il ne se tape pas, il s'importe d'un SVG. Les
                # trous l'accompagnent, dans un second rôle.
                contour = tuple(tuple(p) for p in (valeur or ()))
                trous = tuple(tuple(tuple(p) for p in t)
                              for t in (valeurs.get("trous") or ()))
                item.setData(ROLE_VALEUR, contour)
                item.setData(ROLE_TROUS, trous)
                item.setText(texte_contour(contour, trous))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
            elif colonne.genre in (NOMBRE, ENTIER):
                item.setText(texte_nombre(valeur if valeur is not None else ""))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            else:
                item.setText("" if valeur is None else str(valeur))
            self.setItem(ligne, i, item)
        self._verrouiller_cotes(ligne, valeurs.get("contour"))
        self.blockSignals(precedent)
        self._verifier_ligne(ligne)

    def _verrouiller_cotes(self, ligne: int, contour) -> None:
        """Une chute biscornue tient ses cotes de son polygone : la table
        acceptait qu'on tape 999 × 888 sur une ligne à contour, le débit
        continuait de scier 400 × 300 — un chiffre faux sous les yeux.
        Les deux cellules passent en lecture seule, et le disent."""
        if not any(c.genre == CONTOUR for c in self.COLONNES) or not contour:
            return
        for i, colonne in enumerate(self.COLONNES):
            if colonne.cle not in ("longueur", "largeur"):
                continue
            item = self.item(ligne, i)
            if item is None:
                continue
            item.setFlags(Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
            item.setToolTip("Cote donnée par le contour : c'est la boîte du"
                            " polygone. Effacez le contour pour la saisir"
                            " à la main.")

    def remplir(self, objets: list):
        precedent = self.blockSignals(True)
        self.setRowCount(0)
        self.blockSignals(precedent)
        for objet in objets:
            valeurs = {c.cle: (texte_defauts(objet) if c.genre == DEFAUTS
                               else getattr(objet, c.cle))
                       for c in self.COLONNES}
            if any(c.genre == CONTOUR for c in self.COLONNES):
                valeurs["trous"] = getattr(objet, "trous", ())
            self.ajouter_ligne(**valeurs)

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
                                      if colonne.genre in (BOOLEEN, CHOIX,
                                                           CONTOUR)
                                      else item.text())
                if colonne.genre == CONTOUR:
                    copie["trous"] = item.data(ROLE_TROUS)
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
            if colonne.genre == CONTOUR:
                # Un contour ne se tape ni ne se colle : Suppr effaçait
                # « ◇ 6 pts » en laissant la forme dans la donnée de la
                # cellule — la table montrait un rectangle, la fraise
                # découpait toujours le polygone. Ici, on efface les deux.
                item.setData(ROLE_VALEUR, ())
                item.setData(ROLE_TROUS, ())
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
        elif descripteur.genre == CONTOUR:
            return                      # un contour ne se colle pas
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
            if colonne.genre not in (NOMBRE, ENTIER, DEFAUTS):
                continue
            item = self.item(ligne, i)
            if item is None:
                continue
            texte = item.text().strip()
            valide, plainte = True, ""
            if texte and colonne.genre == DEFAUTS:
                try:
                    lire_defauts(texte, "", 0.0)
                except ErreurSaisie as erreur:
                    valide, plainte = False, str(erreur).lstrip(" :")
            elif texte:
                try:
                    float(texte.replace(",", "."))
                except ValueError:
                    valide = False
                    plainte = "« %s » n'est pas un nombre." % texte
            item.setBackground(QColor(0, 0, 0, 0) if valide
                               else QColor(192, 57, 43, 90))
            item.setToolTip(colonne.info if valide else plainte)
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
        Colonne("Long.", "longueur", NOMBRE,
                "Longueur en mm, le long du fil du bois.", 0),
        Colonne("Larg.", "largeur", NOMBRE,
                "Largeur en mm, en travers du fil.", 0),
        Colonne("Ép.", "epaisseur", NOMBRE,
                "Épaisseur en mm, cote FINIE. Le brut se rabote : une"
                " planche plus épaisse convient, jamais une plus mince.", 18),
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
        Colonne("Planche", "planche", PLANCHE,
                "Imposer la ligne de stock où tailler cette pièce (sa"
                " référence) — vide, le chutier choisit. Se remplit aussi"
                " d'un clic droit sur la pièce, dans le plan.", ""),
        Colonne("Contour", "contour", CONTOUR,
                "Une forme quelconque à découper à la CNC, importée d'un"
                " SVG (Fichier → Importer des contours). Longueur et"
                " largeur sont alors sa boîte englobante. Dès qu'une pièce"
                " d'une matière a un contour, toute cette matière est"
                " imbriquée à la fraise au lieu d'être sciée.", ()),
    )

    COLONNE_PLANCHE = 8
    COLONNE_CONTOUR = 9
    AVANCEES = (7, 8, 9)             # Composable, Planche, Contour

    def __init__(self, matieres_connues, references_stock=lambda: []):
        super().__init__()
        self.setItemDelegateForColumn(4, DelegateListe(matieres_connues, self))
        self.setItemDelegateForColumn(
            self.COLONNE_PLANCHE,
            DelegateListe(references_stock, self, vide="(au choix)"))

    def imposer_planche(self, reference_piece: str, reference_planche: str):
        """Écrit ``reference_planche`` sur toutes les lignes de la pièce
        nommée — l'effet du clic droit sur le plan."""
        for ligne in self.lignes_utiles():
            if self.texte(ligne, 0) == reference_piece:
                self.item(ligne, self.COLONNE_PLANCHE).setText(reference_planche)

    def matieres(self) -> list:
        """Les matières écrites dans les pièces — ce que le stock doit
        proposer, puisque les deux doivent employer le même mot."""
        return sorted({self.texte(l, 4) for l in range(self.rowCount())
                       if self.texte(l, 4)})

    def pieces(self) -> list:
        return [opt.Piece(**self.valeurs_ligne(l)) for l in self.lignes_utiles()]

    def resume(self) -> str:
        try:
            pieces = self.pieces()
        except ErreurSaisie as erreur:
            return "⚠ %s" % erreur
        if not pieces:
            return "Aucune pièce — ajoutez une ligne, collez un tableau" \
                   " (Ctrl+V), importez un CSV ou des contours SVG."
        exemplaires = sum(p.quantite for p in pieces)
        matieres = sorted({p.matiere for p in pieces if p.matiere})
        surface = sum(p.aire * p.quantite for p in pieces)
        contours = sum(1 for p in pieces if p.contour)
        return ("%d référence(s), %d exemplaire(s)%s · %s · surface des"
                " pièces %s m²" % (len(pieces), exemplaires,
                            " dont %d contour(s) à imbriquer" % contours
                            if contours else "",
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
        Colonne("Long.", "longueur", NOMBRE,
                "Longueur en mm, le long du fil.", 0),
        Colonne("Larg.", "largeur", NOMBRE,
                "Largeur en mm, en travers du fil.", 0),
        Colonne("Ép.", "epaisseur", NOMBRE,
                "Épaisseur BRUTE disponible, en mm.", 18),
        Colonne("Matière", "matiere", MATIERE,
                "Le même mot que dans les pièces, sinon rien ne s'apparie.",
                ""),
        Colonne("Qté", "quantite", ENTIER,
                "Combien de morceaux identiques. Sans effet sur un profil"
                " de catalogue, qui n'est pas borné.", 1),
        Colonne("Chute", "chute", BOOLEEN,
                "Un morceau déjà en atelier, à écouler EN PRIORITÉ sur"
                " les planches neuves. Jamais compté à l'achat.", False),
        Colonne("Atelier", "atelier", BOOLEEN,
                "Cette ligne vit dans le stock COMMUN de l'atelier,"
                " retrouvé d'un projet à l'autre — pas dans ce projet."
                " Les chutes rangées y vont d'elles-mêmes.", False),
        Colonne("Fil", "fil", BOOLEEN,
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
        Colonne("Défauts", "defauts", DEFAUTS,
                "Ce que la planche a de moins que son rectangle, termes"
                " séparés par « ; » :\n"
                "  bouts 30 — 30 mm à ôter à chaque bout (fendu)\n"
                "  rives 8 — 8 mm à ôter sur chaque rive (flache)\n"
                "  1200-1280 — un nœud traversant, de 1200 à 1280 mm\n"
                "  600,140,60,40 — une zone x, y, longueur, largeur\n"
                "(x depuis le bout gauche, y depuis la rive basse). Les"
                " zones sont écartées par des coupes guillotine avant"
                " toute pose ; le trait de scie tombe hors du défaut."
                " Une ligne à plusieurs exemplaires les décrit tous"
                " pareils : une planche singulière prend sa propre ligne.",
                ""),
        Colonne("Contour", "contour", CONTOUR,
                "Une chute BISCORNUE : le reste d'une planche imbriquée à"
                " la CNC, rangé au stock avec sa forme. Ne sert qu'à"
                " l'imbrication de contours — un lot de rectangles à scier"
                " l'ignore. Se remplit par « Ranger les chutes au stock »,"
                " pas à la main.", ()),
    )

    AVANCEES = (8, 9, 10, 12)        # Fil, Catalogue, Prix, Contour

    def __init__(self, matieres_connues=None):
        super().__init__()
        # La liste propose les matières des DEUX tables, pas seulement les
        # siennes : le stock d'un projet importé porte encore le bois du
        # précédent, et « douglas », écrit vingt fois dans les pièces
        # juste au-dessus, n'était pas proposé — le seul mot dont on ait
        # besoin, absent de la seule liste où on le cherche.
        self.setItemDelegateForColumn(
            4, DelegateListe(matieres_connues or self.matieres, self))

    def stock(self) -> list:
        return [opt.Planche(**self.valeurs_ligne(l))
                for l in self.lignes_utiles()]

    def matieres(self) -> list:
        return sorted({self.texte(l, 4) for l in range(self.rowCount())
                       if self.texte(l, 4)})

    def references(self) -> list:
        """Les références du stock, dans l'ordre de la table — ce qu'une
        pièce peut s'imposer comme planche."""
        vues, refs = set(), []
        for l in self.lignes_utiles():
            ref = self.texte(l, 0)
            if ref not in vues:
                vues.add(ref)
                refs.append(ref)
        return refs

    def resume(self) -> str:
        try:
            stock = self.stock()
        except ErreurSaisie as erreur:
            return "⚠ %s" % erreur
        if not stock:
            return "Stock vide — le débit n'aura rien où se poser."
        chutes = sum(s.quantite for s in stock if s.chute)
        atelier = sum(1 for s in stock if s.atelier)
        catalogue = sum(1 for s in stock if s.illimite)
        surface = sum(s.aire * s.quantite for s in stock if not s.illimite)
        details = ["%d référence(s)" % len(stock)]
        if atelier:
            details.append("%d de l'atelier" % atelier)
        if chutes:
            details.append("%d chute(s) à écouler d'abord" % chutes)
        if catalogue:
            details.append("%d profil(s) de catalogue" % catalogue)
        details.append("surface en atelier %s m²" % opt._m2(surface))
        return " · ".join(details)
