#!/usr/bin/env python3
"""StatsBomb 360 -> JSON pour la page analytics du site.

Tourne sur GitHub Actions (le host data.statsbombservices.com est injoignable ailleurs).
3 modes :
  probe        : compte la couverture 360 sur la saison + exporte le meilleur match (viewer).
  match <id>   : exporte les frames d un match -> frames_<id>.json (feature 1, freeze-frame).
  leaderboard  : agrege sur toute la saison -> analytics_360.json (feature 2, classements).

Auth : SB_USERNAME / SB_PASSWORD (HTTP basic). Events/matches via statsbombpy.
"""
import os, sys, json, time, argparse, datetime
import requests
from statsbombpy import sb

COMP = int(os.environ.get("COMP_ID", "8"))
SEASON = int(os.environ.get("SEASON_ID", "318"))
BASE = "https://data.statsbombservices.com/api/v2/360-frames/"
AUTH = (os.environ.get("SB_USERNAME", ""), os.environ.get("SB_PASSWORD", ""))
HEAD = {"User-Agent": "ligue2-effectifs/1.0"}

INTEREST = {"Pass", "Shot", "Ball Receipt*", "Ball Receipt"}


def now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def get_frames(match_id):
    """360 v2 brut (avec line_breaking_pass, ball_receipt_in_space, etc.)."""
    try:
        r = requests.get(BASE + str(match_id), auth=AUTH, headers=HEAD, timeout=90)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print("  frames err", match_id, e)
        return None


def matches():
    m = sb.matches(competition_id=COMP, season_id=SEASON)
    out = []
    for _, r in m.iterrows():
        out.append({
            "match_id": int(r["match_id"]),
            "date": str(r.get("match_date", "")),
            "home": r.get("home_team", ""),
            "away": r.get("away_team", ""),
            "hs": r.get("home_score"), "as": r.get("away_score"),
        })
    out.sort(key=lambda x: x["date"])
    return out


def events_index(match_id):
    """event_uuid -> infos actor (nom, equipe, type, minute, location, fin)."""
    try:
        ev = sb.events(match_id=match_id)
    except Exception as e:
        print("  events err", match_id, e)
        return {}
    idx = {}
    cols = ev.columns
    for _, r in ev.iterrows():
        eid = r.get("id")
        if not isinstance(eid, str):
            continue
        end = None
        if "pass_end_location" in cols and isinstance(r.get("pass_end_location"), list):
            end = r.get("pass_end_location")
        elif "shot_end_location" in cols and isinstance(r.get("shot_end_location"), list):
            end = r.get("shot_end_location")[:2]
        idx[eid] = {
            "player": r.get("player") if isinstance(r.get("player"), str) else None,
            "team": r.get("team") if isinstance(r.get("team"), str) else None,
            "type": r.get("type") if isinstance(r.get("type"), str) else None,
            "minute": int(r.get("minute")) if r.get("minute") == r.get("minute") else None,
            "second": int(r.get("second")) if r.get("second") == r.get("second") else None,
            "location": r.get("location") if isinstance(r.get("location"), list) else None,
            "end": end,
        }
    return idx


def frame_count(match_id):
    fr = get_frames(match_id)
    if not fr:
        return 0
    return len(fr)


# ---------------------------------------------------------------- probe
def do_probe(sample=10):
    ms = matches()
    print(f"{len(ms)} matchs en base (comp {COMP} saison {SEASON})")
    # echantillonne les plus recents joues
    played = [m for m in ms if m["hs"] is not None][-sample:]
    cov = []
    best = None
    for m in played:
        n = frame_count(m["match_id"])
        cov.append({**m, "frames": n})
        print(f'  {m["date"]} {m["home"]} vs {m["away"]} -> {n} frames')
        if n and (best is None or n > best["frames"]):
            best = {**m, "frames": n}
        time.sleep(0.3)
    out = {
        "comp": COMP, "season": SEASON, "updated": now(),
        "matches_total": len(ms), "sampled": len(played),
        "coverage": cov, "best_match": best,
    }
    json.dump(out, open("_360_probe.json", "w"), ensure_ascii=False, indent=1)
    print("-> _360_probe.json")
    if best:
        print(f'meilleur match: {best["match_id"]} ({best["frames"]} frames) -> export viewer')
        export_match(best["match_id"])
    else:
        print("AUCUNE frame 360 trouvee sur l echantillon.")
    return out


