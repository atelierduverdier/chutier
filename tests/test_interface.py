# -*- coding: utf-8 -*-
"""Tests de l'interface Qt — sans écran.

Lancement : python3 tests/test_interface.py

Ce que ces tests gardent, ce sont les promesses que l'œil ne peut pas
vérifier tout seul : qu'une table rende exactement les pièces qu'on lui a
données, qu'une couleur ne change pas d'un lancement à l'autre, que
« ranger les chutes au stock » ne perde ni n'invente de bois. Le reste —
est-ce que le plan se LIT — se juge sur capture, pas ici.

Les réglages Qt (géométrie de fenêtre, dernier dossier) sont détournés
vers un dossier jetable : un test ne touche jamais la configuration de
l'utilisateur.
"""

import contextlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPageLayout, QPainter  # noqa: E402
from PySide6.QtPrintSupport import QPrinter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_JETABLE = tempfile.mkdtemp(prefix="chutier-tests-")
# Le stock commun de l'atelier est détourné lui aussi : un test ne touche
# JAMAIS l'inventaire réel — et un fichier absent, c'est l'accueil sur
# l'exemple, celui que les tests connaissent.
_ATELIER = os.path.join(_JETABLE, "atelier", "atelier.json")
os.environ["CHUTIER_ATELIER"] = _ATELIER
# Les réglages Qt aussi — par la variable d'environnement, PAS par
# QSettings.setPath : sur Linux, celui-ci ne détournait rien, et la suite
# écrivait depuis le début dans ~/.config/AtelierDuVerdier/Chutier.conf
# (le dernier dossier ouvert y pointait sur /tmp/chutier-tests-…, et la
# géométrie de la fenêtre y était celle d'un test). Vu le 03/09/2026.
os.environ["CHUTIER_SANS_RESEAU"] = "1"
os.environ["XDG_CONFIG_HOME"] = _JETABLE

APP = QApplication.instance() or QApplication([])

import apparence  # noqa: E402
import interface  # noqa: E402
interface.SYNCHRONE = True      # pas de fil ni de boîte de progression ici
import csv_io  # noqa: E402
import optimiseur as opt  # noqa: E402
import projet_io  # noqa: E402
import tables_saisie as tsa  # noqa: E402

PIECES = [
    opt.Piece("montant", 1750, 60, 18, "sapin", 4),
    opt.Piece("traverse", 560, 60, 18, "sapin", 6),
    opt.Piece("tablette", 560, 180, 18, "sapin", 3),
    opt.Piece("taquet", 120, 40, 18, "sapin", 8, opt.FIL_INDIFFERENT),
]
STOCK = [
    opt.Planche("sapin 2400x200", 2400, 200, 18, "sapin", quantite=4),
    opt.Planche("chute etagere", 800, 180, 18, "sapin", chute=True),
]


@contextlib.contextmanager
def _dialogue_repond(chemin):
    """Fait répondre ``chemin`` au sélecteur de fichiers, le temps d'un
    test : les exports passent tous par lui, et c'est justement le chemin
    complet qu'on veut éprouver."""
    ancien = interface.QFileDialog.getSaveFileName
    interface.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: (chemin, ""))
    try:
        yield
    finally:
        interface.QFileDialog.getSaveFileName = ancien


def _fenetre():
    f = interface.FenetrePrincipale()
    # Le calcul d'accueil est différé (QTimer.singleShot) : on le laisse
    # tirer TOUT DE SUITE, sinon il tire au milieu d'un autre test, sur une
    # saisie que ce test a pu rendre invalide — et ouvre une boîte modale
    # que personne ne fermera hors écran.
    APP.processEvents()
    f._calculer_si_pieces()     # un atelier garni ouvre sans pièces
    return f


class Couleurs(unittest.TestCase):

    def test_une_teinte_par_reference_toutes_differentes(self):
        references = [p.reference for p in PIECES] + ["Lame 1 G", "Lame 1 D"]
        palette = apparence.palette_pieces(references)
        teintes = [c.hue() for c in palette.values()]
        self.assertEqual(len(set(teintes)), len(teintes),
                         "deux références partagent une teinte")

    def test_la_couleur_ne_bouge_pas_d_un_lancement_a_l_autre(self):
        """hash() d'une chaîne est salé au démarrage de Python : la
        première version changeait de couleurs à chaque ouverture, en
        annonçant le contraire. Deux processus séparés doivent répondre
        la même chose."""
        code = ("import sys; sys.path.insert(0, %r);"
                " import apparence;"
                " print(apparence.couleur_piece('montant').name())" % RACINE)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        vues = {subprocess.run([sys.executable, "-c", code], env=env,
                               capture_output=True, text=True).stdout.strip()
                for _ in range(3)}
        self.assertEqual(len(vues), 1, "la couleur change d'un lancement à"
                                       " l'autre : %s" % vues)

    def test_plus_de_references_que_de_cases(self):
        """Au-delà du nombre de teintes disponibles, on ne doit ni planter
        ni boucler : les couleurs se répètent, c'est tout."""
        palette = apparence.palette_pieces(["p%d" % i for i in range(200)])
        self.assertEqual(len(palette), 200)


