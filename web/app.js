// Chutier — la page. Aucune logique de débit ici : tout passe par le
// worker Pyodide (web/worker.js) et pont_web.py. Cette couche tient les
// tables, les réglages, le plan en SVG et les fichiers, comme
// interface.py le fait pour Qt — et lit les mêmes fichiers (.json, .csv,
// .svg) que l'application de bureau.

import { t, langue, changerLangue, traduirePage } from "./langue.js";

const FILS = [["longueur", "Longueur"], ["largeur", "Largeur"], ["indifferent", "Indifférent"]];

const COLONNES = {
  pieces: [
    { cle: "reference", titre: "Référence", genre: "texte", info: "Nom de la pièce : c'est lui qui lui donne sa couleur sur le plan." },
    { cle: "longueur", titre: "Long.", genre: "nombre", info: "Longueur en mm, le long du fil." },
    { cle: "largeur", titre: "Larg.", genre: "nombre", info: "Largeur en mm, en travers du fil." },
    { cle: "epaisseur", titre: "Ép.", genre: "nombre", info: "Épaisseur FINIE en mm. Le brut se rabote : une planche plus épaisse convient, jamais une plus mince." },
    { cle: "matiere", titre: "Matière", genre: "matiere", info: "Le même mot que dans le stock, sinon rien ne s'apparie." },
    { cle: "quantite", titre: "Qté", genre: "entier", info: "Nombre d'exemplaires." },
    { cle: "fil", titre: "Fil", genre: "choix", choix: FILS, info: "Où court le fil du bois dans la pièce. « Indifférent » autorise la rotation." },
    { cle: "composable", titre: "Composable", genre: "bool", avancee: true, info: "Trop large pour tout brut, cette pièce peut se faire en plusieurs lames collées." },
    { cle: "planche", titre: "Planche", genre: "planche", avancee: true, info: "Imposer la ligne de stock où tailler cette pièce (vide : au choix)." },
    { cle: "contour", titre: "Contour", genre: "contour", avancee: true, info: "Une forme quelconque importée d'un SVG, imbriquée à la CNC." },
  ],
  stock: [
    { cle: "reference", titre: "Référence", genre: "texte", info: "Nom du morceau de stock, tel qu'il est repéré à l'atelier." },
    { cle: "longueur", titre: "Long.", genre: "nombre", info: "Longueur en mm, le long du fil." },
    { cle: "largeur", titre: "Larg.", genre: "nombre", info: "Largeur en mm, en travers du fil." },
    { cle: "epaisseur", titre: "Ép.", genre: "nombre", info: "Épaisseur BRUTE disponible, en mm." },
    { cle: "matiere", titre: "Matière", genre: "matiere", info: "Le même mot que dans les pièces." },
    { cle: "quantite", titre: "Qté", genre: "entier", info: "Combien de morceaux identiques." },
    { cle: "chute", titre: "Chute", genre: "bool", info: "Déjà en atelier, à écouler EN PRIORITÉ. Jamais compté à l'achat." },
    { cle: "atelier", titre: "Atelier", genre: "bool", info: "Vit dans le stock commun de ce navigateur, retrouvé d'un projet à l'autre." },
    { cle: "fil", titre: "Fil", genre: "bool", avancee: true, info: "Décocher pour un panneau (contreplaqué, MDF) : rotation libre." },
    { cle: "illimite", titre: "Catalogue", genre: "bool", avancee: true, info: "Une section qu'on peut ACHETER : la quantité ne borne plus rien." },
    { cle: "prix", titre: "Prix", genre: "nombre", avancee: true, info: "Coût d'UNE planche, pas au mètre. 0 pour ne pas en tenir compte." },
    { cle: "defauts_texte", titre: "Défauts", genre: "texte", info: "bouts 30 ; rives 8 ; 1200-1280 ; 600,140,60,40 — recoupes de bout et de rive, nœud traversant, zone x,y,longueur,largeur." },
    { cle: "contour", titre: "Contour", genre: "contour", avancee: true, info: "Une chute BISCORNUE, reste d'une planche imbriquée rangé au stock avec sa forme. Ne sert qu'à l'imbrication de contours." },
  ],
};

const DEFAUTS_LIGNE = {
  pieces: { reference: "", longueur: "", largeur: "", epaisseur: 18, matiere: "", quantite: 1, fil: "longueur", composable: false, planche: "", contour: [], trous: [] },
  stock: { reference: "", longueur: "", largeur: "", epaisseur: 18, matiere: "", quantite: 1, chute: false, atelier: false, fil: true, illimite: false, prix: 0, defauts_texte: "", contour: [], trous: [] },
};

const REGLAGES = [
  ["La scie", [
    ["trait_de_scie", "Trait de scie (mm)", "nombre", "3 à 4 mm pour une lame de circulaire."],
    ["coupe_en_bandes", "Coupe en bandes", "bool", "Scie à panneaux ou à format : déligner d'abord en bandes pleine longueur, puis tronçonner chaque bande."],
    ["surcote_longueur", "Surcote de longueur (mm)", "nombre", "Marge de recoupe ajoutée à chaque pièce au débit."],
    ["surcote_largeur", "Surcote de largeur (mm)", "nombre", "Idem en travers — de quoi dresser les rives."]]],
  ["Ce qui mérite d'être gardé", [
    ["chute_mini_longueur", "Chute mini — longueur (mm)", "nombre", "En dessous, le reste part aux pertes."],
    ["chute_mini_largeur", "Chute mini — largeur (mm)", "nombre", "Le petit côté du reste."]]],
  ["Le bois", [
    ["tolerance_epaisseur", "Tolérance d'épaisseur (mm)", "nombre", "Le bruit de mesure, pas un vrai manque d'épaisseur."],
    ["surcote_joint", "Surcote de joint collé (mm)", "nombre", "Largeur perdue à chaque collage d'une pièce composable."]]],
  ["La CNC (contours imbriqués)", [
    ["ecart_contours", "Écart entre contours (mm)", "nombre", "Diamètre de fraise plus un jeu."],
    ["marge_bord", "Marge au bord (mm)", "nombre", "Distance entre un contour et le bord de la planche."],
    ["vitesse_fraisage", "Vitesse de fraisage (mm/min)", "nombre", "Pour estimer le temps de découpe d'une planche imbriquée."],
    ["pas_rotation", "Orientations", "choix", "Les angles essayés pour une pièce à fil indifférent.",
      [[180, "2 orientations (180°) — rapide"], [90, "4 orientations (90°)"], [45, "8 orientations (45°)"], [30, "12 orientations (30°)"], [15, "24 orientations (15°) — lent"]]]]],
  ["Le calcul", [
    ["priorite", "Privilégier", "choix", "Entre deux plans dans le même bois neuf : moins de pertes, ou moins de coupes.",
      [["bois", "le bois — moins de pertes"], ["scie", "le temps de scie — moins de coupes"]]],
    ["essais_melanges", "Essais de mélange", "entier", "Ordres tirés au hasard en plus des stratégies réglées. Graine fixe : même plan."],
    ["passes_amelioration", "Passes d'amélioration", "entier", "Vider une planche, replacer ses pièces ailleurs. 0 pour s'en passer."]]],
];

// Les réglages du G-code ne touchent pas au plan : les changer ne périme
// pas le calcul, ils ne servent qu'à l'écriture du programme. D'où un
// bloc d'état à part, et « gcode » comme cible dans REGLAGES.
const REGLAGES_GCODE = [
  ["La CNC (G-code)", [
    ["dialecte", "Dialecte", "choix", "LinuxCNC accepte G64, le changement d'outil T/M6 et la correction G43 ; GRBL les refuse et mélange nativement.",
      [["linuxcnc", "LinuxCNC (RS274)"], ["grbl", "GRBL / grblHAL"]]],
    ["diametre_fraise", "Diamètre de fraise (mm)", "nombre", "Le diamètre RÉEL, mesuré. Il doit tenir dans l'écart entre contours du plan, sinon deux parcours voisins se recouvrent."],
    ["sens", "Sens de coupe", "choix", "En avalant, le tour se parcourt en horaire et les trous en anti-horaire : meilleur état de chant sur du panneau.",
      [["avalant", "en avalant"], ["opposition", "en opposition"]]],
    ["profondeur_passe", "Profondeur de passe (mm)", "nombre", "Ce qu'on descend par tour. La moitié du diamètre en panneau, le diamètre en tendre."],
    ["depassement", "Dépassement sous la planche (mm)", "nombre", "Ce qu'on mord dans le martyr, pour traverser vraiment."],
    ["vitesse_plongee", "Plongée en Z (mm/min)", "nombre", "Bien plus lente que l'avance : la fraise coupe mal par le bout."],
    ["vitesse_broche", "Broche (tr/min)", "entier", "Zéro n'écrit ni M3 ni M5 — pour une broche lancée à la main."],
    ["hauteur_securite", "Hauteur de sécurité (mm)", "nombre", "La hauteur des déplacements rapides au-dessus de la planche."],
    ["outil", "Numéro d'outil", "entier", "Le T<n> M6 du début. Zéro le saute. Sans effet en GRBL."],
    ["attaches", "Attaches par contour", "entier", "Sans elles, la pièce se libère au dernier tour, la fraise la prend et l'envoie."],
    ["longueur_attache", "Longueur d'une attache (mm)", "nombre", "Le long du contour."],
    ["hauteur_attache", "Bois laissé sous l'attache (mm)", "nombre", "Ce qu'il restera à couper au ciseau."],
    ["longueur_rampe", "Longueur de rampe (mm)", "nombre", "La descente se fait en biais sur cette longueur. Zéro plonge droit — et casse la fraise."],
    ["aspiration", "Aspiration / air", "choix", "C'est le CÂBLAGE qui décide, pas le goût : la sortie qui n'est pas branchée ne fait rien, et le fichier tourne sans air sans que rien ne le dise.",
      [["", "aucune"], ["M7", "M7 (brouillard)"], ["M8", "M8 (arrosage)"]]],
  ], "gcode"],
];

