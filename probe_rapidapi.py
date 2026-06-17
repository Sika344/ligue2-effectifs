#!/usr/bin/env python3
import os, json, urllib.request, urllib.error

KEY = os.environ.get("RAPIDAPI_KEY", "")
HOST = "free-api-live-football-data.p.rapidapi.com"
os.makedirs("probe", exist_ok=True)

def call(path):
    url = f"https://{HOST}/{path}"
    req = urllib.request.Request(url, headers={
        "x-rapidapi-host": HOST, "x-rapidapi-key": KEY,
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","replace")
    except Exception as e:
        return -1, str(e)

def probe(name, path):
    st, body = call(path)
    with open(f"probe/{name}.json","w",encoding="utf-8") as f: f.write(body)
    print(f"[{st}] {name} <- {path} ({len(body)} o)")
    try: return st, json.loads(body)
    except Exception: return st, None

def longest_list(obj, need=("name",)):
    best=[]
    def walk(o):
        nonlocal best
        if isinstance(o,list) and o and all(isinstance(x,dict) for x in o):
            if any(all(k in x for k in need) for x in o) and len(o)>len(best): best=o
        if isinstance(o,dict):
            for v in o.values(): walk(v)
        elif isinstance(o,list):
            for v in o: walk(v)
    walk(obj); return best

print("=== STANDINGS L2 (110) ===")
st, data = probe("standing_110", "football-get-standing-all?leagueid=110")
team_id=None
if data is not None:
    rows = longest_list(data, ("name","pts"))
    if not rows: rows = longest_list(data, ("name","id"))
    print(f"{len(rows)} lignes de classement :")
    for r in rows:
        print("   ", r.get("id"), "|", r.get("name"))
    if rows: team_id = rows[0].get("id")

print("\n=== EFFECTIF equipe", team_id, "===")
if team_id is not None:
    st, sq = probe(f"squad_{team_id}", f"football-get-list-player?teamid={team_id}")
    if sq is not None:
        players = longest_list(sq, ("name",))
        print(f"{len(players)} joueurs detectes")
        if players:
            p0=players[0]
            print("CLES joueur:", list(p0.keys()))
            for p in players[:4]:
                print("  --", json.dumps(p, ensure_ascii=False)[:400])
else:
    print("pas d id equipe")
print("=== FIN ===")
