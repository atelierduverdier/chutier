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
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contours_svg  # noqa: E402
from optimiseur import (  # noqa: E402
    FIL_INDIFFERENT, FIL_LONGUEUR, Parametres, Piece, Planche, optimiser,
)

try:
    from shapely import affinity
    from shapely.geometry import Point, Polygon, box
    import imbrication
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

    def test_la_longueur_de_fraisage_est_celle_des_contours(self):
        cadre = ((0, 0), (100, 0), (100, 100), (0, 100))
        trou = ((20, 20), (80, 20), (80, 80), (20, 80))
        pieces = [Piece("cadre", 100, 100, 15, "cp", 1, FIL_INDIFFERENT,
                        contour=cadre, trous=(trou,)),
                  Piece("cale", 60, 30, 15, "cp", 1)]
        stock = [Planche("cp", 300, 200, 15, "cp", 1, fil=False)]
        r = optimiser(pieces, stock, RAPIDE)
        d = r.debits[0]
        self.assertAlmostEqual(d.longueur_fraisage, 400 + 240 + 180, places=3)
        self.assertAlmostEqual(r.bilan.longueur_fraisage, d.longueur_fraisage)
        scie = optimiser([Piece("cale", 60, 30, 15, "cp", 1)], stock, RAPIDE)
        self.assertEqual(scie.debits[0].longueur_fraisage, 0.0)

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

    def test_une_piece_s_imbrique_dans_le_trou_d_une_autre(self):
        """Un cadre de 200 × 200 évidé à 140 × 140 : avec 8 d'écart, deux
        carrés de 50 (50 + 8 + 50 = 108 ≤ 124) tiennent dans son trou —
        et c'est là que le NFP les met, la boîte posée n'y grandit pas."""
        cadre = ((0, 0), (200, 0), (200, 200), (0, 200))
        trou = ((30, 30), (170, 30), (170, 170), (30, 170))
        pieces = [Piece("cadre", 200, 200, 15, "cp", 1, FIL_INDIFFERENT,
                        contour=cadre, trous=(trou,)),
                  Piece("carre", 50, 50, 15, "cp", 4)]
        stock = [Planche("cp", 400, 300, 15, "cp", 1, fil=False)]
        params = Parametres(essais_melanges=0, processus=1)
        r = optimiser(pieces, stock, params)
        self.assertEqual(r.bilan.nb_non_placees, 0)
        d = r.debits[0]
        cadre_pose = [p for p in d.poses if p.piece.reference == "cadre"][0]
        self.assertEqual(len(cadre_pose.trous), 1)
        materiau = Polygon(cadre_pose.contour, [cadre_pose.trous[0]])
        trou_pose = Polygon(cadre_pose.trous[0])
        dedans = [p for p in d.poses if p.piece.reference == "carre"
                  and trou_pose.contains(Polygon(p.contour))]
        self.assertGreaterEqual(len(dedans), 2, "aucun carré dans le trou")
        for p in dedans:
            self.assertGreaterEqual(materiau.distance(Polygon(p.contour)),
                                    params.ecart_contours - 0.5)
        self.assertAlmostEqual(cadre_pose.aire, 200 * 200 - 140 * 140, places=3)

    def test_export_svg_garde_les_trous(self):
        cadre = ((0, 0), (100, 0), (100, 100), (0, 100))
        trou = ((20, 20), (80, 20), (80, 80), (20, 80))
        pieces = [Piece("cadre", 100, 100, 15, "cp", 1, FIL_INDIFFERENT,
                        contour=cadre, trous=(trou,))]
        stock = [Planche("cp", 200, 200, 15, "cp", 1, fil=False)]
        r = optimiser(pieces, stock, RAPIDE)
        chemin = os.path.join(tempfile.mkdtemp(), "cadre.svg")
        contours_svg.ecrire_svg(chemin, r.debits[0], 1)
        formes, _ = contours_svg.formes_depuis_svg(chemin)
        relu = [f for f in formes if f["nom"].startswith("cadre")][0]
        self.assertEqual(len(relu["trous"]), 1)
        self.assertAlmostEqual(abs(contours_svg._aire_signee(relu["trous"][0])),
                               60 * 60, places=2)

    def test_contour_trop_court(self):
        with self.assertRaises(ValueError):
            optimiser([Piece("x", 10, 10, 18, "cp", contour=((0, 0), (1, 1)))],
                      [Planche("cp", 100, 100, 18, "cp")])

    def test_pas_de_rotation_invalide(self):
        with self.assertRaises(ValueError):
            optimiser([Piece("x", 10, 10, 18, "cp")],
                      [Planche("cp", 100, 100, 18, "cp")],
                      Parametres(pas_rotation=70))


