#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interface Qt du chutier — saisie des pièces et du stock, calcul de la
feuille de débit, dessin du plan planche par planche.

Ne contient aucune logique de débit : tout passe par
``optimiseur.optimiser()``. Cette couche ne fait qu'assembler les entrées
et afficher le ``Resultat`` qui en revient.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

import csv_io
import optimiseur as opt

TITRE = "Chutier — feuille de débit"

COLONNES_PIECES = ["Référence", "Longueur", "Largeur", "Épaisseur",
                    "Matière", "Qté", "Fil", "Composable"]
COLONNES_STOCK = ["Référence", "Longueur", "Largeur", "Épaisseur",
                   "Matière", "Qté", "Chute", "A un fil", "Catalogue",
                   "Prix"]

FILS_PIECE = [
    (opt.FIL_LONGUEUR, "Longueur"),
    (opt.FIL_LARGEUR, "Largeur"),
    (opt.FIL_INDIFFERENT, "Indifférent"),
]

COULEUR_CHUTE = QColor("#b9bdc4")
COULEUR_TRAIT_CHUTE = QColor("#6b7078")
COULEUR_PERTE_FOND = QColor("#f4f2ee")
COULEUR_BORD_PLANCHE = QColor("#2f3540")
COULEUR_ALERTE = QColor("#c0392b")


def _couleur_piece(reference: str) -> QColor:
    """Une teinte stable par référence, dérivée de son nom — deux pièces
    de même référence ont toujours la même couleur d'une session à
    l'autre, sans table à tenir à jour."""
    teinte = (hash(reference) % 360 + 360) % 360
    return QColor.fromHsv(teinte, 110, 235)


def _texte_ou_zero(cellule: QTableWidgetItem) -> str:
    return cellule.text().strip() if cellule is not None else ""


class TableEditable(QTableWidget):
    """Table à lignes ajoutables/supprimables, colonnes fixées."""

    def __init__(self, colonnes: list):
        super().__init__(0, len(colonnes))
        self.setHorizontalHeaderLabels(colonnes)
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(colonnes)):
            self.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)

    def ligne_texte(self, ligne: int, colonne: int, defaut: str = "") -> str:
        item = self.item(ligne, colonne)
        return item.text().strip() if item is not None else defaut

    def widget_ligne(self, ligne: int, colonne: int):
        return self.cellWidget(ligne, colonne)

    def ajouter_ligne(self):
        self.insertRow(self.rowCount())

    def supprimer_lignes_selectionnees(self):
        lignes = sorted({i.row() for i in self.selectedIndexes()},
                        reverse=True)
        for ligne in lignes:
            self.removeRow(ligne)


class ComboMatiere(QComboBox):
    """La liste des matières déjà présentes dans le stock, relue à chaque
    ouverture — éditable pour une matière qui n'y figure pas encore.
    Sans ce rafraîchissement paresseux, une liste figée à la création de
    la ligne resterait périmée dès que le stock change ensuite."""

    def __init__(self, table_stock: "TableStock"):
        super().__init__()
        self.setEditable(True)
        self._table_stock = table_stock

    def showPopup(self):
        actuel = self.currentText()
        matieres = sorted({self._table_stock.ligne_texte(r, 4)
                           for r in range(self._table_stock.rowCount())
                           if self._table_stock.ligne_texte(r, 4)})
        self.blockSignals(True)
        self.clear()
        self.addItems(matieres)
        self.setCurrentText(actuel)
        self.blockSignals(False)
        super().showPopup()


