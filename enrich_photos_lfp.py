#!/usr/bin/env python3
"""Recupere les photos buste officielles LFP (ma-api.ligue1.fr, public) -> photos_lfp.json.
A lancer ponctuellement (les photos changent peu). Le pipeline FotMob fusionne ce fichier."""
import json, time, unicodedata, urllib.request, urllib.error

HOST = "https://ma-api.ligue1.fr"
# nom FotMob (cle de ligue2.json) -> shortId club LFP
CLUBS = {
    "Troyes":33,"Le Mans":26,"Saint-Etienne":31,"Red Star":29,"Rodez":64,"Reims":41,
    "Annecy FC":1782,"Montpellier":10,"Pau":73,"Dunkerque":48,"Guingamp":24,"Grenoble":38,
    "Clermont Foot":40,"Nancy":11,"Boulogne":84,"Laval":25,"SC Bastia":3,"Amiens":18,
}
HEAD = {"User-Agent":"Mozilla/5.0","Accept":"application/json",
        "Origin":"https://ligue1.com","Referer":"https://ligue1.com/"}

def get(url):
    try:
        req = urllib.request.Request(url, headers=HEAD)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8","replace"))
    except Exception as e:
        print("  err", url, e); return None

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode().lower()
    return "".join(c for c in s if c.isalnum() or c==" ").strip()

out = {}
for name, sid in CLUBS.items():
    cid = f"l1_championship_club_2025_{sid}"
    club = get(f"{HOST}/championship-club/{cid}") or get(f"{HOST}/championship-clubs/{cid}")
    pids = []
    if club:
        ch = club.get("championships", {})
        for chid in ["4"] + [k for k in ch if k != "4"]:
            if chid in ch and ch[chid].get("playersIds"):
                pids = ch[chid]["playersIds"]; break
    entries = []
    for pid in pids:
        p = get(f"{HOST}/championship-player/{pid}")
        time.sleep(0.04)
        if not p: continue
        pch = p.get("championships", {})
        c4 = pch.get("4") or (next(iter(pch.values()), {}) if pch else {})
        assets = c4.get("assets", {}) if isinstance(c4, dict) else {}
        bust = (assets.get("bustPictures") or {}).get("medium")
        if not bust: continue
        country = p.get("country") if isinstance(p.get("country"), dict) else {}
        cc = (p.get("countryShortCode") or p.get("nationality")
              or country.get("shortName") or country.get("code"))
        entries.append({"num": c4.get("jerseyNumber"),
                        "name": (p.get("lastName") or "").upper(),
                        "norm": norm(p.get("lastName")),
                        "foot": p.get("preferredFoot"),
                        "cc": cc,
                        "url": bust})
    out[name] = entries
    print(f"{name:<16} {len(entries)} photos")

json.dump(out, open("photos_lfp.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
tot = sum(len(v) for v in out.values())
print(f"\nphotos_lfp.json : {len(out)} clubs, {tot} photos")
