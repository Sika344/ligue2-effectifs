#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pressing.py — intensité et réussite du pressing par équipe, sur la saison,
pour la page « Defending » (sous-vue Pressing). Écrit pressing.json à la racine
du repo ; une GitHub Action le régénère.

DEUX AXES, calculés pour deux seuils de « camp adverse » (x>60 et x>80) :

  X — INTENSITÉ = PPDA INVERSÉ (haut = presse fort).
      PPDA = passes de l'adversaire / actions défensives de l'équipe, dans la
      zone de construction adverse (au-dessus du seuil). Une valeur BASSE de PPDA
      = pressing intense ; on affiche donc son inverse (100 / PPDA) pour que
      « plus haut = presse plus fort ».
        passes adverses  : événements Pass de l'adversaire, origine x >= seuil
        actions défensives : Pressure, Interception, Duel, Tackle, Foul Committed
                             de l'équipe, origine x >= seuil
      (définition standard du PPDA : on ne compte pas les Clearance/Block/Recovery)

  Y — RÉUSSITE = récupérations hautes + dépossessions adverses provoquées, dans
      le camp adverse (au-dessus du seuil), par match ou en cumul.
        récupérations hautes : Ball Recovery, Interception, tacle gagné de
                               l'équipe, x >= seuil
        dépossessions adverses : événements de l'adversaire, x >= seuil, marquant
                               une perte de balle — Dispossessed, Miscontrol,
                               passe/dribble Incomplete, et sorties en touche
                               (drapeau `out`)
      On stocke le compte brut ; la page divise par le nombre de matchs pour la
      vue « Par match ».

Période 5 (séance de tirs au but) exclue. Coordonnées dans le repère de l'équipe
qui réalise l'action (0-120 vers le but adverse) ; les événements adverses sont
retournés (x -> 120-x) pour être comparés au même seuil côté camp adverse.

SORTIE pressing.json :
{
  "competition":"Ligue 2","season":"2025-2026","season_id":318,"updated":"...Z",
  "teams": {
    "<équipe>": {
      "matches": N,
      "z60": {"opp_pass":.., "def_act":.., "recov":.., "disp":..},
      "z80": {"opp_pass":.., "def_act":.., "recov":.., "disp":..}
    }
  }
}
opp_pass / def_act servent au PPDA ; recov + disp = numérateur de l'axe Y.

