# -*- coding: utf-8 -*-
"""Tests de l'imbrication de contours (CNC) et de la lecture/écriture SVG.

Lancement : python3 tests/test_imbrication.py

Les invariants d'une imbrication : chaque pièce entière dans sa planche,
à la marge du bord, hors des zones écartées ; deux pièces jamais à moins
de l'écart de fraise ; la surface posée est celle des polygones ; même
entrée, même résultat.
"""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contours_svg  # noqa: E402
from optimiseur import (  # noqa: E402
    FIL_INDIFFERENT, FIL_LONGUEUR, Parametres, Piece, Planche, optimiser,
)

try:
    from shapely.geometry import Polygon, box
    SHAPELY = True
except ImportError:                      # pragma: no cover
    SHAPELY = False

L = ((0, 0), (80, 0), (80, 20), (20, 20), (20, 80), (0, 80))
ROND = tuple((30 + 30 * math.cos(2 * math.pi * i / 40),
              30 + 30 * math.sin(2 * math.pi * i / 40)) for i in range(40))
RAPIDE = Parametres(essais_melanges=0)


def _pieces():
    return [Piece("L", 80, 80, 18, "cp", 5, FIL_INDIFFERENT, contour=L),
            Piece("rond", 60, 60, 18, "cp", 3, FIL_INDIFFERENT, contour=ROND),
            Piece("cale", 120, 40, 18, "cp", 4)]


@unittest.skipUnless(SHAPELY, "shapely absent")
class Invariants(unittest.TestCase):

    def _verifier(self, resultat, params):
        for d in resultat.debits:
            pl = d.planche
            self.assertTrue(d.imbriquee)
            self.assertEqual(d.coupes, [])
            bord = box(0, 0, pl.longueur, pl.largeur).buffer(
                -params.marge_bord + 1e-6, join_style="mitre")
            for x, y, dx, dy in pl.defauts:
                bord = bord.difference(box(x, y, x + dx, y + dy))
            polys = []
            for p in d.poses:
                self.assertTrue(p.contour, "une pose imbriquée porte son contour")
                poly = Polygon(p.contour)
                self.assertTrue(poly.is_valid)
                self.assertTrue(bord.contains(poly.buffer(-1e-3)),
                                "« %s » sort du bord utile" % p.piece.reference)
                self.assertAlmostEqual(p.aire, poly.area, places=3)
                self.assertAlmostEqual(p.x, poly.bounds[0], places=3)
                self.assertAlmostEqual(p.dim_x, poly.bounds[2] - poly.bounds[0],
                                       places=3)
                polys.append(poly)
            for i in range(len(polys)):
                for j in range(i + 1, len(polys)):
                    self.assertGreaterEqual(
                        polys[i].distance(polys[j]),
                        params.ecart_contours - 0.25,     # simplification
                        "deux pièces trop proches")
            for c in d.chutes:
                chute = box(c.x, c.y, c.x + c.dim_x, c.y + c.dim_y)
                for poly in polys:
                    self.assertFalse(chute.intersects(poly.buffer(-1e-3)),
                                     "une chute recouvre une pièce")
            self.assertAlmostEqual(
                d.surface, d.surface_poses + d.surface_chutes + d.perte,
                places=3)
        demandes = sum(p.quantite for p in _pieces())
        poses = sum(len(d.poses) for d in resultat.debits)
        self.assertEqual(demandes, poses + resultat.bilan.nb_non_placees)

    def test_panneau_sans_fil(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 2, fil=False)]
        r = optimiser(_pieces(), stock, RAPIDE)
        self._verifier(r, RAPIDE)
        self.assertEqual(r.bilan.nb_non_placees, 0)

    def test_avec_defauts_et_marge(self):
        params = Parametres(essais_melanges=1, ecart_contours=10,
                            marge_bord=12)
        stock = [Planche("cp", 600, 400, 18, "cp", 2, fil=False,
                         recoupe_bouts=20, defauts=((200, 100, 60, 60),))]
        r = optimiser(_pieces(), stock, params)
        self._verifier(r, params)
        for d in r.debits:
            for p in d.poses:
                self.assertGreaterEqual(p.x, 20 + 12 - 1e-3)

    def test_le_fil_borne_les_orientations(self):
        stock = [Planche("planche", 600, 200, 18, "cp", 3)]     # a un fil
        pieces = [Piece("barre", 150, 30, 18, "cp", 6, FIL_LONGUEUR,
                        contour=((0, 0), (150, 0), (150, 30), (0, 30)))]
        r = optimiser(pieces, stock, RAPIDE)
        for d in r.debits:
            for p in d.poses:
                self.assertIn(p.angle, (0.0, 180.0))
                self.assertFalse(p.pivotee)

    def test_deterministe(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 2, fil=False)]
        a = optimiser(_pieces(), stock, Parametres(essais_melanges=2))
        b = optimiser(_pieces(), stock, Parametres(essais_melanges=2))
        self.assertEqual(a.texte(), b.texte())

    def test_deux_formes_en_l_s_emboitent(self):
        """Deux L de 80 × 80 tête-bêche, à 8 d'écart et 2 du bord,
        tiennent dans 84 × 112 (calculé à la main) — donc dans 100 × 120 ;
        en rectangles englobants (80 + 8 + 80 = 168), jamais."""
        stock = [Planche("carre", 100, 120, 18, "cp", 1, fil=False)]
        pieces = [Piece("L", 80, 80, 18, "cp", 2, FIL_INDIFFERENT, contour=L)]
        r = optimiser(pieces, stock, Parametres(essais_melanges=0,
                                                marge_bord=2, ecart_contours=8))
        self.assertEqual(r.bilan.nb_posees, 2)
        self.assertEqual(r.bilan.nb_planches_entamees, 1)

    def test_les_chutes_sont_des_bandes_utiles(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 1, fil=False)]
        pieces = [Piece("cale", 120, 40, 18, "cp", 2)]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertTrue(r.debits[0].chutes)
        grande = max(r.debits[0].chutes, key=lambda c: c.aire)
        self.assertGreater(grande.aire, 0.5 * 600 * 400)

    def test_lot_rectangles_seuls_reste_guillotine(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 1, fil=False)]
        r = optimiser([Piece("cale", 120, 40, 18, "cp", 2)], stock, RAPIDE)
        self.assertFalse(r.debits[0].imbriquee)
        self.assertTrue(r.debits[0].coupes)

    def test_epingle_sur_une_planche_imbriquee(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 2, fil=False)]
        premier = optimiser(_pieces(), stock, RAPIDE)
        second = optimiser(_pieces(), stock, RAPIDE,
                           epingles=[premier.debits[0]])
        self.assertEqual([p.contour for p in second.debits[0].poses],
                         [p.contour for p in premier.debits[0].poses])
        self.assertEqual(second.bilan.nb_posees, premier.bilan.nb_posees)

    def test_contour_trop_court(self):
        with self.assertRaises(ValueError):
            optimiser([Piece("x", 10, 10, 18, "cp", contour=((0, 0), (1, 1)))],
                      [Planche("cp", 100, 100, 18, "cp")])

    def test_pas_de_rotation_invalide(self):
        with self.assertRaises(ValueError):
            optimiser([Piece("x", 10, 10, 18, "cp")],
                      [Planche("cp", 100, 100, 18, "cp")],
                      Parametres(pas_rotation=70))


SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="200mm"
     viewBox="0 0 300 200">
<g id="calque">
  <rect id="carre" x="10" y="10" width="50" height="40"/>
  <path id="L" d="M 100 10 L 180 10 L 180 30 L 120 30 L 120 90 L 100 90 Z"/>
  <circle id="rond" cx="250" cy="100" r="30"/>
  <path id="anneau" d="M 10 100 h 60 v 60 h -60 z M 20 110 h 40 v 40 h -40 z"/>
  <path id="ouvert" d="M 0 0 L 10 10"/>
</g></svg>"""


class LectureSvg(unittest.TestCase):

    def setUp(self):
        self.chemin = os.path.join(tempfile.mkdtemp(), "formes.svg")
        with open(self.chemin, "w", encoding="utf-8") as f:
            f.write(SVG)

    def test_chaque_trace_ferme_devient_une_forme(self):
        formes, avertissements = contours_svg.formes_depuis_svg(self.chemin)
        noms = [f["nom"] for f in formes]
        self.assertEqual(noms, ["carre", "L", "rond", "anneau"])
        self.assertTrue(any("ouvert" in a for a in avertissements))

    def test_cotes_en_mm_et_origine_au_coin(self):
        formes, _ = contours_svg.formes_depuis_svg(self.chemin)
        carre = formes[0]
        self.assertAlmostEqual(carre["longueur"], 50, places=3)
        self.assertAlmostEqual(carre["largeur"], 40, places=3)
        self.assertEqual(min(p[0] for p in carre["contour"]), 0.0)
        self.assertEqual(min(p[1] for p in carre["contour"]), 0.0)
        rond = formes[2]
        self.assertAlmostEqual(rond["longueur"], 60, places=1)

    def test_le_trou_ne_devient_pas_une_forme(self):
        formes, _ = contours_svg.formes_depuis_svg(self.chemin)
        anneau = formes[3]
        self.assertEqual(len(anneau["contour"]), 4)
        self.assertAlmostEqual(anneau["longueur"], 60, places=3)

    def test_sens_direct(self):
        formes, _ = contours_svg.formes_depuis_svg(self.chemin)
        for forme in formes:
            self.assertGreater(contours_svg._aire_signee(forme["contour"]), 0)


@unittest.skipUnless(SHAPELY, "shapely absent")
class EcritureSvg(unittest.TestCase):

    def test_aller_retour(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 1, fil=False)]
        r = optimiser(_pieces(), stock, RAPIDE)
        chemin = os.path.join(tempfile.mkdtemp(), "decoupe.svg")
        contours_svg.ecrire_svg(chemin, r.debits[0], 1, "essai")
        formes, _ = contours_svg.formes_depuis_svg(chemin)
        # la planche elle-même, puis chaque pièce
        self.assertEqual(len(formes), 1 + len(r.debits[0].poses))
        self.assertAlmostEqual(formes[0]["longueur"], 600, places=3)
        aires_lues = sorted(abs(contours_svg._aire_signee(f["contour"]))
                            for f in formes[1:])
        aires_posees = sorted(p.aire for p in r.debits[0].poses)
        for a, b in zip(aires_lues, aires_posees):
            self.assertAlmostEqual(a, b, delta=b * 0.01)

    def test_jamais_de_qt(self):
        for module in ("contours_svg.py", "imbrication.py"):
            chemin = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), module)
            with open(chemin, encoding="utf-8") as f:
                source = f.read()
            for interdit in ("PySide", "PyQt", "QtWidgets", "QtCore", "QtGui"):
                self.assertNotIn(interdit, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
