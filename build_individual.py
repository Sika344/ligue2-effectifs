#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_individual.py — données joueur pour l'onglet « Individual » (spider chart).

SORTIE : individual_<saison>.json, contenant les VALEURS BRUTES par joueur.

POURQUOI PAS DE PERCENTILES ICI : le seuil de minutes est réglable dans la page.
Or changer le seuil change le groupe de comparaison, donc TOUS les percentiles.
Les calculer côté Python les figerait sur un seuil unique. Ils sont donc calculés
dans le navigateur, à chaque déplacement du curseur.

SUR LA RÉSOLUTION DES MÉTRIQUES : les noms de colonnes de `player_season_stats`
varient selon le niveau de collecte de l'abonnement. Plutôt que de coder en dur
des noms supposés et de produire des colonnes vides sans le dire, chaque métrique
porte une liste de noms candidats. Le script ne retient qu'une correspondance
EXACTE ; s'il n'en trouve aucune, il ne devine pas : il inscrit la métrique dans
`diagnostic.non_resolues` avec les colonnes les plus ressemblantes, à trancher à
la main. Le JSON embarque aussi la liste complète des colonnes disponibles.

SAISON (même convention que les autres build_*.py) :
  - défaut = CURRENT_SEASON -> individual.json
  - autre saison -> individual_<saison>.json
  - saison passée en argv[1] ou via la variable d'environnement SEASON.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_individual.py 2026-2027