class Tables(unittest.TestCase):

    def setUp(self):
        self.stock = tsa.TableStock()
        self.pieces = tsa.TablePieces(self.stock.matieres)

    def test_aller_retour_pieces(self):
        self.pieces.remplir(PIECES)
        self.assertEqual(self.pieces.pieces(), PIECES)

    def test_aller_retour_stock(self):
        self.stock.remplir(STOCK)
        self.assertEqual(self.stock.stock(), STOCK)

    def test_ligne_sans_reference_ignoree(self):
        self.pieces.remplir(PIECES)
        self.pieces.ajouter_ligne()
        self.assertEqual(len(self.pieces.pieces()), len(PIECES))

    def test_nombre_illisible_signale_la_reference(self):
        self.pieces.remplir(PIECES)
        self.pieces.item(1, 1).setText("douze")
        with self.assertRaises(tsa.ErreurSaisie) as leve:
            self.pieces.pieces()
        self.assertIn("traverse", str(leve.exception))

    def test_collage_d_un_bloc_de_tableur(self):
        self.pieces.ajouter_ligne()
        self.pieces.setCurrentCell(0, 0)
        self.pieces.coller("chevron\t2000\t80\t45\tchene\t3\n"
                           "cale\t150\t80\t45\tchene\t12")
        obtenues = self.pieces.pieces()
        self.assertEqual([p.reference for p in obtenues], ["chevron", "cale"])
        self.assertEqual(obtenues[0].longueur, 2000)
        self.assertEqual(obtenues[1].quantite, 12)
        # le fil et le composable gardent leur défaut, non collés
        self.assertEqual(obtenues[0].fil, opt.FIL_LONGUEUR)
        self.assertFalse(obtenues[0].composable)

    def test_collage_au_point_virgule(self):
        self.pieces.ajouter_ligne()
        self.pieces.setCurrentCell(0, 0)
        self.pieces.coller("panneau;600;400;18;mdf;2")
        self.assertEqual(self.pieces.pieces()[0].largeur, 400)

    def test_duplication(self):
        self.pieces.remplir(PIECES)
        self.pieces.selectRow(0)
        self.pieces.dupliquer_selection()
        obtenues = self.pieces.pieces()
        self.assertEqual(len(obtenues), len(PIECES) + 1)
        self.assertEqual(obtenues[1], obtenues[0])

    def test_duplication_garde_les_cases_et_les_choix(self):
        self.pieces.remplir([PIECES[3]])   # fil indifférent
        self.pieces.selectRow(0)
        self.pieces.dupliquer_selection()
        self.assertEqual(self.pieces.pieces()[1].fil, opt.FIL_INDIFFERENT)

    def test_un_clic_bascule_la_case_a_cocher(self):
        """Les cases sont dessinées par un délégué, plus par un QCheckBox
        posé dans la cellule : c'est ce délégué qui doit recevoir le clic
        et basculer la valeur, au centre de la cellule."""
        self.pieces.remplir(PIECES)
        self.assertFalse(self.pieces.pieces()[0].composable)
        colonne = 7                                   # Composable
        boite = self.pieces.visualItemRect(self.pieces.item(0, colonne))
        QTest.mouseClick(self.pieces.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, boite.center())
        self.assertTrue(self.pieces.pieces()[0].composable)
        QTest.mouseClick(self.pieces.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, boite.center())
        self.assertFalse(self.pieces.pieces()[0].composable)

    def test_un_clic_ailleurs_ne_bascule_rien(self):
        self.stock.remplir(STOCK)
        boite = self.stock.visualItemRect(self.stock.item(0, 0))
        QTest.mouseClick(self.stock.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, boite.center())
        self.assertEqual(self.stock.stock(), STOCK)

    def test_les_cases_survivent_a_l_enregistrement(self):
        avec = [opt.Piece("panneau", 900, 600, 18, "mdf", 1,
                          opt.FIL_INDIFFERENT, composable=True)]
        self.pieces.remplir(avec)
        self.assertEqual(self.pieces.pieces(), avec)

    def test_la_colonne_defauts_fait_l_aller_retour(self):
        stock = [opt.Planche("abimee", 2400, 200, 18, "sapin",
                             recoupe_bouts=30, recoupe_rives=5.5,
                             defauts=((1200, 0, 80, 200), (600, 140, 60, 40)))]
        self.stock.remplir(stock)
        self.assertEqual(self.stock.texte(0, 11),
                         "bouts 30 ; rives 5.5 ; 1200-1280 ; 600,140,60,40")
        self.assertEqual(self.stock.stock(), stock)

    def test_la_syntaxe_des_defauts(self):
        lu = tsa.lire_defauts("Bout 20; R 4 ; 100 à 150 ; 10 20 30 40", "", 90)
        self.assertEqual(lu, {"recoupe_bouts": 20.0, "recoupe_rives": 4.0,
                              "defauts": ((100.0, 0.0, 50.0, 90.0),
                                          (10.0, 20.0, 30.0, 40.0))})
        self.assertEqual(tsa.lire_defauts("", "", 90),
                         {"recoupe_bouts": 0.0, "recoupe_rives": 0.0,
                          "defauts": ()})
        with self.assertRaises(tsa.ErreurSaisie) as leve:
            tsa.lire_defauts("noeud à 300", "« p »", 90)
        self.assertIn("noeud à 300", str(leve.exception))

    def test_un_defaut_illisible_se_signale_a_la_frappe(self):
        self.stock.remplir(STOCK)
        self.stock.item(0, 11).setText("n'importe quoi")
        self.assertNotEqual(self.stock.item(0, 11).background().color().alpha(),
                            0)
        with self.assertRaises(tsa.ErreurSaisie):
            self.stock.stock()

    def test_les_matieres_du_stock_alimentent_les_pieces(self):
        self.stock.remplir(STOCK)
        self.assertEqual(self.stock.matieres(), ["sapin"])


class RangerLesChutes(unittest.TestCase):
    """« Ranger au stock » est la seule opération qui réécrive une saisie
    de l'utilisateur : elle doit être juste au morceau près."""

    def setUp(self):
        self.resultat = opt.optimiser(PIECES, STOCK)

    def test_les_planches_entamees_sortent_du_stock(self):
        apres = interface.stock_apres_debit(STOCK, self.resultat)
        consommees = interface.planches_consommees(self.resultat)
        for planche in STOCK:
            reste = sum(p.quantite for p in apres
                        if p.reference == planche.reference)
            self.assertEqual(reste,
                             planche.quantite - consommees.get(planche, 0),
                             "mauvais décompte pour « %s »" % planche.reference)

    def test_les_chutes_creees_entrent_au_stock(self):
        apres = interface.stock_apres_debit(STOCK, self.resultat)
        anciennes = {p.reference for p in STOCK}
        neuves = sum(p.quantite for p in apres if p.reference not in anciennes)
        self.assertEqual(neuves, len(self.resultat.chutes_creees))
        for planche in apres:
            if planche.reference not in anciennes:
                self.assertTrue(planche.chute,
                                "une chute rangée doit rester une chute")

    def test_deux_lignes_de_stock_du_meme_nom_ne_se_confondent_pas(self):
        """Rien n'interdit deux chutes appelées pareil à des cotes
        différentes. Décompter sur le seul nom retirait les exemplaires
        de la mauvaise ligne."""
        stock = [opt.Planche("chute", 2400, 200, 18, "sapin", quantite=2,
                             chute=True),
                 opt.Planche("chute", 300, 80, 18, "sapin", quantite=2,
                             chute=True)]
        resultat = opt.optimiser(
            [opt.Piece("montant", 1750, 60, 18, "sapin", 2)], stock,
            opt.Parametres(essais_melanges=0))
        apres = interface.stock_apres_debit(stock, resultat)
        petite = [p for p in apres if p.longueur == 300]
        self.assertEqual([p.quantite for p in petite], [2],
                         "la petite chute n'a pas servi, elle doit rester"
                         " entière")

    def test_un_profil_de_catalogue_ne_se_deduit_pas(self):
        catalogue = [opt.Planche("douglas 4 m", 4000, 200, 30, "sapin",
                                 quantite=1, illimite=True)]
        resultat = opt.optimiser(PIECES, catalogue)
        apres = interface.stock_apres_debit(catalogue, resultat)
        garde = [p for p in apres if p.reference == "douglas 4 m"]
        self.assertEqual([p.quantite for p in garde], [1],
                         "un profil de catalogue s'achète, il ne s'épuise pas")

    def test_rien_ne_se_perd_en_surface(self):
        """La surface sortie du stock = pièces + chutes rangées + pertes."""
        apres = interface.stock_apres_debit(STOCK, self.resultat)
        anciennes = {p.reference for p in STOCK}
        surface_neuves = sum(p.aire * p.quantite for p in apres
                             if p.reference not in anciennes)
        self.assertAlmostEqual(surface_neuves,
                               self.resultat.bilan.surface_chutes_creees,
                               places=3)


class ReglagesJetables(unittest.TestCase):

    def test_les_reglages_qt_sont_detournes(self):
        """Un test ne touche jamais la configuration de l'utilisateur.
        QSettings.setPath(IniFormat, …) le promettait et ne le faisait
        pas ; seule la variable d'environnement tient parole."""
        f = interface.FenetrePrincipale()
        self.assertTrue(f._reglages.fileName().startswith(_JETABLE),
                        f._reglages.fileName())


