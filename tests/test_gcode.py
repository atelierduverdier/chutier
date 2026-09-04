# -*- coding: utf-8 -*-
"""Le G-code sort d'ici et va droit dans une machine qui coupe du bois :
on ne le juge pas sur son texte, on le REJOUE. Un simulateur relit le
programme mot à mot, tient l'état modal (G0/G1, position, avance) et rend
la liste des déplacements ; les tests portent alors sur ce que la fraise
fait, pas sur ce que le fichier dit.

Lancement : python3 tests/test_gcode.py
"""

import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gcode  # noqa: E402
from optimiseur import (  # noqa: E402
    FIL_INDIFFERENT, Parametres, Piece, Planche, optimiser,
)

CARRE = ((0, 0), (100, 0), (100, 100), (0, 100))
TROU = ((30, 30), (70, 30), (70, 70), (30, 70))
RAPIDE = Parametres(essais_melanges=0, processus=1)


# ---------------------------------------------------------------------------
# Le simulateur
# ---------------------------------------------------------------------------

class Deplacement:
    """Un mouvement de la machine, tel qu'il aura lieu."""

    __slots__ = ("rapide", "de", "a", "avance", "ligne", "commentaire")

    def __init__(self, rapide, de, a, avance, ligne, commentaire):
        self.rapide = rapide
        self.de = de
        self.a = a
        self.avance = avance
        self.ligne = ligne
        self.commentaire = commentaire

    @property
    def longueur(self):
        return math.dist(self.de, self.a)

    @property
    def coupe(self):
        """Un déplacement qui enlève de la matière : en avance, sous le
        dessus de la planche."""
        return not self.rapide and (self.de[2] < -1e-9 or self.a[2] < -1e-9)


def rejouer(texte):
    """(déplacements, mots) du programme. ``mots`` garde les codes M et G
    non modaux dans l'ordre, pour vérifier l'en-tête et la fin."""
    position = [0.0, 0.0, 0.0]
    rapide = True
    avance = None
    commentaire = ""
    deplacements = []
    mots = []
    for numero, brute in enumerate(texte.splitlines(), 1):
        ligne = brute.strip()
        if not ligne:
            continue
        if ligne.startswith("("):
            if not ligne.endswith(")"):
                raise AssertionError("commentaire non refermé ligne %d : %s"
                                     % (numero, ligne))
            commentaire = ligne[1:-1]
            continue
        if "(" in ligne or ")" in ligne:
            raise AssertionError("parenthèse en plein code ligne %d : %s"
                                 % (numero, ligne))
        for mot in re.findall(r"[A-Z]-?\d*\.?\d*", ligne.upper()):
            lettre, valeur = mot[0], mot[1:]
            if lettre == "G" and valeur in ("0", "00"):
                rapide = True
            elif lettre == "G" and valeur in ("1", "01"):
                rapide = False
            elif lettre in "GM":
                mots.append(mot)
            elif lettre == "F":
                avance = float(valeur)
            elif lettre == "T":
                mots.append(mot)
        depart = tuple(position)
        bouge = False
        for axe, indice in (("X", 0), ("Y", 1), ("Z", 2)):
            trouve = re.search(axe + r"(-?\d*\.?\d+)", ligne.upper())
            if trouve:
                position[indice] = float(trouve.group(1))
                bouge = True
        if bouge:
            deplacements.append(Deplacement(rapide, depart, tuple(position),
                                            avance, numero, commentaire))
    return deplacements, mots


def _debit_carre(epaisseur=15.0, trou=True):
    piece = Piece("cadre", 100, 100, epaisseur, "cp", 1, FIL_INDIFFERENT,
                  contour=CARRE, trous=(TROU,) if trou else ())
    stock = [Planche("cp", 400, 300, epaisseur, "cp", 1, fil=False)]
    return optimiser([piece], stock, RAPIDE).debits[0]


# ---------------------------------------------------------------------------

class Simulateur(unittest.TestCase):
    """Le simulateur doit être digne de confiance avant les tests."""

    def test_il_lit_les_modes_et_les_positions(self):
        deplacements, mots = rejouer(
            "(essai)\nG21 G90\nG0 X10 Y20\nG1 Z-3 F400\nG1 X30\nM2\n")
        self.assertEqual([d.rapide for d in deplacements],
                         [True, False, False])
        self.assertEqual(deplacements[0].a, (10.0, 20.0, 0.0))
        self.assertEqual(deplacements[1].a, (10.0, 20.0, -3.0))
        self.assertEqual(deplacements[2].a, (30.0, 20.0, -3.0))
        self.assertEqual(deplacements[2].avance, 400.0)
        self.assertIn("M2", mots)

    def test_il_refuse_un_commentaire_ouvert(self):
        with self.assertRaises(AssertionError):
            rejouer("(sans fin\nG0 X1\n")


