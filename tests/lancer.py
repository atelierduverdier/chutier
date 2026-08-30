#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lance toute la suite.

    python3 tests/lancer.py

Quatre fichiers depuis que l'interface existe — les lancer un par un
finissait par en oublier un.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
DOSSIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(DOSSIER))

if __name__ == "__main__":
    suite = unittest.TestLoader().discover(DOSSIER, pattern="test_*.py")
    resultat = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if resultat.wasSuccessful() else 1)