// Traduit à l'affichage, pas ici : une constante figerait la langue du chargement.
const RAISONS_VIDE = "Saisissez les pièces à débiter, vérifiez le stock, puis Calculer le débit (F5).";

// -- état ---------------------------------------------------------------------

const etat = {
  pieces: [], stock: [], parametres: {}, gcode: {}, epingles: [], resultat: null,
  aJour: false, zoom: 1, avancees: false, traits: false, planche: 1, nomProjet: "",
};

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...enfants) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  }
  for (const c of enfants) if (c !== null && c !== undefined) e.append(c);
  return e;
};
const mm = (v) => { const f = Number(v); return Number.isInteger(f) ? String(f) : f.toFixed(1).replace(/\.0$/, ""); };
// La virgule décimale suit la langue : en anglais, un point.
const dec = (texte) => (langue === "fr" ? texte.replace(".", ",") : texte);
const m2 = (v) => dec((v / 1e6).toFixed(3));
const pct = (v) => dec((100 * v).toFixed(1));

// -- le worker -----------------------------------------------------------------

let worker = null;
const attentes = new Map();
let compteur = 0;

// -- version et mise à jour ------------------------------------------------------
// La même valeur qu'optimiseur.VERSION, sw.js et version.json —
// tests/test_version.py y veille. version.json, lui, est lu au réseau à
// chaque visite (jamais du cache) : c'est lui qui dit ce qui est en ligne.

export const VERSION = "1.2.6";

function controlerVersion() {
  const b = $("#b-version");
  b.textContent = VERSION; b.className = "ver";
  b.title = t("Version ") + VERSION + t(" du chutier. Vérification de la mise à jour…");
  fetch(new URL("../version.json?t=" + Date.now(), import.meta.url), { cache: "no-store" })
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      if (!j || !j.version) return;
      if (j.version === VERSION) {
        b.className = "ver ok"; b.title = t("À jour : c'est bien la dernière version (") + VERSION + ").";
      } else {
        b.className = "ver vieux"; b.textContent = VERSION + " ⟳";
        b.title = t("Version ") + j.version + t(" disponible. Toucher pour mettre à jour (Ctrl + Maj + R).");
        b.onclick = forcerMaj;
      }
    })
    .catch(() => { b.title = t("Version ") + VERSION + ". Hors-ligne : mise à jour non vérifiable."; });
}

function forcerMaj() {
  const recharger = () => location.replace(location.pathname + "?maj=" + Date.now());
  if (!("serviceWorker" in navigator)) { recharger(); return; }
  navigator.serviceWorker.getRegistrations()
    .then(rs => Promise.all(rs.map(r => r.unregister())))
    .then(() => caches.keys())
    .then(ks => Promise.all(ks.map(k => caches.delete(k))))
    .then(recharger, recharger);
}

controlerVersion();
if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register(new URL("../sw.js", import.meta.url)).catch(() => {});
}
let pythonPret = false;
let demarre = false;

function lancerWorker() {
  worker = new Worker(new URL("./worker.js", import.meta.url));
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.etat) { $("#etat").textContent = m.etat; return; }
    if (m.echec) { $("#etat").textContent = t("Python n'a pas pu se charger : ") + m.echec; const v = $("#plan-vide"); if (v) v.textContent = t("Python n'a pas pu se charger : ") + m.echec; return; }
    if (m.pret) { pythonPret = true; $("#etat").textContent = t("Prêt"); if (!demarre) { demarre = true; demarrer(); } return; }
    const a = attentes.get(m.id);
    if (!a) return;
    attentes.delete(m.id);
    m.ok ? a.resolve(m.valeur) : a.reject(new Error(m.erreur));
  };
}

/**
 * Comme `appeler`, mais qui ne laisse jamais un rejet filer : une
 * interruption (Échap rejette les promesses en attente) ou une exception
 * Python laissaient sinon le geste sans réponse, et le message d'erreur
 * dans la console plutôt que sous les yeux. Rend `null` en cas d'échec.
 */
async function tenter(fn, ...args) {
  try {
    return await appeler(fn, ...args);
  } catch (erreur) {
    $("#etat").textContent = t("Le calcul a échoué : ") + erreur.message;
    return null;
  }
}

function appeler(fn, ...args) {
  return new Promise((resolve, reject) => {
    const id = ++compteur;
    attentes.set(id, { resolve, reject });
    worker.postMessage({ id, fn, args });
  });
}

// -- les workers auxiliaires ----------------------------------------------------------
//
// Le navigateur n'a pas de processus : Python y tourne sur un seul cœur.
// Mais l'essentiel du temps d'une imbrication part dans les no-fit
// polygons, indépendants les uns des autres — on en confie donc une
// tranche à chacun de quelques Web Workers de plus, qui rendent leurs
// géométries au principal. Ils ne naissent qu'au premier calcul qui en a
// besoin (chacun recharge Pyodide, une quinzaine de secondes la première
// fois — depuis le cache ensuite) et vivent jusqu'à la fin de la séance.

const NB_AUXILIAIRES = Math.max(0, Math.min((navigator.hardwareConcurrency || 2) - 1, 3));
// En dessous, la mise en route coûte plus que le calcul qu'elle abrège.
const SEUIL_NFP = 40;
const auxiliaires = [];

function naitreAuxiliaire() {
  const aux = { w: new Worker(new URL("./worker.js", import.meta.url)), attentes: new Map(), compteur: 0, pret: null };
  aux.pret = new Promise((resolve, rejeter) => {
    aux.w.onmessage = (e) => {
      const m = e.data;
      if (m.pret) { resolve(aux); return; }
      if (m.echec) { rejeter(new Error(m.echec)); return; }
      if (m.etat) return;
      const a = aux.attentes.get(m.id);
      if (!a) return;
      aux.attentes.delete(m.id);
      m.ok ? a.resolve(m.valeur) : a.reject(new Error(m.erreur));
    };
  });
  return aux;
}

function appelerAux(aux, fn, ...args) {
  return new Promise((resolve, reject) => {
    const id = ++aux.compteur;
    aux.attentes.set(id, { resolve, reject });
    aux.w.postMessage({ id, fn, args });
  });
}

/**
 * Précalcule les no-fit polygons à plusieurs, et les range dans le worker
 * principal. Sans effet si le calcul n'imbrique rien, s'il est trop petit
 * pour valoir la peine, ou si le navigateur n'a qu'un cœur — et sans
 * conséquence s'il échoue : le calcul refera le travail lui-même.
 */
async function precalculerNfp(entree) {
  if (!NB_AUXILIAIRES) return;
  try {
    const combien = JSON.parse(await appeler("taches_nfp", entree));
    // Ce que le worker principal a DÉJÀ en cache ne se recalcule pas : le
    // refaire à plusieurs prenait deux fois plus de temps que de ne rien
    // faire (mesuré le 04/09/2026 : 3,7 s contre 2,0 s au deuxième calcul).
    if (!combien.ok || combien.manquants.length < SEUIL_NFP) return;
    while (auxiliaires.length < NB_AUXILIAIRES) auxiliaires.push(naitreAuxiliaire());
    const prets = await Promise.all(auxiliaires.map(a => a.pret));
    const parts = prets.length + 1;
    $("#etat").textContent = t`Calcul des contours sur ${parts} cœurs…`;
    const tranche = (i) => JSON.stringify(combien.manquants.filter((_, k) => k % parts === i));
    const tranches = await Promise.all([
      appeler("calculer_nfp", entree, tranche(0)),
      ...prets.map((a, i) => appelerAux(a, "calculer_nfp", entree, tranche(i + 1))),
    ]);
    const faits = [];
    for (const brut of tranches) {
      const r = JSON.parse(brut);
      if (!r.ok) return;              // on laisse le calcul tout refaire
      faits.push(...r.faits);
    }
    await appeler("recevoir_nfp", entree, JSON.stringify(faits));
  } catch (_) {
    // Un worker de trop qui ne démarre pas ne doit pas empêcher de
    // calculer : le principal sait très bien faire tout le travail.
  }
}

// Interrompre : un worker qui calcule ne s'écoute pas. On le tue et on en
// relance un — Python se recharge depuis le cache, deux secondes — et
// les appels en attente reçoivent leur refus.
function interrompre() {
  if (!worker) return;
  worker.terminate();
  for (const aux of auxiliaires) { aux.w.terminate(); for (const a of aux.attentes.values()) a.reject(new Error("interrompu")); }
  auxiliaires.length = 0;
  for (const a of attentes.values()) a.reject(new Error("interrompu"));
  attentes.clear();
  pythonPret = false;
  $("#etat").textContent = t("Calcul interrompu — Python se recharge…");
  lancerWorker();
}
lancerWorker();

// -- annuler / refaire ------------------------------------------------------------

const historique = { passe: [], futur: [], courant: null, minuterie: null };
const instantane = () => JSON.stringify({ pieces: etat.pieces, stock: etat.stock, epingles: etat.epingles });
function consigner() {
  const nouveau = instantane();
  if (nouveau === historique.courant) return;
  // Tant que Python charge, `courant` peut valoir null (rien n'a encore
  // été consigné) alors que les boutons répondent déjà : le pousser
  // mettait un null dans la pile, et Annuler explosait dessus.
  if (historique.courant !== null) { historique.passe.push(historique.courant); historique.passe.splice(0, historique.passe.length - 100); }
  historique.futur = []; historique.courant = nouveau;
}
function marquerChangement() {
  // Une frappe = un pas, mais pas une lettre : la minuterie regroupe ce qui se tape d'une traite.
  clearTimeout(historique.minuterie);
  historique.minuterie = setTimeout(consigner, 500);
  brouillonPlusTard();
}
function rejouer(texte) {
  const d = JSON.parse(texte);
  etat.pieces = d.pieces; etat.stock = d.stock; etat.epingles = d.epingles;
  historique.courant = texte; etat.aJour = false;
  rendreTable("pieces"); rendreTable("stock"); rafraichirEtat(); enregistrerAtelier(); brouillonPlusTard();
}
function annuler() { clearTimeout(historique.minuterie); consigner(); if (!historique.passe.length) { $("#etat").textContent = t("Rien à annuler"); return; } historique.futur.push(historique.courant); rejouer(historique.passe.pop()); }
function refaire() {
  // La saisie en cours se consigne d'abord, comme dans annuler() : sinon
  // ce qu'on vient de taper dans les 500 ms de la minuterie est perdu.
  clearTimeout(historique.minuterie);
  const avant = historique.futur.length;
  consigner();
  historique.futur = historique.futur.length ? historique.futur : [];
  if (!avant || !historique.futur.length) { $("#etat").textContent = t("Rien à refaire"); return; }
  historique.passe.push(historique.courant); rejouer(historique.futur.pop());
}

