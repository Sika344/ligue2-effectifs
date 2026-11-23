#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_mendy.py — compare Alexandre Mendy aux avants-centres de Saudi Pro League.

Produit mendy_saudi.html, un fichier autonome à ouvrir dans un navigateur.
Sans rapport avec le site : ce script ne lit ni n'écrit aucun fichier du dépôt.

================================================================== LE VISUEL
Une bande par métrique, comme le graphique PPDA des équipes : chaque joueur
est un point placé selon sa valeur, avec les repères P50 et P90.

  - points GRIS pour les avants-centres du championnat, le nom au survol
  - écusson du club pour les quatre joueurs mis en avant, nom affiché dessous

Les écussons sont INTÉGRÉS au fichier en base64, pas liés : le visuel reste
lisible hors ligne et ne dépend pas de la survie d'une URL. Si un écusson ne
se télécharge pas, on retombe sur une pastille aux initiales plutôt que de
casser la bande.

============================================================== LE GROUPE
Avants-centres au sens strict — les trois postes axiaux de StatsBomb — avec au
moins 200 minutes. Le nombre de joueurs retenus est affiché sous chaque bande :
un percentile calculé sur douze joueurs ne vaut pas celui calculé sur quarante,
et c'est au lecteur de le savoir.

USAGE :
    SB_USERNAME='…' SB_PASSWORD='…' python build_mendy.py
