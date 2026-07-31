/* season.js — sélecteur de saison partagé par les pages du site.
 *
 * Convention de nommage des données (celle des build_*.py) :
 *   · saison courante  -> fichier SANS suffixe        xg.json
 *   · saison passée    -> fichier suffixé             xg_2025-2026.json
 *
 * >>> LE JOUR DE LA BASCULE (1re journée de L2 2026-27, week-end du 8 août) :
 *     1. lancer le workflow « archive saison » pour figer 2025-2026 ;
 *     2. passer CURRENT ci-dessous à "2026-2027" ;
 *     3. passer CURRENT_SEASON à "2026-2027" dans chaque build_*.py.
 *     Tant que l'étape 1 n'est pas faite, choisir 2025-2026 ne trouvera rien.
 *
 * La saison choisie est mémorisée et se propage d'une page à l'autre par le
 * paramètre ?s= ajouté aux liens de navigation.
 */
(function () {
  "use strict";

  var CURRENT = "2025-2026";                  // <- à changer le 8 août
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
    return CURRENT;
  }

  var courante = lire();

  /* "xg.json" -> "xg.json" si saison courante, "xg_2025-2026.json" sinon. */
  function fichier(nom) {
    if (courante === CURRENT) return nom;
    return String(nom).replace(/\.json(\?|$)/, "_" + courante + ".json$1");
  }

  /* Ajoute ?s=<saison> aux liens internes pour garder le choix en naviguant. */
  function propager() {
    if (courante === CURRENT) return;
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

    var sel = document.createElement("select");
    sel.className = "seasonsel";
    sel.setAttribute("aria-label", "Choisir la saison");
    sel.innerHTML = LIST.map(function (s) {
      return '<option value="' + s + '"' + (s === courante ? " selected" : "") +
             ">" + s.replace("-", "/") + (s === CURRENT ? " · en cours" : "") + "</option>";
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
    CURRENT: CURRENT,
    LIST: LIST,
    estCourante: courante === CURRENT,
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
