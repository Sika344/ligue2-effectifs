/* season.js — sélecteur de saison partagé par toutes les pages du site.
 *
 * PRINCIPE : chaque saison a ses propres fichiers, explicitement suffixés.
 *   xg_2025-2026.json   xg_2026-2027.json
 *   ligue2_2025-2026.json   ligue2_2026-2027.json
 * Aucun fichier « nu » n'est plus utilisé : un nom sans saison était ambigu,
 * et c'est exactement ce qui avait fait diverger ligue2.json (effectifs 26-27
 * sous une étiquette 25-26).
 *
 * POUR AJOUTER UNE SAISON : l'ajouter à LIST ci-dessous, et déposer les JSON
 * correspondants. Rien d'autre à toucher dans les pages.
 *
 * Les build_*.py, eux, produisent toujours un fichier nu pour la saison qu'ils
 * traitent : il faut donc le renommer (ou lancer le workflow « archive saison »)
 * après chaque génération.
 *
 * Le choix est mémorisé et se propage d'une page à l'autre via ?s= dans l'URL.
 */
(function () {
  "use strict";

  var DEFAUT  = "2025-2026";   // saison pre-selectionnee a l'arrivee sur le site
  var LIST    = ["2026-2027", "2025-2026"];   // ordre d'affichage
  var KEY     = "l2_saison";

  function lire() {
    var q = null;
    try { q = new URLSearchParams(location.search).get("s"); } catch (e) {}
    if (q && LIST.indexOf(q) >= 0) {
      try { localStorage.setItem(KEY, q); } catch (e) {}
      return q;
    }
    try {
      var v = localStorage.getItem(KEY);
      if (v && LIST.indexOf(v) >= 0) return v;
    } catch (e) {}
    return DEFAUT;
  }

  var courante = lire();

  /* TOUT est suffixe, sans exception : chaque saison a ses propres fichiers,
     explicitement nommes. Plus aucun fichier "nu" dont la saison serait
     ambigue -- c'etait le cas de ligue2.json, qui portait le nom de la saison
     courante tout en contenant les effectifs de la suivante.
       xg.json -> xg_2025-2026.json ou xg_2026-2027.json */
  function fichier(nom) {
    return String(nom).replace(/\.json(\?|$)/, "_" + courante + ".json$1");
  }

  /* Ajoute ?s=<saison> aux liens internes pour garder le choix en naviguant. */
  function propager() {
    var liens = document.querySelectorAll('.sitenav a[href$=".html"], select.viewsel option');
    Array.prototype.forEach.call(liens, function (el) {
      var attr = el.tagName === "OPTION" ? "value" : "href";
      var v = el.getAttribute(attr);
      if (v && v.indexOf("?") < 0) el.setAttribute(attr, v + "?s=" + courante);
    });
  }

  /* Insère la liste déroulante dans la barre de navigation. */
  function monter() {
    var nav = document.querySelector(".sitenav");
    if (!nav || nav.querySelector(".seasonsel")) return;

    /* rapport-pre-match.html a deja son propre selecteur (#seasonSelect) :
       on ne le double pas, on se contente de le caler sur le choix global. */
    var propre = document.getElementById("seasonSelect");
    if (propre) {
      propre.addEventListener("change", function () {
        try { localStorage.setItem(KEY, propre.value); } catch (e) {}
      });
      // Changer .value ne declenche PAS l'evenement "change" : sans ce dispatch,
      // le menu afficherait la saison choisie ailleurs sur le site alors que la
      // page continuerait d'afficher les donnees de sa saison par defaut.
      if (propre.value !== courante) {
        var existe = Array.prototype.some.call(propre.options, function (o) {
          return o.value === courante;
        });
        if (existe) {
          propre.value = courante;
          propre.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
      return;
    }

    var sel = document.createElement("select");
    sel.className = "seasonsel";
    sel.setAttribute("aria-label", "Choisir la saison");
    sel.innerHTML = LIST.map(function (s) {
      return '<option value="' + s + '"' + (s === courante ? " selected" : "") +
             ">" + s.replace("-", "/") + "" + "</option>";
    }).join("");
    sel.style.cssText =
      "margin:9px 3px 9px auto;padding:6px 10px;font-family:inherit;font-size:12.5px;" +
      "font-weight:650;color:#0a1733;border:1px solid #c3cad6;border-radius:8px;" +
      "background:#fbfcfd;cursor:pointer;flex:0 0 auto";
    sel.onchange = function () {
      try { localStorage.setItem(KEY, sel.value); } catch (e) {}
      var u = new URL(location.href);
      u.searchParams.set("s", sel.value);
      location.href = u.toString();
    };
    nav.appendChild(sel);
    propager();
  }

  window.SEASON = {
    courante: courante,
    DEFAUT: DEFAUT,
    LIST: LIST,
    estCourante: false,
    fichier: fichier,
    monter: monter,
    /* Message à afficher quand un JSON de saison passée est absent. */
    absent: function (nom) {
      return "Données indisponibles pour la saison " + courante.replace("-", "/") +
             " (" + fichier(nom) + " absent du dépôt).";
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", monter);
  } else {
    monter();
  }
})();
