// Chutier — la page. Aucune logique de débit ici : tout passe par le
// worker Pyodide (web/worker.js) et pont_web.py. Cette couche tient les
// tables, les réglages, le plan en SVG et les fichiers, comme
// interface.py le fait pour Qt — et lit les mêmes fichiers (.json, .csv,
// .svg) que l'application de bureau.

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
  ],
};

const DEFAUTS_LIGNE = {
  pieces: { reference: "", longueur: "", largeur: "", epaisseur: 18, matiere: "", quantite: 1, fil: "longueur", composable: false, planche: "", contour: [], trous: [] },
  stock: { reference: "", longueur: "", largeur: "", epaisseur: 18, matiere: "", quantite: 1, chute: false, atelier: false, fil: true, illimite: false, prix: 0, defauts_texte: "" },
};

const REGLAGES = [
  ["La scie", [
    ["trait_de_scie", "Trait de scie (mm)", "nombre", "3 à 4 mm pour une lame de circulaire."],
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
    ["pas_rotation", "Orientations", "choix", "Les angles essayés pour une pièce à fil indifférent.",
      [[90, "4 orientations (90°)"], [45, "8 orientations (45°)"], [30, "12 orientations (30°)"], [15, "24 orientations (15°) — lent"]]]]],
  ["Le calcul", [
    ["priorite", "Privilégier", "choix", "Entre deux plans dans le même bois neuf : moins de pertes, ou moins de coupes.",
      [["bois", "le bois — moins de pertes"], ["scie", "le temps de scie — moins de coupes"]]],
    ["essais_melanges", "Essais de mélange", "entier", "Ordres tirés au hasard en plus des stratégies réglées. Graine fixe : même plan."],
    ["passes_amelioration", "Passes d'amélioration", "entier", "Vider une planche, replacer ses pièces ailleurs. 0 pour s'en passer."]]],
];

const RAISONS_VIDE = "Saisissez les pièces à débiter, vérifiez le stock, puis Calculer le débit (F5).";

// -- état ---------------------------------------------------------------------

