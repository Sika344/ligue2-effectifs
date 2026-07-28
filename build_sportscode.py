#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_sportscode.py — timelines événementielles par match, pour export Hudl SportsCode.

Écrit :
    sc/index.json            catalogue des matchs (journée, date, équipes, score)
    sc/sc_<match_id>.json    timeline d'un match

La page `sportscode.html` charge ces JSON au runtime et génère le XML SportsCode
côté navigateur (avec offsets vidéo et seuils réglables par l'utilisateur).

Identifiants StatsBomb via SB_USERNAME / SB_PASSWORD (lus par statsbombpy).
Ne jamais committer les identifiants.

SAISON :
  - défaut = CURRENT_SEASON -> sortie dans sc/
  - autre saison -> sortie dans sc_<saison>/
  - saison passée en argv[1] ou via la variable d'environnement SEASON ("2024-2025").

MODE INCRÉMENTAL (défaut) : un match dont le JSON existe déjà est ignoré.
    --force  régénère tout.
    --limit N  ne traite que N matchs (utile pour tester).

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_sportscode.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_sportscode.py 2024-2025 --force

--------------------------------------------------------------------------------
FORMAT sc_<match_id>.json
--------------------------------------------------------------------------------
{
  "match_id": 3922241,
  "competition": "Ligue 2", "season": "2025-2026",
  "date": "2025-08-09", "round": 1,
  "home": "Amiens", "away": "Troyes", "score": "1-2",
  "teams": ["Amiens", "Troyes"],
  "periods": [1, 2],
  "updated": "2026-07-28T10:00:00Z",
  "ev": [ ... ]
}

Chaque événement porte :
    k    type      ko | gk | pos | sh | cr | og
    team nom StatsBomb de l'équipe concernée
    p    période (1 = 1re MT, 2 = 2e MT, 3/4 = prolongations)
    s    secondes écoulées DEPUIS LE COUP D'ENVOI DE CETTE PÉRIODE

Détail par type :
    ko   coup d'envoi                    -> {k,team,p,s}
    gk   six mètres                      -> {k,team,p,s, pe, len, nxt[]}
             pe   = fin de la possession issue du 6m (s de la période)
             len  = longueur en mètres de la passe de 6m
             nxt  = longueurs des passes suivantes de la même équipe dans la
                    même possession (5 max) -> sert au calcul "short-long"
    pos  possession                      -> {k,team,p,s, e, n}
             e = fin, n = nombre d'événements de la possession
    sh   tir                             -> {k,team,p,s, xg, o, pen, pl}
             o = shot_outcome StatsBomb brut (Goal / Saved / Off T / Blocked / …)
             pen = True si penalty (hors séance de tirs au but, exclue)
    cr   centre                          -> {k,team,p,s, o, pl}
             o = pass_outcome StatsBomb ("" = passe réussie)
    og   but contre son camp             -> {k,team,p,s, pl}
             team = équipe QUI MARQUE (bénéficiaire du csc)

Les libellés de lignes SportsCode, durées avant/après et descripteurs sont
entièrement gérés côté HTML : ce script ne fait que fournir la matière brute.
"""

import os
import sys
import json
import math
import datetime

from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318}

# StatsBomb : terrain 120 x 80 unités = 105 x 68 mètres
MX = 105.0 / 120.0
MY = 68.0 / 80.0

MAX_NXT = 5          # nb de passes suivantes stockées après un 6m
PERIODS = (1, 2, 3, 4)   # 5 = séance de tirs au but -> exclue


# ------------------------------------------------------------------ utilitaires

def ts_seconds(timestamp):
    """'00:12:34.567' (relatif au début de la période) -> 754.567"""
    if not isinstance(timestamp, str):
        return None
    try:
        h, m, rest = timestamp.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    except (ValueError, AttributeError):
        return None


def val(row, key, default=None):
    """Accès tolérant à une colonne pandas éventuellement absente ou NaN."""
    v = row.get(key, default)
    if v is None:
        return default
    if isinstance(v, float) and math.isnan(v):
        return default
    return v


def loc_xy(v):
    """[x, y] StatsBomb -> (x, y) ou None."""
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return None
    return None


def pass_length_m(row):
    """Longueur de la passe en mètres, depuis location -> pass_end_location."""
    a = loc_xy(val(row, "location"))
    b = loc_xy(val(row, "pass_end_location"))
    if not a or not b:
        # repli : pass_length StatsBomb est en unités terrain
        pl = val(row, "pass_length")
        if pl is None:
            return None
        try:
            return round(float(pl) * MX, 1)
        except (TypeError, ValueError):
            return None
    dx = (b[0] - a[0]) * MX
    dy = (b[1] - a[1]) * MY
    return round(math.hypot(dx, dy), 1)


def resolve_season_id(season):
    if season in SEASON_IDS:
        return SEASON_IDS[season]
    comps = sb.competitions()
    hit = comps[(comps.competition_id == COMPETITION_ID)
                & (comps.season_name == season)]
    if hit.empty:
        raise SystemExit("Saison %s introuvable pour competition_id=%s"
                         % (season, COMPETITION_ID))
    return int(hit.iloc[0].season_id)


# --------------------------------------------------------------- extraction match

def build_match(ev):
    """DataFrame d'événements d'un match -> liste d'événements compacts."""
    ev = ev.copy()
    ev["_s"] = ev["timestamp"].map(ts_seconds)
    ev = ev[ev["_s"].notna()]
    ev = ev[ev["period"].isin(PERIODS)]
    # ordre chronologique strict
    sort_cols = [c for c in ("period", "minute", "second", "index") if c in ev.columns]
    ev = ev.sort_values(sort_cols)

    rows = [r for _, r in ev.iterrows()]
    out = []
    periods_seen = set()

    # ---- possessions : bornes et équipe
    poss = {}
    for r in rows:
        pid = val(r, "possession")
        if pid is None:
            continue
        pid = int(pid)
        p = int(val(r, "period", 0))
        s = float(r["_s"])
        d = poss.get(pid)
        if d is None:
            poss[pid] = {"team": val(r, "possession_team", ""), "p": p,
                         "s": s, "e": s, "n": 1}
        else:
            # une possession ne devrait pas franchir une période ; on la coupe si ça arrive
            if p == d["p"]:
                d["e"] = max(d["e"], s)
                d["n"] += 1

    for pid in sorted(poss):
        d = poss[pid]
        if not d["team"]:
            continue
        periods_seen.add(d["p"])
        out.append({"k": "pos", "team": d["team"], "p": d["p"],
                    "s": round(d["s"], 2), "e": round(d["e"], 2), "n": d["n"]})

    # ---- passes indexées par possession (pour la chaîne après un 6m)
    by_poss = {}
    for i, r in enumerate(rows):
        pid = val(r, "possession")
        if pid is None:
            continue
        by_poss.setdefault(int(pid), []).append(i)

    seen_kickoff = set()

    for i, r in enumerate(rows):
        typ = val(r, "type", "")
        team = val(r, "team", "")
        p = int(val(r, "period", 0))
        s = round(float(r["_s"]), 2)
        if not team or p not in PERIODS:
            continue
        periods_seen.add(p)

        # ---- coup d'envoi : 1re passe de chaque période en play_pattern From Kick Off
        if (typ == "Pass" and val(r, "play_pattern", "") == "From Kick Off"
                and p not in seen_kickoff):
            seen_kickoff.add(p)
            out.append({"k": "ko", "team": team, "p": p, "s": s})

        # ---- six mètres
        if typ == "Pass" and val(r, "pass_type", "") == "Goal Kick":
            pid = val(r, "possession")
            pe = s
            nxt = []
            if pid is not None:
                pid = int(pid)
                d = poss.get(pid)
                if d and d["p"] == p:
                    pe = round(d["e"], 2)
                for j in by_poss.get(pid, []):
                    if j <= i:
                        continue
                    rj = rows[j]
                    if val(rj, "type", "") != "Pass" or val(rj, "team", "") != team:
                        continue
                    lj = pass_length_m(rj)
                    if lj is not None:
                        nxt.append(lj)
                    if len(nxt) >= MAX_NXT:
                        break
            out.append({"k": "gk", "team": team, "p": p, "s": s,
                        "pe": pe, "len": pass_length_m(r), "nxt": nxt})

        # ---- tirs
        if typ == "Shot":
            xg = val(r, "shot_statsbomb_xg")
            out.append({
                "k": "sh", "team": team, "p": p, "s": s,
                "xg": round(float(xg), 3) if xg is not None else None,
                "o": val(r, "shot_outcome", "") or "",
                "pen": val(r, "shot_type", "") == "Penalty",
                "pl": val(r, "player", "") or "",
            })

        # ---- centres
        if typ == "Pass" and bool(val(r, "pass_cross", False)):
            out.append({"k": "cr", "team": team, "p": p, "s": s,
                        "o": val(r, "pass_outcome", "") or "",
                        "pl": val(r, "player", "") or ""})

        # ---- csc : StatsBomb crée "Own Goal Against" (équipe fautive)
        #      et "Own Goal For" (équipe qui en profite). On garde le "For".
        if typ == "Own Goal For":
            out.append({"k": "og", "team": team, "p": p, "s": s,
                        "pl": val(r, "player", "") or ""})

    out.sort(key=lambda e: (e["p"], e["s"], e["k"]))
    return out, sorted(periods_seen)


# ----------------------------------------------------------------------- main

def main():
    args = [a for a in sys.argv[1:]]
    force = "--force" in args
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
        args = [a for a in args if a != "--limit" and not a.isdigit()]
    args = [a for a in args if not a.startswith("--")]

    season = args[0] if args else os.environ.get("SEASON", CURRENT_SEASON)
    season_id = resolve_season_id(season)
    outdir = "sc" if season == CURRENT_SEASON else "sc_%s" % season
    os.makedirs(outdir, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("Saison %s (season_id=%s) -> %s/" % (season, season_id, outdir))

    matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)
    matches = matches.sort_values(["match_week", "match_date"])

    index = []
    done = skipped = failed = 0

    for _, m in matches.iterrows():
        mid = int(m["match_id"])
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        hs, as_ = m.get("home_score"), m.get("away_score")
        score = ("%d-%d" % (int(hs), int(as_))) if hs == hs and as_ == as_ else ""
        rnd = m.get("match_week")
        rnd = int(rnd) if rnd == rnd and rnd is not None else None
        date = str(m.get("match_date", ""))[:10]

        path = os.path.join(outdir, "sc_%d.json" % mid)
        entry = {"match_id": mid, "date": date, "round": rnd,
                 "home": home, "away": away, "score": score}

        if os.path.exists(path) and not force:
            index.append(entry)
            skipped += 1
            continue

        if limit is not None and done >= limit:
            if os.path.exists(path):
                index.append(entry)
            continue

        try:
            ev = sb.events(match_id=mid)
        except Exception as exc:                       # match non joué / indispo
            print("  !! %s %s-%s : %s" % (mid, home, away, exc))
            failed += 1
            continue

        if ev is None or len(ev) == 0:
            failed += 1
            continue

        try:
            evs, periods = build_match(ev)
        except Exception as exc:
            print("  !! %s parsing : %s" % (mid, exc))
            failed += 1
            continue

        doc = {
            "match_id": mid, "competition": "Ligue 2", "season": season,
            "season_id": season_id, "date": date, "round": rnd,
            "home": home, "away": away, "score": score,
            "teams": [home, away], "periods": periods,
            "updated": now, "ev": evs,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

        index.append(entry)
        done += 1
        print("  ok  %-9s J%-3s %-22s %-5s %-22s  %4d év." %
              (mid, rnd if rnd else "?", home, score, away, len(evs)))

    index.sort(key=lambda e: (e["round"] or 99, e["date"], e["home"]))
    with open(os.path.join(outdir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"competition": "Ligue 2", "season": season,
                   "season_id": season_id, "updated": now,
                   "matches": index}, f, ensure_ascii=False, indent=1)

    print("\n%d générés, %d déjà présents, %d échecs — %d matchs à l'index."
          % (done, skipped, failed, len(index)))


if __name__ == "__main__":
    main()
