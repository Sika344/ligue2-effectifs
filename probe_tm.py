#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sonde : Transfermarkt est-il scrapable depuis un runner GitHub ? -> _debug_tm.json"""
import json, re, time, traceback, requests

S = requests.Session()
S.headers.update({
  "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept-Language":"fr-FR,fr;q=0.9,en;q=0.8",
  "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Upgrade-Insecure-Requests":"1",
})
BASE="https://www.transfermarkt.fr"; SEASON=2024
diag={}

def probe(url):
    r=S.get(url, timeout=30, allow_redirects=True)
    t=r.text
    return {"url":url,"status":r.status_code,"len":len(t),
            "server":r.headers.get("server"),"cf_ray":r.headers.get("cf-ray"),
            "final_url":r.url,
            "title":(re.search(r"<title>(.*?)</title>", t, re.S) or [None,""])[1].strip()[:120]}, t

try:
    url=f"{BASE}/ligue-2/startseite/wettbewerb/FR2/plus/?saison_id={SEASON}"
    meta,html=probe(url)
    diag["competition"]=meta
    ids=sorted(set(re.findall(r"/verein/(\d+)/saison_id", html)), key=int)
    diag["club_count"]=len(ids); diag["club_ids"]=ids[:40]
    diag["html_snippet"]=re.sub(r"\s+"," ",html[:400])
    time.sleep(4)
    if ids:
        kmeta,khtml=probe(f"{BASE}/-/kader/verein/{ids[0]}/saison_id/{SEASON}/plus/1")
        diag["kader"]=kmeta
        pids=sorted(set(re.findall(r"/profil/spieler/(\d+)", khtml)), key=int)
        diag["kader_player_count"]=len(pids); diag["kader_player_ids"]=pids[:25]
except Exception as e:
    diag["exception"]=repr(e); diag["traceback"]=traceback.format_exc()

json.dump(diag, open("_debug_tm.json","w"), ensure_ascii=False, indent=2)
print(json.dumps(diag, ensure_ascii=False)[:1200])