const etat = {
  pieces: [], stock: [], parametres: {}, epingles: [], resultat: null,
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
const m2 = (v) => (v / 1e6).toFixed(3).replace(".", ",");
const pct = (v) => (100 * v).toFixed(1).replace(".", ",");

// -- le worker -----------------------------------------------------------------

const worker = new Worker(new URL("./worker.js", import.meta.url));
const attentes = new Map();
let compteur = 0;
let pythonPret = false;

worker.onmessage = (e) => {
  const m = e.data;
  if (m.etat) { $("#etat").textContent = m.etat; return; }
  if (m.echec) { $("#etat").textContent = "Python n'a pas pu se charger : " + m.echec; $("#plan-vide").textContent = "Python n'a pas pu se charger : " + m.echec; return; }
  if (m.pret) { pythonPret = true; $("#etat").textContent = "Prêt"; demarrer(); return; }
  const a = attentes.get(m.id);
  if (!a) return;
  attentes.delete(m.id);
  m.ok ? a.resolve(m.valeur) : a.reject(new Error(m.erreur));
};

function appeler(fn, ...args) {
  return new Promise((resolve, reject) => {
    const id = ++compteur;
    attentes.set(id, { resolve, reject });
    worker.postMessage({ id, fn, args });
  });
}

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

function matieres() { return [...new Set(etat.stock.map(s => (s.matiere || "").trim()).filter(Boolean))].sort(); }
function references() { return [...new Set(etat.stock.map(s => (s.reference || "").trim()).filter(Boolean))]; }

function rendreTable(nom) {
  const table = $("#t-" + nom);
  const lignes = etat[nom];
  const colonnes = COLONNES[nom].filter(c => !c.avancee || etat.avancees || lignes.some(l => utilisee(c, l)));
  table.replaceChildren();
  const entete = el("tr");
  for (const c of colonnes) entete.append(el("th", { text: c.titre, title: c.info }));
  table.append(el("thead", {}, entete));
  const corps = el("tbody");
  lignes.forEach((ligne, i) => {
    const tr = el("tr", { "data-ligne": i, onclick: (e) => { if (e.target.tagName !== "INPUT" && e.target.tagName !== "SELECT") { tr.classList.toggle("choisie", !(e.ctrlKey || e.metaKey) ? true : !tr.classList.contains("choisie")); if (!(e.ctrlKey || e.metaKey)) for (const autre of corps.children) if (autre !== tr) autre.classList.remove("choisie"); } } });
    for (const c of colonnes) tr.append(cellule(nom, ligne, c, i));
    corps.append(tr);
  });
  table.append(corps);
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
  const changer = () => { etat.aJour = false; rafraichirEtat(); };
  if (c.genre === "bool") {
    td.append(el("input", { type: "checkbox", title: c.info, onchange: (e) => { ligne[c.cle] = e.target.checked; changer(); if (c.cle === "atelier" || nom === "stock") enregistrerAtelier(); } }));
    td.firstChild.checked = Boolean(ligne[c.cle]);
  } else if (c.genre === "choix") {
    const sel = el("select", { title: c.info, onchange: (e) => { ligne[c.cle] = e.target.value; changer(); } });
    for (const [v, t] of c.choix) sel.append(el("option", { value: v, text: t }));
    sel.value = ligne[c.cle];
    td.append(sel);
  } else if (c.genre === "contour") {
    const n = (ligne.contour || []).length;
    const t = (ligne.trous || []).length;
    td.textContent = n ? `◇ ${n} pts` + (t ? ` · ${t} trou${t > 1 ? "s" : ""}` : "") : "";
    td.title = c.info;
  } else {
    const input = el("input", { type: "text", title: c.info, value: ligne[c.cle] ?? "", "data-colonne": c.cle,
      oninput: (e) => { ligne[c.cle] = e.target.value; e.target.classList.toggle("faux", (c.genre === "nombre" || c.genre === "entier") && e.target.value.trim() !== "" && Number.isNaN(Number(e.target.value.replace(",", ".")))); changer(); if (nom === "stock") enregistrerAtelier(); },
      onpaste: (e) => coller(nom, i, c, e), onkeydown: (e) => touche(nom, i, e) });
    if (c.genre === "matiere" || c.genre === "planche") {
      const liste = "l-" + nom + "-" + c.cle;
      input.setAttribute("list", liste);
      let dl = document.getElementById(liste);
      if (!dl) { dl = el("datalist", { id: liste }); document.body.append(dl); }
      dl.replaceChildren(...(c.genre === "matiere" ? matieres() : references()).map(v => el("option", { value: v })));
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
      else if (col.genre === "choix") { const trouve = col.choix.find(([k, t]) => k === v.toLowerCase() || t.toLowerCase() === v.toLowerCase()); if (trouve) etat[nom][ligne][col.cle] = trouve[0]; }
      else if (col.genre !== "contour") etat[nom][ligne][col.cle] = v;
    });
  });
  etat.aJour = false;
  rendreTable(nom); rafraichirEtat(); if (nom === "stock") enregistrerAtelier();
}

function lignesChoisies(nom) { return [...$("#t-" + nom).querySelectorAll("tr.choisie")].map(tr => Number(tr.dataset.ligne)); }
function ajouterLigne(nom) { etat[nom].push({ ...DEFAUTS_LIGNE[nom] }); etat.aJour = false; rendreTable(nom); rafraichirEtat(); const dern = $("#t-" + nom).querySelector("tbody tr:last-child input[type=text]"); dern && dern.focus(); }
function dupliquerLignes(nom) { const choisies = lignesChoisies(nom); if (!choisies.length) return; const copies = choisies.map(i => JSON.parse(JSON.stringify(etat[nom][i]))); etat[nom].splice(choisies[choisies.length - 1] + 1, 0, ...copies); etat.aJour = false; rendreTable(nom); rafraichirEtat(); if (nom === "stock") enregistrerAtelier(); }
function supprimerLignes(nom, lignes = lignesChoisies(nom)) { for (const i of [...lignes].sort((a, b) => b - a)) etat[nom].splice(i, 1); etat.aJour = false; rendreTable(nom); rafraichirEtat(); if (nom === "stock") enregistrerAtelier(); }

