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

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPageLayout, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

import apparence
import csv_io
import optimiseur as opt
import projet_io
import tables_saisie as tsa
import vue_plan
from tables_saisie import ErreurSaisie

TITRE = "Chutier — feuille de débit"
# Chemin absolu : le lanceur .desktop fixe le dossier courant, mais rien
# d'autre ne le garantit (double-clic depuis un autre dossier, etc.).
ICONE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "resources", "icone.svg")

PLAN, ACHATS, CHUTES, NON_PLACEES = range(4)


def chutes_groupees(resultat) -> dict:
    """Les chutes créées rassemblées par cotes identiques, la plus grande
    d'abord. Deux chutes de 505 × 41 sont un lot de deux, pas deux lignes."""
    groupes = {}
    for c in resultat.chutes_creees:
        cle = (round(c.dim_x, 1), round(c.dim_y, 1), round(c.epaisseur, 1),
               c.matiere, c.fil)
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
    planches entamées en moins, les chutes créées en plus.

    C'est la seule opération du chutier qui réécrive une saisie de
    l'utilisateur — elle est donc écrite ici, séparée de la boîte de
    dialogue qui la propose, pour être vérifiable par un test.
    """
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

    # Une chute rangée va à l'ATELIER, pas au projet : c'est là qu'on la
    # retrouvera au débit suivant.
    for (dim_x, dim_y, epaisseur, matiere, fil), nombre in \
            chutes_groupees(resultat).items():
        modele = opt.ChuteCreee(dim_x, dim_y, 0, 0, epaisseur, matiere, fil)
        reference = "Chute %s %s×%s" % (matiere, opt._mm(dim_x), opt._mm(dim_y))
        nouveau.append(dataclasses.replace(modele.en_planche(reference),
                                           quantite=nombre, atelier=True))
    return nouveau


class FenetrePrincipale(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITRE)
        self.resize(1500, 900)
        self._resultat = None
        self._chemin = None
        self._modifie = False
        self._a_jour = False
        self._chargement = True
        self._reglages = QSettings("AtelierDuVerdier", "Chutier")
        self._chemin_atelier = projet_io.chemin_atelier()

        self._construire()
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
        central.addWidget(self._onglets_saisie())
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
        fichier.addAction(self.a_atelier)
        fichier.addSeparator()
        fichier.addAction(self.a_exporter)
        fichier.addAction(self.a_fiche)
        fichier.addAction(self.a_imprimer)
        fichier.addSeparator()
        fichier.addAction(self.a_quitter)

        edition = menu.addMenu("&Édition")
        for action in (self.a_ligne, self.a_dupliquer, self.a_supprimer):
            edition.addAction(action)
        edition.addSeparator()
        edition.addAction(self.a_matiere)

        debit = menu.addMenu("&Débit")
        debit.addAction(self.a_calculer)
        debit.addSeparator()
        debit.addAction(self.a_saisie)

        exemples = menu.addMenu("E&xemples")
        exemples.addAction(self.a_exemple)
        exemples.addAction(self.a_volets)

        menu.addMenu("&Aide").addAction(self.a_aide)

        barre = self.addToolBar("Principale")
        barre.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        barre.setMovable(False)
        for action in (self.a_ouvrir, self.a_enregistrer):
            barre.addAction(action)
        barre.addSeparator()
        barre.addAction(self.a_importer)
        barre.addSeparator()
        barre.addAction(self.a_calculer)
        barre.addAction(self.a_exporter)
        barre.addAction(self.a_imprimer)
        barre.addSeparator()
        barre.addAction(self.a_saisie)

    # -- saisie ------------------------------------------------------------

    def _onglets_saisie(self) -> QWidget:
        self.table_stock = tsa.TableStock()
        self.table_pieces = tsa.TablePieces(self.table_stock.matieres)

        self.onglets_saisie = QTabWidget()
        self.onglets_saisie.setDocumentMode(True)
        self.onglets_saisie.addTab(self._page_pieces(), "Pièces")
        self.onglets_saisie.addTab(self._page_stock(), "Stock")
        self.onglets_saisie.addTab(self._page_reglages(), "Réglages")
        self.onglets_saisie.setTabToolTip(
            0, "Ce qu'il faut débiter : une ligne par référence")
        self.onglets_saisie.setTabToolTip(
            1, "Ce qu'on a sous la main : planches, chutes, profils à acheter")
        self.onglets_saisie.setTabToolTip(
            2, "Comment on scie : trait de scie, surcotes, seuils de chute")

        for table in (self.table_pieces, self.table_stock):
            table.itemChanged.connect(self._saisie_changee)
            table.model().rowsInserted.connect(self._saisie_changee)
            table.model().rowsRemoved.connect(self._saisie_changee)
        return self.onglets_saisie

    def _page_table(self, table, resume, actions) -> QWidget:
        page = QWidget()
        colonne = QVBoxLayout(page)
        colonne.setContentsMargins(6, 6, 6, 6)
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
        return self._page_table(
            self.table_pieces, self.resume_pieces,
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
        return self._page_table(
            self.table_stock, self.resume_stock,
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
        colonne.addWidget(self._groupe_reglage("Le calcul", [
            ("Essais de mélange", self.spin_essais,
             "Ordres de pièces tirés au hasard en plus des stratégies"
             " réglées. Plus d'essais range parfois mieux, et calcule plus"
             " longtemps. Le hasard est à graine fixe : mêmes entrées,"
             " même plan."),
        ]))
        colonne.addStretch()

        cadre = QScrollArea()
        cadre.setWidgetResizable(True)
        cadre.setWidget(page)
        cadre.setFrameShape(QScrollArea.Shape.NoFrame)
        return cadre

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
            " ajuster — clic sur une planche : la sélectionner."))
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
        self._a_jour = False
        self.bilan.vider()
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
        self.onglets_saisie.setTabText(
            0, "Pièces  ·  %d" % len(self.table_pieces.lignes_utiles()))
        self.onglets_saisie.setTabText(
            1, "Stock  ·  %d" % len(self.table_stock.lignes_utiles()))

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
        return (self.table_pieces if self.onglets_saisie.currentIndex() == 0
                else self.table_stock if self.onglets_saisie.currentIndex() == 1
                else None)

    def _ajouter_ligne(self):
        table = self._table_courante()
        if table is None:
            self.onglets_saisie.setCurrentIndex(0)
            table = self.table_pieces
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
            essais_melanges=self.spin_essais.value())

    def _appliquer_parametres(self, p: opt.Parametres):
        for spin, valeur in ((self.spin_trait, p.trait_de_scie),
                             (self.spin_chute_longueur, p.chute_mini_longueur),
                             (self.spin_chute_largeur, p.chute_mini_largeur),
                             (self.spin_surcote_longueur, p.surcote_longueur),
                             (self.spin_surcote_largeur, p.surcote_largeur),
                             (self.spin_tolerance, p.tolerance_epaisseur),
                             (self.spin_surcote_joint, p.surcote_joint),
                             (self.spin_essais, p.essais_melanges)):
            spin.setValue(valeur)

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
            resultat = opt.optimiser(pieces, stock, self._parametres_actuels())
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
                                "sciure et rebuts")
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
        self.onglets_saisie.setCurrentIndex(1)
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
                                  self._parametres_actuels())
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
        self.onglets_saisie.setCurrentIndex(0)
        self._saisie_changee()

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

    def composer_document(self, peintre: QPainter, imprimante) -> int:
        """Peint toutes les pages et rend leur nombre. Séparé du choix de
        l'imprimante pour être éprouvé sur un PDF, sans matériel."""
        pages = self._pages_a_imprimer()
        largeur = max(1, int(peintre.device().width() * 0.98))
        for numero, planches in enumerate(pages, 1):
            if numero > 1:
                imprimante.newPage()
            self._dessiner_page(peintre,
                                self._image_du_plan(planches, largeur),
                                numero, len(pages), planches)
        return len(pages)

    def _image_du_plan(self, planches: list, largeur_px: int):
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
        vue.afficher(planches, self.case_traits.isChecked(),
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
        """Sous le plan, les cotes de débit planche par planche.

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
            texte = "%d.  %s" % (numero, "   ·   ".join(morceaux))
            boite = QRectF(zone.left(), y, zone.width(),
                           zone.bottom() - y)
            if boite.height() < ligne:
                break
            hauteur = peintre.boundingRect(
                boite, int(Qt.TextFlag.TextWordWrap), texte).height()
            peintre.drawText(boite, int(Qt.TextFlag.TextWordWrap), texte)
            y += hauteur + ligne * 0.35

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
             opt.Planche("chute étagère", 800, 180, 18, "sapin", chute=True),
             opt.Planche("chute courte", 400, 120, 18, "sapin", chute=True)]
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

<p><b>Sortir le débit</b><br>
Fichier → <i>fiche d'atelier</i> écrit en texte la liste des poses et des
coupes, planche par planche — celle qu'on coche à la scie. Fichier →
<i>exporter les pièces</i> ressort la feuille de débit au format CSV,
pour un tableur ou un autre projet.</p>

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

    def closeEvent(self, evenement):
        if not self._confirmer_abandon():
            evenement.ignore()
            return
        # « Abandonner » abandonne le PROJET ; l'atelier, lui, est un
        # inventaire et s'écrit toujours (s'il se lit).
        self._enregistrer_atelier()
        self._reglages.setValue("geometrie", self.saveGeometry())
        self._reglages.setValue("splitter", self._splitter.saveState())
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
