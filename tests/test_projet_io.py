# -*- coding: utf-8 -*-
"""Tests de la sauvegarde/chargement du projet (pièces, stock, paramètres).

Lancement : python3 tests/test_projet_io.py
"""

import dataclasses
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimiseur import FIL_INDIFFERENT, Parametres, Piece, Planche  # noqa: E402
import projet_io  # noqa: E402


def _chemin_temp() -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    f.close()
    return f.name


class EnregistrerEtLire(unittest.TestCase):

    def test_aller_retour(self):
        pieces = [
            Piece("montant", 1750, 60, 18, "sapin", 4),
            Piece("taquet", 120, 40, 18, "sapin", 8, FIL_INDIFFERENT,
                 composable=True),
        ]
        stock = [
            Planche("sapin 2400x200", 2400, 200, 18, "sapin", quantite=4),
            Planche("catalogue", 4000, 175, 65, "sapin", illimite=True,
                    prix=35.0),
            Planche("chute", 800, 180, 18, "sapin", chute=True),
            Planche("abimee", 2400, 200, 18, "sapin", recoupe_bouts=30,
                    defauts=((1200, 0, 80, 200), (600, 140, 60, 40))),
        ]
        parametres = Parametres(trait_de_scie=4.0, tolerance_epaisseur=5.0,
                                surcote_joint=2.5)

        chemin = _chemin_temp()
        projet_io.enregistrer(chemin, pieces, stock, parametres)
        pieces_lues, stock_lu, parametres_lus = projet_io.lire(chemin)

        self.assertEqual(pieces_lues, pieces)
        self.assertEqual(stock_lu, stock)
        self.assertEqual(parametres_lus, parametres)

    def test_parametres_absents_valent_les_defauts(self):
        chemin = _chemin_temp()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write('{"pieces": [], "stock": []}')
        _, _, parametres = projet_io.lire(chemin)
        self.assertEqual(parametres, Parametres())

    def test_json_invalide(self):
        chemin = _chemin_temp()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("{ceci n'est pas du JSON")
        with self.assertRaises(ValueError):
            projet_io.lire(chemin)

    def test_champ_manquant(self):
        chemin = _chemin_temp()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write('{"pieces": []}')      # "stock" absent
        with self.assertRaises(ValueError):
            projet_io.lire(chemin)

    def test_champ_de_piece_inconnu(self):
        chemin = _chemin_temp()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write('{"pieces": [{"reference": "x", "longueur": 100,'
                    ' "largeur": 50, "epaisseur_qui_n_existe_pas": 1}],'
                    ' "stock": []}')
        with self.assertRaises(ValueError):
            projet_io.lire(chemin)

    def test_fichier_introuvable(self):
        with self.assertRaises(OSError):
            projet_io.lire("/inexistant/projet.json")

    def test_jamais_de_qt(self):
        # règle de couches : la persistance de projet ne connaît pas
        # l'interface, comme optimiseur.py et csv_io.py
        chemin = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "projet_io.py")
        with open(chemin, encoding="utf-8") as f:
            source = f.read()
        for interdit in ("PySide", "PyQt", "QtWidgets", "QtCore", "QtGui"):
            self.assertNotIn(interdit, source)


class Epingles(unittest.TestCase):

    def test_aller_retour(self):
        import optimiseur as opt
        pieces = [Piece("montant", 1750, 60, 18, "sapin", 4)]
        stock = [Planche("sapin", 2400, 200, 18, "sapin", 2)]
        resultat = opt.optimiser(pieces, stock, Parametres(essais_melanges=0))
        chemin = _chemin_temp()
        projet_io.enregistrer(chemin, pieces, stock, Parametres(),
                              epingles=resultat.debits)
        relues = projet_io.lire_epingles(chemin)
        self.assertEqual(relues, resultat.debits)

    def test_projet_d_avant_les_epingles(self):
        chemin = _chemin_temp()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write('{"pieces": [], "stock": []}')
        self.assertEqual(projet_io.lire_epingles(chemin), [])


