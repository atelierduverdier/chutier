// Pyodide dans un Web Worker : le cœur Python tourne ici, la page reste
// vive. Protocole : {id, fn, args} → {id, ok, valeur | erreur}.
// Les modules Python sont ceux du dépôt, chargés tels quels.

const VERSION_PYODIDE = "0.28.0";
const CDN = `https://cdn.jsdelivr.net/pyodide/v${VERSION_PYODIDE}/full/`;
const MODULES = ["optimiseur.py", "imbrication.py", "triangulation.py",
  "contours_svg.py", "projet_io.py", "csv_io.py", "couleurs.py",
  "saisie.py", "stock_atelier.py", "exemples.py", "export_cnc.py", "gcode.py",
  "fcstd_io.py", "pont_web.py"];

importScripts(CDN + "pyodide.js");

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
      // Un déploiement en plein rechargement peut mélanger un app.js du
      // jour avec un pont_web.py resservi périmé par le cache (bris de
      // réseau sur CE fichier précis pendant qu'un autre passait) :
      // « pont[fn] is not a function » ne dit rien à l'atelier. Un message
      // qui nomme la fonction et pointe le geste qui répare (14/09/2026).
      throw new Error("version des fichiers incohérente (" + fn
        + " introuvable) — rechargez la page (Ctrl+Maj+R)");
    }
    const valeur = pont[fn](...args);
    postMessage({ id, ok: true, valeur: typeof valeur === "string" ? valeur : String(valeur) });
  } catch (erreur) {
    postMessage({ id, ok: false, erreur: String(erreur).split("\n").slice(-3).join(" ") });
  }
}

onmessage = (e) => { if (pret) traiter(e.data); else enAttente.push(e.data); };
