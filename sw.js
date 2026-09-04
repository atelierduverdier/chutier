// Service worker : le chutier reste utilisable sans réseau, Python compris.
//
// Réseau d'abord, cache en secours : en ligne, chaque visite reçoit les
// fichiers du jour (rien ne reste bloqué sur une vieille version servie
// par son propre cache) ; hors-ligne, le cache répond. Les fichiers de
// Pyodide sur le CDN sont versionnés dans leur adresse, donc immuables :
// eux se prennent d'abord au cache — une quinzaine de Mo qu'on ne
// retélécharge pas.
//
// La VERSION ci-dessous suit celle d'optimiseur.py (tests/test_version.py
// y veille) : un cache par version, les autres s'effacent à l'activation.
const VERSION = "1.0.0";
const CACHE = "chutier-v" + VERSION;
const PORTEE = new URL("./", self.location).pathname;
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/";
const MODULES = ["optimiseur.py", "imbrication.py", "triangulation.py",
  "contours_svg.py", "projet_io.py", "csv_io.py", "couleurs.py",
  "saisie.py", "stock_atelier.py", "exemples.py", "export_cnc.py", "fcstd_io.py", "pont_web.py"];
const FICHIERS = ["./", "./index.html", "./manifest.webmanifest", "./resources/icone.svg",
  "./web/app.js", "./web/langue.js", "./web/style.css", "./web/worker.js",
  ...MODULES.map(m => "./" + m)];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(FICHIERS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then(cles => Promise.all(cles.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function garder(requete, reponse) {
  if (reponse.ok || reponse.type === "opaque") {
    const copie = reponse.clone();
    caches.open(CACHE).then(c => c.put(requete, copie));
  }
  return reponse;
}

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  // version.json va TOUJOURS au réseau : c'est lui qui dit quelle version
  // est en ligne. Servi du cache, il comparerait la version installée à
  // elle-même et répondrait « à jour » pour l'éternité.
  if (url.pathname.endsWith("/version.json")) return;
  if (url.href.startsWith(PYODIDE)) {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => garder(e.request, r))));
    return;
  }
  if (url.origin !== self.location.origin || !url.pathname.startsWith(PORTEE) || url.search) return;
  // « no-cache » : le navigateur revalide auprès du serveur au lieu de
  // se fier à son propre cache HTTP — sans quoi un app.js d'hier peut
  // survivre à une publication tant que sa fraîcheur heuristique dure.
  const init = e.request.mode === "navigate" ? undefined : { cache: "no-cache" };
  e.respondWith(fetch(e.request, init).then(r => garder(e.request, r))
    .catch(() => caches.match(e.request)
      .then(hit => hit || (e.request.mode === "navigate" ? caches.match("./index.html") : Response.error()))));
});