// -- brouillon : le projet en cours survit à un rechargement ----------------------------

let minuterieBrouillon = null;
function brouillonPlusTard() { clearTimeout(minuterieBrouillon); minuterieBrouillon = setTimeout(enregistrerBrouillon, 800); }
function enregistrerBrouillon() {
  stockage.ecrire("brouillon", { pieces: etat.pieces, stock: etat.stock.filter(s => !s.atelier), parametres: etat.parametres, epingles: etat.epingles, nomProjet: etat.nomProjet, date: Date.now() });
}
function brouillon() { return stockage.lire("brouillon", null); }

// -- stockage local : atelier, réglages, préférences ----------------------------

const stockage = {
  lire(cle, defaut) { try { const v = localStorage.getItem("chutier." + cle); return v === null ? defaut : JSON.parse(v); } catch { return defaut; } },
  ecrire(cle, valeur) { try { localStorage.setItem("chutier." + cle, JSON.stringify(valeur)); } catch { /* navigation privée */ } },
};

function enregistrerAtelier() {
  stockage.ecrire("atelier", etat.stock.filter(s => s.atelier && (s.reference || "").trim()));
}
function atelier() { return stockage.lire("atelier", []).map(s => ({ ...DEFAUTS_LIGNE.stock, ...s, atelier: true })); }

// -- tables ---------------------------------------------------------------------

// Les matières des DEUX tables : leur colonne n'a de sens que si elles
// emploient le même mot, et proposer à chacune sa propre liste laissait
// justement de côté celui qui manque.
function matieres() { return [...new Set([...etat.stock, ...etat.pieces].map(s => (s.matiere || "").trim()).filter(Boolean))].sort(); }
function references() { return [...new Set(etat.stock.map(s => (s.reference || "").trim()).filter(Boolean))]; }

// -- la largeur des colonnes de texte -------------------------------------------------
//
// Le contenu d'une cellule est un <input>, et la longueur de ce qu'il
// porte n'entre pas dans le calcul de la colonne : le navigateur taille
// sur l'en-tête, et « Douglas » s'affichait « Doug… » dans une colonne de
// 59 px là où il en faut 66. L'attribut « size » n'y peut rien, la
// largeur à 100 % l'emporte. On mesure donc le texte nous-mêmes et on
// pose une largeur minimale sur l'en-tête, que la colonne suit.

const GENRES_A_MESURER = new Set(["texte", "matiere", "planche"]);
//: Bordures du champ et marges de la cellule, en pixels.
const AIR_CELLULE = 6;
//: Au-delà, une référence à rallonge mangerait toute la table.
const LARGEUR_MAXI = 220;

/**
 * La largeur qu'il faut à chaque colonne de texte, mesurée par le
 * NAVIGATEUR : `scrollWidth` d'un champ est la largeur de son contenu,
 * quelle que soit celle du champ. Mesurer la chaîne à part, au canvas,
 * donnait 50 px là où le champ en demandait 76 — une police résolue
 * autrement, et « Douglas » restait coupé après correction.
 */
function ajusterColonnes(table, colonnes) {
  const entetes = [...table.querySelectorAll("th")];
  colonnes.forEach((c, i) => {
    if (!GENRES_A_MESURER.has(c.genre) || !entetes[i]) return;
    let besoin = 0;
    for (const champ of table.querySelectorAll(
        "tbody td:nth-child(" + (i + 1) + ") input")) {
      besoin = Math.max(besoin, champ.scrollWidth);
    }
    entetes[i].style.minWidth = besoin
      ? Math.min(besoin + AIR_CELLULE, LARGEUR_MAXI) + "px" : "";
  });
}

function rendreTable(nom) {
  const table = $("#t-" + nom);
  const lignes = etat[nom];
  const colonnes = COLONNES[nom].filter(c => !c.avancee || etat.avancees || lignes.some(l => utilisee(c, l)));
  table.replaceChildren();
  const entete = el("tr");
  for (const c of colonnes) entete.append(el("th", { text: t(c.titre), title: t(c.info) }));
  table.append(el("thead", {}, entete));
  const corps = el("tbody");
  lignes.forEach((ligne, i) => {
    const tr = el("tr", { "data-ligne": i, onclick: (e) => { if (e.target.tagName !== "INPUT" && e.target.tagName !== "SELECT") { tr.classList.toggle("choisie", !(e.ctrlKey || e.metaKey) ? true : !tr.classList.contains("choisie")); if (!(e.ctrlKey || e.metaKey)) for (const autre of corps.children) if (autre !== tr) autre.classList.remove("choisie"); } } });
    for (const c of colonnes) tr.append(cellule(nom, ligne, c, i));
    corps.append(tr);
  });
  table.append(corps);
  ajusterColonnes(table, colonnes);
  $("#n-" + nom).textContent = "· " + lignes.filter(l => (l.reference || "").trim()).length;
  rafraichirResumes();
}

function utilisee(c, l) {
  const v = l[c.cle];
  if (c.genre === "bool") return v !== DEFAUTS_LIGNE[l.contour !== undefined ? "pieces" : "stock"][c.cle];
  if (c.genre === "contour") return Array.isArray(v) && v.length > 0;
  if (c.genre === "nombre") return Number(v || 0) !== 0;
  return Boolean(v);
}

function cellule(nom, ligne, c, i) {
  const td = el("td", { class: c.genre === "nombre" || c.genre === "entier" ? "num" : c.genre === "bool" ? "bool" : c.genre });
  const changer = () => { etat.aJour = false; rafraichirEtat(); marquerChangement(); };
  if (c.genre === "bool") {
    td.append(el("input", { type: "checkbox", title: t(c.info), onchange: (e) => { ligne[c.cle] = e.target.checked; changer(); if (c.cle === "atelier" || nom === "stock") enregistrerAtelier(); } }));
    td.firstChild.checked = Boolean(ligne[c.cle]);
  } else if (c.genre === "choix") {
    const sel = el("select", { title: t(c.info), onchange: (e) => { ligne[c.cle] = e.target.value; changer(); } });
    for (const [v, libelle] of c.choix) sel.append(el("option", { value: v, text: t(libelle) }));
    sel.value = ligne[c.cle];
    td.append(sel);
  } else if (c.genre === "contour") {
    const n = (ligne.contour || []).length;
    const nt = (ligne.trous || []).length;
    td.textContent = n ? t`◇ ${n} pts` + (nt ? t` · ${nt} trou${nt > 1 ? "s" : ""}` : "") : "";
    td.title = t(c.info);
  } else {
    const input = el("input", { type: "text", title: t(c.info), value: ligne[c.cle] ?? "", "data-colonne": c.cle,
      oninput: (e) => { ligne[c.cle] = e.target.value; e.target.classList.toggle("faux", (c.genre === "nombre" || c.genre === "entier") && e.target.value.trim() !== "" && Number.isNaN(Number(e.target.value.replace(",", ".")))); changer(); if (nom === "stock") enregistrerAtelier(); },
      onpaste: (e) => coller(nom, i, c, e), onkeydown: (e) => touche(nom, i, e) });
    if (c.genre === "matiere" || c.genre === "planche") {
      const liste = "l-" + nom + "-" + c.cle;
      input.setAttribute("list", liste);
      // Relue À CHAQUE OUVERTURE, comme le menu du bureau : garnie une
      // fois pour toutes au dessin de la table, elle datait de l'état
      // d'alors — après un import en douglas, la table du stock n'étant
      // pas redessinée, sa liste ne proposait toujours que l'ancien bois.
      const garnir = () => {
        let dl = document.getElementById(liste);
        if (!dl) { dl = el("datalist", { id: liste }); document.body.append(dl); }
        dl.replaceChildren(...(c.genre === "matiere" ? matieres() : references()).map(v => el("option", { value: v })));
      };
      garnir();
      input.addEventListener("focus", garnir);
    }
    td.append(input);
  }
  return td;
}

function touche(nom, i, e) {
  if (e.key === "Enter") { e.preventDefault(); if (i === etat[nom].length - 1) ajouterLigne(nom); const suivante = $("#t-" + nom).querySelector(`tr[data-ligne="${i + 1}"] input[type=text]`); suivante && suivante.focus(); }
  if (e.key === "Delete" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); supprimerLignes(nom, [i]); }
}

