#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interface Qt du chutier.

Trois temps, trois onglets à gauche : ce qu'on veut débiter, ce qu'on a
en stock, comment on scie. Le résultat occupe toute la droite, le plan
en tête — c'est ce qu'on regarde, pas la saisie qu'on vient de finir.

Aucune logique de débit ici : tout passe par ``optimiseur.optimiser()``.
Cette couche assemble les entrées et affiche le ``Resultat`` qui revient.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from xml.etree.ElementTree import ParseError as ET_ParseError

from PySide6.QtCore import QEvent, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction, QFont, QIcon, QKeySequence, QPageLayout, QPainter,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

import apparence
import contours_svg
import csv_io
import exemples
import export_cnc
import optimiseur as opt
import projet_io
import tables_saisie as tsa
import vue_plan
from stock_atelier import (  # noqa: F401 — les tests les prennent ici
    chutes_groupees, planches_consommees, stock_apres_debit,
)
from tables_saisie import ErreurSaisie

TITRE = "Chutier — feuille de débit"
# Chemin absolu : le lanceur .desktop fixe le dossier courant, mais rien
# d'autre ne le garantit (double-clic depuis un autre dossier, etc.).
ICONE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "resources", "icone.svg")

PLAN, ACHATS, CHUTES, NON_PLACEES = range(4)


