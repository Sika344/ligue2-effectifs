#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_shotmix.py — répartition des TIRS et des BUTS par famille d'attaque,
sur toute la saison, pour chaque équipe. Écrit shotmix.json à la racine du repo.
La page rapport-pre-match.html le charge au runtime (comme xg.json / losses.json) ;
une GitHub Action le régénère => auto-actualisé.

QUATRE FAMILLES, à partir du champ StatsBomb `play_pattern` du tir :

  placee      Attaque placée          play_pattern = "Regular Play"
  transition  Transition offensive    play_pattern = "From Counter"
  cpa         Coup de pied arrêté     play_pattern = "From Free Kick" ou "From Corner"
  autres      Autres                  "From Throw In", "From Goal Kick",
                                      "From Keeper", "Other" — et tout libellé inconnu

FENÊTRE DE 15 SECONDES (SP_WINDOW) — correctif important :
`play_pattern` décrit l'ORIGINE DE LA POSSESSION et l'étiquette persiste sur
toute la séquence. Un corner dégagé, récupéré, recyclé, puis frappé 40 s plus
tard resterait tagué "From Corner" alors que la phase est redevenue de
l'attaque placée. Idem pour une touche suivie de vingt passes.
On mesure donc le délai entre la remise en jeu (premier événement de la
possession) et le tir :
  - délai <= SP_WINDOW  -> la famille d'origine est conservée (cpa / autres)
  - délai >  SP_WINDOW  -> le tir bascule en "placee"
"Regular Play" et "From Counter" ne sont jamais reclassés.
SP_WINDOW vaut 15 secondes par défaut, réglable par variable d'environnement.

PENALTIES EXCLUS : les tirs dont `shot_type` vaut "Penalty" ne sont comptés
nulle part, ni dans les tirs ni dans les buts, ni dans les totaux. On raisonne
donc entièrement hors penalty. Les tirs de la période 5 (séance de tirs au but)
sont eux aussi écartés.

PERSPECTIVE OFFENSIVE : on compte les tirs et buts PRODUITS par l'équipe, pas
ceux qu'elle concède.

xG : somme des `shot_statsbomb_xg` par famille, mêmes exclusions que les tirs
(penalties et période 5 écartés). Sert au nuage Buts vs xG de la page Attacking.

BUT = tir dont `shot_outcome` vaut "Goal". Les csc sont des événements
"Own Goal For"/"Own Goal Against" et non des tirs : ils n'entrent donc pas
dans le décompte, ce qui est le comportement voulu.

Sortie shotmix.json :
{
  "competition": "Ligue 2", "season": "2025-2026", "season_id": 318,
  "updated": "...Z",
  "keys": ["placee", "transition", "cpa", "autres"],
  "labels": {"placee": "Attaque placée", ...},
  "teams": {
    "<nom StatsBomb>": {
      "matches": N,
      "shots":  {"placee": .., "transition": .., "cpa": .., "autres": ..},
      "goals":  {"placee": .., "transition": .., "cpa": .., "autres": ..},
      "xg":     {"placee": .., "transition": .., "cpa": .., "autres": ..},
      "shots_total": T, "goals_total": G, "xg_total": X
    }
  }
}

SAISON (même convention que build_xg.py / build_losses.py) :
  - défaut = CURRENT_SEASON -> shotmix.json
  - autre saison -> shotmix_<saison>.json  (ex. shotmix_2024-2025.json)
  - saison passée en argv[1] ou via la variable d'environnement SEASON.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_shotmix.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_shotmix.py 2024-2025