class Atelier(unittest.TestCase):
    """Le stock commun : ce qui fait qu'une chute rangée ce soir est là
    au projet suivant, sans la recopier."""

    def setUp(self):
        if os.path.exists(_ATELIER):
            os.unlink(_ATELIER)

    tearDown = setUp

    def test_le_chemin_suit_la_variable_d_environnement(self):
        self.assertEqual(projet_io.chemin_atelier(), _ATELIER)

    def test_ranger_les_chutes_ecrit_l_atelier_aussitot(self):
        f = _fenetre()
        with mock.patch.object(
                interface.QMessageBox, "question",
                return_value=interface.QMessageBox.StandardButton.Yes):
            f._ranger_chutes()
        self.assertTrue(os.path.exists(_ATELIER), "rien n'a été écrit")
        rangees = projet_io.lire_atelier(_ATELIER)
        self.assertEqual(sum(p.quantite for p in rangees),
                         len(f._resultat.chutes_creees))
        self.assertTrue(all(p.atelier and p.chute for p in rangees))

    def test_enregistrer_scinde_projet_et_atelier(self):
        f = _fenetre()
        f.table_stock.ajouter_ligne(reference="rayon chêne", longueur=2000,
                                    largeur=150, epaisseur=27,
                                    matiere="chêne", atelier=True)
        f._chemin = os.path.join(_JETABLE, "scinde.json")
        f._enregistrer()
        _, stock_projet, _ = projet_io.lire(f._chemin)
        self.assertFalse(any(s.atelier for s in stock_projet),
                         "une ligne d'atelier est restée dans le projet")
        self.assertEqual([s.reference for s in projet_io.lire_atelier(_ATELIER)],
                         ["rayon chêne"])

    def test_ouvrir_un_projet_reprend_l_atelier_du_jour(self):
        projet_io.enregistrer_atelier(_ATELIER, [
            opt.Planche("chute du jour", 600, 120, 18, "sapin", chute=True)])
        chemin = os.path.join(_JETABLE, "sans-atelier.json")
        projet_io.enregistrer(chemin, PIECES, STOCK, opt.Parametres())
        f = _fenetre()
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               return_value=(chemin, "")):
            f._ouvrir()
        stock = f.table_stock.stock()
        self.assertEqual([s.reference for s in stock if s.atelier],
                         ["chute du jour"])
        self.assertEqual([s.reference for s in stock if not s.atelier],
                         [s.reference for s in STOCK])

    def test_nouveau_repart_avec_l_atelier(self):
        projet_io.enregistrer_atelier(_ATELIER, [
            opt.Planche("rayon", 2000, 150, 27, "chêne")])
        f = _fenetre()
        f._modifie = False
        f._nouveau()
        self.assertEqual(f.table_pieces.pieces(), [])
        self.assertEqual([s.reference for s in f.table_stock.stock()],
                         ["rayon"])

    def test_un_atelier_garni_ouvre_sur_lui_sans_plainte(self):
        """Feuille de pièces blanche, stock de l'atelier, et aucune boîte
        « aucune pièce à débiter » à l'accueil."""
        projet_io.enregistrer_atelier(_ATELIER, [
            opt.Planche("rayon", 2000, 150, 27, "chêne")])
        with mock.patch.object(interface.QMessageBox, "warning") as boite:
            f = interface.FenetrePrincipale()
            f._calculer_si_pieces()
        boite.assert_not_called()
        self.assertEqual(f.table_pieces.pieces(), [])
        self.assertEqual([s.reference for s in f.table_stock.stock()],
                         ["rayon"])
        self.assertFalse(f._modifie)

    def test_la_fermeture_ecrit_l_atelier(self):
        f = _fenetre()
        f.table_stock.ajouter_ligne(reference="rayon", longueur=2000,
                                    largeur=150, epaisseur=27,
                                    matiere="chêne", atelier=True)
        f._modifie = False
        f.close()
        self.assertEqual([s.reference for s in projet_io.lire_atelier(_ATELIER)],
                         ["rayon"])


class ReglagesDesExemples(unittest.TestCase):

    def test_les_orientations_de_l_exemple_arrivent_dans_l_interface(self):
        """L'exemple des formes demande DEUX orientations pour rester
        rapide ; la liste n'offrait que 90, 45, 30 et 15, findData ne
        trouvait pas 180 et le réglage retombait silencieusement sur 90 —
        quatre orientations, 592 no-fit polygons au lieu de 168, et un
        plan différent de celui que l'exemple décrit."""
        import exemples
        f = _fenetre()
        f._charger_exemple_formes()
        APP.processEvents()
        attendu = exemples.formes_biscornues()[2]
        obtenu = f._parametres_actuels()
        self.assertEqual(obtenu.pas_rotation, attendu.pas_rotation)
        self.assertEqual(obtenu.marge_bord, attendu.marge_bord)
        self.assertEqual(obtenu.ecart_contours, attendu.ecart_contours)
        f._modifie = False
        f.close()

    def test_chaque_reglage_de_chaque_exemple_est_offert(self):
        """Un réglage qu'un exemple pose et que la liste n'a pas retombe
        en silence sur le premier venu."""
        import exemples
        f = _fenetre()
        for charger, nom in ((f._charger_exemple, "panneaux"),
                             (f._charger_exemple_formes, "formes")):
            charger()
            APP.processEvents()
            voulu = (exemples.formes_biscornues()[2] if nom == "formes"
                     else opt.Parametres())
            obtenu = f._parametres_actuels()
            for champ in ("pas_rotation", "priorite"):
                self.assertEqual(getattr(obtenu, champ),
                                 getattr(voulu, champ),
                                 "%s : %s perdu" % (nom, champ))
        f._modifie = False
        f.close()


