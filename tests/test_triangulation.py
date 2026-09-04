# -*- coding: utf-8 -*-
"""Tests de la triangulation maison, contre shapely.

Lancement : python3 tests/test_triangulation.py

Ce qui compte pour une somme de Minkowski : les triangles couvrent
exactement la matière — union égale au polygone, somme des aires égale
à l'aire, aucun chevauchement.
"""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import triangulation  # noqa: E402

try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    SHAPELY = True
except ImportError:                      # pragma: no cover
    SHAPELY = False

L = ((0, 0), (80, 0), (80, 20), (20, 20), (20, 80), (0, 80))
ETOILE = tuple((50 + (40 if i % 2 == 0 else 16) * math.cos(math.pi / 2 + i * math.pi / 5),
                50 + (40 if i % 2 == 0 else 16) * math.sin(math.pi / 2 + i * math.pi / 5))
               for i in range(10))
ROND = tuple((30 + 30 * math.cos(2 * math.pi * i / 40),
              30 + 30 * math.sin(2 * math.pi * i / 40)) for i in range(40))
CADRE = ((0, 0), (200, 0), (200, 200), (0, 200))
TROU = ((30, 30), (170, 30), (170, 170), (30, 170))
TROU2 = ((60, 60), (140, 60), (140, 140), (60, 140))


def _polygone_aleatoire(rng, n):
    """Un polygone étoilé (rayons aléatoires autour d'un centre) : simple
    par construction, aussi concave qu'on veut."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = rng.uniform(20, 100)
        pts.append((r * math.cos(a), r * math.sin(a)))
    return tuple(pts)


@unittest.skipUnless(SHAPELY, "shapely absent")
class Couverture(unittest.TestCase):

    def _verifier(self, exterieur, trous=()):
        attendu = Polygon(exterieur, [list(t) for t in trous])
        tris = triangulation.trianguler(exterieur, trous)
        self.assertTrue(tris, "aucun triangle")
        polys = [Polygon(t) for t in tris]
        for p in polys:
            self.assertTrue(p.is_valid)
            self.assertGreater(p.area, 0)
        self.assertAlmostEqual(sum(p.area for p in polys), attendu.area,
                               delta=attendu.area * 1e-6 + 1e-6,
                               msg="chevauchement ou manque")
        union = unary_union(polys)
        self.assertAlmostEqual(union.symmetric_difference(attendu).area, 0.0,
                               delta=attendu.area * 1e-6 + 1e-6,
                               msg="l'union n'est pas le polygone")

    def test_equerre(self):
        self._verifier(L)

    def test_etoile(self):
        self._verifier(ETOILE)

    def test_rond(self):
        self._verifier(ROND)

    def test_cadre_a_un_trou(self):
        self._verifier(CADRE, (TROU,))

    def test_cadre_a_trou_dans_le_trou(self):
        """Deux trous : l'un fermé, l'autre séparé — deux ponts."""
        self._verifier(CADRE, (((20, 20), (80, 20), (80, 80), (20, 80)),
                               ((120, 120), (180, 120), (180, 180), (120, 180))))

    def test_ordre_des_sommets_indifferent(self):
        self._verifier(tuple(reversed(L)))
        self._verifier(CADRE, (tuple(reversed(TROU)),))

    def test_polygones_aleatoires(self):
        rng = random.Random(7)
        for _ in range(40):
            self._verifier(_polygone_aleatoire(rng, rng.randint(5, 30)))

    def test_meme_matiere_que_shapely(self):
        """Là où shapely 2.1 triangule, la matière couverte est la même."""
        import shapely
        if not hasattr(shapely, "constrained_delaunay_triangles"):
            self.skipTest("shapely < 2.1")
        p = Polygon(CADRE, [list(TROU)])
        ref = unary_union(list(shapely.constrained_delaunay_triangles(p).geoms))
        mienne = unary_union([Polygon(t) for t in
                              triangulation.trianguler(CADRE, (TROU,))])
        self.assertAlmostEqual(ref.symmetric_difference(mienne).area, 0.0,
                               places=6)


class SansDependance(unittest.TestCase):

    def test_jamais_de_shapely_ni_de_qt(self):
        chemin = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "triangulation.py")
        with open(chemin, encoding="utf-8") as f:
            source = f.read()
        for interdit in ("shapely", "numpy", "PySide", "QtCore"):
            self.assertNotIn(interdit, source.split('"""', 2)[2])

    def test_triangle_et_degenere(self):
        self.assertEqual(len(triangulation.trianguler(((0, 0), (1, 0), (0, 1)))), 1)
        self.assertEqual(triangulation.trianguler(((0, 0), (1, 0))), [])
        self.assertEqual(triangulation.trianguler(((0, 0), (1, 0), (2, 0))), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
