#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_rapport.py — compositions des N derniers matchs par club -> rapport_<saison>.json

Alimente le bloc « 5 derniers matchs » de rapport-pre-match.html.

NOMBRE DE MATCHS : on prend les N derniers matchs JOUES de chaque club, avec
N = 5 au maximum. S'il n'y en a qu'un de joue (1re journee), un seul apparait ;
deux apres la 2e journee, et ainsi de suite. La page affiche autant de blocs
qu'elle en recoit, il n'y a donc rien a changer cote HTML.

SORTIE (format attendu par la page) :
{
  "clubs": ["Amiens", ...],
  "byClub": {
    "Amiens": [ {label, comp, date, kickoff, venue,
                 home:{name, short, color, formation, players[], subs[],
                       goals[], manager, score},
                 away:{...}}, ... ]
  }
}

Identifiants StatsBomb via SB_USERNAME / SB_PASSWORD.

USAGE
    python build_rapport.py                 # saison courante -> rapport.json
    python build_rapport.py 2026-2027       # -> rapport_2026-2027.json
    SEASON=2026-2027 python build_rapport.py
"""

import os
import re
import sys
import json
import math
import datetime
import unicodedata

from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {
    "2025-2026": 318,
    "2026-2027": 351,
}
N_MATCHS = 5                  # plafond ; on en prend moins s'il y en a moins
SHOOTOUT_PERIOD = 5
REFS = "_rapport_refs.json"   # couleurs, noms courts, coordonnees par poste
COULEUR_DEFAUT = "#0a1733"


# ---------------------------------------------------------------- utilitaires

def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def val(row, key, default=None):
    v = row.get(key, default)
    if v is None:
        return default
    if isinstance(v, float) and math.isnan(v):
        return default
    return v


def minute_de(row):
    try:
        return int(val(row, "minute", 0)) + (1 if int(val(row, "second", 0)) >= 30 else 0)
    except (TypeError, ValueError):
        return None


def charger_refs():
    """Couleurs/noms courts par club et coordonnees par poste.

    Ces reperes viennent des donnees deja en place : ils fixent l'apparence,
    pas les chiffres. Absents, on retombe sur des valeurs neutres.
    """
    refs = {"couleurs": {}, "postes": {}}
    for chemin in (REFS, os.path.join("deploy", REFS)):
        if os.path.exists(chemin):
            with open(chemin, encoding="utf-8") as f:
                refs = json.load(f)
            break
    par_role = {}
    for code, v in (refs.get("postes") or {}).items():
        if v.get("role"):
            par_role[norm(v["role"])] = (code, v["x"], v["y"])
    return refs.get("couleurs") or {}, par_role


def court(nom):
    """Nom court de secours : 4 premieres lettres, comme les donnees existantes."""
    return (str(nom or "")[:4]).upper()


# ------------------------------------------------------------------ extraction

def numeros_du_match(mid):
    """Numeros de maillot de TOUS les inscrits (titulaires + remplacants).

    Le onze de depart ne donne que les titulaires : sans la feuille de match,
    les entrants sortiraient sans numero.
    """
    out = {}
    try:
        lu = sb.lineups(match_id=mid)
    except Exception:
        return out
    if not isinstance(lu, dict):
        return out
    for df in lu.values():
        try:
            for _, r in df.iterrows():
                nom = r.get("player_name") or r.get("player_nickname")
                num = r.get("jersey_number")
                if nom and num == num and num is not None:
                    out[norm(nom)] = int(num)
        except Exception:
            continue
    return out


def compo_du_match(ev, equipes, couleurs, par_role, numeros=None):
    """Evenements d'un match -> {equipe: bloc home/away}."""
    rows = [r for _, r in ev.iterrows()]
    out = {}

    for nom in equipes:
        joueurs, remplacants, buts = [], [], []
        formation = ""
        sortis, cartons = {}, {}
        entres = {}

        # --- onze de depart : l'evenement « Starting XI » porte la formation
        for r in rows:
            if val(r, "type") != "Starting XI" or val(r, "team") != nom:
                continue
            tac = val(r, "tactics") or {}
            f = tac.get("formation")
            if f:
                formation = "-".join(str(f))
            for p in (tac.get("lineup") or []):
                poste = ((p.get("position") or {}).get("name")) or ""
                code, x, y = par_role.get(norm(poste), (None, 0.5, 0.5))
                joueurs.append({
                    "num": p.get("jersey_number"),
                    "pos": code or "MID",
                    "x": x, "y": y,
                    "name": ((p.get("player") or {}).get("name")) or "",
                    "role": poste,
                })
            break

        # --- remplacements, cartons, buts
        for r in rows:
            if val(r, "period") == SHOOTOUT_PERIOD:
                continue
            if val(r, "team") != nom:
                # but contre son camp inscrit par l'adversaire -> compte pour nous
                if val(r, "type") == "Own Goal Against":
                    pass
                continue
            typ = val(r, "type")
            mn = minute_de(r)

            if typ == "Substitution":
                sortant = val(r, "player") or ""
                entrant = ((val(r, "substitution_replacement") or {}) or {})
                if isinstance(entrant, dict):
                    entrant = entrant.get("name") or ""
                if sortant:
                    sortis[norm(sortant)] = mn
                if entrant:
                    entres[norm(entrant)] = mn

            elif typ in ("Bad Behaviour", "Foul Committed"):
                carte = (val(r, "bad_behaviour_card") or val(r, "foul_committed_card") or "")
                if isinstance(carte, dict):
                    carte = carte.get("name", "")
                who = norm(val(r, "player") or "")
                if "Second Yellow" in str(carte) or "Red" in str(carte):
                    cartons[who] = ("rc", mn)
                elif "Yellow" in str(carte):
                    cartons.setdefault(who, ("yc", mn))

            elif typ == "Shot" and val(r, "shot_outcome") == "Goal":
                buts.append({"player": norm(val(r, "player") or ""), "min": mn})
            elif typ == "Own Goal For":
                buts.append({"player": norm(val(r, "player") or ""), "min": mn})

        # --- numeros : feuille de match, completee par le onze de depart
        numero = dict(numeros or {})
        for j in joueurs:
            if j.get("num") is not None:
                numero[norm(j["name"])] = j["num"]

        for j in joueurs:
            k = norm(j["name"])
            if k in sortis and sortis[k] is not None:
                j["off"] = sortis[k]
            if k in cartons:
                kind, mn = cartons[k]
                j[kind] = mn

        for r in rows:
            if val(r, "team") != nom or val(r, "type") != "Substitution":
                continue
            e = val(r, "substitution_replacement")
            e = e.get("name") if isinstance(e, dict) else e
            if not e:
                continue
            k = norm(e)
            if any(norm(x["name"]) == k for x in remplacants):
                continue
            item = {"num": numero.get(k), "name": e}
            if entres.get(k) is not None:
                item["on"] = entres[k]
            if k in cartons:
                kind, mn = cartons[k]
                item[kind] = mn
            remplacants.append(item)
            numero.setdefault(k, None)

        buts_fmt = []
        for b in buts:
            buts_fmt.append({"num": numero.get(b["player"]), "min": b["min"]})

        infos = couleurs.get(nom) or {}
        out[nom] = {
            "name": nom,
            "short": infos.get("short") or court(nom),
            "color": infos.get("color") or COULEUR_DEFAUT,
            "formation": formation,
            "players": joueurs,
            "subs": remplacants,
            "goals": buts_fmt,
            "manager": "",
            "score": 0,
        }
    return out