SAISON : défaut CURRENT_SEASON -> pressing.json, sinon pressing_<saison>.json.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_pressing.py
"""

import os
import sys
import json
import datetime
from collections import defaultdict
from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318}

SHOOTOUT_PERIOD = 5
THRESHOLDS = {"z60": 60.0, "z80": 80.0}

# --- ventilation fine, ajoutee pour les filtres de la page Defending ---------
# Quatre quarts egaux du terrain, dans le sens d'attaque de l'equipe observee.
# 120 unites StatsBomb = 105 m, donc ~26 m par zone.
#   q1 = basse | q2 = mediane basse | q3 = mediane haute | q4 = haute
ZONES = (("q1", 0.0, 30.0), ("q2", 30.0, 60.0), ("q3", 60.0, 90.0), ("q4", 90.0, 120.1))
# Coups de pied arretes : meme convention que build_inposs.py (Set pieces xG).
SET_PIECE = {"From Corner", "From Free Kick", "From Throw In"}
COUNTERS = ("opp_pass", "def_act", "recov", "disp")


def zone_of(xa):
    for name, lo, hi in ZONES:
        if lo <= xa < hi:
            return name
    return None

# actions défensives comptées au dénominateur du PPDA (définition standard)
PPDA_DEF = {"Pressure", "Interception", "Duel", "Tackle", "Foul Committed"}
# récupérations « propres » comptées à l'axe Y
RECOV = {"Ball Recovery", "Interception"}


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
    out = "pressing.json" if label == CURRENT_SEASON else f"pressing_{label}.json"
    return label, sid, out


def xof(loc):
    try:
        x = float(loc[0])
    except (TypeError, ValueError, IndexError):
        return None
    return None if x != x else x


def truthy(v):
    if v is None:
        return False
    if isinstance(v, float) and v != v:
        return False
    return bool(v)


def has_outcome(v, names):
    """v est un dict d'outcome StatsBomb (ex. pass_outcome) ; True si son 'name' est dans names."""
    if isinstance(v, dict):
        return v.get("name") in names
    return str(v) in names


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}")
    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

    per_team = {}
    for _, m in matches.iterrows():
        mid = m["match_id"]
        for c in ("home_team", "away_team"):
            per_team.setdefault(m[c], set()).add(mid)

    ev_cache = {}

    def events(mid):
        if mid not in ev_cache:
            ev_cache[mid] = sb.events(match_id=mid)
        return ev_cache[mid]

    teams_out = {}
    for team, mids in sorted(per_team.items()):
        agg = {k: defaultdict(float) for k in THRESHOLDS}
        cells = {ctx: {z[0]: {c: 0 for c in COUNTERS} for z in ZONES}
                 for ctx in ("open", "sp")}
        n_match = 0
        for mid in mids:
            try:
                ev = events(mid)
            except Exception as e:
                print(f"  · {team}: match {mid} ignoré ({e})")
                continue
            if ev is None or len(ev) == 0 or "type" not in ev.columns:
                continue
            n_match += 1

            col = lambda c: ev[c] if c in ev.columns else None
            c_team, c_type = ev["team"], ev["type"]
            c_per, c_loc = col("period"), col("location")
            c_pout, c_dout = col("pass_outcome"), col("dribble_outcome")
            c_patt = col("play_pattern")
            c_out = col("out")
            c_dukw = col("duel_outcome")
            if c_loc is None:
                continue
            get = lambda s, i: (s.get(i) if s is not None else None)

            for idx in ev.index:
                if c_per is not None and c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                x = xof(get(c_loc, idx))
                if x is None:
                    continue
                typ = c_type.get(idx)
                own = c_team.get(idx) == team
                # x dans le repère du camp adverse de "team"
                xa = x if own else (120.0 - x)

                # --- ventilation zone x contexte (independante des seuils PPDA) ---
                zn = zone_of(xa)
                if zn is not None:
                    ctx = "sp" if (get(c_patt, idx) in SET_PIECE) else "open"
                    cc = cells[ctx][zn]
                    if own:
                        if typ in PPDA_DEF:
                            cc["def_act"] += 1
                        if typ in RECOV:
                            cc["recov"] += 1
                        elif typ == "Duel" and has_outcome(get(c_dukw, idx),
                                                           {"Won", "Success", "Success In Play",
                                                            "Success Out"}):
                            cc["recov"] += 1
                    else:
                        if typ == "Pass":
                            cc["opp_pass"] += 1
                        if typ in ("Dispossessed", "Miscontrol"):
                            cc["disp"] += 1
                        elif typ == "Pass" and has_outcome(get(c_pout, idx),
                                                           {"Incomplete", "Out"}):
                            cc["disp"] += 1
                        elif typ == "Dribble" and has_outcome(get(c_dout, idx), {"Incomplete"}):
                            cc["disp"] += 1
                        elif truthy(get(c_out, idx)):
                            cc["disp"] += 1

                for key, thr in THRESHOLDS.items():
                    if xa < thr:
                        continue
                    a = agg[key]
                    if own:
                        # dénominateur PPDA + récupérations hautes
                        if typ in PPDA_DEF:
                            a["def_act"] += 1
                        if typ in RECOV:
                            a["recov"] += 1
                        elif typ == "Duel" and has_outcome(get(c_dukw, idx),
                                                            {"Won", "Success", "Success In Play",
                                                             "Success Out"}):
                            a["recov"] += 1
                    else:
                        # numérateur PPDA : passes adverses
                        if typ == "Pass":
                            a["opp_pass"] += 1
                        # dépossessions adverses provoquées
                        if typ in ("Dispossessed", "Miscontrol"):
                            a["disp"] += 1
                        elif typ == "Pass" and has_outcome(get(c_pout, idx),
                                                           {"Incomplete", "Out"}):
                            a["disp"] += 1
                        elif typ == "Dribble" and has_outcome(get(c_dout, idx), {"Incomplete"}):
                            a["disp"] += 1
                        elif truthy(get(c_out, idx)):
                            a["disp"] += 1

        teams_out[team] = {
            "matches": n_match,
            "cells": cells,
            "z60": {k: agg["z60"][k] for k in ("opp_pass", "def_act", "recov", "disp")},
            "z80": {k: agg["z80"][k] for k in ("opp_pass", "def_act", "recov", "disp")},
        }
        z = agg["z60"]
        ppda = (z["opp_pass"] / z["def_act"]) if z["def_act"] else 0
        y = (z["recov"] + z["disp"]) / max(1, n_match)
        print(f"  ✓ {team:<18} {n_match} matchs | PPDA(x>60) {ppda:.2f} | "
              f"réussite/match {y:.1f}")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "teams": teams_out,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(teams_out)} équipes.")


if __name__ == "__main__":
    main()
