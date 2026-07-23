#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_recoveries.py — zones de RÉCUPÉRATION de balle par équipe, sur TOUTE la saison.
Écrit recoveries.json à la racine du repo. La page rapport-pre-match.html le charge
au runtime (comme losses.json) ; une GitHub Action le régénère => auto-actualisé.

Symétrique de build_losses.py : même grille, même fenêtre, mêmes règles.

Découpage du terrain : grille 12 colonnes x 8 lignes (cases de 10 m x 10 m),
repère StatsBomb (x 0-120, y 0-80). L'équipe qui récupère attaque vers la droite,
donc une récupération dans son propre camp apparaît à GAUCHE de la grille.

CE QUI COMPTE COMME RÉCUPÉRATION — les deux familles combinées :

  A. Actions défensives propres de l'équipe
       - Ball Recovery        (ballon flottant récupéré)
       - Interception         (interception réussie)
       - Duel type "Tackle"   (tacle gagné)
       - actions du GARDIEN   (captation, arrêt bloqué, sortie aérienne) :
         type "Goal Keeper" avec un type d'action de prise de balle

  B. Miroir exact des pertes adverses (mêmes 4 cas que build_losses.py)
       - Dispossessed / Miscontrol de l'adversaire
       - Dribble adverse outcome = Incomplete
       - Passe adverse outcome  = Incomplete
     Les coordonnées adverses sont RETOURNÉES (x -> 120-x, y -> 80-y) pour
     revenir dans le repère de l'équipe qui récupère.
     Une perte adverse déjà couverte par une action défensive de l'équipe au
     même instant n'est pas comptée deux fois (déduplication à 1,5 s près).

EXCLUS :
  - récupérations immédiatement reperdues : drapeau StatsBomb
    `ball_recovery_recovery_failure` à True, ou `interception_outcome` /
    `duel_outcome` traduisant un échec (Lost, Lost In Play, Lost Out)
  - tout événement avec le drapeau `out` à True (ballon sorti du jeu)
  - période 5 (séance de tirs au but)

RÉCUPÉRATIONS À RISQUE ("risk") : une récupération est dite à risque — au sens
offensif, elle débouche sur du danger — si dans les 10 secondes qui suivent
l'équipe produit un TIR en jeu courant ou un CENTRE en jeu courant, dans la
séquence de possession qu'elle ouvre à la récupération. La case retenue est
celle de la RÉCUPÉRATION, pas celle du tir. Une récupération compte pour 1 même
si elle génère plusieurs événements.

RÉCUPÉRATIONS DÉCISIVES ("goal_locs") : sous-ensemble pour lequel un BUT de
l'équipe (Shot avec shot_outcome = "Goal", hors penalty) survient dans la même
fenêtre de 10 s et la même séquence. On stocke la position exacte de la
récupération (et non une case) pour l'afficher en point rouge.

Sortie recoveries.json :
{
  "competition": "Ligue 2", "season": "2025-2026", "season_id": 318,
  "cols": 12, "rows": 8, "updated": "...Z",
  "teams": {
    "<nom StatsBomb>": {
      "matches": N, "total": T, "risk_total": R, "goal_total": G,
      "grid": [[...12 valeurs...] x 8 lignes], # ligne 0 = y 0-10 (haut du terrain)
      "risk": [[...12 valeurs...] x 8 lignes],
      "goal_locs": [[x, y], ...]
    }
  }
}

SAISON (même convention que build_losses.py) :
  - défaut = CURRENT_SEASON -> recoveries.json
  - autre saison -> recoveries_<saison>.json
  - saison passée en argv[1] ou via la variable d'environnement SEASON.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_recoveries.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_recoveries.py 2024-2025
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

COLS = 12                       # 120 m / 12 = cases de 10 m
ROWS = 8                        # 80 m / 8  = cases de 10 m
PITCH_X = 120.0
PITCH_Y = 80.0

RISK_WINDOW = 10.0              # secondes
SHOOTOUT_PERIOD = 5
DEDUP_WINDOW = 1.5              # s — évite de compter 2 fois la même récupération

# --- famille A : actions défensives propres
PASS_LOST = {"Incomplete"}      # pour la famille B (miroir des pertes adverses)