class TablePieces(TableEditable):
    def __init__(self, table_stock: "TableStock"):
        super().__init__(COLONNES_PIECES)
        self._table_stock = table_stock

    def ajouter_ligne(self, reference="", longueur="", largeur="",
                      epaisseur="18", matiere="", quantite="1",
                      composable=False):
        ligne = self.rowCount()
        self.insertRow(ligne)
        for col, valeur in enumerate(
                [reference, longueur, largeur, epaisseur]):
            self.setItem(ligne, col, QTableWidgetItem(str(valeur)))
        combo_matiere = ComboMatiere(self._table_stock)
        combo_matiere.setCurrentText(str(matiere))
        self.setCellWidget(ligne, 4, combo_matiere)
        self.setItem(ligne, 5, QTableWidgetItem(str(quantite)))
        combo_fil = QComboBox()
        for cle, libelle in FILS_PIECE:
            combo_fil.addItem(libelle, cle)
        self.setCellWidget(ligne, 6, combo_fil)
        case_composable = QCheckBox()
        case_composable.setChecked(bool(composable))
        case_composable.setToolTip(
            "Trop large pour tout brut, cette pièce peut se reconstituer"
            " en collant plusieurs lames côte à côte (ou en tenon-rainure)"
            " plutôt que de rester non placée.")
        self.setCellWidget(ligne, 7, case_composable)

    def pieces(self) -> list:
        resultat = []
        for ligne in range(self.rowCount()):
            reference = self.ligne_texte(ligne, 0)
            if not reference:
                continue
            longueur = _flottant(self.ligne_texte(ligne, 1), reference)
            largeur = _flottant(self.ligne_texte(ligne, 2), reference)
            epaisseur = _flottant(self.ligne_texte(ligne, 3, "0") or "0",
                                  reference)
            matiere = self.widget_ligne(ligne, 4).currentText().strip()
            quantite = _entier(self.ligne_texte(ligne, 5, "1") or "1",
                               reference)
            fil = self.widget_ligne(ligne, 6).currentData()
            composable = self.widget_ligne(ligne, 7).isChecked()
            resultat.append(opt.Piece(reference, longueur, largeur,
                                      epaisseur, matiere, quantite, fil,
                                      composable))
        return resultat


class TableStock(TableEditable):
    def __init__(self):
        super().__init__(COLONNES_STOCK)

    def ajouter_ligne(self, reference="", longueur="", largeur="",
                      epaisseur="18", matiere="", quantite="1",
                      chute=False, fil=True, illimite=False, prix="0"):
        ligne = self.rowCount()
        self.insertRow(ligne)
        for col, valeur in enumerate(
                [reference, longueur, largeur, epaisseur, matiere,
                 quantite]):
            self.setItem(ligne, col, QTableWidgetItem(str(valeur)))
        case_chute = QCheckBox()
        case_chute.setChecked(chute)
        self.setCellWidget(ligne, 6, case_chute)
        case_fil = QCheckBox()
        case_fil.setChecked(fil)
        self.setCellWidget(ligne, 7, case_fil)
        case_illimite = QCheckBox()
        case_illimite.setChecked(illimite)
        case_illimite.setToolTip(
            "Un profil de catalogue (une section qu'on peut acheter),"
            " pas des planches déjà en atelier — la quantité ne borne"
            " plus rien, le chutier en prend autant que le débit"
            " demande, et compte ensuite combien en acheter.")
        self.setCellWidget(ligne, 8, case_illimite)
        item_prix = QTableWidgetItem(str(prix))
        item_prix.setToolTip(
            "Coût d'UNE planche à ces cotes, pas un prix au mètre. Sert à"
            " départager plusieurs profils Catalogue par le coût réel"
            " plutôt que la seule surface neuve — laisser à 0 pour ne pas"
            " en tenir compte.")
        self.setItem(ligne, 9, item_prix)

    def stock(self) -> list:
        resultat = []
        for ligne in range(self.rowCount()):
            reference = self.ligne_texte(ligne, 0)
            if not reference:
                continue
            longueur = _flottant(self.ligne_texte(ligne, 1), reference)
            largeur = _flottant(self.ligne_texte(ligne, 2), reference)
            epaisseur = _flottant(self.ligne_texte(ligne, 3, "0") or "0",
                                  reference)
            matiere = self.ligne_texte(ligne, 4)
            quantite = _entier(self.ligne_texte(ligne, 5, "1") or "1",
                               reference)
            chute = self.widget_ligne(ligne, 6).isChecked()
            fil = self.widget_ligne(ligne, 7).isChecked()
            illimite = self.widget_ligne(ligne, 8).isChecked()
            prix = _flottant(self.ligne_texte(ligne, 9, "0") or "0",
                             reference)
            resultat.append(opt.Planche(reference, longueur, largeur,
                                        epaisseur, matiere, quantite,
                                        chute, fil, illimite, prix))
        return resultat


class ErreurSaisie(ValueError):
    pass


def _flottant(texte: str, reference: str) -> float:
    try:
        return float(texte.replace(",", "."))
    except ValueError:
        raise ErreurSaisie(
            "« %s » : nombre attendu, « %s » lu" % (reference, texte))


