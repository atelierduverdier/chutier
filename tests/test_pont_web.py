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


class NfpEnParallele(unittest.TestCase):
    """Le navigateur n'a pas de processus : il répartit les no-fit
    polygons entre plusieurs Web Workers. Chaque worker doit voir la MÊME
    liste de tâches, cache ou non, sinon les tranches ne se correspondent
    plus et le plan est faux."""

    def _entree(self):
        import exemples
        pieces, stock, params = exemples.formes_biscornues()
        return json.dumps({
            "pieces": [{"reference": p.reference, "longueur": p.longueur,
                        "largeur": p.largeur, "epaisseur": p.epaisseur,
                        "matiere": p.matiere, "quantite": p.quantite,
                        "fil": "indifferent",
                        "contour": [list(c) for c in p.contour],
                        "trous": [[list(x) for x in t] for t in p.trous]}
                       for p in pieces],
            "stock": [{"reference": s.reference, "longueur": s.longueur,
                       "largeur": s.largeur, "epaisseur": s.epaisseur,
                       "matiere": s.matiere, "quantite": s.quantite,
                       "chute": s.chute, "fil": s.fil} for s in stock],
            "parametres": {"pas_rotation": params.pas_rotation,
                           "ecart_contours": params.ecart_contours,
                           "essais_melanges": 0, "processus": 1}})

    def _vider_caches(self):
        import imbrication
        for cache in (imbrication._VARIANTES, imbrication._NFPS,
                      imbrication._CADRES):
            cache.clear()

    def test_les_tranches_se_recollent_et_donnent_le_meme_plan(self):
        entree = self._entree()
        self._vider_caches()
        seul = json.loads(pont_web.calculer(entree))
        self.assertTrue(seul["ok"], seul)

        self._vider_caches()
        combien = json.loads(pont_web.taches_nfp(entree))
        self.assertTrue(combien["ok"])
        self.assertGreater(combien["nombre"], 40)

        self.assertEqual(combien["manquants"], list(range(combien["nombre"])))

        # trois « workers » : chacun part d'un cache vide, comme dans la page
        manquants = combien["manquants"]
        faits = []
        for part in range(3):
            self._vider_caches()
            rangs = [r for k, r in enumerate(manquants) if k % 3 == part]
            tranche = json.loads(pont_web.calculer_nfp(entree,
                                                       json.dumps(rangs)))
            self.assertTrue(tranche["ok"], tranche)
            faits.extend(tranche["faits"])
        self.assertEqual(len(faits), combien["nombre"])
        self.assertEqual(sorted(r for r, _ in faits),
                         list(range(combien["nombre"])))

        self._vider_caches()
        range_ = json.loads(pont_web.recevoir_nfp(entree, json.dumps(faits)))
        self.assertTrue(range_["ok"], range_)
        import imbrication
        self.assertTrue(imbrication._NFPS and imbrication._CADRES)
        a_plusieurs = json.loads(pont_web.calculer(entree))
        self.assertTrue(a_plusieurs["ok"])
        # le plan doit être le MÊME : le parallélisme ne change pas le résultat
        self.assertEqual(a_plusieurs["resultat"]["bilan"],
                         seul["resultat"]["bilan"])
        self.assertEqual(a_plusieurs["resultat"]["fiche"],
                         seul["resultat"]["fiche"])

    def test_ce_qui_est_deja_en_cache_ne_se_recalcule_pas(self):
        """Au deuxième calcul, tout est en cache : plus rien à répartir,
        et la page se passe des workers auxiliaires."""
        entree = self._entree()
        self._vider_caches()
        self.assertTrue(json.loads(pont_web.calculer(entree))["ok"])
        combien = json.loads(pont_web.taches_nfp(entree))
        self.assertGreater(combien["nombre"], 40)
        self.assertEqual(combien["manquants"], [])

    def test_sans_contour_il_n_y_a_rien_a_repartir(self):
        entree = json.dumps({
            "pieces": [{"reference": "cale", "longueur": 100, "largeur": 50,
                        "epaisseur": 15, "matiere": "cp", "quantite": 2}],
            "stock": [{"reference": "cp", "longueur": 400, "largeur": 200,
                       "epaisseur": 15, "matiere": "cp", "quantite": 1}]})
        self.assertEqual(json.loads(pont_web.taches_nfp(entree))["nombre"], 0)

    def test_une_saisie_invalide_ne_leve_pas(self):
        for mauvaise in ("", "{", '{"pieces": 3}'):
            for sortie in (pont_web.taches_nfp(mauvaise),
                           pont_web.calculer_nfp(mauvaise, "[]"),
                           pont_web.recevoir_nfp(mauvaise, "[]")):
                self.assertIn("ok", json.loads(sortie))


class Deplacement(unittest.TestCase):

    def test_deplacer_renvoie_le_debit_ou_un_refus(self):
        cale = {"reference": "cale", "longueur": 100, "largeur": 50,
                "epaisseur": 15, "matiere": "cp", "quantite": 2,
                "fil": "indifferent",
                "contour": [[0, 0], [100, 0], [100, 50], [0, 50]]}
        stock = [{"reference": "cp", "longueur": 400, "largeur": 200,
                  "epaisseur": 15, "matiere": "cp", "quantite": 1, "fil": False}]
        r = json.loads(pont_web.calculer(json.dumps(
            {"pieces": [cale], "stock": stock,
             "parametres": {"essais_melanges": 0, "processus": 1}})))
        d = r["resultat"]["debits"][0]
        ok = json.loads(pont_web.deplacer(json.dumps(d["epingle"]), 1, 150, 50,
                                          json.dumps({"essais_melanges": 0})))
        self.assertNotIn("refus", ok)
        self.assertAlmostEqual(ok["poses"][1]["x"], d["poses"][1]["x"] + 150)
        self.assertIn("epingle", ok)
        refus = json.loads(pont_web.deplacer(json.dumps(d["epingle"]), 1, 1000,
                                             0, "{}"))
        self.assertIn("refus", refus)


if __name__ == "__main__":
    unittest.main(verbosity=2)