FAIL_OUTCOMES = {"Lost", "Lost In Play", "Lost Out", "Incomplete"}

# actions de gardien qui valent prise de balle
GK_CATCH = {"Collected", "Keeper Sweeper", "Smother", "Punch", "Claim",
            "Shot Saved to Post", "Saved to Post"}


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
    out = "recoveries.json" if label == CURRENT_SEASON else f"recoveries_{label}.json"
    return label, sid, out


def tsec(ts):
    """timestamp StatsBomb "HH:MM:SS.mmm" -> secondes écoulées dans la période."""
    try:
        hh, mm, ss = str(ts).split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None


def truthy(v):
    if v is None:
        return False
    if isinstance(v, float) and v != v:      # NaN
        return False
    return bool(v)


def blank(v):
    return v is None or (isinstance(v, float) and v != v) or v == ""


def xy(loc, flip=False):
    """[x, y] StatsBomb -> couple de flottants, éventuellement retourné."""
    try:
        x = float(loc[0])
        y = float(loc[1])
    except (TypeError, ValueError, IndexError):
        return None
    if x != x or y != y:                     # NaN
        return None
    if flip:
        x, y = PITCH_X - x, PITCH_Y - y
    return x, y


def cell_of(pt):
    """(x, y) -> (ligne, colonne) dans la grille."""
    if pt is None:
        return None
    x, y = pt
    c = min(COLS - 1, max(0, int(x / (PITCH_X / COLS))))
    r = min(ROWS - 1, max(0, int(y / (PITCH_Y / ROWS))))
    return r, c


def is_recovery(ev_type, rec_fail, inter_out, duel_type, duel_out, gk_type, went_out):
    """Famille A : action défensive propre, maîtrisée."""
    if truthy(went_out):
        return False
    if ev_type == "Ball Recovery":
        return not truthy(rec_fail)
    if ev_type == "Interception":
        return blank(inter_out) or str(inter_out) not in FAIL_OUTCOMES
    if ev_type == "Duel":
        if str(duel_type) != "Tackle":
            return False
        return blank(duel_out) or str(duel_out) not in FAIL_OUTCOMES
    if ev_type == "Goal Keeper":
        return (not blank(gk_type)) and str(gk_type) in GK_CATCH
    return False


def is_opp_loss(ev_type, pass_outcome, dribble_outcome, went_out):
    """Famille B : perte adverse, mêmes règles que build_losses.py."""
    if truthy(went_out):
        return False
    if ev_type in ("Dispossessed", "Miscontrol"):
        return True
    if ev_type == "Dribble" and dribble_outcome == "Incomplete":
        return True
    if ev_type == "Pass" and pass_outcome in PASS_LOST:
        return True
    return False


