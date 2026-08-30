# -*- coding: utf-8 -*-
"""Tests de la lecture CSV des pièces (contrat d'échange avec les projets
qui produisent une liste de pièces, sans dépendre du chutier).

Lancement : python3 tests/test_csv_io.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimiseur import FIL_INDIFFERENT, FIL_LONGUEUR, Piece  # noqa: E402
import csv_io  # noqa: E402


def _fichier(contenu: str) -> str:
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    f.write(contenu)
    f.close()
    return f.name


class LecturePieces(unittest.TestCase):

    def test_cas_nominal(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil\n"
            "montant,1750,60,18,sapin,4,longueur\n"
            "taquet,120,40,18,sapin,8,indifferent\n")
        pieces = csv_io.lire_pieces(chemin)
        self.assertEqual(pieces, [
            Piece("montant", 1750.0, 60.0, 18.0, "sapin", 4, FIL_LONGUEUR),
            Piece("taquet", 120.0, 40.0, 18.0, "sapin", 8, FIL_INDIFFERENT),
        ])

    def test_composable(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil,"
            "composable\n"
            "panneau,650,422,18,sapin,1,longueur,1\n"
            "montant,1750,60,18,sapin,4,longueur,0\n")
        pieces = csv_io.lire_pieces(chemin)
        self.assertTrue(pieces[0].composable)
        self.assertFalse(pieces[1].composable)

    def test_composable_absent_vaut_faux(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite\n"
            "montant,1750,60,18,sapin,4\n")
        pieces = csv_io.lire_pieces(chemin)
        self.assertFalse(pieces[0].composable)

    def test_composable_inconnu(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil,"
            "composable\n"
            "panneau,650,422,18,sapin,1,longueur,peut-etre\n")
        with self.assertRaises(ValueError):
            csv_io.lire_pieces(chemin)

    def test_fil_absent_vaut_longueur(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite\n"
            "montant,1750,60,18,sapin,4\n")
        pieces = csv_io.lire_pieces(chemin)
        self.assertEqual(pieces[0].fil, FIL_LONGUEUR)

    def test_epaisseur_et_quantite_absentes_ont_un_defaut(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil\n"
            "cale,300,50,,,, \n")
        pieces = csv_io.lire_pieces(chemin)
        self.assertEqual(pieces[0].epaisseur, 0.0)
        self.assertEqual(pieces[0].quantite, 1)
        self.assertEqual(pieces[0].matiere, "")

    def test_colonne_manquante(self):
        chemin = _fichier("reference,longueur,largeur\nmontant,1750,60\n")
        with self.assertRaises(ValueError):
            csv_io.lire_pieces(chemin)

    def test_reference_vide(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil\n"
            ",1750,60,18,sapin,4,longueur\n")
        with self.assertRaises(ValueError):
            csv_io.lire_pieces(chemin)

    def test_nombre_invalide(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil\n"
            "montant,abc,60,18,sapin,4,longueur\n")
        with self.assertRaises(ValueError):
            csv_io.lire_pieces(chemin)

    def test_fil_inconnu(self):
        chemin = _fichier(
            "reference,longueur,largeur,epaisseur,matiere,quantite,fil\n"
            "montant,1750,60,18,sapin,4,diagonal\n")
        with self.assertRaises(ValueError):
            csv_io.lire_pieces(chemin)

    def test_fichier_introuvable(self):
        with self.assertRaises(OSError):
            csv_io.lire_pieces("/inexistant/chemin.csv")

    def test_jamais_de_qt(self):
        # règle de couches : la lecture CSV ne connaît pas l'interface
        chemin = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "csv_io.py")
        with open(chemin, encoding="utf-8") as f:
            source = f.read()
        for interdit in ("PySide", "PyQt", "QtWidgets", "QtCore", "QtGui"):
            self.assertNotIn(interdit, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