function rafraichirResumes() {
  const pieces = etat.pieces.filter(p => (p.reference || "").trim());
  const ex = pieces.reduce((n, p) => n + (Number(p.quantite) || 1), 0);
  const contours = pieces.filter(p => (p.contour || []).length).length;
  $("#r-pieces").textContent = pieces.length ? `${pieces.length} référence(s), ${ex} exemplaire(s)` + (contours ? ` dont ${contours} contour(s) à imbriquer` : "") + ` · ${[...new Set(pieces.map(p => p.matiere).filter(Boolean))].join(", ") || "matière non renseignée"}` : "Aucune pièce — ajoutez une ligne, collez un tableau (Ctrl+V), importez un CSV ou des contours SVG.";
  const stock = etat.stock.filter(s => (s.reference || "").trim());
  const chutes = stock.filter(s => s.chute).reduce((n, s) => n + (Number(s.quantite) || 1), 0);
  const atelierN = stock.filter(s => s.atelier).length;
  $("#r-stock").textContent = stock.length ? `${stock.length} référence(s)` + (atelierN ? ` · ${atelierN} de l'atelier` : "") + (chutes ? ` · ${chutes} chute(s) à écouler d'abord` : "") : "Stock vide — le débit n'aura rien où se poser.";
}

// -- réglages ------------------------------------------------------------------------

function rendreReglages() {
  const zone = $("#reglages");
  zone.replaceChildren();
  for (const [titre, champs] of REGLAGES) {
    zone.append(el("h3", { text: titre }));
    for (const [cle, libelle, genre, info, choix] of champs) {
      zone.append(el("label", { text: libelle, title: info }));
      let champ;
      if (genre === "choix") {
        champ = el("select", { onchange: (e) => { etat.parametres[cle] = isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value); changerReglage(); } });
        for (const [v, t] of choix) champ.append(el("option", { value: v, text: t }));
        champ.value = String(etat.parametres[cle]);
      } else {
        champ = el("input", { type: "number", step: genre === "entier" ? 1 : 0.5, min: 0, value: etat.parametres[cle], oninput: (e) => { etat.parametres[cle] = Number(e.target.value); changerReglage(); } });
      }
      zone.append(champ);
      zone.append(el("p", { class: "discret", text: info }));
    }
  }
}
function changerReglage() { etat.aJour = false; stockage.ecrire("parametres", etat.parametres); rafraichirEtat(); }

// -- calcul ---------------------------------------------------------------------------

async function calculer() {
  if (!pythonPret) return;
  const pieces = etat.pieces.filter(p => (p.reference || "").trim());
  if (!pieces.length) { alerter("Aucune pièce à débiter."); return; }
  $("#etat").textContent = "Calcul…";
  $("#b-calculer").disabled = true;
  try {
    const sortie = JSON.parse(await appeler("calculer", JSON.stringify({ pieces, stock: etat.stock.filter(s => (s.reference || "").trim()), parametres: { ...etat.parametres, processus: 1 }, epingles: etat.epingles })));
    if (!sortie.ok) { alerter("Saisie invalide : " + sortie.erreur); $("#etat").textContent = "Saisie invalide"; return; }
    if (sortie.epingles_relachees) { etat.epingles = []; $("#etat").textContent = "Épingles relâchées : une planche ou une pièce a changé."; }
    else $("#etat").textContent = "Plan à jour";
    etat.resultat = sortie.resultat;
    etat.aJour = true;
    afficherResultat();
  } catch (erreur) {
    alerter("Le calcul a échoué : " + erreur.message);
    $("#etat").textContent = "Échec du calcul";
  } finally {
    $("#b-calculer").disabled = false;
  }
}

function alerter(texte) { window.alert(texte); }

