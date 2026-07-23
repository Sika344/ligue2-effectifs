#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_losses.py — zones de pertes de balle par équipe, sur TOUTE la saison.
Écrit losses.json à la racine du repo. La page rapport-pre-match.html le charge
au runtime (comme xg.json) ; une GitHub Action le régénère => auto-actualisé.

Découpage du terrain : grille 12 colonnes x 8 lignes (cases de 10 m x 10 m),
repère StatsBomb (x 0-120, y 0-80) — l'équipe qui a le ballon attaque toujours
vers la droite, donc la grille est déjà orientée « sens du jeu ».

Sont comptées comme PERTES (possession rendue à l'adversaire, BALLON TOUJOURS
EN JEU — le jeu n'est pas arrêté) :
  - Dispossessed                       (dépossédé au duel)
  - Miscontrol                         (mauvais contrôle)
  - Dribble  outcome = Incomplete      (dribble raté)
  - Pass     outcome = Incomplete      (passe interceptée / pour l'adversaire)

Sont donc EXCLUS : passes en touche ou en sortie de but (outcome "Out"), passes
en position de hors-jeu (outcome "Pass Offside"), et tout événement dont le
drapeau StatsBomb `out` vaut True (le ballon a quitté le terrain).

Identifiants StatsBomb via SB_USERNAME / SB_PASSWORD (statsbombpy les lit
automatiquement). Ne jamais committer les identifiants.

PERTES A RISQUE (2e grille, "risk") : une perte est dite a risque si, dans les
10 secondes qui suivent, l'adversaire produit un TIR en jeu courant ou un
CENTRE en jeu courant, ET que cet evenement appartient a la sequence de
possession adverse ouverte juste apres la perte. Les coups de pied arretes
(penalty, coup franc, corner, engagement, touche) sont exclus des deux cotes.
Une perte compte pour 1 meme si elle genere plusieurs evenements. La case
retenue est celle de la PERTE, pas celle du tir ou du centre.

PERTES FATALES ("goal_locs") : sous-ensemble des pertes a risque pour lesquelles
un BUT adverse (Shot avec shot_outcome = "Goal", hors penalty) survient dans la
meme fenetre de 10 s et la meme sequence de possession adverse. On stocke la
position exacte de la perte (et non une case) pour l'afficher en point rouge.

Sortie losses.json :
{
  "competition": "Ligue 2", "season": "2025-2026", "season_id": 318,
  "cols": 6, "rows": 5, "updated": "...Z",
  "teams": {
    "<nom StatsBomb>": {
      "matches": N, "total": T, "risk_total": R, "goal_total": G,
      "grid": [[...12 valeurs...] x 8 lignes], # ligne 0 = y 0-10 (haut du terrain)
      "risk": [[...12 valeurs...] x 8 lignes], # pertes suivies d'un tir/centre <10 s
      "goal_locs": [[x, y], ...]               # position EXACTE des pertes ayant mené
                                               # à un but adverse (repère 120 x 80)
    }
  }
}

SAISON (paramétrable), même convention que build_xg.py :
  - défaut = CURRENT_SEASON -> losses.json
  - autre saison -> losses_<saison>.json  (ex. losses_2024-2025.json)
  - saison passée en argv[1] ou via la variable d'environnement SEASON.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_losses.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_losses.py 2024-2025
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

PASS_LOST = {"Incomplete"}   # ni "Out" ni "Pass Offside" : le jeu serait arrêté

RISK_WINDOW = 10.0           # secondes
SHOOTOUT_PERIOD = 5          # séance de tirs au but : exclue



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
    out = "losses.json" if label == CURRENT_SEASON else f"losses_{label}.json"
    return label, sid, out


def cell_of(loc):
    """[x, y] StatsBomb -> (ligne, colonne) dans la grille, ou None."""
    try:
        x = float(loc[0])
        y = float(loc[1])
    except (TypeError, ValueError, IndexError):
        return None
    if x != x or y != y:            # NaN
        return None
    c = int(x / (PITCH_X / COLS))
    r = int(y / (PITCH_Y / ROWS))
    c = min(COLS - 1, max(0, c))
    r = min(ROWS - 1, max(0, r))
    return r, c


def tsec(ts):
    """timestamp StatsBomb "HH:MM:SS.mmm" -> secondes écoulées dans la période."""
    try:
        hh, mm, ss = str(ts).split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None


def blank(v):
    return v is None or (isinstance(v, float) and v != v) or v == ""


def is_danger(ev_type, shot_type, pass_cross, pass_type):
    """Tir ou centre, en jeu courant uniquement."""
    if ev_type == "Shot":
        return shot_type == "Open Play"
    if ev_type == "Pass" and truthy(pass_cross):
        return blank(pass_type)          # pass_type rempli = corner / cf / touche / 6 m
    return False


def truthy(v):
    """Le drapeau StatsBomb `out` arrive en bool, NaN ou None selon les matchs."""
    if v is None:
        return False
    if isinstance(v, float) and v != v:      # NaN
        return False
    return bool(v)


def is_loss(ev_type, pass_outcome, dribble_outcome, went_out):
    if truthy(went_out):                     # ballon sorti -> jeu arrêté -> exclu
        return False
    if ev_type == "Dispossessed" or ev_type == "Miscontrol":
        return True
    if ev_type == "Dribble" and dribble_outcome == "Incomplete":
        return True
    if ev_type == "Pass" and pass_outcome in PASS_LOST:
        return True
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
        for col in ("home_team", "away_team"):
            per_team.setdefault(m[col], set()).add(mid)

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
            c_per = col("period")
            c_ts = col("timestamp")
            c_poss = col("possession")
            c_pteam = col("possession_team")
            c_pout, c_dout, c_out = col("pass_outcome"), col("dribble_outcome"), col("out")
            c_stype, c_cross, c_ptype = col("shot_type"), col("pass_cross"), col("pass_type")
            c_loc = col("location")
            if c_per is None or c_ts is None or c_poss is None or c_pteam is None:
                continue

            # équipe propriétaire de chaque séquence de possession
            poss_team = {}
            for idx in ev.index:
                pi = c_poss.get(idx)
                if pi == pi and pi not in poss_team:
                    poss_team[pi] = c_pteam.get(idx)

            # tirs / centres adverses en jeu courant, indexés par séquence
            # + buts adverses (pour les pertes fatales)
            danger, scored = {}, {}
            c_sout = col("shot_outcome")
            for idx in ev.index:
                if c_team.get(idx) == team or c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                t = tsec(c_ts.get(idx))
                if t is None:
                    continue
                stype = c_stype.get(idx) if c_stype is not None else None
                if (c_type.get(idx) == "Shot" and stype != "Penalty"
                        and c_sout is not None and c_sout.get(idx) == "Goal"):
                    scored.setdefault(c_poss.get(idx), []).append((c_per.get(idx), t))
                if not is_danger(c_type.get(idx), stype,
                                 c_cross.get(idx) if c_cross is not None else None,
                                 c_ptype.get(idx) if c_ptype is not None else None):
                    continue
                danger.setdefault(c_poss.get(idx), []).append((c_per.get(idx), t))

            for idx in ev.index:
                if c_team.get(idx) != team or c_per.get(idx) == SHOOTOUT_PERIOD:
                    continue
                if not is_loss(c_type.get(idx),
                               c_pout.get(idx) if c_pout is not None else None,
                               c_dout.get(idx) if c_dout is not None else None,
                               c_out.get(idx) if c_out is not None else None):
                    continue
                cell = cell_of(c_loc.get(idx) if c_loc is not None else None)
                if cell is None:
                    continue
                grid[cell[0]][cell[1]] += 1

                t0 = tsec(c_ts.get(idx))
                p0 = c_poss.get(idx)
                if t0 is None or p0 != p0:
                    continue
                # séquence de possession adverse ouverte juste après la perte
                target = None
                for step in range(1, 4):
                    cand = p0 + step
                    if cand not in poss_team:
                        break
                    if poss_team[cand] != team:
                        target = cand
                        break
                if target is None:
                    continue
                per0 = c_per.get(idx)
                for per1, t1 in danger.get(target, ()):
                    if per1 == per0 and 0 < (t1 - t0) <= RISK_WINDOW:
                        risk[cell[0]][cell[1]] += 1
                        break
                for per1, t1 in scored.get(target, ()):
                    if per1 == per0 and 0 < (t1 - t0) <= RISK_WINDOW:
                        loc = c_loc.get(idx) if c_loc is not None else None
                        try:
                            gx, gy = float(loc[0]), float(loc[1])
                        except (TypeError, ValueError, IndexError):
                            break
                        if gx == gx and gy == gy:
                            goal_locs.append([round(gx, 1), round(gy, 1)])
                        break

        total = sum(sum(r) for r in grid)
        rtotal = sum(sum(r) for r in risk)
        teams_out[team] = {"matches": n, "total": total, "risk_total": rtotal,
                           "goal_total": len(goal_locs),
                           "grid": grid, "risk": risk, "goal_locs": goal_locs}
        pm = (total / n) if n else 0
        pct = (100.0 * rtotal / total) if total else 0
        print(f"  ✓ {team}: {n} matchs | {total} pertes ({pm:.1f}/match) | "
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
