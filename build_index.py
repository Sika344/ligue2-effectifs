#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_index.py — index OFFENSIF et DÉFENSIF par équipe, sur toute la saison.
Écrit teamindex.json à la racine du repo, lu au runtime par chartindex.html ;
une GitHub Action le régénère => auto-actualisé.

COMPOSITION DES DEUX INDEX (poids égal entre les composantes) :

  Index offensif = moyenne des z-scores de
      OBV possession          valeur créée ballon au pied
      possession %            part du temps de possession
      xG                      hors penalty, par 90
      box touches             ballons touchés dans la surface adverse, par 90

  Index défensif = moyenne des z-scores de
      OBV défensif            valeur créée par les actions défensives
      intensité défensive     actions défensives par minute de possession adverse
      xG concédés             INVERSÉ (moins on concède, mieux c'est), par 90
      box touches concédées   INVERSÉ, par 90
      récupérations hautes    actions défensives à x >= 80, par 90

Les z-scores sont calculés sur les 18 équipes de la compétition.

CENTILES DU TABLEAU : rang croissant sur n équipes -> centile = 100 * rang / n
(donc 100 pour la meilleure). OFF = centile de l'index offensif, DEF = centile
de l'index défensif, OVERALL = centile de la SOMME des deux z-scores.

OBV : les champs `obv_*` ne sont pas présents dans tous les abonnements
StatsBomb. Le script les détecte automatiquement. S'ils manquent, les deux
colonnes OBV valent null, `obv_available` passe à false, et chaque index est
calculé sur ses composantes restantes — le poids reste égal entre elles.

DÉFINITIONS DE DÉTAIL
  actions défensives : Pressure, Interception, Duel, Clearance, Block,
                       Ball Recovery, Foul Committed
  surface adverse    : x in [102, 120], y in [18, 62]
  box touches        : Pass, Ball Receipt*, Carry, Shot, Dribble dans la surface
  possession         : durée d'une séquence = dernier timestamp - premier, même période
  période 5 (tirs au but) : exclue partout

Sortie teamindex.json :
{
  "competition": "Ligue 2", "season": "2025-2026", "season_id": 318,
  "updated": "...Z", "obv_available": true/false,
  "cols": [...],           # ordre des colonnes du tableau
  "teams": {
    "<nom StatsBomb>": {
      "matches": N, "minutes": M,
      "poss": .., "def_int": .., "xg90": .., "xga90": ..,
      "boxt90": .., "boxa90": .., "hirec90": ..,
      "obv_off": .. | null, "obv_def": .. | null,
      "off_z": .., "def_z": .., "off_pct": .., "def_pct": .., "overall_pct": ..,
      "totals": {...}      # mêmes mesures en cumul saison, pour la bascule Total
    }
  }
}

SAISON : défaut CURRENT_SEASON -> teamindex.json, sinon teamindex_<saison>.json.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_index.py
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
BOX_X0, BOX_X1, BOX_Y0, BOX_Y1 = 102.0, 120.0, 18.0, 62.0
HIGH_X = 80.0

DEF_ACTIONS = {"Pressure", "Interception", "Duel", "Clearance", "Block",
               "Ball Recovery", "Foul Committed"}
TOUCH_TYPES = {"Pass", "Ball Receipt*", "Carry", "Shot", "Dribble"}
POSS_ACTIONS = {"Pass", "Carry", "Dribble", "Shot"}

COLS = ["matches", "overall_pct", "off_pct", "def_pct", "poss", "def_int",
        "xg90", "xga90", "boxt90", "boxa90", "obv_off", "obv_def", "hirec90"]


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
    out = "teamindex.json" if label == CURRENT_SEASON else f"teamindex_{label}.json"
    return label, sid, out


def tsec(ts):
    try:
        hh, mm, ss = str(ts).split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None


def fnum(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def xy(loc):
    try:
        x, y = float(loc[0]), float(loc[1])
    except (TypeError, ValueError, IndexError):
        return None
    if x != x or y != y:
        return None
    return x, y


def in_box(pt):
    return pt is not None and BOX_X0 <= pt[0] <= BOX_X1 and BOX_Y0 <= pt[1] <= BOX_Y1


def zscores(vals):
    n = len(vals)
    mu = sum(vals) / n if n else 0.0
    var = sum((v - mu) ** 2 for v in vals) / n if n else 0.0
    sd = var ** 0.5
    return [((v - mu) / sd) if sd > 1e-12 else 0.0 for v in vals]


def percentiles(vals):
    """Rang croissant sur n équipes -> 100 * rang / n (100 = meilleure)."""
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    out = [0] * n
    for rank, i in enumerate(order, start=1):
        out[i] = round(100.0 * rank / n)
    return out


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

    # ---- détection des champs OBV sur le premier match lisible
    obv_col = None
    for mids in per_team.values():
        try:
            ev = events(next(iter(mids)))
        except Exception:
            continue
        for c in ("obv_total_net", "obv_for_net"):
            if c in ev.columns:
                obv_col = c
                break
        break
    print(f"[OBV] colonne détectée : {obv_col or 'AUCUNE — les deux colonnes OBV seront vides'}")

    acc = {t: defaultdict(float) for t in per_team}
    nmatch = {t: 0 for t in per_team}

    for team, mids in sorted(per_team.items()):
        for mid in mids:
            try:
                ev = events(mid)
            except Exception as e:
                print(f"  · {team}: match {mid} ignoré ({e})")
                continue
            if ev is None or len(ev) == 0 or "type" not in ev.columns:
                continue
            nmatch[team] += 1

            col = lambda c: ev[c] if c in ev.columns else None
            c_team, c_type = ev["team"], ev["type"]
            c_per, c_ts = col("period"), col("timestamp")
            c_poss, c_pteam = col("possession"), col("possession_team")
            c_loc, c_xg = col("location"), col("shot_statsbomb_xg")
            c_stype = col("shot_type")
            c_obv = col(obv_col) if obv_col else None
            if c_per is None or c_ts is None or c_poss is None or c_pteam is None:
                continue
            get = lambda s, i: (s.get(i) if s is not None else None)

            a = acc[team]

            # durée de possession par équipe
            seqs = defaultdict(list)
            for idx in ev.index:
                if c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                pi = c_poss.get(idx)
                if pi == pi:
                    seqs[pi].append(idx)
            for pi, idxs in seqs.items():
                t0, t1 = tsec(c_ts.get(idxs[0])), tsec(c_ts.get(idxs[-1]))
                if t0 is None or t1 is None or t1 < t0:
                    continue
                d = t1 - t0
                if c_pteam.get(idxs[0]) == team:
                    a["poss_sec"] += d
                else:
                    a["opp_poss_sec"] += d
                a["tot_poss_sec"] += d

            for idx in ev.index:
                if c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                own = c_team.get(idx) == team
                typ = c_type.get(idx)
                pt = xy(get(c_loc, idx))

                # xG produit / concédé, hors penalty
                if typ == "Shot" and get(c_stype, idx) != "Penalty":
                    g = fnum(get(c_xg, idx))
                    if g is not None:
                        a["xg" if own else "xga"] += g

                # ballons touchés dans la surface
                if typ in TOUCH_TYPES and in_box(pt):
                    a["boxt" if own else "boxa"] += 1

                if typ in DEF_ACTIONS:
                    if own:
                        a["def_act"] += 1
                        if pt is not None and pt[0] >= HIGH_X:
                            a["hirec"] += 1

                if c_obv is not None and own:
                    v = fnum(get(c_obv, idx))
                    if v is not None:
                        if typ in POSS_ACTIONS:
                            a["obv_off"] += v
                        elif typ in DEF_ACTIONS:
                            a["obv_def"] += v

    # ---- mesures par équipe
    teams = sorted(per_team)
    rows = {}
    for t in teams:
        a, n = acc[t], max(1, nmatch[t])
        p90 = lambda v: v / n
        opp_min = a["opp_poss_sec"] / 60.0
        rows[t] = {
            "matches": nmatch[t],
            "poss": (100.0 * a["poss_sec"] / a["tot_poss_sec"]) if a["tot_poss_sec"] else 0.0,
            "def_int": (a["def_act"] / opp_min) if opp_min > 0 else 0.0,
            "xg90": p90(a["xg"]),
            "xga90": p90(a["xga"]),
            "boxt90": p90(a["boxt"]),
            "boxa90": p90(a["boxa"]),
            "hirec90": p90(a["hirec"]),
            "obv_off": p90(a["obv_off"]) if obv_col else None,
            "obv_def": p90(a["obv_def"]) if obv_col else None,
            "totals": {
                "xg": a["xg"], "xga": a["xga"], "boxt": a["boxt"], "boxa": a["boxa"],
                "hirec": a["hirec"], "def_act": a["def_act"],
                "obv_off": a["obv_off"] if obv_col else None,
                "obv_def": a["obv_def"] if obv_col else None,
            },
        }

    # ---- index : moyenne des z-scores des composantes disponibles
    def zof(key, sign=1):
        return zscores([sign * rows[t][key] for t in teams])

    off_parts = [zof("poss"), zof("xg90"), zof("boxt90")]
    def_parts = [zof("def_int"), zof("xga90", -1), zof("boxa90", -1), zof("hirec90")]
    if obv_col:
        off_parts.append(zof("obv_off"))
        def_parts.append(zof("obv_def"))

    off_z = [sum(p[i] for p in off_parts) / len(off_parts) for i in range(len(teams))]
    def_z = [sum(p[i] for p in def_parts) / len(def_parts) for i in range(len(teams))]
    off_p = percentiles(off_z)
    def_p = percentiles(def_z)
    all_p = percentiles([off_z[i] + def_z[i] for i in range(len(teams))])

    for i, t in enumerate(teams):
        rows[t]["off_z"] = round(off_z[i], 4)
        rows[t]["def_z"] = round(def_z[i], 4)
        rows[t]["off_pct"] = off_p[i]
        rows[t]["def_pct"] = def_p[i]
        rows[t]["overall_pct"] = all_p[i]

    for t in sorted(teams, key=lambda x: -rows[x]["overall_pct"]):
        r = rows[t]
        print(f"  ✓ {t:<18} M{r['matches']:>3} | overall {r['overall_pct']:>3} "
              f"| off {r['off_pct']:>3} | def {r['def_pct']:>3} "
              f"| poss {r['poss']:.0f}% | xG/90 {r['xg90']:.2f} | xGA/90 {r['xga90']:.2f}")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "obv_available": bool(obv_col),
        "obv_column": obv_col,
        "cols": COLS,
        "teams": rows,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(rows)} équipes. OBV disponible : {bool(obv_col)}")


if __name__ == "__main__":
    main()
