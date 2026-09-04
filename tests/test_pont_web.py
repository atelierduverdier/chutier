# -*- coding: utf-8 -*-
"""Tests du pont JSON de la page web — sans navigateur ni Pyodide : ce
que la page appelle, en CPython.

Lancement : python3 tests/test_pont_web.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import couleurs  # noqa: E402
import optimiseur as opt  # noqa: E402
import pont_web  # noqa: E402

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="200mm"
 viewBox="0 0 300 200"><path id="cadre" d="M 10 10 h 100 v 100 h -100 z
 M 30 30 h 60 v 60 h -60 z"/><circle id="rond" cx="200" cy="100" r="20"/></svg>"""


class Calcul(unittest.TestCase):

    def test_l_exemple_se_calcule(self):
        sortie = json.loads(pont_web.calculer(pont_web.exemple()))
        self.assertTrue(sortie["ok"], sortie)
        r = sortie["resultat"]
        self.assertEqual(r["bilan"]["nb_posees"], 21)
        self.assertEqual(len(r["debits"]), r["bilan"]["nb_planches_entamees"])
        self.assertIn("montant", r["couleurs"])
        self.assertTrue(r["fiche"].startswith("Feuille de débit"))
        self.assertTrue(all(c.startswith("#") for c in r["couleurs"].values()))
        premiere = r["debits"][0]
        self.assertIn("epingle", premiere)
        self.assertEqual(len(premiere["poses"]), len(premiere["epingle"]["poses"]))

    def test_l_exemple_des_formes_se_calcule(self):
        entree = json.loads(pont_web.exemple_formes())
        self.assertEqual(entree["parametres"]["pas_rotation"], 180)
        entree["parametres"]["processus"] = 0
        sortie = json.loads(pont_web.calculer(json.dumps(entree)))
        self.assertTrue(sortie["ok"], sortie)
        self.assertEqual(sortie["resultat"]["bilan"]["nb_non_placees"], 0)
        self.assertTrue(sortie["resultat"]["debits"][0]["imbriquee"])

    def test_les_couleurs_sont_celles_du_bureau(self):
        try:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication
            import apparence
        except ImportError:
            self.skipTest("Qt absent")
        QApplication.instance() or QApplication([])
        refs = ["montant", "taquet", "Lame 1 G", "cœur"]
        qt = apparence.palette_pieces(refs)
        web = couleurs.palette_hex(refs)
        for ref in refs:
            self.assertEqual(qt[ref].name(), web[ref])
        self.assertEqual(apparence.couleur_piece("montant").name(),
                         couleurs.hex_piece("montant"))

    def test_defauts_en_texte_et_nombres_en_texte(self):
        entree = json.dumps({
            "pieces": [{"reference": "x", "longueur": "734", "largeur": "100",
                        "epaisseur": "18", "matiere": "b", "quantite": "1"}],
            "stock": [{"reference": "p", "longueur": "800", "largeur": "100",
                       "epaisseur": "18", "matiere": "b", "quantite": "1",
                       "defauts_texte": "bouts 30"}],
            "parametres": {"trait_de_scie": "3", "essais_melanges": "0"}})
        sortie = json.loads(pont_web.calculer(entree))
        self.assertTrue(sortie["ok"], sortie)
        self.assertEqual(sortie["resultat"]["bilan"]["nb_posees"], 1)
        self.assertEqual(sortie["resultat"]["debits"][0]["defauts_texte"],
                         "bouts 30")

    def test_erreur_lisible(self):
        sortie = json.loads(pont_web.calculer(json.dumps({"pieces": [], "stock": []})))
        self.assertFalse(sortie["ok"])
        self.assertIn("aucune pièce", sortie["erreur"])
        sortie = json.loads(pont_web.calculer(json.dumps({
            "pieces": [{"reference": "x", "longueur": 10, "largeur": 10}],
            "stock": [{"reference": "p", "longueur": 100, "largeur": 100,
                       "defauts_texte": "n'importe quoi"}]})))
        self.assertFalse(sortie["ok"])
        self.assertIn("incompris", sortie["erreur"])

    def test_epingle_reprise_puis_relachee(self):
        premier = json.loads(pont_web.calculer(pont_web.exemple()))["resultat"]
        entree = json.loads(pont_web.exemple())
        entree["epingles"] = [premier["debits"][0]["epingle"]]
        second = json.loads(pont_web.calculer(json.dumps(entree)))
        self.assertTrue(second["ok"])
        self.assertFalse(second["epingles_relachees"])
        self.assertEqual([p["reference"] for p in second["resultat"]["debits"][0]["poses"]],
                         [p["reference"] for p in premier["debits"][0]["poses"]])
        entree["pieces"] = [p for p in entree["pieces"] if p["reference"] != "montant"]
        troisieme = json.loads(pont_web.calculer(json.dumps(entree)))
        self.assertTrue(troisieme["ok"])
        self.assertTrue(troisieme["epingles_relachees"])

    def test_stock_apres_debit(self):
        r = json.loads(pont_web.calculer(pont_web.exemple()))["resultat"]
        apres = r["stock_apres"]
        self.assertTrue(any(s["atelier"] and s["chute"] for s in apres)
                        or not r["chutes_groupees"])


