#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Récupère les effectifs de Ligue 2 depuis API-Football et écrit ligue2.json.
Tourne sur GitHub Actions (la clé arrive via la variable d'env API_FOOTBALL_KEY).
Plan gratuit -> saisons 2022 à 2024 uniquement.
"""
import os, sys, json, time, requests

KEY    = os.environ["API_FOOTBALL_KEY"]
SEASON = int(os.environ.get("SEASON", "2024"))
LEAGUE = 62                              # 62 = Ligue 2
BASE   = "https://v3.football.api-sports.io"
H      = {"x-apisports-key": KEY}
SLEEP  = 4                               # throttle (plan free ~10 req/min)

POS_MAP = {"Goalkeeper": "GK", "Defender": "DEF", "Midfielder": "MID", "Attacker": "ATT"}

# nationalité (nom anglais renvoyé par l'API) -> code ISO-2, converti en emoji drapeau
NAT2CC = {
    "France":"FR","Cameroon":"CM","Senegal":"SN","Mali":"ML","Ivory Coast":"CI",
    "Morocco":"MA","Algeria":"DZ","Tunisia":"TN","Guinea":"GN","Guinea-Bissau":"GW",
    "Nigeria":"NG","Ghana":"GH","Congo":"CG","Congo DR":"CD","DR Congo":"CD",
    "Gabon":"GA","Burkina Faso":"BF","Cape Verde Islands":"CV","Cape Verde":"CV",
    "Comoros":"KM","Madagascar":"MG","Angola":"AO","Benin":"BJ","Togo":"TG",
    "Mauritania":"MR","Chad":"TD","Central African Republic":"CF","Niger":"NE",
    "Brazil":"BR","Argentina":"AR","Colombia":"CO","Uruguay":"UY","Chile":"CL",
    "Portugal":"PT","Spain":"ES","Serbia":"RS","Croatia":"HR","Albania":"AL",
    "Switzerland":"CH","Belgium":"BE","Netherlands":"NL","Germany":"DE","Italy":"IT",
    "England":"GB","Scotland":"GB","Wales":"GB","Ireland":"IE","Northern Ireland":"GB",
    "Turkey":"TR","Greece":"GR","Poland":"PL","Romania":"RO","Czech Republic":"CZ",
    "Austria":"AT","Denmark":"DK","Sweden":"SE","Norway":"NO","Finland":"FI",
    "Lebanon":"LB","Israel":"IL","Japan":"JP","South Korea":"KR","USA":"US",
    "Canada":"CA","Armenia":"AM","Georgia":"GE","Kosovo":"XK","North Macedonia":"MK",
    "Bosnia and Herzegovina":"BA","Montenegro":"ME","Slovenia":"SI","Slovakia":"SK",
    "Ukraine":"UA", "Russia":"RU", "Haiti":"HT", "Jamaica":"JM", "Equatorial Guinea":"GQ",
}

def flag(nat):
    cc = NAT2CC.get(nat)
    if not cc or len(cc) != 2:
        return "\U0001F3F3"  # drapeau blanc par défaut
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc.upper())

def get(path, **params):
    """GET avec retries + backoff sur 429 (rate limit)."""
    for attempt in range(4):
        try:
            r = requests.get(f"{BASE}/{path}", headers=H, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  ! réseau {path} {params}: {e}", file=sys.stderr); time.sleep(SLEEP*3); continue
        if r.status_code == 429:
            print(f"  ! 429 rate limit sur {path}, pause 60s", file=sys.stderr); time.sleep(60); continue
        if r.status_code != 200:
            print(f"  ! HTTP {r.status_code} sur {path}", file=sys.stderr); time.sleep(SLEEP*2); continue
        j = r.json()
        if j.get("errors"):
            print(f"  ! erreurs API {path} {params}: {j['errors']}", file=sys.stderr)
        return j
    return {"response": [], "paging": {"current": 1, "total": 1}}

def fetch():
    out = {}
    teams_resp = get("teams", league=LEAGUE, season=SEASON); time.sleep(SLEEP)
    teams = teams_resp.get("response", [])
    print(f"{len(teams)} clubs trouvés pour la saison {SEASON}")
    for entry in teams:
        t = entry["team"]
        tid, tname, logo = t["id"], t["name"], t.get("logo")

        # 1) numéros de maillot via /players/squads
        numbers = {}
        sq = get("players/squads", team=tid); time.sleep(SLEEP)
        for blk in sq.get("response", []):
            for p in blk.get("players", []):
                numbers[p["id"]] = p.get("number")

        # 2) bio + stats + photo via /players (paginé)
        players, page = [], 1
        while True:
            pr = get("players", team=tid, season=SEASON, page=page); time.sleep(SLEEP)
            for it in pr.get("response", []):
                pl = it.get("player", {})
                st = (it.get("statistics") or [{}])[0]
                games = st.get("games") or {}
                height = pl.get("height")
                if height:
                    height = height.replace("\u00a0", " ").replace(" cm", "").strip()
                players.append({
                    "num":    numbers.get(pl.get("id")) or "?",
                    "name":   (pl.get("lastname") or pl.get("name") or "").upper(),
                    "flag":   flag(pl.get("nationality")),
                    "nat":    pl.get("nationality"),
                    "height": height,
                    "age":    pl.get("age"),
                    "pos":    POS_MAP.get(games.get("position"), "MID"),
                    "photo":  pl.get("photo"),
                    "m":      games.get("appearences") or 0,
                    "t":      games.get("lineups") or 0,
                })
            paging = pr.get("paging") or {}
            if paging.get("current", 1) >= paging.get("total", 1):
                break
            page += 1
        # tri stable : gardiens d'abord, puis par n° de maillot
        order = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}
        players.sort(key=lambda p: (order.get(p["pos"], 9),
                                    int(p["num"]) if str(p["num"]).isdigit() else 999))
        out[tname] = {"logo": logo, "squad": players}
        print(f"  {tname}: {len(players)} joueurs")
    return out

if __name__ == "__main__":
    data = fetch()
    if not data:
        print("Aucune donnée récupérée — abandon (on ne réécrit pas ligue2.json).", file=sys.stderr)
        sys.exit(1)
    payload = {"season": SEASON, "updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "teams": data}
    with open("ligue2.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"OK — {len(data)} équipes écrites dans ligue2.json")