# ---------------------------------------------------------------- match (feature 1)
def export_match(match_id, cap=140):
    fr = get_frames(match_id)
    if not fr:
        print("pas de 360 pour", match_id)
        return None
    idx = events_index(match_id)
    minfo = next((m for m in matches() if m["match_id"] == int(match_id)), {})
    events = []
    for f in fr:
        uuid = f.get("event_uuid")
        e = idx.get(uuid)
        if not e:
            continue
        typ = e["type"] or ""
        lb = bool(f.get("line_breaking_pass"))
        ris = bool(f.get("ball_receipt_in_space"))
        is_shot = typ == "Shot"
        # on ne garde que les actions parlantes
        if not (lb or ris or is_shot):
            continue
        ff = []
        for p in (f.get("freeze_frame") or []):
            loc = p.get("location") or [None, None]
            ff.append({
                "x": loc[0], "y": loc[1],
                "m": bool(p.get("teammate")),
                "a": bool(p.get("actor")),
                "k": bool(p.get("keeper")),
            })
        events.append({
            "uuid": uuid,
            "min": e["minute"], "sec": e["second"],
            "type": typ, "player": e["player"], "team": e["team"],
            "loc": e["location"], "end": e["end"],
            "lb": lb, "ris": ris,
            "ris_d": f.get("ball_receipt_exceeds_distance"),
            "dnd": f.get("distance_to_nearest_defender"),
            "ngs": f.get("num_defenders_on_goal_side_of_actor"),
            "va": f.get("visible_area"),
            "ff": ff,
        })
    # priorise tirs + line-breaking, limite la taille
    events.sort(key=lambda x: (0 if x["type"] == "Shot" else (1 if x["lb"] else 2),
                               x["min"] or 0))
    events = events[:cap]
    out = {
        "match_id": int(match_id),
        "label": f'{minfo.get("home","")} {minfo.get("hs","")}-{minfo.get("as","")} {minfo.get("away","")}',
        "home": minfo.get("home", ""), "away": minfo.get("away", ""),
        "date": minfo.get("date", ""), "updated": now(),
        "count": len(events), "events": events,
    }
    fn = f"frames_{match_id}.json"
    json.dump(out, open(fn, "w"), ensure_ascii=False)
    print(f"-> {fn} ({len(events)} actions)")
    return out


# ---------------------------------------------------------------- leaderboard (feature 2)
def do_leaderboard(maxn=None):
    ms = [m for m in matches() if m["hs"] is not None]
    if maxn:
        ms = ms[-maxn:]
    lb = {}   # player -> {team, count}
    rs = {}   # player -> {team, count, c5, c10}
    nproc = 0
    nframes = 0
    for m in ms:
        fr = get_frames(m["match_id"])
        if not fr:
            continue
        idx = events_index(m["match_id"])
        nproc += 1
        nframes += len(fr)
        for f in fr:
            e = idx.get(f.get("event_uuid"))
            if not e or not e["player"]:
                continue
            pl, tm = e["player"], e["team"]
            if f.get("line_breaking_pass") and e["type"] == "Pass":
                d = lb.setdefault(pl, {"team": tm, "c": 0}); d["c"] += 1
            if f.get("ball_receipt_in_space"):
                d = rs.setdefault(pl, {"team": tm, "c": 0, "c5": 0, "c10": 0})
                d["c"] += 1
                ex = f.get("ball_receipt_exceeds_distance") or 0
                if ex >= 5: d["c5"] += 1
                if ex >= 10: d["c10"] += 1
        print(f'  {m["date"]} {m["home"]}-{m["away"]} ({len(fr)} frames)  [{nproc}/{len(ms)}]')
        time.sleep(0.25)
    lb_list = sorted(({"player": k, **v} for k, v in lb.items()), key=lambda x: -x["c"])
    rs_list = sorted(({"player": k, **v} for k, v in rs.items()),
                     key=lambda x: (-x["c10"], -x["c5"], -x["c"]))
    out = {
        "comp": COMP, "season": SEASON, "updated": now(),
        "matches_processed": nproc, "frames_total": nframes,
        "line_breaking": lb_list[:60],
        "receptions_space": rs_list[:60],
    }
    json.dump(out, open("analytics_360.json", "w"), ensure_ascii=False, indent=1)
    print(f"-> analytics_360.json ({nproc} matchs, {nframes} frames, "
          f"{len(lb_list)} passeurs, {len(rs_list)} receveurs)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "match", "leaderboard"])
    ap.add_argument("--match_id")
    ap.add_argument("--max", type=int)
    ap.add_argument("--sample", type=int, default=10)
    a = ap.parse_args()
    if a.mode == "probe":
        do_probe(sample=a.sample)
    elif a.mode == "match":
        if not a.match_id:
            sys.exit("--match_id requis")
        export_match(a.match_id)
    elif a.mode == "leaderboard":
        do_leaderboard(maxn=a.max)
