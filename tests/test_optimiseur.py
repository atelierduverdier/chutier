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
    RAISON_TROP_GRANDE, Achat, Parametres, Piece, Planche, optimiser,
    _nombre_de_lames, _plus_large_compatible,
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


class PiecesComposables(unittest.TestCase):

    def test_nombre_de_lames_arithmetique(self):
        # 422 de large, brut a 200 max, 3 mm par joint -> 3 lames de
        # 142,667 (verifie : 3 lames - 2 joints = la largeur d'origine)
        n = _nombre_de_lames(422, 200, 3)
        self.assertEqual(n, 3)
        largeur_lame = (422 + (n - 1) * 3) / n
        self.assertAlmostEqual(n * largeur_lame - (n - 1) * 3, 422)
        self.assertLessEqual(largeur_lame, 200)

    def test_nombre_de_lames_une_seule_si_ca_loge(self):
        self.assertEqual(_nombre_de_lames(180, 200, 3), 1)

    def test_nombre_de_lames_garde_fou(self):
        # aucune largeur utile : ne boucle pas indefiniment
        self.assertGreater(_nombre_de_lames(1000, 0, 3), 50)

    def test_plus_large_compatible_ignore_matiere_et_epaisseur(self):
        piece = Piece("p", 100, 50, 18, "sapin")
        stock = [Planche("b1", 500, 300, 18, "chêne"),   # mauvaise matière
                Planche("b2", 500, 120, 12, "sapin"),    # trop mince
                Planche("b3", 500, 180, 18, "sapin")]
        self.assertEqual(_plus_large_compatible(piece, stock, RAPIDE), 180)

    def test_pas_decompose_si_ca_loge_deja(self):
        # composable mais tient dans une seule planche : aucun joint
        r = optimiser(
            [Piece("panneau", 650, 180, 18, "sapin", composable=True)],
            [Planche("b", 4000, 200, 18, "sapin")], RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)
        self.assertNotIn("lame", r.debits[0].poses[0].piece.reference)

    def test_decompose_en_plusieurs_lames(self):
        # 422 de large sur un brut de 200 -> 3 lames collees, comme le
        # Panneau_Haut d'un vrai projet (porte-hammam, 29/08/2026)
        r = optimiser(
            [Piece("Panneau_Haut", 650, 422, 18, "sapin", composable=True)],
            [Planche("b", 4000, 200, 18, "sapin")], RAPIDE)
        self.assertEqual(len(r.non_placees), 0)
        self.assertEqual(r.bilan.nb_posees, 3)
        references = {p.piece.reference for d in r.debits for p in d.poses}
        self.assertEqual(references, {"Panneau_Haut (lame 1/3)",
                                      "Panneau_Haut (lame 2/3)",
                                      "Panneau_Haut (lame 3/3)"})

    def test_fil_largeur_non_decompose(self):
        # sur FIL_LARGEUR c'est la longueur de la piece qui court le long
        # de la largeur de la planche (pivotee) : 800 > 200, trop grande,
        # et la largeur n'est pas l'axe a elargir par collage ici
        r = optimiser(
            [Piece("p", 800, 100, 18, "sapin", fil=FIL_LARGEUR,
                  composable=True)],
            [Planche("b", 4000, 200, 18, "sapin")], RAPIDE)
        self.assertEqual(r.non_placees[0].raison, RAISON_TROP_GRANDE)

    def test_non_composable_reste_non_placee(self):
        # meme piece, meme stock, sans l'indicateur : comportement inchange
        r = optimiser(
            [Piece("Panneau_Haut", 650, 422, 18, "sapin")],
            [Planche("b", 4000, 200, 18, "sapin")], RAPIDE)
        self.assertEqual(r.non_placees[0].raison, RAISON_TROP_GRANDE)

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