"""

import os
import sys
import json
import datetime
from statsbombpy import sb

COMPETITION_ID = 8              # Ligue 2
CURRENT_SEASON = "2025-2026"    # saison courante -> sortie NON suffixée
SEASON_IDS = {
    "2025-2026": 318,
}

SHOOTOUT_PERIOD = 5

# délai max entre la remise en jeu et le tir pour rester un coup de pied arrêté
try:
    SP_WINDOW = float(os.environ.get("SP_WINDOW", "15"))
except ValueError:
    SP_WINDOW = 15.0

# familles soumises à la fenêtre : au-delà, le tir redevient de l'attaque placée
WINDOWED = {"cpa", "autres"}

KEYS = ["placee", "transition", "cpa", "autres"]
LABELS = {
    "placee": "Attaque placée",
    "transition": "Transition offensive",
    "cpa": "Coup de pied arrêté",
    "autres": "Autres",
}

PATTERN_MAP = {
    "Regular Play": "placee",
    "From Counter": "transition",
    "From Free Kick": "cpa",
    "From Corner": "cpa",
    "From Throw In": "autres",
    "From Goal Kick": "autres",
    "From Keeper": "autres",
    "Other": "autres",
}


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
    label = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "")).strip()
    if not label:
        label = CURRENT_SEASON
    sid = SEASON_IDS.get(label) or lookup_season_id(label)
    out = "shotmix.json" if label == CURRENT_SEASON else f"shotmix_{label}.json"
    return label, sid, out


def tsec(ts):
    """timestamp StatsBomb "HH:MM:SS.mmm" -> secondes écoulées dans la période."""
    try:
        hh, mm, ss = str(ts).split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None


def blank(v):
    return v is None or (isinstance(v, float) and v != v) or v == ""


def family(play_pattern):
    if blank(play_pattern):
        return "autres"
    return PATTERN_MAP.get(str(play_pattern), "autres")


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants dans l'environnement.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}")

    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

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
    reclassified = 0
    for team, mids in sorted(per_team.items()):
        shots = {k: 0 for k in KEYS}
        goals = {k: 0 for k in KEYS}
        xg = {k: 0.0 for k in KEYS}
        n = 0
        for mid in mids:
            try:
                ev = events(mid)
            except Exception as e:
                print(f"  · {team}: match {mid} ignoré ({e})")
                continue
            if ev is None or len(ev) == 0 or "type" not in ev.columns:
                continue
            n += 1

            col = lambda c: ev[c] if c in ev.columns else None
            c_team, c_type = ev["team"], ev["type"]
            c_per = col("period")
            c_pat = col("play_pattern")
            c_stype = col("shot_type")
            c_out = col("shot_outcome")
            c_xg = col("shot_statsbomb_xg")
            c_ts = col("timestamp")
            c_poss = col("possession")

            # instant de la remise en jeu = premier événement de chaque possession
            poss_start = {}
            if c_poss is not None and c_ts is not None:
                for idx in ev.index:
                    pi = c_poss.get(idx)
                    if pi != pi or pi in poss_start:
                        continue
                    t = tsec(c_ts.get(idx))
                    if t is not None:
                        poss_start[pi] = (c_per.get(idx) if c_per is not None else None, t)

            for idx in ev.index:
                if c_team.get(idx) != team or c_type.get(idx) != "Shot":
                    continue
                if c_per is not None and c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                # penalties écartés partout
                if c_stype is not None and c_stype.get(idx) == "Penalty":
                    continue

                fam = family(c_pat.get(idx) if c_pat is not None else None)

                # fenêtre : au-delà de SP_WINDOW après la remise en jeu,
                # la séquence est redevenue de l'attaque placée
                if fam in WINDOWED and c_poss is not None and c_ts is not None:
                    ref = poss_start.get(c_poss.get(idx))
                    t1 = tsec(c_ts.get(idx))
                    if ref is not None and t1 is not None:
                        per0, t0 = ref
                        same_period = (per0 is None or c_per is None
                                       or per0 == c_per.get(idx))
                        if same_period and (t1 - t0) > SP_WINDOW:
                            fam = "placee"
                            reclassified += 1

                shots[fam] += 1
                if c_out is not None and c_out.get(idx) == "Goal":
                    goals[fam] += 1
                if c_xg is not None:
                    try:
                        v = float(c_xg.get(idx))
                        if v == v:
                            xg[fam] += v
                    except (TypeError, ValueError):
                        pass

        st = sum(shots.values())
        gt = sum(goals.values())
        xt = sum(xg.values())
        teams_out[team] = {
            "matches": n,
            "shots": shots,
            "goals": goals,
            "xg": {k: round(v, 3) for k, v in xg.items()},
            "shots_total": st,
            "goals_total": gt,
            "xg_total": round(xt, 3),
        }
        pct = lambda d, tot: " / ".join(
            f"{k}:{(100.0 * d[k] / tot):.0f}%" if tot else f"{k}:—" for k in KEYS
        )
        print(f"  ✓ {team}: {n} matchs | {st} tirs ({pct(shots, st)}) | "
              f"{gt} buts ({pct(goals, gt)}) | {xt:.1f} xG")

    print(f"\n[fenêtre {SP_WINDOW:.0f}s] {reclassified} tirs reclassés en attaque placée "
          f"(séquence trop éloignée de la remise en jeu).")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "keys": KEYS,
        "labels": LABELS,
        "note": "hors penalty",
        "sp_window": SP_WINDOW,
        "teams": teams_out,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(teams_out)} équipes.")


if __name__ == "__main__":
    main()
