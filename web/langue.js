// Le chutier en deux langues, pour la page web seulement — l'application
// de bureau reste en français, comme le reste de l'atelier.
//
// La clé EST le texte français : rien à inventer, rien à tenir à jour de
// part et d'autre, et un texte sans traduction s'affiche en français
// plutôt que de disparaître. `{}` marque la place d'une valeur, dans
// l'ordre — l'anglais peut les remettre où sa grammaire les veut.
//
// Deux usages :
//   t("Réglages")                     → "Settings"
//   t`${n} référence(s)`              → "3 reference(s)"
// (le gabarit passe par la clé "{} référence(s)").
//
// tests/test_langue.py vérifie que toute chaîne enveloppée dans app.js a
// sa clé ici, et qu'aucune clé ne reste orpheline.

const ANGLAIS = {
  // -- colonnes des pièces et du stock
  "Longueur": "Length",
  "Largeur": "Width",
  "Indifférent": "Either",
  "Référence": "Name",
  "Nom de la pièce : c'est lui qui lui donne sa couleur sur le plan.": "The part's name — it is what gives it its colour on the plan.",
  "Long.": "Length",
  "Longueur en mm, le long du fil.": "Length in mm, along the grain.",
  "Larg.": "Width",
  "Largeur en mm, en travers du fil.": "Width in mm, across the grain.",
  "Ép.": "Thick.",
  "Épaisseur FINIE en mm. Le brut se rabote : une planche plus épaisse convient, jamais une plus mince.": "FINISHED thickness in mm. Rough stock gets planed: a thicker board will do, a thinner one never will.",
  "Matière": "Material",
  "Le même mot que dans le stock, sinon rien ne s'apparie.": "The same word as in the stock, otherwise nothing matches.",
  "Qté": "Qty",
  "Nombre d'exemplaires.": "How many of them.",
  "Fil": "Grain",
  "Où court le fil du bois dans la pièce. « Indifférent » autorise la rotation.": "Which way the grain runs in the part. “Either” allows rotation.",
  "Composable": "Glue-up",
  "Trop large pour tout brut, cette pièce peut se faire en plusieurs lames collées.": "Too wide for any stock, this part may be made of several boards glued up.",
  "Planche": "Board",
  "Imposer la ligne de stock où tailler cette pièce (vide : au choix).": "Force the stock row this part is cut from (empty: the chutier chooses).",
  "Contour": "Outline",
  "Une forme quelconque importée d'un SVG, imbriquée à la CNC.": "An arbitrary shape imported from an SVG, nested on the CNC.",
  "Nom du morceau de stock, tel qu'il est repéré à l'atelier.": "The name of this piece of stock, as it is marked in the workshop.",
  "Épaisseur BRUTE disponible, en mm.": "ROUGH thickness available, in mm.",
  "Le même mot que dans les pièces.": "The same word as in the parts.",
  "Combien de morceaux identiques.": "How many identical pieces.",
  "Chute": "Offcut",
  "Déjà en atelier, à écouler EN PRIORITÉ. Jamais compté à l'achat.": "Already in the workshop, used up FIRST. Never counted as a purchase.",
  "Atelier": "Workshop",
  "Vit dans le stock commun de ce navigateur, retrouvé d'un projet à l'autre.": "Lives in this browser's shared stock, kept from one project to the next.",
  "Décocher pour un panneau (contreplaqué, MDF) : rotation libre.": "Uncheck for a sheet good (plywood, MDF): free rotation.",
  "Catalogue": "Catalogue",
  "Une section qu'on peut ACHETER : la quantité ne borne plus rien.": "A size you can BUY: the quantity no longer limits anything.",
  "Prix": "Price",
  "Coût d'UNE planche, pas au mètre. 0 pour ne pas en tenir compte.": "Cost of ONE board, not per metre. 0 to ignore it.",
  "Défauts": "Defects",
  "bouts 30 ; rives 8 ; 1200-1280 ; 600,140,60,40 — recoupes de bout et de rive, nœud traversant, zone x,y,longueur,largeur.": "bouts 30 ; rives 8 ; 1200-1280 ; 600,140,60,40 — trim off each end, trim off each edge, a through knot, an area x,y,length,width.",
  "Une chute BISCORNUE, reste d'une planche imbriquée rangé au stock avec sa forme. Ne sert qu'à l'imbrication de contours.": "An ODD-SHAPED offcut: what is left of a nested board, put back into stock with its shape. Only ever used for nesting outlines.",

  // -- réglages
  "La scie": "The saw",
  "Trait de scie (mm)": "Kerf (mm)",
  "3 à 4 mm pour une lame de circulaire.": "3 to 4 mm for a circular saw blade.",
  "Coupe en bandes": "Strip cutting",
  "Scie à panneaux ou à format : déligner d'abord en bandes pleine longueur, puis tronçonner chaque bande.": "Panel saw or sliding table saw: rip into full-length strips first, then crosscut each strip.",
  "Surcote de longueur (mm)": "Length allowance (mm)",
  "Marge de recoupe ajoutée à chaque pièce au débit.": "Trimming margin added to every part when breaking down.",
  "Surcote de largeur (mm)": "Width allowance (mm)",
  "Idem en travers — de quoi dresser les rives.": "The same across — enough to joint the edges.",
  "Ce qui mérite d'être gardé": "What is worth keeping",
  "Chute mini — longueur (mm)": "Minimum offcut — length (mm)",
  "En dessous, le reste part aux pertes.": "Below that, what is left counts as waste.",
  "Chute mini — largeur (mm)": "Minimum offcut — width (mm)",
  "Le petit côté du reste.": "The short side of the leftover.",
  "Le bois": "The wood",
  "Tolérance d'épaisseur (mm)": "Thickness tolerance (mm)",
  "Le bruit de mesure, pas un vrai manque d'épaisseur.": "Measurement noise, not a real shortfall in thickness.",
  "Surcote de joint collé (mm)": "Glue joint allowance (mm)",
  "Largeur perdue à chaque collage d'une pièce composable.": "Width lost at each glue joint of a glued-up part.",
  "La CNC (contours imbriqués)": "The CNC (nested outlines)",
  "Écart entre contours (mm)": "Gap between outlines (mm)",
  "Diamètre de fraise plus un jeu.": "Cutter diameter plus some clearance.",
  "Marge au bord (mm)": "Edge margin (mm)",
  "Distance entre un contour et le bord de la planche.": "Distance between an outline and the edge of the board.",
  "Vitesse de fraisage (mm/min)": "Feed rate (mm/min)",
  "Pour estimer le temps de découpe d'une planche imbriquée.": "To estimate the cutting time of a nested board.",
  "Orientations": "Orientations",
  "Les angles essayés pour une pièce à fil indifférent.": "The angles tried for a part whose grain is either way.",
  "4 orientations (90°)": "4 orientations (90°)",
  "8 orientations (45°)": "8 orientations (45°)",
  "12 orientations (30°)": "12 orientations (30°)",
  "24 orientations (15°) — lent": "24 orientations (15°) — slow",
  "Le calcul": "The computation",
  "Privilégier": "Favour",
  "Entre deux plans dans le même bois neuf : moins de pertes, ou moins de coupes.": "Between two plans using the same new wood: less waste, or fewer cuts.",
  "le bois — moins de pertes": "the wood — less waste",
  "le temps de scie — moins de coupes": "sawing time — fewer cuts",
  "Essais de mélange": "Shuffled tries",
  "Ordres tirés au hasard en plus des stratégies réglées. Graine fixe : même plan.": "Random orders on top of the set strategies. Fixed seed: same plan every time.",
  "Passes d'amélioration": "Improvement passes",
  "Vider une planche, replacer ses pièces ailleurs. 0 pour s'en passer.": "Empty a board and place its parts elsewhere. 0 to skip it.",

  // -- état, version, calcul
  "Saisissez les pièces à débiter, vérifiez le stock, puis Calculer le débit (F5).": "Enter the parts to cut, check the stock, then Compute the plan (F5).",
  "Version ": "Version ",
  " du chutier. Vérification de la mise à jour…": " of the chutier. Checking for an update…",
  "À jour : c'est bien la dernière version (": "Up to date: this is the latest version (",
  " disponible. Toucher pour mettre à jour (Ctrl + Maj + R).": " available. Tap to update (Ctrl + Shift + R).",
  ". Hors-ligne : mise à jour non vérifiable.": ". Offline: cannot check for an update.",
  "Python n'a pas pu se charger : ": "Python could not load: ",
  "Prêt": "Ready",
  "Calcul interrompu — Python se recharge…": "Computation interrupted — Python is reloading…",
  "Rien à annuler": "Nothing to undo",
  "Rien à refaire": "Nothing to redo",
  "Aucun calcul": "No computation yet",
  "⚠ Saisie modifiée — F5 pour recalculer": "⚠ Input changed — F5 to recompute",
  "Brouillon repris": "Draft restored",
  "Aucune pièce à débiter.": "No parts to cut.",
  "Calcul…": "Computing…",
  "Calcul des contours sur {} cœurs…": "Computing the outlines on {} cores…",
  "Saisie invalide : ": "Invalid input: ",
  "Saisie invalide": "Invalid input",
  "Épingles relâchées : une planche ou une pièce a changé.": "Pins released: a board or a part has changed.",
  "Plan à jour": "Plan up to date",
  "Calcul interrompu — le plan précédent reste affiché": "Computation interrupted — the previous plan is still shown",
  "Le calcul a échoué : ": "The computation failed: ",
  "Échec du calcul": "Computation failed",

  // -- tables
  "◇ {} pts": "◇ {} pts",
  " · {} trou{}": " · {} hole{}",
  "{} référence(s), {} exemplaire(s)": "{} reference(s), {} item(s)",
  " dont {} contour(s) à imbriquer": " including {} outline(s) to nest",
  "matière non renseignée": "material not given",
  " · {}": " · {}",
  "Aucune pièce — ajoutez une ligne, collez un tableau (Ctrl+V), importez un CSV ou des contours SVG.": "No parts — add a row, paste a table (Ctrl+V), import a CSV or SVG outlines.",
  "{} référence(s)": "{} reference(s)",
  " · {} de l'atelier": " · {} from the workshop",
  " · {} chute(s) à écouler d'abord": " · {} offcut(s) to use up first",
  "Stock vide — le débit n'aura rien où se poser.": "Empty stock — the plan will have nothing to land on.",

  // -- tuiles du bilan
  "Pièces posées": "Parts placed",
  "{} / {}": "{} / {}",
  "{} non placée(s)": "{} not placed",
  "Rendement": "Yield",
  " m² de pièces": " m² of parts",
  "Planches entamées": "Boards used",
  "dont {} chute(s)": "including {} offcut(s)",
  "aucune chute écoulée": "no offcut used up",
  "Pertes": "Waste",
  "{} m de fraisage ≈ {} min": "{} m of milling ≈ {} min",
  "sciure et rebuts · {} coupe(s)": "sawdust and scrap · {} cut(s)",
  "Chutes créées": "Offcuts created",
  " m² à ranger": " m² to put away",
  "rien à garder": "nothing worth keeping",
  "À acheter": "To buy",
  "prix non renseignés": "no prices given",

  // -- listes
  "{} × « {} » — {} × {} × {} mm, {}": "{} × “{}” — {} × {} × {} mm, {}",
  " — {} €": " — €{}",
  " (biscornue, {} sommets)": " (odd-shaped, {} vertices)",
  "{} ×  {} × {} × {} mm — {}{}": "{} ×  {} × {} × {} mm — {}{}",
  "« {} » ×{} — {}": "“{}” ×{} — {}",
  "Ces pièces n'ont trouvé aucune place. Ajoutez du stock, relâchez le fil, ou cochez « Composable ».": "These parts found no room. Add stock, loosen the grain, or tick “Glue-up”.",
  "Tout est passé — aucune pièce laissée de côté.": "Everything fits — not one part left out.",

  // -- le plan
  " (ex. {})": " (no. {})",
  " [chute]": " [offcut]",
  " [catalogue]": " [catalogue]",
  "   —   {} m de fraisage": "   —   {} m of milling",
  "   —   ÉPINGLÉE": "   —   PINNED",
  "{}.  {}{}   —   {} × {} × {} mm, {}{}   —   {} pièce(s), rendement {} %{}{}": "{}.  {}{}   —   {} × {} × {} mm, {}{}   —   {} part(s), yield {} %{}{}",
  "chute biscornue": "odd-shaped offcut",
  "{} × {}": "{} × {}",
  "chute": "offcut",
  ", tournée de {}°": ", turned {}°",
  ", pivotée": ", turned",
  "{} {}/{} — {} × {} en ({}, {}){}": "{} {}/{} — {} × {} at ({}, {}){}",
  "{} ×{}": "{} ×{}",
  "chute réutilisable": "reusable offcut",
  "défaut écarté": "defect avoided",
  "perte": "waste",
  "{} · {}": "{} · {}",

  // -- impression
  "Feuille de débit": "Cutting list",
  " — {}/{} pièce(s), rendement {} %, {} planche(s), pertes {} m²": " — {}/{} part(s), yield {} %, {} board(s), waste {} m²",
  "{} {} × {}": "{} {} × {}",
  "découpe CNC : contours imbriqués, à exporter en SVG": "CNC cutting: nested outlines, export as SVG",
  "coupes :  ": "cuts:  ",
  "{} {} {}": "{} {} {}",
  "↕ tronçonnage, en travers du fil, à x mm du bout gauche — ↔ délignage, le long du fil, à y mm de la rive basse.": "↕ crosscut, across the grain, x mm from the left end — ↔ rip, along the grain, y mm from the bottom edge.",

  // -- fichiers
  "Ouverture impossible : ": "Could not open: ",
  "Import impossible : ": "Could not import: ",
  "{} pièce(s) lue(s) dans {}": "{} part(s) read from {}",
  "{} pièce(s) lue(s) dans {} — mais aucune planche en {} dans le stock (il y a : {}). Corrigez la colonne Matière, des deux côtés le même mot.": "{} part(s) read from {} — but no board in {} in the stock (there is: {}). Fix the Material column, the same word on both sides.",
  "Aucun tracé fermé dans ce SVG.\n": "No closed path in this SVG.\n",
  "{} contour(s) importé(s)\n\n": "{} outline(s) imported\n\n",
  "{} contour(s) importé(s)": "{} outline(s) imported",
  "Calculez d'abord le débit.": "Compute the plan first.",
  "Recalculez avant de ranger les chutes : la saisie a changé depuis le dernier calcul.": "Recompute before putting the offcuts away: the input has changed since the last run.",
  "Le stock sera mis à jour comme si le débit était fait : planches entamées en moins, chutes créées en plus, à l'atelier de ce navigateur. Continuer ?": "The stock will be updated as though the cutting were done: boards used removed, offcuts created added, in this browser's workshop. Carry on?",
  "Stock de l'atelier mis à jour dans ce navigateur.": "Workshop stock updated in this browser.",
  "Vider les pièces et le stock du projet ? (l'atelier reste)": "Clear the project's parts and stock? (the workshop stays)",

  // -- menu du plan
  "Relâcher la planche {}": "Release board {}",
  "Épingler la planche {} — la garder telle quelle": "Pin board {} — keep it as it is",
  "Tailler « {} » dans…": "Cut “{}” from…",
  "Laisser le chutier choisir": "Let the chutier choose",
  "Pièce déplacée — planche épinglée : reprise telle quelle au prochain calcul.": "Part moved — board pinned: it will be kept as it is at the next run.",

  // -- les raisons de non-placement, écrites par le cœur (optimiseur.py)
  "aucune planche de cette matière dans le stock": "no board of this material in the stock",
  "trop grande pour les formats du stock (fil compris)": "too big for the sizes in stock (grain included)",
  "aucune planche assez épaisse pour cette pièce": "no board thick enough for this part",
  "plus de place dans le stock fourni": "no more room in the stock given",
  "sa planche imposée n'est pas dans le stock": "the board it was forced onto is not in the stock",
  "sa planche imposée ne peut pas la recevoir": "the board it was forced onto cannot take it",
  "plus de place sur sa planche imposée": "no more room on the board it was forced onto",
  "seules des chutes biscornues de cette matière en stock : elles ne servent qu'à l'imbrication de contours": "only odd-shaped offcuts of this material in stock: those are used for nesting outlines and nothing else",

  // -- la page elle-même
  "Chutier — feuille de débit et stock de chutes": "Chutier — cutting list and offcut stock",
  "Chutier": "Chutier",
  "English / français": "English / français",
  "Version du chutier": "Version of the chutier",
  "feuille de débit, stock de chutes, imbrication CNC — dans votre navigateur, rien n'est envoyé nulle part": "cutting list, offcut stock, CNC nesting — in your browser, nothing is sent anywhere",
  "Vider les pièces et le stock du projet (l'atelier reste)": "Clear the project's parts and stock (the workshop stays)",
  "Nouveau": "New",
  "Rouvrir un projet enregistré (.json)": "Reopen a saved project (.json)",
  "Ouvrir…": "Open…",
  "Télécharger le projet (.json)": "Download the project (.json)",
  "Enregistrer": "Save",
  "Annuler (Ctrl+Z)": "Undo (Ctrl+Z)",
  "Refaire (Ctrl+Maj+Z)": "Redo (Ctrl+Shift+Z)",
  "Calculer le débit (F5)": "Compute the plan (F5)",
  "Calculer le débit": "Compute the plan",
  "Interrompre le calcul en cours (Échap)": "Stop the computation under way (Esc)",
  "Interrompre": "Stop",
  "Imprimer le plan et la liste des coupes (Ctrl+P)": "Print the plan and the list of cuts (Ctrl+P)",
  "Imprimer": "Print",
  "Plus…": "More…",
  "Importer des pièces (CSV)…": "Import parts (CSV)…",
  "Importer des pièces (FreeCAD .FCStd)…": "Import parts (FreeCAD .FCStd)…",
  "Exporter les pièces (CSV)": "Export the parts (CSV)",
  "Importer des contours (SVG)…": "Import outlines (SVG)…",
  "Exporter la découpe (SVG)": "Export the cutting (SVG)",
  "Exporter la découpe (DXF)": "Export the cutting (DXF)",
  "Exporter la découpe (LightBurn)": "Export the cutting (LightBurn)",
  "Exporter la fiche d'atelier (texte)": "Export the workshop sheet (text)",
  "Exemple : panneaux": "Example: sheet goods",
  "Exemple : formes biscornues (CNC)": "Example: odd shapes (CNC)",
  "Tout désépingler": "Unpin everything",
  "Repères et conventions": "Conventions and landmarks",
  "Pièces": "Parts",
  "+ ligne": "+ row",
  "Dupliquer": "Duplicate",
  "Supprimer": "Delete",
  "colonnes avancées": "advanced columns",
  "Stock": "Stock",
  "Le stock de l'atelier mis à jour comme si le débit était fait : planches entamées en moins, chutes créées en plus": "The workshop stock updated as though the cutting were done: boards used removed, offcuts created added",
  "Ranger les chutes au stock": "Put the offcuts into stock",
  "Réglages": "Settings",
  "Retenus d'une séance à l'autre dans ce navigateur, comme le stock coché « Atelier ». Un projet enregistré garde les siens.": "Kept from one session to the next in this browser, like stock ticked “Workshop”. A saved project keeps its own.",
  "Plan de débit": "Cutting plan",
  "Pièces non placées": "Parts not placed",
  "Traits de scie": "Kerfs",
  "La CNC (G-code)": "The CNC (G-code)",
  "Dialecte": "Dialect",
  "LinuxCNC accepte G64, le changement d'outil T/M6 et la correction G43 ; GRBL les refuse et mélange nativement.": "LinuxCNC accepts G64, the T/M6 tool change and the G43 offset; GRBL rejects them and blends natively.",
  "LinuxCNC (RS274)": "LinuxCNC (RS274)",
  "GRBL / grblHAL": "GRBL / grblHAL",
  "Diamètre de fraise (mm)": "Cutter diameter (mm)",
  "Le diamètre RÉEL, mesuré. Il doit tenir dans l'écart entre contours du plan, sinon deux parcours voisins se recouvrent.": "The REAL diameter, measured. It must fit in the plan's gap between outlines, otherwise two neighbouring paths overlap.",
  "Sens de coupe": "Cutting direction",
  "En avalant, le tour se parcourt en horaire et les trous en anti-horaire : meilleur état de chant sur du panneau.": "Climb milling runs the outside clockwise and the holes anticlockwise: a better edge on sheet goods.",
  "en avalant": "climb",
  "en opposition": "conventional",
  "Profondeur de passe (mm)": "Depth of cut (mm)",
  "Ce qu'on descend par tour. La moitié du diamètre en panneau, le diamètre en tendre.": "How far down per loop. Half the diameter in sheet goods, the whole diameter in softwood.",
  "Dépassement sous la planche (mm)": "Overcut below the board (mm)",
  "Ce qu'on mord dans le martyr, pour traverser vraiment.": "How far into the spoilboard, so it really goes through.",
  "Plongée en Z (mm/min)": "Plunge in Z (mm/min)",
  "Bien plus lente que l'avance : la fraise coupe mal par le bout.": "Much slower than the feed: an end mill cuts badly with its tip.",
  "Broche (tr/min)": "Spindle (rpm)",
  "Zéro n'écrit ni M3 ni M5 — pour une broche lancée à la main.": "Zero writes neither M3 nor M5 — for a spindle started by hand.",
  "Hauteur de sécurité (mm)": "Safe height (mm)",
  "La hauteur des déplacements rapides au-dessus de la planche.": "The height of rapid moves above the board.",
  "Numéro d'outil": "Tool number",
  "Le T<n> M6 du début. Zéro le saute. Sans effet en GRBL.": "The T<n> M6 at the start. Zero skips it. No effect on GRBL.",
  "Attaches par contour": "Tabs per outline",
  "Sans elles, la pièce se libère au dernier tour, la fraise la prend et l'envoie.": "Without them the part comes free on the last loop, the cutter catches it and throws it.",
  "Longueur d'une attache (mm)": "Tab length (mm)",
  "Le long du contour.": "Along the outline.",
  "Bois laissé sous l'attache (mm)": "Wood left under the tab (mm)",
  "Ce qu'il restera à couper au ciseau.": "What is left to pare off with a chisel.",
  "Longueur de rampe (mm)": "Ramp length (mm)",
  "La descente se fait en biais sur cette longueur. Zéro plonge droit — et casse la fraise.": "The descent slopes over this length. Zero plunges straight down — and breaks the cutter.",
  "Aspiration / air": "Extraction / air",
  "C'est le CÂBLAGE qui décide, pas le goût : la sortie qui n'est pas branchée ne fait rien, et le fichier tourne sans air sans que rien ne le dise.": "The WIRING decides, not taste: the output that is not connected does nothing at all, and the file runs without air with nothing to say so.",
  "aucune": "none",
  "M7 (brouillard)": "M7 (mist)",
  "M8 (arrosage)": "M8 (flood)",
  "Exporter le G-code (fraiseuse)": "Export the G-code (router)",
  "Glisser pour élargir la saisie (double-clic : largeur d'origine)": "Drag to widen the input side (double-click: original width)",
  "Dézoomer": "Zoom out",
  "Zoomer": "Zoom in",
  "Revoir tout le plan": "See the whole plan again",
  "Ajuster": "Fit",
  "Chargement de Python dans le navigateur (une quinzaine de Mo la première fois, ensuite en cache)…": "Loading Python in the browser (some fifteen megabytes the first time, cached afterwards)…",
  "Ctrl+molette : zoomer — clic droit sur une planche : l'épingler — clic droit sur une pièce : la tailler dans une autre planche — sur une planche imbriquée, glisser une pièce la déplace (la planche s'épingle).": "Ctrl+wheel: zoom — right-click a board: pin it — right-click a part: cut it from another board — on a nested board, dragging a part moves it (the board gets pinned).",
  "Les planches NEUVES réellement entamées — les chutes, déjà en atelier, n'y figurent jamais. Renseignez le prix d'une planche dans le stock pour obtenir le coût.": "The NEW boards actually used — offcuts, already in the workshop, never appear here. Give a board's price in the stock to get the cost.",
  "Les restes assez grands pour resservir — la raison d'être du chutier. « Ranger les chutes au stock » met l'atelier à jour comme si le débit était fait.": "The leftovers big enough to serve again — the whole point of the chutier. “Put the offcuts into stock” updates the workshop as though the cutting were done.",
  "Python se charge…": "Python is loading…",
  "Code source, LGPL-2.1": "Source code, LGPL-2.1",
  "· Atelier du Verdier": "· Atelier du Verdier",

  // -- l'aide
  "Le geste : les pièces à débiter, le stock où les tailler, les réglages de scie, puis Calculer (F5). Le plan se lit à droite, toutes planches empilées.\n\nSaisie : Ctrl+V colle un bloc venu d'un tableur (colonnes séparées par une tabulation ou un point-virgule) ; Entrée passe à la ligne suivante ; Ctrl+Suppr ôte la ligne ; clic sur une ligne pour la choisir, Ctrl-clic pour en ajouter.\n\nL'atelier : les lignes de stock cochées « Atelier » restent dans ce navigateur d'un projet à l'autre. « Ranger les chutes au stock » y écrit aussitôt.\n\nCorriger le plan : clic droit sur une planche pour l'épingler (reprise telle quelle au prochain calcul), clic droit sur une pièce pour la tailler dans une autre planche.\n\nLa CNC : Plus… → Importer des contours (SVG) ajoute aux pièces chaque tracé fermé ; dès qu'une matière compte un contour, tout ce lot est imbriqué à la fraise. Plus… → exporter la découpe sort chaque planche en SVG, DXF ou LightBurn à l'échelle 1, pour la chaîne CNC ou le laser.\n\nTout est en millimètres. La longueur court le long du fil. Une planche plus épaisse que la pièce convient, jamais une plus mince. Les chutes passent avant les planches neuves. Rien ne quitte votre navigateur.":
    "How it goes: the parts to cut, the stock to cut them from, the saw settings, then Compute (F5). The plan reads on the right, all boards stacked.\n\nEntering: Ctrl+V pastes a block from a spreadsheet (columns separated by a tab or a semicolon); Enter moves to the next row; Ctrl+Delete removes the row; click a row to select it, Ctrl-click to add to the selection.\n\nThe workshop: stock rows ticked “Workshop” stay in this browser from one project to the next. “Put the offcuts into stock” writes to it straight away.\n\nCorrecting the plan: right-click a board to pin it (kept as it is at the next run), right-click a part to cut it from another board.\n\nThe CNC: More… → Import outlines (SVG) adds every closed path to the parts; as soon as one material has an outline, that whole lot is nested for the router. More… → export the cutting writes each board as SVG, DXF or LightBurn at scale 1, for the CNC chain or the laser.\n\nEverything is in millimetres. Length runs along the grain. A board thicker than the part will do, a thinner one never will. Offcuts come before new boards. Nothing leaves your browser.",
};

