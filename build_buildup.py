#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_buildup.py — analyse des phases de construction (build-ups) par équipe,
sur toute la saison. Écrit buildup.json à la racine du repo, lu au runtime par
attacking.html ; une GitHub Action le régénère => auto-actualisé.

UN BUILD-UP = une séquence de possession de l'équipe, classée par son point de
départ. La séquence court jusqu'à la FIN DE LA POSSESSION au sens StatsBomb
(perte, tir, ballon sorti).

SIX START TYPES, cumulables (un build-up peut en porter plusieurs) :
  goalkick   Goal kick          première passe de la possession, pass_type "Goal Kick"
  gkdist     GK distribution    relance du gardien dans le jeu, hors goal kick
  openplay   Open play          play_pattern "Regular Play" ou "From Counter"
  low        Low build up       départ dans le 1er tiers (x < 40), hors goal kick
  mid        Mid build up       départ à partir du 2e tiers (x >= 40)
  throwin    Throw in           touche, uniquement si la possession dure > 6 s

Comme les catégories se recoupent, on n'agrège pas par catégorie : on agrège par
COMBINAISON EXACTE de catégories (masque de bits). Le site peut ainsi cumuler
plusieurs filtres sans jamais compter deux fois le même build-up — il suffit de
sommer les combinaisons qui intersectent la sélection.

TROIS MESURES par build-up :
  crossed    la possession amène le ballon au-delà de la médiane (x > 60)
  success    elle finit par une entrée dans le dernier tiers (x > 80) ou un tir
  pressure   parmi les passes de l'équipe tentées AVANT la médiane (origine
             x <= 60), combien sont sous pression (drapeau `under_pressure`).
             On stocke numérateur et dénominateur pour pouvoir agréger.

Sortie buildup.json :
{
  "competition": "Ligue 2", "season": "2025-2026", "season_id": 318,
  "updated": "...Z",
  "keys": ["goalkick","gkdist","openplay","low","mid","throwin"],
  "bits": {"goalkick": 1, "gkdist": 2, ...},
  "teams": {
    "<nom StatsBomb>": {
      "matches": N,
      "buckets": [ {"m": <masque>, "n": .., "cr": .., "su": .., "pu": .., "pt": ..}, ... ]
    }
  }
}
n = nombre de build-ups, cr = franchissent la médiane, su = réussis,
pu = passes avant médiane sous pression, pt = passes avant médiane au total.

SAISON (même convention que les autres scripts) :
  - défaut = CURRENT_SEASON -> buildup.json
  - autre saison -> buildup_<saison>.json
  - saison passée en argv[1] ou via la variable d'environnement SEASON.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_buildup.py
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
MIDLINE = 60.0          # médiane du terrain (repère 0-120)
FINAL_THIRD = 80.0      # entrée dans le dernier tiers
LOW_THIRD = 40.0        # limite haute du premier tiers
THROWIN_MIN_SEC = 6.0   # une touche ne compte que si la possession dure plus

KEYS = ["goalkick", "gkdist", "openplay", "low", "mid", "throwin"]
BITS = {k: 1 << i for i, k in enumerate(KEYS)}
LABELS = {
    "goalkick": "Goal kick",
    "gkdist": "GK distribution",
    "openplay": "Open play",
    "low": "Low build up",
    "mid": "Mid build up",
    "throwin": "Throw in",
}


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
    out = "buildup.json" if label == CURRENT_SEASON else f"buildup_{label}.json"
    return label, sid, out


def tsec(ts):
    try:
        hh, mm, ss = str(ts).split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None


def truthy(v):
    if v is None:
        return False
    if isinstance(v, float) and v != v:
        return False
    return bool(v)


def blank(v):
    return v is None or (isinstance(v, float) and v != v) or v == ""