def _entier(texte: str, reference: str) -> int:
    try:
        return int(texte)
    except ValueError:
        raise ErreurSaisie(
            "« %s » : entier attendu, « %s » lu" % (reference, texte))


class VuePlanche(QGraphicsView):
    """Dessine une planche débitée : pièces posées en couleur, chutes
    réutilisables en hachuré. Ce que ni pièce ni chute ne couvrent est
    la perte (sciure + rebuts) — il apparaît en fond, non détouré."""

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setScene(QGraphicsScene(self))
        self._debit = None
        self._etiquettes = []

    def afficher(self, debit):
        self._debit = debit
        scene = self.scene()
        scene.clear()
        if debit is None:
            return

        pl = debit.planche
        scene.setSceneRect(QRectF(0, 0, pl.longueur, pl.largeur))

        fond = QGraphicsRectItem(0, 0, pl.longueur, pl.largeur)
        fond.setBrush(QBrush(COULEUR_PERTE_FOND))
        fond.setPen(QPen(COULEUR_BORD_PLANCHE, max(pl.longueur, 1) / 400))
        scene.addItem(fond)

        self._etiquettes = []
        for pose in debit.poses:
            self._ajouter_rect(scene, pose.x, pose.y, pose.dim_x,
                               pose.dim_y, pl.largeur,
                               _couleur_piece(pose.piece.reference),
                               "%s\n%g × %g" % (pose.piece.reference,
                                                round(pose.dim_x, 1),
                                                round(pose.dim_y, 1)),
                               pose.piece.reference)

        for chute in debit.chutes:
            self._ajouter_rect(scene, chute.x, chute.y, chute.dim_x,
                               chute.dim_y, pl.largeur, COULEUR_CHUTE,
                               "chute\n%g × %g" % (round(chute.dim_x, 1),
                                                   round(chute.dim_y, 1)),
                               "chute", hachure=True)

        self._ajuster()

    def _ajouter_rect(self, scene, x, y, dx, dy, largeur_planche, couleur,
                      etiquette, etiquette_courte, hachure=False):
        # Les données ont leur origine en bas-gauche ; QGraphicsRectItem
        # place la sienne en haut-gauche — on retourne y ici, une fois,
        # plutôt que de retourner toute la vue (le texte resterait lisible).
        y_qt = largeur_planche - y - dy
        rect = QGraphicsRectItem(x, y_qt, dx, dy)
        if hachure:
            brosse = QBrush(couleur, Qt.BrushStyle.BDiagPattern)
            rect.setBrush(brosse)
            rect.setPen(QPen(COULEUR_TRAIT_CHUTE, 1))
        else:
            rect.setBrush(QBrush(couleur))
            rect.setPen(QPen(COULEUR_BORD_PLANCHE, 1))
        rect.setToolTip(etiquette.replace("\n", " "))
        scene.addItem(rect)

        # Une planche de menuiserie est souvent longue et étroite (un
        # 150×3000) : la pièce posée peut être trop basse pour ses deux
        # lignes complètes tout en étant bien assez large pour son seul
        # nom. Les trois variantes sont préparées ; _ajuster choisit celle
        # qui loge sous le zoom courant, ou aucune (l'info-bulle reste).
        complet = self._texte_centre(scene, etiquette, x, y_qt, dx, dy, 8)
        court = self._texte_centre(scene, etiquette_courte, x, y_qt, dx, dy, 6)
        hors = None
        if y < 0.5:
            # La pièce est au ras du bord bas de la planche (y=0) : rien
            # n'occupe l'en-dessous. La vue en garde toujours une marge
            # libre là (une planche de charpente est bien plus longue que
            # large) — l'étiquette peut y déborder sans chevaucher un
            # voisin, qu'il soit une pièce ou une chute.
            hors = self._texte_centre(scene, etiquette_courte, x,
                                      y_qt + dy, dx, 0, 6, cote="dessous")
        elif y + dy > largeur_planche - 0.5:
            hors = self._texte_centre(scene, etiquette_courte, x, y_qt,
                                      dx, 0, 6, cote="dessus")
        self._etiquettes.append((complet, court, hors, dx, dy))

    def _texte_centre(self, scene, chaine, x, y_qt, dx, dy, taille_police,
                      cote="dedans"):
        texte = QGraphicsSimpleTextItem(chaine)
        texte.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        police = QFont()
        police.setPointSize(taille_police)
        texte.setFont(police)
        # ItemIgnoresTransformations ancre pos() au point de la scène (donc
        # zoomé avec la vue) mais dessine ensuite en pixels non zoomés — le
        # centrage se fait par une transformation propre à l'item, en pixels.
        boite = texte.boundingRect()
        texte.setPos(x + dx / 2, y_qt + dy / 2)
        if cote == "dessus":
            decalage_y = -boite.height() - 3
        elif cote == "dessous":
            decalage_y = 3
        else:
            decalage_y = -boite.height() / 2
        texte.setTransform(
            texte.transform().translate(-boite.width() / 2, decalage_y))
        scene.addItem(texte)
        return texte, boite

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajuster()

    def _ajuster(self):
        if self.scene() is None or self.scene().sceneRect().isEmpty():
            return
        self.fitInView(self.scene().sceneRect(),
                       Qt.AspectRatioMode.KeepAspectRatio)
        echelle = self.transform().m11()
        for (texte_c, boite_c), (texte_k, boite_k), hors, dx, dy \
                in getattr(self, "_etiquettes", []):
            def tient(boite, hauteur=dy):
                return (dx * echelle >= boite.width() + 4
                        and hauteur * echelle >= boite.height() + 4)
            if tient(boite_c):
                texte_c.setVisible(True)
                texte_k.setVisible(False)
                if hors:
                    hors[0].setVisible(False)
            elif tient(boite_k):
                texte_c.setVisible(False)
                texte_k.setVisible(True)
                if hors:
                    hors[0].setVisible(False)
            else:
                texte_c.setVisible(False)
                texte_k.setVisible(False)
                if hors:
                    texte_h, boite_h = hors
                    texte_h.setVisible(dx * echelle >= boite_h.width() + 4)