class CorrectionsDAudit(unittest.TestCase):
    """Six défauts trouvés par un audit le 4 septembre 2026 — chacun se
    reproduisait à l'exécution, aucun ne se voyait à la lecture."""

    def setUp(self):
        # Hors écran, une boîte modale n'a personne pour la fermer : la
        # suite entière s'y fige. On les remplace par des espions.
        self._muettes = contextlib.ExitStack()
        self.boites = {}
        for nom in ("information", "warning", "critical"):
            self.boites[nom] = self._muettes.enter_context(mock.patch.object(
                interface.QMessageBox, nom,
                return_value=interface.QMessageBox.StandardButton.Ok))
        self.addCleanup(self._muettes.close)

    def _textes_dits(self):
        return [str(a) for espion in self.boites.values()
                for appel in espion.call_args_list for a in appel.args]

    def _atelier_intact(self):
        """Le fichier d'atelier est partagé par toute la suite : un test
        qui y ajoute une planche ouvre les fenêtres suivantes SANS pièces
        (l'accueil ne charge alors pas son exemple), et le premier calcul
        venu se plante sur une modale que personne ne ferme."""
        avant = (open(_ATELIER, encoding="utf-8").read()
                 if os.path.exists(_ATELIER) else None)

        def remettre():
            if avant is None:
                if os.path.exists(_ATELIER):
                    os.remove(_ATELIER)
            else:
                with open(_ATELIER, "w", encoding="utf-8") as f:
                    f.write(avant)
        self.addCleanup(remettre)

    def test_recharger_l_atelier_garde_ce_qui_vient_d_etre_tape(self):
        """« Recharger le stock de l'atelier » relisait le fichier sans
        y écrire d'abord : la ligne cochée Atelier qu'on venait de taper
        disparaissait de la table ET du fichier."""
        self._atelier_intact()
        f = _fenetre()
        f.table_stock.ajouter_ligne(reference="rayon chêne neuf", longueur=2000,
                                    largeur=150, epaisseur=27, matiere="chêne",
                                    atelier=True)
        f._recharger_atelier()
        APP.processEvents()
        references = [s.reference for s in f.table_stock.stock()]
        self.assertIn("rayon chêne neuf", references)
        self.assertIn("rayon chêne neuf",
                      [s.reference for s in projet_io.lire_atelier(_ATELIER)])
        f._modifie = False
        f.close()

    def test_un_document_neuf_ouvre_une_pile_d_annulation_neuve(self):
        """Ctrl+Z sur un projet fraîchement ouvert rejouait la saisie du
        PRÉCÉDENT — et Ctrl+S l'écrivait dans son fichier."""
        f = _fenetre()
        f._charger_exemple()
        APP.processEvents()
        self.assertTrue([p.reference for p in f.table_pieces.pieces()])
        chemin = os.path.join(tempfile.mkdtemp(), "projet-b.json")
        projet_io.enregistrer(
            chemin, [opt.Piece("plateau chêne", 900, 400, 27, "chêne")],
            [opt.Planche("chêne", 2000, 500, 27, "chêne")], opt.Parametres())
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               staticmethod(lambda *a, **k: (chemin, ""))):
            f._ouvrir()
        APP.processEvents()
        self.assertEqual([p.reference for p in f.table_pieces.pieces()],
                         ["plateau chêne"])
        f._annuler()
        APP.processEvents()
        self.assertEqual([p.reference for p in f.table_pieces.pieces()],
                         ["plateau chêne"], "l'annulation a rejoué l'ancien")
        self.assertIn("Rien à annuler", f.statusBar().currentMessage())
        f._modifie = False
        f.close()

    def test_annuler_rend_au_plan_ses_epingles(self):
        """Le liseré ÉPINGLÉE vient de vue.epinglees : sans mise à jour,
        « Relâcher la planche » restait proposé sur une planche qui ne
        l'était plus, et ne faisait rien."""
        f = _fenetre()
        f._calculer()
        APP.processEvents()
        f._epingler(1)
        APP.processEvents()
        self.assertEqual(f.vue.epinglees, {1})
        f._annuler()
        APP.processEvents()
        self.assertEqual(len(f._epingles), len(f.vue.epinglees))
        f._modifie = False
        f.close()

    def test_supprimer_un_contour_efface_aussi_la_forme(self):
        """Suppr effaçait « ◇ 6 pts » en laissant le polygone dans la
        donnée de la cellule : la table montrait un rectangle, la fraise
        découpait toujours la forme."""
        f = _fenetre()
        f._charger_exemple_formes()
        APP.processEvents()
        table = f.table_pieces
        colonne = table.COLONNE_CONTOUR
        self.assertTrue(table.item(0, colonne).data(tsa.ROLE_VALEUR))
        table.setCurrentCell(0, colonne)
        table.vider_cellules()
        self.assertEqual(table.item(0, colonne).text(), "")
        self.assertFalse(table.item(0, colonne).data(tsa.ROLE_VALEUR))
        self.assertFalse(table.pieces()[0].contour)
        f._modifie = False
        f.close()

    def test_les_cotes_d_une_chute_biscornue_ne_se_tapent_pas(self):
        """Elles viennent du polygone : la table acceptait 999 × 888 et
        le débit continuait de scier 400 × 300."""
        f = _fenetre()
        contour = ((0, 0), (400, 0), (400, 300), (0, 300))
        f.table_stock.ajouter_ligne(reference="biscornue", longueur=400,
                                    largeur=300, epaisseur=15,
                                    matiere="contreplaqué", chute=True,
                                    contour=contour, trous=())
        ligne = f.table_stock.rowCount() - 1
        for colonne in (1, 2):
            drapeaux = f.table_stock.item(ligne, colonne).flags()
            self.assertFalse(bool(drapeaux & Qt.ItemFlag.ItemIsEditable),
                             "la cote se tape encore")
        f._modifie = False
        f.close()

    def test_glisser_refuse_un_plan_perime_et_marque_le_projet(self):
        f = _fenetre()
        f._charger_exemple_formes()
        APP.processEvents()
        f._calculer()
        APP.processEvents()
        debit = f._resultat.debits[-1]
        f._a_jour = False
        f._deplacer_pose(len(f._resultat.debits), debit.poses[0], 1, 0)
        self.assertEqual(f._epingles, [], "déplacement accepté sur plan périmé")
        self.assertTrue(any("Recalculez" in d for d in self._textes_dits()))
        f._a_jour = True
        for indice, pose in enumerate(debit.poses):
            for dx, dy in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
                f._deplacer_pose(len(f._resultat.debits), pose, dx, dy)
                if f._epingles:
                    break
            if f._epingles:
                break
        self.assertTrue(f._epingles)
        self.assertTrue(f._modifie)
        self.assertIn("●", f.windowTitle())
        f._modifie = False
        f.close()


class Deplacement(unittest.TestCase):

    def test_une_piece_glissee_epingle_sa_planche(self):
        f = _fenetre()
        f._charger_exemple_formes()
        APP.processEvents()
        f._calculer()
        APP.processEvents()
        r = f._resultat
        self.assertTrue(r.debits)
        numero = len(r.debits)                     # la dernière, non épinglée
        debit = r.debits[numero - 1]
        pose = debit.poses[0]
        f._deplacer_pose(numero, pose, 10000, 0)     # refusé : hors planche
        self.assertEqual(f._epingles, [])
        self.assertIn("refusé", f.statusBar().currentMessage())
        # une pièce coincée entre ses voisines ne bouge pas d'un
        # millimètre : on cherche celle qui a de l'air, et son sens
        trouvee = None
        for indice, pose in enumerate(debit.poses):
            for dx, dy in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
                f._deplacer_pose(numero, pose, dx, dy)
                if f._epingles:
                    trouvee = (indice, pose, dx, dy)
                    break
            if trouvee:
                break
        self.assertIsNotNone(trouvee, "aucune pièce n'a pu bouger")
        indice, pose, dx, dy = trouvee
        self.assertEqual(len(f._epingles), 1)
        self.assertTrue(f._modifie)
        # la planche épinglée ouvre la liste, la pièce a bougé
        self.assertAlmostEqual(f._resultat.debits[0].poses[indice].x, pose.x + dx)
        self.assertAlmostEqual(f._resultat.debits[0].poses[indice].y, pose.y + dy)
        self.assertEqual(f.vue.epinglees, {1})
        # sans quoi la fermeture ouvre « Projet modifié », modale, que
        # personne ne fermera hors écran : la suite entière se fige
        f._modifie = False
        f.close()


