# -*- coding: utf-8 -*-
"""La version du chutier est écrite à quatre endroits — optimiseur.py,
web/app.js, sw.js, version.json — et une valeur recopiée à la main finit
toujours par prendre du retard quelque part. Ici on vérifie qu'elles
disent toutes la même chose, et que la vérification en ligne sait
comparer, et se taire quand le réseau ne répond pas.

Lancement : python3 tests/test_version.py
"""

import http.server
import json
import os
import re
import sys
import threading
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import optimiseur as opt  # noqa: E402
import verifier_version as vv  # noqa: E402


def _lire(nom):
    with open(os.path.join(RACINE, nom), encoding="utf-8") as f:
        return f.read()


class VersionsSynchronisees(unittest.TestCase):

    def test_app_js(self):
        m = re.search(r'^export const VERSION = "([^"]+)";', _lire("web/app.js"), re.M)
        self.assertEqual(m and m.group(1), opt.VERSION)

    def test_service_worker(self):
        m = re.search(r'^const VERSION = "([^"]+)";', _lire("sw.js"), re.M)
        self.assertEqual(m and m.group(1), opt.VERSION)

    def test_version_json(self):
        self.assertEqual(json.loads(_lire("version.json"))["version"], opt.VERSION)

    def test_le_service_worker_met_en_cache_les_modules_du_worker(self):
        """Les deux listes de modules Python doivent être les mêmes, sinon
        le hors-ligne casse au premier module manquant."""
        def modules(texte):
            m = re.search(r"const MODULES = \[(.*?)\];", texte, re.S)
            return sorted(re.findall(r'"([^"]+\.py)"', m.group(1)))
        self.assertEqual(modules(_lire("sw.js")), modules(_lire("web/worker.js")))

    def test_la_version_a_trois_nombres(self):
        self.assertRegex(opt.VERSION, r"^\d+\.\d+\.\d+$")


class ServiceWorker(unittest.TestCase):

    def test_tout_va_au_reseau_en_revalidant(self):
        """Le service worker sert le réseau d'abord — encore faut-il que
        le navigateur ne réponde pas depuis son PROPRE cache HTTP. La
        navigation en était exclue : une modification d'index.html restait
        invisible après rechargement, sur un serveur sans en-tête
        Cache-Control (vu le 4 septembre 2026)."""
        source = _lire("sw.js")
        self.assertIn('fetch(e.request, { cache: "no-cache" })', source)
        self.assertNotIn('mode === "navigate" ? undefined', source)

    def test_version_json_ne_passe_jamais_par_le_cache(self):
        """C'est lui qui dit quelle version est en ligne : servi du cache,
        il comparerait la version installée à elle-même."""
        source = _lire("sw.js")
        self.assertIn('endsWith("/version.json")', source)


class Comparaison(unittest.TestCase):

    def test_numerique_pas_textuelle(self):
        self.assertTrue(vv.plus_recente("1.10.0", "1.9.3"))
        self.assertFalse(vv.plus_recente("1.9.3", "1.10.0"))
        self.assertFalse(vv.plus_recente("1.0.0", "1.0.0"))
        self.assertTrue(vv.plus_recente("2.0", "1.99.99"))

    def test_verdicts(self):
        self.assertEqual(vv.comparer("1.0.0", "1.0.0"), vv.A_JOUR)
        self.assertEqual(vv.comparer("1.0.0", "1.0.1"), vv.EN_RETARD)
        self.assertEqual(vv.comparer("1.0.1", "1.0.0"), vv.A_JOUR)   # en avance = à jour
        self.assertEqual(vv.comparer("1.0.0", None), vv.INCONNUE)
        self.assertEqual(vv.comparer("1.0.0", ""), vv.INCONNUE)


class EnLigne(unittest.TestCase):

    def test_sans_reseau_on_ne_leve_pas(self):
        self.assertIsNone(vv.version_en_ligne("http://127.0.0.1:1/version.json", 0.5))

    def test_un_serveur_local_repond(self):
        class Serveur(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                corps = (b'{"version": "9.8.7"}' if self.path.startswith("/version.json")
                         else b"pas du json")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args):
                pass

        with http.server.HTTPServer(("127.0.0.1", 0), Serveur) as srv:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = "http://127.0.0.1:%d" % srv.server_address[1]
            self.assertEqual(vv.version_en_ligne(base + "/version.json", 2), "9.8.7")
            self.assertIsNone(vv.version_en_ligne(base + "/autre", 2))
            srv.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
