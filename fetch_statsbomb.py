#!/usr/bin/env python3
# Construit ligue2.json a partir de StatsBomb player-stats (roster + minutes + buts/passes
# + poste + taille + age), fusionne avec LFP (numero + photo + pied) et l ancien ligue2.json
# (drapeau + logo en repli). Identifiants via env SB_USERNAME / SB_PASSWORD (secrets Actions).
#
# Usage Actions :
#   SB_USERNAME, SB_PASSWORD, SB_COMP_ID, SB_SEASON_ID, [SB_SEASON_LABEL] en env
#   python fetch_statsbomb.py
# Mise au point hors-ligne (sans API) :
#   python fetch_statsbomb.py --sample dump_player_stats.json   (liste de dicts player_season_*)
#   python fetch_statsbomb.py --dump dump_player_stats.json      (sauve le brut pour inspection)

import os, sys, json, unicodedata, datetime, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
LFP_PATH = os.path.join(HERE, "photos_lfp.json")
PREV_PATH = os.path.join(HERE, "ligue2.json")
OUT_PATH = os.path.join(HERE, "ligue2.json")

COMP_ID = os.environ.get("SB_COMP_ID", "").strip()
SEASON_ID = os.environ.get("SB_SEASON_ID", "").strip()
SEASON_LABEL = os.environ.get("SB_SEASON_LABEL", "2025/2026").strip()

# Map team StatsBomb -> cle canonique (a completer une fois les noms SB connus).
# Laisse vide : un appariement flou se charge du reste, et tout non-resolu est logue.
TEAM_NAME_MAP = {
    # "Saint-Etienne": "Saint-Etienne",
    # "Paris FC": "Paris FC",
}

# StatsBomb position_id -> (posDesc compatible roleOf, pos grossier)
POS = {
    1: ("GK", "GK"),
    2: ("RB", "DEF"), 3: ("CB", "DEF"), 4: ("CB", "DEF"), 5: ("CB", "DEF"), 6: ("LB", "DEF"),
    7: ("RWB", "DEF"), 8: ("LWB", "DEF"),
    9: ("CDM", "MID"), 10: ("CDM", "MID"), 11: ("CDM", "MID"),
    12: ("RM", "MID"), 13: ("CM", "MID"), 14: ("CM", "MID"), 15: ("CM", "MID"), 16: ("LM", "MID"),
    17: ("RW", "MID"), 18: ("CAM", "MID"), 19: ("CAM", "MID"), 20: ("CAM", "MID"), 21: ("LW", "MID"),
    22: ("CF", "ATT"), 23: ("ST", "ATT"), 24: ("CF", "ATT"), 25: ("CF", "ATT"),
}
POS_RANK = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}

# --- drapeaux ISO3 -> emoji (repris de fetch_api.py) ---
try:
    import pycountry
except Exception:
    pycountry = None
_TAG = {
    "ENG": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "SCO": "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F",
    "WAL": "\U0001F3F4\U000E0067\U000E0062\U000E0077\U000E006C\U000E0073\U000E007F",
}
_ISO3_FIX = {"NIR": "GB", "KOS": "XK", "KVX": "XK"}
def flag(ccode):
    if not ccode:
        return ""
    cc = str(ccode).upper()
    if cc in _TAG:
        return _TAG[cc]
    a2 = None
    if cc in _ISO3_FIX:
        a2 = _ISO3_FIX[cc]
    elif pycountry:
        c = pycountry.countries.get(alpha_3=cc)
        a2 = c.alpha_2 if c else None
    if not a2 or len(a2) != 2:
        return ""
    return chr(0x1F1E6 + ord(a2[0]) - 65) + chr(0x1F1E6 + ord(a2[1]) - 65)

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    for ch in "-_.'":
        s = s.replace(ch, " ")
    return " ".join(s.split())

def short_name(full):
    full = (full or "").strip()
    if " " in full:
        return full.split(" ", 1)[1].upper()
    return full.upper()

def age_from(birth):
    try:
        y, m, d = str(birth)[:10].split("-")
        b = datetime.date(int(y), int(m), int(d))
        t = datetime.date.today()
        return t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    except Exception:
        return None

