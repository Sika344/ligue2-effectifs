#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Récupère les effectifs Ligue 2 (API-Football) -> ligue2.json. Écrit toujours _debug.json."""
import os, sys, json, time, traceback, requests

KEY    = os.environ.get("API_FOOTBALL_KEY", "")
SEASON = int(os.environ.get("SEASON", "2024"))
LEAGUE = int(os.environ.get("LEAGUE", "62"))      # 62 = Ligue 2
BASE   = "https://v3.football.api-sports.io"
H      = {"x-apisports-key": KEY}
SLEEP  = 7

POS_MAP = {"Goalkeeper":"GK","Defender":"DEF","Midfielder":"MID","Attacker":"ATT"}
NAT2CC = {
 "France":"FR","Cameroon":"CM","Senegal":"SN","Mali":"ML","Ivory Coast":"CI","Morocco":"MA",
 "Algeria":"DZ","Tunisia":"TN","Guinea":"GN","Guinea-Bissau":"GW","Nigeria":"NG","Ghana":"GH",
 "Congo":"CG","Congo DR":"CD","DR Congo":"CD","Gabon":"GA","Burkina Faso":"BF","Cape Verde Islands":"CV",
 "Cape Verde":"CV","Comoros":"KM","Madagascar":"MG","Angola":"AO","Benin":"BJ","Togo":"TG",
 "Mauritania":"MR","Chad":"TD","Niger":"NE","Brazil":"BR","Argentina":"AR","Colombia":"CO",
 "Uruguay":"UY","Chile":"CL","Portugal":"PT","Spain":"ES","Serbia":"RS","Croatia":"HR","Albania":"AL",
 "Switzerland":"CH","Belgium":"BE","Netherlands":"NL","Germany":"DE","Italy":"IT","England":"GB",
 "Scotland":"GB","Wales":"GB","Ireland":"IE","Northern Ireland":"GB","Turkey":"TR","Greece":"GR",
 "Poland":"PL","Romania":"RO","Czech Republic":"CZ","Austria":"AT","Denmark":"DK","Sweden":"SE",
 "Norway":"NO","Finland":"FI","Lebanon":"LB","Israel":"IL","Japan":"JP","South Korea":"KR","USA":"US",
 "Canada":"CA","Armenia":"AM","Georgia":"GE","Kosovo":"XK","North Macedonia":"MK","Haiti":"HT",
 "Bosnia and Herzegovina":"BA","Montenegro":"ME","Slovenia":"SI","Slovakia":"SK","Ukraine":"UA",
 "Equatorial Guinea":"GQ","Jamaica":"JM","Gambia":"GM",
}
def flag(nat):
    cc=NAT2CC.get(nat)
    if not cc or len(cc)!=2: return "\U0001F3F3"
    return "".join(chr(0x1F1E6+ord(c)-ord("A")) for c in cc.upper())

def get(path, **params):
    for _ in range(4):
        try:
            r=requests.get(f"{BASE}/{path}",headers=H,params=params,timeout=30)
        except requests.RequestException:
            time.sleep(SLEEP*3); continue
        if r.status_code==429: time.sleep(60); continue
        if r.status_code!=200: time.sleep(SLEEP*2); continue
        return r.json()
    return {"response":[], "paging":{"current":1,"total":1}, "results":0, "errors":["max_retries"]}

diag={"season":SEASON,"league":LEAGUE,"key_present":bool(KEY),"key_len":len(KEY)}
data={}
try:
    tr=get("teams", league=LEAGUE, season=SEASON); time.sleep(SLEEP)
    diag["teams_results"]=tr.get("results"); diag["teams_errors"]=tr.get("errors")
    teams=tr.get("response",[])
    diag["teams_sample"]=[e["team"]["name"] for e in teams[:5]]
    if teams:
        tid=teams[0]["team"]["id"]
        pr0=get("players", team=tid, season=SEASON, page=1); time.sleep(SLEEP)
        diag["players_sample_results"]=pr0.get("results"); diag["players_sample_errors"]=pr0.get("errors")
        diag["players_paging"]=pr0.get("paging")

    for entry in teams:
        t=entry["team"]; tid=t["id"]; tname=t["name"]; logo=t.get("logo")
        numbers={}
        sq=get("players/squads", team=tid); time.sleep(SLEEP)
        for blk in sq.get("response",[]):
            for p in blk.get("players",[]): numbers[p["id"]]=p.get("number")
        players=[]; page=1
        while True:
            pr=get("players", team=tid, season=SEASON, page=page); time.sleep(SLEEP)
            for it in pr.get("response",[]):
                pl=it.get("player",{}) or {}
                st=(it.get("statistics") or [{}])[0] or {}
                g=st.get("games") or {}
                h=pl.get("height")
                if h: h=h.replace("\u00a0"," ").replace(" cm","").strip()
                players.append({"num":numbers.get(pl.get("id")) or "?",
                    "name":(pl.get("lastname") or pl.get("name") or "").upper(),
                    "flag":flag(pl.get("nationality")),"nat":pl.get("nationality"),
                    "height":h,"age":pl.get("age"),
                    "pos":POS_MAP.get(g.get("position"),"MID"),"photo":pl.get("photo"),
                    "m":g.get("appearences") or 0,"t":g.get("lineups") or 0})
            pg=pr.get("paging") or {}
            if pg.get("current",1)>=pg.get("total",1): break
            page+=1
        order={"GK":0,"DEF":1,"MID":2,"ATT":3}
        players.sort(key=lambda p:(order.get(p["pos"],9), int(p["num"]) if str(p["num"]).isdigit() else 999))
        data[tname]={"logo":logo,"squad":players}
    diag["teams_built"]=len(data)
    diag["players_total"]=sum(len(v["squad"]) for v in data.values())
except Exception as e:
    diag["exception"]=repr(e); diag["traceback"]=traceback.format_exc()

json.dump(diag, open("_debug.json","w"), ensure_ascii=False, indent=2)
if data:
    payload={"season":SEASON,"updated":time.strftime("%Y-%m-%d %H:%M UTC",time.gmtime()),"teams":data}
    json.dump(payload, open("ligue2.json","w"), ensure_ascii=False, indent=2)
    print(f"OK {len(data)} équipes / {diag.get('players_total')} joueurs")
else:
    print("Aucune donnée — voir _debug.json")
