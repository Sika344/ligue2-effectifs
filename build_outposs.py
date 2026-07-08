#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_outposs.py — 6 KPI "OUT OF POSSESSION" par équipe, sur TOUTE la saison Ligue 2.
Miroir défensif de build_inposs.py. Écrit outposs.json à la racine du repo ;
rapport-pre-match.html le charge au runtime, une GitHub Action le régénère.

Identifiants StatsBomb via SB_USERNAME / SB_PASSWORD (lus par statsbombpy).
Ne jamais committer les identifiants.

Les 6 KPI :
  - Pass per defensive action ..... passes adverses / actions défensives, dans les 60% hauts
                                    du terrain (PPDA). BAS = pressing plus agressif.  [agrégat saison]
  - High press shots ............. tirs consécutifs à une récupération haute : un tir compte si
                                    l'équipe a réalisé une action défensive dans le dernier tiers
                                    (x >= 80) dans les HIGH_PRESS_WINDOW secondes précédentes.  [moyenne/match]
  - Counterpressures ............. événements Pressure avec counterpress = True (pressing dans
                                    les 5 s suivant une perte de balle).  [moyenne/match]
  - Goals conceded ............... buts encaissés (score du match, tirs au but exclus).  [moyenne/match]
  - Non penalty xG conceded ...... somme des shot_statsbomb_xg adverses hors penalty.  [moyenne/match]
  - Box cross conceded ........... centres adverses (pass_cross) finissant dans la surface.
                                    Miroir de "Crosses into box".  [moyenne/match]

Choix d'agrégation (identiques à build_inposs.py) :
  - KPI de comptage -> MOYENNE PAR MATCH (comparable même si les clubs n'ont pas joué le
    même nombre de matchs).
  - KPI de ratio (PPDA) -> AGRÉGAT SAISON (total / total), plus stable qu'une moyenne de ratios.

Géométrie StatsBomb : terrain 120 x 80 (yards). Les coordonnées d'un événement sont TOUJOURS
dans le repère de l'équipe qui le réalise, laquelle attaque vers x = 120. Donc :
  - nos actions défensives dans nos 60% offensifs  -> x >= 48
  - les passes adverses dans leurs 60% défensifs   -> x <= 72   (miroir : 120 - 48)
Surface adverse : x in [102, 120], y in [18, 62].

SAISON (paramétrable) : identique à build_inposs.py
  - défaut = saison courante (CURRENT_SEASON) -> écrit `outposs.json`
  - autre saison -> `outposs_<saison>.json`, saison en argv[1] ou $SEASON ("2024-2025")

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_outposs.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_outposs.py 2024-2025
"""

import os
import sys
import json
import math
import bisect
import datetime

import pandas as pd
from statsbombpy import sb

COMPETITION_ID = 8              # Ligue 2
CURRENT_SEASON = "2025-2026"    # saison courante -> sortie NON suffixée (outposs.json)
SEASON_IDS = {                  # ids connus (évite un appel réseau ; complété à la demande)
    "2025-2026": 318,
}

KPIS = [
    "Pass per defensive action",
    "High press shots",
    "Counterpressures",
    "Goals conceded",
    "Non penalty xG conceded",
    "Box cross conceded",
]

# --- géométrie terrain (yards) ---
BOX_X0, BOX_X1 = 102.0, 120.0
BOX_Y0, BOX_Y1 = 18.0, 62.0

# --- PPDA ---
# Zone : les 60% du terrain les plus hauts pour l'équipe qui presse (40% de 120 = 48).
PPDA_X_MIN = 48.0               # nos actions défensives : x >= 48 (notre repère)
PPDA_OPP_X_MAX = 120.0 - PPDA_X_MIN   # passes adverses : x <= 72 (leur repère)
# "Challenge" du PPDA classique = Duel(Tackle) + Dribbled Past.
DEF_ACTION_TYPES = ("Interception", "Foul Committed", "Dribbled Past")
DEF_DUEL_TYPES = ("Tackle",)    # type == "Duel" ET duel_type == "Tackle"

# --- High press shots ---
HIGH_PRESS_X_MIN = 80.0         # dernier tiers
HIGH_PRESS_WINDOW = 8.0         # secondes entre l'action défensive et le tir
HIGH_PRESS_TRIGGERS = ("Pressure", "Interception", "Duel", "Ball Recovery", "Foul Won")

SHOOTOUT_PERIOD = 5             # tirs au but : exclus de tous les comptages


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


def safe_float(x):
    try:
        f = float(x)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def is_true(x):
    """pass_cross / counterpress valent True (numpy bool) ou NaN -> vrai booléen."""
    return (not pd.isna(x)) and bool(x)


def ev_time(e):
    """Secondes écoulées depuis le coup d'envoi (`minute` est cumulatif chez StatsBomb)."""
    return safe_float(e.get("minute")) * 60.0 + safe_float(e.get("second"))


