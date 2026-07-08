#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_inposs.py — 8 KPI "IN-POSSESSION" par équipe, sur TOUTE la saison Ligue 2.
Écrit inposs.json à la racine du repo. La page rapport-pre-match.html le charge au
runtime (comme ligue2.json / xg.json) ; une GitHub Action le régénère => auto-actualisé.

Identifiants StatsBomb via variables d'environnement SB_USERNAME / SB_PASSWORD
(statsbombpy les lit automatiquement). Ne jamais committer les identifiants.

Les 8 KPI (définitions validées par Geoffrey) :
  - NP xG ............................ somme des shot_statsbomb_xg hors penalty   [moyenne/match]
  - Directness ...................... VITESSE de progression vers le but (m/s)    [agrégat saison]
  - Box Penetration ................. entrées dans la surface (passes complétées + conduites)  [moyenne/match]
  - Counter attacking shots ......... tirs play_pattern == "From Counter"          [moyenne/match]
  - Cross to pass ratio – Box entry . part des entrées surface réalisées par centre (%)  [agrégat saison]
  - Crosses into box ................ centres (pass_cross) finissant dans la surface  [moyenne/match]
  - Set pieces xG ................... somme des shot_statsbomb_xg hors penalty sur coups de pied
                                      arrêtés (play_pattern in From Corner / From Free Kick /
                                      From Throw In)  [moyenne/match]
  - Counter attacking shots conceded  tirs From Counter CONCÉDÉS (tirs de l'adversaire)  [moyenne/match]

Choix d'agrégation :
  - KPI de comptage (NP xG, Box Penetration, Counter shots, Crosses into box) -> MOYENNE PAR MATCH
    (comparable entre les 18 clubs même s'ils n'ont pas joué exactement le même nombre de matchs).
  - KPI de ratio / vitesse (Directness, Cross ratio) -> AGRÉGAT SAISON (total / total), plus stable
    que la moyenne de ratios par match.

Géométrie StatsBomb : terrain 120 x 80 (yards), l'équipe en possession attaque toujours vers x = 120.
Surface adverse : x in [102, 120], y in [18, 62]. Distances converties en mètres (×0.9144) pour
que Directness se lise comme une vraie vitesse en m/s.

SAISON (paramétrable) :
  - défaut = saison courante (CURRENT_SEASON) -> écrit `inposs.json`
  - autre saison -> écrit `inposs_<saison>.json` (ex. inposs_2024-2025.json)
  - la saison se passe en argv[1] OU via la variable d'environnement SEASON, au format
    "2024-2025". Le season_id StatsBomb est résolu automatiquement via sb.competitions()
    s'il n'est pas déjà connu dans SEASON_IDS.

USAGE LOCAL (génère inposs.json tout de suite, sans attendre l'Action) :
    SB_USERNAME='…' SB_PASSWORD='…' python build_inposs.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_inposs.py 2024-2025
Puis déposer le JSON à la racine du repo (github.com/Sika344/ligue2-effectifs/upload/main).
"""

import os
import sys
import json
import math
import datetime

import pandas as pd
from statsbombpy import sb

COMPETITION_ID = 8              # Ligue 2
CURRENT_SEASON = "2025-2026"    # saison courante -> sortie NON suffixée (inposs.json)
SEASON_IDS = {                  # ids connus (évite un appel réseau ; complété à la demande)
    "2025-2026": 318,
}

KPIS = [
    "NP xG",
    "Directness",
    "Box Penetration",
    "Counter attacking shots",
    "Cross to pass ratio – Box entry",
    "Crosses into box",
    "Set pieces xG",
    "Counter attacking shots conceded",
]

# play_patterns considérés comme coup de pied arrêté (Set pieces xG)
SET_PIECE_PATTERNS = ("From Corner", "From Free Kick", "From Throw In")

# --- géométrie terrain (yards) ---
GOAL = (120.0, 40.0)
BOX_X0, BOX_X1 = 102.0, 120.0
BOX_Y0, BOX_Y1 = 18.0, 62.0
YARD_TO_M = 0.9144


def loc(v):
    """(x, y) depuis une location StatsBomb (liste [x, y]) ou None."""
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return None
    return None


def in_box(p):
    return p is not None and BOX_X0 <= p[0] <= BOX_X1 and BOX_Y0 <= p[1] <= BOX_Y1


def dist_goal(p):
    return math.hypot(GOAL[0] - p[0], GOAL[1] - p[1])


def safe_float(x):
    try:
        f = float(x)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def is_true(x):
    """pass_cross vaut True (numpy bool) ou NaN -> renvoie un vrai booléen."""
    return (not pd.isna(x)) and bool(x)


def new_acc():
    return {
        "matches": 0,
        "np_xg": 0.0,          # somme xG hors penalty
        "box_entries": 0,      # entrées surface (passes complétées + conduites)
        "cross_entries": 0,    # entrées surface réalisées par un centre
        "counter": 0,          # tirs From Counter
        "counter_conceded": 0, # tirs From Counter concédés (adversaire)
        "setpiece_xg": 0.0,    # somme xG hors penalty sur coups de pied arrêtés
        "crosses_box": 0,      # centres finissant dans la surface
        "prog_m": 0.0,         # progression nette vers le but (m), passes complétées + conduites
        "dur_s": 0.0,          # durée totale (s) de ces actions
    }


def accumulate(df, a):
    """df = events d'UNE équipe sur UN match. a = accumulateur de l'équipe (mué en place)."""
    a["matches"] += 1
    for _, e in df.iterrows():
        t = e.get("type")

        if t == "Shot":
            if e.get("shot_type") != "Penalty":
                xg = safe_float(e.get("shot_statsbomb_xg"))
                a["np_xg"] += xg
                if e.get("play_pattern") in SET_PIECE_PATTERNS:
                    a["setpiece_xg"] += xg
            if e.get("play_pattern") == "From Counter":
                a["counter"] += 1
            continue

        start = loc(e.get("location"))

        if t == "Pass":
            end = loc(e.get("pass_end_location"))
            completed = pd.isna(e.get("pass_outcome"))   # NaN = passe réussie
            cross = is_true(e.get("pass_cross"))

            # KPI #4 : centre finissant dans la surface (tenté)
            if cross and in_box(end):
                a["crosses_box"] += 1

            # KPI #2 / #6 : entrée surface par passe complétée (départ hors surface)
            if completed and in_box(end) and (start is None or not in_box(start)):
                a["box_entries"] += 1
                if cross:
                    a["cross_entries"] += 1

            # KPI #5 : directness — passes complétées
            if completed and start is not None and end is not None:
                dur = safe_float(e.get("duration"))
                if dur > 0:
                    a["prog_m"] += (dist_goal(start) - dist_goal(end)) * YARD_TO_M
                    a["dur_s"] += dur

        elif t == "Carry":
            end = loc(e.get("carry_end_location"))

            # KPI #2 : entrée surface par conduite (départ hors surface)
            if in_box(end) and (start is None or not in_box(start)):
                a["box_entries"] += 1

            # KPI #5 : directness — conduites
            if start is not None and end is not None:
                dur = safe_float(e.get("duration"))
                if dur > 0:
                    a["prog_m"] += (dist_goal(start) - dist_goal(end)) * YARD_TO_M
                    a["dur_s"] += dur


NEEDED_COLS = [
    "type", "team", "location", "pass_end_location", "carry_end_location",
    "pass_cross", "pass_outcome", "shot_statsbomb_xg", "shot_type",
    "play_pattern", "duration",
]


def lookup_season_id(label):
    """Retrouve le season_id StatsBomb depuis le libellé ("2024-2025" -> "2024/2025")."""
    want = label.replace("-", "/")
    comps = sb.competitions()
    comps = comps[comps["competition_id"] == COMPETITION_ID]
    hit = comps[comps["season_name"] == want]
    if len(hit) == 0:
        avail = ", ".join(f"{r.season_name}={r.season_id}" for r in comps.itertuples())
        print(f"ERREUR : saison '{label}' introuvable pour competition_id={COMPETITION_ID}.\n"
              f"Saisons disponibles : {avail or '(aucune)'}", file=sys.stderr)
        sys.exit(1)
    sid = int(hit.iloc[0]["season_id"])
    print(f"season_id résolu via l'API : {label} -> {sid}")
    return sid


def resolve_season():
    """Saison cible = argv[1], sinon $SEASON, sinon CURRENT_SEASON.
    Renvoie (label, season_id, chemin_de_sortie)."""
    label = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "")).strip()
    if not label:
        label = CURRENT_SEASON
    sid = SEASON_IDS.get(label) or lookup_season_id(label)
    out = "inposs.json" if label == CURRENT_SEASON else f"inposs_{label}.json"
    return label, sid, out


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants dans l'environnement.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}")

    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

    # match_ids par équipe (noms StatsBomb)
    per_team = {}
    for _, m in matches.iterrows():
        mid = m["match_id"]
        for col in ("home_team", "away_team"):
            per_team.setdefault(m[col], set()).add(mid)

    ev_cache = {}

    def events(mid):
        if mid not in ev_cache:
            ev_cache[mid] = sb.events(match_id=mid)
        return ev_cache[mid]

    teams_out = {}
    for team, mids in sorted(per_team.items()):
        a = new_acc()
        for mid in mids:
            try:
                ev = events(mid)
            except Exception as e:
                print(f"  · {team}: match {mid} ignoré ({e})")
                continue
            if ev is None or len(ev) == 0 or "type" not in ev.columns:
                continue  # match non joué / données indisponibles
            for c in NEEDED_COLS:
                if c not in ev.columns:
                    ev[c] = pd.NA
            sub = ev[ev["team"] == team]
            if len(sub):
                accumulate(sub, a)
                # tirs From Counter concédés = tirs From Counter de l'adversaire sur ce match
                opp_counter = ev[(ev["team"] != team)
                                 & (ev["type"] == "Shot")
                                 & (ev["play_pattern"] == "From Counter")]
                a["counter_conceded"] += len(opp_counter)

        m = a["matches"]
        if m == 0:
            continue

        box = a["box_entries"]
        teams_out[team] = {
            "NP xG": round(a["np_xg"] / m, 3),
            "Directness": round(a["prog_m"] / a["dur_s"], 3) if a["dur_s"] > 0 else 0.0,
            "Box Penetration": round(box / m, 2),
            "Counter attacking shots": round(a["counter"] / m, 2),
            "Cross to pass ratio – Box entry": round(100.0 * a["cross_entries"] / box, 1) if box > 0 else 0.0,
            "Crosses into box": round(a["crosses_box"] / m, 2),
            "Set pieces xG": round(a["setpiece_xg"] / m, 3),
            "Counter attacking shots conceded": round(a["counter_conceded"] / m, 2),
            "matches": m,
        }
        t = teams_out[team]
        print(f"  ✓ {team}: {m} matchs | NPxG {t['NP xG']} | Direct {t['Directness']} "
              f"| BoxPen {t['Box Penetration']} | CounterSh {t['Counter attacking shots']} "
              f"| Cross% {t['Cross to pass ratio – Box entry']} | CrossBox {t['Crosses into box']} "
              f"| SetPcXG {t['Set pieces xG']} | CounterShConc {t['Counter attacking shots conceded']}")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "kpis": KPIS,
        "teams": teams_out,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(teams_out)} équipes.")


if __name__ == "__main__":
    main()
