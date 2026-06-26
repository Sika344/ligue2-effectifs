#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_xg.py — xG créés / concédés par tranche de 15 min, sur TOUTE la saison.
Écrit xg.json à la racine du repo. La page rapport-pre-match.html le charge au
runtime (comme ligue2.json) ; une GitHub Action le régénère => auto-actualisé.

Identifiants StatsBomb via variables d'environnement SB_USERNAME / SB_PASSWORD
(statsbombpy les lit automatiquement). Ne jamais committer les identifiants.

Sortie xg.json :
{
  "competition": "Ligue 2",
  "season": "2025-2026",
  "season_id": 318,
  "updated": "2026-06-26T10:00:00Z",
  "teams": {
    "<nom StatsBomb>": { "for":[b0..b5], "against":[b0..b5], "matches": N },
    ...
  }
}
Tranches : 0-15 / 15-30 / 30-45 / 45-60 / 60-75 / 75-90.
Arrêts de jeu rattachés à la tranche en cours ; period 5 (TAB) et prolongations exclues.

La page réconcilie les noms StatsBomb avec ses noms de clubs via matchTeam()/norm(),
donc garder ici les noms StatsBomb tels quels est suffisant.

USAGE LOCAL (pour générer xg.json tout de suite, sans attendre l'Action) :
    SB_USERNAME='…' SB_PASSWORD='…' python build_xg.py
Puis déposer xg.json à la racine du repo (github.com/Sika344/ligue2-effectifs/upload/main).
"""

import os
import sys
import json
import datetime
from statsbombpy import sb

COMPETITION_ID = 8       # Ligue 2
SEASON_ID = 318          # 2025/2026
SEASON_LABEL = "2025-2026"


def bucket_15(period, minute):
    """minute = champ StatsBomb (0-based, continu : 45+ en 2e période)."""
    try:
        period = int(period)
        minute = int(minute)
    except (TypeError, ValueError):
        return None
    if period == 1:
        return min(2, minute // 15)              # 0-15 / 15-30 / 30-45 (+ arrêts 1re MT)
    if period == 2:
        return 3 + min(2, (minute - 45) // 15)   # 45-60 / 60-75 / 75-90 (+ arrêts 2e MT)
    return None                                   # prolongations / TAB -> exclu


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants dans l'environnement.", file=sys.stderr)
        sys.exit(1)

    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={SEASON_ID})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=SEASON_ID)

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
        F = [0.0] * 6
        A = [0.0] * 6
        n = 0
        for mid in mids:
            try:
                ev = events(mid)
            except Exception as e:
                # match non joué / données indisponibles -> on ignore
                print(f"  · {team}: match {mid} ignoré ({e})")
                continue
            if ev is None or len(ev) == 0 or "type" not in ev.columns:
                continue  # pas d'events exploitables -> probablement non joué
            n += 1
            shots = ev[ev["type"] == "Shot"]
            if "shot_statsbomb_xg" not in shots.columns:
                continue  # pas de colonne xG sur ce match
            for _, s in shots.iterrows():
                b = bucket_15(s.get("period"), s.get("minute"))
                if b is None:
                    continue
                xg = s.get("shot_statsbomb_xg")
                if xg is None:
                    continue
                if s.get("team") == team:
                    F[b] += float(xg)
                else:
                    A[b] += float(xg)
        teams_out[team] = {
            "for": [round(v, 2) for v in F],
            "against": [round(v, 2) for v in A],
            "matches": n,
        }
        print(f"  ✓ {team}: {n} matchs | créés {teams_out[team]['for']} | concédés {teams_out[team]['against']}")

    out = {
        "competition": "Ligue 2",
        "season": SEASON_LABEL,
        "season_id": SEASON_ID,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "teams": teams_out,
    }
    with open("xg.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nxg.json écrit : {len(teams_out)} équipes.")


if __name__ == "__main__":
    main()
