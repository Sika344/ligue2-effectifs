/* season.js — sélecteurs COMPÉTITION et SAISON partagés par toutes les pages.
 *
 * ============================================================= DEUX AXES
 * Le site couvrait la Ligue 2 sur plusieurs saisons. Il couvre maintenant
 * deux compétitions, chacune sur ses saisons. Chaque jeu de données est donc
 * identifié par un couple (compétition, saison), et porte un nom de fichier
 * qui dit les deux.
 *
 *   Ligue 2 : xg_2026-2027.json        (INCHANGÉ, pas de préfixe)
 *   Ligue 1 : xg_L1_2026-2027.json     (préfixe L1_)
 *
 * POURQUOI LA LIGUE 2 N'A PAS DE PRÉFIXE. Tous ses fichiers existent déjà
 * sous ces noms, produits et vérifiés depuis des mois. Leur ajouter un
 * préfixe aurait voulu dire renommer une soixantaine de fichiers et relancer
 * autant de chaînes pour n'y rien gagner. Le préfixe vide n'est pas une
 * négligence : c'est ce qui garantit que l'ajout de la Ligue 1 ne peut PAS
 * casser la Ligue 2.
 *
 * ================================================= POUR AJOUTER UNE SAISON
 * L'ajouter dans SAISONS, sous la compétition concernée, et déposer les JSON.
 * Rien d'autre à toucher dans les pages.
 *
 * ============================================ POUR AJOUTER UNE COMPÉTITION
 * Une entrée dans LIGUES, une liste dans SAISONS. Les pages suivent seules.
 *
 * Les deux choix sont mémorisés et se propagent d'une page à l'autre via
 * ?c= (compétition) et ?s= (saison) dans l'URL.
 */
