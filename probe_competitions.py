#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_competitions.py — que couvre vraiment notre compte StatsBomb ?

Écrit `probe/competitions.json` et affiche la liste dans le log.
Sert à savoir si le Championnat National (3e division française) est
accessible, avant d'essayer d'en tirer des stats pour Sochaux et Dijon.

USAGE
    SB_USERNAME='…' SB_PASSWORD='…' python probe_competitions.py
ou via l'Action `probe competitions` (workflow_dispatch).
"""

import os
import sys
import json

from statsbombpy import sb


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("!! SB_USERNAME / SB_PASSWORD absents de l'environnement.")
        raise SystemExit(1)

    try:
        comps = sb.competitions()
    except Exception as exc:
        print("!! sb.competitions() a échoué : %s" % exc)
        raise SystemExit(1)

    cols = [c for c in ("competition_id", "season_id", "country_name",
                        "competition_name", "season_name",
                        "match_available", "match_available_360")
            if c in comps.columns]
    comps = comps[cols]

    os.makedirs("probe", exist_ok=True)
    comps.to_json("probe/competitions.json", orient="records",
                  force_ascii=False, indent=1)

    print("=== %d couples compétition/saison accessibles ===\n" % len(comps))

    # 1. tout ce qui est français
    fr = comps[comps.get("country_name", "") == "France"] \
        if "country_name" in comps.columns else comps
    print("--- FRANCE ---")
    if len(fr) == 0:
        print("  (aucune compétition française)")
    for _, r in fr.sort_values(["competition_name", "season_name"]).iterrows():
        print("  comp=%-5s season=%-5s  %-34s %s"
              % (r["competition_id"], r["season_id"],
                 r["competition_name"], r["season_name"]))

    # 2. recherche ciblée : 3e division
    print("\n--- RECHERCHE 'National' / 'Ligue 3' ---")
    if "competition_name" in comps.columns:
        hit = comps[comps.competition_name.str.contains(
            "National|Ligue 3", case=False, na=False)]
        if len(hit) == 0:
            print("  AUCUNE correspondance -> le Championnat National n'est PAS")
            print("  couvert par ce compte. Pas de stats StatsBomb possibles")
            print("  pour Sochaux et Dijon sur leur saison 2025-2026.")
        else:
            for _, r in hit.iterrows():
                print("  TROUVÉ : comp=%s season=%s  %s %s (%s)"
                      % (r["competition_id"], r["season_id"],
                         r.get("country_name", ""), r["competition_name"],
                         r["season_name"]))

    # 3. la liste complète des compétitions distinctes, pour information
    print("\n--- TOUTES LES COMPÉTITIONS ---")
    if "competition_name" in comps.columns:
        seen = comps.drop_duplicates("competition_id")
        for _, r in seen.sort_values(
                ["country_name", "competition_name"]).iterrows():
            print("  comp=%-5s %-18s %s"
                  % (r["competition_id"], r.get("country_name", ""),
                     r["competition_name"]))


if __name__ == "__main__":
    main()