def is_danger(ev_type, shot_type, pass_cross, pass_type):
    """Tir ou centre, en jeu courant uniquement."""
    if ev_type == "Shot":
        return shot_type == "Open Play"
    if ev_type == "Pass" and truthy(pass_cross):
        return blank(pass_type)      # pass_type rempli = corner / cf / touche / 6 m
    return False


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
        for c in ("home_team", "away_team"):
            per_team.setdefault(m[c], set()).add(mid)

    ev_cache = {}

    def events(mid):
        if mid not in ev_cache:
            ev_cache[mid] = sb.events(match_id=mid)
        return ev_cache[mid]

    teams_out = {}
    for team, mids in sorted(per_team.items()):
        grid = [[0] * COLS for _ in range(ROWS)]
        risk = [[0] * COLS for _ in range(ROWS)]
        goal_locs = []
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
            c_per, c_ts = col("period"), col("timestamp")
            c_poss, c_pteam = col("possession"), col("possession_team")
            c_loc, c_out = col("location"), col("out")
            c_recfail = col("ball_recovery_recovery_failure")
            c_interout = col("interception_outcome")
            c_dueltype, c_duelout = col("duel_type"), col("duel_outcome")
            c_gktype = col("goalkeeper_type")
            c_pout, c_dout = col("pass_outcome"), col("dribble_outcome")
            c_stype, c_cross, c_ptype = col("shot_type"), col("pass_cross"), col("pass_type")
            c_sout = col("shot_outcome")
            if c_per is None or c_ts is None or c_poss is None or c_pteam is None:
                continue

            get = lambda s, i: (s.get(i) if s is not None else None)

            # équipe propriétaire de chaque séquence de possession
            poss_team = {}
            for idx in ev.index:
                pi = c_poss.get(idx)
                if pi == pi and pi not in poss_team:
                    poss_team[pi] = c_pteam.get(idx)

            # tirs / centres de l'équipe en jeu courant + ses buts, par séquence
            danger, scored = {}, {}
            for idx in ev.index:
                if c_team.get(idx) != team or c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                t = tsec(c_ts.get(idx))
                if t is None:
                    continue
                stype = get(c_stype, idx)
                if (c_type.get(idx) == "Shot" and stype != "Penalty"
                        and c_sout is not None and c_sout.get(idx) == "Goal"):
                    scored.setdefault(c_poss.get(idx), []).append((c_per.get(idx), t))
                if is_danger(c_type.get(idx), stype, get(c_cross, idx), get(c_ptype, idx)):
                    danger.setdefault(c_poss.get(idx), []).append((c_per.get(idx), t))

            # ---- collecte des récupérations (familles A puis B)
            recs = []          # (période, seconde, x, y, possession)
            for idx in ev.index:
                if c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                own = c_team.get(idx) == team
                if own:
                    ok = is_recovery(c_type.get(idx), get(c_recfail, idx),
                                     get(c_interout, idx), get(c_dueltype, idx),
                                     get(c_duelout, idx), get(c_gktype, idx),
                                     get(c_out, idx))
                else:
                    ok = is_opp_loss(c_type.get(idx), get(c_pout, idx),
                                     get(c_dout, idx), get(c_out, idx))
                if not ok:
                    continue
                pt = xy(get(c_loc, idx), flip=not own)
                if pt is None:
                    continue
                t = tsec(c_ts.get(idx))
                if t is None:
                    continue
                recs.append((c_per.get(idx), t, pt[0], pt[1], c_poss.get(idx), own))

            # déduplication : une perte adverse doublonnant une action propre
            recs.sort(key=lambda r: (r[0] if r[0] is not None else 0, r[1]))
            kept = []
            for r in recs:
                dup = False
                for k in reversed(kept):
                    if k[0] != r[0] or (r[1] - k[1]) > DEDUP_WINDOW:
                        break
                    if abs(k[2] - r[2]) <= 8 and abs(k[3] - r[3]) <= 8:
                        dup = True
                        break
                if not dup:
                    kept.append(r)

            # ---- comptage
            for per0, t0, x, y, p0, _own in kept:
                cell = cell_of((x, y))
                if cell is None:
                    continue
                grid[cell[0]][cell[1]] += 1

                if p0 != p0:
                    continue
                # séquence de l'équipe ouverte à la récupération (ou juste après)
                target = None
                for step in range(0, 3):
                    cand = p0 + step
                    if cand not in poss_team:
                        break
                    if poss_team[cand] == team:
                        target = cand
                        break
                if target is None:
                    continue
                for per1, t1 in danger.get(target, ()):
                    if per1 == per0 and 0 < (t1 - t0) <= RISK_WINDOW:
                        risk[cell[0]][cell[1]] += 1
                        break
                for per1, t1 in scored.get(target, ()):
                    if per1 == per0 and 0 < (t1 - t0) <= RISK_WINDOW:
                        goal_locs.append([round(x, 1), round(y, 1)])
                        break

        total = sum(sum(r) for r in grid)
        rtotal = sum(sum(r) for r in risk)
        teams_out[team] = {"matches": n, "total": total, "risk_total": rtotal,
                           "goal_total": len(goal_locs),
                           "grid": grid, "risk": risk, "goal_locs": goal_locs}
        pm = (total / n) if n else 0
        pct = (100.0 * rtotal / total) if total else 0
        print(f"  ✓ {team}: {n} matchs | {total} récupérations ({pm:.1f}/match) | "
              f"{rtotal} à risque ({pct:.1f}%) | {len(goal_locs)} ayant mené à un but")

    out = {
        "competition": "Ligue 2",
        "season": season_label,
        "season_id": season_id,
        "cols": COLS,
        "rows": ROWS,
        "updated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "teams": teams_out,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(teams_out)} équipes.")


if __name__ == "__main__":
    main()
