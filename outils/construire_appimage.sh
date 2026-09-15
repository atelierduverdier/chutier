#!/bin/bash
# Construit l'AppImage Linux du Chutier (bureau, PySide6), à partir des
# sources du dépôt.
#
# PyInstaller fige interface.py — PySide6, shapely et numpy embarqués —
# dans un dossier autonome (--onedir : pas de dézippage à chaque
# lancement, contrairement à --onefile) ; appimagetool l'empaquette
# ensuite avec son .desktop et son icône. Rien de tout ça ne modifie le
# dépôt : tout se construit dans un dossier jetable.
#
# Ne réutilise PAS l'environnement Python système directement : un venv
# --system-site-packages hérite de PySide6/shapely/numpy déjà installés
# (pas de retéléchargement de plusieurs centaines de Mo) tout en gardant
# PyInstaller isolé.
#
# Lancement : outils/construire_appimage.sh [dossier_de_sortie]

set -euo pipefail
cd "$(dirname "$0")/.."
SORTIE="${1:-$PWD}"
TRAVAIL="$(mktemp -d)"
trap 'rm -rf "$TRAVAIL"' EXIT

echo "→ Icône PNG (depuis resources/icone.svg)…"
rsvg-convert -w 256 -h 256 resources/icone.svg -o "$TRAVAIL/chutier.png"

echo "→ Environnement Python jetable (hérite de PySide6/shapely/numpy système)…"
python3 -m venv --system-site-packages "$TRAVAIL/venv"
source "$TRAVAIL/venv/bin/activate"
pip install --upgrade pip -q
pip install pyinstaller -q

echo "→ PyInstaller (interface.py)…"
pyinstaller --name chutier --onedir --windowed \
  --add-data "$PWD/resources/icone.svg:resources" \
  --distpath "$TRAVAIL/dist" --workpath "$TRAVAIL/build" --specpath "$TRAVAIL" \
  --noconfirm \
  interface.py

echo "→ AppDir…"
APPDIR="$TRAVAIL/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -r "$TRAVAIL/dist/chutier/." "$APPDIR/usr/bin/"
cp "$TRAVAIL/chutier.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/chutier.png"
cp "$TRAVAIL/chutier.png" "$APPDIR/chutier.png"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
# chutier est un dossier PyInstaller --onedir : ses .so voisins
# (_internal) sont retrouvés par rpath, pas besoin de LD_LIBRARY_PATH.
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/bin/chutier" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/chutier.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Chutier
GenericName=Feuille de débit
Comment=Optimiseur de découpe de bois — plan de débit et stock de chutes
Exec=chutier
Icon=chutier
Categories=Graphics;Engineering;
Terminal=false
EOF

echo "→ appimagetool…"
OUTIL="$TRAVAIL/appimagetool"
curl -sL -o "$OUTIL" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
chmod +x "$OUTIL"

mkdir -p "$SORTIE"
ARCH=x86_64 "$OUTIL" "$APPDIR" "$SORTIE/Chutier-x86_64.AppImage"

echo "→ Vérification (calcul en tâche de fond, sans écran)…"
if XDG_CONFIG_HOME="$TRAVAIL/essai" CHUTIER_ATELIER="$TRAVAIL/essai/atelier.json" \
   QT_QPA_PLATFORM=offscreen timeout 15 "$SORTIE/Chutier-x86_64.AppImage" &
then
  PID=$!
  sleep 4
  if kill -0 "$PID" 2>/dev/null; then
    echo "  lancée et vivante — arrêt."
    kill "$PID"; wait "$PID" 2>/dev/null || true
  else
    echo "  ATTENTION : arrêtée toute seule, quelque chose a raté." >&2
    exit 1
  fi
fi

echo
echo "AppImage prête : $SORTIE/Chutier-x86_64.AppImage"
