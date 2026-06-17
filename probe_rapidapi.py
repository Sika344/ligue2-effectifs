#!/usr/bin/env python3
"""Probe econome pour valider l'API RapidAPI 'Free API Live Football Data'.
Tourne sur GitHub Actions (cle = secret RAPIDAPI_KEY). Ecrit probe/*.json + un resume."""
import os, json, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("RAPIDAPI_KEY", "")
HOST = "free-api-live-football-data.p.rapidapi.com"
os.makedirs("probe", exist_ok=True)

def call(path):
    url = f"https://{HOST}/{path}"
    req = urllib.request.Request(url, headers={
        "x-rapidapi-host": HOST,
        "x-rapidapi-key": KEY,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)

def save(name, body):
    with open(f"probe/{name}.json", "w", encoding="utf-8") as f:
        f.write(body)

def probe(name, path):
    st, body = call(path)
    save(name, body)
    print(f"[{st}] {name}  <-  {path}  ({len(body)} octets)")
    return st, body

def jload(body):
    try:
        return json.loads(body)
    except Exception:
        return None

def find_team_ids(obj, found):
    """Cherche recursivement des dicts {id:int, name:str} (candidats equipe)."""
    if isinstance(obj, dict):
        if isinstance(obj.get("id"), int) and isinstance(obj.get("name"), str) and "shortName" not in obj.get("name","")  :
            found.append((obj["id"], obj["name"]))
        for v in obj.values():
            find_team_ids(v, found)
    elif isinstance(obj, list):
        for v in obj:
            find_team_ids(v, found)

print("=== PROBE Ligue 2 (leagueid=110 suppose) ===")
LID = "110"

# 1) Detail de la ligue -> confirme nom/pays
st, body = probe("league_detail_110", f"football-get-league-detail?leagueid={LID}")

# 2) Equipes de la ligue -> ids equipes
st, teams_body = probe("teams_110", f"football-get-list-all-team?leagueid={LID}")
team_id = None
data = jload(teams_body)
if data is not None:
    found = []
    find_team_ids(data, found)
    # dedup en gardant l'ordre
    seen = set(); uniq = []
    for i, n in found:
        if i not in seen:
            seen.add(i); uniq.append((i, n))
    print("Candidats equipes (10 premiers):", uniq[:10])
    if uniq:
        team_id = uniq[0][0]

# 3) Effectif d'une equipe -> CHAMPS DISPO (le point decisif)
if team_id is not None:
    st, sq = probe(f"squad_team_{team_id}", f"football-get-list-all-player?teamid={team_id}")
    if st != 200 or len(sq) < 50:
        # fallback: detail equipe (contient peut-etre l'effectif)
        probe(f"team_detail_{team_id}", f"football-get-team-detail?teamid={team_id}")
else:
    print("!! Pas d'id equipe extrait, effectif non teste ce run")

# 4) Buteurs de la ligue -> forme buts/passes sans appel par joueur
probe("topgoals_110", f"football-get-top-players-by-goals?leagueid={LID}")

print("=== FIN PROBE ===")
