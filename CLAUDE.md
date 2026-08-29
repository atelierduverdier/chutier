# CLAUDE.md

Tout est en français : code, commentaires, messages de commit.

**Lire `README.md` d'abord** : il porte les conventions du cœur
(millimètres, fil le long de la longueur, trait de scie, chutes minis,
score) et la liste de ce qui reste à bâtir.

Règle de couches : `optimiseur.py` est la couche géométrie, **sans Qt ni
aucune dépendance** — `tests/test_optimiseur.py` le vérifie. Toute
interface se construit au-dessus, dans des modules séparés.

Après chaque modification :

```bash
python3 tests/test_optimiseur.py
```

Commits directement sur `main`, sans « Co-Authored-By ».