class Geometrie(unittest.TestCase):

    def test_le_parcours_est_decale_du_rayon(self):
        """Une fraise qui suit le contour enlève son rayon de chaque côté :
        la pièce sortirait trop petite d'un diamètre entier."""
        debit = _debit_carre()
        for diametre in (4.0, 6.0, 10.0):
            texte, _, _ = gcode.programme(
                debit, gcode.Reglages(diametre_fraise=diametre, attaches=0))
            deplacements, _ = rejouer(texte)
            rayon = diametre / 2.0
            pose = debit.poses[0]
            # seulement les points ATTEINTS : le « de » du premier
            # déplacement est la position d'avant, hors du contour
            dehors = [d for d in deplacements if d.commentaire == "tour de piece"]
            xs = [d.a[0] for d in dehors]
            ys = [d.a[1] for d in dehors]
            # le tour passe à un rayon À L'EXTÉRIEUR de la pièce
            self.assertAlmostEqual(min(xs), pose.x - rayon, places=2)
            self.assertAlmostEqual(max(xs), pose.x + pose.dim_x + rayon,
                                   places=2)
            self.assertAlmostEqual(min(ys), pose.y - rayon, places=2)
            self.assertAlmostEqual(max(ys), pose.y + pose.dim_y + rayon,
                                   places=2)
            # et le trou à un rayon À L'INTÉRIEUR
            trou = [d for d in deplacements if d.commentaire == "trou"]
            tx = [d.a[0] for d in trou]
            self.assertAlmostEqual(min(tx), pose.x + 30 + rayon, places=2)
            self.assertAlmostEqual(max(tx), pose.x + 70 - rayon, places=2)

    def test_le_sens_de_rotation_suit_le_reglage(self):
        """En avalant : le tour en horaire, les trous en anti-horaire. Se
        tromper de sens, sur du contreplaqué, c'est un chant éclaté."""
        debit = _debit_carre()
        for sens, tour_horaire in (("avalant", True), ("opposition", False)):
            texte, _, _ = gcode.programme(
                debit, gcode.Reglages(sens=sens, attaches=0, longueur_rampe=0))
            deplacements, _ = rejouer(texte)
            for commentaire, attendu in (("tour de piece", tour_horaire),
                                         ("trou", not tour_horaire)):
                points = [d.a[:2] for d in deplacements
                          if d.commentaire == commentaire and d.coupe]
                self.assertGreater(len(points), 3)
                aire = sum(points[i][0] * points[(i + 1) % len(points)][1]
                           - points[(i + 1) % len(points)][0] * points[i][1]
                           for i in range(len(points)))
                self.assertEqual(aire < 0, attendu,
                                 "%s en %s : mauvais sens" % (commentaire, sens))

    def test_les_trous_se_percent_avant_le_tour(self):
        """L'inverse évide une pièce déjà libre, qui a bougé."""
        texte, _, _ = gcode.programme(_debit_carre())
        ordre = [c for c in re.findall(r"^\((trou|tour de piece)\)$", texte,
                                       re.M)]
        self.assertEqual(ordre, ["trou", "tour de piece"])

    def test_un_trou_plus_petit_que_la_fraise_est_signale(self):
        piece = Piece("bague", 100, 100, 15, "cp", 1, FIL_INDIFFERENT,
                      contour=CARRE,
                      trous=(((48, 48), (52, 48), (52, 52), (48, 52)),))
        debit = optimiser([piece], [Planche("cp", 400, 300, 15, "cp", 1,
                                            fil=False)], RAPIDE).debits[0]
        texte, avertissements, _ = gcode.programme(
            debit, gcode.Reglages(diametre_fraise=6))
        self.assertTrue(any("plus petit que la fraise" in a
                            for a in avertissements))
        self.assertIn("ATTENTION", texte)
        self.assertNotIn("(trou)", texte)


