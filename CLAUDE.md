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
CHUTIER_ATELIER=/tmp/chutier-essai/atelier.json XDG_CONFIG_HOME=/tmp/chutier-essai CHUTIER_SANS_RESEAU=1 QT_QPA_PLATFORM=offscreen python3 -c "import interface,sys;from PySide6.QtWidgets import QApplication;a=QApplication(sys.argv);f=interface.FenetrePrincipale();f.resize(1680,960);f.show();a.processEvents();f._calculer();a.processEvents();f.grab().save('/tmp/chutier.png')"
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

**Les exports CNC se jugent dans les vrais logiciels**, pas sur le
texte produit. Le DXF passe l'audit d'`ezdxf` (`pip install ezdxf` dans
un venv jetable ; `tests/test_export_cnc.py` saute le test s'il manque).
Le .lbrn s'ouvre dans le LightBurn 1.3.01 de la machine, sur un écran
virtuel pour ne pas déranger la session :

```bash
Xvfb :99 -screen 0 1700x1050x24 &
cp -r ~/.config/LightBurn /tmp/essai-lb/          # jamais la vraie config
cd ~/Applications/LightBurn-1.3 && DISPLAY=:99 XDG_CONFIG_HOME=/tmp/essai-lb ./LightBurn fichier.lbrn
DISPLAY=:99 import -window root /tmp/vue.png
```

Deux défauts n'ont été vus que comme ça : une `AppVersion` déclarée trop
récente ouvrait sur un avertissement de perte de données (bouton par
défaut sur NON), et un `<Shape Type="Text">` écrit à la main fait planter
LightBurn par une faute de segmentation — d'où un .lbrn sans noms de
pièces.

**La version** est `VERSION` dans `optimiseur.py`, recopiée dans
`web/app.js`, `sw.js` et `version.json` — `tests/test_version.py` refuse
qu'elles divergent. On la monte, aux quatre endroits et en un seul commit,
à chaque publication qui change quelque chose pour l'utilisateur : c'est
`version.json` en ligne, comparé à la version embarquée, qui allume la
pastille « ⟳ » sur le web et dans la barre d'état du bureau. Un
changement purement documentaire ne monte pas la version.

Commits directement sur `main`, sans « Co-Authored-By ».
