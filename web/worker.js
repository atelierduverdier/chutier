// Pyodide dans un Web Worker : le cœur Python tourne ici, la page reste
// vive. Protocole : {id, fn, args} → {id, ok, valeur | erreur}.
// Les modules Python sont ceux du dépôt, chargés tels quels.
//
// Worker de MODULE, pas classique : depuis la 314.0.0, pyodide.mjs le
// refuse tel quel (« Classic web workers are not supported ») — la page
// (app.js) crée donc ce worker avec {type: "module"}. En échange, shapely
// 2.1.2 (GEOS bien plus récent que la 3.12.1 de la 0.28) : une
// TopologyException GEOS sur un NFP à pointes aiguës (une étoile SVG)
// tuait tout le worker sans le moindre rattrapage possible côté Python —
// vérifié réel sur le dossier de Christophe (14/09/2026), et vérifié
// résolu par cette version.

const VERSION_PYODIDE = "314.0.6";
const CDN = `https://cdn.jsdelivr.net/pyodide/v${VERSION_PYODIDE}/full/`;
const MODULES = ["optimiseur.py", "imbrication.py", "triangulation.py",
  "contours_svg.py", "projet_io.py", "csv_io.py", "couleurs.py",
  "saisie.py", "stock_atelier.py", "exemples.py", "export_cnc.py", "gcode.py",
  "fcstd_io.py", "pont_web.py"];

const { loadPyodide } = await import(CDN + "pyodide.mjs");

let pont = null;
let pyodide = null;

async function demarrer() {
  postMessage({ etat: "Chargement de Python…" });
  pyodide = await loadPyodide({ indexURL: CDN });
  postMessage({ etat: "Chargement de numpy et shapely…" });
  await pyodide.loadPackage(["numpy", "shapely"]);
  postMessage({ etat: "Chargement du chutier…" });
  for (const nom of MODULES) {
    const reponse = await fetch(new URL("../" + nom, self.location.href));
    if (!reponse.ok) throw new Error("impossible de lire " + nom);
    pyodide.FS.writeFile("/home/pyodide/" + nom, await reponse.text());
  }
  pyodide.runPython('import sys; sys.path.insert(0, "/home/pyodide"); import pont_web');
  pont = pyodide.pyimport("pont_web");
  postMessage({ pret: true });
}

const enAttente = [];
let pret = false;

demarrer().then(() => { pret = true; for (const m of enAttente) traiter(m); })
  .catch(erreur => postMessage({ echec: String(erreur) }));

function traiter(message) {
  const { id, fn, args } = message;
  try {
    if (typeof pont[fn] !== "function") {
      // « pont[fn] is not a function » ne dit rien à l'atelier. Deux
      // causes vues le 14/09/2026 : un déploiement en plein rechargement
      // qui mélange un app.js du jour avec un pont_web.py resservi périmé
      // par le cache — OU un module Python déjà mort d'un plantage fatal
      // plus tôt dans CE worker (une TopologyException GEOS, par exemple,
      // ne se rattrape pas en WebAssembly et emporte tout Python avec
      // elle). app.js relance un worker neuf dès qu'il voit passer cette
      // erreur ; pas la peine de le dire ici, un mot suffit à nommer la
      // fonction absente.
      throw new Error("le moteur de calcul ne répond plus (" + fn
        + " introuvable)");
    }
    const valeur = pont[fn](...args);
    postMessage({ id, ok: true, valeur: typeof valeur === "string" ? valeur : String(valeur) });
  } catch (erreur) {
    postMessage({ id, ok: false, erreur: String(erreur).split("\n").slice(-3).join(" ") });
  }
}

onmessage = (e) => { if (pret) traiter(e.data); else enAttente.push(e.data); };