def fnum(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN -> None
    except Exception:
        return None

def load_json(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# --- recuperation player-stats (API ou fichier) ---
def fetch_rows(sample_path, dump_path):
    if sample_path:
        rows = load_json(sample_path, [])
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

# --- appariement equipe SB -> cle canonique ---
def build_team_resolver(prev_teams):
    canon = list(prev_teams.keys())
    nindex = {norm(k): k for k in canon}
    def resolve(sb_team):
        if sb_team in TEAM_NAME_MAP:
            return TEAM_NAME_MAP[sb_team]
        n = norm(sb_team)
        if n in nindex:
            return nindex[n]
        # tokens significatifs (retire mots de club generiques)
        stop = {"fc", "as", "sc", "ac", "us", "sco", "ogc", "rc", "stade", "football", "club"}
        toks = [t for t in n.split() if t not in stop]
        best, score = None, 0
        for ck, cn in nindex.items():
            ctoks = [t for t in ck.split() if t not in stop]
            inter = len(set(toks) & set(ctoks))
            if inter > score:
                best, score = cn, inter
            elif score == 0 and (ck in n or n in ck):
                best = cn
        return best  # peut etre None
    return resolve

# --- index LFP / ancien JSON par equipe ---
def index_by_norm(entries, name_key):
    idx = {}
    for e in entries:
        k = norm(e.get(name_key))
        idx.setdefault(k, e)
        lt = k.split()[-1] if k else ""
        idx.setdefault(lt, e)
    return idx

def match(idx, sname):
    n = norm(sname)
    if n in idx:
        return idx[n]
    lt = n.split()[-1] if n else ""
    if lt in idx:
        return idx[lt]
    for k, e in idx.items():
        if k and (k in n or n in k):
            return e
    return None

def build():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample")
    ap.add_argument("--dump")
    args = ap.parse_args()

    prev = load_json(PREV_PATH, {"teams": {}})
    prev_teams = prev.get("teams", {})
    lfp = load_json(LFP_PATH, {})

    rows = fetch_rows(args.sample, args.dump)
    resolve = build_team_resolver(prev_teams)

    teams = {}          # cle canonique -> {logo, squad:[]}
    unmatched_teams = set()

    for r in rows:
        sb_team = r.get("team_name") or r.get("team") or ""
        canon = resolve(sb_team) or sb_team
        if canon == sb_team and sb_team not in prev_teams:
            unmatched_teams.add(sb_team)

        full = r.get("player_name") or ""
        sname = short_name(full)

        # indices LFP / ancien JSON pour cette equipe
        lfp_entries = lfp.get(canon, [])
        prev_squad = prev_teams.get(canon, {}).get("squad", [])
        lfp_idx = index_by_norm(lfp_entries, "norm")
        prev_idx = index_by_norm(prev_squad, "name")

        le = match(lfp_idx, sname)
        pe = match(prev_idx, sname)

        # poste
        pid = r.get("primary_position")
        try:
            pid = int(pid)
        except Exception:
            pid = None
        posDesc, pos = POS.get(pid, (None, None))
        if not pos and pe:
            posDesc, pos = pe.get("posDesc"), pe.get("pos")

        # buts / passes (per90 -> total)
        n90 = fnum(r.get("player_season_90s_played"))
        mins = r.get("player_season_minutes")
        try:
            mins = int(mins)
        except Exception:
            mins = None
        if n90 is None and mins is not None:
            n90 = mins / 90.0
        g90 = fnum(r.get("player_season_goals_90"))
        a90 = fnum(r.get("player_season_assists_90"))
        g = int(round(g90 * n90)) if (g90 is not None and n90) else 0
        a = int(round(a90 * n90)) if (a90 is not None and n90) else 0

        def as_int(v):
            try:
                return int(round(float(v)))
            except Exception:
                return None

        height = r.get("player_height") or (pe.get("height") if pe else None)
        try:
            height = int(height) if height is not None else None
        except Exception:
            height = None
        age = age_from(r.get("birth_date")) or (pe.get("age") if pe else None)

        # numero / photo / pied : LFP prioritaire, repli ancien JSON
        num = le.get("num") if le else (pe.get("num") if pe else None)
        photo = le.get("url") if le else (pe.get("photo") if pe else None)
        photoLFP = bool(le and le.get("url"))
        foot = (le.get("foot") if le else None) or (pe.get("foot") if pe else None)
        # nom d affichage : officiel LFP si dispo
        name = (le.get("name") if le else None) or (pe.get("name") if pe else None) or sname
        # drapeau : ancien JSON (FotMob) en attendant l enrichissement LFP nationalite
        ccode = pe.get("ccode") if pe else None
        fl = (pe.get("flag") if pe else None) or flag(ccode)

        player = {
            "num": num, "name": name, "fullname": full,
            "flag": fl, "ccode": ccode,
            "height": height, "age": age,
            "pos": pos, "posDesc": posDesc,
            "g": g, "a": a,
            "mins": mins, "apps": as_int(r.get("player_season_appearances")),
            "starts": as_int(r.get("player_season_starting_appearances")),
            "photo": photo, "photoLFP": photoLFP, "foot": foot,
            "sbId": r.get("player_id"),
        }
        t = teams.setdefault(canon, {"logo": prev_teams.get(canon, {}).get("logo"), "squad": []})
        t["squad"].append(player)

    # tri GK->DEF->MID->ATT puis par numero
    for t in teams.values():
        t["squad"].sort(key=lambda p: (POS_RANK.get(p.get("pos"), 9),
                                       p["num"] if p.get("num") is not None else 999))

    out = {
        "season": SEASON_LABEL,
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "StatsBomb (stats) + LFP (photos)",
        "teams": teams,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    nb = sum(len(t["squad"]) for t in teams.values())
    print(f"[ok] {len(teams)} clubs, {nb} joueurs -> {OUT_PATH}")
    if unmatched_teams:
        print("[!] equipes SB non mappees (a ajouter dans TEAM_NAME_MAP):")
        for t in sorted(unmatched_teams):
            print("    -", t)

if __name__ == "__main__":
    build()
