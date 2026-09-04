# -*- coding: utf-8 -*-
"""La page web est bilingue : chaque texte enveloppé dans ``t()`` de
``web/app.js`` — et chaque texte visible d'``index.html`` — doit avoir sa
traduction dans ``web/langue.js``, et aucune traduction ne doit rester
orpheline. Une clé oubliée s'affiche en français au milieu de l'anglais,
sans rien casser : c'est justement ce qui se remarque tard.

On lit le JavaScript en texte, avec un vrai balayage lexical — une
expression régulière butait sur les gabarits imbriqués
(``t`… ${x ? t`…` : ""}` ``).

Lancement : python3 tests/test_langue.py
"""

import os
import re
import sys
import unittest
from html.parser import HTMLParser

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import optimiseur as opt  # noqa: E402


def _lire(nom):
    with open(os.path.join(RACINE, nom), encoding="utf-8") as f:
        return f.read()


def _normal(texte):
    """La même clé, qu'elle soit écrite avec un vrai saut de ligne (un
    gabarit d'app.js) ou avec l'échappement « \\n » (le dictionnaire)."""
    return texte.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


# -- le balayage de app.js ---------------------------------------------------

class _Balayage:
    """Les chaînes passées à ``t(...)`` et les gabarits ``t`...` ``, avec
    leurs ``${…}`` remplacés par ``{}`` — la forme des clés."""

    def __init__(self, source):
        self.s = source
        self.cles = []
        self._tout()

    def _chaine(self, i):
        q = self.s[i]
        j = i + 1
        while self.s[j] != q:
            j += 2 if self.s[j] == "\\" else 1
        return self.s[i + 1:j], j + 1

    def _gabarit(self, i):
        """s[i] == '`' : rend (clé, position après le backtick fermant)."""
        j = i + 1
        morceaux = []
        while True:
            c = self.s[j]
            if c == "\\":
                morceaux.append(self.s[j:j + 2])
                j += 2
                continue
            if c == "`":
                return "".join(morceaux), j + 1
            if self.s.startswith("${", j):
                k = j + 2
                prof = 1
                while prof:
                    c2 = self.s[k]
                    if c2 == "{":
                        prof += 1
                        k += 1
                    elif c2 == "}":
                        prof -= 1
                        k += 1
                    elif c2 == "`":
                        interne, k = self._gabarit(k)
                        if self.s[j:k].count("t`") and self.s[k - len(interne) - 3] == "t":
                            self.cles.append(interne)
                    elif c2 in "\"'":
                        _, k = self._chaine(k)
                    else:
                        k += 1
                morceaux.append("{}")
                j = k
                continue
            morceaux.append(c)
            j += 1

    def _tout(self):
        s = self.s
        i = 0
        while i < len(s):
            if s.startswith("//", i):
                i = s.find("\n", i)
                if i < 0:
                    break
                continue
            if s.startswith("/*", i):
                i = s.index("*/", i) + 2
                continue
            if s[i] == "`":
                cle, fin = self._gabarit(i)
                if i and s[i - 1] == "t" and not re.match(r"\w", s[i - 2] or " "):
                    self.cles.append(cle)
                i = fin
                continue
            if s[i] in "\"'":
                contenu, fin = self._chaine(i)
                avant = s[max(0, i - 2):i]
                if avant.endswith("t(") and not re.match(r"\w", (s[i - 3:i - 2] or " ")):
                    self.cles.append(contenu)
                i = fin
                continue
            i += 1


def _cles_app():
    balayage = _Balayage(_lire("web/app.js"))
    return sorted({_normal(c) for c in balayage.cles})


# -- les textes de la page ---------------------------------------------------

class _Page(HTMLParser):

    def __init__(self):
        super().__init__()
        self.textes = []
        self._muet = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._muet = True
        for cle, valeur in attrs:
            if cle in ("title", "placeholder") and valeur:
                self.textes.append(valeur)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._muet = False

    def handle_data(self, donnee):
        if not self._muet and donnee.strip():
            self.textes.append(donnee.strip())


def _cles_page():
    page = _Page()
    page.feed(_lire("index.html"))
    return sorted({t for t in page.textes if re.search(r"[A-Za-zÀ-ÿ]", t)})