function coller(nom, i, c, e) {
  const texte = (e.clipboardData || window.clipboardData).getData("text");
  if (!texte.includes("\n") && !texte.includes("\t") && !texte.includes(";")) return;
  e.preventDefault();
  const colonnes = COLONNES[nom].filter(x => !x.avancee || etat.avancees);
  const depart = colonnes.findIndex(x => x.cle === c.cle);
  const rangs = texte.replace(/\r/g, "").replace(/\n$/, "").split("\n");
  rangs.forEach((rang, dl) => {
    const cellules = rang.includes("\t") ? rang.split("\t") : rang.split(";");
    const ligne = i + dl;
    while (ligne >= etat[nom].length) etat[nom].push({ ...DEFAUTS_LIGNE[nom] });
    cellules.forEach((cell, dc) => {
      const col = colonnes[depart + dc];
      if (!col) return;
      const v = cell.trim();
      if (col.genre === "bool") etat[nom][ligne][col.cle] = ["1", "x", "vrai", "true", "oui", "o"].includes(v.toLowerCase());
      else if (col.genre === "choix") { const trouve = col.choix.find(([k, libelle]) => k === v.toLowerCase() || libelle.toLowerCase() === v.toLowerCase() || t(libelle).toLowerCase() === v.toLowerCase()); if (trouve) etat[nom][ligne][col.cle] = trouve[0]; }
      else if (col.genre !== "contour") etat[nom][ligne][col.cle] = v;
    });
  });
  etat.aJour = false;
  rendreTable(nom); rafraichirEtat(); if (nom === "stock") enregistrerAtelier(); marquerChangement();
}

function lignesChoisies(nom) { return [...$("#t-" + nom).querySelectorAll("tr.choisie")].map(tr => Number(tr.dataset.ligne)); }
function ajouterLigne(nom) { etat[nom].push({ ...DEFAUTS_LIGNE[nom] }); etat.aJour = false; rendreTable(nom); rafraichirEtat(); marquerChangement(); const dern = $("#t-" + nom).querySelector("tbody tr:last-child input[type=text]"); dern && dern.focus(); }
function dupliquerLignes(nom) { const choisies = lignesChoisies(nom); if (!choisies.length) return; const copies = choisies.map(i => JSON.parse(JSON.stringify(etat[nom][i]))); etat[nom].splice(choisies[choisies.length - 1] + 1, 0, ...copies); etat.aJour = false; rendreTable(nom); rafraichirEtat(); if (nom === "stock") enregistrerAtelier(); marquerChangement(); }
function supprimerLignes(nom, lignes = lignesChoisies(nom)) { for (const i of [...lignes].sort((a, b) => b - a)) etat[nom].splice(i, 1); etat.aJour = false; rendreTable(nom); rafraichirEtat(); if (nom === "stock") enregistrerAtelier(); marquerChangement(); }

function rafraichirResumes() {
  const pieces = etat.pieces.filter(p => (p.reference || "").trim());
  const ex = pieces.reduce((n, p) => n + (Number(p.quantite) || 1), 0);
  const contours = pieces.filter(p => (p.contour || []).length).length;
  $("#r-pieces").textContent = pieces.length ? t`${pieces.length} référence(s), ${ex} exemplaire(s)` + (contours ? t` dont ${contours} contour(s) à imbriquer` : "") + t` · ${[...new Set(pieces.map(p => p.matiere).filter(Boolean))].join(", ") || t("matière non renseignée")}` : t("Aucune pièce — ajoutez une ligne, collez un tableau (Ctrl+V), importez un CSV ou des contours SVG.");
  const stock = etat.stock.filter(s => (s.reference || "").trim());
  const chutes = stock.filter(s => s.chute).reduce((n, s) => n + (Number(s.quantite) || 1), 0);
  const atelierN = stock.filter(s => s.atelier).length;
  $("#r-stock").textContent = stock.length ? t`${stock.length} référence(s)` + (atelierN ? t` · ${atelierN} de l'atelier` : "") + (chutes ? t` · ${chutes} chute(s) à écouler d'abord` : "") : t("Stock vide — le débit n'aura rien où se poser.");
}

// -- réglages ------------------------------------------------------------------------

function rendreReglages() {
  const zone = $("#reglages");
  zone.replaceChildren();
  for (const [titre, champs, cible = "parametres"] of [...REGLAGES, ...REGLAGES_GCODE]) {
    zone.append(el("h3", { text: t(titre) }));
    for (const [cle, libelle, genre, info, choix] of champs) {
      const ou = etat[cible];
      zone.append(el("label", { text: t(libelle), title: t(info) }));
      let champ;
      if (genre === "choix") {
        champ = el("select", { onchange: (e) => { ou[cle] = isNaN(Number(e.target.value)) || e.target.value === "" ? e.target.value : Number(e.target.value); changerReglage(cible); } });
        for (const [v, libelle] of choix) champ.append(el("option", { value: v, text: t(libelle) }));
        champ.value = String(ou[cle]);
      } else if (genre === "bool") {
        champ = el("input", { type: "checkbox", onchange: (e) => { ou[cle] = e.target.checked; changerReglage(cible); } });
        champ.checked = Boolean(ou[cle]);
      } else {
        champ = el("input", { type: "number", step: genre === "entier" ? 1 : 0.5, min: 0, value: ou[cle], oninput: (e) => { ou[cle] = Number(e.target.value); changerReglage(cible); } });
      }
      zone.append(champ);
      zone.append(el("p", { class: "discret", text: t(info) }));
    }
  }
}
function changerReglage(cible = "parametres") {
  // Les réglages du G-code ne changent pas le plan : le périmer ferait
  // recalculer une heure de fraisage pour un diamètre de fraise.
  if (cible === "parametres") { etat.aJour = false; rafraichirEtat(); }
  stockage.ecrire(cible, etat[cible]);
  brouillonPlusTard();
}

// -- calcul ---------------------------------------------------------------------------

async function calculer() {
  if (!pythonPret) return;
  const pieces = etat.pieces.filter(p => (p.reference || "").trim());
  if (!pieces.length) { alerter(t("Aucune pièce à débiter.")); return; }
  $("#etat").textContent = t("Calcul…");
  $("#b-calculer").disabled = true;
  $("#b-interrompre").hidden = false;
  try {
    const entree = JSON.stringify({ pieces, stock: etat.stock.filter(s => (s.reference || "").trim()), parametres: { ...etat.parametres, processus: 1 }, epingles: etat.epingles });
    await precalculerNfp(entree);
    $("#etat").textContent = t("Calcul…");
    const sortie = JSON.parse(await appeler("calculer", entree));
    if (!sortie.ok) { alerter(t("Saisie invalide : ") + sortie.erreur); $("#etat").textContent = t("Saisie invalide"); return; }
    if (sortie.epingles_relachees) { etat.epingles = []; $("#etat").textContent = t("Épingles relâchées : une planche ou une pièce a changé."); }
    else $("#etat").textContent = t("Plan à jour");
    etat.resultat = sortie.resultat;
    etat.aJour = true;
    afficherResultat();
  } catch (erreur) {
    if (erreur.message === "interrompu") { $("#etat").textContent = t("Calcul interrompu — le plan précédent reste affiché"); }
    else { alerter(t("Le calcul a échoué : ") + erreur.message); $("#etat").textContent = t("Échec du calcul"); }
  } finally {
    $("#b-calculer").disabled = false;
    $("#b-interrompre").hidden = true;
  }
}

function alerter(texte) { window.alert(texte); }

function afficherResultat() {
  const r = etat.resultat;
  const b = r.bilan;
  const tuiles = [
    [t("Pièces posées"), t`${b.nb_posees} / ${b.nb_demandees}`, b.nb_non_placees ? t`${b.nb_non_placees} non placée(s)` : "", b.nb_non_placees ? "alerte" : ""],
    [t("Rendement"), pct(b.rendement) + " %", m2(b.surface_pieces) + t(" m² de pièces"), ""],
    [t("Planches entamées"), String(b.nb_planches_entamees), b.nb_chutes_consommees ? t`dont ${b.nb_chutes_consommees} chute(s)` : t("aucune chute écoulée"), ""],
    [t("Pertes"), m2(b.surface_perdue) + " m²", b.longueur_fraisage > 0 ? t`${dec((b.longueur_fraisage / 1000).toFixed(1))} m de fraisage ≈ ${Math.round(b.longueur_fraisage / Math.max(etat.parametres.vitesse_fraisage || 1500, 1))} min` : t`sciure et rebuts · ${b.nb_coupes} coupe(s)`, ""],
    [t("Chutes créées"), String(r.chutes_groupees.reduce((n, c) => n + c.nombre, 0)), b.surface_chutes_creees ? m2(b.surface_chutes_creees) + t(" m² à ranger") : t("rien à garder"), b.surface_chutes_creees ? "accent" : ""],
    [t("À acheter"), String(r.achats.reduce((n, a) => n + a.nombre, 0)), r.cout ? r.cout.toFixed(2) + " €" : t("prix non renseignés"), ""],
  ];
  $("#tuiles").replaceChildren(...tuiles.map(([l, v, d, ton]) => el("div", { class: "tuile " + ton }, el("div", { class: "libelle", text: l }), el("div", { class: "valeur", text: v }), el("div", { class: "detail", text: d }))));
  $("#l-achats").replaceChildren(...r.achats.map(a => el("li", { text: t`${a.nombre} × « ${a.reference} » — ${mm(a.longueur)} × ${mm(a.largeur)} × ${mm(a.epaisseur)} mm, ${a.matiere}` + (a.prix ? t` — ${(a.nombre * a.prix).toFixed(2)} €` : "") })));
  $("#n-achats").textContent = "· " + r.achats.reduce((n, a) => n + a.nombre, 0);
  $("#l-chutes").replaceChildren(...r.chutes_groupees.map(c => el("li", { text: t`${c.nombre} ×  ${mm(c.dim_x)} × ${mm(c.dim_y)} × ${mm(c.epaisseur)} mm — ${c.matiere}${c.biscornue ? t` (biscornue, ${c.sommets} sommets)` : ""}` })));
  $("#n-chutes").textContent = "· " + r.chutes_groupees.reduce((n, c) => n + c.nombre, 0);
  $("#b-ranger").disabled = !r.chutes_groupees.length;
  $("#l-non").replaceChildren(...r.non_placees.map(n => el("li", { class: "rouge", text: t`« ${n.reference} » ×${n.exemplaires} — ${t(n.raison)}` })));
  $("#n-non").textContent = b.nb_non_placees ? "· " + b.nb_non_placees : "";
  $("#m-non").textContent = r.non_placees.length ? t("Ces pièces n'ont trouvé aucune place. Ajoutez du stock, relâchez le fil, ou cochez « Composable ».") : t("Tout est passé — aucune pièce laissée de côté.");
  etat.planche = 1;
  dessinerPlan();
  rendreImpression();
}