class EpinglesEtPlancheImposee(unittest.TestCase):

    def test_epingler_garde_la_planche_au_recalcul(self):
        f = _fenetre()
        fixe = f._resultat.debits[1]
        f._epingler(2)
        self.assertEqual(f._epingles, [fixe])
        self.assertEqual(f.vue.epinglees, {1})
        repris = f._resultat.debits[0]
        self.assertEqual([(p.piece.reference, p.x, p.y) for p in repris.poses],
                         [(p.piece.reference, p.x, p.y) for p in fixe.poses])
        self.assertIn("ÉPINGLÉE", "".join(
            it.text() for it in f.vue.scene().items()
            if hasattr(it, "text")))
        f._desepingler(1)
        self.assertEqual(f._epingles, [])
        self.assertEqual(f.vue.epinglees, set())

    def test_une_epingle_perimee_se_relache_sans_bloquer(self):
        f = _fenetre()
        f._epingler(1)
        f.table_pieces.item(0, 1).setText("1700")      # le montant change
        with mock.patch.object(interface.QMessageBox, "warning") as boite:
            f._calculer()
        boite.assert_not_called()
        self.assertEqual(f._epingles, [])
        self.assertTrue(f._a_jour)

    def test_les_epingles_survivent_a_l_enregistrement(self):
        f = _fenetre()
        f._epingler(1)
        chemin = os.path.join(_JETABLE, "epingle.json")
        f._chemin = chemin
        f._enregistrer()
        g = _fenetre()
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               return_value=(chemin, "")):
            g._ouvrir()
        self.assertEqual(g._epingles, f._epingles)
        self.assertEqual(g.vue.epinglees, {1})

    def test_imposer_une_planche_depuis_le_plan(self):
        f = _fenetre()
        f._imposer_planche("tablette", "chute étagère")
        tablettes = [p for p in f.table_pieces.pieces()
                     if p.reference == "tablette"]
        self.assertEqual([p.planche for p in tablettes], ["chute étagère"])
        # une seule tablette y loge : les deux autres sont non placées,
        # avec la raison qui le dit
        self.assertEqual(f._resultat.bilan.nb_non_placees, 2)
        self.assertEqual(f._resultat.non_placees[0].raison,
                         opt.RAISON_PLANCHE_PLEINE)
        f._imposer_planche("tablette", "")
        self.assertEqual(f._resultat.bilan.nb_non_placees, 0)

    def test_les_trous_font_l_aller_retour_dans_la_table(self):
        stock = tsa.TableStock()
        pieces = tsa.TablePieces(stock.matieres, stock.references)
        cadre = opt.Piece("cadre", 100, 100, 15, "cp", 1, opt.FIL_INDIFFERENT,
                          contour=((0, 0), (100, 0), (100, 100), (0, 100)),
                          trous=(((20, 20), (80, 20), (80, 80), (20, 80)),))
        pieces.remplir([cadre])
        self.assertEqual(pieces.pieces(), [cadre])
        self.assertEqual(pieces.texte(0, 9), "◇ 4 pts · 1 trou")
        pieces.selectRow(0)
        pieces.dupliquer_selection()
        self.assertEqual(pieces.pieces()[1].trous, cadre.trous)

    def test_la_colonne_planche_fait_l_aller_retour(self):
        stock = tsa.TableStock()
        stock.remplir(STOCK)
        self.assertEqual(stock.references(),
                         ["sapin 2400x200", "chute etagere"])
        pieces = tsa.TablePieces(stock.matieres, stock.references)
        avec = [opt.Piece("t", 560, 180, 18, "sapin", planche="chute etagere")]
        pieces.remplir(avec)
        self.assertEqual(pieces.pieces(), avec)


SVG_FORMES = """<svg xmlns="http://www.w3.org/2000/svg" width="300mm"
 height="200mm" viewBox="0 0 300 200">
<path id="equerre" d="M 10 10 L 90 10 L 90 30 L 30 30 L 30 90 L 10 90 Z"/>
<circle id="rondelle" cx="200" cy="100" r="25"/></svg>"""


class Contours(unittest.TestCase):
    """Des formes quelconques, importées d'un SVG, imbriquées à la CNC."""

    def _svg(self):
        chemin = os.path.join(_JETABLE, "formes.svg")
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(SVG_FORMES)
        return chemin

    def test_l_import_ajoute_des_pieces_a_contour(self):
        f = _fenetre()
        avant = len(f.table_pieces.pieces())
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               return_value=(self._svg(), "")):
            f._importer_contours()
        pieces = f.table_pieces.pieces()
        self.assertEqual(len(pieces), avant + 2)
        equerre = [p for p in pieces if p.reference == "equerre"][0]
        self.assertEqual(len(equerre.contour), 6)
        self.assertEqual(equerre.matiere, "sapin")     # celle du stock
        self.assertEqual(equerre.fil, opt.FIL_INDIFFERENT)
        self.assertAlmostEqual(equerre.longueur, 80, places=3)
        self.assertEqual(f.table_pieces.texte(avant, 9), "◇ 6 pts")
        self.assertFalse(f.table_pieces.isColumnHidden(9))

    def test_le_lot_a_contour_s_imbrique_et_se_dessine(self):
        f = _fenetre()
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               return_value=(self._svg(), "")):
            f._importer_contours()
        f._calculer()
        self.assertTrue(any(d.imbriquee for d in f._resultat.debits))
        polygones = [it for it in f.vue.scene().items()
                     if isinstance(it, interface.vue_plan.QGraphicsPolygonItem)]
        self.assertGreaterEqual(len(polygones), 2)

    def test_le_contour_survit_au_projet_et_a_la_duplication(self):
        f = _fenetre()
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               return_value=(self._svg(), "")):
            f._importer_contours()
        f.table_pieces.selectRow(f.table_pieces.rowCount() - 1)
        f.table_pieces.dupliquer_selection()
        pieces = f.table_pieces.pieces()
        self.assertEqual(pieces[-1].contour, pieces[-2].contour)
        chemin = os.path.join(_JETABLE, "contours.json")
        f._chemin = chemin
        f._enregistrer()
        relues, _, _ = projet_io.lire(chemin)
        self.assertEqual(relues, pieces)

    def test_l_export_svg_ecrit_une_planche_par_fichier(self):
        f = _fenetre()
        with mock.patch.object(interface.QFileDialog, "getOpenFileName",
                               return_value=(self._svg(), "")):
            f._importer_contours()
        f._calculer()
        base = os.path.join(_JETABLE, "decoupe")
        with _dialogue_repond(base + ".svg"):
            f._exporter_svg()
        fichiers = sorted(n for n in os.listdir(_JETABLE)
                          if n.startswith("decoupe"))
        self.assertEqual(len(fichiers), len(f.vue.debits_affiches()))


class AnnulerRefaire(unittest.TestCase):

    def test_annuler_rend_la_saisie_d_avant(self):
        f = _fenetre()
        avant = f.table_pieces.pieces()
        f.table_pieces.item(0, 1).setText("1700")
        f._consigner()                         # ce que la minuterie ferait
        self.assertEqual(f.table_pieces.pieces()[0].longueur, 1700)
        f._annuler()
        self.assertEqual(f.table_pieces.pieces(), avant)
        f._refaire()
        self.assertEqual(f.table_pieces.pieces()[0].longueur, 1700)

    def test_annuler_restaure_meme_un_nombre_illisible(self):
        f = _fenetre()
        f.table_pieces.item(0, 1).setText("douze")
        f._consigner()
        f.table_pieces.item(0, 1).setText("1200")
        f._consigner()
        f._annuler()
        self.assertEqual(f.table_pieces.texte(0, 1), "douze")
        f.table_pieces.item(0, 1).setText("1750")      # ne rien laisser d'invalide

    def test_annuler_une_suppression_de_ligne(self):
        f = _fenetre()
        n = len(f.table_pieces.pieces())
        f.table_pieces.selectRow(0)
        f.table_pieces.supprimer_selection()
        f._consigner()
        self.assertEqual(len(f.table_pieces.pieces()), n - 1)
        f._annuler()
        self.assertEqual(len(f.table_pieces.pieces()), n)

    def test_rien_a_annuler_au_depart(self):
        f = _fenetre()
        f._annuler()                           # ne lève pas, ne change rien
        self.assertEqual(len(f.table_pieces.pieces()), 4)


