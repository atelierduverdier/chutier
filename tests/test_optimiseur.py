# -*- coding: utf-8 -*-
"""Tests de l'optimiseur de débit.

Deux familles :
- des propriétés vérifiées sur des instances aléatoires à graine fixe
  (bornes, chevauchements, trait de scie, conservation des surfaces,
  comptabilité des exemplaires) ;
- des cas exacts calculés à la main (trait de scie au millimètre près,
  débit en long, fil, chutes minimales, surcote).

Lancement : python3 tests/test_optimiseur.py
"""

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimiseur import (  # noqa: E402
    EPS, FIL_INDIFFERENT, FIL_LARGEUR, FIL_LONGUEUR,
    RAISON_INCOMPATIBLE, RAISON_PLUS_DE_PLACE, RAISON_TROP_EPAISSE,
    RAISON_TROP_GRANDE, Parametres, Piece, Planche, optimiser,
)

RAPIDE = Parametres(essais_melanges=0)


def _instance(graine):
    """Une petite instance aléatoire mais reproductible."""
    rng = random.Random(graine)
    stock = []
    for i in range(rng.randint(2, 4)):
        stock.append(Planche("p%d" % i,
                             float(rng.randrange(400, 2400, 50)),
                             float(rng.randrange(100, 600, 20)),
                             18, "bois",
                             quantite=rng.randint(1, 2),
                             chute=rng.random() < 0.3))
    pieces = []
    for i in range(rng.randint(4, 12)):
        a = float(rng.randrange(30, 1200, 10))
        b = float(rng.randrange(20, 300, 10))
        pieces.append(Piece("pc%d" % i, max(a, b), min(a, b), 18, "bois",
                            quantite=rng.randint(1, 2),
                            fil=rng.choice([FIL_LONGUEUR, FIL_INDIFFERENT])))
    return pieces, stock


class ProprietesGeometriques(unittest.TestCase):
    """Ce qui doit être vrai de TOUT résultat, quelle que soit l'instance."""

    def _verifier(self, resultat, pieces, params):
        tol = 1e-6
        for d in resultat.debits:
            rects = ([(p.x, p.y, p.dim_x, p.dim_y) for p in d.poses]
                     + [(c.x, c.y, c.dim_x, c.dim_y) for c in d.chutes])
            # dans les bornes de la planche
            for (x, y, w, h) in rects:
                self.assertGreaterEqual(x, -tol)
                self.assertGreaterEqual(y, -tol)
                self.assertLessEqual(x + w, d.planche.longueur + tol)
                self.assertLessEqual(y + h, d.planche.largeur + tol)
            # séparés par au moins un trait de scie sur un axe
            for a, b in itertools.combinations(rects, 2):
                gx = max(a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]))
                gy = max(a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]))
                self.assertGreaterEqual(max(gx, gy),
                                        params.trait_de_scie - tol,
                                        "chevauchement ou trait mangé")
            # conservation des surfaces
            self.assertGreaterEqual(d.perte, -tol)
            self.assertAlmostEqual(
                d.surface, d.surface_poses + d.surface_chutes + d.perte,
                places=3)
            # dimensions posées = pièce + surcote, dans le bon sens
            for p in d.poses:
                gx = p.piece.longueur + params.surcote_longueur
                gy = p.piece.largeur + params.surcote_largeur
                attendu = (gy, gx) if p.pivotee else (gx, gy)
                self.assertAlmostEqual(p.dim_x, attendu[0], places=6)
                self.assertAlmostEqual(p.dim_y, attendu[1], places=6)
                if d.planche.fil and p.piece.fil == FIL_LONGUEUR:
                    self.assertFalse(p.pivotee)
                if d.planche.fil and p.piece.fil == FIL_LARGEUR:
                    self.assertTrue(p.pivotee)
            # chutes au-dessus des minis
            for c in d.chutes:
                self.assertGreaterEqual(max(c.dim_x, c.dim_y),
                                        params.chute_mini_longueur - tol)
                self.assertGreaterEqual(min(c.dim_x, c.dim_y),
                                        params.chute_mini_largeur - tol)
            # coupes numérotées dans l'ordre
            self.assertEqual([c.ordre for c in d.coupes],
                             list(range(1, len(d.coupes) + 1)))
        # chaque exemplaire est posé une fois OU expliqué
        demandes = sum(p.quantite for p in pieces)
        poses = [(p.piece, p.exemplaire)
                 for d in resultat.debits for p in d.poses]
        self.assertEqual(len(poses), len(set(poses)), "exemplaire posé deux fois")
        self.assertEqual(demandes,
                         len(poses) + sum(n.exemplaires
                                          for n in resultat.non_placees))
        # bilan cohérent avec les débits
        b = resultat.bilan
        self.assertEqual(b.nb_posees, len(poses))
        self.assertAlmostEqual(b.surface_perdue,
                               sum(d.perte for d in resultat.debits),
                               places=3)
        self.assertAlmostEqual(b.surface_entamee,
                               sum(d.surface for d in resultat.debits),
                               places=3)

    def test_instances_aleatoires(self):
        for graine in range(12):
            pieces, stock = _instance(graine)
            self._verifier(optimiser(pieces, stock, RAPIDE), pieces, RAPIDE)

    def test_avec_melanges(self):
        params = Parametres(essais_melanges=3)
        pieces, stock = _instance(100)
        self._verifier(optimiser(pieces, stock, params), pieces, params)

    def test_trait_de_scie_nul(self):
        params = Parametres(trait_de_scie=0.0, essais_melanges=0)
        pieces, stock = _instance(7)
        self._verifier(optimiser(pieces, stock, params), pieces, params)

    def test_grosse_instance(self):
        rng = random.Random(42)
        stock = [Planche("p%d" % i, 2500, 600, 18, "bois", quantite=3)
                 for i in range(3)]
        pieces = [Piece("pc%d" % i,
                        float(rng.randrange(50, 1400, 10)),
                        float(rng.randrange(30, 400, 10)),
                        18, "bois", quantite=rng.randint(1, 3))
                  for i in range(30)]
        self._verifier(optimiser(pieces, stock, RAPIDE), pieces, RAPIDE)