"""

import os
import re
import json
import base64
import datetime
import time
import unicodedata

import requests
from statsbombpy import sb

COMPETITION_ID = 194          # Pro League, Arabie saoudite
SORTIE = "mendy_saudi.html"
SORTIE_SVG = "mendy_saudi.svg"
SORTIE_PNG = "mendy_saudi.png"
MIN_MINUTES = int(os.environ.get("MIN_MINUTES", "200"))

POSTES_AXIAUX = {"Centre Forward", "Left Centre Forward", "Right Centre Forward"}

# (clé StatsBomb, intitulé affiché, décimales, sens)
# sens = +1 quand « plus, c'est mieux ». Les cinq le sont.
METRIQUES = [
    ("player_season_np_xg_90",                 "Non-penalty xG", 2, 1),
    ("player_season_touches_inside_box_90",    "Touches in box", 1, 1),
    ("player_season_conversion_ratio",         "Goal conversion %", 1, 1),
    ("player_season_xa_90",                    "xG Assisted", 2, 1),
    # Renommé à la demande de Geoffrey. Le nom est d'ailleurs plus juste que
    # celui de StatsBomb : la métrique vaut (buts + passes décisives) moins
    # (xG + xA), donc bien un écart à l'attendu sur les deux registres.
    ("player_season_over_under_performance_90", "Goals and assists above expectation", 2, 1),
]
# Conversion % est une fraction chez StatsBomb (0,18 = 18 %) : on l'affiche en %.
EN_POURCENT = {"player_season_conversion_ratio"}

# Joueurs mis en avant : nom tel qu'attendu, club, couleur de repli, écusson.
VEDETTES = [
    ("Alexandre Mendy",  "Al Faisaly", "#7B1E2B",
     "https://upload.wikimedia.org/wikipedia/en/b/b0/Al_Faisaly_FC_logo.svg"),
    ("Ivan Toney",       "Al Ahli",    "#0A6B3D",
     "https://upload.wikimedia.org/wikipedia/en/4/45/Al_Ahli_Saudi_FC_logo.svg"),
    ("Cristiano Ronaldo", "Al Nassr",  "#F5C518",
     "https://upload.wikimedia.org/wikipedia/commons/3/3f/Nassr_FC_Logo.svg"),
    ("Alexandre Lacazette", "Neom SC", "#111111",
     "https://upload.wikimedia.org/wikipedia/en/0/09/Neom_SC_logo.svg"),
]

UA = {"User-Agent": "ligue2-effectifs/1.0"}


def nn(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def esc(t):
    return (str(t if t is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def val(row, cle):
    if cle not in row:
        return None
    v = row[cle]
    if v is None or v != v:
        return None
    return float(v)


def percentile(valeurs, v):
    """Rang moyen : les joueurs à égalité comptent pour une demi-place.

    Sans ce demi-rang, plusieurs joueurs à exactement 0 — fréquent sur
    « conversion » ou « xA » — recevraient tous le percentile le plus bas.
    """
    if not valeurs:
        return None
    inf = sum(1 for x in valeurs if x < v)
    eq = sum(1 for x in valeurs if x == v)
    return 100.0 * (inf + eq / 2) / len(valeurs)


def valeur_au_pct(triees, pct):
    if not triees:
        return None
    i = (len(triees) - 1) * pct / 100.0
    b, h = int(i), min(len(triees) - 1, int(i) + 1)
    return triees[b] if b == h else triees[b] + (triees[h] - triees[b]) * (i - b)


def ecusson(url):
    """SVG de l'écusson en data URL, ou None si le téléchargement échoue.

    Une courte pause avant chaque appel : Wikimedia renvoie un 429 quand on
    enchaîne quatre requêtes d'affilée, et on perdait un écusson sur quatre.
    """
    time.sleep(1.5)
    try:
        r = requests.get(url, headers=UA, timeout=30)
        if r.status_code != 200 or not r.content:
            print("   !! écusson indisponible (%s) : %s" % (r.status_code, url))
            return None
        mime = "image/svg+xml" if url.endswith(".svg") else "image/png"
        return "data:%s;base64,%s" % (mime, base64.b64encode(r.content).decode())
    except Exception as exc:
        print("   !! écusson illisible (%s) : %s" % (exc, url))
        return None


def saison_courante():
    comps = sb.competitions()
    c = comps[comps["competition_id"] == COMPETITION_ID]
    if c.empty:
        raise SystemExit(
            "ÉCHEC : la compétition %d (Saudi Pro League) n'est pas dans la "
            "licence. Rien n'a été écrit." % COMPETITION_ID)
    c = c.sort_values("season_id", ascending=False)
    return int(c.iloc[0]["season_id"]), str(c.iloc[0].get("season_name") or "")


# ===================================================================== IMAGE
# Le HTML est dessiné par le navigateur ; une image, non. On redessine donc les
# mêmes bandes en SVG, à partir des MÊMES données calculées plus haut — les
# chiffres ne peuvent pas diverger entre les deux sorties.
#
# Ce que l'image perd : le survol. Les points gris y deviennent anonymes. C'est
# assumé — les nommer tous rendrait la bande illisible — et c'est pourquoi le
# HTML reste produit à côté.

L_MARGE = 60          # marge gauche et droite, en pixels
L_LARGE = 1120        # largeur totale
H_BANDE = 250         # hauteur d'une bande


def _t(x, y, txt, taille=12, gras=False, ancre="start", couleur="#1f2937"):
    return ('<text x="%.1f" y="%.1f" font-family="Arial,Helvetica,sans-serif" '
            'font-size="%d" font-weight="%s" text-anchor="%s" fill="%s">%s</text>'
            % (x, y, taille, "bold" if gras else "normal", ancre, couleur, esc(txt)))


def dessiner_svg(bandes, snom, manquants):
    util = L_LARGE - 2 * L_MARGE
    haut = 150 + H_BANDE * len(bandes) + 120
    g = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
         'width="%d" height="%d" viewBox="0 0 %d %d">' % (L_LARGE, haut, L_LARGE, haut),
         '<rect width="%d" height="%d" fill="#ffffff"/>' % (L_LARGE, haut)]

    g.append(_t(L_MARGE, 54, "Alexandre Mendy — comparaison aux avants-centres de Saudi Pro League",
                21, True, couleur="#111827"))
    g.append(_t(L_MARGE, 78, "Saison %s · avants-centres axiaux · minimum %d minutes · source StatsBomb"
                % (snom, MIN_MINUTES), 12, couleur="#6b7280"))
    if manquants:
        g.append(_t(L_MARGE, 100, "Non retrouvé(s) : " +
                    ", ".join("%s (%s)" % (n, c) for n, c in manquants), 11, couleur="#92400e"))

    y0 = 150
    for b in bandes:
        axe = y0 + 118
        g.append(_t(L_MARGE, y0 + 6, b["lab"], 15, True, couleur="#111827"))
        g.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e5e7eb" stroke-width="2"/>'
                 % (L_MARGE, axe, L_LARGE - L_MARGE, axe))

        for cle, lib in (("p50x", "P50"), ("p90x", "P90")):
            x = L_MARGE + util * b[cle] / 100.0
            g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c3cad6" '
                     'stroke-width="1" stroke-dasharray="4 3"/>' % (x, y0 + 26, x, axe + 14))
            g.append(_t(x, y0 + 20, "%s · %s" % (lib, b[cle[:3]]), 11, True, "middle", "#9ca3af"))

        for p in b["pts"]:
            x = L_MARGE + util * p["x"] / 100.0
            if not p["ved"]:
                g.append('<circle cx="%.1f" cy="%.1f" r="7" fill="#c9ced8" '
                         'stroke="#ffffff" stroke-width="2"/>' % (x, axe))

        # Les joueurs mis en avant par-dessus, pour qu'aucun point gris ne les
        # recouvre, et décalés sur deux niveaux quand ils sont proches.
        for p in b["pts"]:
            if not p["ved"]:
                continue
            x = L_MARGE + util * p["x"] / 100.0
            yl = axe - 72 - 40 * int(p.get("niv") or 0)
            if p["logo"]:
                g.append('<image x="%.1f" y="%.1f" width="42" height="42" xlink:href="%s"/>'
                         % (x - 21, yl, p["logo"]))
            else:
                ini = "".join(w[0] for w in p["ved"].split())
                g.append('<circle cx="%.1f" cy="%.1f" r="20" fill="%s"/>'
                         % (x, yl + 21, p["couleur"] or "#555"))
                g.append(_t(x, yl + 26, ini, 13, True, "middle", "#ffffff"))
            # Un nom centré sur un joueur situé tout au bord sortait du cadre
            # (« Alexandre Lacazette » à droite). On bascule l'ancrage.
            if x < L_MARGE + 90:
                ancre, xt = "start", L_MARGE
            elif x > L_LARGE - L_MARGE - 90:
                ancre, xt = "end", L_LARGE - L_MARGE
            else:
                ancre, xt = "middle", x
            g.append(_t(xt, yl + 58, p["ved"], 11, True, ancre, "#111827"))
            g.append(_t(xt, yl + 72, p["val"], 11, True, ancre, "#0d3b8c"))
            g.append('<circle cx="%.1f" cy="%.1f" r="5" fill="#0d3b8c"/>' % (x, axe))

        g.append(_t(L_MARGE, axe + 26, b["min"], 12, couleur="#6b7280"))
        g.append(_t(L_LARGE - L_MARGE, axe + 26, b["max"], 12, ancre="end", couleur="#6b7280"))
        g.append(_t(L_MARGE, axe + 48, "%d avants-centres retenus" % b["n"], 11, couleur="#9ca3af"))
        y0 += H_BANDE

    pied = [
        "Chaque point est un avant-centre de Saudi Pro League. Les quatre joueurs mis en avant portent l'écusson de leur club.",
        "Les repères P50 et P90 situent la médiane et le neuvième décile du groupe. Les valeurs sont des cadences par 90 minutes,",
        "sauf « Goal conversion % ». « Goals and assists above expectation » est la métrique StatsBomb « Over/Under Performance » :",
        "buts et passes décisives moins xG et xA. Les points gris ne sont pas nommés sur l'image : leur nom s'affiche au survol",
        "dans la version HTML, produite à côté de celle-ci.",
    ]
    for i, t in enumerate(pied):
        g.append(_t(L_MARGE, y0 + 18 + i * 16, t, 11, couleur="#9ca3af"))

    g.append("</svg>")
    return "\n".join(g)


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        raise SystemExit("ERREUR : SB_USERNAME / SB_PASSWORD manquants.")

    sid, snom = saison_courante()
    print("Saudi Pro League, saison %s (season_id=%s)" % (snom, sid))

    df = sb.player_season_stats(competition_id=COMPETITION_ID, season_id=sid)
    print("   %d lignes reçues" % len(df))

    joueurs = []
    for _, r in df.iterrows():
        mn = val(r, "player_season_minutes")
        if mn is None or mn < MIN_MINUTES:
            continue
        poste = r.get("primary_position")
        if poste not in POSTES_AXIAUX:
            continue
        j = {"nom": r.get("player_name"), "club": r.get("team_name"),
             "min": int(round(mn)), "poste": poste, "v": {}}
        for cle, _lab, _dec, _sens in METRIQUES:
            j["v"][cle] = val(r, cle)
        joueurs.append(j)

    print("   %d avants-centres à %d minutes ou plus" % (len(joueurs), MIN_MINUTES))
    if len(joueurs) < 5:
        raise SystemExit(
            "ÉCHEC : seulement %d avants-centres au-dessus de %d minutes — "
            "un percentile n'aurait aucun sens. Rien n'a été écrit.\n"
            "Baisse MIN_MINUTES ou élargis le groupe aux ailiers."
            % (len(joueurs), MIN_MINUTES))

    # Rattachement des vedettes, par nom normalisé.
    index = {nn(j["nom"]): j for j in joueurs}
    vedettes = {}
    manquants = []
    for nom, club, couleur, url in VEDETTES:
        cible = index.get(nn(nom))
        if cible is None:
            # Nom de famille seul, si une seule correspondance : StatsBomb
            # écrit parfois « Cristiano Ronaldo dos Santos Aveiro ».
            fam = nn(nom).split()[-1]
            cands = [j for k, j in index.items() if fam in k.split()]
            cible = cands[0] if len(cands) == 1 else None
        if cible is None:
            manquants.append((nom, club))
            continue
        vedettes[id(cible)] = {"nom": nom, "club": club, "couleur": couleur,
                               "logo": ecusson(url)}
    if manquants:
        print("   !! non retrouvés dans le groupe :")
        for nom, club in manquants:
            print("      %-22s %s" % (nom, club))

    ecrire(joueurs, vedettes, snom, manquants)


def ecrire(joueurs, vedettes, snom, manquants):
    bandes = []
    for cle, lab, dec, _sens in METRIQUES:
        vals = [j["v"][cle] for j in joueurs if j["v"][cle] is not None]
        if len(vals) < 5:
            continue
        triees = sorted(vals)
        lo, hi = triees[0], triees[-1]
        etendue = (hi - lo) or 1.0
        p50 = valeur_au_pct(triees, 50)
        p90 = valeur_au_pct(triees, 90)

        pc = lambda v: (v - lo) / etendue * 100.0
        fmt = (lambda v: ("%." + str(dec) + "f") % (v * 100)) if cle in EN_POURCENT \
            else (lambda v: ("%." + str(dec) + "f") % v)

        pts = []
        for j in joueurs:
            v = j["v"][cle]
            if v is None:
                continue
            ved = vedettes.get(id(j))
            pts.append({
                "x": round(pc(v), 3), "nom": j["nom"], "club": j["club"],
                "val": fmt(v), "min": j["min"],
                "pct": round(percentile(vals, v)),
                "ved": ved["nom"] if ved else None,
                "logo": ved["logo"] if ved else None,
                "couleur": ved["couleur"] if ved else None,
            })
        pts.sort(key=lambda p: (p["ved"] is not None, p["x"]))

        # ANTI-CHEVAUCHEMENT. Deux joueurs mis en avant proches l'un de l'autre
        # voyaient leurs écussons se superposer et leurs noms se mélanger —
        # « Cristiano Ronaldo » et « Ivan Toney » devenaient illisibles. On les
        # répartit donc sur deux niveaux : dès qu'un écusson est à moins de
        # ECART_VED de son voisin de gauche déjà placé au niveau bas, il monte.
        # 17 % et non 11 : à 11, « Cristiano Ronaldo » et « Ivan Toney »
        # restaient superposés sur l'image, où les noms sont plus larges
        # que dans le HTML.
        # 17 % : à 11, « Cristiano Ronaldo » et « Ivan Toney » restaient
        # superposés sur l'image, où les noms sont plus larges que dans le HTML.
        ECART_VED = 17.0          # en % de la largeur de la bande
        NIVEAUX = 3               # deux niveaux ne suffisent pas quand trois
                                  # joueurs se tiennent dans quelques pourcents
        dernier = [None] * NIVEAUX
        for p in sorted([x for x in pts if x["ved"]], key=lambda x: x["x"]):
            # on prend le niveau le plus bas qui laisse assez d'espace ; si
            # aucun ne convient, celui dont le voisin est le plus éloigné.
            choix = None
            for k in range(NIVEAUX):
                if dernier[k] is None or (p["x"] - dernier[k]) >= ECART_VED:
                    choix = k
                    break
            if choix is None:
                choix = max(range(NIVEAUX), key=lambda k: p["x"] - dernier[k])
            p["niv"] = choix
            dernier[choix] = p["x"]
        bandes.append({"lab": lab, "n": len(vals), "min": fmt(lo), "max": fmt(hi),
                       "p50": fmt(p50), "p50x": round(pc(p50), 3),
                       "p90": fmt(p90), "p90x": round(pc(p90), 3), "pts": pts})

    note_manquants = ""
    if manquants:
        note_manquants = ('<p class="avert">Non retrouvé(s) dans le groupe : <b>' +
                          ", ".join(esc(n) + " (" + esc(c) + ")" for n, c in manquants) +
                          "</b>. Soit le joueur n'a pas atteint " + str(MIN_MINUTES) +
                          " minutes, soit StatsBomb le classe à un autre poste, "
                          "soit il n'évolue pas dans ce championnat.</p>")

    html = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alexandre Mendy — Saudi Pro League</title>
<style>
  :root{--ink:#1f2937;--ink2:#111827;--muted:#6b7280;--faint:#9ca3af;--line:#e5e7eb}
  *{box-sizing:border-box}
  body{margin:0;background:#fff;color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:1040px;margin:26px auto 70px;padding:0 20px}
  h1{margin:0 0 4px;font-size:21px;font-weight:800;letter-spacing:-.01em;color:var(--ink2)}
  .sub{font-size:12.5px;color:var(--muted);margin-bottom:4px}
  .avert{font-size:12px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;
    border-radius:8px;padding:9px 12px;margin:14px 0 0;line-height:1.5}
  .bande{margin:30px 0 0;padding-bottom:4px}
  .tt{font-size:15px;font-weight:800;color:var(--ink2);margin-bottom:2px}
  .tt span{font-weight:600;color:var(--faint);font-size:12px;margin-left:8px}
  .plot{position:relative;height:118px;margin-top:96px}
  .axe{position:absolute;left:0;right:0;top:72px;height:2px;background:var(--line)}
  .rep{position:absolute;top:10px;bottom:34px;width:1px;border-left:1px dashed #c3cad6}
  .rep b{position:absolute;top:-16px;left:50%;transform:translateX(-50%);
    font-size:11px;font-weight:700;color:var(--faint);white-space:nowrap}
  .pt{position:absolute;top:66px;width:14px;height:14px;margin-left:-7px;border-radius:50%;
    background:#c9ced8;border:2px solid #fff;cursor:default;transition:transform .1s}
  .pt:hover{background:#8a93a6;transform:scale(1.35);z-index:40}
  .ved{position:absolute;top:30px;margin-left:-23px;width:46px;text-align:center;z-index:30}
  .ved .logo{width:40px;height:40px;object-fit:contain;display:block;margin:0 auto;
    filter:drop-shadow(0 1px 3px rgba(0,0,0,.25))}
  .ved .pill{width:38px;height:38px;border-radius:50%;margin:0 auto;display:flex;
    align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:800}
  .ved .nm{font-size:10.5px;font-weight:800;color:var(--ink2);margin-top:3px;
    white-space:nowrap;transform:translateX(-50%);margin-left:50%;display:inline-block}
  .ved .vv{font-size:11px;font-weight:800;color:#0d3b8c}
  .bornes{position:absolute;top:84px;left:0;right:0;font-size:12px;color:var(--muted)}
  .bornes .l{position:absolute;left:0}.bornes .r{position:absolute;right:0}
  .base{font-size:11.5px;color:var(--faint);margin-top:40px}
  .tip{position:fixed;display:none;z-index:99;background:#0a1733;color:#fff;
    border-radius:7px;padding:7px 10px;font-size:11.5px;line-height:1.45;
    box-shadow:0 6px 18px rgba(0,0,0,.35);pointer-events:none;white-space:nowrap}
  .tip b{font-weight:800}
  footer{margin-top:40px;font-size:11.5px;color:var(--faint);line-height:1.7;
    border-top:1px solid var(--line);padding-top:14px}
</style></head><body>
<div class="wrap">
  <h1>Alexandre Mendy — comparaison aux avants-centres de Saudi Pro League</h1>
  <div class="sub">Saison __SAISON__ · avants-centres axiaux · minimum __MINMIN__ minutes · source StatsBomb</div>
  __AVERT__
  <div id="bandes"></div>
  <footer>
    Chaque point est un avant-centre. Les quatre joueurs mis en avant portent l'écusson de
    leur club ; <b>survole un point gris</b> pour voir le nom, la valeur et le percentile.
    Les repères <b>P50</b> et <b>P90</b> situent la médiane et le neuvième décile du groupe.<br>
    Les valeurs suivies de « /90 » sont des cadences par 90 minutes, pas des totaux.
    <b>Goals and assists above expectation</b> est la métrique que StatsBomb nomme
    « Over/Under Performance » : buts et passes décisives moins xG et xA.<br>
    Le groupe est volontairement étroit — avants-centres axiaux uniquement. Le nombre de
    joueurs est rappelé sous chaque bande : un percentile sur douze joueurs ne vaut pas
    un percentile sur quarante.
  </footer>
</div>
<div class="tip" id="tip"></div>
<script>
const BANDES = __DATA__;
const tip = document.getElementById("tip");
function html(){
  return BANDES.map(b => {
    const pts = b.pts.map(p => {
      const d = 'data-n="'+p.nom.replace(/"/g,'&quot;')+'" data-c="'+(p.club||"").replace(/"/g,'&quot;')+
                '" data-v="'+p.val+'" data-p="'+p.pct+'" data-m="'+p.min+'"';
      if(!p.ved) return '<span class="pt" style="left:'+p.x+'%" '+d+'></span>';
      const img = p.logo
        ? '<img class="logo" src="'+p.logo+'" alt="">'
        : '<span class="pill" style="background:'+(p.couleur||"#555")+'">'+
          p.ved.split(" ").map(s=>s[0]).join("")+'</span>';
      const dy = p.niv ? (' top:'+(30-22*p.niv)+'px;') : '';
      return '<span class="ved" style="left:'+p.x+'%;'+dy+'" '+d+'>'+img+
             '<span class="nm">'+p.ved+'</span>'+
             '<span class="nm vv">'+p.val+'</span></span>';
    }).join("");
    return '<div class="bande"><div class="tt">'+b.lab+'</div>'+
      '<div class="plot">'+
        '<div class="axe"></div>'+
        '<div class="rep" style="left:'+b.p50x+'%"><b>P50 · '+b.p50+'</b></div>'+
        '<div class="rep" style="left:'+b.p90x+'%"><b>P90 · '+b.p90+'</b></div>'+
        pts+
        '<div class="bornes"><span class="l">'+b.min+'</span><span class="r">'+b.max+'</span></div>'+
      '</div><div class="base">'+b.n+' avants-centres retenus</div></div>';
  }).join("");
}
document.getElementById("bandes").innerHTML = html();
document.addEventListener("mouseover", e => {
  const t = e.target.closest("[data-n]");
  if(!t){ tip.style.display="none"; return; }
  tip.innerHTML = "<b>"+t.dataset.n+"</b><br>"+t.dataset.c+" · "+t.dataset.m+" min<br>"+
                  t.dataset.v+" · percentile "+t.dataset.p;
  tip.style.display="block";
  const r = t.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(window.innerWidth-240, r.left-60))+"px";
  tip.style.top  = (r.bottom+8)+"px";
});
</script></body></html>"""

    html = (html.replace("__SAISON__", esc(snom))
                .replace("__MINMIN__", str(MIN_MINUTES))
                .replace("__AVERT__", note_manquants)
                .replace("__DATA__", json.dumps(bandes, ensure_ascii=False)))

    with open(SORTIE, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("\n%s écrit : %d bandes, %d joueurs." % (SORTIE, len(bandes), len(joueurs)))

    svg = dessiner_svg(bandes, snom, manquants)
    with open(SORTIE_SVG, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print("%s écrit." % SORTIE_SVG)
    try:
        import cairosvg
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=SORTIE_PNG,
                         scale=2, background_color="white")
        print("%s écrit (deux fois la résolution)." % SORTIE_PNG)
    except Exception as exc:
        # Le SVG reste utilisable : il s'ouvre dans un navigateur et s'importe
        # dans Keynote ou PowerPoint. On ne fait donc pas échouer le run.
        print("   !! PNG non produit (%s) — le SVG, lui, est bien là." % exc)


if __name__ == "__main__":
    main()
