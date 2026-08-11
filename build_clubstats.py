#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_clubstats.py — pour chaque équipe : points par match (total, domicile,
extérieur) sur la saison en cours ET la saison précédente, plus les 5 derniers
résultats officiels. Écrit clubstats.json à la racine du repo ; une GitHub
Action le régénère.

PÉRIMÈTRE : uniquement les matchs de Ligue 2 (competition_id=8), la seule
compétition couverte par le pipeline. « Derniers résultats officiels » se
limite donc au championnat — pas de Coupe de France ni de barrages, qui ne
sont pas dans les données StatsBomb du projet.

Une équipe qui n'a pas évolué en Ligue 2 la saison précédente (parce qu'elle
était en Ligue 1) a ses champs `prev` à null plutôt qu'une valeur trompeuse ;
la page l'affiche alors comme « — (hors Ligue 2 la saison passée) ».

SORTIE clubstats.json :
{
  "current_season": "2025-2026", "previous_season": "2024-2025", "updated": "...Z",
  "teams": {
    "<équipe>": {
      "ppg":  {"all":.., "home":.., "away":.., "played":..},   # saison en cours
      "prev": {"all":.., "home":.., "away":.., "played":..} | null,
      "last5": [ {"date":"..","opp":"..","venue":"home|away","gf":..,"ga":..,"result":"V|N|D"}, ... ]
                # les 5 derniers matchs JOUÉS, du plus récent au plus ancien
    }
  }
}

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_clubstats.py
"""

import os
import sys
import json
import datetime
from collections import defaultdict
from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318,
    "2026-2027": 351,   # 1re journee jouee le 08/08/2026
}
# la saison précédente est résolue via l'API (lookup_season_id) si absente d'ici


def lookup_season_id(label):
    want = label.replace("-", "/")
    comps = sb.competitions()
    comps = comps[comps["competition_id"] == COMPETITION_ID]
    hit = comps[comps["season_name"] == want]
    if len(hit) == 0:
        return None
    return int(hit.iloc[0]["season_id"])


def previous_label(label):
    a, b = label.split("-")
    return f"{int(a)-1}-{int(b)-1}"


def matches_for(season_id):
    """Renvoie les matchs terminés (score connu), triés par date."""
    m = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)
    m = m[m["home_score"].notna() & m["away_score"].notna()]
    return m.sort_values("match_date")


def compute_ppg(matches, team):
    played = pts = 0
    home_p = home_pts = away_p = away_pts = 0
    for _, m in matches.iterrows():
        if m["home_team"] == team:
            gf, ga = int(m["home_score"]), int(m["away_score"])
            venue = "home"
        elif m["away_team"] == team:
            gf, ga = int(m["away_score"]), int(m["home_score"])
            venue = "away"
        else:
            continue
        p = 3 if gf > ga else (1 if gf == ga else 0)
        played += 1
        pts += p
        if venue == "home":
            home_p += 1; home_pts += p
        else:
            away_p += 1; away_pts += p
    if played == 0:
        return None
    return {
        "all": round(pts / played, 2),
        "home": round(home_pts / home_p, 2) if home_p else None,
        "away": round(away_pts / away_p, 2) if away_p else None,
        "played": played,
    }


def compute_last5(matches, team):
    rows = []
    for _, m in matches.iterrows():
        if m["home_team"] == team:
            gf, ga, venue, opp = int(m["home_score"]), int(m["away_score"]), "home", m["away_team"]
        elif m["away_team"] == team:
            gf, ga, venue, opp = int(m["away_score"]), int(m["home_score"]), "away", m["home_team"]
        else:
            continue
        res = "V" if gf > ga else ("N" if gf == ga else "D")
        date = str(m.get("match_date", "") or "")[:10]
        rows.append({"date": date, "opp": opp, "venue": venue, "gf": gf, "ga": ga, "result": res})
    return list(reversed(rows[-5:]))


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    cur_label = CURRENT_SEASON
    cur_id = SEASON_IDS.get(cur_label) or lookup_season_id(cur_label)
    prev_label = previous_label(cur_label)
    prev_id = lookup_season_id(prev_label)

    print(f"Saison en cours : {cur_label} (id {cur_id})")
    print(f"Saison précédente : {prev_label} (id {prev_id if prev_id else 'introuvable — champs prev à null'})")

    cur_matches = matches_for(cur_id)
    prev_matches = matches_for(prev_id) if prev_id else None

    teams = sorted(set(cur_matches["home_team"]) | set(cur_matches["away_team"]))

    out = {}
    for team in teams:
        ppg = compute_ppg(cur_matches, team)
        prev_ppg = compute_ppg(prev_matches, team) if prev_matches is not None else None
        last5 = compute_last5(cur_matches, team)
        out[team] = {"ppg": ppg, "prev": prev_ppg, "last5": last5}
        tag = "" if prev_ppg else " · pas en L2 la saison passée"
        print(f"  ✓ {team:<18} {ppg['all'] if ppg else '—'} pts/match "
              f"(dom {ppg['home'] if ppg else '—'} / ext {ppg['away'] if ppg else '—'}){tag}")

    result = {
        "current_season": cur_label,
        "previous_season": prev_label,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "teams": out,
    }
    with open("clubstats.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nclubstats.json écrit : {len(out)} équipes.")


if __name__ == "__main__":
    main()