class Fichiers(unittest.TestCase):

    def test_svg_dans_les_deux_sens(self):
        lu = json.loads(pont_web.depuis_svg(SVG))
        self.assertEqual([f["nom"] for f in lu["formes"]], ["cadre", "rond"])
        self.assertEqual(len(lu["formes"][0]["trous"]), 1)
        entree = json.loads(pont_web.exemple())
        entree["pieces"] = [{"reference": f["nom"], "longueur": f["longueur"],
                             "largeur": f["largeur"], "epaisseur": 15,
                             "matiere": "cp", "quantite": 1,
                             "fil": opt.FIL_INDIFFERENT, "contour": f["contour"],
                             "trous": f["trous"]} for f in lu["formes"]]
        entree["stock"] = [{"reference": "cp", "longueur": 400, "largeur": 300,
                            "epaisseur": 15, "matiere": "cp", "quantite": 1,
                            "fil": False}]
        entree["parametres"]["processus"] = 1
        sortie = json.loads(pont_web.calculer(json.dumps(entree)))
        self.assertTrue(sortie["ok"], sortie)
        debit = sortie["resultat"]["debits"][0]
        self.assertTrue(debit["imbriquee"])
        svg = pont_web.svg_planche(json.dumps(debit["epingle"]), 1, "essai")
        self.assertIn("<svg", svg)
        relu = json.loads(pont_web.depuis_svg(svg))
        self.assertEqual(len(relu["formes"]), 3)      # planche + 2 pièces

    def test_fcstd_en_base64(self):
        import base64
        import fcstd_io
        donnees = fcstd_io.fabriquer({"Debit": [
            ["Rep.", "Longueur", "Largeur", "Qte"], ["M1", 1000, 60, 2]]})
        lu = json.loads(pont_web.depuis_fcstd(base64.b64encode(donnees).decode()))
        self.assertEqual(lu["pieces"][0]["reference"], "M1")
        self.assertEqual(lu["pieces"][0]["quantite"], 2)
        self.assertIn("erreur", json.loads(pont_web.depuis_fcstd(
            base64.b64encode(b"rien").decode())))

    def test_csv_dans_les_deux_sens(self):
        entree = json.loads(pont_web.exemple())
        csv = pont_web.vers_csv(json.dumps(entree["pieces"]))
        relu = json.loads(pont_web.depuis_csv(csv))
        self.assertEqual([p["reference"] for p in relu["pieces"]],
                         [p["reference"] for p in entree["pieces"]])
        self.assertIn("erreur", json.loads(pont_web.depuis_csv("a,b\n1,2\n")))

    def test_projet_dans_les_deux_sens(self):
        entree = pont_web.exemple()
        texte = pont_web.vers_projet(entree)
        relu = json.loads(pont_web.depuis_projet(texte))
        self.assertEqual(relu["pieces"], json.loads(entree)["pieces"])
        self.assertEqual(relu["stock"][1]["defauts_texte"], "740-800")
        self.assertIn("erreur", json.loads(pont_web.depuis_projet("{pas du json")))

    def test_jamais_de_qt(self):
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for module in ("pont_web.py", "couleurs.py", "saisie.py",
                       "stock_atelier.py"):
            with open(os.path.join(racine, module), encoding="utf-8") as f:
                source = f.read()
            for interdit in ("PySide", "QtWidgets", "QtCore", "QtGui"):
                self.assertNotIn(interdit, source, module)


if __name__ == "__main__":
    unittest.main(verbosity=2)