@unittest.skipUnless(SHAPELY, "shapely absent")
class NoFitPolygon(unittest.TestCase):
    """Le NFP de B autour de A est la région des positions de B (son
    coin bas-gauche) où elle recouvre A."""

    def test_deux_rectangles(self):
        """Autour d'un 40 × 30, un 20 × 10 recouvre pour tout coin dans
        [−20, 40] × [−10, 30] — au surcroît de simplification près (deux
        dixièmes de chaque côté)."""
        formes = imbrication._Formes(Parametres(ecart_contours=0))
        ca, *_ = formes.variante(Piece("a", 40, 30, 18, "cp"), 0)
        cb, *_ = formes.variante(Piece("b", 20, 10, 18, "cp"), 0)
        nfp = formes.nfp(ca, cb)
        for lu, attendu in zip(nfp.bounds, (-20, -10, 40, 30)):
            self.assertAlmostEqual(lu, attendu, delta=0.5)

    def test_concave_contre_convexe_tirages(self):
        """Point dans le NFP ⇔ recouvrement, sur des positions tirées au
        hasard : c'est la définition, et la triangulation ne doit rien y
        changer."""
        formes = imbrication._Formes(Parametres(ecart_contours=0))
        cl, _, sl, _, _ = formes.variante(
            Piece("L", 80, 80, 18, "cp", contour=L), 0)
        cr, _, sr, _, _ = formes.variante(
            Piece("rond", 60, 60, 18, "cp", contour=ROND), 90)
        nfp = formes.nfp(cl, cr)
        rng = random.Random(1)
        for _ in range(1500):
            tx, ty = rng.uniform(-70, 90), rng.uniform(-70, 90)
            dedans = nfp.contains(Point(tx, ty))
            recouvre = sl.intersection(affinity.translate(sr, tx, ty)).area > 1e-6
            self.assertEqual(dedans, recouvre, "en (%.1f, %.1f)" % (tx, ty))

    def test_l_ecart_elargit_le_nfp(self):
        avec = imbrication._Formes(Parametres(ecart_contours=8))
        sans = imbrication._Formes(Parametres(ecart_contours=0))
        for f in (avec, sans):
            f.variante(Piece("a", 40, 30, 18, "cp"), 0)
            f.variante(Piece("b", 20, 10, 18, "cp"), 0)
        ca = (("r", 40.0, 30.0), 0)
        cb = (("r", 20.0, 10.0), 0)
        self.assertGreater(avec.nfp(ca, cb).area, sans.nfp(ca, cb).area)
        # à 8 juste de l'écart, un point à 7,5 est bloqué, à 8,5 libre
        self.assertTrue(avec.nfp(ca, cb).contains(Point(40 + 7.5, 10)))
        self.assertFalse(avec.nfp(ca, cb).contains(Point(40 + 8.5, 10)))

    def test_le_repli_de_triangulation_donne_le_meme_nfp(self):
        """Sans shapely 2.1 (le navigateur), la triangulation maison
        doit produire le même NFP, donc le même plan."""
        from unittest import mock
        cadre = ((0, 0), (200, 0), (200, 200), (0, 200))
        trou = ((30, 30), (170, 30), (170, 170), (30, 170))
        pieces = [Piece("cadre", 200, 200, 15, "cp", 1, FIL_INDIFFERENT,
                        contour=cadre, trous=(trou,)),
                  Piece("L", 80, 80, 15, "cp", 3, FIL_INDIFFERENT, contour=L),
                  Piece("rond", 60, 60, 15, "cp", 2, FIL_INDIFFERENT,
                        contour=ROND)]
        stock = [Planche("cp", 500, 400, 15, "cp", 1, fil=False)]
        params = Parametres(essais_melanges=0, processus=1)

        def vider():
            imbrication._NFPS.clear()
            imbrication._CADRES.clear()
            imbrication._VARIANTES.clear()
        vider()
        avec = optimiser(pieces, stock, params)
        vider()
        with mock.patch.object(imbrication, "TRIANGULATION_SHAPELY", False):
            sans = optimiser(pieces, stock, params)
        vider()
        self.assertEqual(avec.bilan.nb_posees, sans.bilan.nb_posees)
        self.assertEqual(len(avec.debits), len(sans.debits))
        for a, b in zip(avec.debits[0].poses, sans.debits[0].poses):
            self.assertEqual(a.piece.reference, b.piece.reference)
            self.assertAlmostEqual(a.x, b.x, delta=0.05)
            self.assertAlmostEqual(a.y, b.y, delta=0.05)
            self.assertEqual(a.angle, b.angle)

    def test_parallele_egale_sequentiel(self):
        stock = [Planche("cp", 600, 400, 18, "cp", 3, fil=False)]
        seq = optimiser(_pieces(), stock, Parametres(essais_melanges=2,
                                                     processus=1))
        par = optimiser(_pieces(), stock, Parametres(essais_melanges=2,
                                                     processus=0))
        self.assertEqual(seq.texte(), par.texte())

    def test_les_sommets_de_la_region_libre_touchent(self):
        """Chaque pièce posée touche un voisin ou le bord, à l'écart
        près : c'est la propriété du NFP, et ce qui rend le plan serré."""
        params = Parametres(essais_melanges=0, processus=1)
        stock = [Planche("cp", 600, 400, 18, "cp", 1, fil=False)]
        r = optimiser(_pieces(), stock, params)
        d = r.debits[0]
        bord = box(0, 0, 600, 400).buffer(-params.marge_bord, join_style="mitre")
        polys = [Polygon(p.contour) for p in d.poses]
        for i, poly in enumerate(polys):
            distances = [poly.distance(q) for j, q in enumerate(polys) if j != i]
            distances.append(bord.exterior.distance(poly))
            self.assertLessEqual(min(distances), params.ecart_contours + 0.5,
                                 "« %s » flotte" % d.poses[i].piece.reference)


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

    def test_le_trou_devient_un_trou_de_la_forme(self):
        formes, _ = contours_svg.formes_depuis_svg(self.chemin)
        anneau = formes[3]
        self.assertEqual(len(anneau["contour"]), 4)
        self.assertAlmostEqual(anneau["longueur"], 60, places=3)
        self.assertEqual(len(anneau["trous"]), 1)
        trou = anneau["trous"][0]
        # déplacé comme son contour : le trou de 40 × 40 est à 10 du bord
        self.assertAlmostEqual(min(p[0] for p in trou), 10, places=3)
        self.assertAlmostEqual(max(p[0] for p in trou), 50, places=3)
        for forme in formes[:3]:
            self.assertEqual(forme["trous"], ())

    def test_sens_direct(self):
        formes, _ = contours_svg.formes_depuis_svg(self.chemin)
        for forme in formes:
            self.assertGreater(contours_svg._aire_signee(forme["contour"]), 0)


