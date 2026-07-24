#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_finishing.py — un enregistrement par TIR de la saison, pour la vue
« Finishing » de la page Attacking. Écrit finishing.json à la racine du repo ;
une GitHub Action le régénère => auto-actualisé.

CE QUI EST STOCKÉ, par tir :
  équipe, tireur, position du tir (repère StatsBomb 0-120 / 0-80),
  issue, action type, position de la passe décisive et son auteur.

ACTION TYPE — mêmes règles que build_shotmix.py, fenêtre de 15 s comprise :
  positional   play_pattern "Regular Play"  +  la famille « autres »
               ("From Throw In", "From Goal Kick", "From Keeper", "Other"),
               versée dedans sur décision de Geoffrey
  transition   "From Counter"
  set_piece    "From Free Kick" ou "From Corner", uniquement si le tir survient
               dans les SP_WINDOW secondes suivant la remise en jeu ; au-delà la
               séquence est redevenue de l'attaque placée et bascule en positional

ISSUE DU TIR :
  goal   shot_outcome "Goal"
  on     "Saved", "Saved to Post"          (cadré)
  off    tout le reste — "Off T", "Wayward", "Blocked", "Post", "Saved Off T".
         Les tirs contrés et les poteaux comptent donc en NON CADRÉ.

EXCLUS : penalties (shot_type "Penalty") et période 5 (séance de tirs au but).

PASSE DÉCISIVE : `shot_key_pass_id` pointe vers l'événement de passe. On récupère
sa position d'origine et son auteur. Un tir sans passe décisive (conduite, second
ballon, récupération) a kx = ky = -1 et kp = -1.

Sortie finishing.json — tables d'index puis une matrice compacte :
{
  "competition": "Ligue 2", "season": "...", "season_id": 318, "updated": "...Z",
  "sp_window": 15,
  "teams":   ["Amiens", ...],
  "players": ["Alexandre Mendy", ...],
  "acts":    ["positional", "transition", "set_piece"],
  "outs":    ["off", "on", "goal"],
  "shots":   [[t, p, x, y, o, a, kx, ky, kp], ...]
}
t/p/kp = indices dans teams/players ; o = indice dans outs ; a = indice dans acts.

SAISON : défaut CURRENT_SEASON -> finishing.json, sinon finishing_<saison>.json.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_finishing.py
"""

import os
import sys
import json
import datetime
from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318}

SHOOTOUT_PERIOD = 5
try:
    SP_WINDOW = float(os.environ.get("SP_WINDOW", "15"))
except ValueError:
    SP_WINDOW = 15.0

ACTS = ["positional", "transition", "set_piece"]
OUTS = ["off", "on", "goal"]
ON_TARGET = {"Saved", "Saved to Post"}

PATTERN_ACT = {
    "Regular Play": "positional",
    "From Counter": "transition",
    "From Free Kick": "set_piece",
    "From Corner": "set_piece",
    "From Throw In": "positional",
    "From Goal Kick": "positional",
    "From Keeper": "positional",
    "Other": "positional",
}
WINDOWED = {"set_piece"}


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
    out = "finishing.json" if label == CURRENT_SEASON else f"finishing_{label}.json"
    return label, sid, out


def tsec(ts):
    try:
        hh, mm, ss = str(ts).split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None


def blank(v):
    return v is None or (isinstance(v, float) and v != v) or v == ""


def xy(loc):
    try:
        x, y = float(loc[0]), float(loc[1])
    except (TypeError, ValueError, IndexError):
        return None
    if x != x or y != y:
        return None
    return round(x, 1), round(y, 1)


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}  (fenêtre CPA {SP_WINDOW:.0f}s)")
    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

    teams, players = [], []
    ti, pi = {}, {}

    def idx_team(name):
        if name not in ti:
            ti[name] = len(teams)
            teams.append(name)
        return ti[name]

    def idx_player(name):
        if blank(name):
            return -1
        if name not in pi:
            pi[name] = len(players)
            players.append(name)
        return pi[name]

    shots = []
    reclassified = 0
    n_match = 0

    for _, m in matches.iterrows():
        mid = m["match_id"]
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
        c_per, c_ts = col("period"), col("timestamp")
        c_poss = col("possession")
        c_loc, c_pat = col("location"), col("play_pattern")
        c_stype, c_out = col("shot_type"), col("shot_outcome")
        c_player, c_id = col("player"), col("id")
        c_kp = col("shot_key_pass_id")
        get = lambda s, i: (s.get(i) if s is not None else None)

        # index des événements par identifiant, pour retrouver la passe décisive
        by_id = {}
        if c_id is not None:
            for i in ev.index:
                v = c_id.get(i)
                if not blank(v):
                    by_id[str(v)] = i

        # instant de la remise en jeu de chaque possession
        poss_start = {}
        if c_poss is not None and c_ts is not None:
            for i in ev.index:
                p = c_poss.get(i)
                if p != p or p in poss_start:
                    continue
                t = tsec(c_ts.get(i))
                if t is not None:
                    poss_start[p] = (get(c_per, i), t)

        for i in ev.index:
            if c_type.get(i) != "Shot":
                continue
            if c_per is not None and c_per.get(i) == SHOOTOUT_PERIOD:
                continue
            if c_stype is not None and c_stype.get(i) == "Penalty":
                continue
            pt = xy(get(c_loc, i))
            if pt is None:
                continue

            act = PATTERN_ACT.get(str(get(c_pat, i)), "positional")
            if act in WINDOWED and c_poss is not None and c_ts is not None:
                ref = poss_start.get(c_poss.get(i))
                t1 = tsec(c_ts.get(i))
                if ref is not None and t1 is not None:
                    per0, t0 = ref
                    same = (per0 is None or c_per is None or per0 == c_per.get(i))
                    if same and (t1 - t0) > SP_WINDOW:
                        act = "positional"
                        reclassified += 1

            o = get(c_out, i)
            if o == "Goal":
                out_i = 2
            elif str(o) in ON_TARGET:
                out_i = 1
            else:
                out_i = 0

            kx = ky = -1
            kp = -1
            kid = get(c_kp, i)
            if not blank(kid):
                j = by_id.get(str(kid))
                if j is not None:
                    kpt = xy(get(c_loc, j))
                    if kpt is not None:
                        kx, ky = kpt
                    kp = idx_player(get(c_player, j))

            shots.append([idx_team(c_team.get(i)), idx_player(get(c_player, i)),
                          pt[0], pt[1], out_i, ACTS.index(act), kx, ky, kp])

    by_team = {}
    for s in shots:
        by_team[teams[s[0]]] = by_team.get(teams[s[0]], 0) + 1
    for t in sorted(by_team, key=lambda k: -by_team[k]):
        print(f"  ✓ {t:<18} {by_team[t]} tirs")

    ng = sum(1 for s in shots if s[4] == 2)
    non = sum(1 for s in shots if s[4] == 1)
    nk = sum(1 for s in shots if s[8] >= 0)
    print(f"\n{len(shots)} tirs | {ng} buts | {non} cadrés non marqués | "
          f"{nk} avec passe décisive identifiée | {reclassified} CPA reclassés en positional")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "sp_window": SP_WINDOW,
        "matches": n_match,
        "teams": teams,
        "players": players,
        "acts": ACTS,
        "outs": OUTS,
        "shots": shots,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{out_path} écrit : {len(teams)} équipes, {len(players)} joueurs.")


if __name__ == "__main__":
    main()
