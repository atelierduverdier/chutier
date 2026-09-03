# CLAUDE.md

Tout est en français : code, commentaires, messages de commit.

**Lire `README.md` d'abord** : il porte les conventions du cœur
(millimètres, fil le long de la longueur, trait de scie, chutes minis,
score) et la liste de ce qui reste à bâtir.

Règle de couches : `optimiseur.py` est la couche géométrie, **sans Qt ni
aucune dépendance** — `tests/test_optimiseur.py` le vérifie. L'interface
se construit au-dessus, en quatre modules : `apparence.py` (couleurs,
tuiles), `tables_saisie.py` (les deux tables et leurs délégués),
`vue_plan.py` (le dessin), `interface.py` (la fenêtre). Aucun ne fait de
géométrie ; aucun n'est importé par le cœur.

Après chaque modification :

```bash
python3 tests/lancer.py
```

**Une modification d'interface se juge sur capture, pas sur le code.** En
sans-écran :

```bash
CHUTIER_ATELIER=/tmp/chutier-essai/atelier.json XDG_CONFIG_HOME=/tmp/chutier-essai QT_QPA_PLATFORM=offscreen python3 -c "import interface,sys;from PySide6.QtWidgets import QApplication;a=QApplication(sys.argv);f=interface.FenetrePrincipale();f.resize(1680,960);f.show();a.processEvents();f._calculer();a.processEvents();f.grab().save('/tmp/chutier.png')"
```

Les deux variables d'environnement ne sont pas décoratives : sans elles,
la fenêtre lit et écrit le VRAI stock de l'atelier
(`~/.local/share/chutier/atelier.json`) et les vrais réglages Qt
(`~/.config/AtelierDuVerdier/Chutier.conf`) — le harnais de tests les
pose lui-même. `QSettings.setPath` ne détourne rien sur Linux ; seule
`XDG_CONFIG_HOME` tient parole.

Trois défauts n'ont été vus que comme ça, jamais en relisant le code :
deux références du même vert, une étiquette « chute » écrite par-dessus
le titre d'une planche, et des cartouches tombés à huit pixels sur un
brin de 4 m. Le dessin est le produit — il se regarde.

Commits directement sur `main`, sans « Co-Authored-By ».