function afficherResultat() {
  const r = etat.resultat;
  const b = r.bilan;
  const tuiles = [
    ["Pièces posées", `${b.nb_posees} / ${b.nb_demandees}`, b.nb_non_placees ? `${b.nb_non_placees} non placée(s)` : "", b.nb_non_placees ? "alerte" : ""],
    ["Rendement", pct(b.rendement) + " %", m2(b.surface_pieces) + " m² de pièces", ""],
    ["Planches entamées", String(b.nb_planches_entamees), b.nb_chutes_consommees ? `dont ${b.nb_chutes_consommees} chute(s)` : "aucune chute écoulée", ""],
    ["Pertes", m2(b.surface_perdue) + " m²", `sciure et rebuts · ${b.nb_coupes} coupe(s)`, ""],
    ["Chutes créées", String(r.chutes_groupees.reduce((n, c) => n + c.nombre, 0)), b.surface_chutes_creees ? m2(b.surface_chutes_creees) + " m² à ranger" : "rien à garder", b.surface_chutes_creees ? "accent" : ""],
    ["À acheter", String(r.achats.reduce((n, a) => n + a.nombre, 0)), r.cout ? r.cout.toFixed(2) + " €" : "prix non renseignés", ""],
  ];
  $("#tuiles").replaceChildren(...tuiles.map(([l, v, d, ton]) => el("div", { class: "tuile " + ton }, el("div", { class: "libelle", text: l }), el("div", { class: "valeur", text: v }), el("div", { class: "detail", text: d }))));
  $("#l-achats").replaceChildren(...r.achats.map(a => el("li", { text: `${a.nombre} × « ${a.reference} » — ${mm(a.longueur)} × ${mm(a.largeur)} × ${mm(a.epaisseur)} mm, ${a.matiere}` + (a.prix ? ` — ${(a.nombre * a.prix).toFixed(2)} €` : "") })));
  $("#n-achats").textContent = "· " + r.achats.reduce((n, a) => n + a.nombre, 0);
  $("#l-chutes").replaceChildren(...r.chutes_groupees.map(c => el("li", { text: `${c.nombre} ×  ${mm(c.dim_x)} × ${mm(c.dim_y)} × ${mm(c.epaisseur)} mm — ${c.matiere}` })));
  $("#n-chutes").textContent = "· " + r.chutes_groupees.reduce((n, c) => n + c.nombre, 0);
  $("#b-ranger").disabled = !r.chutes_groupees.length;
  $("#l-non").replaceChildren(...r.non_placees.map(n => el("li", { class: "rouge", text: `« ${n.reference} » ×${n.exemplaires} — ${n.raison}` })));
  $("#n-non").textContent = b.nb_non_placees ? "· " + b.nb_non_placees : "";
  $("#m-non").textContent = r.non_placees.length ? "Ces pièces n'ont trouvé aucune place. Ajoutez du stock, relâchez le fil, ou cochez « Composable »." : "Tout est passé — aucune pièce laissée de côté.";
  etat.planche = 1;
  dessinerPlan();
  rendreImpression();
}

// -- le plan --------------------------------------------------------------------------

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}, ...enfants) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); for (const c of enfants) e.append(c); return e; };

