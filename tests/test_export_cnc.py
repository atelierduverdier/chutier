# -*- coding: utf-8 -*-
"""Tests des exports DXF et LightBurn — relus par un lecteur indépendant :
xml.etree et les regex de LaserAtelier pour le .lbrn, une lecture des
paires code/valeur pour le DXF.

Lancement : python3 tests/test_export_cnc.py
"""

import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import export_cnc  # noqa: E402
import pont_web  # noqa: E402
import json  # noqa: E402
from optimiseur import FIL_INDIFFERENT, Parametres, Piece, Planche, optimiser  # noqa: E402

CADRE = ((0, 0), (100, 0), (100, 100), (0, 100))
TROU = ((20, 20), (80, 20), (80, 80), (20, 80))


def _debit():
    pieces = [Piece("cadre", 100, 100, 15, "cp", 1, FIL_INDIFFERENT,
                    contour=CADRE, trous=(TROU,)),
              Piece("cale", 60, 30, 15, "cp", 2)]
    stock = [Planche("cp", 300, 200, 15, "cp", 1, fil=False)]
    return optimiser(pieces, stock, Parametres(essais_melanges=0,
                                                processus=1)).debits[0]


def _paires_dxf(texte):
    lignes = texte.splitlines()
    return [(lignes[i].strip(), lignes[i + 1].strip())
            for i in range(0, len(lignes) - 1, 2)]


class Dxf(unittest.TestCase):

    def test_une_polyline_fermee_par_contour(self):
        d = _debit()
        texte = export_cnc.dxf_planche(d, 1, "essai")
        paires = _paires_dxf(texte)
        polylines = [i for i, p in enumerate(paires) if p == ("0", "POLYLINE")]
        # la planche, le cadre, son trou, deux cales
        self.assertEqual(len(polylines), 1 + 2 + 2)
        for i in polylines:
            self.assertIn(("70", "1"), paires[i:i + 8], "polyline non fermée")
        self.assertEqual(paires.count(("0", "SEQEND")), len(polylines))
        self.assertEqual(paires.count(("0", "TEXT")), len(d.poses))
        self.assertIn(("1", "AC1009"), paires)
        self.assertTrue(texte.rstrip().endswith("EOF"))

    def test_les_sommets_sont_ceux_de_la_pose(self):
        d = _debit()
        paires = _paires_dxf(export_cnc.dxf_planche(d))
        xs = [float(v) for c, v in paires if c == "10"]
        ys = [float(v) for c, v in paires if c == "20"]
        for pose in d.poses:
            for x, y in (pose.contour or ()):
                self.assertTrue(any(abs(x - vx) < 1e-3 for vx in xs))
                self.assertTrue(any(abs(y - vy) < 1e-3 for vy in ys))


class LightBurn(unittest.TestCase):

    def test_un_shape_par_contour(self):
        d = _debit()
        texte = export_cnc.lightburn_planche(d, 1, "essai <&>")
        racine = ET.fromstring(texte)
        self.assertEqual(racine.tag, "LightBurnProject")
        formes = racine.findall("Shape")
        self.assertEqual(len(formes), 1 + 2 + 2)
        self.assertEqual([f.get("CutIndex") for f in formes][0], "1")
        self.assertTrue(all(f.get("CutIndex") == "0" for f in formes[1:]))
        self.assertEqual(len(racine.findall("CutSetting")), 2)

    def test_relu_par_le_lecteur_de_laseratelier(self):
        chemin = os.path.expanduser(
            "~/.local/share/FreeCAD/v1-1/Mod/LaserAtelier/svg_import.py")
        if not os.path.exists(chemin):
            self.skipTest("LaserAtelier absent")
        import importlib.util
        spec = importlib.util.spec_from_file_location("svg_import_la", chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        d = _debit()
        import tempfile
        fichier = os.path.join(tempfile.mkdtemp(), "planche.lbrn")
        with open(fichier, "w", encoding="utf-8") as f:
            f.write(export_cnc.lightburn_planche(d, 1))
        chemins, bornes = module.convertir_lightburn(fichier)
        self.assertEqual(len(chemins), 5)
        self.assertTrue(all(dd.endswith("Z") for _, dd in chemins), "contours fermés")
        self.assertAlmostEqual(bornes[2], 300, places=3)
        self.assertAlmostEqual(bornes[3], 200, places=3)

    def test_sommets_et_segments(self):
        d = _debit()
        texte = export_cnc.lightburn_planche(d)
        premier = re.search(r"<VertList>(.*?)</VertList>", texte).group(1)
        self.assertEqual(premier.count("V"), 4)          # la planche
        prims = re.search(r"<PrimList>(.*?)</PrimList>", texte).group(1)
        self.assertEqual(prims, "L0 1L1 2L2 3L3 0")


class Pont(unittest.TestCase):

    def test_decoupe_dans_les_trois_formats(self):
        sortie = json.loads(pont_web.calculer(pont_web.exemple_formes().replace(
            '"processus": 0', '"processus": 1')))
        debit = sortie["resultat"]["debits"][0]["epingle"]
        for fmt, marque in (("svg", "<svg"), ("dxf", "AC1009"),
                            ("lbrn", "<LightBurnProject")):
            self.assertIn(marque, pont_web.decoupe(fmt, json.dumps(debit), 1, "t"))
        with self.assertRaises(ValueError):
            pont_web.decoupe("pdf", json.dumps(debit))


if __name__ == "__main__":
    unittest.main(verbosity=2)
