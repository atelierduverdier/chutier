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

import os
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_JETABLE = tempfile.mkdtemp(prefix="chutier-tests-")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  _JETABLE)

APP = QApplication.instance() or QApplication([])

import apparence  # noqa: E402
import interface  # noqa: E402
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


def _fenetre():
    f = interface.FenetrePrincipale()
    f._calculer()
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
            avant = planche.quantite
            reste = sum(p.quantite for p in apres
                        if p.reference == planche.reference)
            self.assertEqual(reste,
                             avant - consommees.get(planche.reference, 0),
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

    def test_les_reglages_font_l_aller_retour(self):
        p = opt.Parametres(trait_de_scie=4.0, surcote_longueur=6.0,
                           surcote_largeur=2.0, tolerance_epaisseur=5.0,
                           chute_mini_longueur=300.0, chute_mini_largeur=50.0,
                           surcote_joint=4.0, essais_melanges=3)
        self.f._appliquer_parametres(p)
        self.assertEqual(self.f._parametres_actuels(), p)
        self.f._appliquer_parametres(opt.Parametres())


if __name__ == "__main__":
    unittest.main(verbosity=2)
