#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_defending.py — hauteur du BLOC DÉFENSIF par équipe, par match, sur toute
la saison. Écrit defending.json à la racine du repo, lu au runtime par
defending.html ; une GitHub Action le régénère => auto-actualisé.

HAUTEUR DU BLOC = « defensive distance » StatsBomb : distance moyenne, le long
de l'axe du terrain, des actions défensives de l'équipe par rapport à son propre
but. Plus la valeur est haute, plus l'équipe défend loin de son but ; les mètres
« laissés derrière » sont l'espace entre son but et cette ligne.

Comme la métrique agrégée n'est pas garantie dans tous les abonnements, on la
RECALCULE depuis les événements, ce qui la rend disponible partout et permet le
détail par match, à domicile et à l'extérieur :

  actions défensives retenues : Pressure, Interception, Duel, Clearance, Block,
                                Ball Recovery, Foul Committed, Tackle
  x défensif normalisé : pour chaque action, distance au propre but. StatsBomb
    place toujours l'équipe qui a le ballon en attaque vers x=120 ; une action
    défensive est enregistrée dans le repère de l'équipe QUI DÉFEND avec le but
    défendu en x=0, donc x = distance au but. On moyenne ces x sur le match.
  -> block_x (mètres) = moyenne ; behind = block_x (espace devant le but couvert)

Sortie defending.json :
{
  "competition": "Ligue 2", "season": "...", "season_id": 318, "updated": "...Z",
  "teams": {
    "<équipe>": {
      "matches": [
        {"mid":.., "date":"..", "opp":"..", "venue":"home|away",
         "gf":.., "ga":.., "block":.., "formation":"4-3-3"|null,
         "opp_formation":"..."|null}
      ],
      "avg": {"all":.., "home":.., "away":..}     # moyennes de block
    }
  },
  "standings": [ {"team":"..", "rank":.., "pts":.., "played":..}, ... ]  # actuel
}

Le classement (pour les filtres « face au top 5 / top 10 ») est calculé depuis
les résultats des matchs terminés — il se réactualise donc à chaque journée.

SAISON : défaut CURRENT_SEASON -> defending.json, sinon defending_<saison>.json.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_defending.py
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

SHOOTOUT_PERIOD = 5
DEF_ACTIONS = {"Pressure", "Interception", "Duel", "Clearance", "Block",
               "Ball Recovery", "Foul Committed", "Tackle"}
PITCH_X = 120.0


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
    out = "defending.json" if label == CURRENT_SEASON else f"defending_{label}.json"
    return label, sid, out


def blank(v):
    return v is None or (isinstance(v, float) and v != v) or v == ""


def xof(loc):
    try:
        x = float(loc[0])
    except (TypeError, ValueError, IndexError):
        return None
    return None if x != x else x


def formation_of(ev, team):
    """Formation de départ de l'équipe : event 'Starting XI' -> tactics.formation."""
    if "type" not in ev.columns:
        return None
    sub = ev[ev["type"] == "Starting XI"]
    for _, r in sub.iterrows():
        if r.get("team") != team:
            continue
        tac = r.get("tactics")
        if isinstance(tac, dict):
            f = tac.get("formation")
            if f:
                return str(f)
    return None


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    season_label, season_id, out_path = resolve_season()
    print(f"Saison {season_label} -> {out_path}")
    print(f"Récupération des matchs (competition_id={COMPETITION_ID}, season_id={season_id})…")
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)

    meta = {}
    for _, m in matches.iterrows():
        mid = m["match_id"]
        meta[mid] = {
            "home": m.get("home_team"), "away": m.get("away_team"),
            "hs": m.get("home_score"), "as": m.get("away_score"),
            "date": str(m.get("match_date", "") or "")[:10],
            "status": str(m.get("match_status", "") or ""),
        }

    teams = defaultdict(lambda: {"matches": []})
    standings = defaultdict(lambda: {"pts": 0, "played": 0, "gf": 0, "ga": 0, "w": 0, "d": 0, "l": 0})

    for _, m in matches.iterrows():
        mid = m["match_id"]
        info = meta[mid]
        home, away = info["home"], info["away"]
        hs, as_ = info["hs"], info["as"]

        # classement : matchs terminés uniquement
        done = (hs is not None and as_ is not None and hs == hs and as_ == as_)
        if done:
            hs, as_ = int(hs), int(as_)
            for t, gf, ga in ((home, hs, as_), (away, as_, hs)):
                s = standings[t]
                s["played"] += 1; s["gf"] += gf; s["ga"] += ga
                if gf > ga: s["pts"] += 3; s["w"] += 1
                elif gf == ga: s["pts"] += 1; s["d"] += 1
                else: s["l"] += 1

        try:
            ev = sb.events(match_id=mid)
        except Exception as e:
            print(f"  · match {mid} ignoré ({e})")
            continue
        if ev is None or len(ev) == 0 or "type" not in ev.columns:
            continue

        col = lambda c: ev[c] if c in ev.columns else None
        c_team, c_type = ev["team"], ev["type"]
        c_per, c_loc = col("period"), col("location")

        form = {home: formation_of(ev, home), away: formation_of(ev, away)}

        # somme et compte des x défensifs par équipe
        acc = {home: [0.0, 0], away: [0.0, 0]}
        for idx in ev.index:
            if c_per is not None and c_per.get(idx) == SHOOTOUT_PERIOD:
                continue
            t = c_team.get(idx)
            if t not in acc or c_type.get(idx) not in DEF_ACTIONS:
                continue
            x = xof(c_loc.get(idx) if c_loc is not None else None)
            if x is None:
                continue
            acc[t][0] += x
            acc[t][1] += 1

        for t in (home, away):
            s, n = acc[t]
            if n == 0:
                continue
            block = round(s / n, 1)
            opp = away if t == home else home
            venue = "home" if t == home else "away"
            gf = (hs if t == home else as_) if done else None
            ga = (as_ if t == home else hs) if done else None
            teams[t]["matches"].append({
                "mid": int(mid), "date": info["date"], "opp": opp, "venue": venue,
                "gf": gf, "ga": ga, "block": block,
                "formation": form.get(t), "opp_formation": form.get(opp),
            })

    # moyennes par équipe
    out_teams = {}
    for t, d in teams.items():
        ms = sorted(d["matches"], key=lambda x: x["date"])
        def avg(vs):
            vs = [x["block"] for x in vs]
            return round(sum(vs) / len(vs), 1) if vs else None
        out_teams[t] = {
            "matches": ms,
            "avg": {"all": avg(ms),
                    "home": avg([x for x in ms if x["venue"] == "home"]),
                    "away": avg([x for x in ms if x["venue"] == "away"])},
        }

    # classement final trié
    table = []
    for t, s in standings.items():
        table.append({"team": t, "pts": s["pts"], "played": s["played"],
                      "gf": s["gf"], "ga": s["ga"], "gd": s["gf"] - s["ga"],
                      "w": s["w"], "d": s["d"], "l": s["l"]})
    table.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))
    for i, r in enumerate(table, start=1):
        r["rank"] = i

    for r in table[:6]:
        print(f"  {r['rank']:>2}. {r['team']:<18} {r['pts']} pts")
    for t in sorted(out_teams):
        a = out_teams[t]["avg"]
        print(f"  ✓ {t:<18} bloc all={a['all']} home={a['home']} away={a['away']} "
              f"({len(out_teams[t]['matches'])} matchs)")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "teams": out_teams,
        "standings": table,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(out_teams)} équipes.")


if __name__ == "__main__":
    main()
