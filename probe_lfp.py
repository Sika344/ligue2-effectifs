#!/usr/bin/env python3
"""Cherche le feed roster (joueurs + photos) sur le backend public ma-api.ligue1.fr.
Tourne sur GitHub Actions (open internet). Teste des endpoints candidats pour Rodez (club 64)."""
import json, urllib.request, urllib.error, os

os.makedirs("probe", exist_ok=True)
CLUB = "l1_championship_club_2025_64"
HOSTS = ["https://ma-api.ligue1.fr", "https://api.ligue1.fr"]
CANDS = [
    f"/championship-clubs/{CLUB}",
    f"/championship-club/{CLUB}",
    f"/championship-clubs/{CLUB}/squad",
    f"/championship-clubs/{CLUB}/players",
    f"/championship-squad/{CLUB}",
    f"/championship-players/{CLUB}",
    f"/championship-club-squad/{CLUB}",
    f"/championship-club-players/{CLUB}",
    f"/championship-club-detail/{CLUB}",
    f"/championship-clubs-players/{CLUB}",
    f"/championship-club-stats/{CLUB}",
    f"/championship-rosters/{CLUB}",
]

def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Origin": "https://ligue1.com", "Referer": "https://ligue1.com/"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode("utf-8","replace")[:200])
    except Exception as e:
        return -1, str(e)[:200]

found = []
for host in HOSTS:
    for path in CANDS:
        url = host + path
        st, body = get(url)
        hit = st == 200 and ('"name"' in body or '"lastName"' in body or '"players"' in body or 'player' in body.lower())
        mark = "  <<< ROSTER?" if hit else ""
        print(f"[{st}] {url}  ({len(body)} o){mark}")
        if hit:
            fn = f"probe/lfp_{len(found)}.json"
            with open(fn, "w", encoding="utf-8") as f: f.write(body)
            found.append((url, fn))

# test l'URL photo connue (Rodez exemple)
photo = "https://s3.eu-west-3.amazonaws.com/ligue1.image/players/2025/all/player_official_2025_3308_579587-400x300.png"
st, _ = get(photo)
print(f"\nPHOTO test: [{st}] {photo}")
print("\nROSTER trouves:", found)