// -- le plan --------------------------------------------------------------------------

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}, ...enfants) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); for (const c of enfants) e.append(c); return e; };

// Le tracé SVG d'anneaux (extérieur puis trous), y retourné par Y.
const chemin = (anneaux, Y) => anneaux.map(anneau => "M" + anneau.map(([px, py]) => `${px} ${Y(py)}`).join(" L") + " Z").join(" ");

function dessinerPlan() {
  const zone = $("#plan");
  const r = etat.resultat;
  if (!r || !r.debits.length) { zone.replaceChildren(el("p", { class: "vide", id: "plan-vide", text: t(RAISONS_VIDE) })); $("#legende").replaceChildren(); return; }
  const L = Math.max(...r.debits.map(d => d.planche.longueur));
  const police = L / 110;                       // mm de scène : le plan est en mm
  const cartouche = L / 85;
  const bande = cartouche * 2.2, interligne = cartouche * 1.4;
  const svg = svgEl("svg", { xmlns: NS });
  const defs = svgEl("defs");
  defs.append(motif("hachure-chute", "#767c85", "#faf8f4", L / 400), motif("hachure-defaut", "#a85a52", "#faf8f4", L / 400, true));
  svg.append(defs);
  let y = 0;
  r.debits.forEach((d, idx) => {
    const numero = idx + 1;
    const pl = d.planche;
    const epinglee = numero <= etat.epingles.length;
    const groupe = svgEl("g", { "data-planche": numero, class: "planche" });
    groupe.append(svgEl("text", { x: 0, y: y + cartouche, "font-size": cartouche, "font-weight": "bold", class: "cartouche" }, t`${numero}.  ${pl.reference}${d.plusieurs ? t` (ex. ${d.exemplaire})` : ""}   —   ${mm(pl.longueur)} × ${mm(pl.largeur)} × ${mm(pl.epaisseur)} mm, ${pl.matiere}${pl.chute ? t(" [chute]") : pl.illimite ? t(" [catalogue]") : ""}   —   ${d.poses.length} pièce(s), rendement ${pct(d.rendement)} %${d.imbriquee ? t`   —   ${dec((d.longueur_fraisage / 1000).toFixed(1))} m de fraisage` : ""}${epinglee ? t("   —   ÉPINGLÉE") : ""}`));
    y += bande;
    const yh = y;
    const Y = (v, h = 0) => yh + pl.largeur - v - h;
    if ((pl.contour || []).length) {
      // Une chute biscornue : sa forme en papier, sa boîte en pointillé.
      groupe.append(svgEl("rect", { x: 0, y: yh, width: pl.longueur, height: pl.largeur, fill: "none", stroke: "#767c85", "stroke-width": L / 800, "stroke-dasharray": `${L / 200} ${L / 200}` }));
      groupe.append(svgEl("path", { d: chemin([pl.contour, ...(pl.trous || [])], Y), "fill-rule": "evenodd", fill: "#faf8f4", stroke: "#2f3540", "stroke-width": L / 500 }));
    } else {
      groupe.append(svgEl("rect", { x: 0, y: yh, width: pl.longueur, height: pl.largeur, fill: "#faf8f4", stroke: "#2f3540", "stroke-width": L / 500 }));
    }
    // recoupes et défauts
    for (const [x, yy, dx, dy] of zonesEcartees(pl)) groupe.append(svgEl("rect", { x, y: Y(yy, dy), width: dx, height: dy, fill: "url(#hachure-defaut)", stroke: "#a85a52", "stroke-width": L / 1200 }));
    for (const c of d.chutes) {
      if ((c.contour || []).length) {
        groupe.append(svgEl("path", { d: chemin([c.contour, ...(c.trous || [])], Y), "fill-rule": "evenodd", fill: "url(#hachure-chute)", stroke: "#767c85", "stroke-width": L / 1200 }));
        const [cx, cy] = centreDeGravite(c.contour);
        groupe.append(...etiquette(t("chute biscornue"), t`${mm(c.dim_x)} × ${mm(c.dim_y)}`, cx - c.dim_x * 0.3, Y(cy) - c.dim_y * 0.3, c.dim_x * 0.6, c.dim_y * 0.6, police, "#2f3540"));
      } else {
        groupe.append(svgEl("rect", { x: c.x, y: Y(c.y, c.dim_y), width: c.dim_x, height: c.dim_y, fill: "url(#hachure-chute)", stroke: "#767c85", "stroke-width": L / 1200 }));
        groupe.append(...etiquette(t`chute`, t`${mm(c.dim_x)} × ${mm(c.dim_y)}`, c.x, Y(c.y, c.dim_y), c.dim_x, c.dim_y, police, "#2f3540"));
      }
    }
    d.poses.forEach((p, ip) => {
      const couleur = r.couleurs[p.reference] || "#ddd";
      let forme;
      if (p.contour.length) {
        forme = svgEl("path", { d: chemin([p.contour, ...p.trous], Y), "fill-rule": "evenodd", fill: couleur, stroke: "#2f3540", "stroke-width": L / 1500 });
      } else {
        forme = svgEl("rect", { x: p.x, y: Y(p.y, p.dim_y), width: p.dim_x, height: p.dim_y, fill: couleur, stroke: "#2f3540", "stroke-width": L / 1500 });
      }
      forme.setAttribute("data-planche", numero); forme.setAttribute("data-pose", ip);
      forme.append(svgEl("title", {}, t`${p.reference} ${p.exemplaire}/${p.quantite} — ${mm(p.dim_x)} × ${mm(p.dim_y)} en (${mm(p.x)}, ${mm(p.y)})${p.angle ? t`, tournée de ${mm(p.angle)}°` : p.pivotee ? t(", pivotée") : ""}`));
      groupe.append(forme);
      if (p.contour.length) {
        // Le nom seul, au centre de gravité — ou, pour une forme à trou
        // (dont le centre de gravité est DANS le trou), dans la barre du
        // bas, entre le bord et le trou le plus bas.
        let cx, cy, bx = p.dim_x * 0.6, by = p.dim_y * 0.6;
        if (p.trous.length) {
          const basTrou = Math.min(...p.trous.flat().map(q => q[1]));
          cx = p.x + p.dim_x / 2; cy = (p.y + basTrou) / 2; by = Math.max(basTrou - p.y, 1);
        } else [cx, cy] = centreDeGravite(p.contour);
        groupe.append(...etiquette(p.reference, "", cx - bx / 2, Y(cy) - by / 2, bx, by, police, "#2f3540"));
      } else {
        groupe.append(...etiquette(p.reference, t`${mm(p.dim_x)} × ${mm(p.dim_y)}`, p.x, Y(p.y, p.dim_y), p.dim_x, p.dim_y, police, "#2f3540"));
      }
    });
    if (etat.traits) for (const c of d.coupes) {
      const trait = c.sens === "delignage"
        ? svgEl("line", { x1: c.de, y1: Y(c.position), x2: c.a, y2: Y(c.position) })
        : svgEl("line", { x1: c.position, y1: Y(c.de), x2: c.position, y2: Y(c.a) });
      trait.setAttribute("stroke", "#c0392b"); trait.setAttribute("stroke-width", L / 700); trait.setAttribute("stroke-dasharray", `${L / 150} ${L / 300}`);
      groupe.append(trait);
      const [nx, ny] = c.sens === "delignage" ? [c.de + police * 0.2, Y(c.position) - police * 0.2] : [c.position + police * 0.2, Y(c.a) + police * 0.9];
      groupe.append(svgEl("text", { x: nx, y: ny, "font-size": police * 0.8, "font-weight": "bold", fill: "#c0392b" }, String(c.ordre)));
    }
    if (epinglee) groupe.append(svgEl("rect", { x: 0, y: yh, width: pl.longueur, height: pl.largeur, fill: "none", stroke: "#2f3540", "stroke-width": L / 300, "stroke-dasharray": `${L / 100} ${L / 200}` }));
    if (numero === etat.planche) groupe.append(svgEl("rect", { x: 0, y: yh, width: pl.longueur, height: pl.largeur, fill: "none", stroke: "#ff8a00", "stroke-width": L / 600 }));
    svg.append(groupe);
    y += pl.largeur + interligne;
  });
  const H = y - interligne;
  svg.setAttribute("viewBox", `0 0 ${L} ${H}`);
  zone.replaceChildren(svg);
  ajusterZoom();
  // légende
  const comptes = {};
  for (const d of r.debits) for (const p of d.poses) comptes[p.reference] = (comptes[p.reference] || 0) + 1;
  const legende = Object.entries(comptes).map(([ref, n]) => el("span", {}, el("span", { class: "pastille", style: `background:${r.couleurs[ref]}` }), t`${ref} ×${n}`));
  if (r.debits.some(d => d.chutes.length)) legende.push(el("span", {}, el("span", { class: "pastille", style: "background: repeating-linear-gradient(45deg,#faf8f4,#faf8f4 2px,#767c85 2px,#767c85 3px)" }), t("chute réutilisable")));
  if (r.debits.some(d => zonesEcartees(d.planche).length)) legende.push(el("span", {}, el("span", { class: "pastille", style: "background: repeating-linear-gradient(45deg,#faf8f4,#faf8f4 2px,#a85a52 2px,#a85a52 3px)" }), t("défaut écarté")));
  legende.push(el("span", {}, el("span", { class: "pastille", style: "background:#faf8f4" }), t("perte")));
  $("#legende").replaceChildren(...legende);
}