class ProfilsDeCatalogue(unittest.TestCase):
    """``Planche(illimite=True)`` : un profil qu'on peut acheter, pas des
    planches déjà en atelier — le solveur choisit lui-même combien en
    prendre, ``Resultat.achats`` compte ensuite quoi acheter."""

    def test_achete_juste_ce_qu_il_faut(self):
        # 5 pieces de 1000, planches de 2400 -> 3 planches (2 par planche)
        pieces = [Piece("p", 1000, 100, 18, "sapin", quantite=5)]
        stock = [Planche("2400x100", 2400, 100, 18, "sapin", illimite=True)]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual(len(r.non_placees), 0)
        self.assertEqual(r.achats, [
            Achat("2400x100", 2400, 100, 18, "sapin", 3)])

    def test_repartit_entre_deux_profils_par_epaisseur(self):
        # comme un vrai achat (29/08/2026) : 175x65 et 200x30 en catalogue,
        # une pièce à 50 ne peut venir QUE du 65 ; une à 20, des deux —
        # mais y aller par le plus mince suffit (moins de gâchis d'épaisseur)
        pieces = [
            Piece("epaisse", 1000, 100, 50, "sapin", quantite=2),
            Piece("fine", 1000, 100, 20, "sapin", quantite=2),
        ]
        stock = [
            Planche("4000x175x65", 4000, 175, 65, "sapin", illimite=True),
            Planche("4000x200x30", 4000, 200, 30, "sapin", illimite=True),
        ]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual(len(r.non_placees), 0)
        references = {a.reference for a in r.achats}
        self.assertIn("4000x175x65", references)          # les 50 n'ont que lui
        for d in r.debits:
            for p in d.poses:
                if p.piece.reference == "epaisse":
                    self.assertEqual(d.planche.reference, "4000x175x65")

    def test_achats_ignore_les_chutes(self):
        pieces = [Piece("p", 300, 100, 18, "sapin", quantite=1)]
        stock = [Planche("chute", 400, 120, 18, "sapin", chute=True),
                Planche("catalogue", 2400, 200, 18, "sapin", illimite=True)]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual(len(r.achats), 0)   # la chute a suffi, rien a acheter

    def test_illimite_sans_effet_sur_une_chute(self):
        # illimite ne veut rien dire pour une chute : deja possedee, on
        # n'en achete jamais davantage qu'il n'en existe reellement
        pieces = [Piece("p", 1000, 100, 18, "sapin", quantite=5)]
        stock = [Planche("chute", 1000, 100, 18, "sapin", quantite=1,
                         chute=True, illimite=True)]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual(r.bilan.nb_posees, 1)
        self.assertEqual(len(r.non_placees), 1)
        self.assertEqual(r.non_placees[0].exemplaires, 4)

    def test_sans_prix_le_moins_de_rabotage_perdu_gagne(self):
        # prix a 0 partout (le defaut) : sans savoir lequel coute le plus,
        # le choix se fait par le moins de rabotage perdu — une piece a 20
        # gaspille 45 sur un brut a 65, seulement 10 sur un brut a 30, le
        # 200x30 doit donc l'emporter meme si sa surface est plus grande
        # (signale par Christophe : "mes planches de 32mm ne sont jamais
        # prises", 30/08/2026 — l'ancien depart par la seule surface
        # ecartait a tort tout brut plus large mais mieux ajuste)
        pieces = [Piece("p", 1000, 100, 20, "sapin", quantite=3)]
        stock = [Planche("175x65", 4000, 175, 65, "sapin", illimite=True),
                Planche("200x30", 4000, 200, 30, "sapin", illimite=True)]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual({a.reference for a in r.achats}, {"200x30"})

    def test_sans_prix_la_surface_depatage_a_gaspillage_egal(self):
        # a gaspillage de rabotage identique (0 pour les deux : la piece
        # loge pile), la plus petite surface neuve tranche, comme avant
        pieces = [Piece("p", 1000, 100, 18, "sapin", quantite=3)]
        stock = [Planche("petit", 4000, 175, 18, "sapin", illimite=True),
                Planche("grand", 4000, 200, 18, "sapin", illimite=True)]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual({a.reference for a in r.achats}, {"petit"})

    def test_prix_depart_le_choix_entre_profils_epaisseur_compatibles(self):
        # les deux profils logent la piece (20 <= 65 et 20 <= 30) : sans
        # prix, la plus petite surface (175) gagnerait — avec un prix qui
        # dit le contraire, c'est le moins cher qui doit l'emporter
        pieces = [Piece("p", 1000, 100, 20, "sapin", quantite=3)]
        cher = Planche("cher_mais_petit", 4000, 175, 65, "sapin",
                       illimite=True, prix=100.0)
        bon_marche = Planche("bon_marche_mais_large", 4000, 200, 30, "sapin",
                             illimite=True, prix=1.0)
        r = optimiser(pieces, [cher, bon_marche], RAPIDE)
        self.assertEqual(len(r.non_placees), 0)
        self.assertEqual({a.reference for a in r.achats},
                         {"bon_marche_mais_large"})

    def test_prix_minimise_le_cout_total_pas_seulement_la_surface(self):
        # cas a deux epaisseurs de besoin, comme un vrai achat
        # (29/08/2026) : le 65 cher ne doit servir qu'aux pieces qui n'ont
        # pas le choix, le reste va au 30 moins cher
        pieces = [
            Piece("epaisse", 1000, 100, 50, "sapin", quantite=2),
            Piece("fine", 1000, 100, 20, "sapin", quantite=6),
        ]
        stock = [
            Planche("4000x175x65", 4000, 175, 65, "sapin", illimite=True,
                    prix=35.0),
            Planche("4000x200x30", 4000, 200, 30, "sapin", illimite=True,
                    prix=12.0),
        ]
        r = optimiser(pieces, stock, RAPIDE)
        self.assertEqual(len(r.non_placees), 0)
        achats = {a.reference: a.nombre for a in r.achats}
        self.assertEqual(achats, {"4000x175x65": 1, "4000x200x30": 2})
        # moins cher que si tout etait force dans le seul profil epais
        cout = achats["4000x175x65"] * 35.0 + achats["4000x200x30"] * 12.0
        self.assertLess(cout, 8 * 35.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