"""

import os
import sys
import json
import math
import difflib
import datetime

from statsbombpy import sb

COMPETITION_ID = 8              # Ligue 2
CURRENT_SEASON = "2025-2026"    # saison courante -> sortie NON suffixée
SEASON_IDS = {
    "2025-2026": 318,
    "2026-2027": 351,
}

# ---------------------------------------------------------------------------
# Les 28 métriques demandées, dans l'ordre de la maquette.
#   cle    : identifiant court utilisé par le JSON et la page
#   label  : libellé affiché sur l'axe du radar
#   cands  : noms de colonnes candidats, essayés dans l'ordre
#   calc   : métrique dérivée — somme de plusieurs colonnes (ex. buts + passes déc.)
#   sens   : +1 si « plus c'est haut, mieux c'est », -1 sinon (pertes, fautes…)
# ---------------------------------------------------------------------------
METRIQUES = [
    dict(cle="obv_off", label="OBV off", sens=+1, calc=[
        "player_season_obv_pass_90",
        "player_season_obv_dribble_carry_90",
        "player_season_obv_shot_90"]),
    dict(cle="xg", label="xG", sens=+1, cands=[
        "player_season_xg_90", "player_season_npxg_90"]),
    dict(cle="box_touches", label="Box touches", sens=+1, cands=[
        "player_season_touches_inside_box_90"]),
    dict(cle="key_passes", label="Key passes", sens=+1, cands=[
        "player_season_key_passes_90"]),
    dict(cle="obv_def", label="OBV def", sens=+1, cands=[
        "player_season_obv_defensive_action_90",
        "player_season_obv_defensive_actions_90"]),
    dict(cle="def_actions", label="Def actions", sens=+1, cands=[
        "player_season_defensive_actions_90",
        "player_season_defensive_action_90",
        "player_season_padj_defensive_actions_90"]),
    dict(cle="pressures", label="Pressures", sens=+1, cands=[
        "player_season_pressures_90", "player_season_padj_pressures_90"]),
    dict(cle="high_recov", label="High recov.", sens=+1, cands=[
        "player_season_high_recoveries_90",
        "player_season_counterpressures_90"]),
    dict(cle="obv_lb", label="OBV line-break", sens=+1, cands=[
        "player_season_obv_line_breaking_pass_90",
        "player_season_line_breaking_pass_obv_90"]),
    dict(cle="lbp_space", label="LBP→space", sens=+1, cands=[
        "player_season_line_breaking_pass_into_space_90",
        "player_season_lbp_into_space_90"]),
    dict(cle="obv_lb_f3", label="OBV LB (f3)", sens=+1, cands=[
        "player_season_obv_line_breaking_pass_final_third_90",
        "player_season_f3_line_breaking_pass_obv_90"]),
    dict(cle="lbp_space_f3", label="LBP→space (f3)", sens=+1, cands=[
        "player_season_line_breaking_pass_into_space_final_third_90",
        "player_season_f3_lbp_into_space_90"]),
    dict(cle="goal_involv", label="Goal involv.", sens=+1, calc=[
        "player_season_goals_90", "player_season_assists_90"]),
    dict(cle="np_xg", label="NP xG", sens=+1, cands=[
        "player_season_np_xg_90", "player_season_npxg_90"]),
    dict(cle="shots", label="Shots", sens=+1, cands=[
        "player_season_shots_90", "player_season_np_shots_90"]),
    dict(cle="xg_per_shot", label="xG/shot", sens=+1, cands=[
        "player_season_np_xg_per_shot", "player_season_xg_per_shot"]),
    dict(cle="corner_xg", label="Corner xG", sens=+1, cands=[
        "player_season_xg_from_corner_90", "player_season_corner_xg_90"]),
    dict(cle="penalties", label="Penalties", sens=+1, cands=[
        "player_season_penalties_won_90", "player_season_penalties_90"]),
    dict(cle="deep_prog", label="Deep prog.", sens=+1, cands=[
        "player_season_deep_progressions_90"]),
    dict(cle="deep_compl", label="Deep compl.", sens=+1, cands=[
        "player_season_deep_completions_90"]),
    dict(cle="passes_box", label="Passes in box", sens=+1, cands=[
        "player_season_passes_inside_box_90",
        "player_season_op_passes_into_box_90"]),
    dict(cle="dribbles", label="Succ. dribbles", sens=+1, cands=[
        "player_season_successful_dribbles_90", "player_season_dribbles_90"]),
    dict(cle="crosses", label="Crosses", sens=+1, cands=[
        "player_season_crosses_90", "player_season_op_crosses_90"]),
    dict(cle="box_crosses", label="Box crosses", sens=+1, cands=[
        "player_season_crosses_into_box_90",
        "player_season_op_crosses_into_box_90"]),
    dict(cle="op_passes", label="OP passes", sens=+1, cands=[
        "player_season_op_passes_90"]),
    dict(cle="passing_pct", label="Passing %", sens=+1, cands=[
        "player_season_passing_ratio", "player_season_pass_completion_ratio"]),
    dict(cle="fouls", label="Fouls", sens=-1, cands=[
        "player_season_fouls_90", "player_season_fouls_committed_90"]),
    dict(cle="cards", label="Cards", sens=-1, calc=[
        "player_season_yellow_cards_90", "player_season_red_cards_90"]),
]

# Colonnes d'identité — mêmes candidats, même méthode.
IDENT = {
    "id":      ["player_id"],
    "nom":     ["player_name"],
    "equipe":  ["team_name", "team"],
    "poste":   ["primary_position", "player_season_most_recent_match_position"],
    "minutes": ["player_season_minutes"],
    "m90":     ["player_season_90s_played"],
    "matchs":  ["player_season_appearances"],
    "titu":    ["player_season_starting_appearances"],
}


def resolve_season():
    """Saison cible = argv[1], sinon $SEASON, sinon CURRENT_SEASON."""
    label = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "")).strip()
    if not label:
        label = CURRENT_SEASON
    sid = SEASON_IDS.get(label)
    if sid is None:
        print(f"ERREUR : saison « {label} » inconnue. Connues : "
              f"{', '.join(sorted(SEASON_IDS))}", file=sys.stderr)
        sys.exit(1)
    out = "individual.json" if label == CURRENT_SEASON else f"individual_{label}.json"
    return label, sid, out


def premier_present(cands, colonnes):
    """Première colonne candidate réellement présente. Aucune supposition."""
    for c in cands:
        if c in colonnes:
            return c
    return None


def nombre(v):
    """float exploitable, ou None. NaN et vides deviennent None, pas 0 :
    un 0 signifierait « le joueur n'en a fait aucun », or on ne le sait pas."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    label, sid, out_path = resolve_season()
    print(f"Saison {label} (season_id={sid}) -> {out_path}")

    print("Appel player_season_stats…")
    df = sb.player_season_stats(competition_id=COMPETITION_ID, season_id=sid)
    if df is None or len(df) == 0:
        print("ERREUR : aucune ligne renvoyée.", file=sys.stderr)
        sys.exit(1)

    colonnes = list(df.columns)
    print(f"{len(df)} joueurs, {len(colonnes)} colonnes disponibles.")

    # ---- résolution des colonnes d'identité --------------------------------
    ident_res, ident_manq = {}, []
    for cle, cands in IDENT.items():
        c = premier_present(cands, colonnes)
        if c:
            ident_res[cle] = c
        else:
            ident_manq.append(cle)
    if "id" not in ident_res or "nom" not in ident_res:
        print("ERREUR : impossible d'identifier les joueurs (player_id/player_name "
              "absents). Colonnes reçues : " + ", ".join(colonnes[:40]), file=sys.stderr)
        sys.exit(1)

    # ---- résolution des métriques ------------------------------------------
    resolues, non_resolues = [], []
    for m in METRIQUES:
        if m.get("calc"):
            trouvees = [c for c in m["calc"] if c in colonnes]
            if len(trouvees) == len(m["calc"]):
                resolues.append(dict(m, source=trouvees, mode="somme"))
            else:
                manquantes = [c for c in m["calc"] if c not in colonnes]
                non_resolues.append(dict(cle=m["cle"], label=m["label"],
                                         attendu=manquantes,
                                         proches=suggestions(manquantes, colonnes)))
            continue
        c = premier_present(m["cands"], colonnes)
        if c:
            resolues.append(dict(m, source=[c], mode="direct"))
        else:
            non_resolues.append(dict(cle=m["cle"], label=m["label"],
                                     attendu=m["cands"],
                                     proches=suggestions(m["cands"], colonnes)))

    print(f"\nMétriques résolues : {len(resolues)}/{len(METRIQUES)}")
    for m in resolues:
        print(f"  ✓ {m['label']:<16} <- {' + '.join(m['source'])}")
    if non_resolues:
        print(f"\nMétriques NON résolues : {len(non_resolues)}")
        for m in non_resolues:
            pr = ", ".join(m["proches"][:3]) or "aucune colonne ressemblante"
            print(f"  ✗ {m['label']:<16} attendu {m['attendu'][0]}")
            print(f"      colonnes proches : {pr}")

    # ---- extraction --------------------------------------------------------
    joueurs = []
    for _, r in df.iterrows():
        p = {
            "id": r.get(ident_res["id"]),
            "nom": r.get(ident_res["nom"]),
        }
        for cle in ("equipe", "poste"):
            if cle in ident_res:
                v = r.get(ident_res[cle])
                p[cle] = None if v != v else v          # NaN -> None
        for cle in ("minutes", "m90", "matchs", "titu"):
            if cle in ident_res:
                p[cle] = nombre(r.get(ident_res[cle]))

        vals = {}
        for m in resolues:
            if m["mode"] == "somme":
                parts = [nombre(r.get(c)) for c in m["source"]]
                v = None if all(x is None for x in parts) else sum(x or 0 for x in parts)
            else:
                v = nombre(r.get(m["source"][0]))
            if v is not None:
                vals[m["cle"]] = round(v, 4)
        p["vals"] = vals
        joueurs.append(p)

    joueurs.sort(key=lambda p: (-(p.get("minutes") or 0), str(p.get("nom"))))

    postes = {}
    for p in joueurs:
        postes[p.get("poste") or "?"] = postes.get(p.get("poste") or "?", 0) + 1

    sortie = {
        "season": label,
        "source": "StatsBomb player_season_stats",
        "updated": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%d %H:%M UTC"),
        "metrics": [{"cle": m["cle"], "label": m["label"], "sens": m["sens"],
                     "source": m["source"]} for m in resolues],
        "postes": dict(sorted(postes.items(), key=lambda kv: -kv[1])),
        "players": joueurs,
        # Le diagnostic voyage AVEC les données : sans lui, une métrique absente
        # se lirait comme une métrique à zéro.
        "diagnostic": {
            "colonnes_disponibles": colonnes,
            "identite_manquante": ident_manq,
            "non_resolues": non_resolues,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(joueurs)} joueurs, "
          f"{len(resolues)} métriques, {len(postes)} postes.")


def suggestions(attendus, colonnes):
    """Colonnes réelles les plus proches — pour trancher à la main, jamais
    appliquées automatiquement : un mauvais rapprochement produirait un radar
    faux et silencieux."""
    out = []
    for a in attendus:
        out += difflib.get_close_matches(a, colonnes, n=3, cutoff=0.6)
    vus, uniq = set(), []
    for c in out:
        if c not in vus:
            vus.add(c)
            uniq.append(c)
    return uniq


if __name__ == "__main__":
    main()