def is_def_action(e):
    t = e.get("type")
    if t in DEF_ACTION_TYPES:
        return True
    return t == "Duel" and e.get("duel_type") in DEF_DUEL_TYPES


def new_acc():
    return {
        "matches": 0,
        "def_actions": 0,       # PPDA : dénominateur
        "opp_passes": 0,        # PPDA : numérateur
        "hp_shots": 0,          # tirs après récupération haute
        "counterpress": 0,      # pressings dans les 5 s d'une perte
        "goals_conceded": 0,    # score adverse (tirs au but exclus)
        "np_xg_conceded": 0.0,  # xG adverse hors penalty
        "box_cross_conceded": 0,
    }


def accumulate(ev, team, a, conceded):
    """ev = TOUS les événements d'UN match. a muté en place."""
    a["matches"] += 1
    a["goals_conceded"] += conceded

    ev = ev[ev["period"] != SHOOTOUT_PERIOD]
    sub = ev[ev["team"] == team]      # nos événements
    opp = ev[ev["team"] != team]      # ceux de l'adversaire

    # --- nos actions : PPDA (dénominateur), counterpressures, déclencheurs de pressing haut ---
    triggers = []
    for _, e in sub.iterrows():
        t = e.get("type")
        p = loc(e.get("location"))

        if is_def_action(e) and p is not None and p[0] >= PPDA_X_MIN:
            a["def_actions"] += 1

        if t == "Pressure" and is_true(e.get("counterpress")):
            a["counterpress"] += 1

        if t in HIGH_PRESS_TRIGGERS and p is not None and p[0] >= HIGH_PRESS_X_MIN:
            triggers.append(ev_time(e))

    # --- nos tirs : High press shots ---
    triggers.sort()
    for _, e in sub[sub["type"] == "Shot"].iterrows():
        if e.get("shot_type") == "Penalty":
            continue
        ts = ev_time(e)
        i = bisect.bisect_left(triggers, ts - HIGH_PRESS_WINDOW)
        # un déclencheur existe-t-il dans [ts - fenêtre, ts] ?
        if i < len(triggers) and triggers[i] <= ts:
            a["hp_shots"] += 1

    # --- événements adverses : PPDA (numérateur), xG concédés, centres concédés ---
    for _, e in opp.iterrows():
        t = e.get("type")

        if t == "Pass":
            p = loc(e.get("location"))
            if p is not None and p[0] <= PPDA_OPP_X_MAX:
                a["opp_passes"] += 1
            if is_true(e.get("pass_cross")) and in_box(loc(e.get("pass_end_location"))):
                a["box_cross_conceded"] += 1

        elif t == "Shot" and e.get("shot_type") != "Penalty":
            a["np_xg_conceded"] += safe_float(e.get("shot_statsbomb_xg"))


NEEDED_COLS = [
    "type", "team", "period", "minute", "second", "location",
    "pass_end_location", "pass_cross", "duel_type", "counterpress",
    "shot_statsbomb_xg", "shot_type",
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
    out = "outposs.json" if label == CURRENT_SEASON else f"outposs_{label}.json"
    return label, sid, out


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants dans l'environnement.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}")

    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

    # match_ids par équipe + score encaissé par équipe sur chaque match
    per_team, conceded_by = {}, {}
    for _, m in matches.iterrows():
        mid = m["match_id"]
        h, aw = m["home_team"], m["away_team"]
        per_team.setdefault(h, set()).add(mid)
        per_team.setdefault(aw, set()).add(mid)
        conceded_by[(h, mid)] = int(safe_float(m.get("away_score")))
        conceded_by[(aw, mid)] = int(safe_float(m.get("home_score")))

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
            if not (ev["team"] == team).any():
                continue
            accumulate(ev, team, a, conceded_by.get((team, mid), 0))

        m = a["matches"]
        if m == 0:
            continue

        teams_out[team] = {
            "Pass per defensive action": round(a["opp_passes"] / a["def_actions"], 2) if a["def_actions"] else 0.0,
            "High press shots": round(a["hp_shots"] / m, 2),
            "Counterpressures": round(a["counterpress"] / m, 1),
            "Goals conceded": round(a["goals_conceded"] / m, 2),
            "Non penalty xG conceded": round(a["np_xg_conceded"] / m, 3),
            "Box cross conceded": round(a["box_cross_conceded"] / m, 2),
            "matches": m,
        }
        t = teams_out[team]
        print(f"  ✓ {team}: {m} matchs | PPDA {t['Pass per defensive action']} "
              f"| HPShots {t['High press shots']} | CtrPress {t['Counterpressures']} "
              f"| GC {t['Goals conceded']} | NPxGC {t['Non penalty xG conceded']} "
              f"| BoxCrossC {t['Box cross conceded']}")

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
