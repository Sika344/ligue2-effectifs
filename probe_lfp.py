#!/usr/bin/env python3
import json, urllib.request, urllib.error, os
os.makedirs("probe", exist_ok=True)
HOST="https://ma-api.ligue1.fr"
HEAD={"User-Agent":"Mozilla/5.0","Accept":"application/json","Origin":"https://ligue1.com","Referer":"https://ligue1.com/"}
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=30) as r:
            return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","replace")[:200]
    except Exception as e:
        return -1, str(e)[:200]
dbg={}
st,body=get(f"{HOST}/championship-clubs/l1_championship_club_2025_64")
dbg["club_status"]=st; dbg["club_len"]=len(body)
pids=[]
try:
    j=json.loads(body); ch=j.get("championships",{})
    for k in ["4"]+[x for x in ch if x!="4"]:
        if ch.get(k,{}).get("playersIds"): pids=ch[k]["playersIds"]; break
except Exception as e: dbg["club_parse_err"]=str(e)
dbg["n_pids"]=len(pids); dbg["pids_sample"]=pids[:3]
if pids:
    st2,body2=get(f"{HOST}/championship-player/{pids[0]}")
    dbg["player_status"]=st2; dbg["player_len"]=len(body2)
    try:
        p=json.loads(body2); c4=p.get("championships",{}).get("4",{})
        dbg["lastName"]=p.get("lastName")
        dbg["bust"]=(c4.get("assets",{}).get("bustPictures",{}) or {}).get("medium")
    except Exception as e: dbg["player_parse_err"]=str(e); dbg["player_body_head"]=body2[:150]
json.dump(dbg,open("probe/lfp_debug.json","w"),ensure_ascii=False,indent=1)
print(json.dumps(dbg,ensure_ascii=False,indent=1))