(function () {
  "use strict";

  /* id : ce qui circule dans l'URL et le stockage local
     nom : ce qui s'affiche dans la liste déroulante
     comp : l'identifiant StatsBomb, pour information et usage éventuel
     prefixe : ce qui s'insère dans le nom de fichier (vide = Ligue 2) */
  /* `club` est le club suivi dans cette compétition : celui qu'on met en
     évidence dans les classements, qu'on ouvre par défaut dans les rapports
     et les profils individuels. Écrit ici et nulle part ailleurs.
     `alias` sert à le retrouver quand la source le nomme autrement — « Rennes »
     chez StatsBomb, « Stade Rennais » à la LFP. La recherche est tolérante
     (voir clubParmi), parce qu'un club non reconnu ferait silencieusement
     basculer la page sur la première équipe de la liste, par ordre
     alphabétique, sans que rien ne le signale. */
  var LIGUES = [
    { id: "L2", nom: "Ligue 2", comp: 8, prefixe: "",
      club: "Montpellier", alias: ["Montpellier HSC", "MHSC"] },
    { id: "L1", nom: "Ligue 1", comp: 7, prefixe: "L1_",
      club: "Rennes", alias: ["Stade Rennais", "Stade Rennais FC", "Rennes FC"] }
  ];

  /* Saisons disponibles PAR compétition, dans l'ordre d'affichage.
     La Ligue 1 n'a que 2026-2027 : c'est un choix, pas une limite technique.
     Les 360 existent chez StatsBomb depuis 2020/2021 pour les deux. */
  var SAISONS = {
    L2: ["2026-2027", "2025-2026"],
    L1: ["2026-2027"]
  };

  var LIGUE_DEFAUT  = "L2";          // le site s'ouvre sur la Ligue 2
  var SAISON_DEFAUT = "2025-2026";   // saison pré-sélectionnée en Ligue 2

  var KEY_LIGUE  = "l2_ligue";
  var KEY_SAISON = "l2_saison";

  function param(nom) {
    try { return new URLSearchParams(location.search).get(nom); } catch (e) { return null; }
  }
  function stocke(cle, v) { try { localStorage.setItem(cle, v); } catch (e) {} }
  function stocke_lire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }

  function infos(id) {
    for (var i = 0; i < LIGUES.length; i++) if (LIGUES[i].id === id) return LIGUES[i];
    return LIGUES[0];
  }
  function connue(id) { return !!SAISONS[id]; }

  /* --- la compétition : URL, puis mémoire, puis défaut --- */
  function lireLigue() {
    var q = param("c");
    if (q && connue(q)) { stocke(KEY_LIGUE, q); return q; }
    var v = stocke_lire(KEY_LIGUE);
    if (v && connue(v)) return v;
    return LIGUE_DEFAUT;
  }

  var ligue = lireLigue();
  var LIST  = SAISONS[ligue];

  /* --- la saison : même ordre, MAIS validée contre la compétition courante.
     Sans ce garde-fou, quelqu'un qui consulte la Ligue 2 en 2025-2026 puis
     bascule en Ligue 1 demanderait xg_L1_2025-2026.json, qui n'existe pas :
     la page afficherait « données indisponibles » sans qu'on comprenne
     pourquoi. On retombe silencieusement sur la saison la plus récente de la
     compétition choisie, qui est toujours en tête de liste. */
  function lireSaison() {
    var q = param("s");
    if (q && LIST.indexOf(q) >= 0) { stocke(KEY_SAISON, q); return q; }
    var v = stocke_lire(KEY_SAISON);
    if (v && LIST.indexOf(v) >= 0) return v;
    if (LIST.indexOf(SAISON_DEFAUT) >= 0) return SAISON_DEFAUT;
    return LIST[0];
  }

  var courante = lireSaison();
  var L = infos(ligue);

  /* TOUT est suffixé, sans exception : chaque couple compétition-saison a ses
     propres fichiers, explicitement nommés. Plus aucun fichier « nu » dont la
     saison serait ambiguë — c'était le cas de ligue2.json, qui portait le nom
     de la saison courante tout en contenant les effectifs de la suivante.
       xg.json -> xg_2026-2027.json       (Ligue 2)
       xg.json -> xg_L1_2026-2027.json    (Ligue 1) */
  function fichier(nom) {
    return String(nom).replace(/\.json(\?|$)/, "_" + L.prefixe + courante + ".json$1");
  }

  /* Ajoute ?c=<ligue>&s=<saison> aux liens internes pour garder les deux
     choix en naviguant. Un lien qui porte déjà un « ? » est laissé tel quel :
     il a été construit exprès par la page, on ne le réécrit pas. */
  function propager() {
    var liens = document.querySelectorAll('.sitenav a[href$=".html"], select.viewsel option');
    Array.prototype.forEach.call(liens, function (el) {
      var attr = el.tagName === "OPTION" ? "value" : "href";
      var v = el.getAttribute(attr);
      if (v && v.indexOf("?") < 0) {
        el.setAttribute(attr, v + "?c=" + ligue + "&s=" + courante);
      }
    });
  }

  /* Recharge la page en changeant un paramètre. La saison n'est PAS reportée
     lors d'un changement de compétition : elle sera revalidée à l'arrivée
     contre les saisons de la nouvelle compétition. */
  function aller(cle, valeur) {
    var u = new URL(location.href);
    u.searchParams.set(cle, valeur);
    if (cle === "c") u.searchParams.delete("s");
    location.href = u.toString();
  }

  var STYLE =
    "margin:9px 3px;padding:6px 10px;font-family:inherit;font-size:12.5px;" +
    "font-weight:650;color:#0a1733;border:1px solid #c3cad6;border-radius:8px;" +
    "background:#fbfcfd;cursor:pointer;flex:0 0 auto";

  function monter() {
    var nav = document.querySelector(".sitenav");
    if (!nav || nav.querySelector(".liguesel")) return;

    /* --- le titre suit la compétition ---
       Les 12 pages portent « ⚽ Ligue 2 <span>Analyse</span> » en dur dans
       leur HTML. Plutôt que d'éditer douze fichiers — et de devoir les
       rééditer à chaque compétition ajoutée — on réécrit le titre ici, au
       seul endroit qui connaît la compétition courante. Le <span> est
       reconstruit à l'identique : c'est lui qui porte le style gris. */
    var marque = nav.querySelector(".brand");
    if (marque) {
      marque.innerHTML = "⚽ " + L.nom + "<span>Analyse</span>";
    }

    /* Le titre de l'onglet du navigateur porte « Ligue 2 » dans les douze
       pages. Même raisonnement que pour la marque : on le réécrit ici au lieu
       d'éditer douze fichiers. On remplace le libellé de CHAQUE autre
       compétition, pas seulement « Ligue 2 », sans quoi passer de la Ligue 1
       à la Ligue 2 laisserait « Ligue 1 » affiché dans l'onglet. */
    try {
      var t = document.title;
      for (var k = 0; k < LIGUES.length; k++) {
        if (LIGUES[k].id !== ligue) {
          t = t.split(LIGUES[k].nom).join(L.nom);
        }
      }
      if (t !== document.title) document.title = t;
    } catch (e) {}

    /* Pastilles « compétition + saison » purement statiques dans le HTML
       (Analytics 360, SportsCode). Les autres pages ont la leur remplie par
       leur propre JS au chargement des données ; ces deux-là n'en ont pas.
       Elles portent donc l'attribut data-ligue-saison et c'est nous qui les
       remplissons. Le texte d'origine est conservé comme préfixe quand il dit
       autre chose que la compétition — « StatsBomb 360 · », par exemple. */
    var pastilles = nav.ownerDocument
      ? nav.ownerDocument.querySelectorAll("[data-ligue-saison]")
      : [];
    Array.prototype.forEach.call(pastilles, function (el) {
      var p = el.getAttribute("data-ligue-saison") || "";
      el.textContent = (p ? p + " · " : "") + L.nom + " " + courante.replace("-", "/");
    });

    /* --- la compétition, toujours montée, sur TOUTES les pages ---
       Elle vient en premier : on choisit la compétition, puis la saison.
       `margin-left:auto` la pousse à droite ; le sélecteur de saison qui
       suit se colle contre elle. */
    var sl = document.createElement("select");
    sl.className = "liguesel";
    sl.setAttribute("aria-label", "Choisir la compétition");
    sl.innerHTML = LIGUES.map(function (g) {
      return '<option value="' + g.id + '"' + (g.id === ligue ? " selected" : "") +
             ">" + g.nom + "</option>";
    }).join("");
    sl.style.cssText = STYLE + ";margin-left:auto";
    sl.onchange = function () {
      stocke(KEY_LIGUE, sl.value);
      aller("c", sl.value);
    };
    nav.appendChild(sl);

    /* --- la saison ---
       rapport-pre-match.html a déjà son propre sélecteur (#seasonSelect) :
       on ne le double pas, on se contente de le caler sur le choix global. */
    var propre = document.getElementById("seasonSelect");
    if (propre) {
      propre.addEventListener("change", function () {
        stocke(KEY_SAISON, propre.value);
      });
      // Changer .value ne déclenche PAS l'événement "change" : sans ce
      // dispatch, le menu afficherait la saison choisie ailleurs sur le site
      // alors que la page continuerait d'afficher les données de sa saison
      // par défaut.
      if (propre.value !== courante) {
        var existe = Array.prototype.some.call(propre.options, function (o) {
          return o.value === courante;
        });
        if (existe) {
          propre.value = courante;
          propre.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
      propager();
      return;
    }

    var sel = document.createElement("select");
    sel.className = "seasonsel";
    sel.setAttribute("aria-label", "Choisir la saison");
    sel.innerHTML = LIST.map(function (s) {
      return '<option value="' + s + '"' + (s === courante ? " selected" : "") +
             ">" + s.replace("-", "/") + "</option>";
    }).join("");
    sel.style.cssText = STYLE;
    /* Une seule saison disponible : la liste n'offre aucun choix, on la
       grise plutôt que de laisser croire qu'il y a quelque chose à cliquer. */
    if (LIST.length < 2) sel.disabled = true;
    sel.onchange = function () {
      stocke(KEY_SAISON, sel.value);
      aller("s", sel.value);
    };
    nav.appendChild(sel);
    propager();
  }

  window.SEASON = {
    courante: courante,
    DEFAUT: SAISON_DEFAUT,
    LIST: LIST,
    estCourante: false,
    fichier: fichier,
    monter: monter,

    /* --- l'axe compétition, lisible par les pages ---
       classement.html s'en sert pour le club mis en évidence, le rapport
       pour son club par défaut, etc. */
    ligue: ligue,            // "L2" ou "L1"
    ligueNom: L.nom,         // "Ligue 2" ou "Ligue 1"
    comp: L.comp,            // 8 ou 7, identifiant StatsBomb
    prefixe: L.prefixe,      // "" ou "L1_"
    LIGUES: LIGUES,
    estL1: ligue === "L1",

    /* --- le club suivi --- */
    club: L.club,

    /* Retrouve le club suivi dans une liste de noms venue des données.
       Trois passes, de la plus sûre à la plus tolérante : égalité stricte,
       puis alias connus, puis inclusion insensible à la casse et aux
       accents. Rend null si rien ne correspond — à l'appelant de décider
       quoi faire, plutôt que de lui rendre une équipe au hasard. */
    clubParmi: function (noms) {
      if (!noms || !noms.length) return null;
      var cands = [L.club].concat(L.alias || []);
      var i, j;
      for (i = 0; i < cands.length; i++) {
        for (j = 0; j < noms.length; j++) if (noms[j] === cands[i]) return noms[j];
      }
      function pl(s) {
        return String(s || "").normalize("NFD")
          .replace(/[̀-ͯ]/g, "").toLowerCase();
      }
      for (i = 0; i < cands.length; i++) {
        var c = pl(cands[i]);
        for (j = 0; j < noms.length; j++) {
          var n = pl(noms[j]);
          if (n === c || n.indexOf(c) >= 0 || c.indexOf(n) >= 0) return noms[j];
        }
      }
      return null;
    },

    /* Message à afficher quand un JSON est absent. Il nomme la compétition :
       en Ligue 1 au lancement, l'absence sera fréquente le temps que les
       chaînes tournent, et « saison 2026/2027 » tout seul laisserait croire
       à un problème de saison. */
    absent: function (nom) {
      return "Données indisponibles pour " + L.nom + " " +
             courante.replace("-", "/") +
             " (" + fichier(nom) + " absent du dépôt).";
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", monter);
  } else {
    monter();
  }
})();