function motif(id, trait, fond, pas, croise = false) {
  const p = svgEl("pattern", { id, patternUnits: "userSpaceOnUse", width: pas * 4, height: pas * 4 });
  p.append(svgEl("rect", { width: pas * 4, height: pas * 4, fill: fond }));
  p.append(svgEl("path", { d: `M0 ${pas * 4} L${pas * 4} 0`, stroke: trait, "stroke-width": pas / 3 }));
  if (croise) p.append(svgEl("path", { d: `M0 0 L${pas * 4} ${pas * 4}`, stroke: trait, "stroke-width": pas / 3 }));
  return p;
}

function zonesEcartees(pl) {
  const z = [];
  if (pl.recoupe_bouts > 0) { z.push([0, 0, pl.recoupe_bouts, pl.largeur]); z.push([pl.longueur - pl.recoupe_bouts, 0, pl.recoupe_bouts, pl.largeur]); }
  if (pl.recoupe_rives > 0) { z.push([0, 0, pl.longueur, pl.recoupe_rives]); z.push([0, pl.largeur - pl.recoupe_rives, pl.longueur, pl.recoupe_rives]); }
  for (const d of pl.defauts || []) z.push(d);
  return z;
}

function centreDeGravite(pts) {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    const d = x1 * y2 - x2 * y1; a += d; cx += (x1 + x2) * d; cy += (y1 + y2) * d;
  }
  return Math.abs(a) < 1e-9 ? pts[0] : [cx / (3 * a), cy / (3 * a)];
}

// Une étiquette qui tient dans sa case : deux lignes, une ligne, le nom seul, ou rien.
function etiquette(nom, cotes, x, y, dx, dy, police, encre) {
  const largeurTexte = (texte, f) => texte.length * f * 0.56;
  const taille = Math.min(police * 1.4, Math.max(police * 0.8, dy * 0.22));
  const variantes = [[[nom, cotes], taille], [[t`${nom} · ${cotes}`], taille], [[nom], taille * 0.9]];
  for (const [lignes, f] of variantes) {
    const lignesUtiles = lignes.filter(Boolean);
    if (Math.max(...lignesUtiles.map(l => largeurTexte(l, f))) <= dx * 0.95 && lignesUtiles.length * f * 1.15 <= dy * 0.95) {
      return lignesUtiles.map((l, i) => svgEl("text", { x: x + dx / 2, y: y + dy / 2 + (i - (lignesUtiles.length - 1) / 2) * f * 1.15 + f * 0.35, "font-size": f, "text-anchor": "middle", fill: encre, "pointer-events": "none" }, l));
    }
  }
  return [];
}

function ajusterZoom() {
  const svg = $("#plan svg");
  if (!svg) return;
  const zone = $("#plan");
  const [, , L, H] = svg.getAttribute("viewBox").split(" ").map(Number);
  const echelle = Math.min((zone.clientWidth - 16) / L, (zone.clientHeight - 16) / H);
  const largeur = L * echelle * etat.zoom;
  svg.setAttribute("width", largeur); svg.setAttribute("height", H * echelle * etat.zoom);
  svg.style.margin = "8px";
}

// -- impression : cotes et coupes sous le plan --------------------------------------------

function rendreImpression() {
  const r = etat.resultat;
  const zone = $("#impression");
  zone.replaceChildren();
  if (!r) return;
  zone.append(el("h3", { text: (etat.nomProjet || t("Feuille de débit")) + t` — ${r.bilan.nb_posees}/${r.bilan.nb_demandees} pièce(s), rendement ${pct(r.bilan.rendement)} %, ${r.bilan.nb_planches_entamees} planche(s), pertes ${m2(r.bilan.surface_perdue)} m²` }));
  r.debits.forEach((d, i) => {
    const lots = {};
    for (const p of d.poses) { const k = t`${p.reference} ${mm(p.dim_x)} × ${mm(p.dim_y)}`; lots[k] = (lots[k] || 0) + 1; }
    zone.append(el("p", {}, el("b", { text: `${i + 1}.  ` }), Object.entries(lots).map(([k, n]) => k + (n > 1 ? ` ×${n}` : "")).join("   ·   ")));
    zone.append(el("p", { text: d.imbriquee ? t("découpe CNC : contours imbriqués, à exporter en SVG") : t("coupes :  ") + d.coupes.map(c => t`${c.ordre} ${c.sens === "tronconnage" ? "↕" : "↔"} ${mm(c.position)}`).join("   ·   ") }));
  });
  zone.append(el("p", { class: "discret", text: t("↕ tronçonnage, en travers du fil, à x mm du bout gauche — ↔ délignage, le long du fil, à y mm de la rive basse.") }));
}

// -- fichiers ------------------------------------------------------------------------------

function telecharger(nom, texte, type = "text/plain") {
  const a = el("a", { href: URL.createObjectURL(new Blob([texte], { type })), download: nom });
  document.body.append(a); a.click(); a.remove();
}
function lireFichier(input, binaire = false) { return new Promise((resolve) => { input.onchange = () => { const f = input.files[0]; input.value = ""; if (!f) return resolve(null); const lecteur = new FileReader(); lecteur.onload = () => resolve({ nom: f.name, texte: binaire ? lecteur.result.split(",")[1] : lecteur.result }); binaire ? lecteur.readAsDataURL(f) : lecteur.readAsText(f); }; input.click(); }); }

async function ouvrirProjet() {
  const f = await lireFichier($("#f-projet")); if (!f) return;
  const brut = await tenter("depuis_projet", f.texte); if (brut === null) return;
  const d = JSON.parse(brut);
  if (d.erreur) { alerter(t("Ouverture impossible : ") + d.erreur); return; }
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.stock = [...d.stock.filter(s => !s.atelier).map(s => ({ ...DEFAUTS_LIGNE.stock, ...s })), ...atelier()];
  etat.parametres = { ...etat.parametres, ...d.parametres };
  etat.epingles = d.epingles || [];
  etat.nomProjet = f.nom.replace(/\.json$/i, "");
  rendreTout(); calculer(); marquerChangement();
}
async function enregistrerProjet() {
  const texte = await tenter("vers_projet", JSON.stringify({ pieces: etat.pieces, stock: etat.stock.filter(s => !s.atelier), parametres: etat.parametres, epingles: etat.epingles }));
  if (texte === null) return;
  telecharger((etat.nomProjet || "debit") + ".json", texte, "application/json");
  enregistrerAtelier();
}
async function importerCsv() {
  const f = await lireFichier($("#f-csv")); if (!f) return;
  const brut = await tenter("depuis_csv", f.texte); if (brut === null) return;
  const d = JSON.parse(brut);
  if (d.erreur) { alerter(t("Import impossible : ") + d.erreur); return; }
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.aJour = false; rendreTable("pieces"); rafraichirEtat(); marquerChangement();
  signalerMatieresOrphelines(d.pieces.length, f.nom);
}

/**
 * Des pièces importées dans un bois que le stock n'a pas, c'est un débit
 * qui ne placera rien — et le seul endroit où on le lisait était l'onglet
 * des pièces non placées, après un calcul. On le dit tout de suite, avec
 * les deux mots en présence : la faute est presque toujours une majuscule
 * ou une espace. (Le bureau le fait depuis la 1.2.3 ; la page se taisait.)
 */
function signalerMatieresOrphelines(nombre, source) {
  const duStock = new Set(etat.stock.map(s => (s.matiere || "").trim()).filter(Boolean));
  const orphelines = [...new Set(etat.pieces.map(p => (p.matiere || "").trim()).filter(Boolean))]
    .filter(m => !duStock.has(m));
  if (!orphelines.length || !duStock.size) {
    $("#etat").textContent = t`${nombre} pièce(s) lue(s) dans ${source}`;
    return;
  }
  $("#etat").textContent = t`${nombre} pièce(s) lue(s) dans ${source} — mais aucune planche en ${orphelines.join(", ")} dans le stock (il y a : ${[...duStock].sort().join(", ")}). Corrigez la colonne Matière, des deux côtés le même mot.`;
}

async function importerFcstd() {
  const f = await lireFichier($("#f-fcstd"), true); if (!f) return;
  const brut = await tenter("depuis_fcstd", f.texte); if (brut === null) return;
  const d = JSON.parse(brut);
  if (d.erreur) { alerter(t("Import impossible : ") + d.erreur); return; }
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.aJour = false; rendreTable("pieces"); rafraichirEtat(); marquerChangement();
  signalerMatieresOrphelines(d.pieces.length, f.nom);
}
async function exporterCsv() { const texte = await tenter("vers_csv", JSON.stringify(etat.pieces)); if (texte !== null) telecharger((etat.nomProjet || "pieces") + ".csv", texte, "text/csv"); }
async function importerSvg() {
  const f = await lireFichier($("#f-svg")); if (!f) return;
  const brut = await tenter("depuis_svg", f.texte); if (brut === null) return;
  const d = JSON.parse(brut);
  if (d.erreur) { alerter(t("Import impossible : ") + d.erreur); return; }
  if (!d.formes.length) { alerter(t("Aucun tracé fermé dans ce SVG.\n") + d.avertissements.join("\n")); return; }
  window.chutier.ajouterFormes(d.formes);
  etat.aJour = false; rafraichirEtat();
  if (d.avertissements.length) alerter(t`${d.formes.length} contour(s) importé(s)\n\n` + d.avertissements.join("\n"));
  else $("#etat").textContent = t`${d.formes.length} contour(s) importé(s)`;
}
const FORMATS_DECOUPE = { svg: ["svg", "image/svg+xml"], dxf: ["dxf", "application/dxf"], lbrn: ["lbrn", "application/xml"], gcode: ["ngc", "text/plain"] };
async function exporterDecoupe(format) {
  if (!etat.resultat) { alerter(t("Calculez d'abord le débit.")); return; }
  const titre = etat.nomProjet || t("Feuille de débit");
  const [extension, type] = FORMATS_DECOUPE[format];
  for (const [i, d] of etat.resultat.debits.entries()) {
    const texte = await tenter("decoupe", format, JSON.stringify(d.epingle), i + 1, titre, format === "gcode" ? JSON.stringify(etat.gcode) : "");
    if (texte === null) return;
    // Un débit mal formé revient en JSON d'erreur, pas en dessin : un SVG
    // commence par « <?xml », un DXF par « 999 », jamais par « { ».
    if (texte.startsWith('{"erreur"')) { alerter(t("Le calcul a échoué : ") + JSON.parse(texte).erreur); return; }
    telecharger(`${titre}-planche-${i + 1}.${extension}`, texte, type);
    await new Promise(r => setTimeout(r, 300));
  }
}
function exporterFiche() { if (!etat.resultat) { alerter(t("Calculez d'abord le débit.")); return; } telecharger((etat.nomProjet || "fiche-atelier") + ".txt", (etat.nomProjet || t("Feuille de débit")) + "\n\n" + etat.resultat.fiche + "\n"); }