class Passes(unittest.TestCase):

    def test_on_descend_par_passes_et_on_traverse(self):
        reglages = gcode.Reglages(profondeur_passe=4, depassement=0.5,
                                  attaches=0)
        texte, _, _ = gcode.programme(_debit_carre(epaisseur=15))
        texte, _, _ = gcode.programme(_debit_carre(epaisseur=15), reglages)
        deplacements, _ = rejouer(texte)
        fonds = sorted({round(d.a[2], 3) for d in deplacements if d.coupe})
        self.assertAlmostEqual(min(fonds), -15.5, places=3)
        # chaque palier descend d'au plus une passe
        paliers = sorted(f for f in fonds if f <= 0)
        for avant, apres in zip(paliers, paliers[1:]):
            self.assertLessEqual(abs(apres - avant), 4.0 + 1e-6)

    def test_une_epaisseur_nulle_se_refuse(self):
        """Sans épaisseur, le programme ne sait pas jusqu'où descendre —
        et le dire ici vaut mieux que devant la machine."""
        debit = _debit_carre(epaisseur=15)
        import dataclasses
        creuse = dataclasses.replace(debit, planche=dataclasses.replace(
            debit.planche, epaisseur=0))
        with self.assertRaises(ValueError) as leve:
            gcode.programme(creuse)
        self.assertIn("épaisseur", str(leve.exception))

    def test_aucun_rapide_ne_traverse_la_matiere(self):
        """Un G0 sous le dessus de la planche, c'est la fraise qui traverse
        le bois à vitesse de transit."""
        texte, _, _ = gcode.programme(_debit_carre())
        deplacements, _ = rejouer(texte)
        for d in deplacements:
            if not d.rapide:
                continue
            bouge_en_xy = (abs(d.a[0] - d.de[0]) > 1e-9
                           or abs(d.a[1] - d.de[1]) > 1e-9)
            if bouge_en_xy:
                self.assertGreaterEqual(min(d.de[2], d.a[2]), -1e-9,
                                        "rapide dans la matière ligne %d"
                                        % d.ligne)

    def test_la_plongee_a_sa_propre_vitesse(self):
        reglages = gcode.Reglages(longueur_rampe=0, vitesse_plongee=250,
                                  vitesse_avance=1800)
        texte, _, _ = gcode.programme(_debit_carre(), reglages)
        deplacements, _ = rejouer(texte)
        plongees = [d for d in deplacements
                    if not d.rapide and abs(d.a[2] - d.de[2]) > 1e-9
                    and abs(d.a[0] - d.de[0]) < 1e-9
                    and abs(d.a[1] - d.de[1]) < 1e-9]
        self.assertTrue(plongees)
        for d in plongees:
            self.assertEqual(d.avance, 250.0)

    def test_la_rampe_descend_en_avancant(self):
        """Une plongée droite à pleine profondeur casse la fraise."""
        reglages = gcode.Reglages(longueur_rampe=25, attaches=0)
        texte, _, _ = gcode.programme(_debit_carre(), reglages)
        deplacements, _ = rejouer(texte)
        obliques = [d for d in deplacements
                    if not d.rapide and abs(d.a[2] - d.de[2]) > 1e-6
                    and math.dist(d.de[:2], d.a[:2]) > 1e-6]
        self.assertTrue(obliques, "aucune descente en biais")
        droites = [d for d in deplacements
                   if not d.rapide and d.a[2] < -1e-9
                   and abs(d.a[2] - d.de[2]) > 1e-6
                   and math.dist(d.de[:2], d.a[:2]) < 1e-9]
        self.assertEqual(droites, [], "plongée droite malgré la rampe")


