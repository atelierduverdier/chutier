# -*- coding: utf-8 -*-
"""Tests de l'import depuis un tableur FreeCAD : formules, alias,
références entre feuilles, titres de section, unités — et le document
réel de la porte de hammam quand il est là.

Lancement : python3 tests/test_fcstd_io.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fcstd_io  # noqa: E402
from optimiseur import FIL_INDIFFERENT, FIL_LONGUEUR  # noqa: E402

PARAMETRES = [
    ["PARAMETRES", None],
    ["Hauteur vantail", (1900, "HautVantail")],
    ["Largeur montant", (110, "LargMontant")],
    ["Épaisseur", ("=35 mm", "EpVantail")],
    ["Longueur traverse", ("=B2 / 2 - 2 * B3", "LongTraverse")],
]
DEBIT = [
    ["FEUILLE DE DEBIT"],
    ["Rep.", "Designation", "Qte", "Longueur", "Largeur", "Epaisseur", "Fil"],
    ["VANTAIL — CADRE (douglas)"],
    ["M1", "Montant", 2, "=round(Parametres.HautVantail * 10) / 10",
     "=Parametres.LargMontant", "=Parametres.EpVantail"],
    ["T1", "Traverse basse", 1, "=Parametres.LongTraverse", "12,5 cm",
     "=Parametres.EpVantail", "indifférent"],
    [],
    ["P1", "Lame", 3, "=max(600, 2^3 * 50 + 100)", 80.5, 15],
]


class Arrondi(unittest.TestCase):
    """FreeCAD arrondit à l'écart de zéro (std::round), Python au pair :
    round(2.5) vaut 3 là-bas, 2 ici. Une feuille de débit qui montre 3 et
    qu'on lit 2, c'est un millimètre de bois en moins sans un mot — et
    « =round(x * 10) / 10 » est la forme la plus courante."""

    def _longueur(self, formule):
        donnees = fcstd_io.fabriquer({"Debit": [
            ["Rep.", "Longueur", "Largeur"], ["A", "=" + formule, 10]]})
        return fcstd_io.lire_pieces(donnees)[0].longueur

    def test_les_demis_montent(self):
        for formule, attendu in (("round(2.5)", 3.0), ("round(0.5)", 1.0),
                                 ("round(1.5)", 2.0), ("round(1234.5)", 1235.0),
                                 ("round(1.2345, 2)", 1.23),
                                 ("round(2.4)", 2.0)):
            self.assertEqual(self._longueur(formule), attendu, formule)

    def test_les_puissances_s_enchainent_par_la_droite(self):
        self.assertEqual(self._longueur("2^3^2"), 512.0)
        self.assertEqual(self._longueur("2^3"), 8.0)


class Lecture(unittest.TestCase):

    def setUp(self):
        self.donnees = fcstd_io.fabriquer({"Parametres": PARAMETRES,
                                           "Debit": DEBIT})

    def test_formules_alias_et_references_entre_feuilles(self):
        pieces = fcstd_io.lire_pieces(self.donnees)
        self.assertEqual([p.reference for p in pieces],
                         ["Montant (M1)", "Traverse basse (T1)", "Lame (P1)"])
        m1, t1, p1 = pieces
        self.assertEqual((m1.longueur, m1.largeur, m1.epaisseur, m1.quantite),
                         (1900.0, 110.0, 35.0, 2))
        self.assertEqual(t1.longueur, 1900 / 2 - 2 * 110)      # via B2, B3
        self.assertEqual(t1.largeur, 125.0)                     # 12,5 cm
        self.assertEqual(t1.fil, FIL_INDIFFERENT)
        self.assertEqual(m1.fil, FIL_LONGUEUR)
        self.assertEqual(p1.longueur, 600.0)                    # max, ^
        self.assertEqual(p1.largeur, 80.5)
        self.assertEqual(p1.quantite, 3)

    def test_le_titre_de_section_et_la_ligne_vide_sont_sautes(self):
        self.assertEqual(len(fcstd_io.lire_pieces(self.donnees)), 3)

    def test_une_feuille_renommee_se_retrouve_par_son_label(self):
        # FreeCAD écrit les formules par le LABEL affiché dans l'arbre
        # (« =Parametres.HautVantail »), pas par le nom interne
        # (« Spreadsheet001 ») : les deux ne coïncident que tant que
        # personne n'a renommé la feuille — audit du 05/09/2026.
        donnees = fcstd_io.fabriquer(
            {"Spreadsheet001": PARAMETRES, "Debit": DEBIT},
            labels={"Spreadsheet001": "Parametres"})
        pieces = fcstd_io.lire_pieces(donnees)
        self.assertEqual(pieces[0].longueur, 1900.0)

    def test_feuille_nommee(self):
        self.assertEqual(len(fcstd_io.lire_pieces(self.donnees, "Debit")), 3)
        with self.assertRaises(ValueError) as leve:
            fcstd_io.lire_pieces(self.donnees, "Cotes")
        self.assertIn("Cotes", str(leve.exception))
        with self.assertRaises(ValueError):
            fcstd_io.lire_pieces(self.donnees, "Parametres")   # pas d'en-tête

    def test_les_refus_nomment_la_cellule(self):
        donnees = fcstd_io.fabriquer({"Debit": [
            ["Rep.", "Longueur", "Largeur"],
            ["A", "=Parametres.Inconnu", 10]]})
        with self.assertRaises(ValueError) as leve:
            fcstd_io.lire_pieces(donnees)
        self.assertIn("Debit!B2", str(leve.exception))
        self.assertIn("Parametres", str(leve.exception))
        donnees = fcstd_io.fabriquer({"Debit": [
            ["Rep.", "Longueur", "Largeur"],
            ["A", "=B3 + 1", 10], ["B", "=B2 + 1", 10]]})
        with self.assertRaises(ValueError) as leve:
            fcstd_io.lire_pieces(donnees)
        self.assertIn("circulaire", str(leve.exception))
        donnees = fcstd_io.fabriquer({"Debit": [
            ["Rep.", "Longueur", "Largeur"], ["A", "douze", 10]]})
        with self.assertRaises(ValueError) as leve:
            fcstd_io.lire_pieces(donnees)
        self.assertIn("douze", str(leve.exception))

    def test_un_document_modele_indique_la_macro(self):
        """Le document des volets battants n'a qu'un tableur de cotes
        pilotes : dire ce qui manque ne suffit pas, il faut indiquer le
        chemin — la macro qui mesure les solides et écrit un CSV."""
        donnees = fcstd_io.fabriquer({"Parametres": [
            ["Hauteur vantail", (1900, "HautVantail")],
            ["Largeur montant", (110, "LargMontant")]]})
        with self.assertRaises(ValueError) as leve:
            fcstd_io.lire_pieces(donnees)
        message = str(leve.exception)
        self.assertIn("Parametres", message)
        self.assertIn("Exporter_Chutier", message)
        self.assertIn("CSV", message)

    def test_le_document_reel_des_volets_battants(self):
        """Modelé, sans feuille de débit : il doit être refusé avec le
        chemin à suivre, pas avec un simple « non »."""
        chemin = os.path.expanduser(
            "~/Projets/realisations/volets-battants/Volets.FCStd")
        if not os.path.exists(chemin):
            self.skipTest("document absent")
        with self.assertRaises(ValueError) as leve:
            fcstd_io.lire_fichier(chemin)
        self.assertIn("Exporter_Chutier", str(leve.exception))

    def test_pas_un_document_freecad(self):
        with self.assertRaises(ValueError):
            fcstd_io.lire_pieces(b"pas un zip")
        import io
        import zipfile
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as z:
            z.writestr("autre.txt", "x")
        with self.assertRaises(ValueError):
            fcstd_io.lire_pieces(tampon.getvalue())

    def test_le_document_reel_de_la_porte_de_hammam(self):
        chemin = os.path.expanduser(
            "~/Projets/realisations/porte-hammam/PorteHammam.FCStd")
        if not os.path.exists(chemin):
            self.skipTest("document absent")
        pieces = fcstd_io.lire_fichier(chemin, "Debit")
        self.assertGreaterEqual(len(pieces), 6)
        montant = [p for p in pieces if p.reference.startswith("Montant")][0]
        self.assertEqual(montant.quantite, 2)
        self.assertGreater(montant.longueur, 1000)
        self.assertGreater(montant.largeur, 50)
        self.assertGreater(montant.epaisseur, 20)
        for p in pieces:
            self.assertGreater(p.longueur, 0)
            self.assertGreater(p.largeur, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