function rangerChutes() {
  const r = etat.resultat;
  if (!r || !etat.aJour) { alerter(t("Recalculez avant de ranger les chutes : la saisie a changé depuis le dernier calcul.")); return; }
  if (!window.confirm(t("Le stock sera mis à jour comme si le débit était fait : planches entamées en moins, chutes créées en plus, à l'atelier de ce navigateur. Continuer ?"))) return;
  etat.stock = r.stock_apres.map(s => ({ ...DEFAUTS_LIGNE.stock, ...s, defauts_texte: defautsTexte(s) }));
  etat.aJour = false; rendreTable("stock"); rafraichirEtat(); enregistrerAtelier();
  $("#etat").textContent = t("Stock de l'atelier mis à jour dans ce navigateur.");
}
function defautsTexte(s) {
  // « bouts » et « rives » sont la SYNTAXE que Python relit : jamais traduites.
  const morceaux = [];
  if (s.recoupe_bouts > 0) morceaux.push("bouts " + mm(s.recoupe_bouts));
  if (s.recoupe_rives > 0) morceaux.push("rives " + mm(s.recoupe_rives));
  for (const [x, y, dx, dy] of s.defauts || []) morceaux.push(y === 0 && y + dy === s.largeur ? `${mm(x)}-${mm(x + dx)}` : [x, y, dx, dy].map(mm).join(","));
  return morceaux.join(" ; ");
}

// -- épingles et planche imposée --------------------------------------------------------

function menuContextuel(e) {
  const cible = e.target.closest("[data-planche]");
  if (!cible || !etat.resultat) return;
  e.preventDefault();
  const numero = Number(cible.dataset.planche);
  const ip = cible.dataset.pose;
  const pose = ip !== undefined ? etat.resultat.debits[numero - 1].poses[Number(ip)] : null;
  const menu = $("#menu-contextuel");
  menu.replaceChildren();
  const epinglee = numero <= etat.epingles.length;
  menu.append(el("button", { text: epinglee ? t`Relâcher la planche ${numero}` : t`Épingler la planche ${numero} — la garder telle quelle`, onclick: () => { fermerMenu(); if (epinglee) etat.epingles.splice(numero - 1, 1); else etat.epingles.push(etat.resultat.debits[numero - 1].epingle); calculer(); } }));
  if (pose) {
    menu.append(el("div", { class: "sep" }), el("div", { class: "titre", text: t`Tailler « ${pose.reference} » dans…` }));
    for (const ref of references()) menu.append(el("button", { text: ref, onclick: () => { fermerMenu(); imposerPlanche(pose.reference, ref); } }));
    menu.append(el("button", { text: t("Laisser le chutier choisir"), onclick: () => { fermerMenu(); imposerPlanche(pose.reference, ""); } }));
  }
  menu.style.left = e.clientX + "px"; menu.style.top = e.clientY + "px"; menu.hidden = false;
  etat.planche = numero; dessinerPlan();
}
function fermerMenu() { $("#menu-contextuel").hidden = true; }

// -- la largeur de la saisie ----------------------------------------------------------
// Douze colonnes de stock ne tiennent pas dans un tiers d'écran : la
// table défilait en travers, et sa barre venait buter sur la ligne de
// résumé. On donne la poignée, comme au bureau — et le navigateur s'en
// souvient.

const LARGEUR_MINI = 380;

function poserLargeur(px) {
  const maxi = Math.max(LARGEUR_MINI, window.innerWidth - 420);
  const large = Math.min(Math.max(px, LARGEUR_MINI), maxi);
  document.documentElement.style.setProperty("--saisie", large + "px");
  stockage.ecrire("largeurSaisie", large);
  ajusterZoom();
}

function brancherPoignee() {
  const poignee = $("#poignee");
  const garde = stockage.lire("largeurSaisie", 0);
  if (garde) poserLargeur(garde);
  let attrape = false;
  poignee.addEventListener("pointerdown", (e) => {
    attrape = true;
    try { poignee.setPointerCapture(e.pointerId); } catch (_) { /* synthétique */ }
    e.preventDefault();
  });
  poignee.addEventListener("pointermove", (e) => {
    if (attrape) poserLargeur(e.clientX - $("main").getBoundingClientRect().left);
  });
  poignee.addEventListener("pointerup", () => { attrape = false; });
  poignee.addEventListener("dblclick", () => {
    document.documentElement.style.removeProperty("--saisie");
    stockage.ecrire("largeurSaisie", 0);
    ajusterZoom();
  });
  poignee.addEventListener("keydown", (e) => {
    const pas = e.shiftKey ? 60 : 20;
    if (e.key === "ArrowLeft") { poserLargeur($(".saisie").clientWidth - pas); e.preventDefault(); }
    else if (e.key === "ArrowRight") { poserLargeur($(".saisie").clientWidth + pas); e.preventDefault(); }
  });
}

// -- glisser une pièce imbriquée -----------------------------------------------------------
// Le pointeur prend la forme ; au relâchement, le cœur valide (dans le
// bois, à l'écart des autres), refait les chutes, et la planche s'épingle
// d'elle-même — sinon le prochain calcul déferait la main.
let glisse = null;
function debutGlisse(e) {
  if (e.button !== 0 || !etat.resultat) return;
  const forme = e.target.closest("[data-pose]");
  if (!forme) return;
  const numero = Number(forme.dataset.planche), ip = Number(forme.dataset.pose);
  const d = etat.resultat.debits[numero - 1];
  if (!d.imbriquee) return;
  const svg = forme.ownerSVGElement;
  const ctm = svg.getScreenCTM();
  glisse = { forme, numero, ip, x0: e.clientX, y0: e.clientY, echelle: ctm.a, dx: 0, dy: 0 };
  try { forme.setPointerCapture(e.pointerId); } catch (_) { /* pointeur synthétique */ }
  forme.style.cursor = "grabbing";
  e.preventDefault();
}
function mouvementGlisse(e) {
  if (!glisse) return;
  glisse.dx = (e.clientX - glisse.x0) / glisse.echelle;
  glisse.dy = (e.clientY - glisse.y0) / glisse.echelle;
  glisse.forme.setAttribute("transform", `translate(${glisse.dx} ${glisse.dy})`);
}
async function finGlisse(e) {
  if (!glisse) return;
  const g = glisse; glisse = null;
  g.forme.style.cursor = "";
  if (Math.abs(g.dx) < 0.5 && Math.abs(g.dy) < 0.5) { g.forme.removeAttribute("transform"); return; }
  try {
    const entree = JSON.stringify({ pieces: etat.pieces.filter(p => (p.reference || "").trim()), stock: etat.stock.filter(s => (s.reference || "").trim()), parametres: { ...etat.parametres, processus: 1 } });
    const avant = JSON.stringify({ debits: etat.resultat.debits.map(d => d.epingle), non_placees: etat.resultat.non_placees });
    // Le SVG a y vers le bas, la planche vers le haut.
    const sortie = JSON.parse(await appeler("deplacer", entree, avant, g.numero, g.ip, Math.round(g.dx * 100) / 100, -Math.round(g.dy * 100) / 100, etat.epingles.length));
    if (!sortie.ok) { $("#etat").textContent = sortie.refus || (t("Le calcul a échoué : ") + sortie.erreur); dessinerPlan(); return; }
    // Le résultat ENTIER est refait : bilan, chutes groupées et stock
    // d'après en dépendent, et « Ranger les chutes au stock » rangerait
    // sinon les chutes d'avant le déplacement.
    etat.resultat = sortie.resultat;
    if (g.numero <= etat.epingles.length) etat.epingles[g.numero - 1] = sortie.resultat.debits[g.numero - 1].epingle;
    else etat.epingles.push(sortie.resultat.debits[etat.epingles.length].epingle);
    etat.planche = etat.epingles.length;
    afficherResultat();
    $("#etat").textContent = t("Pièce déplacée — planche épinglée : reprise telle quelle au prochain calcul.");
    consigner(); enregistrerBrouillon(); brouillonPlusTard();
  } catch (erreur) {
    // Un calcul interrompu (Échap) rejette les promesses en attente : la
    // pièce garderait sinon le décalage que la souris lui a donné.
    $("#etat").textContent = t("Le calcul a échoué : ") + erreur.message;
    dessinerPlan();
  }
}
function imposerPlanche(reference, planche) { for (const p of etat.pieces) if (p.reference === reference) p.planche = planche; etat.avancees = etat.avancees || Boolean(planche); rendreTable("pieces"); calculer(); }

// -- fenêtre --------------------------------------------------------------------------------

function rafraichirEtat() {
  if (!etat.resultat) $("#etat").textContent = pythonPret ? t("Aucun calcul") : $("#etat").textContent;
  else if (!etat.aJour) $("#etat").textContent = t("⚠ Saisie modifiée — F5 pour recalculer");
}
function rendreTout() { rendreTable("pieces"); rendreTable("stock"); rendreReglages(); rafraichirEtat(); }