@unittest.skipUnless(SHAPELY, "shapely absent")
class LectureSvgInkscape(unittest.TestCase):
    """Un fichier réellement écrit par Inkscape (1.4, avec ses espaces de
    noms sodipodi/inkscape, ses ``id`` automatiques, ses transformations)
    — c'est ce qu'apportent les gens, pas un SVG écrit à la main."""

    CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "inkscape-exemple.svg")

    def test_les_cinq_formes_reviennent_en_millimetres(self):
        formes, avertissements = contours_svg.formes_depuis_svg(self.CHEMIN)
        self.assertEqual(avertissements, [])
        par_nom = {f["nom"]: f for f in formes}
        self.assertEqual(set(par_nom), {"rect1", "path1", "circle2", "path2",
                                        "ellipse2"})
        # viewBox 210 × 148 pour 210 × 148 mm : l'unité utilisateur EST le mm
        self.assertAlmostEqual(par_nom["rect1"]["longueur"], 60.0, places=2)
        self.assertAlmostEqual(par_nom["rect1"]["largeur"], 40.0, places=2)
        # le rectangle tourné de 30° : sa boîte est 40·cos30 + 30·sin30
        self.assertAlmostEqual(par_nom["path1"]["longueur"],
                               40 * math.cos(math.radians(30))
                               + 30 * math.sin(math.radians(30)), places=1)
        self.assertAlmostEqual(par_nom["circle2"]["longueur"], 40.0, places=2)
        self.assertGreater(len(par_nom["circle2"]["contour"]), 24)
        self.assertEqual(len(par_nom["path2"]["trous"]), 1)     # le cadre
        self.assertAlmostEqual(par_nom["ellipse2"]["largeur"], 16.0, places=1)


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