class Attaches(unittest.TestCase):

    def test_elles_laissent_du_bois_sous_la_piece(self):
        reglages = gcode.Reglages(attaches=3, longueur_attache=6,
                                  hauteur_attache=1.5, depassement=0.5)
        texte, _, _ = gcode.programme(_debit_carre(epaisseur=15), reglages)
        deplacements, _ = rejouer(texte)
        hauteur = -(15 - 1.5)
        remontees = [d for d in deplacements
                     if d.commentaire == "tour de piece"
                     and abs(d.a[2] - hauteur) < 1e-6]
        self.assertTrue(remontees, "aucune attache")
        # trois montées et trois descentes, sur le seul dernier tour
        montees = sum(1 for d in deplacements
                      if abs(d.a[2] - hauteur) < 1e-6 and d.de[2] < hauteur - 1e-6)
        self.assertEqual(montees, 3 * 2, "attaches par contour")

    def test_sans_attaches_la_fraise_ne_remonte_jamais_en_coupant(self):
        """Une remontée en pleine coupe n'a qu'une raison d'être : une
        attache. Sans attaches, le Z ne fait que descendre — les rampes
        comprises — jusqu'au dégagement en rapide."""
        texte, _, _ = gcode.programme(_debit_carre(), gcode.Reglages(attaches=0))
        deplacements, _ = rejouer(texte)
        self.assertTrue([d for d in deplacements if d.coupe])
        for d in deplacements:
            if d.rapide:
                continue
            self.assertLessEqual(d.a[2], d.de[2] + 1e-6,
                                 "la fraise remonte en coupant, ligne %d"
                                 % d.ligne)

    def test_une_attache_plus_epaisse_que_la_planche_se_refuse(self):
        with self.assertRaises(ValueError):
            gcode.programme(_debit_carre(epaisseur=15),
                            gcode.Reglages(hauteur_attache=20))


class Dialectes(unittest.TestCase):

    def test_linuxcnc_melange_change_d_outil_et_finit_par_m2(self):
        texte, _, _ = gcode.programme(_debit_carre(),
                                   gcode.Reglages(dialecte="linuxcnc", outil=3))
        _, mots = rejouer(texte)
        self.assertIn("G64", texte)
        self.assertIn("T3", mots)
        self.assertIn("M6", mots)
        self.assertIn("G43", texte)
        self.assertEqual(mots[-1], "M2")

    def test_grbl_refuse_ces_mots(self):
        """GRBL mélange nativement ($11) et n'a pas de table d'outils :
        G64, T/M6 et G43 y sont des erreurs."""
        texte, _, _ = gcode.programme(_debit_carre(),
                                   gcode.Reglages(dialecte="grbl", outil=3))
        _, mots = rejouer(texte)
        for interdit in ("G64", "G43", "M6"):
            self.assertNotIn(interdit, texte.split("(")[0] + texte,
                             "%s dans un programme GRBL" % interdit)
        self.assertEqual(mots[-1], "M30")

    def test_un_dialecte_inconnu_se_refuse(self):
        with self.assertRaises(ValueError):
            gcode.programme(_debit_carre(), gcode.Reglages(dialecte="mach3"))

    def test_l_aspiration_est_un_cablage_pas_un_gout(self):
        """M7 et M8 sont deux sorties, deux broches de HAL : celle qui
        n'est pas câblée ne fait rien du tout, et le fichier tourne sans
        air sans que rien ne le dise."""
        for code in ("", "M7", "M8"):
            texte, _, _ = gcode.programme(_debit_carre(),
                                       gcode.Reglages(aspiration=code))
            _, mots = rejouer(texte)
            self.assertEqual(code in mots, bool(code))
            self.assertEqual("M9" in mots, bool(code))
        with self.assertRaises(ValueError):
            gcode.programme(_debit_carre(), gcode.Reglages(aspiration="M42"))

    def test_la_broche_a_zero_ne_lance_rien(self):
        texte, _, _ = gcode.programme(_debit_carre(),
                                   gcode.Reglages(vitesse_broche=0))
        _, mots = rejouer(texte)
        self.assertNotIn("M3", mots)
        self.assertNotIn("M5", mots)