class CasExacts(unittest.TestCase):
    """Valeurs calculées à la main, au millimètre et au mm² près."""

    def test_trait_de_scie_au_millimetre(self):
        # 100 + 3 + 100 = 203 : les deux passent tout juste
        r = optimiser([Piece("c", 100, 100, 18, "x", quantite=2)],
                      [Planche("b", 203, 100, 18, "x")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 2)
        self.assertEqual(r.non_placees, [])
        self.assertAlmostEqual(r.bilan.surface_perdue, 300.0, places=3)
        self.assertEqual(r.chutes_creees, [])

    def test_trait_de_scie_manque_un_millimetre(self):
        r = optimiser([Piece("c", 100, 100, 18, "x", quantite=2)],
                      [Planche("b", 202, 100, 18, "x")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)
        self.assertEqual(r.non_placees[0].exemplaires, 1)
        self.assertEqual(r.non_placees[0].raison, RAISON_PLUS_DE_PLACE)

    def test_debit_en_long(self):
        # 7 lames de 300 dans 2400 (6 traits de 3), la 8e ne passe pas
        r = optimiser([Piece("lame", 300, 140, 18, "x", quantite=8)],
                      [Planche("l", 2400, 140, 18, "x")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 7)
        self.assertEqual(sum(n.exemplaires for n in r.non_placees), 1)
        self.assertEqual(len(r.chutes_creees), 1)
        chute = r.chutes_creees[0]
        self.assertAlmostEqual(chute.dim_x, 279.0, places=6)
        self.assertAlmostEqual(chute.dim_y, 140.0, places=6)
        self.assertAlmostEqual(r.bilan.surface_perdue, 7 * 3 * 140.0, places=3)

    def test_remplissage_exact(self):
        r = optimiser([Piece("c", 400, 150, 18, "x")],
                      [Planche("b", 400, 150, 18, "x")], RAPIDE)
        d = r.debits[0]
        self.assertEqual((len(d.poses), len(d.coupes), len(d.chutes)),
                         (1, 0, 0))
        self.assertAlmostEqual(d.perte, 0.0, places=6)

    def test_chute_mini(self):
        pieces = [Piece("c", 400, 100, 18, "x")]
        stock = [Planche("b", 500, 100, 18, "x")]
        # reste de 97 × 100 : rebut avec les seuils par défaut (200/40)…
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual(r.chutes_creees, [])
        self.assertAlmostEqual(r.bilan.surface_perdue, 10000.0, places=3)
        # … chute réutilisable si l'on abaisse le seuil
        r = optimiser(pieces, stock,
                      Parametres(chute_mini_longueur=90, essais_melanges=0))
        self.assertEqual(len(r.chutes_creees), 1)
        self.assertAlmostEqual(r.bilan.surface_perdue, 300.0, places=3)


class SensDuFil(unittest.TestCase):

    def test_fil_longueur_interdit_la_rotation(self):
        # planche de 500 le long du fil : la pièce de 1000 n'y loge qu'en
        # travers, ce que son fil interdit
        r = optimiser([Piece("g", 1000, 50, 18, "x")],
                      [Planche("A", 500, 1200, 18, "x")], RAPIDE)
        self.assertEqual(r.debits, [])
        self.assertEqual(r.non_placees[0].raison, RAISON_TROP_GRANDE)

    def test_fil_indifferent_autorise_la_rotation(self):
        r = optimiser([Piece("g", 1000, 50, 18, "x", fil=FIL_INDIFFERENT)],
                      [Planche("A", 500, 1200, 18, "x")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)
        self.assertTrue(r.debits[0].poses[0].pivotee)

    def test_panneau_sans_fil(self):
        r = optimiser([Piece("g", 1000, 50, 18, "x")],
                      [Planche("P", 500, 1200, 18, "x", fil=False)], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)

    def test_fil_largeur(self):
        r = optimiser([Piece("g", 300, 80, 18, "x", fil=FIL_LARGEUR)],
                      [Planche("A", 1200, 400, 18, "x")], RAPIDE)
        pose = r.debits[0].poses[0]
        self.assertTrue(pose.pivotee)
        self.assertAlmostEqual(pose.dim_x, 80.0, places=6)


class StockEtChutes(unittest.TestCase):

    def test_les_chutes_passent_avant_les_neuves(self):
        r = optimiser(
            [Piece("t", 550, 180, 18, "x")],
            [Planche("neuve", 2400, 200, 18, "x"),
             Planche("ch", 600, 200, 18, "x", chute=True)], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)
        self.assertTrue(r.debits[0].planche.chute)
        self.assertAlmostEqual(r.bilan.surface_neuve_entamee, 0.0, places=3)
        self.assertEqual(r.bilan.nb_chutes_consommees, 1)

    def test_chute_reinjectee_au_stock(self):
        r = optimiser([Piece("lame", 300, 140, 18, "x", quantite=7)],
                      [Planche("l", 2400, 140, 18, "x")], RAPIDE)
        planche = r.chutes_creees[0].en_planche("reste de l")
        self.assertTrue(planche.chute)
        r2 = optimiser([Piece("cale", 250, 140, 18, "x")], [planche], RAPIDE)
        self.assertEqual(r2.bilan.nb_posees, 1)
        self.assertEqual(r2.bilan.nb_chutes_consommees, 1)


class MatiereEtEpaisseur(unittest.TestCase):

    def test_epaisseur_incompatible(self):
        r = optimiser([Piece("c", 100, 50, 18, "sapin")],
                      [Planche("b", 500, 200, 12, "sapin")], RAPIDE)
        self.assertEqual(r.non_placees[0].raison, RAISON_TROP_EPAISSE)

    def test_planche_plus_epaisse_convient(self):
        # le brut se rabote : une planche de 30 fournit une pièce de 18
        r = optimiser([Piece("c", 100, 50, 18, "sapin")],
                      [Planche("b", 500, 200, 30, "sapin")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)

    def test_deux_finitions_sur_le_meme_brut(self):
        # deux pièces d'épaisseurs différentes, toutes deux plus minces
        # que le seul brut disponible : rien n'empêche de les tirer de
        # la même planche, chacune rabotée à sa propre cote ensuite
        r = optimiser(
            [Piece("fine", 100, 50, 8, "sapin"),
             Piece("epaisse", 100, 50, 20, "sapin")],
            [Planche("b", 500, 200, 30, "sapin")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 2)
        self.assertEqual(len(r.debits), 1)

    def test_trop_epaisse_meme_avec_plusieurs_brut(self):
        r = optimiser([Piece("c", 100, 50, 50, "sapin")],
                      [Planche("b1", 500, 200, 18, "sapin"),
                       Planche("b2", 500, 200, 30, "sapin")], RAPIDE)
        self.assertEqual(r.non_placees[0].raison, RAISON_TROP_EPAISSE)

    def test_matiere_normalisee_et_tolerance(self):
        r = optimiser([Piece("c", 100, 50, 18.05, "  Sapin ")],
                      [Planche("b", 500, 200, 18.0, "sapin")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)

    def test_matiere_differente(self):
        r = optimiser([Piece("c", 100, 50, 18, "chêne")],
                      [Planche("b", 500, 200, 18, "sapin")], RAPIDE)
        self.assertEqual(r.non_placees[0].raison, RAISON_INCOMPATIBLE)

    def test_lots_separes(self):
        r = optimiser(
            [Piece("c1", 100, 50, 18, "chêne"),
             Piece("c2", 100, 50, 18, "sapin")],
            [Planche("b1", 500, 200, 18, "chêne"),
             Planche("b2", 500, 200, 18, "sapin")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 2)
        for d in r.debits:
            for p in d.poses:
                self.assertEqual(p.piece.matiere.strip().casefold(),
                                 d.planche.matiere.strip().casefold())


class Divers(unittest.TestCase):

    def test_surcote(self):
        params = Parametres(surcote_longueur=10, surcote_largeur=5,
                            essais_melanges=0)
        r = optimiser([Piece("c", 100, 50, 18, "x")],
                      [Planche("b", 300, 100, 18, "x")], params)
        pose = r.debits[0].poses[0]
        self.assertAlmostEqual(pose.dim_x, 110.0, places=6)
        self.assertAlmostEqual(pose.dim_y, 55.0, places=6)
        r = optimiser([Piece("c", 100, 50, 18, "x")],
                      [Planche("b", 105, 52, 18, "x")], params)
        self.assertEqual(r.non_placees[0].raison, RAISON_TROP_GRANDE)

    def test_quantites(self):
        r = optimiser([Piece("c", 100, 50, 18, "x", quantite=3)],
                      [Planche("b", 500, 200, 18, "x")], RAPIDE)
        exemplaires = sorted(p.exemplaire
                             for d in r.debits for p in d.poses)
        self.assertEqual(exemplaires, [1, 2, 3])

    def test_deterministe(self):
        pieces, stock = _instance(5)
        a = optimiser(pieces, stock).texte()
        b = optimiser(pieces, stock).texte()
        self.assertEqual(a, b)

    def test_texte(self):
        pieces, stock = _instance(3)
        texte = optimiser(pieces, stock, RAPIDE).texte()
        self.assertIn("Feuille de débit", texte)
        self.assertIn("Planche 1", texte)

    def test_validation(self):
        with self.assertRaises(ValueError):
            optimiser([Piece("c", 0, 50)], [Planche("b", 500, 200)])
        with self.assertRaises(ValueError):
            optimiser([Piece("c", 100, 50, fil="travers")],
                      [Planche("b", 500, 200)])
        with self.assertRaises(ValueError):
            optimiser([Piece("c", 100, 50)],
                      [Planche("b", 500, 200, quantite=0)])
        with self.assertRaises(ValueError):
            optimiser([Piece("c", 100, 50)], [Planche("b", 500, 200)],
                      Parametres(trait_de_scie=-1))

    def test_jamais_de_qt_dans_le_coeur(self):
        # règle de couches : le cœur doit rester important sans interface
        chemin = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "optimiseur.py")
        with open(chemin, encoding="utf-8") as f:
            source = f.read()
        for interdit in ("PySide", "PyQt", "QtWidgets", "QtCore", "QtGui"):
            self.assertNotIn(interdit, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