class FenetrePrincipale(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITRE)
        self.resize(1600, 850)
        self._resultat = None
        self._tailles_appliquees = False

        self._construire()
        self._charger_exemple()

    def showEvent(self, event):
        super().showEvent(event)
        if self._tailles_appliquees:
            return
        self._tailles_appliquees = True
        # QSplitter.setSizes() avant que la fenêtre ait une géométrie
        # réelle est redistribué au premier affichage réel (aux seuls
        # facteurs d'étirement) — et showEvent lui-même est encore trop
        # tôt, un resize venant de la fenêtre le réécrase juste après.
        # Un timer à délai nul le réapplique une fois ce cycle passé.
        QTimer.singleShot(0, self._appliquer_tailles)

    def _appliquer_tailles(self):
        # Un chiffre fixe se périme dès que le panneau de saisie
        # s'élargit (un bouton, un paramètre de plus) — son propre
        # minimum réel est le seul repère qui ne ment pas ; le reste
        # de la largeur va aux résultats (le plan est ce qu'on regarde).
        gauche = self._splitter_central.widget(0).minimumSizeHint().width()
        droite = max(500, self._splitter_central.width() - gauche)
        self._splitter_central.setSizes([gauche, droite])
        self._splitter_resultats.setSizes([220, 780])

    # -- construction -----------------------------------------------

    def _construire(self):
        central = QSplitter(Qt.Orientation.Horizontal)
        central.addWidget(self._panneau_saisie())
        central.addWidget(self._panneau_resultats())
        central.setStretchFactor(0, 2)
        central.setStretchFactor(1, 3)
        central.setSizes([520, 760])
        self._splitter_central = central
        self.setCentralWidget(central)

    def _panneau_saisie(self) -> QWidget:
        panneau = QWidget()
        disposition = QVBoxLayout(panneau)

        # Le stock se construit avant les pièces : ComboMatiere y puise sa
        # liste de matières (relue à chaque ouverture, voir sa docstring).
        self.table_stock = TableStock()
        self.table_pieces = TablePieces(self.table_stock)

        disposition.addWidget(QLabel("<b>Pièces à débiter</b>"))
        disposition.addWidget(self.table_pieces, stretch=2)
        ligne_pieces = self._boutons_table(
            self.table_pieces, lambda: self.table_pieces.ajouter_ligne())
        bouton_importer = QPushButton("Importer un CSV…")
        bouton_importer.clicked.connect(self._importer_csv)
        ligne_pieces.addWidget(bouton_importer)
        disposition.addLayout(ligne_pieces)

        disposition.addWidget(QLabel("<b>Stock (planches et chutes)</b>"))
        disposition.addWidget(self.table_stock, stretch=2)
        disposition.addLayout(self._boutons_table(
            self.table_stock, lambda: self.table_stock.ajouter_ligne()))

        disposition.addWidget(self._groupe_parametres())

        boutons = QHBoxLayout()
        bouton_exemple = QPushButton("Exemple : panneaux")
        bouton_exemple.clicked.connect(self._charger_exemple)
        boutons.addWidget(bouton_exemple)
        bouton_volets = QPushButton("Exemple : volets (150×30)")
        bouton_volets.clicked.connect(self._charger_exemple_volets)
        boutons.addWidget(bouton_volets)
        boutons.addStretch()
        bouton_calculer = QPushButton("Calculer le débit")
        bouton_calculer.setDefault(True)
        bouton_calculer.clicked.connect(self._calculer)
        boutons.addWidget(bouton_calculer)
        disposition.addLayout(boutons)

        return panneau

    def _boutons_table(self, table: TableEditable, ajouter) -> QHBoxLayout:
        ligne = QHBoxLayout()
        bouton_ajouter = QPushButton("+ ligne")
        bouton_ajouter.clicked.connect(ajouter)
        bouton_supprimer = QPushButton("− lignes sélectionnées")
        bouton_supprimer.clicked.connect(table.supprimer_lignes_selectionnees)
        ligne.addWidget(bouton_ajouter)
        ligne.addWidget(bouton_supprimer)
        ligne.addStretch()
        return ligne

    def _groupe_parametres(self) -> QGroupBox:
        groupe = QGroupBox("Paramètres")
        disposition = QHBoxLayout(groupe)

        defauts = opt.Parametres()

        self.spin_trait = self._spin(defauts.trait_de_scie, 0, 20)
        self.spin_chute_longueur = self._spin(defauts.chute_mini_longueur,
                                              0, 5000)
        self.spin_chute_largeur = self._spin(defauts.chute_mini_largeur,
                                             0, 2000)
        self.spin_tolerance = self._spin(defauts.tolerance_epaisseur, 0, 10)
        self.spin_surcote_joint = self._spin(defauts.surcote_joint, 0, 20)

        for libelle, widget in [
                ("Trait de scie (mm)", self.spin_trait),
                ("Chute mini — longueur (mm)", self.spin_chute_longueur),
                ("Chute mini — largeur (mm)", self.spin_chute_largeur),
                ("Tolérance épaisseur (mm)", self.spin_tolerance),
                ("Surcote de joint collé (mm)", self.spin_surcote_joint)]:
            colonne = QVBoxLayout()
            colonne.addWidget(QLabel(libelle))
            colonne.addWidget(widget)
            disposition.addLayout(colonne)

        return groupe

    def _spin(self, valeur, minimum, maximum) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(valeur)
        spin.setDecimals(1)
        return spin

    def _panneau_resultats(self) -> QWidget:
        panneau = QWidget()
        disposition = QVBoxLayout(panneau)

        self.label_bilan = QLabel("Aucun calcul pour l'instant.")
        self.label_bilan.setWordWrap(True)
        disposition.addWidget(self.label_bilan)

        self.groupe_achats = QGroupBox("À acheter")
        self.groupe_achats.setVisible(False)
        mise_achats = QVBoxLayout(self.groupe_achats)
        self.liste_achats = QListWidget()
        self.liste_achats.setMaximumHeight(100)
        mise_achats.addWidget(self.liste_achats)
        disposition.addWidget(self.groupe_achats)

        scission = QSplitter(Qt.Orientation.Horizontal)
        self.liste_planches = QListWidget()
        self.liste_planches.setMinimumWidth(160)
        self.liste_planches.currentRowChanged.connect(
            self._afficher_planche_selectionnee)
        scission.addWidget(self.liste_planches)
        self.vue_planche = VuePlanche()
        self.vue_planche.setMinimumWidth(300)
        scission.addWidget(self.vue_planche)
        scission.setStretchFactor(0, 1)
        scission.setStretchFactor(1, 3)
        # setStretchFactor ne répartit que l'espace gagné/perdu lors d'un
        # redimensionnement ; sans setSizes, la taille initiale suit le
        # sizeHint (minuscule pour un QGraphicsView vide).
        scission.setSizes([220, 780])
        self._splitter_resultats = scission
        disposition.addWidget(scission, stretch=3)

        disposition.addWidget(QLabel("<b>Pièces non placées</b>"))
        self.liste_non_placees = QListWidget()
        disposition.addWidget(self.liste_non_placees, stretch=1)

        return panneau

    # -- exemples et import ------------------------------------------------

    def _remplir_pieces(self, pieces):
        self.table_pieces.setRowCount(0)
        for p in pieces:
            self.table_pieces.ajouter_ligne(p.reference, p.longueur,
                                            p.largeur, p.epaisseur,
                                            p.matiere, p.quantite,
                                            p.composable)
            combo = self.table_pieces.widget_ligne(
                self.table_pieces.rowCount() - 1, 6)
            combo.setCurrentIndex(
                [cle for cle, _ in FILS_PIECE].index(p.fil))

    def _remplir_stock(self, stock):
        self.table_stock.setRowCount(0)
        for s in stock:
            self.table_stock.ajouter_ligne(s.reference, s.longueur,
                                           s.largeur, s.epaisseur,
                                           s.matiere, s.quantite, s.chute,
                                           s.fil, s.illimite, s.prix)

    def _remplir_tables(self, pieces, stock):
        self._remplir_pieces(pieces)
        self._remplir_stock(stock)

    def _importer_csv(self):
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Importer des pièces", "", "CSV (*.csv)")
        if not chemin:
            return
        try:
            pieces = csv_io.lire_pieces(chemin)
        except (OSError, ValueError) as erreur:
            QMessageBox.warning(self, "Import impossible", str(erreur))
            return
        self._remplir_pieces(pieces)

    def _charger_exemple(self):
        self._remplir_tables(
            [opt.Piece("montant", 1750, 60, 18, "sapin", quantite=4),
             opt.Piece("traverse", 560, 60, 18, "sapin", quantite=6),
             opt.Piece("tablette", 560, 180, 18, "sapin", quantite=3),
             opt.Piece("taquet", 120, 40, 18, "sapin", quantite=8,
                       fil=opt.FIL_INDIFFERENT)],
            [opt.Planche("sapin 2400×200", 2400, 200, 18, "sapin",
                        quantite=4),
             opt.Planche("chute étagère", 800, 180, 18, "sapin", chute=True),
             opt.Planche("chute courte", 400, 120, 18, "sapin", chute=True)])
        self.spin_trait.setValue(opt.Parametres().trait_de_scie)
        self.spin_tolerance.setValue(opt.Parametres().tolerance_epaisseur)

    def _charger_exemple_volets(self):
        """Débit réel d'une paire de volets battants (projet Christophe,
        29/08/2026) : cotes de débit en douglas 27 mm (finies + surcotes
        de corroyage) sorties du modèle FreeCAD AtelierVolets. Le
        couvre-joint (15 mm) vient d'une autre section, il n'est pas ici.
        """
        self._remplir_tables(
            [opt.Piece("Lame 1 G", 1140, 119, 27, "douglas", 1),
             opt.Piece("Lame 2 G", 1140, 119, 27, "douglas", 1),
             opt.Piece("Lame 3 G", 1140, 119, 27, "douglas", 1),
             opt.Piece("Lame 4 G", 1140, 119, 27, "douglas", 1),
             opt.Piece("Lame 5 G", 1140, 105, 27, "douglas", 1),
             opt.Piece("Traverse haute G", 550, 125, 27, "douglas", 1),
             opt.Piece("Barre du Z G", 515, 105, 27, "douglas", 2),
             opt.Piece("Echarpe G", 829.6857318589343, 105, 27, "douglas", 1),
             opt.Piece("Lame 1 D", 1140, 117, 27, "douglas", 1),
             opt.Piece("Lame 2 D", 1140, 117, 27, "douglas", 1),
             opt.Piece("Lame 3 D", 1140, 117, 27, "douglas", 1),
             opt.Piece("Lame 4 D", 1140, 117, 27, "douglas", 1),
             opt.Piece("Lame 5 D", 1140, 103, 27, "douglas", 1),
             opt.Piece("Traverse haute D", 540, 125, 27, "douglas", 1),
             opt.Piece("Barre du Z D", 505, 105, 27, "douglas", 2),
             opt.Piece("Echarpe D", 824.9482377125985, 105, 27, "douglas", 1)],
            [opt.Planche("douglas 150x30 -- 3 m", 3000, 150, 30, "douglas",
                        quantite=3),
             opt.Planche("douglas 150x30 -- 4 m", 4000, 150, 30, "douglas",
                        quantite=2)])
        # 4 mm : le TRAIT_DE_SCIE du projet volets. 5 mm de tolérance
        # d'épaisseur : les planches sont du brut (30) à raboter à la cote
        # finie (27), comme le prévoit SUREPAISSEUR côté volets — sans
        # cet écart, le stock et les pièces ne se rangent pas dans le
        # même lot (par matière + épaisseur À LA TOLÉRANCE PRÈS).
        self.spin_trait.setValue(4.0)
        self.spin_tolerance.setValue(5.0)

    # -- calcul ---------------------------------------------------------

    def _calculer(self):
        try:
            pieces = self.table_pieces.pieces()
            stock = self.table_stock.stock()
            parametres = opt.Parametres(
                trait_de_scie=self.spin_trait.value(),
                chute_mini_longueur=self.spin_chute_longueur.value(),
                chute_mini_largeur=self.spin_chute_largeur.value(),
                tolerance_epaisseur=self.spin_tolerance.value(),
                surcote_joint=self.spin_surcote_joint.value())
            if not pieces:
                raise ErreurSaisie("aucune pièce à débiter")
            resultat = opt.optimiser(pieces, stock, parametres)
        except (ErreurSaisie, ValueError) as erreur:
            QMessageBox.warning(self, "Saisie invalide", str(erreur))
            return

        self._resultat = resultat
        self._afficher_resultat()

    def _afficher_resultat(self):
        r = self._resultat
        b = r.bilan
        self.label_bilan.setText(
            "%d/%d pièce(s) posée(s) — rendement %s %% — "
            "%d planche(s) entamée(s) dont %d chute(s) — "
            "pertes %s m² — chutes créées : %d (%s m²)"
            % (b.nb_posees, b.nb_demandees, opt._pct(b.rendement),
               b.nb_planches_entamees, b.nb_chutes_consommees,
               opt._m2(b.surface_perdue), len(r.chutes_creees),
               opt._m2(b.surface_chutes_creees)))

        self.liste_achats.clear()
        for a in r.achats:
            cout = (" — %s" % opt._prix(a.nombre * a.prix)) if a.prix else ""
            self.liste_achats.addItem(QListWidgetItem(
                "%d × « %s » — %s × %s × %s mm, %s%s"
                % (a.nombre, a.reference, opt._mm(a.longueur),
                   opt._mm(a.largeur), opt._mm(a.epaisseur), a.matiere,
                   cout)))
        cout_total = sum(a.nombre * a.prix for a in r.achats)
        if cout_total:
            self.liste_achats.addItem(QListWidgetItem(
                "Total : %s" % opt._prix(cout_total)))
        self.groupe_achats.setVisible(bool(r.achats))

        self.liste_planches.clear()
        for i, debit in enumerate(r.debits, 1):
            # illimite : la quantite affichee ne dit rien du nombre pris
            plusieurs = debit.planche.quantite > 1 or debit.planche.illimite
            ex = " (ex. %d)" % debit.exemplaire if plusieurs else ""
            texte = ("%d. %s%s — %d pièce(s), rendement %s %%"
                     % (i, debit.planche.reference, ex, len(debit.poses),
                        opt._pct(debit.rendement)))
            item = QListWidgetItem(texte)
            item.setToolTip(texte)
            self.liste_planches.addItem(item)
        if r.debits:
            self.liste_planches.setCurrentRow(0)
        else:
            self.vue_planche.afficher(None)

        self.liste_non_placees.clear()
        for n in r.non_placees:
            item = QListWidgetItem(
                "« %s » ×%d — %s" % (n.piece.reference, n.exemplaires,
                                     n.raison))
            item.setForeground(COULEUR_ALERTE)
            self.liste_non_placees.addItem(item)

    def _afficher_planche_selectionnee(self, ligne: int):
        if self._resultat is None or ligne < 0:
            return
        self.vue_planche.afficher(self._resultat.debits[ligne])


def main():
    app = QApplication(sys.argv)
    fenetre = FenetrePrincipale()
    fenetre.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