def _traductions():
    """Les clés du dictionnaire anglais de web/langue.js."""
    source = _lire("web/langue.js")
    debut = source.index("const ANGLAIS = {")
    fin = source.index("\n};", debut)
    corps = source[debut:fin]
    cles = []
    i = 0
    while i < len(corps):
        if corps.startswith("//", i):
            i = corps.find("\n", i)
            continue
        if corps[i] == '"':
            j = i + 1
            while corps[j] != '"':
                j += 2 if corps[j] == "\\" else 1
            texte = corps[i + 1:j]
            # une clé est suivie de « : », une valeur de « , » ou d'un saut
            suite = corps[j + 1:j + 3].lstrip()
            if suite.startswith(":"):
                cles.append(_normal(texte))
            i = j + 1
            continue
        i += 1
    return cles


class Dictionnaire(unittest.TestCase):

    def setUp(self):
        self.traduites = _traductions()

    def test_pas_de_doublon_dans_le_dictionnaire(self):
        vues = set()
        doubles = [c for c in self.traduites if c in vues or vues.add(c)]
        self.assertEqual(doubles, [], "clés en double")

    def test_chaque_texte_de_app_js_est_traduit(self):
        manquantes = [c for c in _cles_app() if c not in self.traduites]
        self.assertEqual(manquantes, [], "sans traduction anglaise")

    def test_chaque_texte_de_la_page_est_traduit(self):
        manquantes = [c for c in _cles_page() if c not in self.traduites]
        self.assertEqual(manquantes, [], "sans traduction anglaise")

    def test_aucune_traduction_orpheline(self):
        """Une clé qui ne sert plus est du poids mort qu'on relira comme
        si elle comptait."""
        # Les tables constantes (colonnes, réglages) portent leur
        # français sans t() — traduit à l'affichage : on cherche donc le
        # texte dans les sources, pas seulement les appels enveloppés.
        sources = _lire("web/app.js") + _lire("index.html")
        vivantes = set(_cles_app()) | set(_cles_page()) | set(_raisons())
        orphelines = [c for c in self.traduites
                      if c not in vivantes and c.replace("{}", "") .strip()
                      and c.split("{}")[0].strip() not in sources]
        self.assertEqual(orphelines, [], "traductions qui ne servent plus")

    def test_les_raisons_du_coeur_sont_traduites(self):
        """Les raisons de non-placement viennent d'optimiseur.py : elles
        s'affichent telles quelles, donc elles se traduisent aussi."""
        manquantes = [r for r in _raisons() if r not in self.traduites]
        self.assertEqual(manquantes, [])

    def test_les_places_de_valeurs_se_correspondent(self):
        """Autant de « {} » dans la traduction que dans l'original, sans
        quoi une valeur disparaît de l'affichage anglais."""
        source = _lire("web/langue.js")
        for cle in self.traduites:
            if "{}" not in cle:
                continue
            motif = re.escape(cle.replace("\n", "\\n")) + r'"\s*:\s*\n?\s*"((?:[^"\\]|\\.)*)"'
            trouve = re.search(motif, source)
            self.assertIsNotNone(trouve, "valeur introuvable pour %r" % cle)
            self.assertEqual(trouve.group(1).count("{}"), cle.count("{}"),
                             "places de valeurs différentes pour %r" % cle)


def _raisons():
    return [getattr(opt, nom) for nom in dir(opt) if nom.startswith("RAISON_")]


class ChargementDuModule(unittest.TestCase):

    def test_langue_js_est_dans_le_cache_hors_ligne(self):
        self.assertIn("./web/langue.js", _lire("sw.js"))

    def test_app_js_importe_le_module(self):
        self.assertIn('from "./langue.js"', _lire("web/app.js"))

    def test_aucune_traduction_figee_au_chargement(self):
        """Les tables constantes (colonnes, réglages) gardent le
        français : un ``t()`` évalué au chargement figerait la langue de
        la première visite, et le bouton ne changerait plus les
        en-têtes — vu le 4 septembre 2026, colonnes restées françaises.
        """
        source = _lire("web/app.js")
        avant = source[:source.index("// -- version et mise à jour")]
        figees = re.findall(r'(?<![\w.$])t[("`]', avant.replace("import { t,", ""))
        self.assertEqual(figees, [], "traduction évaluée au chargement")


if __name__ == "__main__":
    unittest.main(verbosity=2)