class Avertissements(unittest.TestCase):

    def test_une_fraise_trop_large_mord_dans_la_voisine(self):
        """Le fichier resterait valide, et deux pièces se mangeraient
        l'une l'autre."""
        pieces = [Piece("plaque", 100, 100, 15, "cp", 2, FIL_INDIFFERENT,
                        contour=CARRE)]
        stock = [Planche("cp", 260, 130, 15, "cp", 1, fil=False)]
        debit = optimiser(pieces, stock,
                          Parametres(essais_melanges=0, processus=1,
                                     ecart_contours=6, marge_bord=8)).debits[0]
        self.assertEqual(len(debit.poses), 2)
        _, fine, _ = gcode.programme(debit, gcode.Reglages(diametre_fraise=3))
        self.assertEqual([a for a in fine if "mord" in a], [])
        _, large, _ = gcode.programme(debit, gcode.Reglages(diametre_fraise=12))
        self.assertTrue(any("mord dans" in a for a in large))
        self.assertTrue(any("écart entre contours" in a for a in large))

    def test_le_flanc_qui_rase_le_bord_n_est_qu_une_remarque(self):
        """Une pièce à 5 mm du bord, fraisée à Ø 6, laisse l'outil raser
        l'arête sur un millimètre : c'est le quotidien d'une découpe en
        panneau. En faire une faute, c'était six alarmes pour rien."""
        import dataclasses

        import exemples
        pieces, stock, params = exemples.formes_biscornues()
        r = optimiser(pieces, stock, dataclasses.replace(params, processus=1))
        for numero, debit in enumerate(r.debits, 1):
            _, fautes, remarques = gcode.programme(
                debit, gcode.Reglages(diametre_fraise=6), numero)
            self.assertEqual(fautes, [], "une faute sur un plan cuttable")
            self.assertTrue(remarques)
            for mot in remarques:
                self.assertIn("rase le bord", mot)
                self.assertIn("sans conséquence", mot)

    def test_le_centre_hors_de_la_planche_est_une_faute(self):
        """Là, la machine promène la fraise au-delà de la matière, où sont
        les serre-joints."""
        import dataclasses

        import exemples
        pieces, stock, params = exemples.formes_biscornues()
        r = optimiser(pieces, stock, dataclasses.replace(params, processus=1))
        _, fautes, _ = gcode.programme(r.debits[0],
                                       gcode.Reglages(diametre_fraise=12))
        self.assertTrue(any("CENTRE" in f for f in fautes))

    def test_ils_sont_recopies_en_tete_du_fichier(self):
        """Celui qui ouvre le fichier à la machine ne lit pas l'écran d'où
        il sort."""
        piece = Piece("bague", 100, 100, 15, "cp", 1, FIL_INDIFFERENT,
                      contour=CARRE,
                      trous=(((48, 48), (52, 48), (52, 52), (48, 52)),))
        debit = optimiser([piece], [Planche("cp", 400, 300, 15, "cp", 1,
                                            fil=False)], RAPIDE).debits[0]
        texte, avertissements, remarques = gcode.programme(debit)
        self.assertTrue(avertissements)
        entete = texte.split("G21")[0]
        for mot in avertissements + remarques:
            self.assertIn(mot.split(" — ")[0][:40].replace("(", "["), entete)
        self.assertIn("ATTENTION", entete)


class Robustesse(unittest.TestCase):

    def test_une_reference_a_parentheses_ne_casse_pas_le_programme(self):
        """Une parenthèse dans un commentaire le referme : le programme ne
        se charge plus, pour un nom de pièce."""
        piece = Piece("cadre (grand) 50%", 100, 100, 15, "cp", 1,
                      FIL_INDIFFERENT, contour=CARRE)
        debit = optimiser([piece], [Planche("cp (chute)", 400, 300, 15, "cp",
                                            1, fil=False)], RAPIDE).debits[0]
        texte, _, _ = gcode.programme(debit, titre="Projet (essai)")
        rejouer(texte)          # lève si un commentaire n'est pas refermé

    def test_une_planche_sciee_se_fraise_aussi(self):
        """Un plan à la scie n'a pas de contours : ses rectangles en font
        office, et le programme sort quand même."""
        r = optimiser([Piece("montant", 400, 60, 18, "sapin", 2)],
                      [Planche("sapin", 1000, 200, 18, "sapin", 1)],
                      Parametres(essais_melanges=0))
        texte, _, _ = gcode.programme(r.debits[0], gcode.Reglages(attaches=2))
        deplacements, _ = rejouer(texte)
        self.assertTrue([d for d in deplacements if d.coupe])

    def test_tout_reste_dans_la_planche_sur_un_vrai_plan(self):
        import dataclasses

        import exemples
        pieces, stock, params = exemples.formes_biscornues()
        r = optimiser(pieces, stock, dataclasses.replace(params, processus=1))
        reglages = gcode.Reglages(diametre_fraise=3)
        for numero, debit in enumerate(r.debits, 1):
            texte, avertissements, _ = gcode.programme(debit, reglages, numero)
            self.assertEqual(avertissements, [], debit.planche.reference)
            deplacements, _ = rejouer(texte)
            pl = debit.planche
            for d in deplacements:
                for point in (d.de, d.a):
                    self.assertGreaterEqual(point[0], -2.0)
                    self.assertGreaterEqual(point[1], -2.0)
                    self.assertLessEqual(point[0], pl.longueur + 2.0)
                    self.assertLessEqual(point[1], pl.largeur + 2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
