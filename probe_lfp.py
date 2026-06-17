#!/usr/bin/env python3
import json, urllib.request, urllib.error, os
os.makedirs("probe", exist_ok=True)
HOST="https://ma-api.ligue1.fr"
PID="l1_championship_player_2025_64_50598"
CANDS=[f"/championship-players/{PID}", f"/championship-player/{PID}",
       f"/championship-player-detail/{PID}", f"/championship-player-card/{PID}",
       f"/championship-player-profile/{PID}", f"/championship-player-identity/{PID}",
       f"/championship-player-info/{PID}", f"/championship-player-stats/{PID}"]
def get(url):
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Accept":"application/json",
        "Origin":"https://ligue1.com","Referer":"https://ligue1.com/"})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8","replace")[:300]
    except Exception as e: return -1, str(e)[:300]

summary=[]
for path in CANDS:
    url=HOST+path; st,body=get(url)
    is_player = st==200 and any(k in body for k in ('"lastName"','"firstName"','"shortName"','"shortOptaId"','"birthDate"','"position"'))
    print(f"[{st}] {url} ({len(body)} o){'  <<< PLAYER' if is_player else ''}")
    summary.append({"url":url,"status":st,"player":is_player,"len":len(body)})
    if is_player:
        with open(f"probe/player_{path.split('/')[1]}.json","w",encoding="utf-8") as f: f.write(body)

# test patterns photo (Rodez optaClub=3308 ; joueur opta inconnu, on teste 579587 connu)
photos={
 "ex_400x300":"https://s3.eu-west-3.amazonaws.com/ligue1.image/players/2025/all/player_official_2025_3308_579587-400x300.png",
}
ps={}
for k,u in photos.items():
    st,_=get(u); ps[k]=st; print(f"PHOTO {k}: [{st}]")
with open("probe/player_summary.json","w") as f: json.dump({"endpoints":summary,"photos":ps},f,indent=1)