class FenetrePrincipale(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITRE)
        self.resize(1500, 900)
        self._resultat = None
        self._epingles = []        # Debit repris tels quels au calcul
        self._chemin = None
        self._modifie = False
        self._a_jour = False
        self._chargement = True
        self._reglages = QSettings("AtelierDuVerdier", "Chutier")
        self._chemin_atelier = projet_io.chemin_atelier()

        self._construire()
        self.a_avancees.setChecked(
            self._reglages.value("colonnes_avancees", False, type=bool))
        atelier = self._atelier()
        if atelier:
            # Un atelier déjà garni : on ouvre sur lui, feuille de pièces
            # blanche — c'est le vrai point de départ d'un débit. L'exemple
            # ne sert qu'à la découverte, quand le stock commun est vide.
            self._remplir([], atelier, opt.Parametres())
            self.table_pieces.ajouter_ligne()
        else:
            self._charger_exemple()
        # Le trait de scie est une propriété de LA SCIE, pas du projet :
        # il revient donc tel qu'on l'a laissé, y compris par-dessus les
        # réglages d'usine de l'exemple d'accueil.
        self._appliquer_parametres(self._reglages_memorises())
        self._chargement = False
        self._restaurer_geometrie()
        QTimer.singleShot(0, self._calculer_si_pieces)

    # -- construction -----------------------------------------------------

    def _construire(self):
        self._actions()
        central = QSplitter(Qt.Orientation.Horizontal)
        central.setHandleWidth(9)
        central.setStyleSheet(apparence.STYLE_POIGNEE)
        central.addWidget(self._panneau_saisie())
        central.addWidget(self._panneau_resultats())
        central.setStretchFactor(0, 0)
        central.setStretchFactor(1, 1)
        central.setCollapsible(0, True)
        central.setSizes([640, 1060])
        self._splitter = central
        self.setCentralWidget(central)

        self.etat_fichier = QLabel()
        self.etat_calcul = QLabel()
        self.statusBar().addWidget(self.etat_fichier, 1)
        self.statusBar().addPermanentWidget(self.etat_calcul)
        self._rafraichir_etat()

    def _acte(self, texte, methode, raccourci=None, icone=None, info=None):
        action = QAction(texte, self)
        if icone:
            action.setIcon(apparence.icone(*icone))
        if raccourci:
            action.setShortcut(QKeySequence(raccourci))
        action.setToolTip(info or texte)
        action.setStatusTip(info or texte)
        action.triggered.connect(methode)
        return action

    def _actions(self):
        self.a_nouveau = self._acte(
            "&Nouveau", self._nouveau, "Ctrl+N", ("document-new",),
            "Vider les pièces et le stock pour repartir d'une feuille blanche")
        self.a_ouvrir = self._acte(
            "&Ouvrir un projet…", self._ouvrir, "Ctrl+O", ("document-open",),
            "Rouvrir un projet enregistré (pièces, stock et réglages)")
        self.a_enregistrer = self._acte(
            "&Enregistrer", self._enregistrer, "Ctrl+S", ("document-save",),
            "Enregistrer le projet courant")
        self.a_enregistrer_sous = self._acte(
            "Enregistrer &sous…", self._enregistrer_sous, "Ctrl+Shift+S",
            ("document-save-as",))
        self.a_importer = self._acte(
            "&Importer des pièces (CSV)…", self._importer_csv, "Ctrl+I",
            ("document-import", "document-open"),
            "Charger une liste de pièces produite par un autre projet")
        self.a_contours = self._acte(
            "Importer des &contours (SVG)…", self._importer_contours, None,
            ("document-import", "document-open"),
            "Ajouter des formes quelconques à découper à la CNC : chaque"
            " tracé fermé du SVG devient une pièce à imbriquer")
        self.a_exporter_svg = self._acte(
            "Exporter la découpe (S&VG)…", lambda: self._exporter_decoupe("svg"),
            None, ("document-export",),
            "Une planche par fichier SVG à l'échelle 1, contours des pièces"
            " et de la planche — ce qu'on passe à la chaîne CNC")
        self.a_exporter_dxf = self._acte(
            "Exporter la découpe (D&XF)…", lambda: self._exporter_decoupe("dxf"),
            None, ("document-export",),
            "Une planche par fichier DXF (R12), calques PIECES, PLANCHE et"
            " NOMS — pour la fraiseuse")
        self.a_exporter_lbrn = self._acte(
            "Exporter la découpe (&LightBurn)…",
            lambda: self._exporter_decoupe("lbrn"), None, ("document-export",),
            "Une planche par projet LightBurn (.lbrn), calque 0 les pièces,"
            " calque 1 le tour de planche — pour le laser")
        self.a_exporter = self._acte(
            "E&xporter le plan (image)…", self._exporter_image, "Ctrl+E",
            ("document-export", "image-x-generic"),
            "Enregistrer le plan affiché en PNG, à résolution d'impression")
        self.a_imprimer = self._acte(
            "Im&primer le plan…", self._imprimer, "Ctrl+P",
            ("document-print",),
            "Sortir le plan affiché sur papier, à emporter à l'établi")
        self.a_fiche = self._acte(
            "Exporter la &fiche d'atelier (texte)…", self._exporter_fiche,
            None, ("text-x-generic",),
            "La liste des poses et des coupes planche par planche, à cocher"
            " au fur et à mesure du débit")
        self.a_etiquettes = self._acte(
            "Imprimer les é&tiquettes…", self._imprimer_etiquettes, None,
            ("document-print",),
            "Une étiquette par pièce débitée — référence, cotes, planche,"
            " couleur du plan — 24 par page A4 (70 × 37 mm), à coller sur"
            " le bois")
        self.a_exporter_csv = self._acte(
            "Exporter les pièces (CSV)…", self._exporter_csv, None,
            ("document-export",),
            "Ressortir la liste de pièces au format d'échange, pour un"
            " tableur ou un autre projet")
        self.a_atelier = self._acte(
            "Recharger le stock de l'&atelier", self._recharger_atelier, None,
            ("view-refresh",),
            "Relire le fichier commun de l'atelier (chutes rangées, planches"
            " en rayon) — utile s'il a été modifié par une autre fenêtre")
        self.a_quitter = self._acte("&Quitter", self.close, "Ctrl+Q",
                                    ("application-exit",))

        self.a_ligne = self._acte("Ajouter une &ligne", self._ajouter_ligne,
                                  "Ctrl+Return", ("list-add",))
        self.a_dupliquer = self._acte(
            "&Dupliquer la sélection", self._dupliquer, "Ctrl+D",
            ("edit-copy",), "Recopier les lignes choisies juste en dessous")
        self.a_supprimer = self._acte(
            "&Supprimer les lignes", self._supprimer, "Ctrl+Del",
            ("list-remove",))
        self.a_matiere = self._acte(
            "&Matière → lignes sélectionnées", self._matiere_en_lot, None,
            None, "Appliquer une même matière à toutes les lignes choisies")

        self.a_calculer = self._acte(
            "&Calculer le débit", self._calculer, "F5",
            ("system-run", "media-playback-start", "view-refresh"),
            "Recalculer la feuille de débit (F5)")
        self.a_avancees = QAction("Colonnes &avancées", self)
        self.a_avancees.setCheckable(True)
        self.a_avancees.setStatusTip(
            "Montrer les colonnes rarement remplies (Composable, Planche ;"
            " Fil, Catalogue, Prix) — elles reviennent d'elles-mêmes dès"
            " qu'une ligne s'en sert")
        self.a_avancees.toggled.connect(self._basculer_avancees)
        self.a_desepingler = self._acte(
            "Tout &désépingler", self._tout_desepingler, None, None,
            "Relâcher toutes les planches épinglées : le prochain calcul"
            " repart de zéro")
        self.a_saisie = QAction("Masquer la &saisie", self)
        self.a_saisie.setCheckable(True)
        self.a_saisie.setShortcut(QKeySequence("Ctrl+M"))
        self.a_saisie.setStatusTip(
            "Laisser tout l'écran au plan — pratique sur un brin de 4 m")
        self.a_saisie.toggled.connect(self._basculer_saisie)

        self.a_exemple = self._acte("Exemple : &panneaux",
                                    self._charger_exemple)
        self.a_volets = self._acte("Exemple : &volets battants (150×30)",
                                   self._charger_exemple_volets)
        self.a_formes = self._acte("Exemple : &formes biscornues (CNC)",
                                   self._charger_exemple_formes, None, None,
                                   "Un cadre évidé, des cœurs, des étoiles,"
                                   " des anneaux… imbriqués à la fraise sur"
                                   " un panneau de contreplaqué")
        self.a_aide = self._acte("&Raccourcis et conventions", self._aide,
                                 "F1", ("help-contents",))

        menu = self.menuBar()
        fichier = menu.addMenu("&Fichier")
        for action in (self.a_nouveau, self.a_ouvrir, self.a_enregistrer,
                       self.a_enregistrer_sous):
            fichier.addAction(action)
        fichier.addSeparator()
        fichier.addAction(self.a_importer)
        fichier.addAction(self.a_exporter_csv)
        fichier.addSeparator()
        fichier.addAction(self.a_contours)
        fichier.addAction(self.a_exporter_svg)
        fichier.addAction(self.a_exporter_dxf)
        fichier.addAction(self.a_exporter_lbrn)
        fichier.addSeparator()
        fichier.addAction(self.a_atelier)
        fichier.addSeparator()
        fichier.addAction(self.a_exporter)
        fichier.addAction(self.a_fiche)
        fichier.addAction(self.a_imprimer)
        fichier.addAction(self.a_etiquettes)
        fichier.addSeparator()
        fichier.addAction(self.a_quitter)

        edition = menu.addMenu("&Édition")
        for action in (self.a_ligne, self.a_dupliquer, self.a_supprimer):
            edition.addAction(action)
        edition.addSeparator()
        edition.addAction(self.a_matiere)
        edition.addSeparator()
        edition.addAction(self.a_avancees)

        debit = menu.addMenu("&Débit")
        debit.addAction(self.a_calculer)
        debit.addAction(self.a_desepingler)
        debit.addSeparator()
        debit.addAction(self.a_saisie)

        menu_exemples = menu.addMenu("E&xemples")
        exemples = menu_exemples
        exemples.addAction(self.a_exemple)
        exemples.addAction(self.a_volets)
        exemples.addAction(self.a_formes)

        menu.addMenu("&Aide").addAction(self.a_aide)

        # La barre d'outils n'est pas une seconde barre de menus : elle
        # porte le geste principal, accentué, et trois raccourcis de
        # main. Le reste vit dans les menus.
        barre = self.addToolBar("Principale")
        barre.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        barre.setMovable(False)
        for action in (self.a_ouvrir, self.a_enregistrer):
            barre.addAction(action)
        barre.addSeparator()
        self.bouton_calculer = QToolButton()
        self.bouton_calculer.setDefaultAction(self.a_calculer)
        self.bouton_calculer.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.bouton_calculer.setStyleSheet(apparence.STYLE_ACCENT)
        barre.addWidget(self.bouton_calculer)
        barre.addSeparator()
        barre.addAction(self.a_imprimer)
        barre.addAction(self.a_saisie)

    # -- saisie ------------------------------------------------------------

    def _panneau_saisie(self) -> QWidget:
        """Pièces au-dessus, stock en dessous, réglages repliés sous les
        deux. Trois onglets, c'était quatre lignes de pièces et 700 px de
        vide, pendant que le stock — dont le débit a besoin en même
        temps — se cachait derrière un clic."""
        self.table_stock = tsa.TableStock()
        self.table_pieces = tsa.TablePieces(self.table_stock.matieres,
                                            self.table_stock.references)
        self._table_active = self.table_pieces

        self.saisie = QSplitter(Qt.Orientation.Vertical)
        self.saisie.setHandleWidth(9)
        self.saisie.setStyleSheet(apparence.STYLE_POIGNEE)
        self.saisie.addWidget(self._page_pieces())
        self.saisie.addWidget(self._page_stock())
        self.saisie.addWidget(self._page_reglages())
        self.saisie.setStretchFactor(0, 3)
        self.saisie.setStretchFactor(1, 2)
        self.saisie.setStretchFactor(2, 0)
        self.saisie.setCollapsible(2, False)

        for table in (self.table_pieces, self.table_stock):
            table.itemChanged.connect(self._saisie_changee)
            table.model().rowsInserted.connect(self._saisie_changee)
            table.model().rowsRemoved.connect(self._saisie_changee)
            table.installEventFilter(self)
        return self.saisie

    def eventFilter(self, objet, evenement):
        # La table qui reçoit le focus devient celle des actions de ligne
        # (« + ligne », Dupliquer…) — les onglets décidaient avant.
        if evenement.type() == QEvent.Type.FocusIn and objet in (
                self.table_pieces, self.table_stock):
            self._table_active = objet
        return super().eventFilter(objet, evenement)

    def _page_table(self, table, titre, resume, actions) -> QWidget:
        page = QWidget()
        colonne = QVBoxLayout(page)
        colonne.setContentsMargins(6, 6, 6, 6)
        colonne.setSpacing(4)
        colonne.addWidget(titre)
        colonne.addWidget(table, stretch=1)
        colonne.addWidget(resume)
        ligne = QHBoxLayout()
        for bouton in actions:
            ligne.addWidget(bouton)
        ligne.addStretch()
        colonne.addLayout(ligne)
        return page

    def _bouton(self, action, texte=None) -> QToolButton:
        """Un bouton de ligne, au libellé COURT.

        Le libellé long du menu (« Matière → lignes sélectionnées »)
        imposait au panneau de saisie une largeur minimale de 765 px : on
        ne pouvait plus le rétrécir pour donner de la place au plan.
        L'info-bulle, elle, porte toujours la phrase entière."""
        bouton = QToolButton()
        bouton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if texte is None:
            bouton.setDefaultAction(action)
        else:
            bouton.setText(texte)
            bouton.setIcon(action.icon())
            bouton.setToolTip(action.toolTip())
            bouton.clicked.connect(action.trigger)
        return bouton

    def _page_pieces(self) -> QWidget:
        self.resume_pieces = apparence.discret("")
        self.titre_pieces = apparence.titre("Pièces")
        self.titre_pieces.setToolTip(
            "Ce qu'il faut débiter : une ligne par référence")
        return self._page_table(
            self.table_pieces, self.titre_pieces, self.resume_pieces,
            [self._bouton(self.a_ligne, "+ ligne"),
             self._bouton(self.a_dupliquer, "Dupliquer"),
             self._bouton(self.a_supprimer, "Supprimer"),
             self._bouton(self.a_matiere, "Matière…"),
             self._bouton(self.a_importer, "Importer…")])

    def _page_stock(self) -> QWidget:
        self.resume_stock = apparence.discret("")
        self.resume_stock.setToolTip(
            "Les lignes cochées « Atelier » vivent dans le fichier commun\n"
            "%s\nréécrit à chaque enregistrement, rangement de chutes et"
            " fermeture." % self._chemin_atelier)
        self.titre_stock = apparence.titre("Stock")
        self.titre_stock.setToolTip(
            "Ce qu'on a sous la main : planches, chutes, profils à acheter")
        return self._page_table(
            self.table_stock, self.titre_stock, self.resume_stock,
            [self._bouton(self.a_ligne, "+ ligne"),
             self._bouton(self.a_dupliquer, "Dupliquer"),
             self._bouton(self.a_supprimer, "Supprimer")])

    def _page_reglages(self) -> QWidget:
        defauts = opt.Parametres()
        self.spin_trait = self._spin(defauts.trait_de_scie, 0, 20)
        self.spin_surcote_longueur = self._spin(defauts.surcote_longueur, 0, 200)
        self.spin_surcote_largeur = self._spin(defauts.surcote_largeur, 0, 200)
        self.spin_chute_longueur = self._spin(defauts.chute_mini_longueur, 0, 5000)
        self.spin_chute_largeur = self._spin(defauts.chute_mini_largeur, 0, 2000)
        self.spin_tolerance = self._spin(defauts.tolerance_epaisseur, 0, 10)
        self.spin_surcote_joint = self._spin(defauts.surcote_joint, 0, 20)
        self.spin_essais = QSpinBox()
        self.spin_essais.setRange(0, 64)
        self.spin_essais.setValue(defauts.essais_melanges)
        self.spin_essais.valueChanged.connect(self._saisie_changee)
        self.spin_ecart = self._spin(defauts.ecart_contours, 0, 50)
        self.spin_marge_bord = self._spin(defauts.marge_bord, 0, 100)
        self.choix_rotation = QComboBox()
        for pas, libelle in ((90, "4 orientations (90°)"),
                             (45, "8 orientations (45°)"),
                             (30, "12 orientations (30°)"),
                             (15, "24 orientations (15°) — lent")):
            self.choix_rotation.addItem(libelle, pas)
        self.choix_rotation.currentIndexChanged.connect(self._saisie_changee)
        self.spin_processus = QSpinBox()
        self.spin_processus.setRange(0, 64)
        self.spin_processus.setSpecialValueText("tous les cœurs")
        self.spin_processus.setValue(defauts.processus)
        self.spin_processus.valueChanged.connect(self._saisie_changee)
        self.spin_passes = QSpinBox()
        self.spin_passes.setRange(0, 10)
        self.spin_passes.setValue(defauts.passes_amelioration)
        self.spin_passes.valueChanged.connect(self._saisie_changee)
        self.choix_priorite = QComboBox()
        self.choix_priorite.addItem("le bois — moins de pertes",
                                    opt.PRIORITE_BOIS)
        self.choix_priorite.addItem("le temps de scie — moins de coupes",
                                    opt.PRIORITE_SCIE)
        self.choix_priorite.currentIndexChanged.connect(self._saisie_changee)

        page = QWidget()
        colonne = QVBoxLayout(page)
        colonne.setContentsMargins(6, 6, 6, 6)
        colonne.addWidget(apparence.discret(
            "Ces réglages sont retenus d'une séance à l'autre et reviennent"
            " pour tout projet neuf — un trait de scie est une propriété de"
            " la scie, pas du projet. Un projet enregistré, lui, garde les"
            " siens et les réimpose à l'ouverture."))
        colonne.addWidget(self._groupe_reglage("La scie", [
            ("Trait de scie (mm)", self.spin_trait,
             "Largeur de matière mangée par chaque coupe — 3 à 4 mm pour"
             " une lame de scie circulaire."),
            ("Surcote de longueur (mm)", self.spin_surcote_longueur,
             "Marge de recoupe ajoutée à chaque pièce au débit. La pièce"
             " garde ses cotes nominales dans la liste ; c'est le morceau"
             " scié qui est plus grand."),
            ("Surcote de largeur (mm)", self.spin_surcote_largeur,
             "Idem en travers — de quoi dresser les rives à la"
             " dégauchisseuse."),
        ]))
        colonne.addWidget(self._groupe_reglage("Ce qui mérite d'être gardé", [
            ("Chute mini — longueur (mm)", self.spin_chute_longueur,
             "En dessous, le reste part aux pertes plutôt qu'au chutier."
             " C'est le grand côté du reste qui est comparé ici."),
            ("Chute mini — largeur (mm)", self.spin_chute_largeur,
             "Le petit côté du reste. Deux seuils, parce qu'un tasseau"
             " long et étroit se garde, un carré de même surface non."),
        ]))
        colonne.addWidget(self._groupe_reglage("Le bois", [
            ("Tolérance d'épaisseur (mm)", self.spin_tolerance,
             "N'absorbe que le bruit de mesure (18,0 mesuré contre 18,05"
             " demandé). Le brut se rabote : une planche plus épaisse"
             " convient toujours, une plus mince jamais."),
            ("Surcote de joint collé (mm)", self.spin_surcote_joint,
             "Largeur perdue à chaque collage entre deux lames d'une"
             " pièce composable — sans effet sur les autres."),
        ]))
        colonne.addWidget(self._groupe_reglage("La CNC (contours imbriqués)", [
            ("Écart entre contours (mm)", self.spin_ecart,
             "Diamètre de fraise plus un jeu : la distance minimale entre"
             " deux pièces imbriquées. Ne joue que pour les matières qui"
             " comptent au moins un contour."),
            ("Marge au bord (mm)", self.spin_marge_bord,
             "Distance entre un contour et le bord de la planche — pour"
             " la bride, ou une rive douteuse."),
            ("Orientations", self.choix_rotation,
             "Les angles essayés pour une pièce à fil indifférent (ou sur"
             " un panneau sans fil). Plus d'orientations imbriquent parfois"
             " mieux, et calculent d'autant plus longtemps."),
            ("Processus", self.spin_processus,
             "Les stratégies d'imbrication se répartissent sur les cœurs"
             " de la machine. Le résultat ne dépend pas de ce nombre ;"
             " seule la durée change. 1 pour calculer sans parallélisme."),
        ]))
        colonne.addWidget(self._groupe_reglage("Le calcul", [
            ("Privilégier", self.choix_priorite,
             "Entre deux plans qui placent tout dans le même bois neuf :"
             " garder celui qui perd le moins de matière, ou celui qui"
             " demande le moins de coupes — à la circulaire, des pièces de"
             " même largeur rangées en bandes se scient bien plus vite."),
            ("Essais de mélange", self.spin_essais,
             "Ordres de pièces tirés au hasard en plus des stratégies"
             " réglées. Plus d'essais range parfois mieux, et calcule plus"
             " longtemps. Le hasard est à graine fixe : mêmes entrées,"
             " même plan."),
            ("Passes d'amélioration", self.spin_passes,
             "Après le meilleur rangement, on essaie planche par planche"
             " de la vider et de replacer ses pièces dans les trous des"
             " autres — c'est ainsi qu'une planche de trop disparaît."
             " 0 pour s'en passer."),
        ]))
        colonne.addStretch()

        cadre = QScrollArea()
        cadre.setWidgetResizable(True)
        cadre.setWidget(page)
        cadre.setFrameShape(QScrollArea.Shape.NoFrame)
        self.reglages = apparence.Repliable(
            "Réglages", cadre,
            "Comment on scie : trait de scie, surcotes, seuils de chute")
        self.reglages.ouvrir(
            self._reglages.value("reglages_ouverts", False, type=bool))
        self.reglages.bascule.connect(self._reglages_bascules)
        return self.reglages

    def _reglages_bascules(self, ouvert):
        # Déplié, le groupe recevait la hauteur qu'il avait replié : trois
        # lignes visibles et un ascenseur. On lui donne une vraie part.
        tailles = self.saisie.sizes()
        total = sum(tailles)
        if ouvert and total:
            part = int(total * 0.45)
            reste = total - part
            self.saisie.setSizes([int(reste * 0.55), reste - int(reste * 0.55),
                                  part])

    def _groupe_reglage(self, titre, champs) -> QGroupBox:
        groupe = QGroupBox(titre)
        formulaire = QFormLayout(groupe)
        formulaire.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        for libelle, widget, info in champs:
            formulaire.addRow(libelle, widget)
            explication = apparence.discret(info)
            formulaire.addRow("", explication)
            widget.setToolTip(info)
        return groupe

    def _spin(self, valeur, minimum, maximum) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(valeur)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setSuffix(" mm")
        spin.valueChanged.connect(self._saisie_changee)
        return spin

    # -- résultats ---------------------------------------------------------

    def _panneau_resultats(self) -> QWidget:
        panneau = QWidget()
        colonne = QVBoxLayout(panneau)
        colonne.setContentsMargins(6, 6, 6, 6)

        self.bilan = apparence.BandeauBilan()
        colonne.addWidget(self.bilan)

        self.onglets_resultats = QTabWidget()
        self.onglets_resultats.setDocumentMode(True)
        self.onglets_resultats.addTab(self._page_plan(), "Plan de débit")
        self.onglets_resultats.addTab(self._page_achats(), "À acheter")
        self.onglets_resultats.addTab(self._page_chutes(), "Chutes créées")
        self.onglets_resultats.addTab(self._page_non_placees(),
                                      "Pièces non placées")
        colonne.addWidget(self.onglets_resultats, stretch=1)
        return panneau

    def _page_plan(self) -> QWidget:
        page = QWidget()
        colonne = QVBoxLayout(page)
        colonne.setContentsMargins(6, 6, 6, 6)

        barre = QHBoxLayout()
        self.choix_vue = QComboBox()
        self.choix_vue.addItem("Toutes les planches", True)
        self.choix_vue.addItem("Planche sélectionnée seule", False)
        self.choix_vue.setToolTip(
            "Empilées, les planches se lisent d'un seul coup d'œil et"
            " remplissent la hauteur ; seule, une planche se détaille.")
        barre.addWidget(self.choix_vue)

        self.case_traits = QCheckBox("Traits de scie")
        self.case_traits.setToolTip(
            "Les coupes telles qu'on les passera à la scie : chaque trait"
            " traverse de bord à bord le morceau courant. Leur numéro"
            " d'ordre est dans l'info-bulle du trait.")
        barre.addWidget(self.case_traits)
        barre.addStretch()
        # Les deux signaux ne se branchent qu'une fois TOUS les widgets
        # que _redessiner touche construits : brancher au fil de l'eau
        # marchait par chance, l'ordre des lignes tenant lieu de garantie.
        self.choix_vue.currentIndexChanged.connect(self._redessiner)
        self.case_traits.toggled.connect(self._redessiner)

        for texte, info, methode in (
                ("−", "Dézoomer", lambda: self.vue.zoomer(1 / 1.25)),
                ("+", "Zoomer", lambda: self.vue.zoomer(1.25)),
                ("Ajuster", "Revoir tout le plan", lambda: self.vue.ajuster())):
            bouton = QPushButton(texte)
            bouton.setToolTip(info)
            bouton.clicked.connect(methode)
            if texte in ("−", "+"):
                bouton.setFixedWidth(34)
            barre.addWidget(bouton)
        colonne.addLayout(barre)

        scission = QSplitter(Qt.Orientation.Horizontal)
        scission.setHandleWidth(9)
        scission.setStyleSheet(apparence.STYLE_POIGNEE)
        self.liste_planches = QListWidget()
        self.liste_planches.setMinimumWidth(150)
        self.liste_planches.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.liste_planches.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.liste_planches.currentRowChanged.connect(self._planche_choisie)
        scission.addWidget(self.liste_planches)

        self.vue = vue_plan.VuePlan()
        self.vue.setMinimumWidth(300)
        self.vue.au_clic_planche = self._planche_cliquee
        self.vue.au_menu = self._menu_du_plan
        scission.addWidget(self.vue)
        scission.setStretchFactor(0, 0)
        scission.setStretchFactor(1, 1)
        scission.setSizes([230, 900])
        colonne.addWidget(scission, stretch=1)

        # Une planche de 12:1 ne remplira jamais un panneau de 3:2 : le
        # dessin est bridé par la largeur, et la hauteur restante était
        # du vide. La légende s'y loge sans lui prendre un pixel utile.
        self.legende = QListWidget()
        # ListMode et non IconMode : la pastille se met À CÔTÉ du nom
        # au lieu de le surmonter, deux fois moins haut pour autant
        # d'information.
        self.legende.setFlow(QListWidget.Flow.LeftToRight)
        self.legende.setWrapping(True)
        self.legende.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.legende.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.legende.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.legende.setMaximumHeight(84)
        self.legende.setSpacing(2)
        self.legende.setFrameShape(QListWidget.Shape.NoFrame)
        self.legende.setToolTip(
            "Chaque référence a sa teinte, la même d'une séance à l'autre.")
        colonne.addWidget(self.legende)

        colonne.addWidget(apparence.discret(
            "Ctrl+molette : zoomer — glisser : déplacer — double-clic :"
            " ajuster — clic sur une planche : la sélectionner — clic"
            " droit : épingler la planche, imposer une planche à la pièce."))
        return page

    def _page_achats(self) -> QWidget:
        page = QWidget()
        colonne = QVBoxLayout(page)
        colonne.addWidget(apparence.discret(
            "Les planches NEUVES réellement entamées — les chutes, déjà en"
            " atelier, n'y figurent jamais. Renseignez le prix d'une"
            " planche dans le stock pour obtenir le coût."))
        self.liste_achats = QListWidget()
        colonne.addWidget(self.liste_achats, stretch=1)
        return page

    def _page_chutes(self) -> QWidget:
        page = QWidget()
        colonne = QVBoxLayout(page)
        colonne.addWidget(apparence.discret(
            "Les restes assez grands pour resservir — la raison d'être du"
            " chutier. « Ranger au stock » met l'atelier à jour comme si"
            " le débit était fait : les planches entamées en sortent, ces"
            " chutes y entrent."))
        self.liste_chutes = QListWidget()
        colonne.addWidget(self.liste_chutes, stretch=1)
        ligne = QHBoxLayout()
        ligne.addStretch()
        self.bouton_ranger = QPushButton("Ranger ces chutes au stock…")
        self.bouton_ranger.clicked.connect(self._ranger_chutes)
        ligne.addWidget(self.bouton_ranger)
        colonne.addLayout(ligne)
        return page

    def _page_non_placees(self) -> QWidget:
        page = QWidget()
        colonne = QVBoxLayout(page)
        self.mot_non_placees = apparence.discret("")
        colonne.addWidget(self.mot_non_placees)
        self.liste_non_placees = QListWidget()
        colonne.addWidget(self.liste_non_placees, stretch=1)
        return page

    # -- état ---------------------------------------------------------------

    def _vider_resultats(self):
        """Efface TOUT ce qu'un calcul avait affiché. « Nouveau » ne vidait
        que le plan et les tuiles : les onglets gardaient leurs comptes,
        la liste d'achats sa ligne et la légende ses pastilles — un projet
        neuf s'ouvrait avec le bilan du précédent."""
        self._resultat = None
        self._epingles = []
        self.vue.epinglees = set()
        self._a_jour = False
        self.bilan.vider()
        self.vue.message_vide = (
            "Saisissez les pièces à débiter, vérifiez le stock,\n"
            "puis Calculer le débit (F5)."
            if not self.table_pieces.lignes_utiles() else
            "Calculer le débit (F5) pour voir le plan.")
        self.vue.afficher([])
        for liste in (self.liste_planches, self.liste_achats,
                      self.liste_chutes, self.liste_non_placees,
                      self.legende):
            liste.clear()
        self.bouton_ranger.setEnabled(False)
        self.mot_non_placees.setText("")
        for indice, libelle in ((ACHATS, "À acheter"),
                                (CHUTES, "Chutes créées"),
                                (NON_PLACEES, "Pièces non placées")):
            self.onglets_resultats.setTabText(indice, libelle)
        self.onglets_resultats.tabBar().setTabTextColor(
            NON_PLACEES, self.palette().text().color())

    def _saisie_changee(self, *_):
        if self._chargement:
            return
        self._modifie = True
        self._a_jour = False
        self._rafraichir_etat()

    def _rafraichir_etat(self):
        self.resume_pieces.setText(self.table_pieces.resume())
        self.resume_stock.setText(self.table_stock.resume())
        self.titre_pieces.setText(
            "Pièces  ·  %d" % len(self.table_pieces.lignes_utiles()))
        self.titre_stock.setText(
            "Stock  ·  %d" % len(self.table_stock.lignes_utiles()))
        self._rafraichir_colonnes()

        nom = os.path.basename(self._chemin) if self._chemin else "Projet non enregistré"
        self.etat_fichier.setText(("● " if self._modifie else "") + nom)
        self.setWindowTitle("%s%s — %s"
                            % ("● " if self._modifie else "", nom, TITRE))
        if self._resultat is None:
            self.etat_calcul.setText("Aucun calcul")
            self.etat_calcul.setStyleSheet("color: palette(mid);")
        elif self._a_jour:
            self.etat_calcul.setText("Plan à jour")
            self.etat_calcul.setStyleSheet("color: palette(mid);")
        else:
            self.etat_calcul.setText("⚠ Saisie modifiée — F5 pour recalculer")
            self.etat_calcul.setStyleSheet(
                "color: %s; font-weight: bold;" % apparence.ORANGE.name())

    # -- édition ------------------------------------------------------------

    def _table_courante(self):
        return self._table_active

    def _ajouter_ligne(self):
        table = self._table_courante()
        ligne = table.ajouter_ligne()
        table.setCurrentCell(ligne, 0)
        table.editItem(table.item(ligne, 0))

    def _dupliquer(self):
        table = self._table_courante()
        if table is not None:
            table.dupliquer_selection()

    def _supprimer(self):
        table = self._table_courante()
        if table is not None:
            table.supprimer_selection()

    def _matiere_en_lot(self):
        table = self._table_courante()
        if table is None:
            return
        lignes = table.lignes_selectionnees()
        if not lignes:
            QMessageBox.information(
                self, "Aucune ligne sélectionnée",
                "Choisissez d'abord une ou plusieurs lignes (clic, puis"
                " Ctrl ou Maj-clic pour en ajouter).")
            return
        matieres = self.table_stock.matieres()
        depart = table.texte(lignes[0], 4)
        matiere, ok = QInputDialog.getItem(
            self, "Matière", "Matière à appliquer aux %d ligne(s) choisie(s) :"
            % len(lignes), matieres,
            matieres.index(depart) if depart in matieres else 0, True)
        if not ok or not matiere.strip():
            return
        for ligne in lignes:
            table.item(ligne, 4).setText(matiere.strip())

    def _basculer_avancees(self, montrer):
        self._reglages.setValue("colonnes_avancees", montrer)
        self._rafraichir_colonnes()

    def _rafraichir_colonnes(self):
        """Les colonnes rarement remplies se replient, sauf si une ligne
        s'en sert : on ne cache jamais une valeur saisie."""
        montrer = self.a_avancees.isChecked()
        for table in (self.table_pieces, self.table_stock):
            table.montrer_avancees(montrer)

    def _basculer_saisie(self, masquer):
        if masquer:
            self._tailles_saisie = self._splitter.sizes()
            self._splitter.setSizes([0, sum(self._tailles_saisie)])
            self.a_saisie.setText("Montrer la &saisie")
        else:
            self._splitter.setSizes(
                getattr(self, "_tailles_saisie", [620, 880]))
            self.a_saisie.setText("Masquer la &saisie")

    # -- calcul --------------------------------------------------------------

    def _reglages_memorises(self) -> opt.Parametres:
        brut = self._reglages.value("parametres")
        if not brut:
            return opt.Parametres()
        try:
            return opt.Parametres(**json.loads(brut))
        except (ValueError, TypeError):
            # Un réglage retiré du cœur depuis la dernière séance ne doit
            # pas empêcher l'appli de s'ouvrir.
            return opt.Parametres()

    def _memoriser_reglages(self):
        try:
            parametres = self._parametres_actuels()
        except (ErreurSaisie, ValueError):
            return
        self._reglages.setValue(
            "parametres", json.dumps(dataclasses.asdict(parametres)))

    def _parametres_actuels(self) -> opt.Parametres:
        return opt.Parametres(
            trait_de_scie=self.spin_trait.value(),
            chute_mini_longueur=self.spin_chute_longueur.value(),
            chute_mini_largeur=self.spin_chute_largeur.value(),
            surcote_longueur=self.spin_surcote_longueur.value(),
            surcote_largeur=self.spin_surcote_largeur.value(),
            tolerance_epaisseur=self.spin_tolerance.value(),
            surcote_joint=self.spin_surcote_joint.value(),
            essais_melanges=self.spin_essais.value(),
            priorite=self.choix_priorite.currentData(),
            passes_amelioration=self.spin_passes.value(),
            ecart_contours=self.spin_ecart.value(),
            marge_bord=self.spin_marge_bord.value(),
            pas_rotation=self.choix_rotation.currentData(),
            processus=self.spin_processus.value())

    def _appliquer_parametres(self, p: opt.Parametres):
        for spin, valeur in ((self.spin_trait, p.trait_de_scie),
                             (self.spin_chute_longueur, p.chute_mini_longueur),
                             (self.spin_chute_largeur, p.chute_mini_largeur),
                             (self.spin_surcote_longueur, p.surcote_longueur),
                             (self.spin_surcote_largeur, p.surcote_largeur),
                             (self.spin_tolerance, p.tolerance_epaisseur),
                             (self.spin_surcote_joint, p.surcote_joint),
                             (self.spin_essais, p.essais_melanges),
                             (self.spin_passes, p.passes_amelioration),
                             (self.spin_ecart, p.ecart_contours),
                             (self.spin_marge_bord, p.marge_bord),
                             (self.spin_processus, p.processus)):
            spin.setValue(valeur)
        self.choix_priorite.setCurrentIndex(
            max(0, self.choix_priorite.findData(p.priorite)))
        self.choix_rotation.setCurrentIndex(
            max(0, self.choix_rotation.findData(p.pas_rotation)))

    def _calculer_si_pieces(self):
        """Le calcul d'accueil : sur un atelier garni, la feuille de
        pièces est blanche, et « aucune pièce à débiter » n'est pas une
        erreur à l'ouverture."""
        if self.table_pieces.lignes_utiles():
            self._calculer()
        else:
            self._vider_resultats()
            self._rafraichir_etat()

    def _calculer(self):
        # Un débit de 150 pièces demande un tiers de seconde, mais rien ne
        # borne une saisie : le sablier dit au moins que la fenêtre n'est
        # pas figée pour rien.
        resultat, plainte = None, None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pieces = self.table_pieces.pieces()
            stock = self.table_stock.stock()
            if not pieces:
                raise ErreurSaisie("aucune pièce à débiter")
            parametres = self._parametres_actuels()
            try:
                resultat = opt.optimiser(pieces, stock, parametres,
                                         epingles=self._epingles)
            except ValueError as erreur:
                if not self._epingles or not str(erreur).startswith("épingle"):
                    raise
                # Une épingle qui ne colle plus (pièce ou planche changée)
                # ne doit pas bloquer le calcul : on la relâche, on le
                # dit, et on recalcule libre.
                self.statusBar().showMessage(
                    "Épingles relâchées — %s" % erreur, 10000)
                self._epingles = []
                resultat = opt.optimiser(pieces, stock, parametres)
        except (ErreurSaisie, ValueError) as erreur:
            plainte = str(erreur)
        finally:
            # Le curseur revient AVANT la boîte de message : sinon elle
            # s'affiche sous un sablier, à attendre un clic.
            QApplication.restoreOverrideCursor()
        if plainte is not None:
            QMessageBox.warning(self, "Saisie invalide", plainte)
            return
        self._resultat = resultat
        self._a_jour = True
        self._afficher_resultat()
        self._rafraichir_etat()

    def _afficher_resultat(self):
        r = self._resultat
        b = r.bilan
        cout = sum(a.nombre * a.prix for a in r.achats)

        self.bilan.posees.poser(
            "%d / %d" % (b.nb_posees, b.nb_demandees),
            "%d non placée(s)" % b.nb_non_placees if b.nb_non_placees else "",
            "alerte" if b.nb_non_placees else "neutre")
        self.bilan.rendement.poser("%s %%" % opt._pct(b.rendement),
                                   "%s m² de pièces" % opt._m2(b.surface_pieces))
        self.bilan.planches.poser(
            "%d" % b.nb_planches_entamees,
            "dont %d chute(s)" % b.nb_chutes_consommees
            if b.nb_chutes_consommees else "aucune chute écoulée")
        self.bilan.pertes.poser("%s m²" % opt._m2(b.surface_perdue),
                                "sciure et rebuts · %d coupe(s)" % b.nb_coupes)
        self.bilan.chutes.poser(
            "%d" % len(r.chutes_creees),
            "%s m² à ranger" % opt._m2(b.surface_chutes_creees)
            if r.chutes_creees else "rien à garder",
            "accent" if r.chutes_creees else "neutre")
        self.bilan.achat.poser(
            "%d" % sum(a.nombre for a in r.achats),
            opt._prix(cout) if cout else "prix non renseignés")

        self.liste_achats.clear()
        for a in r.achats:
            detail = (" — %s" % opt._prix(a.nombre * a.prix)) if a.prix else ""
            self.liste_achats.addItem(
                "%d × « %s » — %s × %s × %s mm, %s%s"
                % (a.nombre, a.reference, opt._mm(a.longueur),
                   opt._mm(a.largeur), opt._mm(a.epaisseur), a.matiere, detail))
        if cout:
            self.liste_achats.addItem("Total : %s" % opt._prix(cout))
        self.onglets_resultats.setTabText(
            ACHATS, "À acheter  ·  %d" % sum(a.nombre for a in r.achats))

        self.liste_chutes.clear()
        for cle, nombre in chutes_groupees(r).items():
            dim_x, dim_y, epaisseur, matiere, _fil = cle
            self.liste_chutes.addItem(
                "%d ×  %s × %s × %s mm — %s"
                % (nombre, opt._mm(dim_x), opt._mm(dim_y), opt._mm(epaisseur),
                   matiere))
        self.bouton_ranger.setEnabled(bool(r.chutes_creees))
        self.onglets_resultats.setTabText(
            CHUTES, "Chutes créées  ·  %d" % len(r.chutes_creees))

        self.liste_non_placees.clear()
        for n in r.non_placees:
            item = QListWidgetItem("« %s » ×%d — %s"
                                   % (n.piece.reference, n.exemplaires, n.raison))
            item.setForeground(apparence.ALERTE)
            self.liste_non_placees.addItem(item)
        self.mot_non_placees.setText(
            "Tout est passé — aucune pièce laissée de côté."
            if not r.non_placees else
            "Ces pièces n'ont trouvé aucune place. Ajoutez du stock,"
            " relâchez le fil, ou cochez « Composable » pour celles qui"
            " peuvent se faire en plusieurs lames collées.")
        self.onglets_resultats.setTabText(
            NON_PLACEES, "Pièces non placées  ·  %d" % b.nb_non_placees
            if b.nb_non_placees else "Pièces non placées")
        self.onglets_resultats.tabBar().setTabTextColor(
            NON_PLACEES, apparence.ALERTE if b.nb_non_placees
            else self.palette().text().color())

        # Une teinte par référence, calculée sur le débit ENTIER : en
        # mode « planche seule » les couleurs doivent rester celles de la
        # vue d'ensemble, sinon une pièce changerait de couleur en
        # changeant de mode.
        self.vue.couleurs = apparence.palette_pieces(
            {pose.piece.reference for d in r.debits for pose in d.poses})
        # Les débits épinglés ouvrent la liste, dans l'ordre où ils ont
        # été donnés — c'est leur rang qui les marque sur le plan.
        self.vue.epinglees = set(range(1, len(self._epingles) + 1))

        self.liste_planches.blockSignals(True)
        self.liste_planches.clear()
        for i, debit in enumerate(r.debits, 1):
            plusieurs = debit.planche.quantite > 1 or debit.planche.illimite
            ex = " (ex. %d)" % debit.exemplaire if plusieurs else ""
            texte = ("%d. %s%s — %d pièce(s), %s %%"
                     % (i, debit.planche.reference, ex, len(debit.poses),
                        opt._pct(debit.rendement)))
            item = QListWidgetItem(texte)
            item.setToolTip(texte)
            self.liste_planches.addItem(item)
        self.liste_planches.blockSignals(False)
        if r.debits:
            self.liste_planches.setCurrentRow(0)
        self._redessiner()

    # -- dessin --------------------------------------------------------------

    def _redessiner(self):
        if self._resultat is None:
            self.vue.afficher([], self.case_traits.isChecked())
            return
        ligne = max(0, self.liste_planches.currentRow())
        if self.choix_vue.currentData():
            debits = list(enumerate(self._resultat.debits, 1))
        else:
            if not self._resultat.debits:
                debits = []
            else:
                debits = [(ligne + 1, self._resultat.debits[ligne])]
        self.vue.afficher(debits, self.case_traits.isChecked())
        if debits:
            self.vue.selectionner(ligne + 1, defiler=False)
        self.liste_planches.setVisible(not self.choix_vue.currentData())
        self._remplir_legende(debits)

    def _remplir_legende(self, debits):
        self.legende.clear()
        comptes, cotes = {}, {}
        for _, debit in debits:
            for pose in debit.poses:
                reference = pose.piece.reference
                comptes[reference] = comptes.get(reference, 0) + 1
                cotes[reference] = (pose.dim_x, pose.dim_y)
        for reference, nombre in comptes.items():
            dim_x, dim_y = cotes[reference]
            item = QListWidgetItem(
                apparence.pastille(self.vue.couleur(reference)),
                "%s  ×%d" % (reference, nombre))
            item.setToolTip("%s — débitée à %s × %s mm"
                            % (reference, opt._mm(dim_x), opt._mm(dim_y)))
            self.legende.addItem(item)
        if any(debit.chutes for _, debit in debits):
            self.legende.addItem(QListWidgetItem(
                apparence.pastille(apparence.PLAN_CHUTE, hachure=True),
                "chute réutilisable"))
        if any(debit.planche.a_des_defauts for _, debit in debits):
            self.legende.addItem(QListWidgetItem(
                apparence.pastille(apparence.PLAN_DEFAUT, hachure=True),
                "défaut écarté"))
        self.legende.addItem(QListWidgetItem(
            apparence.pastille(apparence.PLAN_PAPIER), "perte"))

    def _planche_choisie(self, ligne):
        if self._resultat is None or ligne < 0:
            return
        if self.choix_vue.currentData():
            self.vue.selectionner(ligne + 1)
        else:
            self._redessiner()

    def _planche_cliquee(self, numero):
        self.liste_planches.blockSignals(True)
        self.liste_planches.setCurrentRow(numero - 1)
        self.liste_planches.blockSignals(False)

    # -- épingles et planches imposées --------------------------------------------

    def _menu_du_plan(self, numero, pose, position):
        """Le clic droit sur le plan : épingler / relâcher la planche, et
        pour une pièce, la tailler ailleurs — les deux façons de dire au
        chutier « pas comme ça » sans tricher sur les quantités."""
        if self._resultat is None:
            return
        menu = QMenu(self)
        debit = self._resultat.debits[numero - 1]
        if numero in self.vue.epinglees:
            menu.addAction("Relâcher la planche %d" % numero,
                           lambda: self._desepingler(numero))
        else:
            menu.addAction("Épingler la planche %d — la garder telle quelle"
                           % numero, lambda: self._epingler(numero))
        if pose is not None:
            menu.addSeparator()
            sous = menu.addMenu("Tailler « %s » dans…" % pose.piece.reference)
            for reference in self.table_stock.references():
                action = sous.addAction(reference)
                action.setCheckable(True)
                action.setChecked(reference == pose.piece.planche)
                action.triggered.connect(
                    lambda _=False, r=reference, p=pose.piece.reference:
                    self._imposer_planche(p, r))
            if pose.piece.planche:
                sous.addSeparator()
                sous.addAction("Laisser le chutier choisir",
                               lambda p=pose.piece.reference:
                               self._imposer_planche(p, ""))
        menu.exec(position)
        del debit

    def _epingler(self, numero):
        if self._resultat is None or not self._a_jour:
            QMessageBox.information(
                self, "Plan périmé",
                "Recalculez (F5) avant d'épingler : la planche affichée ne"
                " correspond plus à la saisie.")
            return
        debit = self._resultat.debits[numero - 1]
        if debit in self._epingles:
            return
        self._epingles.append(debit)
        self._modifie = True
        self._calculer()

    def _desepingler(self, numero):
        # Les épingles ouvrent la liste des débits, dans leur ordre : le
        # numéro affiché est leur rang. (Comparer les objets ne marche
        # pas : le calcul renumérote et rebâtit chaque débit.)
        if self._resultat is None or numero > len(self._epingles):
            return
        del self._epingles[numero - 1]
        self._modifie = True
        self._calculer()

    def _tout_desepingler(self):
        if not self._epingles:
            return
        self._epingles = []
        self._modifie = True
        if self._resultat is not None:
            self._calculer()

    def _imposer_planche(self, reference_piece, reference_planche):
        self.table_pieces.imposer_planche(reference_piece, reference_planche)
        self._calculer()

    # -- chutes au stock -------------------------------------------------------

    def _ranger_chutes(self):
        if self._resultat is None or not self._resultat.chutes_creees:
            return
        if not self._a_jour:
            # Le décompte se fait planche par planche, à l'identique : si
            # la saisie a bougé depuis le calcul, plus rien ne correspond
            # et l'opération retirerait — ou pas — n'importe quoi.
            QMessageBox.information(
                self, "Plan périmé",
                "La saisie a changé depuis le dernier calcul : recalculez"
                " (F5) avant de ranger les chutes, sinon le stock serait"
                " mis à jour d'après un débit qui n'est plus celui-là.")
            return
        consommees = planches_consommees(self._resultat)
        groupes = chutes_groupees(self._resultat)

        lignes = ["Le stock sera mis à jour comme si le débit était fait :"]
        for planche, nombre in consommees.items():
            lignes.append("  − %d × « %s » (%s × %s mm)"
                          % (nombre, planche.reference,
                             opt._mm(planche.longueur),
                             opt._mm(planche.largeur)))
        lignes.append("  + %d chute(s) en %d référence(s)"
                      % (len(self._resultat.chutes_creees), len(groupes)))
        lignes.append("")
        lignes.append("Le plan affiché décrira alors le stock d'avant :"
                      " il faudra le recalculer. Continuer ?")
        if QMessageBox.question(
                self, "Ranger les chutes au stock", "\n".join(lignes),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel) \
                != QMessageBox.StandardButton.Yes:
            return

        self.table_stock.remplir(
            stock_apres_debit(self.table_stock.stock(), self._resultat))
        self._a_jour = False
        self._modifie = True
        self._rafraichir_etat()
        self.table_stock.setFocus()
        # L'atelier s'écrit tout de suite : c'est un inventaire, pas un
        # document — la chute existe sur l'étagère que le projet soit
        # enregistré ou non.
        if self._enregistrer_atelier():
            self.statusBar().showMessage(
                "Stock de l'atelier mis à jour : %s" % self._chemin_atelier,
                8000)

    # -- l'atelier ----------------------------------------------------------------

    def _atelier(self) -> list:
        """Le stock commun, tel que le fichier le dit."""
        try:
            return projet_io.lire_atelier(self._chemin_atelier)
        except (OSError, ValueError) as erreur:
            QMessageBox.warning(
                self, "Stock de l'atelier illisible",
                "%s\n\nLe débit se fera sans lui." % erreur)
            return []

    def _enregistrer_atelier(self) -> bool:
        """Écrit au fichier commun les lignes cochées « Atelier ». Une
        saisie illisible n'écrit rien (et rend faux) : on ne remplace pas
        un inventaire par un fichier tronqué."""
        try:
            stock = self.table_stock.stock()
        except ErreurSaisie:
            return False
        try:
            projet_io.enregistrer_atelier(
                self._chemin_atelier, [s for s in stock if s.atelier])
        except OSError as erreur:
            QMessageBox.warning(self, "Atelier non enregistré", str(erreur))
            return False
        return True

    def _atelier_frais(self) -> list:
        """Sauve les lignes d'atelier de la table, puis relit le fichier :
        ce qui a été tapé n'est jamais perdu, ce qu'une autre fenêtre a
        rangé entre-temps est repris."""
        self._enregistrer_atelier()
        return self._atelier()

    def _recharger_atelier(self):
        try:
            stock = [s for s in self.table_stock.stock() if not s.atelier]
        except ErreurSaisie as erreur:
            QMessageBox.warning(self, "Saisie invalide", str(erreur))
            return
        atelier = self._atelier()
        self._chargement = True
        self.table_stock.remplir(stock + atelier)
        self._chargement = False
        self._saisie_changee()
        self.statusBar().showMessage(
            "%d ligne(s) relue(s) depuis %s" % (len(atelier),
                                                 self._chemin_atelier), 8000)

    # -- fichiers ---------------------------------------------------------------

    def _dossier(self) -> str:
        return self._reglages.value("dossier", os.path.expanduser("~"))

    def _retenir_dossier(self, chemin: str):
        self._reglages.setValue("dossier", os.path.dirname(chemin))

    def _nouveau(self):
        if not self._confirmer_abandon():
            return
        atelier = self._atelier_frais()
        self._chargement = True
        self.table_pieces.setRowCount(0)
        self.table_stock.remplir(atelier)
        self.table_pieces.ajouter_ligne()
        if not atelier:
            self.table_stock.ajouter_ligne()
        self._appliquer_parametres(self._reglages_memorises())
        self._chargement = False
        self._chemin = None
        self._modifie = False
        self._vider_resultats()
        self._rafraichir_etat()

    def _confirmer_abandon(self, precision: str = "") -> bool:
        """Vrai si l'on peut écraser la saisie courante.

        Trois issues, pas deux : n'offrir qu'« abandonner ou annuler »
        obligeait à annuler, enregistrer à la main, puis recommencer le
        geste — et invitait à cliquer « abandonner » de lassitude."""
        if not self._modifie:
            return True
        reponse = QMessageBox.warning(
            self, "Projet modifié",
            "Le projet a changé depuis le dernier enregistrement.\n%s"
            % (precision + "\n" if precision else ""),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if reponse == QMessageBox.StandardButton.Save:
            self._enregistrer()
            return not self._modifie      # l'enregistrement a pu échouer
        return reponse == QMessageBox.StandardButton.Discard

    def _ouvrir(self):
        if not self._confirmer_abandon():
            return
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet", self._dossier(), "Projet chutier (*.json)")
        if not chemin:
            return
        try:
            pieces, stock, parametres = projet_io.lire(chemin)
            epingles = projet_io.lire_epingles(chemin)
        except (OSError, ValueError) as erreur:
            QMessageBox.warning(self, "Ouverture impossible", str(erreur))
            return
        # Le projet ne porte que SES planches ; l'atelier vient du fichier
        # commun, dans l'état où il est aujourd'hui — pas celui du jour
        # où le projet a été enregistré.
        self._remplir(pieces, [s for s in stock if not s.atelier]
                      + self._atelier_frais(), parametres)
        self._chemin = chemin
        self._modifie = False
        self._retenir_dossier(chemin)
        self._rafraichir_etat()
        self._epingles = epingles
        if self.table_pieces.lignes_utiles():
            self._calculer()
        else:
            self._vider_resultats()

    def _enregistrer(self):
        if not self._chemin:
            return self._enregistrer_sous()
        try:
            stock = self.table_stock.stock()
            projet_io.enregistrer(self._chemin, self.table_pieces.pieces(),
                                  [s for s in stock if not s.atelier],
                                  self._parametres_actuels(),
                                  epingles=self._epingles)
        except (OSError, ErreurSaisie) as erreur:
            QMessageBox.warning(self, "Enregistrement impossible", str(erreur))
            return
        self._enregistrer_atelier()
        self._modifie = False
        self._rafraichir_etat()

    def _enregistrer_sous(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le projet", self._dossier(),
            "Projet chutier (*.json)")
        if not chemin:
            return
        if not chemin.lower().endswith(".json"):
            chemin += ".json"
        self._chemin = chemin
        self._retenir_dossier(chemin)
        self._enregistrer()

    def _importer_csv(self):
        # L'import REMPLACE toute la liste de pièces : sans cette
        # question, un clic effaçait une saisie non enregistrée.
        if self.table_pieces.lignes_utiles() and not self._confirmer_abandon(
                "La liste de pièces va être remplacée par le contenu du"
                " fichier."):
            return
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Importer des pièces", self._dossier(), "CSV (*.csv)")
        if not chemin:
            return
        try:
            pieces = csv_io.lire_pieces(chemin)
        except (OSError, ValueError) as erreur:
            QMessageBox.warning(self, "Import impossible", str(erreur))
            return
        self._chargement = True
        self.table_pieces.remplir(pieces)
        self._chargement = False
        self._retenir_dossier(chemin)
        self.table_pieces.setFocus()
        self._saisie_changee()

    def _importer_contours(self):
        """Chaque tracé fermé du SVG devient une pièce à contour, AJOUTÉE
        à la liste (l'import CSV, lui, remplace : c'est une feuille de
        débit entière ; ici ce sont des formes qu'on vient chercher)."""
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Importer des contours", self._dossier(), "SVG (*.svg)")
        if not chemin:
            return
        try:
            formes, avertissements = contours_svg.formes_depuis_svg(chemin)
        except (OSError, ValueError, ET_ParseError) as erreur:
            QMessageBox.warning(self, "Import impossible", str(erreur))
            return
        if not formes:
            QMessageBox.information(
                self, "Aucun contour",
                "Le fichier ne contient aucun tracé fermé.\n%s"
                % "\n".join(avertissements))
            return
        self._ajouter_contours(formes)
        self._retenir_dossier(chemin)
        self.table_pieces.setFocus()
        self._saisie_changee()
        message = "%d contour(s) importé(s)" % len(formes)
        if avertissements:
            QMessageBox.information(self, "Contours importés",
                                    message + "\n\n" + "\n".join(avertissements))
        else:
            self.statusBar().showMessage(message, 8000)

    def _ajouter_contours(self, formes):
        """Les formes entrent avec la matière et l'épaisseur de la première
        ligne du stock — le plus souvent la bonne, et une cellule à
        corriger vaut mieux qu'une cellule vide. Fil indifférent : une
        forme découpée à la CNC tourne comme on veut, sauf à dire le
        contraire."""
        try:
            stock = self.table_stock.stock()
        except ErreurSaisie:
            stock = []
        matiere = stock[0].matiere if stock else ""
        epaisseur = stock[0].epaisseur if stock else 18
        self._chargement = True
        # Les lignes vides de fin s'effacent : une forme y prend place.
        for ligne in reversed(range(self.table_pieces.rowCount())):
            if not self.table_pieces.texte(ligne, 0):
                self.table_pieces.removeRow(ligne)
        for forme in formes:
            self.table_pieces.ajouter_ligne(
                reference=forme["nom"], longueur=forme["longueur"],
                largeur=forme["largeur"], epaisseur=epaisseur,
                matiere=matiere, quantite=1, fil=opt.FIL_INDIFFERENT,
                contour=forme["contour"], trous=forme.get("trous", ()))
        self._chargement = False

    def _exporter_svg(self):
        self._exporter_decoupe("svg")

    def _exporter_decoupe(self, format_):
        """Une planche par fichier, à l'échelle 1 : c'est ce que la CNC
        attend, pas un plan d'ensemble. SVG, DXF ou LightBurn."""
        if self._resultat is None or not self._resultat.debits:
            QMessageBox.information(self, "Rien à exporter",
                                    "Calculez d'abord le débit (F5).")
            return
        planches = self.vue.debits_affiches()
        filtre, extension = export_cnc.FORMATS[format_]
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Exporter la découpe (une planche par fichier)",
            self._dossier(), filtre)
        if not chemin:
            return
        if chemin.lower().endswith(extension):
            chemin = chemin[:-len(extension)]
        titre = os.path.splitext(os.path.basename(self._chemin))[0] \
            if self._chemin else "Feuille de débit"
        ecrits = []
        try:
            for numero, debit in planches:
                nom = ("%s%s" % (chemin, extension) if len(planches) == 1
                       else "%s-planche-%d%s" % (chemin, numero, extension))
                with open(nom, "w", encoding="utf-8") as f:
                    f.write(export_cnc.decoupe(format_, debit, numero, titre))
                ecrits.append(nom)
        except OSError as erreur:
            QMessageBox.warning(self, "Export impossible", str(erreur))
            return
        self._retenir_dossier(ecrits[0])
        self.statusBar().showMessage(
            "%d fichier(s) écrit(s) : %s" % (len(ecrits), ecrits[0]), 8000)

    def _exporter_image(self):
        if self._resultat is None or not self._resultat.debits:
            QMessageBox.information(
                self, "Rien à exporter",
                "Calculez d'abord le débit (F5).")
            return
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Exporter le plan", self._dossier(), "Image PNG (*.png)")
        if not chemin:
            return
        if not chemin.lower().endswith(".png"):
            chemin += ".png"
        self._retenir_dossier(chemin)
        image = self._image_du_plan(self.vue.debits_affiches(), 2400)
        if image is None or not image.save(chemin):
            QMessageBox.warning(self, "Export impossible",
                                "L'image n'a pas pu être enregistrée.")
        else:
            self.statusBar().showMessage(
                "Plan exporté (%d × %d px) : %s"
                % (image.width(), image.height(), chemin), 8000)

    def _imprimer(self):
        """Le plan sur papier, celui qu'on emporte à l'établi.

        On imprime l'IMAGE du plan plutôt que la scène directement : les
        étiquettes des pièces sont dessinées à taille de pixel fixe (elles
        doivent rester lisibles à tout zoom), si bien qu'une scène rendue
        telle quelle sur une imprimante à 1200 points par pouce sortirait
        avec des noms hauts d'un demi-millimètre.
        """
        if self._resultat is None or not self._resultat.debits:
            QMessageBox.information(self, "Rien à imprimer",
                                    "Calculez d'abord le débit (F5).")
            return
        imprimante = QPrinter(QPrinter.PrinterMode.HighResolution)
        imprimante.setPageOrientation(QPageLayout.Orientation.Landscape)
        if QPrintDialog(imprimante, self).exec() != QDialog.DialogCode.Accepted:
            return
        peintre = QPainter()
        if not peintre.begin(imprimante):
            QMessageBox.warning(self, "Impression impossible",
                                "L'imprimante n'a pas accepté le document.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pages = self.composer_document(peintre, imprimante)
        finally:
            peintre.end()
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            "Plan envoyé à l'impression (%d page(s))" % pages, 6000)

    # -- étiquettes -----------------------------------------------------------------

    ETIQUETTES_COLONNES, ETIQUETTES_LIGNES = 3, 8     # planche A4 70 × 37 mm

    def _etiquettes(self) -> list:
        """Une entrée par pièce débitée, dans l'ordre des planches et des
        poses — l'ordre où on les sortira de la scie."""
        if self._resultat is None:
            return []
        entrees = []
        for numero, debit in enumerate(self._resultat.debits, 1):
            pl = debit.planche
            plusieurs = pl.quantite > 1 or pl.illimite
            planche = "planche %d — %s%s" % (
                numero, pl.reference,
                " (ex. %d)" % debit.exemplaire if plusieurs else "")
            for pose in debit.poses:
                entrees.append((pose.piece.reference,
                                "%s × %s × %s mm" % (opt._mm(pose.dim_x),
                                                     opt._mm(pose.dim_y),
                                                     opt._mm(pose.piece.epaisseur)),
                                planche,
                                "%d / %d" % (pose.exemplaire,
                                             pose.piece.quantite),
                                self.vue.couleur(pose.piece.reference)))
        return entrees

    def _pages_etiquettes(self) -> list:
        par_page = self.ETIQUETTES_COLONNES * self.ETIQUETTES_LIGNES
        entrees = self._etiquettes()
        return [entrees[i:i + par_page]
                for i in range(0, len(entrees), par_page)]

    def _imprimer_etiquettes(self):
        if self._resultat is None or not self._resultat.debits:
            QMessageBox.information(self, "Rien à imprimer",
                                    "Calculez d'abord le débit (F5).")
            return
        imprimante = QPrinter(QPrinter.PrinterMode.HighResolution)
        imprimante.setPageOrientation(QPageLayout.Orientation.Portrait)
        if QPrintDialog(imprimante, self).exec() != QDialog.DialogCode.Accepted:
            return
        peintre = QPainter()
        if not peintre.begin(imprimante):
            QMessageBox.warning(self, "Impression impossible",
                                "L'imprimante n'a pas accepté le document.")
            return
        try:
            pages = self.composer_etiquettes(peintre, imprimante)
        finally:
            peintre.end()
        self.statusBar().showMessage(
            "Étiquettes envoyées à l'impression (%d page(s))" % pages, 6000)

    def composer_etiquettes(self, peintre: QPainter, imprimante) -> int:
        """Peint toutes les pages d'étiquettes et rend leur nombre. Séparé
        du choix de l'imprimante pour être éprouvé sur un PDF."""
        pages = self._pages_etiquettes()
        for numero, entrees in enumerate(pages, 1):
            if numero > 1:
                imprimante.newPage()
            self._dessiner_etiquettes(peintre, entrees)
        return len(pages)

    def _dessiner_etiquettes(self, peintre: QPainter, entrees: list):
        """Une grille de 3 × 8 sur la page : les planches d'étiquettes du
        commerce à 70 × 37 mm. Chaque étiquette : la référence en gras,
        les cotes, la planche d'où elle vient, son rang — et à gauche une
        bande de la couleur qu'elle a sur le plan, pour retrouver la
        pièce sur le papier comme sur le bois."""
        page = QRectF(0, 0, peintre.device().width(),
                      peintre.device().height())
        marge_x, marge_y = page.width() * 0.035, page.height() * 0.03
        largeur = (page.width() - 2 * marge_x) / self.ETIQUETTES_COLONNES
        hauteur = (page.height() - 2 * marge_y) / self.ETIQUETTES_LIGNES
        police = peintre.font()
        for i, (reference, cotes, planche, rang, couleur) in enumerate(entrees):
            ligne, colonne = divmod(i, self.ETIQUETTES_COLONNES)
            case = QRectF(marge_x + colonne * largeur,
                          marge_y + ligne * hauteur, largeur, hauteur)
            interieur = case.adjusted(largeur * 0.06, hauteur * 0.12,
                                      -largeur * 0.06, -hauteur * 0.12)
            bande = QRectF(interieur.left(), interieur.top(),
                           largeur * 0.05, interieur.height())
            peintre.fillRect(bande, couleur)
            texte = interieur.adjusted(largeur * 0.08, 0, 0, 0)
            haut = texte.top()
            for chaine, taille, gras in ((reference, 11, True),
                                         (cotes, 10, False),
                                         (planche, 8, False),
                                         ("pièce %s" % rang, 8, False)):
                police.setPointSize(taille)
                police.setBold(gras)
                peintre.setFont(police)
                h = peintre.fontMetrics().height() * 1.15
                peintre.drawText(QRectF(texte.left(), haut, texte.width(), h),
                                 int(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignVCenter),
                                 peintre.fontMetrics().elidedText(
                                     chaine, Qt.TextElideMode.ElideRight,
                                     int(texte.width())))
                haut += h
        police.setBold(False)
        peintre.setFont(police)

    def composer_document(self, peintre: QPainter, imprimante) -> int:
        """Peint toutes les pages et rend leur nombre. Séparé du choix de
        l'imprimante pour être éprouvé sur un PDF, sans matériel."""
        pages = self._pages_a_imprimer()
        largeur = max(1, int(peintre.device().width() * 0.98))
        for numero, planches in enumerate(pages, 1):
            if numero > 1:
                imprimante.newPage()
            # Sur le papier, les traits de scie se dessinent TOUJOURS,
            # numérotés : c'est la feuille qu'on suit à la scie.
            self._dessiner_page(peintre,
                                self._image_du_plan(planches, largeur,
                                                    traits=True),
                                numero, len(pages), planches)
        return len(pages)

    def _image_du_plan(self, planches: list, largeur_px: int,
                       traits: bool = None):
        """Le plan rendu à ``largeur_px``, sur une vue montée hors écran.

        Deux raisons de ne pas rendre la vue affichée : les tailles de
        texte doivent être grossies à la mesure de la résolution demandée
        (sur une page à 1200 points par pouce, des lettres réglées en
        pixels d'écran sortent à 0,4 mm), ce qui suppose de reconstruire
        la scène ; et on ne va pas défigurer le plan qu'on regarde pour
        écrire un fichier.
        """
        if not planches:
            return None
        vue = vue_plan.VuePlan()
        vue.couleurs = self.vue.couleurs
        vue.epinglees = self.vue.epinglees
        vue.afficher(planches,
                     self.case_traits.isChecked() if traits is None else traits,
                     largeur_prevue=largeur_px,
                     facteur_texte=max(1.0, largeur_px
                                       / vue_plan.VuePlan.LARGEUR_LISIBLE))
        return vue.rendre_image(largeur_px)

    def _pages_a_imprimer(self) -> list:
        """Les planches affichées réparties en pages.

        Une page tient à peu près 1,4 fois plus large que haute : on y met
        autant de planches que leur empilement peut en remplir sans
        écraser le dessin. Tout imprimer sur UNE page marchait pour cinq
        planches et donnait une bande illisible pour quinze — et un plan
        qu'on ne lit pas à l'établi n'est pas un plan.
        """
        planches = self.vue.debits_affiches()
        if not planches:
            return []
        longueur_max = max(d.planche.longueur for _, d in planches)
        largeur_max = max(d.planche.largeur for _, d in planches)
        # 2,2 : la planche, son cartouche et l'interligne qui la suit.
        par_page = max(1, round(0.62 * longueur_max / (largeur_max * 2.2)))
        return [planches[i:i + par_page]
                for i in range(0, len(planches), par_page)]

    def _dessiner_page(self, peintre: QPainter, image=None, numero: int = 1,
                       total: int = 1, planches: list = None):
        page = QRectF(0, 0, peintre.device().width(),
                      peintre.device().height())
        marge = page.width() * 0.01

        titre = os.path.splitext(os.path.basename(self._chemin))[0] \
            if self._chemin else "Feuille de débit"
        police = peintre.font()
        police.setPointSize(12)
        police.setBold(True)
        peintre.setFont(police)
        hauteur_titre = peintre.fontMetrics().height()
        peintre.drawText(QRectF(marge, marge, page.width() - 2 * marge,
                                hauteur_titre),
                         Qt.AlignmentFlag.AlignLeft, titre)
        if total > 1:
            peintre.drawText(QRectF(marge, marge, page.width() - 2 * marge,
                                    hauteur_titre),
                             Qt.AlignmentFlag.AlignRight,
                             "page %d / %d" % (numero, total))

        b = self._resultat.bilan
        police.setPointSize(9)
        police.setBold(False)
        peintre.setFont(police)
        hauteur_sous = peintre.fontMetrics().height()
        resume = ("%d/%d pièce(s) posée(s) · rendement %s %% · %d planche(s)"
                  " entamée(s) dont %d chute(s) · pertes %s m² · chutes"
                  " créées %d"
                  % (b.nb_posees, b.nb_demandees, opt._pct(b.rendement),
                     b.nb_planches_entamees, b.nb_chutes_consommees,
                     opt._m2(b.surface_perdue),
                     len(self._resultat.chutes_creees)))
        peintre.drawText(
            QRectF(marge, marge + hauteur_titre, page.width() - 2 * marge,
                   hauteur_sous),
            Qt.AlignmentFlag.AlignLeft, resume)

        haut = marge + hauteur_titre + hauteur_sous * 1.6
        if planches is None:
            planches = self.vue.debits_affiches()
        cible = QRectF(marge, haut, page.width() - 2 * marge,
                       page.height() - haut - marge)
        if image is None:
            image = self.vue.rendre_image(int(cible.width()))
        if image is None:
            return
        echelle = min(cible.width() / image.width(),
                      cible.height() / image.height())
        largeur, hauteur = image.width() * echelle, image.height() * echelle
        peintre.drawImage(
            QRectF(cible.left() + (cible.width() - largeur) / 2, cible.top(),
                   largeur, hauteur), image)
        self._dessiner_cotes(peintre, planches,
                             QRectF(cible.left(), cible.top() + hauteur * 1.04,
                                    cible.width(),
                                    cible.bottom() - cible.top() - hauteur * 1.04))

    def _dessiner_cotes(self, peintre: QPainter, planches: list,
                        zone: QRectF):
        """Sous le plan, planche par planche : les cotes de débit, puis la
        liste des coupes dans l'ordre, telle qu'on la suit à la scie.

        Une planche de 4 m sur 150 dessinée en travers d'une A4 laisse la
        moitié de la page blanche — et les étiquettes du dessin ne portent
        que le NOM des pièces, jamais leurs cotes quand elles sont
        étroites. C'est là qu'on met ce qui manque pour scier sans revenir
        à l'écran."""
        if not planches or zone.height() <= 0:
            return
        police = peintre.font()
        police.setPointSize(8)
        peintre.setFont(police)
        ligne = peintre.fontMetrics().height()
        if zone.height() < ligne * 3:
            return                      # pas la place : le dessin prime

        y = zone.top()
        gras = QFont(police)
        gras.setBold(True)

        def ecrire(texte, police_):
            nonlocal y
            peintre.setFont(police_)
            boite = QRectF(zone.left(), y, zone.width(), zone.bottom() - y)
            if boite.height() < ligne:
                return False
            hauteur = peintre.boundingRect(
                boite, int(Qt.TextFlag.TextWordWrap), texte).height()
            peintre.drawText(boite, int(Qt.TextFlag.TextWordWrap), texte)
            y += hauteur
            return True

        for numero, debit in planches:
            lots = {}
            for pose in debit.poses:
                cle = (pose.piece.reference, round(pose.dim_x, 1),
                       round(pose.dim_y, 1))
                lots[cle] = lots.get(cle, 0) + 1
            morceaux = ["%s %s × %s%s"
                        % (reference, opt._mm(dx), opt._mm(dy),
                           " ×%d" % n if n > 1 else "")
                        for (reference, dx, dy), n in lots.items()]
            if not ecrire("%d.  %s" % (numero, "   ·   ".join(morceaux)),
                          gras):
                break
            coupes = ["%d %s %s" % (
                c.ordre, "↕" if c.sens == opt.TRONCONNAGE else "↔",
                opt._mm(c.position)) for c in debit.coupes]
            if debit.imbriquee:
                if not ecrire("découpe CNC : contours imbriqués, à exporter"
                              " en SVG (Fichier → Exporter la découpe)",
                              police):
                    break
            elif coupes and not ecrire("coupes :  " + "   ·   ".join(coupes),
                                       police):
                break
            y += ligne * 0.5
        if planches[0][1].coupes:
            ecrire("↕ tronçonnage, en travers du fil, à x mm du bout"
                   " gauche  —  ↔ délignage, le long du fil, à y mm de la"
                   " rive basse. Chaque trait traverse de bord à bord le"
                   " morceau courant ; la lame mange du côté opposé à la"
                   " pièce.", apparence.police_discrete(police))
        peintre.setFont(police)

    def _exporter_fiche(self):
        """La fiche d'atelier : poses et coupes planche par planche.

        Le cœur produisait déjà ce texte (``Resultat.texte()``) et rien ne
        le montrait nulle part — c'est pourtant la liste qu'on coche à la
        scie, pièce après pièce."""
        if self._resultat is None:
            QMessageBox.information(self, "Rien à exporter",
                                    "Calculez d'abord le débit (F5).")
            return
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Exporter la fiche d'atelier", self._dossier(),
            "Texte (*.txt)")
        if not chemin:
            return
        if not chemin.lower().endswith(".txt"):
            chemin += ".txt"
        titre = os.path.splitext(os.path.basename(self._chemin))[0] \
            if self._chemin else "Feuille de débit"
        try:
            with open(chemin, "w", encoding="utf-8") as f:
                f.write("%s\n%s\n\n" % (titre, "=" * len(titre)))
                f.write(self._resultat.texte())
                f.write("\n")
        except OSError as erreur:
            QMessageBox.warning(self, "Export impossible", str(erreur))
            return
        self._retenir_dossier(chemin)
        self.statusBar().showMessage("Fiche d'atelier écrite : %s" % chemin,
                                     8000)

    def _exporter_csv(self):
        try:
            pieces = self.table_pieces.pieces()
        except ErreurSaisie as erreur:
            QMessageBox.warning(self, "Saisie invalide", str(erreur))
            return
        if not pieces:
            QMessageBox.information(self, "Aucune pièce",
                                    "Il n'y a rien à exporter.")
            return
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Exporter les pièces", self._dossier(), "CSV (*.csv)")
        if not chemin:
            return
        if not chemin.lower().endswith(".csv"):
            chemin += ".csv"
        try:
            csv_io.ecrire_pieces(chemin, pieces)
        except OSError as erreur:
            QMessageBox.warning(self, "Export impossible", str(erreur))
            return
        self._retenir_dossier(chemin)
        self.statusBar().showMessage(
            "%d pièce(s) exportée(s) : %s" % (len(pieces), chemin), 8000)

    # -- exemples ----------------------------------------------------------------

    def _remplir(self, pieces, stock, parametres):
        # On RESTAURE l'état de chargement, on ne le remet pas à faux :
        # l'accueil charge l'exemple sous chargement, puis applique les
        # réglages mémorisés — qui, le drapeau tombé trop tôt, marquaient
        # la fenêtre modifiée avant toute frappe. Une fenêtre neuve
        # s'ouvrait « ● Projet non enregistré », et tout geste qui demande
        # confirmation d'abandon (un exemple, un import) posait sa boîte
        # de dialogue là où rien n'avait changé.
        precedent = self._chargement
        self._chargement = True
        self.table_stock.remplir(stock)
        self.table_pieces.remplir(pieces)
        self._appliquer_parametres(parametres)
        self._chargement = precedent
        self._rafraichir_etat()

    def _charger_exemple(self):
        if not self._chargement and not self._confirmer_abandon(
                "L'exemple va remplacer les pièces et le stock."):
            return
        self._remplir(
            [opt.Piece("montant", 1750, 60, 18, "sapin", quantite=4),
             opt.Piece("traverse", 560, 60, 18, "sapin", quantite=6),
             opt.Piece("tablette", 560, 180, 18, "sapin", quantite=3),
             opt.Piece("taquet", 120, 40, 18, "sapin", quantite=8,
                       fil=opt.FIL_INDIFFERENT)],
            [opt.Planche("sapin 2400×200", 2400, 200, 18, "sapin", quantite=4),
             opt.Planche("chute étagère", 800, 180, 18, "sapin", chute=True,
                         defauts=((740, 0, 60, 180),)),
             opt.Planche("chute courte", 400, 120, 18, "sapin", chute=True,
                         recoupe_bouts=15)]
            + self._atelier_frais(),
            opt.Parametres())
        if not self._chargement:
            self._calculer()

    def _charger_exemple_volets(self):
        """Débit réel d'une paire de volets battants (projet Christophe,
        29/08/2026) : cotes de débit en douglas 27 mm (finies + surcotes
        de corroyage) sorties du modèle FreeCAD AtelierVolets. Le
        couvre-joint (15 mm) vient d'une autre section, il n'est pas ici.
        """
        if not self._confirmer_abandon(
                "L'exemple va remplacer les pièces et le stock."):
            return
        # 4 mm : le TRAIT_DE_SCIE du projet volets. 5 mm de tolérance
        # d'épaisseur : les planches sont du brut (30) à raboter à la cote
        # finie (27) — sans cet écart, le stock et les pièces ne se rangent
        # pas dans le même lot (par matière + épaisseur À LA TOLÉRANCE PRÈS).
        self._remplir(
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
                         quantite=2)]
            + self._atelier_frais(),
            opt.Parametres(trait_de_scie=4.0, tolerance_epaisseur=5.0))
        self._calculer()

    def _charger_exemple_formes(self):
        """L'imbrication CNC en un clic : huit formes concaves ou évidées
        (exemples.formes_biscornues) sur du contreplaqué sans fil."""
        if not self._confirmer_abandon(
                "L'exemple va remplacer les pièces et le stock."):
            return
        pieces, stock, parametres = exemples.formes_biscornues()
        self._remplir(pieces, stock + self._atelier_frais(), parametres)
        self._calculer()

    def _aide(self):
        QMessageBox.information(self, "Chutier — repères", """\
<b>Le geste</b><br>
① les pièces à débiter, ② le stock où les tailler, ③ les réglages de
scie, puis <b>F5</b>. Le plan se lit à droite, toutes planches empilées.

<p><b>Saisie</b><br>
<b>Ctrl+V</b> colle un bloc venu d'un tableur à partir de la cellule
courante — colonnes séparées par une tabulation ou un point-virgule.<br>
<b>Ctrl+C</b> recopie la sélection dans l'autre sens.<br>
<b>Ctrl+D</b> duplique les lignes choisies (cinq lames identiques).<br>
<b>Suppr</b> vide les cellules, <b>Ctrl+Suppr</b> ôte les lignes.</p>

<p><b>Plan</b><br>
<b>Ctrl+molette</b> zoome sous la souris, glisser déplace, double-clic
réajuste. <b>Ctrl+M</b> masque la saisie et laisse tout l'écran au plan.
<b>Ctrl+E</b> exporte en PNG ce qui est affiché, <b>Ctrl+P</b> l'imprime
(paginé si les planches sont nombreuses).</p>

<p><b>Corriger le plan</b><br>
Clic droit sur une planche : <i>l'épingler</i> — elle est reprise telle
quelle au prochain calcul, le reste se range autour. Clic droit sur une
pièce : <i>la tailler dans…</i> une autre ligne de stock (la colonne
<i>Planche</i> des pièces dit la même chose). Aucun des deux ne triche
sur les quantités.</p>

<p><b>La CNC</b><br>
Fichier → <i>importer des contours</i> ajoute aux pièces chaque tracé
fermé d'un SVG (Inkscape, FreeCAD…). Dès qu'une matière compte un
contour, tout ce lot est <i>imbriqué</i> à la fraise au lieu d'être
scié : écart entre contours et marge au bord dans les réglages.
Fichier → <i>exporter la découpe</i> sort chaque planche en SVG, en DXF
ou en projet LightBurn, à l'échelle 1, pour la chaîne CNC.</p>

<p><b>Sortir le débit</b><br>
Fichier → <i>fiche d'atelier</i> écrit en texte la liste des poses et des
coupes numérotées, planche par planche — celle qu'on coche à la scie.
Fichier → <i>imprimer les étiquettes</i> sort une étiquette par pièce
(24 par page A4, 70 × 37 mm) à coller sur le bois. Fichier →
<i>exporter les pièces</i> ressort la feuille de débit au format CSV,
pour un tableur ou un autre projet. Avec <i>Traits de scie</i> coché,
chaque trait porte son numéro d'ordre sur le plan.</p>

<p><b>L'atelier</b><br>
Les lignes de stock cochées <i>Atelier</i> vivent dans un fichier commun
(<tt>%s</tt>), pas dans le projet : on les retrouve à chaque projet
neuf ou rouvert. « Ranger ces chutes au stock » y écrit aussitôt ; le
reste s'y écrit à l'enregistrement et à la fermeture.</p>

<p><b>Réglages</b><br>
Trait de scie, surcotes et seuils de chute sont retenus d'une séance à
l'autre : ils reviennent pour tout projet neuf. Un projet enregistré
garde les siens et les réimpose à l'ouverture.</p>

<p><b>Conventions</b><br>
Tout est en millimètres. La longueur court le long du fil. Une planche
plus épaisse que la pièce convient (le brut se rabote) ; une plus mince,
jamais. Les chutes passent avant les planches neuves.</p>"""
                                % self._chemin_atelier)

    # -- fenêtre ------------------------------------------------------------------

    def _restaurer_geometrie(self):
        geometrie = self._reglages.value("geometrie")
        if geometrie:
            self.restoreGeometry(geometrie)
        etat = self._reglages.value("splitter")
        if etat:
            self._splitter.restoreState(etat)
        etat = self._reglages.value("saisie")
        if etat:
            self.saisie.restoreState(etat)

    def closeEvent(self, evenement):
        if not self._confirmer_abandon():
            evenement.ignore()
            return
        # « Abandonner » abandonne le PROJET ; l'atelier, lui, est un
        # inventaire et s'écrit toujours (s'il se lit).
        self._enregistrer_atelier()
        self._reglages.setValue("geometrie", self.saveGeometry())
        self._reglages.setValue("splitter", self._splitter.saveState())
        self._reglages.setValue("saisie", self.saisie.saveState())
        self._reglages.setValue("reglages_ouverts", self.reglages.est_ouvert())
        self._memoriser_reglages()
        super().closeEvent(evenement)


def main():
    app = QApplication(sys.argv)
    # Relie l'appli à chutier.desktop — le WM_CLASS par défaut (basé sur
    # l'exécutable, « python3 » puisqu'on lance via python3 interface.py)
    # ne correspond à rien, et la barre des tâches retombe sur une icône
    # générique même quand le lanceur en porte une bonne. setWindowIcon
    # reste la deuxième ligne de défense, indépendante du lanceur.
    app.setDesktopFileName("chutier")
    if os.path.isfile(ICONE):
        app.setWindowIcon(QIcon(ICONE))
    fenetre = FenetrePrincipale()
    if os.path.isfile(ICONE):
        fenetre.setWindowIcon(QIcon(ICONE))
    fenetre.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