class Interruption(unittest.TestCase):

    def test_un_calcul_interrompu_garde_le_plan_precedent(self):
        f = _fenetre()
        avant = f._resultat
        opt.ANNULATION.set()
        try:
            resultat, plainte, _ = interface._Calcul.calculer(
                f.table_pieces.pieces(), f.table_stock.stock(),
                opt.Parametres(), [])
        finally:
            opt.ANNULATION.clear()
        self.assertIsNone(resultat)
        self.assertEqual(plainte, "annulé")
        f._fin_de_calcul(resultat, plainte, None)
        self.assertIs(f._resultat, avant)


class ExempleFormes(unittest.TestCase):

    def test_l_exemple_des_formes_s_imbrique_entier(self):
        f = _fenetre()
        f._charger_exemple_formes()
        r = f._resultat
        self.assertEqual(r.bilan.nb_non_placees, 0)
        self.assertTrue(all(d.imbriquee for d in r.debits))
        self.assertTrue(any(p.trous for d in r.debits for p in d.poses))
        self.assertGreaterEqual(len([it for it in f.vue.scene().items()
                                     if isinstance(it, interface.vue_plan.QGraphicsPathItem)]), 3)


class Fenetre(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.f = _fenetre()

    def test_le_calcul_remplit_le_plan(self):
        self.assertIsNotNone(self.f._resultat)
        self.assertEqual(self.f.liste_planches.count(),
                         len(self.f._resultat.debits))
        self.assertGreater(len(self.f.vue.scene().items()), 10)

    def test_toutes_les_planches_sont_dessinees(self):
        self.f.choix_vue.setCurrentIndex(0)
        self.assertEqual(len(self.f.vue._zones),
                         len(self.f._resultat.debits))

    def test_une_seule_planche_en_mode_planche_seule(self):
        self.f.choix_vue.setCurrentIndex(1)
        self.assertEqual(len(self.f.vue._zones), 1)
        self.f.choix_vue.setCurrentIndex(0)

    def test_les_traits_de_scie_s_ajoutent_et_se_retirent(self):
        avant = len(self.f.vue.scene().items())
        self.f.case_traits.setChecked(True)
        self.assertGreater(len(self.f.vue.scene().items()), avant)
        self.f.case_traits.setChecked(False)

    def test_les_defauts_se_dessinent_et_se_legendent(self):
        self.f.choix_vue.setCurrentIndex(0)
        libelles = [self.f.legende.item(i).text()
                    for i in range(self.f.legende.count())]
        self.assertIn("défaut écarté", libelles)
        infos = [it.toolTip() for it in self.f.vue.scene().items()]
        self.assertTrue(any(i.startswith("Défaut écarté") for i in infos))
        # les recoupes se dessinent aux deux bouts et sur les deux rives
        zones = self.f.vue._zones_ecartees(
            opt.Planche("p", 1000, 100, 18, "b", recoupe_bouts=20,
                        recoupe_rives=5))
        self.assertEqual([z[:4] for z in zones],
                         [(0.0, 0.0, 20, 100), (980, 0.0, 20, 100),
                          (0.0, 0.0, 1000, 5), (0.0, 95, 1000, 5)])

    def test_la_legende_nomme_chaque_reference_posee(self):
        self.f.choix_vue.setCurrentIndex(0)
        posees = {pose.piece.reference for d in self.f._resultat.debits
                  for pose in d.poses}
        libelles = [self.f.legende.item(i).text()
                    for i in range(self.f.legende.count())]
        for reference in posees:
            self.assertTrue(any(t.startswith(reference) for t in libelles),
                            "« %s » manque à la légende" % reference)

    def test_le_plan_devient_obsolete_quand_la_saisie_change(self):
        self.f._calculer()
        self.assertTrue(self.f._a_jour)
        self.f.table_pieces.item(0, 1).setText("1700")
        self.assertFalse(self.f._a_jour)
        self.f._calculer()

    def test_export_image(self):
        chemin = os.path.join(_JETABLE, "plan.png")
        self.assertTrue(self.f.vue.exporter_image(chemin, largeur_px=800))
        self.assertGreater(os.path.getsize(chemin), 1000)

    def test_enregistrer_puis_relire_rend_la_meme_saisie(self):
        chemin = os.path.join(_JETABLE, "projet.json")
        self.f._chemin = chemin
        self.f._enregistrer()
        pieces, stock, parametres = projet_io.lire(chemin)
        self.assertEqual(pieces, self.f.table_pieces.pieces())
        self.assertEqual(stock, self.f.table_stock.stock())
        self.assertEqual(parametres, self.f._parametres_actuels())

    def test_nouveau_repart_d_une_feuille_blanche(self):
        f = _fenetre()
        f._modifie = False
        f._nouveau()
        self.assertEqual(f.table_pieces.pieces(), [])
        self.assertEqual(f.table_stock.stock(), [])
        self.assertIsNone(f._resultat)

    def test_une_fenetre_neuve_n_est_pas_modifiee(self):
        """L'accueil chargeait l'exemple puis appliquait les réglages
        mémorisés — après que ``_remplir`` eut relâché le drapeau de
        chargement. La fenêtre s'ouvrait « ● Projet non enregistré » sans
        qu'on ait rien touché, et tout geste demandant confirmation
        d'abandon posait sa boîte modale — ce qui figeait aussi la suite
        de tests, sans écran pour cliquer."""
        f = _fenetre()
        self.assertFalse(f._modifie)
        f._charger_exemple_volets()      # sans dialogue, donc sans blocage
        self.assertEqual(len(f._resultat.debits), 5)

    def test_masquer_la_saisie_laisse_tout_au_plan(self):
        self.f.a_saisie.setChecked(True)
        self.assertEqual(self.f._splitter.sizes()[0], 0)
        self.f.a_saisie.setChecked(False)
        self.assertGreater(self.f._splitter.sizes()[0], 0)

    def test_les_cotes_s_affichent_au_micron(self):
        """Une écharpe sort du modèle FreeCAD à 829,6857318589343 mm. La
        table l'arrondit au micron : treize décimales ne se scient pas, et
        la feuille de débit se lit comme on la mesure. C'est un choix, pas
        une perte accidentelle — d'où ce test."""
        f = _fenetre()
        f._charger_exemple_volets()
        echarpe = [p for p in f.table_pieces.pieces()
                   if p.reference == "Echarpe G"][0]
        self.assertAlmostEqual(echarpe.longueur, 829.6857318589343, places=3)
        self.assertEqual(f.table_pieces.texte(7, 1), "829.686")

    def test_nouveau_efface_aussi_les_resultats(self):
        """« Nouveau » ne vidait que le plan et les tuiles : les onglets
        gardaient leurs comptes, la liste d'achats sa ligne, la légende
        ses pastilles. Un projet neuf s'ouvrait avec le bilan du
        précédent."""
        f = _fenetre()
        self.assertGreater(f.liste_achats.count(), 0)
        self.assertGreater(f.legende.count(), 0)
        f._modifie = False
        f._nouveau()
        self.assertEqual(f.liste_achats.count(), 0)
        self.assertEqual(f.liste_chutes.count(), 0)
        self.assertEqual(f.legende.count(), 0)
        self.assertEqual(f.liste_planches.count(), 0)
        for indice in (interface.ACHATS, interface.CHUTES,
                       interface.NON_PLACEES):
            self.assertNotIn("·", f.onglets_resultats.tabText(indice))

    def test_l_export_borne_la_taille_de_l_image(self):
        """Soixante planches font une scène de 7:1 : à 2400 px de large,
        l'image réclamait 16 774 px de haut, 161 Mo — et un PNG de cette
        forme ne s'imprime pas."""
        f = _fenetre()
        f._remplir([opt.Piece("p%d" % i, 900, 180, 27, "douglas", 1)
                    for i in range(180)],
                   [opt.Planche("douglas 3 m", 3000, 200, 30, "douglas",
                                quantite=1, illimite=True)],
                   opt.Parametres(essais_melanges=0))
        f._calculer()
        self.assertGreater(len(f._resultat.debits), 30)
        image = f.vue.rendre_image(24000)
        self.assertIsNotNone(image)
        self.assertLessEqual(image.width() * image.height(),
                             f.vue.PIXELS_MAX)

    def test_la_fiche_d_atelier_liste_les_planches(self):
        chemin = os.path.join(_JETABLE, "fiche.txt")
        with _dialogue_repond(chemin):
            self.f._exporter_fiche()
        contenu = open(chemin, encoding="utf-8").read()
        for debit in self.f._resultat.debits:
            self.assertIn(debit.planche.reference, contenu)
        for pose in self.f._resultat.debits[0].poses:
            self.assertIn(pose.piece.reference, contenu)

    def test_export_csv_puis_reimport(self):
        chemin = os.path.join(_JETABLE, "pieces.csv")
        with _dialogue_repond(chemin):
            self.f._exporter_csv()
        self.assertEqual(csv_io.lire_pieces(chemin),
                         self.f.table_pieces.pieces())

    def test_la_page_imprimee_se_compose(self):
        """L'impression ne peut pas être essayée sans imprimante, mais sa
        mise en page, si : on peint sur une image aux dimensions d'une A4
        paysage à 150 points par pouce."""
        f = _fenetre()
        page = QImage(1754, 1240, QImage.Format.Format_ARGB32)
        page.fill(Qt.GlobalColor.white)
        peintre = QPainter(page)
        try:
            f._dessiner_page(peintre)
        finally:
            peintre.end()
        blancs = sum(1 for y in range(0, page.height(), 7)
                     for x in range(0, page.width(), 7)
                     if page.pixelColor(x, y) == Qt.GlobalColor.white)
        total = len(range(0, page.height(), 7)) * len(range(0, page.width(), 7))
        self.assertLess(blancs / total, 0.97, "la page est restée blanche")

    def test_un_debit_courant_tient_sur_une_page(self):
        f = _fenetre()
        self.assertEqual(len(f._pages_a_imprimer()), 1)
        f._charger_exemple_volets()
        self.assertEqual(len(f._resultat.debits), 5)
        self.assertEqual(len(f._pages_a_imprimer()), 1)

    def test_un_gros_debit_se_pagine(self):
        """Tout imprimer sur UNE page marchait pour cinq planches et
        donnait une bande illisible pour soixante."""
        f = _fenetre()
        f._remplir([opt.Piece("p%d" % i, 900, 180, 27, "douglas", 1)
                    for i in range(180)],
                   [opt.Planche("douglas 3 m", 3000, 200, 30, "douglas",
                                quantite=1, illimite=True)],
                   opt.Parametres(essais_melanges=0))
        f._calculer()
        pages = f._pages_a_imprimer()
        self.assertGreater(len(pages), 1)
        self.assertEqual(sum(len(p) for p in pages), len(f._resultat.debits))
        self.assertLessEqual(max(len(p) for p in pages), 8)
        # aucune planche perdue ni comptée deux fois
        numeros = [n for page in pages for n, _ in page]
        self.assertEqual(numeros, list(range(1, len(numeros) + 1)))

    def test_le_document_sort_en_pdf(self):
        """L'impression ne peut pas s'essayer sans imprimante, mais tout
        le chemin — pagination, rendu, mise en page — se vérifie sur un
        PDF."""
        f = _fenetre()
        chemin = os.path.join(_JETABLE, "plan.pdf")
        imprimante = QPrinter(QPrinter.PrinterMode.HighResolution)
        imprimante.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        imprimante.setOutputFileName(chemin)
        imprimante.setPageOrientation(QPageLayout.Orientation.Landscape)
        peintre = QPainter()
        self.assertTrue(peintre.begin(imprimante))
        try:
            pages = f.composer_document(peintre, imprimante)
        finally:
            peintre.end()
        self.assertEqual(pages, 1)
        self.assertGreater(os.path.getsize(chemin), 5000)

    def test_les_etiquettes_sortent_en_pdf(self):
        f = _fenetre()
        entrees = f._etiquettes()
        self.assertEqual(len(entrees), f._resultat.bilan.nb_posees)
        self.assertEqual(len(f._pages_etiquettes()), 1)          # 21 ≤ 24
        chemin = os.path.join(_JETABLE, "etiquettes.pdf")
        imprimante = QPrinter(QPrinter.PrinterMode.HighResolution)
        imprimante.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        imprimante.setOutputFileName(chemin)
        peintre = QPainter()
        self.assertTrue(peintre.begin(imprimante))
        try:
            pages = f.composer_etiquettes(peintre, imprimante)
        finally:
            peintre.end()
        self.assertEqual(pages, 1)
        self.assertGreater(os.path.getsize(chemin), 2000)

    def test_les_etiquettes_se_paginent(self):
        f = _fenetre()
        f._remplir([opt.Piece("p%d" % i, 300, 100, 18, "sapin", 1)
                    for i in range(50)],
                   [opt.Planche("sapin", 2400, 200, 18, "sapin", 1,
                                illimite=True)] ,
                   opt.Parametres(essais_melanges=0))
        f._calculer()
        pages = f._pages_etiquettes()
        self.assertEqual(len(pages), 3)
        self.assertEqual(sum(len(p) for p in pages), 50)

    def test_une_page_d_etiquettes_se_dessine(self):
        f = _fenetre()
        page = QImage(1240, 1754, QImage.Format.Format_ARGB32)
        page.fill(Qt.GlobalColor.white)
        peintre = QPainter(page)
        try:
            f._dessiner_etiquettes(peintre, f._etiquettes())
        finally:
            peintre.end()
        encre = sum(1 for y in range(0, 1754, 9) for x in range(0, 1240, 9)
                    if page.pixelColor(x, y) != Qt.GlobalColor.white)
        self.assertGreater(encre, 200, "la page est restée blanche")

    def test_une_piece_etroite_montre_ses_cotes_sur_une_ligne(self):
        """Un montant de 1750 × 60 fait 800 px de large à l'écran et
        n'affichait que « montant » : la variante à deux lignes ne tenait
        pas en hauteur. Celle sur une ligne, si."""
        f = _fenetre()
        f.resize(1680, 960)
        f.show()
        APP.processEvents()
        f.vue.ajuster()
        visibles = {it.text() for it in f.vue.scene().items()
                    if hasattr(it, "text") and it.isVisible()}
        self.assertIn("montant  ·  1750 × 60", visibles)
        self.assertIn("tablette\n560 × 180", visibles)

    def test_les_colonnes_avancees_se_replient_sauf_si_utilisees(self):
        f = _fenetre()
        f.a_avancees.setChecked(False)
        self.assertTrue(f.table_pieces.isColumnHidden(7))     # Composable
        self.assertTrue(f.table_stock.isColumnHidden(10))     # Prix
        f.table_stock.item(0, 10).setText("35")
        f._rafraichir_etat()
        self.assertFalse(f.table_stock.isColumnHidden(10),
                         "une valeur saisie ne se cache jamais")
        f.a_avancees.setChecked(True)
        self.assertFalse(f.table_pieces.isColumnHidden(7))

    def test_un_plan_vide_dit_quoi_faire(self):
        f = _fenetre()
        f._modifie = False
        f._nouveau()
        self.assertIn("F5", f.vue.message_vide)
        f.show()
        APP.processEvents()
        image = f.vue.grab().toImage()
        encre = sum(1 for y in range(0, image.height(), 4)
                    for x in range(0, image.width(), 4)
                    if image.pixelColor(x, y) != image.pixelColor(2, 2))
        self.assertGreater(encre, 30, "le plan vide est resté muet")

    def test_les_deux_tables_sont_visibles_ensemble(self):
        f = _fenetre()
        f.show()
        APP.processEvents()
        self.assertTrue(f.table_pieces.isVisible())
        self.assertTrue(f.table_stock.isVisible())
        self.assertFalse(f.reglages.est_ouvert())
        f.reglages.ouvrir(True)
        APP.processEvents()
        self.assertTrue(f.spin_trait.isVisible())
        self.assertGreater(f.saisie.sizes()[2], 100)

    def test_les_actions_de_ligne_suivent_la_table_qui_a_le_focus(self):
        f = _fenetre()
        f.show()
        APP.processEvents()
        f.table_stock.setFocus()
        APP.processEvents()
        avant = f.table_stock.rowCount()
        f._ajouter_ligne()
        self.assertEqual(f.table_stock.rowCount(), avant + 1)
        f.table_pieces.setFocus()
        APP.processEvents()
        avant = f.table_pieces.rowCount()
        f._ajouter_ligne()
        self.assertEqual(f.table_pieces.rowCount(), avant + 1)

    def test_le_papier_porte_toujours_les_coupes(self):
        f = _fenetre()
        f.case_traits.setChecked(False)
        image = f._image_du_plan(f.vue.debits_affiches(), 1200, traits=True)
        rouge = sum(1 for y in range(0, image.height(), 3)
                    for x in range(0, image.width(), 3)
                    if image.pixelColor(x, y).red() > 150
                    and image.pixelColor(x, y).green() < 90)
        self.assertGreater(rouge, 20, "aucun trait de scie sur le papier")

    def test_les_numeros_de_coupe_sont_sur_le_plan(self):
        f = _fenetre()
        f.case_traits.setChecked(True)
        textes = {it.text() for it in f.vue.scene().items()
                  if hasattr(it, "text")}
        for debit in f._resultat.debits:
            for coupe in debit.coupes:
                self.assertIn(str(coupe.ordre), textes)

    def test_la_fiche_liste_les_coupes(self):
        f = _fenetre()
        fiche = f._resultat.texte()
        self.assertIn("coupe 1 :", fiche)
        self.assertIn("tronçonnage", fiche)

    def test_les_reglages_reviennent_d_une_seance_a_l_autre(self):
        """Un trait de scie est une propriété de la scie, pas du projet :
        le retaper à chaque nouveau débit était une corvée, et une source
        d'erreur silencieuse quand on l'oubliait."""
        reglages = self.f._reglages
        self.addCleanup(reglages.remove, "parametres")
        self.f._appliquer_parametres(
            opt.Parametres(trait_de_scie=4.5, tolerance_epaisseur=5.0))
        self.f._memoriser_reglages()
        suivante = _fenetre()
        self.assertEqual(suivante._parametres_actuels().trait_de_scie, 4.5)
        self.assertEqual(suivante._parametres_actuels().tolerance_epaisseur,
                         5.0)
        suivante._modifie = False
        suivante._nouveau()
        self.assertEqual(suivante._parametres_actuels().trait_de_scie, 4.5)

    def test_un_reglage_disparu_ne_bloque_pas_l_ouverture(self):
        self.f._reglages.setValue(
            "parametres", '{"trait_de_scie": 3.0, "vieux_champ": 12}')
        self.addCleanup(self.f._reglages.remove, "parametres")
        self.assertEqual(self.f._reglages_memorises(), opt.Parametres())

    def test_le_dialogue_de_perte_propose_d_enregistrer(self):
        """N'offrir qu'« abandonner ou annuler » obligeait à annuler,
        enregistrer à la main, puis refaire le geste."""
        f = _fenetre()
        f._chemin = os.path.join(_JETABLE, "sauve-au-vol.json")
        f._modifie = True
        with mock.patch.object(
                interface.QMessageBox, "warning",
                return_value=interface.QMessageBox.StandardButton.Save):
            self.assertTrue(f._confirmer_abandon())
        self.assertFalse(f._modifie)
        self.assertTrue(os.path.exists(f._chemin))

    def test_annuler_protege_la_saisie(self):
        f = _fenetre()
        f._modifie = True
        with mock.patch.object(
                interface.QMessageBox, "warning",
                return_value=interface.QMessageBox.StandardButton.Cancel):
            self.assertFalse(f._confirmer_abandon())

    def test_les_cotes_s_impriment_sous_le_plan(self):
        """Une planche de 4 m sur 150 en travers d'une A4 laisse la moitié
        de la page blanche, et les étiquettes du dessin ne portent que le
        NOM des pièces. Les cotes vont dans ce blanc-là."""
        f = _fenetre()
        zone = QImage(1200, 300, QImage.Format.Format_ARGB32)
        zone.fill(Qt.GlobalColor.white)
        peintre = QPainter(zone)
        try:
            f._dessiner_cotes(peintre, f.vue.debits_affiches(),
                              QRectF(10, 10, 1180, 280))
        finally:
            peintre.end()
        encre = sum(1 for y in range(0, 300, 3) for x in range(0, 1200, 3)
                    if zone.pixelColor(x, y) != Qt.GlobalColor.white)
        self.assertGreater(encre, 50, "aucune cote imprimée")

    def test_pas_de_cotes_si_le_plan_prend_toute_la_page(self):
        f = _fenetre()
        page = QImage(600, 40, QImage.Format.Format_ARGB32)
        page.fill(Qt.GlobalColor.white)
        peintre = QPainter(page)
        try:
            f._dessiner_cotes(peintre, f.vue.debits_affiches(),
                              QRectF(0, 0, 600, 8))
        finally:
            peintre.end()
        encre = sum(1 for y in range(40) for x in range(0, 600, 3)
                    if page.pixelColor(x, y) != Qt.GlobalColor.white)
        self.assertEqual(encre, 0, "le dessin prime : pas de texte écrasé")

    def test_les_reglages_font_l_aller_retour(self):
        p = opt.Parametres(trait_de_scie=4.0, surcote_longueur=6.0,
                           surcote_largeur=2.0, tolerance_epaisseur=5.0,
                           chute_mini_longueur=300.0, chute_mini_largeur=50.0,
                           surcote_joint=4.0, essais_melanges=3,
                           priorite=opt.PRIORITE_SCIE, passes_amelioration=5,
                           coupe_en_bandes=True, vitesse_fraisage=900.0)
        self.f._appliquer_parametres(p)
        self.assertEqual(self.f._parametres_actuels(), p)
        self.f._appliquer_parametres(opt.Parametres())


if __name__ == "__main__":
    unittest.main(verbosity=2)
