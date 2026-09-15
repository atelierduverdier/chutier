# -*- coding: utf-8 -*-
"""saisie.py est sans Qt, partagé par le bureau et la page web — mais
n'avait encore aucun test à lui : chaque bug de la colonne Défauts se
découvrait dans l'interface. analyser_termes_defauts()/
texte_depuis_termes() sont le cœur de l'assistant Défauts (bureau et
web) : le terme à terme, jamais destructeur, qui fait tourner les deux.

Lancement : python3 tests/test_saisie.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from saisie import (  # noqa: E402
    ErreurSaisie, analyser_termes_defauts, lire_defauts, texte_defauts,
    texte_depuis_termes, texte_nombre,
)


class TexteNombre(unittest.TestCase):

    def test_entier_sans_decimale(self):
        self.assertEqual(texte_nombre(1942), "1942")
        self.assertEqual(texte_nombre(1942.0), "1942")

    def test_decimale_sans_zero_decoratif(self):
        self.assertEqual(texte_nombre(30.5), "30.5")
        self.assertEqual(texte_nombre(1200.100), "1200.1")


class AnalyserTermesDefauts(unittest.TestCase):

    def test_bouts(self):
        self.assertEqual(analyser_termes_defauts("bouts 30"),
                         [{"genre": "bouts", "valeur": 30.0}])

    def test_rives_avec_virgule_decimale(self):
        self.assertEqual(analyser_termes_defauts("rives 8,5"),
                         [{"genre": "rives", "valeur": 8.5}])

    def test_bande_toujours_triee(self):
        """1280-1200 doit revenir dans le même ordre que 1200-1280 : la
        planche ne sait pas dans quel sens on l'a tapée."""
        self.assertEqual(analyser_termes_defauts("1280-1200"),
                         [{"genre": "bande", "de": 1200.0, "a": 1280.0}])

    def test_zone(self):
        self.assertEqual(
            analyser_termes_defauts("600,140,60,40"),
            [{"genre": "zone", "x": 600.0, "y": 140.0,
              "longueur": 60.0, "largeur": 40.0}])

    def test_plusieurs_termes_dans_l_ordre(self):
        termes = analyser_termes_defauts("bouts 30 ; rives 8 ; 1200-1280")
        self.assertEqual([t["genre"] for t in termes],
                         ["bouts", "rives", "bande"])

    def test_terme_non_reconnu_garde_tel_quel(self):
        """lire_defauts refuserait la ligne entière — l'assistant, lui,
        ne doit jamais perdre ce qu'il ne sait pas lire."""
        self.assertEqual(analyser_termes_defauts("un jour je saurai"),
                         [{"genre": "brut", "texte": "un jour je saurai"}])

    def test_texte_vide(self):
        self.assertEqual(analyser_termes_defauts(""), [])
        self.assertEqual(analyser_termes_defauts(None), [])

    def test_termes_vides_ignores(self):
        self.assertEqual(analyser_termes_defauts("bouts 30 ; ; rives 8"),
                         [{"genre": "bouts", "valeur": 30.0},
                          {"genre": "rives", "valeur": 8.0}])


class TexteDepuisTermes(unittest.TestCase):

    def test_aller_retour(self):
        """Ce qu'analyser_termes_defauts lit, texte_depuis_termes doit
        pouvoir le réécrire à l'identique en sens inverse."""
        texte = "bouts 30 ; rives 8 ; 1200-1280 ; 600,140,60,40"
        self.assertEqual(
            texte_depuis_termes(analyser_termes_defauts(texte)), texte)

    def test_brut_recopie_tel_quel(self):
        self.assertEqual(
            texte_depuis_termes([{"genre": "brut", "texte": "mystère"}]),
            "mystère")

    def test_liste_vide(self):
        self.assertEqual(texte_depuis_termes([]), "")

    def test_relisible_par_lire_defauts(self):
        """Le texte reconstruit par l'assistant doit rester un texte
        Défauts VALIDE pour le reste de l'application, pas seulement
        pour lui-même."""
        termes = analyser_termes_defauts("bouts 30 ; 600,140,60,40")
        texte = texte_depuis_termes(termes)
        lu = lire_defauts(texte, "essai", 200.0)
        self.assertEqual(lu["recoupe_bouts"], 30.0)
        self.assertEqual(lu["defauts"], ((600.0, 140.0, 60.0, 40.0),))


class ContreLireDefauts(unittest.TestCase):
    """lire_defauts existait déjà mais n'avait pas de test direct : les
    deux analyseurs doivent s'accorder sur les mêmes termes."""

    def test_lire_defauts_leve_sur_un_terme_incompris(self):
        with self.assertRaises(ErreurSaisie):
            lire_defauts("charabia", "essai", 200.0)

    def test_texte_defauts_et_texte_depuis_termes_s_accordent(self):
        import optimiseur as opt
        planche = opt.Planche(reference="essai", longueur=2400,
                              largeur=200, epaisseur=18, matiere="sapin",
                              recoupe_bouts=30.0,
                              defauts=((1200.0, 0.0, 80.0, 200.0),))
        texte_objet = texte_defauts(planche)
        texte_termes = texte_depuis_termes(
            analyser_termes_defauts(texte_objet))
        self.assertEqual(texte_objet, texte_termes)


if __name__ == "__main__":
    unittest.main()