def xof(loc):
    try:
        x = float(loc[0])
    except (TypeError, ValueError, IndexError):
        return None
    return None if x != x else x


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
        buckets = defaultdict(lambda: {"n": 0, "cr": 0, "su": 0, "pu": 0, "pt": 0})
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
            c_per, c_ts = col("period"), col("timestamp")
            c_poss, c_pteam = col("possession"), col("possession_team")
            c_loc, c_pat = col("location"), col("play_pattern")
            c_ptype, c_pos = col("pass_type"), col("position")
            c_press = col("under_pressure")
            if c_per is None or c_ts is None or c_poss is None or c_pteam is None:
                continue
            get = lambda s, i: (s.get(i) if s is not None else None)

            # regrouper les index par possession
            seqs = defaultdict(list)
            for idx in ev.index:
                pi = c_poss.get(idx)
                if pi == pi:
                    seqs[pi].append(idx)

            for pi, idxs in seqs.items():
                if c_pteam.get(idxs[0]) != team:
                    continue
                if c_per.get(idxs[0]) == SHOOTOUT_PERIOD:
                    continue
                own = [i for i in idxs if c_team.get(i) == team]
                if not own:
                    continue

                first = own[0]
                x0 = xof(get(c_loc, first))
                pat = get(c_pat, first)
                ptype = get(c_ptype, first)
                is_pass = c_type.get(first) == "Pass"

                # durée de la séquence
                t0, t1 = tsec(c_ts.get(idxs[0])), tsec(c_ts.get(idxs[-1]))
                dur = (t1 - t0) if (t0 is not None and t1 is not None) else 0.0

                # ---- classement en start types (cumulables)
                mask = 0
                gk = is_pass and str(ptype) == "Goal Kick"
                if gk:
                    mask |= BITS["goalkick"]
                if is_pass and str(ptype) == "Throw-in" and dur > THROWIN_MIN_SEC:
                    mask |= BITS["throwin"]
                if not gk and (str(pat) == "From Keeper"
                               or (is_pass and blank(ptype) and str(get(c_pos, first)) == "Goalkeeper")):
                    mask |= BITS["gkdist"]
                if str(pat) in ("Regular Play", "From Counter"):
                    mask |= BITS["openplay"]
                if x0 is not None:
                    if x0 < LOW_THIRD and not gk:
                        mask |= BITS["low"]
                    if x0 >= LOW_THIRD:
                        mask |= BITS["mid"]
                if not mask:
                    continue

                # ---- mesures
                crossed = success = False
                pu = pt = 0
                for i in own:
                    x = xof(get(c_loc, i))
                    if x is not None:
                        if x > MIDLINE:
                            crossed = True
                        if x > FINAL_THIRD:
                            success = True
                    if c_type.get(i) == "Shot":
                        success = True
                    if c_type.get(i) == "Pass" and x is not None and x <= MIDLINE:
                        pt += 1
                        if truthy(get(c_press, i)):
                            pu += 1

                b = buckets[mask]
                b["n"] += 1
                b["cr"] += 1 if crossed else 0
                b["su"] += 1 if success else 0
                b["pu"] += pu
                b["pt"] += pt

        rows = [{"m": m, **v} for m, v in sorted(buckets.items())]
        teams_out[team] = {"matches": n_match, "buckets": rows}
        tot = sum(r["n"] for r in rows)
        cr = sum(r["cr"] for r in rows)
        su = sum(r["su"] for r in rows)
        ptt = sum(r["pt"] for r in rows)
        puu = sum(r["pu"] for r in rows)
        f = lambda a, b_: (100.0 * a / b_) if b_ else 0
        print(f"  ✓ {team}: {n_match} matchs | {tot} build-ups | "
              f"médiane {f(cr, tot):.0f}% | réussis {f(su, tot):.0f}% | "
              f"pression {f(puu, ptt):.0f}%")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "keys": KEYS,
        "bits": BITS,
        "labels": LABELS,
        "teams": teams_out,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(teams_out)} équipes.")


if __name__ == "__main__":
    main()
