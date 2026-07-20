#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_losses.py — zones de pertes de balle par équipe, sur TOUTE la saison.
Écrit losses.json à la racine du repo. La page rapport-pre-match.html le charge
au runtime (comme xg.json) ; une GitHub Action le régénère => auto-actualisé.

Découpage du terrain : grille 6 colonnes x 5 lignes (cases de 20 m x 16 m),
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

Sortie losses.json :
{
  "competition": "Ligue 2", "season": "2025-2026", "season_id": 318,
  "cols": 6, "rows": 5, "updated": "...Z",
  "teams": {
    "<nom StatsBomb>": {
      "matches": N, "total": T,
      "grid": [[...6 valeurs...] x 5 lignes]   # ligne 0 = y 0-16 (haut du terrain)
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

COLS = 6                        # 120 m / 6 = cases de 20 m
ROWS = 5                        # 80 m / 5 = cases de 16 m
PITCH_X = 120.0
PITCH_Y = 80.0

PASS_LOST = {"Incomplete"}   # ni "Out" ni "Pass Offside" : le jeu serait arrêté


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
            own = ev[ev["team"] == team]
            if len(own) == 0:
                continue
            po = own["pass_outcome"] if "pass_outcome" in own.columns else None
            do = own["dribble_outcome"] if "dribble_outcome" in own.columns else None
            oo = own["out"] if "out" in own.columns else None
            for idx, row in own.iterrows():
                t = row.get("type")
                p_out = po.get(idx) if po is not None else None
                d_out = do.get(idx) if do is not None else None
                w_out = oo.get(idx) if oo is not None else None
                if not is_loss(t, p_out, d_out, w_out):
                    continue
                cell = cell_of(row.get("location"))
                if cell is None:
                    continue
                grid[cell[0]][cell[1]] += 1

        total = sum(sum(r) for r in grid)
        teams_out[team] = {"matches": n, "total": total, "grid": grid}
        pm = (total / n) if n else 0
        print(f"  ✓ {team}: {n} matchs | {total} pertes ({pm:.1f}/match)")

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
