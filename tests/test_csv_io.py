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


class EcriturePieces(unittest.TestCase):
    """Le contrat d'echange ne servait que dans un sens : on importait une
    feuille produite ailleurs, jamais on ne ressortait celle qu'on venait
    de saisir."""

    def test_aller_retour(self):
        pieces = [
            Piece("montant", 1750, 60, 18, "sapin", 4),
            Piece("echarpe", 829.6857, 105, 27, "douglas", 1),
            Piece("taquet", 120, 40, 18, "sapin", 8, FIL_INDIFFERENT,
                 composable=True),
        ]
        chemin = _fichier("")
        csv_io.ecrire_pieces(chemin, pieces)
        relues = csv_io.lire_pieces(chemin)
        self.assertEqual(len(relues), len(pieces))
        for ecrite, relue in zip(pieces, relues):
            self.assertEqual(relue.reference, ecrite.reference)
            self.assertAlmostEqual(relue.longueur, ecrite.longueur, places=3)
            self.assertEqual(relue.quantite, ecrite.quantite)
            self.assertEqual(relue.fil, ecrite.fil)
            self.assertEqual(relue.composable, ecrite.composable)

    def test_pas_de_zero_decoratif(self):
        chemin = _fichier("")
        csv_io.ecrire_pieces(
            chemin, [Piece("montant", 1750, 60, 18, "sapin", 4)])
        ligne = open(chemin, encoding="utf-8").read().splitlines()[1]
        self.assertTrue(ligne.startswith("montant,1750,60,18,"), ligne)

    def test_l_entete_ecrit_est_celui_qui_est_lu(self):
        chemin = _fichier("")
        csv_io.ecrire_pieces(chemin, [Piece("p", 10, 10, 10, "m", 1)])
        entete = open(chemin, encoding="utf-8").read().splitlines()[0]
        for colonne in csv_io.COLONNES_REQUISES:
            self.assertIn(colonne, entete.split(","))


class MarqueDOrdre(unittest.TestCase):
    """Excel écrit « CSV UTF-8 » avec une marque d'ordre d'octets, qui se
    colle au premier nom de colonne : le fichier était refusé pour une
    colonne manquante qui, elle, était bien là."""

    LIGNES = ("reference,longueur,largeur,epaisseur,matiere,quantite\n"
              "montant,1750,60,18,sapin,4\n")

    def test_un_fichier_avec_bom(self):
        chemin = os.path.join(tempfile.mkdtemp(), "avec-bom.csv")
        with open(chemin, "w", encoding="utf-8-sig") as f:
            f.write(self.LIGNES)
        with open(chemin, "rb") as f:
            self.assertTrue(f.read(3) == b"\xef\xbb\xbf")
        pieces = csv_io.lire_pieces(chemin)
        self.assertEqual([p.reference for p in pieces], ["montant"])

    def test_un_texte_collé_avec_bom(self):
        pieces = csv_io.lire_pieces_texte("\ufeff" + self.LIGNES)
        self.assertEqual([p.reference for p in pieces], ["montant"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