# ----------------------------------------------------------------------- main

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    saison = (args[0] if args else os.environ.get("SEASON", "")).strip() or CURRENT_SEASON

    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("!! SB_USERNAME / SB_PASSWORD absents de l'environnement.")
        raise SystemExit(1)

    sid = SEASON_IDS.get(saison)
    if sid is None:
        comps = sb.competitions()
        hit = comps[(comps.competition_id == COMPETITION_ID) & (comps.season_name == saison)]
        if hit.empty:
            print("!! Saison %s introuvable." % saison)
            raise SystemExit(1)
        sid = int(hit.iloc[0].season_id)

    sortie = "rapport.json" if saison == CURRENT_SEASON else "rapport_%s.json" % saison
    print("Saison %s (season_id=%s) -> %s" % (saison, sid, sortie))

    couleurs, par_role = charger_refs()
    print("reperes : %d clubs colores, %d postes cartographies" % (len(couleurs), len(par_role)))

    try:
        matches = sb.matches(competition_id=COMPETITION_ID, season_id=sid)
    except Exception as exc:
        print("!! Impossible de lister les matchs : %s" % exc)
        raise SystemExit(1)

    # --- matchs joues, du plus recent au plus ancien
    joues = []
    for _, m in matches.iterrows():
        hs, as_ = m.get("home_score"), m.get("away_score")
        if hs != hs or as_ != as_ or hs is None or as_ is None:
            continue
        joues.append(m)
    joues.sort(key=lambda m: str(m.get("match_date", "")), reverse=True)
    print("%d match(s) joue(s) sur %d au calendrier" % (len(joues), len(matches)))

    clubs = sorted(set(matches["home_team"]) | set(matches["away_team"]))
    besoin = {}
    for m in joues:
        for c in (m["home_team"], m["away_team"]):
            besoin.setdefault(c, [])
            if len(besoin[c]) < N_MATCHS:
                besoin[c].append(m)

    a_traiter = {}
    for c, ms in besoin.items():
        for m in ms:
            a_traiter[int(m["match_id"])] = m
    print("%d match(s) a analyser pour couvrir les %d clubs" % (len(a_traiter), len(clubs)))

    compos = {}
    for i, (mid, m) in enumerate(sorted(a_traiter.items()), 1):
        try:
            ev = sb.events(match_id=mid)
        except Exception as exc:
            print("  !! %s : %s" % (mid, exc))
            continue
        if ev is None or len(ev) == 0:
            continue
        eq = [m["home_team"], m["away_team"]]
        try:
            blocs = compo_du_match(ev, eq, couleurs, par_role,
                                   numeros_du_match(mid))
        except Exception as exc:
            print("  !! %s parsing : %s" % (mid, exc))
            continue

        hs, as_ = int(m["home_score"]), int(m["away_score"])
        blocs[m["home_team"]]["score"] = hs
        blocs[m["away_team"]]["score"] = as_
        blocs[m["home_team"]]["manager"] = manager_de(m, "home")
        blocs[m["away_team"]]["manager"] = manager_de(m, "away")

        compos[mid] = {
            "label": "%s %d-%d %s" % (m["home_team"], hs, as_, m["away_team"]),
            "comp": "France - Ligue 2",
            "date": str(m.get("match_date", ""))[:10],
            "kickoff": (str(m.get("kick_off", ""))[:5] + " UTC") if m.get("kick_off") == m.get("kick_off") else "",
            "venue": str(m.get("stadium", "") or ""),
            "home": blocs[m["home_team"]],
            "away": blocs[m["away_team"]],
        }
        print("  ok  %-9s %s" % (mid, compos[mid]["label"]), flush=True)

    byClub = {}
    for c in clubs:
        byClub[c] = [compos[int(m["match_id"])] for m in besoin.get(c, [])
                     if int(m["match_id"]) in compos]

    doc = {"clubs": clubs, "byClub": byClub,
           "season": saison, "season_id": sid,
           "updated": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    n = sum(len(v) for v in byClub.values())
    print("\n%s ecrit : %d clubs, %d bloc(s) de match." % (sortie, len(clubs), n))
    vides = [c for c, v in byClub.items() if not v]
    if vides:
        print("clubs sans match : %s" % ", ".join(vides))


def manager_de(m, side):
    v = m.get("%s_managers" % side)
    if isinstance(v, list) and v:
        return v[0].get("name", "") if isinstance(v[0], dict) else str(v[0])
    if isinstance(v, str):
        return v
    return ""


if __name__ == "__main__":
    main()