function dessinerPlan() {
  const zone = $("#plan");
  const r = etat.resultat;
  if (!r || !r.debits.length) { zone.replaceChildren(el("p", { class: "vide", id: "plan-vide", text: RAISONS_VIDE })); $("#legende").replaceChildren(); return; }
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
    groupe.append(svgEl("text", { x: 0, y: y + cartouche, "font-size": cartouche, "font-weight": "bold", class: "cartouche" }, `${numero}.  ${pl.reference}${d.plusieurs ? ` (ex. ${d.exemplaire})` : ""}   —   ${mm(pl.longueur)} × ${mm(pl.largeur)} × ${mm(pl.epaisseur)} mm, ${pl.matiere}${pl.chute ? " [chute]" : pl.illimite ? " [catalogue]" : ""}   —   ${d.poses.length} pièce(s), rendement ${pct(d.rendement)} %${epinglee ? "   —   ÉPINGLÉE" : ""}`));
    y += bande;
    const yh = y;
    const Y = (v, h = 0) => yh + pl.largeur - v - h;
    groupe.append(svgEl("rect", { x: 0, y: yh, width: pl.longueur, height: pl.largeur, fill: "#faf8f4", stroke: "#2f3540", "stroke-width": L / 500 }));
    // recoupes et défauts
    for (const [x, yy, dx, dy] of zonesEcartees(pl)) groupe.append(svgEl("rect", { x, y: Y(yy, dy), width: dx, height: dy, fill: "url(#hachure-defaut)", stroke: "#a85a52", "stroke-width": L / 1200 }));
    for (const c of d.chutes) {
      groupe.append(svgEl("rect", { x: c.x, y: Y(c.y, c.dim_y), width: c.dim_x, height: c.dim_y, fill: "url(#hachure-chute)", stroke: "#767c85", "stroke-width": L / 1200 }));
      groupe.append(...etiquette(`chute`, `${mm(c.dim_x)} × ${mm(c.dim_y)}`, c.x, Y(c.y, c.dim_y), c.dim_x, c.dim_y, police, "#2f3540"));
    }
    d.poses.forEach((p, ip) => {
      const couleur = r.couleurs[p.reference] || "#ddd";
      let forme;
      if (p.contour.length) {
        const chemin = [p.contour, ...p.trous].map(anneau => "M" + anneau.map(([px, py]) => `${px} ${Y(py)}`).join(" L") + " Z").join(" ");
        forme = svgEl("path", { d: chemin, "fill-rule": "evenodd", fill: couleur, stroke: "#2f3540", "stroke-width": L / 1500 });
      } else {
        forme = svgEl("rect", { x: p.x, y: Y(p.y, p.dim_y), width: p.dim_x, height: p.dim_y, fill: couleur, stroke: "#2f3540", "stroke-width": L / 1500 });
      }
      forme.setAttribute("data-planche", numero); forme.setAttribute("data-pose", ip);
      forme.append(svgEl("title", {}, `${p.reference} ${p.exemplaire}/${p.quantite} — ${mm(p.dim_x)} × ${mm(p.dim_y)} en (${mm(p.x)}, ${mm(p.y)})${p.angle ? `, tournée de ${mm(p.angle)}°` : p.pivotee ? ", pivotée" : ""}`));
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
        groupe.append(...etiquette(p.reference, `${mm(p.dim_x)} × ${mm(p.dim_y)}`, p.x, Y(p.y, p.dim_y), p.dim_x, p.dim_y, police, "#2f3540"));
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
  const legende = Object.entries(comptes).map(([ref, n]) => el("span", {}, el("span", { class: "pastille", style: `background:${r.couleurs[ref]}` }), `${ref} ×${n}`));
  if (r.debits.some(d => d.chutes.length)) legende.push(el("span", {}, el("span", { class: "pastille", style: "background: repeating-linear-gradient(45deg,#faf8f4,#faf8f4 2px,#767c85 2px,#767c85 3px)" }), "chute réutilisable"));
  if (r.debits.some(d => zonesEcartees(d.planche).length)) legende.push(el("span", {}, el("span", { class: "pastille", style: "background: repeating-linear-gradient(45deg,#faf8f4,#faf8f4 2px,#a85a52 2px,#a85a52 3px)" }), "défaut écarté"));
  legende.push(el("span", {}, el("span", { class: "pastille", style: "background:#faf8f4" }), "perte"));
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
  const largeurTexte = (t, f) => t.length * f * 0.56;
  const taille = Math.min(police * 1.4, Math.max(police * 0.8, dy * 0.22));
  const variantes = [[[nom, cotes], taille], [[`${nom} · ${cotes}`], taille], [[nom], taille * 0.9]];
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
  zone.append(el("h3", { text: (etat.nomProjet || "Feuille de débit") + ` — ${r.bilan.nb_posees}/${r.bilan.nb_demandees} pièce(s), rendement ${pct(r.bilan.rendement)} %, ${r.bilan.nb_planches_entamees} planche(s), pertes ${m2(r.bilan.surface_perdue)} m²` }));
  r.debits.forEach((d, i) => {
    const lots = {};
    for (const p of d.poses) { const k = `${p.reference} ${mm(p.dim_x)} × ${mm(p.dim_y)}`; lots[k] = (lots[k] || 0) + 1; }
    zone.append(el("p", {}, el("b", { text: `${i + 1}.  ` }), Object.entries(lots).map(([k, n]) => k + (n > 1 ? ` ×${n}` : "")).join("   ·   ")));
    zone.append(el("p", { text: d.imbriquee ? "découpe CNC : contours imbriqués, à exporter en SVG" : "coupes :  " + d.coupes.map(c => `${c.ordre} ${c.sens === "tronconnage" ? "↕" : "↔"} ${mm(c.position)}`).join("   ·   ") }));
  });
  zone.append(el("p", { class: "discret", text: "↕ tronçonnage, en travers du fil, à x mm du bout gauche — ↔ délignage, le long du fil, à y mm de la rive basse." }));
}

// -- fichiers ------------------------------------------------------------------------------

function telecharger(nom, texte, type = "text/plain") {
  const a = el("a", { href: URL.createObjectURL(new Blob([texte], { type })), download: nom });
  document.body.append(a); a.click(); a.remove();
}
function lireFichier(input) { return new Promise((resolve) => { input.onchange = () => { const f = input.files[0]; input.value = ""; if (!f) return resolve(null); const lecteur = new FileReader(); lecteur.onload = () => resolve({ nom: f.name, texte: lecteur.result }); lecteur.readAsText(f); }; input.click(); }); }

async function ouvrirProjet() {
  const f = await lireFichier($("#f-projet")); if (!f) return;
  const d = JSON.parse(await appeler("depuis_projet", f.texte));
  if (d.erreur) { alerter("Ouverture impossible : " + d.erreur); return; }
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.stock = [...d.stock.filter(s => !s.atelier).map(s => ({ ...DEFAUTS_LIGNE.stock, ...s })), ...atelier()];
  etat.parametres = { ...etat.parametres, ...d.parametres };
  etat.epingles = d.epingles || [];
  etat.nomProjet = f.nom.replace(/\.json$/i, "");
  rendreTout(); calculer();
}
async function enregistrerProjet() {
  const texte = await appeler("vers_projet", JSON.stringify({ pieces: etat.pieces, stock: etat.stock.filter(s => !s.atelier), parametres: etat.parametres, epingles: etat.epingles }));
  telecharger((etat.nomProjet || "debit") + ".json", texte, "application/json");
  enregistrerAtelier();
}
async function importerCsv() {
  const f = await lireFichier($("#f-csv")); if (!f) return;
  const d = JSON.parse(await appeler("depuis_csv", f.texte));
  if (d.erreur) { alerter("Import impossible : " + d.erreur); return; }
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.aJour = false; rendreTable("pieces"); rafraichirEtat();
}
async function exporterCsv() { telecharger((etat.nomProjet || "pieces") + ".csv", await appeler("vers_csv", JSON.stringify(etat.pieces)), "text/csv"); }
async function importerSvg() {
  const f = await lireFichier($("#f-svg")); if (!f) return;
  const d = JSON.parse(await appeler("depuis_svg", f.texte));
  if (d.erreur) { alerter("Import impossible : " + d.erreur); return; }
  if (!d.formes.length) { alerter("Aucun tracé fermé dans ce SVG.\n" + d.avertissements.join("\n")); return; }
  window.chutier.ajouterFormes(d.formes);
  etat.aJour = false; rafraichirEtat();
  if (d.avertissements.length) alerter(`${d.formes.length} contour(s) importé(s)\n\n` + d.avertissements.join("\n"));
  else $("#etat").textContent = `${d.formes.length} contour(s) importé(s)`;
}
async function exporterSvg() {
  if (!etat.resultat) { alerter("Calculez d'abord le débit."); return; }
  const titre = etat.nomProjet || "Feuille de débit";
  for (const [i, d] of etat.resultat.debits.entries()) {
    const svg = await appeler("svg_planche", JSON.stringify(d.epingle), i + 1, titre);
    telecharger(`${titre}-planche-${i + 1}.svg`, svg, "image/svg+xml");
    await new Promise(r => setTimeout(r, 300));
  }
}
function exporterFiche() { if (!etat.resultat) { alerter("Calculez d'abord le débit."); return; } telecharger((etat.nomProjet || "fiche-atelier") + ".txt", (etat.nomProjet || "Feuille de débit") + "\n\n" + etat.resultat.fiche + "\n"); }

function rangerChutes() {
  const r = etat.resultat;
  if (!r || !etat.aJour) { alerter("Recalculez avant de ranger les chutes : la saisie a changé depuis le dernier calcul."); return; }
  if (!window.confirm("Le stock sera mis à jour comme si le débit était fait : planches entamées en moins, chutes créées en plus, à l'atelier de ce navigateur. Continuer ?")) return;
  etat.stock = r.stock_apres.map(s => ({ ...DEFAUTS_LIGNE.stock, ...s, defauts_texte: defautsTexte(s) }));
  etat.aJour = false; rendreTable("stock"); rafraichirEtat(); enregistrerAtelier();
  $("#etat").textContent = "Stock de l'atelier mis à jour dans ce navigateur.";
}
function defautsTexte(s) {
  const t = [];
  if (s.recoupe_bouts > 0) t.push("bouts " + mm(s.recoupe_bouts));
  if (s.recoupe_rives > 0) t.push("rives " + mm(s.recoupe_rives));
  for (const [x, y, dx, dy] of s.defauts || []) t.push(y === 0 && y + dy === s.largeur ? `${mm(x)}-${mm(x + dx)}` : [x, y, dx, dy].map(mm).join(","));
  return t.join(" ; ");
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
  menu.append(el("button", { text: epinglee ? `Relâcher la planche ${numero}` : `Épingler la planche ${numero} — la garder telle quelle`, onclick: () => { fermerMenu(); if (epinglee) etat.epingles.splice(numero - 1, 1); else etat.epingles.push(etat.resultat.debits[numero - 1].epingle); calculer(); } }));
  if (pose) {
    menu.append(el("div", { class: "sep" }), el("div", { class: "titre", text: `Tailler « ${pose.reference} » dans…` }));
    for (const ref of references()) menu.append(el("button", { text: ref, onclick: () => { fermerMenu(); imposerPlanche(pose.reference, ref); } }));
    menu.append(el("button", { text: "Laisser le chutier choisir", onclick: () => { fermerMenu(); imposerPlanche(pose.reference, ""); } }));
  }
  menu.style.left = e.clientX + "px"; menu.style.top = e.clientY + "px"; menu.hidden = false;
  etat.planche = numero; dessinerPlan();
}
function fermerMenu() { $("#menu-contextuel").hidden = true; }
function imposerPlanche(reference, planche) { for (const p of etat.pieces) if (p.reference === reference) p.planche = planche; etat.avancees = etat.avancees || Boolean(planche); rendreTable("pieces"); calculer(); }

// -- fenêtre --------------------------------------------------------------------------------

function rafraichirEtat() {
  if (!etat.resultat) $("#etat").textContent = pythonPret ? "Aucun calcul" : $("#etat").textContent;
  else if (!etat.aJour) $("#etat").textContent = "⚠ Saisie modifiée — F5 pour recalculer";
}
function rendreTout() { rendreTable("pieces"); rendreTable("stock"); rendreReglages(); rafraichirEtat(); }

function nouveau() {
  etat.pieces = [{ ...DEFAUTS_LIGNE.pieces }];
  etat.stock = atelier();
  if (!etat.stock.length) etat.stock.push({ ...DEFAUTS_LIGNE.stock });
  etat.epingles = []; etat.resultat = null; etat.aJour = false; etat.nomProjet = "";
  rendreTout(); dessinerPlan(); $("#tuiles").replaceChildren(); rendreImpression();
}

async function chargerExemple() {
  const d = JSON.parse(await appeler("exemple"));
  etat.pieces = d.pieces.map(p => ({ ...DEFAUTS_LIGNE.pieces, ...p }));
  etat.stock = [...d.stock.map(s => ({ ...DEFAUTS_LIGNE.stock, ...s })), ...atelier()];
  etat.epingles = []; etat.nomProjet = "";
  rendreTout(); calculer();
}

async function demarrer() {
  const defauts = JSON.parse(await appeler("parametres_defaut"));
  etat.parametres = { ...defauts, ...stockage.lire("parametres", {}) };
  etat.avancees = stockage.lire("avancees", false);
  etat.traits = stockage.lire("traits", false);
  $("#c-avancees").checked = etat.avancees; $("#c-traits").checked = etat.traits;
  if (atelier().length) nouveau(); else await chargerExemple();
}

function aide() {
  alerter(`Le geste : les pièces à débiter, le stock où les tailler, les réglages de scie, puis Calculer (F5). Le plan se lit à droite, toutes planches empilées.

Saisie : Ctrl+V colle un bloc venu d'un tableur (colonnes séparées par une tabulation ou un point-virgule) ; Entrée passe à la ligne suivante ; Ctrl+Suppr ôte la ligne ; clic sur une ligne pour la choisir, Ctrl-clic pour en ajouter.

L'atelier : les lignes de stock cochées « Atelier » restent dans ce navigateur d'un projet à l'autre. « Ranger les chutes au stock » y écrit aussitôt.

Corriger le plan : clic droit sur une planche pour l'épingler (reprise telle quelle au prochain calcul), clic droit sur une pièce pour la tailler dans une autre planche.

La CNC : Plus… → Importer des contours (SVG) ajoute aux pièces chaque tracé fermé ; dès qu'une matière compte un contour, tout ce lot est imbriqué à la fraise. Plus… → Exporter la découpe sort chaque planche en SVG à l'échelle 1.

Tout est en millimètres. La longueur court le long du fil. Une planche plus épaisse que la pièce convient, jamais une plus mince. Les chutes passent avant les planches neuves. Rien ne quitte votre navigateur.`);
}

function brancher() {
  $("#b-nouveau").onclick = () => { if (window.confirm("Vider les pièces et le stock du projet ? (l'atelier reste)")) nouveau(); };
  $("#b-ouvrir").onclick = ouvrirProjet;
  $("#b-enregistrer").onclick = enregistrerProjet;
  $("#b-calculer").onclick = calculer;
  $("#b-imprimer").onclick = () => window.print();
  $("#b-importer-csv").onclick = importerCsv;
  $("#b-exporter-csv").onclick = exporterCsv;
  $("#b-importer-svg").onclick = importerSvg;
  $("#b-exporter-svg").onclick = exporterSvg;
  $("#b-fiche").onclick = exporterFiche;
  $("#b-exemple").onclick = chargerExemple;
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
  $("#plan").addEventListener("click", (e) => { const c = e.target.closest("[data-planche]"); if (c) { etat.planche = Number(c.dataset.planche); dessinerPlan(); } });
  document.addEventListener("click", (e) => { if (!e.target.closest("#menu-contextuel")) fermerMenu(); });
  for (const b of document.querySelectorAll("[data-onglet]")) b.onclick = () => { for (const x of document.querySelectorAll("[data-onglet]")) x.classList.toggle("actif", x === b); for (const o of document.querySelectorAll(".onglet")) o.classList.toggle("actif", o.id === "o-" + b.dataset.onglet); if (b.dataset.onglet === "plan") ajusterZoom(); };
  document.addEventListener("keydown", (e) => { if (e.key === "F5") { e.preventDefault(); calculer(); } });
  window.addEventListener("resize", ajusterZoom);
  window.addEventListener("beforeprint", () => { etat.zoom = 1; ajusterZoom(); });
  $("#menu-contextuel").hidden = true;
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
window.chutier = { etat, calculer, appeler, rendreTout, ajouterFormes: (formes) => { const premier = etat.stock.find(s => (s.reference || "").trim()); etat.pieces = etat.pieces.filter(p => (p.reference || "").trim()); for (const f of formes) etat.pieces.push({ ...DEFAUTS_LIGNE.pieces, reference: f.nom, longueur: f.longueur, largeur: f.largeur, epaisseur: premier ? premier.epaisseur : 18, matiere: premier ? premier.matiere : "", fil: "indifferent", contour: f.contour, trous: f.trous, quantite: f.quantite || 1 }); rendreTable("pieces"); } };