class Atelier(unittest.TestCase):
    """Le fichier commun : lu absent comme vide, écrit marqué atelier."""

    def test_absent_vaut_vide(self):
        self.assertEqual(projet_io.lire_atelier("/inexistant/atelier.json"),
                         [])

    def test_aller_retour_marque_atelier(self):
        chemin = os.path.join(tempfile.mkdtemp(), "sous", "atelier.json")
        stock = [Planche("chute", 800, 180, 18, "sapin", chute=True),
                 Planche("rayon", 2000, 150, 27, "chêne", quantite=3)]
        projet_io.enregistrer_atelier(chemin, stock)      # dossier créé
        relu = projet_io.lire_atelier(chemin)
        self.assertEqual(relu, [dataclasses.replace(s, atelier=True)
                                for s in stock])

    def test_chemin_par_defaut(self):
        with mock.patch.dict(os.environ, {"CHUTIER_ATELIER": "",
                                          "XDG_DATA_HOME": "/donnees"}):
            self.assertEqual(projet_io.chemin_atelier(),
                             "/donnees/chutier/atelier.json")
        with mock.patch.dict(os.environ, {"CHUTIER_ATELIER": "/ici.json"}):
            self.assertEqual(projet_io.chemin_atelier(), "/ici.json")

    def test_mal_forme(self):
        chemin = _chemin_temp()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write('{"pieces": []}')
        with self.assertRaises(ValueError):
            projet_io.lire_atelier(chemin)


class EcritureAtomique(unittest.TestCase):
    """Un disque plein ou une coupure en plein json.dump laissait un
    projet TRONQUE a la place du bon : le fichier de destination etait
    ouvert en ecriture avant meme de savoir si l'ecriture aboutirait."""

    def test_un_echec_laisse_l_ancien_fichier_intact(self):
        chemin = _chemin_temp()
        pieces = [Piece("montant", 1750, 60, 18, "sapin", 4)]
        stock = [Planche("b", 2400, 200, 18, "sapin")]
        projet_io.enregistrer(chemin, pieces, stock, Parametres())
        avant = open(chemin, encoding="utf-8").read()

        with mock.patch("json.dump", side_effect=OSError("disque plein")):
            with self.assertRaises(OSError):
                projet_io.enregistrer(chemin, pieces, stock,
                                     Parametres(trait_de_scie=9.0))

        self.assertEqual(open(chemin, encoding="utf-8").read(), avant)
        relu = projet_io.lire(chemin)
        self.assertEqual(relu[0], pieces)

    def test_aucun_fichier_temporaire_ne_subsiste(self):
        chemin = _chemin_temp()
        dossier = os.path.dirname(os.path.abspath(chemin))
        avant = set(os.listdir(dossier))
        pieces = [Piece("montant", 1750, 60, 18, "sapin", 4)]
        projet_io.enregistrer(chemin, pieces, [], Parametres())
        with mock.patch("json.dump", side_effect=OSError("disque plein")):
            with self.assertRaises(OSError):
                projet_io.enregistrer(chemin, pieces, [], Parametres())
        restes = {n for n in set(os.listdir(dossier)) - avant
                  if n.startswith(".chutier-")}
        self.assertEqual(restes, set())



class PlancheBiscornue(unittest.TestCase):

    def test_aller_retour_avec_contour(self):
        """Une chute biscornue au stock revient du JSON identique, contour
        et trous compris (et hachable, pour compter les exemplaires)."""
        import json
        pl = Planche("biscornue", 0, 0, 18, "cp", 1, chute=True,
                         contour=((10, 10), (110, 10), (110, 60), (10, 60)),
                         trous=(((30, 20), (50, 20), (50, 40), (30, 40)),))
        self.assertEqual((pl.longueur, pl.largeur), (100.0, 50.0))
        self.assertEqual(pl.contour[0], (0.0, 0.0))
        self.assertEqual(pl.trous[0][0], (20.0, 10.0))
        self.assertAlmostEqual(pl.aire, 5000 - 400)
        d = projet_io.donnees_projet([], [pl], Parametres())
        stock = projet_io.depuis_donnees(json.loads(json.dumps(d)))[1]
        self.assertEqual(stock, [pl])
        self.assertEqual(hash(stock[0]), hash(pl))

if __name__ == "__main__":
    unittest.main(verbosity=2)
