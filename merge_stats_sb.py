#!/usr/bin/env python3
# Ecrase UNIQUEMENT les buts / passes decisives de ligue2.json avec les donnees
# StatsBomb (player_season_stats). Tout le reste (noms, photos, numeros, drapeaux,
# postes, taille, age, logos) est laisse strictement intact : ce fichier est
# construit par fetch_api.py (FotMob) + photos_lfp.json et ne bouge pas ici.
#
# Usage Actions :
#   SB_USERNAME, SB_PASSWORD, SB_COMP_ID, SB_SEASON_ID en env
#   python merge_stats_sb.py
# Hors-ligne (mise au point, sans API) :
#   python merge_stats_sb.py --sample dump_player_stats.json
#   python merge_stats_sb.py --dump dump_player_stats.json   (sauve le brut StatsBomb)

import os, sys, json, unicodedata, datetime, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "ligue2.json")

COMP_ID = os.environ.get("SB_COMP_ID", "8").strip()
SEASON_ID = os.environ.get("SB_SEASON_ID", "318").strip()

# Noms d equipes StatsBomb -> cles de ligue2.json (reprise de fetch_statsbomb.py)
TEAM_NAME_MAP = {
    "Amiens": "Amiens",
    "Bastia": "SC Bastia",
    "Clermont Foot": "Clermont Foot",
    "Dunkerque": "Dunkerque",
    "FC Annecy": "Annecy FC",
    "Grenoble Foot": "Grenoble",
    "Guingamp": "Guingamp",
    "Le Mans": "Le Mans",
    "Montpellier": "Montpellier",
    "Nancy": "Nancy",
    "Pau": "Pau",
    "Red Star FC": "Red Star",
    "Rodez": "Rodez",
    "Saint-Étienne": "Saint-Etienne",
    "Stade Lavallois": "Laval",
    "Stade de Reims": "Reims",
    "Troyes": "Troyes",
    "US Boulogne": "Boulogne",
}

STOP = {"fc", "as", "sc", "ac", "us", "sco", "ogc", "rc", "stade", "football", "club"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    for ch in "-_.'":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def fnum(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN -> None
    except Exception:
        return None


def resolve_team(sb_team, keys, nindex):
    if sb_team in TEAM_NAME_MAP and TEAM_NAME_MAP[sb_team] in keys:
        return TEAM_NAME_MAP[sb_team]
    n = norm(sb_team)
    if n in nindex:
        return nindex[n]
    toks = [t for t in n.split() if t not in STOP]
    best, score = None, 0
    for ck, cn in nindex.items():
        ctoks = [t for t in ck.split() if t not in STOP]
        inter = len(set(toks) & set(ctoks))
        if inter > score:
            best, score = cn, inter
        elif score == 0 and ck and (ck in n or n in ck):
            best = cn
    return best


def player_index(squad):
    """Index d un effectif : nom complet normalise, nom court, dernier token."""
    idx = {}
    for p in squad:
        for key in (norm(p.get("fullname")), norm(p.get("name"))):
            if key:
                idx.setdefault(key, p)
                last = key.split()[-1]
                idx.setdefault(last, p)
    return idx


def match_player(idx, full):
    n = norm(full)
    if not n:
        return None
    if n in idx:
        return idx[n]
    toks = n.split()
    # nom de famille = tout sauf le prenom, puis dernier token
    for cand in (" ".join(toks[1:]), toks[-1]):
        if cand and cand in idx:
            return idx[cand]
    for k, p in idx.items():
        if len(k) >= 4 and (k in n or n in k):
            return p
    return None


def totals(r):
    """Buts / passes decisives en cumule a partir des per-90 StatsBomb."""
    n90 = fnum(r.get("player_season_90s_played"))
    if n90 is None:
        mins = fnum(r.get("player_season_minutes"))
        n90 = mins / 90.0 if mins else None
    g90 = fnum(r.get("player_season_goals_90"))
    a90 = fnum(r.get("player_season_assists_90"))
    g = int(round(g90 * n90)) if (g90 is not None and n90) else 0
    a = int(round(a90 * n90)) if (a90 is not None and n90) else 0
    mins = fnum(r.get("player_season_minutes"))
    return g, a, (int(mins) if mins is not None else None)


def fetch_rows(sample_path, dump_path):
    if sample_path:
        with open(sample_path, encoding="utf-8") as f:
            rows = json.load(f)
        print(f"[sample] {len(rows)} lignes depuis {sample_path}")
        return rows
    if not COMP_ID or not SEASON_ID:
        sys.exit("ERREUR: SB_COMP_ID / SB_SEASON_ID manquants (et pas de --sample).")
    from statsbombpy import sb
    df = sb.player_season_stats(competition_id=int(COMP_ID), season_id=int(SEASON_ID))
    rows = df.to_dict(orient="records")
    print(f"[API] {len(rows)} joueurs (comp {COMP_ID}, saison {SEASON_ID})")
    if dump_path:
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, default=str)
        print(f"[dump] brut sauve -> {dump_path}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample")
    ap.add_argument("--dump")
    ap.add_argument("--json", default=JSON_PATH)
    args = ap.parse_args()

    with open(args.json, encoding="utf-8") as f:
        data = json.load(f)
    teams = data.get("teams", {})
    if not teams:
        sys.exit("ERREUR: ligue2.json sans equipes.")

    rows = fetch_rows(args.sample, args.dump)

    keys = list(teams)
    nindex = {norm(k): k for k in keys}
    indexes = {k: player_index(v.get("squad", [])) for k, v in teams.items()}

    # remise a zero : un joueur absent des donnees SB n a pas joue
    for t in teams.values():
        for p in t.get("squad", []):
            p["g"] = 0
            p["a"] = 0

    hit, miss_team, miss_player = 0, set(), []
    for r in rows:
        sb_team = r.get("team_name") or r.get("team") or ""
        canon = resolve_team(sb_team, keys, nindex)
        if not canon:
            miss_team.add(sb_team)
            continue
        full = r.get("player_name") or ""
        p = match_player(indexes[canon], full)
        if not p:
            g, a, _ = totals(r)
            if g or a:  # on ne signale que les joueurs qui ont marque/passe
                miss_player.append(f"{canon} / {full} (G{g} A{a})")
            continue
        g, a, mins = totals(r)
        p["g"], p["a"] = g, a
        if mins is not None:
            p["mins"] = mins
        if r.get("player_id") is not None:
            p["sbId"] = r.get("player_id")
        hit += 1

    data["source"] = "FotMob (effectifs) + LFP (photos) + StatsBomb (buts/passes)"
    data["statsSource"] = f"StatsBomb comp {COMP_ID} saison {SEASON_ID}"
    data["statsUpdated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    tg = sum(p.get("g") or 0 for t in teams.values() for p in t.get("squad", []))
    ta = sum(p.get("a") or 0 for t in teams.values() for p in t.get("squad", []))
    print(f"[ok] {hit} joueurs apparies | total ligue : {tg} buts, {ta} passes -> {args.json}")
    if miss_team:
        print("[!] equipes StatsBomb non mappees (a ajouter dans TEAM_NAME_MAP) :")
        for t in sorted(miss_team):
            print("    -", t)
    if miss_player:
        print(f"[!] {len(miss_player)} buteurs/passeurs StatsBomb non apparies :")
        for m in miss_player[:40]:
            print("    -", m)


if __name__ == "__main__":
    main()
