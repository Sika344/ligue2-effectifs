#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_goalview.py — tirs CADRÉS CONCÉDÉS par chaque équipe, projetés dans le
plan du but (vue gardien), pour la page « Defending » (sous-vue Goal view).
Écrit goalview.json à la racine du repo ; une GitHub Action le régénère.

VUE GARDIEN, CÔTÉ DÉFENSIF : on retient les tirs cadrés subis par l'équipe,
c.-à-d. les tirs de l'ADVERSAIRE dont l'issue est cadrée. Chaque tir est placé
là où il franchit la ligne de but, via `shot_end_location = [x, y, z]` :
  gy = coordonnée latérale (y) du ballon dans le but
  gz = hauteur (z) du ballon
Le but mesure 7,32 m de large (poteaux à y=36 et y=44) et 2,44 m de haut.

CADRÉ = shot_outcome "Goal", "Saved" ou "Saved to Post". Un but reste marqué
comme but (couleur verte côté page), les autres cadrés en marine — mêmes codes
que la page Finishing (vert = but, marine = cadré).

TROIS ZONES latérales du but, bandes verticales égales sur la largeur (y) :
  gauche  y in [36, 38.67)      (du point de vue de l'attaquant qui tire)
  axe     y in [38.67, 41.33)
  droite  y in [41.33, 44]
La page calcule par zone le % de buts sur tirs cadrés et le xG cumulé concédé.

ACTION TYPE, aligné sur le reste du site :
  open_play   play_pattern "Regular Play" ou "From Counter"
  penalty     shot_type "Penalty"
  set_piece   tout le reste (coups francs, corners, touches, etc.)

Période 5 (séance de tirs au but) exclue. Un tir cadré sans `shot_end_location`
exploitable est ignoré (impossible à placer dans le cadre).

SORTIE goalview.json :
{
  "competition":"Ligue 2","season":"2025-2026","season_id":318,"updated":"...Z",
  "goal": {"y0":36,"y1":44,"z":2.44,"zones":[36,38.667,41.333,44]},
  "teams": ["Amiens", ...],
  "acts":  ["open_play","penalty","set_piece"],
  "shots": [[t, gy, gz, is_goal, a, xg], ...]
}
t = indice équipe concédante ; gy,gz = position dans le but ; is_goal = 0/1 ;
a = indice action type ; xg = shot_statsbomb_xg (0 si absent).

SAISON : défaut CURRENT_SEASON -> goalview.json, sinon goalview_<saison>.json.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_goalview.py
"""

import os
import sys
import json
import datetime
from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318,
    "2026-2027": 351,   # 1re journee jouee le 08/08/2026
}

SHOOTOUT_PERIOD = 5
GOAL_Y0, GOAL_Y1 = 36.0, 44.0     # poteaux
GOAL_Z = 2.44                     # hauteur de la barre
ON_TARGET = {"Saved", "Saved to Post"}

ACTS = ["open_play", "penalty", "set_piece"]


def act_of(pattern, stype):
    if stype == "Penalty":
        return "penalty"
    if str(pattern) in ("Regular Play", "From Counter"):
        return "open_play"
    return "set_piece"


def lookup_season_id(label):
    want = label.replace("-", "/")
    comps = sb.competitions()
    comps = comps[comps["competition_id"] == COMPETITION_ID]
    hit = comps[comps["season_name"] == want]
    if len(hit) == 0:
        avail = ", ".join(f"{r.season_name}={r.season_id}" for r in comps.itertuples())
        print(f"ERREUR : saison '{label}' introuvable.\nDisponibles : {avail or '(aucune)'}",
              file=sys.stderr)
        sys.exit(1)
    sid = int(hit.iloc[0]["season_id"])
    print(f"season_id résolu via l'API : {label} -> {sid}")
    return sid


def resolve_season():
    label = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "")).strip()
    if not label:
        label = CURRENT_SEASON
    sid = SEASON_IDS.get(label) or lookup_season_id(label)
    out = "goalview.json" if label == CURRENT_SEASON else f"goalview_{label}.json"
    return label, sid, out


def fnum(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def end_yz(v):
    """shot_end_location = [x, y, z] ; renvoie (y, z) si exploitable."""
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return None
    y, z = fnum(v[1]), fnum(v[2])
    if y is None or z is None:
        return None
    return y, z


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}")
    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

    teams, ti = [], {}

    def idx_team(name):
        if name not in ti:
            ti[name] = len(teams)
            teams.append(name)
        return ti[name]

    shots = []
    n_match = 0
    skipped_noend = 0

    for _, m in matches.iterrows():
        mid = m["match_id"]
        home, away = m["home_team"], m["away_team"]
        try:
            ev = sb.events(match_id=mid)
        except Exception as e:
            print(f"  · match {mid} ignoré ({e})")
            continue
        if ev is None or len(ev) == 0 or "type" not in ev.columns:
            continue
        n_match += 1

        col = lambda c: ev[c] if c in ev.columns else None
        c_team, c_type = ev["team"], ev["type"]
        c_per = col("period")
        c_out, c_stype = col("shot_outcome"), col("shot_type")
        c_pat, c_xg = col("play_pattern"), col("shot_statsbomb_xg")
        c_end = col("shot_end_location")
        get = lambda s, i: (s.get(i) if s is not None else None)

        for i in ev.index:
            if c_type.get(i) != "Shot":
                continue
            if c_per is not None and c_per.get(i) == SHOOTOUT_PERIOD:
                continue
            outcome = get(c_out, i)
            is_goal = (outcome == "Goal")
            if not (is_goal or str(outcome) in ON_TARGET):
                continue  # on ne garde que les tirs cadrés

            yz = end_yz(get(c_end, i))
            if yz is None:
                skipped_noend += 1
                continue
            gy, gz = yz

            shooter_team = c_team.get(i)
            conceding = away if shooter_team == home else home  # l'équipe qui subit

            act = act_of(get(c_pat, i), get(c_stype, i))
            xg = fnum(get(c_xg, i)) or 0.0

            shots.append([idx_team(conceding), round(gy, 3), round(gz, 3),
                          1 if is_goal else 0, ACTS.index(act), round(xg, 4)])

    by_team = {}
    for s in shots:
        by_team[teams[s[0]]] = by_team.get(teams[s[0]], 0) + 1
    for t in sorted(by_team, key=lambda k: -by_team[k]):
        print(f"  ✓ {t:<18} {by_team[t]} tirs cadrés concédés")

    ng = sum(1 for s in shots if s[3] == 1)
    print(f"\n{len(shots)} tirs cadrés concédés | {ng} buts | "
          f"{skipped_noend} ignorés (pas de shot_end_location)")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "goal": {"y0": GOAL_Y0, "y1": GOAL_Y1, "z": GOAL_Z,
                 "zones": [GOAL_Y0, GOAL_Y0 + (GOAL_Y1 - GOAL_Y0) / 3,
                           GOAL_Y0 + 2 * (GOAL_Y1 - GOAL_Y0) / 3, GOAL_Y1]},
        "teams": teams,
        "acts": ACTS,
        "shots": shots,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{out_path} écrit : {len(teams)} équipes, {len(shots)} tirs.")


if __name__ == "__main__":
    main()