const LANGUES = { fr: {}, en: ANGLAIS };
const ORIGINE = new WeakMap();          // nœud de texte -> son français
const CLE_LANGUE = "chutier.langue";

function langueInitiale() {
  try {
    const gardee = localStorage.getItem(CLE_LANGUE);
    if (gardee === "fr" || gardee === "en") return gardee;
  } catch (_) { /* stockage refusé : on devine */ }
  return (navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en";
}

export let langue = langueInitiale();

/** Le texte traduit, ou le français si la clé manque (jamais rien de vide). */
export function t(premier, ...valeurs) {
  // Gabarit : t`… ${x} …` → la clé porte {} à la place des valeurs.
  const cle = Array.isArray(premier) ? premier.raw.join("{}") : premier;
  const traduit = LANGUES[langue][cle] || cle;
  if (!Array.isArray(premier)) return traduit;
  let i = 0;
  return traduit.replace(/\{\}/g, () => String(valeurs[i++] ?? ""));
}

/** La liste des clés connues — pour le test de synchronisation. */
export const clesAnglaises = () => Object.keys(ANGLAIS);

/**
 * Traduit la page elle-même : le texte des éléments et leurs attributs
 * `title` / `placeholder`. Le français d'origine est gardé dans un
 * `data-fr` au premier passage, sans quoi le second changement de langue
 * chercherait à traduire de l'anglais.
 */
export function traduirePage(racine = document) {
  const marquer = (el, cle, valeur) => {
    const attr = "data-fr-" + cle;
    if (!el.hasAttribute(attr)) el.setAttribute(attr, valeur);
    return el.getAttribute(attr);
  };
  for (const el of racine.querySelectorAll("[title]")) {
    el.setAttribute("title", t(marquer(el, "title", el.getAttribute("title"))));
  }
  for (const el of racine.querySelectorAll("[placeholder]")) {
    el.setAttribute("placeholder", t(marquer(el, "placeholder", el.getAttribute("placeholder"))));
  }
  // Le texte : on garde le français d'origine (espaces compris) dans une
  // table faible, sinon repasser en français chercherait à traduire de
  // l'anglais. Les zones rebâties par app.js (plan, tuiles, tables,
  // réglages, impression) sont sautées : elles passent déjà par t().
  const marche = document.createTreeWalker(racine.body || racine, NodeFilter.SHOW_TEXT);
  const noeuds = [];
  while (marche.nextNode()) noeuds.push(marche.currentNode);
  for (const noeud of noeuds) {
    const parent = noeud.parentElement;
    // #plan est sauté (app.js le rebâtit en SVG à chaque dessin) — mais
    // son message d'accueil, lui, est écrit dans la page et doit suivre.
    if (!parent || (parent.closest("script, style, #plan, #impression, #tuiles, table, #menu-contextuel, #reglages")
                    && parent.id !== "plan-vide")) continue;
    if (!ORIGINE.has(noeud)) {
      if (!noeud.nodeValue.trim()) continue;
      ORIGINE.set(noeud, noeud.nodeValue);
    }
    const brut = ORIGINE.get(noeud);
    const francais = brut.trim();
    noeud.nodeValue = brut.replace(francais, t(francais));
  }
  document.documentElement.lang = langue;
  if (document.title) document.title = t(marquer(document.documentElement, "titre", document.title));
}

/** Change de langue et retient le choix dans ce navigateur. */
export function changerLangue(nouvelle) {
  langue = nouvelle === "en" ? "en" : "fr";
  try { localStorage.setItem(CLE_LANGUE, langue); } catch (_) { /* tant pis */ }
  return langue;
}
