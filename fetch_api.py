#!/usr/bin/env python3
"""Pipeline Ligue 2 via 'Free API Live Football Data' (RapidAPI, wrapper FotMob).
1 appel classement (18 equipes) + 1 appel effectif par equipe = ~19 appels/run.
Buts/passes/photos/logos sans cout supplementaire. Sortie: ligue2.json.

Usage:
  RAPIDAPI_KEY=xxx python3 fetch_api.py            # run reel (API)
  python3 fetch_api.py --selftest                  # parsing hors-ligne (probe/*.json)
"""
import os, sys, json, time, datetime, unicodedata, urllib.request, urllib.error

HOST = "free-api-live-football-data.p.rapidapi.com"
LEAGUE = "110"          # Ligue 2 (FotMob)
SEASON = "2025/2026"
POS_GROUP = {"keepers": "GK", "defenders": "DEF", "midfielders": "MID", "attackers": "ATT"}
POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}

# --- drapeaux : ISO3 -> emoji ---
try:
    import pycountry
except Exception:
    pycountry = None

_TAG = {  # nations britanniques (drapeaux a tag)
    "ENG": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "SCO": "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F",
    "WAL": "\U0001F3F4\U000E0067\U000E0062\U000E0077\U000E006C\U000E0073\U000E007F",
}
_ISO3_FIX = {"NIR": "GB", "KOS": "XK", "KVX": "XK"}
def flag(ccode):
    if not ccode:
        return ""
    cc = ccode.upper()
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

def short_name(full):
    full = (full or "").strip()
    if " " in full:
        return full.split(" ", 1)[1].upper()   # retire le prenom, garde le(s) nom(s)
    return full.upper()

def photo(pid):
    return f"https://images.fotmob.com/image_resources/playerimages/{pid}.png" if pid else None

def team_logo(tid):
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{tid}.png" if tid else None

# --- appels API ---
def call(path, tries=4):
    key = os.environ.get("RAPIDAPI_KEY", "")
    url = f"https://{HOST}/{path}"
    for k in range(tries):
        req = urllib.request.Request(url, headers={
            "x-rapidapi-host": HOST, "x-rapidapi-key": key,
            "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            print(f"  retry {k+1}/{tries} {path}: {e}")
            time.sleep(2 * (k + 1))
    return None

def longest_list(obj, need):
    best = []
    def w(o):
        nonlocal best
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o):
            if any(all(k in x for k in need) for x in o) and len(o) > len(best):
                best = o
        if isinstance(o, dict):
            for v in o.values(): w(v)
        elif isinstance(o, list):
            for v in o: w(v)
    w(obj)
    return best

def parse_standings(data):
    rows = longest_list(data, ("name", "pts")) or longest_list(data, ("name", "id"))
    teams = []
    for r in rows:
        tid = r.get("id")
        teams.append({"id": tid, "name": r.get("name"),
                      "logo": r.get("logo") or team_logo(tid)})
    return teams

def parse_squad(data):
    out = []
    try:
        groups = data["response"]["list"]["squad"]
    except Exception:
        groups = longest_list(data, ("title", "members"))
    for grp in groups:
        pos = POS_GROUP.get(grp.get("title"))
        if not pos:
            continue  # coach exclu
        for m in grp.get("members", []):
            out.append({
                "num": m.get("shirtNumber"),
                "name": short_name(m.get("name")),
                "fullname": m.get("name"),
                "flag": flag(m.get("ccode")),
                "ccode": m.get("ccode"),
                "height": m.get("height"),
                "age": m.get("age"),
                "pos": pos,
                "posDesc": m.get("positionIdsDesc"),
                "photo": photo(m.get("id")),
                "g": m.get("goals") or 0,
                "a": m.get("assists") or 0,
            })
    out.sort(key=lambda p: (POS_ORDER.get(p["pos"], 9),
                            p["num"] if isinstance(p["num"], int) else 999))
    return out

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum() or c == " ").strip()

def load_photos():
    try:
        return json.load(open("photos_lfp.json", encoding="utf-8"))
    except Exception:
        return {}

def apply_photos(team_name, squad, photos):
    entries = photos.get(team_name) or []
    if not entries:
        return 0
    by_num = {e["num"]: e for e in entries if isinstance(e.get("num"), int)}
    hit = 0
    for p in squad:
        e = by_num.get(p["num"]) if isinstance(p["num"], int) else None
        if not e:  # repli sur le nom
            pn = _norm(p["name"])
            for cand in entries:
                cn = cand.get("norm") or ""
                if cn and (cn == pn or cn in pn or pn in cn):
                    e = cand; break
        if e and e.get("url"):
            p["photo"] = e["url"]      # photo officielle LFP (buste)
            p["photoLFP"] = True
            if e.get("foot"): p["foot"] = e["foot"]
            hit += 1
    return hit

def build(get_standings, get_squad):
    photos = load_photos()
    teams_meta = parse_standings(get_standings())
    print(f"{len(teams_meta)} equipes" + (f" | photos LFP: {len(photos)} clubs" if photos else " | sans photos LFP"))
    teams = {}
    for t in teams_meta:
        squad = parse_squad(get_squad(t["id"]))
        nph = apply_photos(t["name"], squad, photos)
        print(f"  {t['name']:<16} {len(squad)} joueurs" + (f"  ({nph} photos LFP)" if photos else ""))
        teams[t["name"]] = {"logo": t["logo"], "squad": squad}
    return {"season": SEASON, "updated": datetime.date.today().isoformat(),
            "source": "FotMob (data) + LFP (photos)", "teams": teams}

def main():
    if "--selftest" in sys.argv:
        std = json.load(open("probe/standing_110.json"))
        sq = json.load(open("probe/squad_10242.json"))
        out = build(lambda: std, lambda tid: sq)  # meme effectif pour tous (test parsing)
        t = out["teams"]["Troyes"]
        print("\n--- Troyes (parse test) ---")
        for p in t["squad"][:6]:
            print(f"  {str(p['num']):>3} {p['flag']} {p['name']:<18} {p['posDesc']}  "
                  f"{p['height']}cm {p['age']}a  G{p['g']} A{p['a']}")
        return
    out = build(
        lambda: call(f"football-get-standing-all?leagueid={LEAGUE}"),
        lambda tid: call(f"football-get-list-player?teamid={tid}"),
    )
    with open("ligue2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    n = sum(len(t["squad"]) for t in out["teams"].values())
    print(f"\nligue2.json ecrit : {len(out['teams'])} equipes, {n} joueurs")

if __name__ == "__main__":
    main()
