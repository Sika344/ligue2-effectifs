#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_sportscode.py — timelines événementielles par match, pour export Hudl SportsCode.

Écrit :
    sc/index.json            catalogue des matchs (journée, date, équipes, score)
    sc/sc_<match_id>.json    timeline d'un match

La page `sportscode.html` charge ces JSON au runtime et génère le XML SportsCode
côté navigateur (avec offsets vidéo et seuils réglables par l'utilisateur).

Identifiants StatsBomb via SB_USERNAME / SB_PASSWORD (lus par statsbombpy).
Ne jamais committer les identifiants.

SAISON :
  - défaut = CURRENT_SEASON -> sortie dans sc/
  - autre saison -> sortie dans sc_<saison>/
  - saison passée en argv[1] ou via la variable d'environnement SEASON ("2024-2025").

MODE INCRÉMENTAL (défaut) : un match dont le JSON existe déjà est ignoré.
    --force  régénère tout.
    --limit N  ne traite que N matchs (utile pour tester).

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_sportscode.py
    SB_USERNAME='…' SB_PASSWORD='…' python build_sportscode.py 2024-2025 --force

--------------------------------------------------------------------------------
FORMAT sc_<match_id>.json
--------------------------------------------------------------------------------
{
  "match_id": 3922241,
  "competition": "Ligue 2", "season": "2025-2026",
  "date": "2025-08-09", "round": 1,
  "home": "Amiens", "away": "Troyes", "score": "1-2",
  "teams": ["Amiens", "Troyes"],
  "periods": [1, 2],
  "updated": "2026-07-28T10:00:00Z",
  "ev": [ ... ]
}

Chaque événement porte :
    k    type      ko | gk | pos | sh | cr | og
    team nom StatsBomb de l'équipe concernée
    p    période (1 = 1re MT, 2 = 2e MT, 3/4 = prolongations)
    s    secondes écoulées DEPUIS LE COUP D'ENVOI DE CETTE PÉRIODE

Détail par type :
    ko   coup d'envoi                    -> {k,team,p,s}
    gk   six mètres                      -> {k,team,p,s, pe, len, nxt[]}
             pe   = fin de la possession issue du 6m (s de la période)
             len  = longueur en mètres de la passe de 6m
             nxt  = longueurs des passes suivantes de la même équipe dans la
                    même possession (5 max) -> sert au calcul "short-long"
    pos  possession                      -> {k,team,p,s, e, n}
             e = fin, n = nombre d'événements de la possession
    sh   tir                             -> {k,team,p,s, xg, o, pen, pl}
             o = shot_outcome StatsBomb brut (Goal / Saved / Off T / Blocked / …)
             pen = True si penalty (hors séance de tirs au but, exclue)
    cr   centre                          -> {k,team,p,s, o, pl}
             o = pass_outcome StatsBomb ("" = passe réussie)
    og   but contre son camp             -> {k,team,p,s, pl}
             team = équipe QUI MARQUE (bénéficiaire du csc)
    tin  touche                          -> {k,team,p,s, e, z, cote, pl}
    fk   coup franc                      -> {k,team,p,s, e, z, cote, pl}
    cor  corner                          -> {k,team,p,s, e, z, cote, pl}
             z    = tiers du terrain (Basse / Mediane / Haute)
             cote = Droite / Gauche  (voir Y_BAS_EST_DROITE)
             e    = fin de la possession ouverte par la remise en jeu
    ass  dernière passe avant un tir     -> {k,team,p,s, pl, rec, xg, but}
    pre  avant-dernière passe            -> {k,team,p,s, pl, rec, xg, but}
             rec = destinataire, xg = xG du tir produit, but = True si but
    bu   build-up                        -> {k,team,p,s, e, h, n, xp}
             h  = zone ou demarre la PRESSION adverse :
                  Basse (< 30 m) / Mediane / Haute (30 derniers metres)
                  / "Sans pression" si l'adversaire ne presse jamais
             xp = abscisse de cette premiere pression, repere du constructeur
             s,e = bornes de la possession entiere
    gkbu relance du gardien hors 6 m     -> {k,team,p,s, e, h, len, pl, rec}

Les libellés de lignes SportsCode, durées avant/après et descripteurs sont
entièrement gérés côté HTML : ce script ne fait que fournir la matière brute.
"""

import os
import sys
import json
import math
import datetime

from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318,
    "2026-2027": 351,   # 1re journee jouee le 08/08/2026
}

# StatsBomb : terrain 120 x 80 unités = 105 x 68 mètres
MX = 105.0 / 120.0
MY = 68.0 / 80.0

MAX_NXT = 5          # nb de passes suivantes stockées après un 6m
PERIODS = (1, 2, 3, 4)   # 5 = séance de tirs au but -> exclue


# ---------------------------------------------------------------- géométrie
# StatsBomb : x de 0 (son propre but) à 120 (but adverse), y de 0 à 80.
# Les tiers reprennent le découpage de l'export IQ (Low / Mid / High Third).
TIERS = ((40.0, "Basse"), (80.0, "Mediane"), (1e9, "Haute"))

# SENS LATÉRAL — le seul point que je n'ai pas pu établir avec certitude.
# Ton export IQ range les Y bas à DROITE (médiane 23 en zone Right contre 87 en
# Left, sur 250 passes). Mais rien ne garantit que l'axe Y d'IQ pointe dans le
# même sens que celui des événements bruts, qui sert ici. Si tous tes centres
# ressortent inversés, il suffit de passer cette constante à False : c'est un
# réglage d'une ligne, pas une reprise du code.
Y_BAS_EST_DROITE = True

# ---------------------------------------------------------------- BUILD-UP
# Regle de Geoffrey : ce n'est pas d'ou part la possession qui compte, mais
# OU COMMENCE LA PRESSION ADVERSE, mesuree depuis le but de l'equipe qui
# construit.
#     Basse   : la pression demarre dans les 30 premiers metres
#     Mediane : elle demarre au-dela de 30 m et avant les 30 derniers
#     Haute   : elle demarre dans les 30 derniers metres
#     Sans pression : aucune pression adverse de toute la possession
#
# StatsBomb exprime le terrain en 120 unites de long, en yards. 30 m valent
# donc 32,81 unites -- pas 30. L'approximation ferait basculer des sequences
# d'une categorie a l'autre.
METRE_EN_UNITES = 1.0 / 0.9144
SEUIL_BAS = 30.0 * METRE_EN_UNITES          # 32,81
SEUIL_HAUT = 120.0 - SEUIL_BAS              # 87,19


def zone_pression(x):
    # x exprime dans le sens d'attaque de l'equipe QUI CONSTRUIT
    if x is None:
        return ""
    if x < SEUIL_BAS:
        return "Basse"
    if x < SEUIL_HAUT:
        return "Mediane"
    return "Haute"


def tiers_de(x):
    """Tiers du terrain dans le sens d'attaque de l'équipe qui a le ballon."""
    if x is None:
        return ""
    for borne, nom in TIERS:
        if x < borne:
            return nom
    return "Haute"


def cote_de(y):
    """Côté du terrain. Voir Y_BAS_EST_DROITE ci-dessus."""
    if y is None:
        return ""
    bas = y < 40.0
    return ("Droite" if bas else "Gauche") if Y_BAS_EST_DROITE else ("Gauche" if bas else "Droite")


# ------------------------------------------------------------------ utilitaires

def ts_seconds(timestamp):
    """'00:12:34.567' (relatif au début de la période) -> 754.567"""
    if not isinstance(timestamp, str):
        return None
    try:
        h, m, rest = timestamp.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    except (ValueError, AttributeError):
        return None


def val(row, key, default=None):
    """Accès tolérant à une colonne pandas éventuellement absente ou NaN."""
    v = row.get(key, default)
    if v is None:
        return default
    if isinstance(v, float) and math.isnan(v):
        return default
    return v


def loc_xy(v):
    """[x, y] StatsBomb -> (x, y) ou None."""
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return None
    return None


def pass_length_m(row):
    """Longueur de la passe en mètres, depuis location -> pass_end_location."""
    a = loc_xy(val(row, "location"))
    b = loc_xy(val(row, "pass_end_location"))
    if not a or not b:
        # repli : pass_length StatsBomb est en unités terrain
        pl = val(row, "pass_length")
        if pl is None:
            return None
        try:
            return round(float(pl) * MX, 1)
        except (TypeError, ValueError):
            return None
    dx = (b[0] - a[0]) * MX
    dy = (b[1] - a[1]) * MY
    return round(math.hypot(dx, dy), 1)


def resolve_season_id(season):
    if season in SEASON_IDS:
        return SEASON_IDS[season]
    comps = sb.competitions()
    hit = comps[(comps.competition_id == COMPETITION_ID)
                & (comps.season_name == season)]
    if hit.empty:
        raise SystemExit("Saison %s introuvable pour competition_id=%s"
                         % (season, COMPETITION_ID))
    return int(hit.iloc[0].season_id)


# --------------------------------------------------------------- extraction match

def build_match(ev):
    """DataFrame d'événements d'un match -> liste d'événements compacts."""
    ev = ev.copy()
    ev["_s"] = ev["timestamp"].map(ts_seconds)
    ev = ev[ev["_s"].notna()]
    ev = ev[ev["period"].isin(PERIODS)]
    # ordre chronologique strict
    sort_cols = [c for c in ("period", "minute", "second", "index") if c in ev.columns]
    ev = ev.sort_values(sort_cols)

    rows = [r for _, r in ev.iterrows()]
    out = []
    periods_seen = set()

    # ---- possessions : bornes et équipe
    poss = {}
    for r in rows:
        pid = val(r, "possession")
        if pid is None:
            continue
        pid = int(pid)
        p = int(val(r, "period", 0))
        s = float(r["_s"])
        d = poss.get(pid)
        if d is None:
            poss[pid] = {"team": val(r, "possession_team", ""), "p": p,
                         "s": s, "e": s, "n": 1}
        else:
            # une possession ne devrait pas franchir une période ; on la coupe si ça arrive
            if p == d["p"]:
                d["e"] = max(d["e"], s)
                d["n"] += 1

    # premiere pression ADVERSE de chaque possession, ramenee dans le repere de
    # l'equipe qui construit
    premiere_pression = {}
    for r in rows:
        if val(r, "type", "") != "Pressure":
            continue
        pid = val(r, "possession")
        if pid is None:
            continue
        pid = int(pid)
        d = poss.get(pid)
        if not d or val(r, "team", "") == d["team"]:
            continue                      # pression de l'equipe qui a le ballon : ignoree
        xy = loc_xy(val(r, "location"))
        if not xy:
            continue
        x_constructeur = 120.0 - xy[0]
        if pid not in premiere_pression:
            premiere_pression[pid] = x_constructeur

    for pid in sorted(poss):
        d = poss[pid]
        if not d["team"]:
            continue
        periods_seen.add(d["p"])
        out.append({"k": "pos", "team": d["team"], "p": d["p"],
                    "s": round(d["s"], 2), "e": round(d["e"], 2), "n": d["n"]})

        # ---- Build Up : classe par l'endroit ou la PRESSION ADVERSE demarre.
        #      Piege traite ici : un evenement Pressure appartient a l'equipe
        #      QUI PRESSE, donc ses coordonnees sont dans SON repere. Il faut
        #      les retourner (x -> 120 - x) pour les ramener dans le sens
        #      d'attaque de l'equipe qui construit. Sans ce retournement, Basse
        #      et Haute seraient purement et simplement inversees.
        xp = premiere_pression.get(pid)
        h = zone_pression(xp) if xp is not None else "Sans pression"
        out.append({"k": "bu", "team": d["team"], "p": d["p"],
                    "s": round(d["s"], 2), "e": round(d["e"], 2),
                    "h": h, "n": d["n"],
                    "xp": None if xp is None else round(xp, 1)})

    # ---- passes indexées par possession (pour la chaîne après un 6m)
    by_poss = {}
    for i, r in enumerate(rows):
        pid = val(r, "possession")
        if pid is None:
            continue
        by_poss.setdefault(int(pid), []).append(i)

    # index id -> position dans `rows`, pour remonter de shot_key_pass_id à la
    # passe elle-même. Sans lui, il faudrait balayer tout le match par tir.
    par_id = {}
    for i, r in enumerate(rows):
        v = val(r, "id")
        if v is not None:
            par_id[str(v)] = i

    seen_kickoff = set()

    for i, r in enumerate(rows):
        typ = val(r, "type", "")
        team = val(r, "team", "")
        p = int(val(r, "period", 0))
        s = round(float(r["_s"]), 2)
        if not team or p not in PERIODS:
            continue
        periods_seen.add(p)

        # ---- coup d'envoi : 1re passe de chaque période en play_pattern From Kick Off
        if (typ == "Pass" and val(r, "play_pattern", "") == "From Kick Off"
                and p not in seen_kickoff):
            seen_kickoff.add(p)
            out.append({"k": "ko", "team": team, "p": p, "s": s})

        # ---- six mètres
        if typ == "Pass" and val(r, "pass_type", "") == "Goal Kick":
            pid = val(r, "possession")
            pe = s
            nxt = []
            if pid is not None:
                pid = int(pid)
                d = poss.get(pid)
                if d and d["p"] == p:
                    pe = round(d["e"], 2)
                for j in by_poss.get(pid, []):
                    if j <= i:
                        continue
                    rj = rows[j]
                    if val(rj, "type", "") != "Pass" or val(rj, "team", "") != team:
                        continue
                    lj = pass_length_m(rj)
                    if lj is not None:
                        nxt.append(lj)
                    if len(nxt) >= MAX_NXT:
                        break
            out.append({"k": "gk", "team": team, "p": p, "s": s,
                        "pe": pe, "len": pass_length_m(r), "nxt": nxt})

        # ---- tirs
        if typ == "Shot":
            xg = val(r, "shot_statsbomb_xg")
            out.append({
                "k": "sh", "team": team, "p": p, "s": s,
                "xg": round(float(xg), 3) if xg is not None else None,
                "o": val(r, "shot_outcome", "") or "",
                "pen": val(r, "shot_type", "") == "Penalty",
                "pl": val(r, "player", "") or "",
            })

        # ---- centres, avec le côté d'où part le centre
        if typ == "Pass" and bool(val(r, "pass_cross", False)):
            xy = loc_xy(val(r, "location"))
            out.append({"k": "cr", "team": team, "p": p, "s": s,
                        "o": val(r, "pass_outcome", "") or "",
                        "cote": cote_de(xy[1] if xy else None),
                        "pl": val(r, "player", "") or ""})

        # ---- remises en jeu : touche, coup franc, corner
        #      Une seule ligne par famille, la zone et le côté en descripteurs :
        #      ton export en fait plusieurs lignes, mais leurs définitions
        #      diffèrent d'un cas à l'autre et je préfère te laisser filtrer
        #      plutôt que d'inventer une règle qui ne serait pas la tienne.
        if typ == "Pass":
            pt = val(r, "pass_type", "")
            if pt in ("Throw-in", "Free Kick", "Corner"):
                xy = loc_xy(val(r, "location"))
                pid = val(r, "possession")
                fin = s
                if pid is not None:
                    d = poss.get(int(pid))
                    if d and d["p"] == p:
                        fin = round(d["e"], 2)
                out.append({
                    "k": {"Throw-in": "tin", "Free Kick": "fk", "Corner": "cor"}[pt],
                    "team": team, "p": p, "s": s, "e": fin,
                    "z": tiers_de(xy[0] if xy else None),
                    "cote": cote_de(xy[1] if xy else None),
                    "pl": val(r, "player", "") or "",
                })

        # ---- Implication offensive : dernière et avant-dernière passe
        #      StatsBomb rattache au tir l'identifiant de la passe qui l'a créé.
        #      L'avant-dernière est la passe précédente de la MÊME équipe dans la
        #      MÊME possession : sans ces deux conditions on remonterait à une
        #      passe adverse ou à la séquence d'avant.
        if typ == "Shot" and val(r, "shot_type", "") != "Penalty":
            kid = val(r, "shot_key_pass_id")
            j = par_id.get(str(kid)) if kid is not None else None
            if j is not None:
                rj = rows[j]
                xg = val(r, "shot_statsbomb_xg")
                xgr = round(float(xg), 3) if xg is not None else None
                out.append({"k": "ass", "team": val(rj, "team", "") or team,
                            "p": int(val(rj, "period", p)), "s": round(float(rj["_s"]), 2),
                            "pl": val(rj, "player", "") or "",
                            "rec": val(rj, "pass_recipient", "") or "",
                            "xg": xgr, "but": val(r, "shot_outcome", "") == "Goal"})
                pj = val(rj, "possession")
                tj = val(rj, "team", "")
                for k2 in range(j - 1, -1, -1):
                    rk = rows[k2]
                    if val(rk, "possession") != pj:
                        break
                    if val(rk, "type", "") == "Pass" and val(rk, "team", "") == tj:
                        out.append({"k": "pre", "team": tj,
                                    "p": int(val(rk, "period", p)),
                                    "s": round(float(rk["_s"]), 2),
                                    "pl": val(rk, "player", "") or "",
                                    "rec": val(rk, "pass_recipient", "") or "",
                                    "xg": xgr, "but": val(r, "shot_outcome", "") == "Goal"})
                        break

        # ---- Goalkeeper Build Up : toutes les relances du gardien SAUF le
        #      six metres. C'est la definition de Geoffrey, et elle explique
        #      pourquoi seules 3 de ses 19 instances partaient d'un degagement :
        #      l'essentiel, ce sont les passes en retrait rejouees au pied ou a
        #      la main. Les six metres ont deja leur propre ligne (k = "gk").
        if (typ == "Pass" and val(r, "position", "") == "Goalkeeper"
                and val(r, "pass_type", "") != "Goal Kick"):
            pid = val(r, "possession")
            fin = s
            zp = "Sans pression"
            if pid is not None:
                dd = poss.get(int(pid))
                if dd and dd["p"] == p:
                    fin = round(dd["e"], 2)
                xpg = premiere_pression.get(int(pid))
                zp = zone_pression(xpg) if xpg is not None else "Sans pression"
            out.append({"k": "gkbu", "team": team, "p": p, "s": s, "e": fin,
                        "h": zp, "len": pass_length_m(r),
                        "pl": val(r, "player", "") or "",
                        "rec": val(r, "pass_recipient", "") or ""})

        # ---- csc : StatsBomb crée "Own Goal Against" (équipe fautive)
        #      et "Own Goal For" (équipe qui en profite). On garde le "For".
        if typ == "Own Goal For":
            out.append({"k": "og", "team": team, "p": p, "s": s,
                        "pl": val(r, "player", "") or ""})

    out.sort(key=lambda e: (e["p"], e["s"], e["k"]))
    return out, sorted(periods_seen)


# ----------------------------------------------------------------------- main

def main():
    args = [a for a in sys.argv[1:]]
    force = "--force" in args
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
        args = [a for a in args if a != "--limit" and not a.isdigit()]
    args = [a for a in args if not a.startswith("--")]

    # NB : une variable d'environnement définie mais VIDE (cas d'un
    # workflow_dispatch avec le champ laissé vide) doit retomber sur la
    # saison courante -> d'où le `or` plutôt qu'un défaut de .get().
    season = (args[0] if args else os.environ.get("SEASON", "")).strip() \
        or CURRENT_SEASON

    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("!! SB_USERNAME / SB_PASSWORD absents de l'environnement.\n"
              "   Dans Actions : Settings > Secrets and variables > Actions.\n"
              "   En local     : SB_USERNAME='…' SB_PASSWORD='…' python build_sportscode.py")
        raise SystemExit(1)

    try:
        season_id = resolve_season_id(season)
    except SystemExit:
        raise
    except Exception as exc:
        print("!! Impossible de résoudre la saison %r : %s" % (season, exc))
        raise SystemExit(1)
    outdir = "sc" if season == CURRENT_SEASON else "sc_%s" % season
    os.makedirs(outdir, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("Saison %s (season_id=%s) -> %s/" % (season, season_id, outdir))

    try:
        matches = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)
    except Exception as exc:
        print("!! Impossible de lister les matchs (competition_id=%s, season_id=%s).\n"
              "   %s\n"
              "   Un code 401 = identifiants StatsBomb refusés : vérifier les secrets\n"
              "   SB_USERNAME / SB_PASSWORD (attention, SB_USERNAME et non SB_SURNAME)."
              % (COMPETITION_ID, season_id, exc))
        raise SystemExit(1)

    if matches is None or len(matches) == 0:
        print("!! Aucun match retourné pour season_id=%s." % season_id)
        raise SystemExit(1)

    matches = matches.sort_values(["match_week", "match_date"])

    def num(v):
        """valeur pandas -> int, ou None si NaN/None/non convertible."""
        if v is None or v != v:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def txt(v):
        return "" if v is None or v != v else str(v)

    # ---- index construit AVANT la boucle et écrit tout de suite : même si le
    #      run s'interrompt, le catalogue est publié et la page reste utilisable.
    index = []
    todo = []
    for _, m in matches.iterrows():
        mid = num(m.get("match_id"))
        if mid is None:
            continue
        hs, as_ = num(m.get("home_score")), num(m.get("away_score"))
        entry = {
            "match_id": mid,
            "date": txt(m.get("match_date"))[:10],
            "round": num(m.get("match_week")),
            "home": txt(m.get("home_team")),
            "away": txt(m.get("away_team")),
            "score": ("%d-%d" % (hs, as_)) if hs is not None and as_ is not None else "",
        }
        index.append(entry)
        todo.append(entry)

    index.sort(key=lambda e: (e["round"] if e["round"] is not None else 99,
                              e["date"], e["home"]))

    index_path = os.path.join(outdir, "index.json")

    def write_index():
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"competition": "Ligue 2", "season": season,
                       "season_id": season_id, "updated": now,
                       "matches": index}, f, ensure_ascii=False, indent=1)

    write_index()
    print("index.json écrit : %d matchs au catalogue." % len(index))

    done = skipped = failed = 0

    for entry in todo:
        mid = entry["match_id"]
        home, away = entry["home"], entry["away"]
        score, rnd, date = entry["score"], entry["round"], entry["date"]

        path = os.path.join(outdir, "sc_%d.json" % mid)

        if os.path.exists(path) and not force:
            skipped += 1
            continue

        if limit is not None and done >= limit:
            continue

        try:
            ev = sb.events(match_id=mid)
        except Exception as exc:                       # match non joué / indispo
            print("  !! %s %s-%s : %s" % (mid, home, away, exc))
            failed += 1
            continue

        if ev is None or len(ev) == 0:
            failed += 1
            continue

        try:
            evs, periods = build_match(ev)
        except Exception as exc:
            print("  !! %s parsing : %s" % (mid, exc))
            failed += 1
            continue

        doc = {
            "match_id": mid, "competition": "Ligue 2", "season": season,
            "season_id": season_id, "date": date, "round": rnd,
            "home": home, "away": away, "score": score,
            "teams": [home, away], "periods": periods,
            "updated": now, "ev": evs,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        except Exception as exc:
            print("  !! %s écriture : %s" % (mid, exc))
            failed += 1
            continue

        done += 1
        print("  ok  %-9s J%-3s %-22s %-5s %-22s  %4d év." %
              (mid, rnd if rnd else "?", home, score, away, len(evs)),
              flush=True)

    write_index()
    print("\n%d générés, %d déjà présents, %d échecs — %d matchs à l'index."
          % (done, skipped, failed, len(index)))

    produced = len([f for f in os.listdir(outdir) if f.startswith("sc_")])
    print("%d fichier(s) sc_*.json dans %s/" % (produced, outdir))
    if produced == 0:
        print("!! Aucune timeline produite.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
