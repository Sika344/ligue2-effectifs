#!/usr/bin/env python3
import json, urllib.request, urllib.error, os, time
os.makedirs("probe", exist_ok=True)
HOST="https://ma-api.ligue1.fr"
HEAD={"User-Agent":"Mozilla/5.0","Accept":"application/json","Origin":"https://ligue1.com","Referer":"https://ligue1.com/"}
def get(url,tries=1):
    last=(None,"")
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=30) as r:
                return r.status, r.read().decode("utf-8","replace")
        except urllib.error.HTTPError as e:
            last=(e.code, e.read().decode("utf-8","replace")[:150])
        except Exception as e:
            last=(-1,str(e)[:150])
        time.sleep(1.5*(k+1))
    return last
dbg={}
# 1) reachability via endpoint stats connu stable
s,b=get(f"{HOST}/championship-player-stats/l1_championship_player_2025_64_50598")
dbg["stats_status"]=s; dbg["stats_len"]=len(b)
# 2) clubs avec retries, plusieurs clubs
for cid in ["l1_championship_club_2025_64","l1_championship_club_2025_31","l1_championship_club_2025_10"]:
    s,b=get(f"{HOST}/championship-clubs/{cid}",tries=6)
    npids=0
    try:
        j=json.loads(b); ch=j.get("championships",{})
        for k in ["4"]+[x for x in ch if x!="4"]:
            if ch.get(k,{}).get("playersIds"): npids=len(ch[k]["playersIds"]); break
    except Exception: pass
    dbg[cid]={"status":s,"len":len(b),"npids":npids,"head":b[:120] if s!=200 else "ok"}
json.dump(dbg,open("probe/lfp_debug.json","w"),ensure_ascii=False,indent=1)
print(json.dumps(dbg,ensure_ascii=False,indent=1))