function nouveau() {
  etat.pieces = [{ ...DEFAUTS_LIGNE.pieces }];
  etat.stock = atelier();
  if (!etat.stock.length) etat.stock.push({ ...DEFAUTS_LIGNE.stock });
  etat.epingles = []; etat.resultat = null; etat.aJour = false; etat.nomProjet = "";
  rendreTout(); dessinerPlan(); $("#tuiles").replaceChildren(); rendreImpression(); marquerChangement();
}

async function chargerExemple(fn = "exemple") {
  const brut = await tenter(fn); if (brut === null) return;
  const d = JSON.parse(brut);
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.stock = [...d.stock.map(s => ({ ...DEFAUTS_LIGNE.stock, ...s })), ...atelier()];
  etat.parametres = { ...etat.parametres, ...d.parametres };
  etat.epingles = []; etat.nomProjet = "";
  rendreTout(); calculer(); marquerChangement();
}

async function demarrer() {
  const defauts = JSON.parse(await appeler("parametres_defaut"));
  etat.parametres = { ...defauts, ...stockage.lire("parametres", {}) };
  const gcodeDefaut = JSON.parse(await appeler("gcode_defaut"));
  etat.gcode = { ...gcodeDefaut, ...stockage.lire("gcode", {}) };
  etat.avancees = stockage.lire("avancees", false);
  etat.traits = stockage.lire("traits", false);
  $("#c-avancees").checked = etat.avancees; $("#c-traits").checked = etat.traits;
  const b = brouillon();
  if (b && (b.pieces || []).some(p => (p.reference || "").trim())) {
    // Le projet en cours d'avant le rechargement : c'est lui qu'on reprend.
    etat.pieces = b.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
    etat.stock = [...(b.stock || []).map(s => ({ ...DEFAUTS_LIGNE.stock, ...s })), ...atelier()];
    etat.parametres = { ...etat.parametres, ...(b.parametres || {}) };
    etat.epingles = b.epingles || []; etat.nomProjet = b.nomProjet || "";
    rendreTout(); historique.courant = instantane(); calculer();
    $("#etat").textContent = t("Brouillon repris") + (b.nomProjet ? " : " + b.nomProjet : "");
  } else if (atelier().length) nouveau(); else await chargerExemple();
  historique.courant = instantane();
}

function aide() {
  alerter(t`Le geste : les pièces à débiter, le stock où les tailler, les réglages de scie, puis Calculer (F5). Le plan se lit à droite, toutes planches empilées.

Saisie : Ctrl+V colle un bloc venu d'un tableur (colonnes séparées par une tabulation ou un point-virgule) ; Entrée passe à la ligne suivante ; Ctrl+Suppr ôte la ligne ; clic sur une ligne pour la choisir, Ctrl-clic pour en ajouter.

L'atelier : les lignes de stock cochées « Atelier » restent dans ce navigateur d'un projet à l'autre. « Ranger les chutes au stock » y écrit aussitôt.

Corriger le plan : clic droit sur une planche pour l'épingler (reprise telle quelle au prochain calcul), clic droit sur une pièce pour la tailler dans une autre planche.

La CNC : Plus… → Importer des contours (SVG) ajoute aux pièces chaque tracé fermé ; dès qu'une matière compte un contour, tout ce lot est imbriqué à la fraise. Plus… → exporter la découpe sort chaque planche en SVG, DXF ou LightBurn à l'échelle 1, pour la chaîne CNC ou le laser.

Tout est en millimètres. La longueur court le long du fil. Une planche plus épaisse que la pièce convient, jamais une plus mince. Les chutes passent avant les planches neuves. Rien ne quitte votre navigateur.`);
}

function brancher() {
  $("#b-nouveau").onclick = () => { if (window.confirm(t("Vider les pièces et le stock du projet ? (l'atelier reste)"))) nouveau(); };
  $("#b-ouvrir").onclick = ouvrirProjet;
  $("#b-enregistrer").onclick = enregistrerProjet;
  $("#b-calculer").onclick = calculer;
  $("#b-interrompre").onclick = interrompre;
  $("#b-annuler").onclick = annuler;
  $("#b-refaire").onclick = refaire;
  $("#b-imprimer").onclick = () => window.print();
  $("#b-importer-csv").onclick = importerCsv;
  $("#b-importer-fcstd").onclick = importerFcstd;
  $("#b-exporter-csv").onclick = exporterCsv;
  $("#b-importer-svg").onclick = importerSvg;
  $("#b-exporter-svg").onclick = () => exporterDecoupe("svg");
  $("#b-exporter-dxf").onclick = () => exporterDecoupe("dxf");
  $("#b-exporter-lbrn").onclick = () => exporterDecoupe("lbrn");
  $("#b-exporter-gcode").onclick = () => exporterDecoupe("gcode");
  $("#b-fiche").onclick = exporterFiche;
  $("#b-exemple").onclick = () => chargerExemple("exemple");
  $("#b-exemple-formes").onclick = () => chargerExemple("exemple_formes");
  $("#b-desepingler").onclick = () => { etat.epingles = []; calculer(); };
  $("#b-aide").onclick = aide;
  $("#b-ranger").onclick = rangerChutes;
  for (const b of document.querySelectorAll("[data-acte]")) b.onclick = () => ({ ligne: ajouterLigne, dupliquer: dupliquerLignes, supprimer: supprimerLignes })[b.dataset.acte](b.dataset.table);
  $("#c-avancees").onchange = (e) => { etat.avancees = e.target.checked; stockage.ecrire("avancees", etat.avancees); rendreTable("pieces"); rendreTable("stock"); };
  $("#c-traits").onchange = (e) => { etat.traits = e.target.checked; stockage.ecrire("traits", etat.traits); dessinerPlan(); };
  $("#b-moins").onclick = () => { etat.zoom = Math.max(0.25, etat.zoom / 1.25); ajusterZoom(); };
  $("#b-plus").onclick = () => { etat.zoom = Math.min(20, etat.zoom * 1.25); ajusterZoom(); };
  $("#b-ajuster").onclick = () => { etat.zoom = 1; ajusterZoom(); };
  $("#plan").addEventListener("wheel", (e) => { if (!e.ctrlKey) return; e.preventDefault(); etat.zoom = Math.min(20, Math.max(0.25, etat.zoom * (e.deltaY < 0 ? 1.25 : 0.8))); ajusterZoom(); }, { passive: false });
  $("#plan").addEventListener("contextmenu", menuContextuel);
  $("#plan").addEventListener("pointerdown", debutGlisse);
  $("#plan").addEventListener("pointermove", mouvementGlisse);
  $("#plan").addEventListener("pointerup", finGlisse);
  $("#plan").addEventListener("pointercancel", () => { if (glisse) { glisse.forme.removeAttribute("transform"); glisse = null; } });
  $("#plan").addEventListener("click", (e) => { const c = e.target.closest("[data-planche]"); if (c) { etat.planche = Number(c.dataset.planche); dessinerPlan(); } });
  document.addEventListener("click", (e) => { if (!e.target.closest("#menu-contextuel")) fermerMenu(); });
  for (const b of document.querySelectorAll("[data-onglet]")) b.onclick = () => { for (const x of document.querySelectorAll("[data-onglet]")) x.classList.toggle("actif", x === b); for (const o of document.querySelectorAll(".onglet")) o.classList.toggle("actif", o.id === "o-" + b.dataset.onglet); if (b.dataset.onglet === "plan") ajusterZoom(); };
  document.addEventListener("keydown", (e) => {
    if (e.key === "F5") { e.preventDefault(); calculer(); }
    else if (e.key === "Escape" && !$("#b-interrompre").hidden) interrompre();
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey && e.target.tagName !== "INPUT") { e.preventDefault(); annuler(); }
    else if ((e.ctrlKey || e.metaKey) && ((e.key.toLowerCase() === "z" && e.shiftKey) || e.key.toLowerCase() === "y")) { e.preventDefault(); refaire(); }
  });
  window.addEventListener("resize", ajusterZoom);
  window.addEventListener("beforeprint", () => { etat.zoom = 1; ajusterZoom(); });
  brancherPoignee();
  $("#menu-contextuel").hidden = true;
  // La langue : le bouton montre celle qu'on prendra en le touchant.
  const bLangue = $("#b-langue");
  const marquerLangue = () => { bLangue.textContent = langue === "fr" ? "EN" : "FR"; };
  marquerLangue();
  bLangue.onclick = () => {
    changerLangue(langue === "fr" ? "en" : "fr");
    marquerLangue();
    rendreTout();          // avant traduirePage : elle rebâtit les tables
    traduirePage();
    if (etat.aJour) $("#etat").textContent = t("Plan à jour");
    dessinerPlan();
    if (etat.resultat) afficherResultat();
  };
  traduirePage();
  // Le menu « Plus… » se referme quand on y choisit une entrée, et quand
  // on clique ailleurs — un <details> ne le fait pas de lui-même.
  const plus = document.querySelector(".menu");
  plus.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { plus.open = false; }));
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu")) plus.open = false; });
}

brancher();
rendreReglages();
// Point d'accès pour les essais automatisés (et la console) : l'état, le
// calcul, l'ajout de formes — rien de plus que ce que la page fait déjà.
window.chutier = { etat, calculer, appeler, rendreTout, annuler, refaire, interrompre, enregistrerBrouillon, ajouterFormes: (formes) => { const premier = etat.stock.find(s => (s.reference || "").trim()); etat.pieces = etat.pieces.filter(p => (p.reference || "").trim()); for (const f of formes) etat.pieces.push({ ...DEFAUTS_LIGNE.pieces, reference: f.nom, longueur: f.longueur, largeur: f.largeur, epaisseur: premier ? premier.epaisseur : 18, matiere: premier ? premier.matiere : "", fil: "indifferent", contour: f.contour, trous: f.trous, quantite: f.quantite || 1 }); rendreTable("pieces"); } };
