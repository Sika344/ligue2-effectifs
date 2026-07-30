#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_height.py — la taille des joueurs est-elle accessible par l'API StatsBomb ?

La plateforme StatsBomb IQ affiche bien « Height: 177cm » pour Nicolas Pays.
Reste à savoir si l'API la sert, et par quel endpoint. `statsbombpy` n'expose
que competitions / matches / lineups / events / frames / *-season-stats /
*-match-stats : aucun endpoint « players ». Ce script :

  1. inspecte les colonnes des endpoints déjà couverts par statsbombpy ;
  2. sonde en direct une liste d'endpoints plausibles non couverts ;
  3. affiche tout ce qui ressemble à une taille ou un poids.

Ne modifie aucun fichier. Identifiants via SB_USERNAME / SB_PASSWORD.

USAGE
    SB_USERNAME='…' SB_PASSWORD='…' python probe_height.py
"""

import os
import re
import sys
import json

import requests
from requests.auth import HTTPBasicAuth

from statsbombpy import sb

COMPETITION_ID = 8
SEASON_ID = 318
HOST = "https://data.statsbombservices.com"

MOTS = ("height", "weight", "taille", "poids", "stature", "cm")


def interessant(nom):
    n = str(nom).lower()
    return any(m in n for m in MOTS)


def montre_colonnes(titre, df):
    print("\n--- %s ---" % titre)
    if df is None:
        print("   (pas de données)")
        return
    try:
        cols = list(df.columns)
    except AttributeError:
        print("   type inattendu : %s" % type(df).__name__)
        return
    print("   %d colonnes" % len(cols))
    hits = [c for c in cols if interessant(c)]
    if hits:
        print("   >>> COLONNES MORPHO TROUVÉES : %s" % hits)
        for c in hits:
            try:
                ech = df[c].dropna().unique()[:5]
                print("       %s -> %s" % (c, list(ech)))
            except Exception:
                pass
    else:
        print("   aucune colonne taille/poids")
        print("   échantillon : %s" % ", ".join(map(str, cols[:12])))


def main():
    user = os.environ.get("SB_USERNAME")
    pwd = os.environ.get("SB_PASSWORD")
    if not (user and pwd):
        print("!! SB_USERNAME / SB_PASSWORD absents.")
        raise SystemExit(1)

    print("=== 1. endpoints couverts par statsbombpy ===")

    try:
        pss = sb.player_season_stats(competition_id=COMPETITION_ID,
                                     season_id=SEASON_ID)
        montre_colonnes("player_season_stats", pss)
    except Exception as exc:
        print("\n--- player_season_stats --- échec : %s" % exc)

    match_id = None
    try:
        ms = sb.matches(competition_id=COMPETITION_ID, season_id=SEASON_ID)
        match_id = int(ms.iloc[0]["match_id"])
    except Exception as exc:
        print("   (impossible de récupérer un match_id : %s)" % exc)

    if match_id:
        try:
            lu = sb.lineups(match_id=match_id)
            # sb.lineups renvoie un dict {équipe: DataFrame}
            if isinstance(lu, dict):
                for eq, df in list(lu.items())[:1]:
                    montre_colonnes("lineups[%s] (match %s)" % (eq, match_id), df)
            else:
                montre_colonnes("lineups (match %s)" % match_id, lu)
        except Exception as exc:
            print("\n--- lineups --- échec : %s" % exc)

        try:
            pms = sb.player_match_stats(match_id=match_id)
            montre_colonnes("player_match_stats (match %s)" % match_id, pms)
        except Exception as exc:
            print("\n--- player_match_stats --- échec : %s" % exc)

    print("\n\n=== 2. endpoints non couverts, sondés en direct ===")
    auth = HTTPBasicAuth(user, pwd)
    chemins = []
    for v in (1, 2, 3, 4, 5, 6, 7, 8):
        chemins += [
            "api/v%d/players" % v,
            "api/v%d/competitions/%d/seasons/%d/players" % (v, COMPETITION_ID, SEASON_ID),
            "api/v%d/competitions/%d/seasons/%d/player-info" % (v, COMPETITION_ID, SEASON_ID),
        ]
    if match_id:
        for v in (1, 2, 3, 4, 5, 6):
            chemins.append("api/v%d/matches/%d/players" % (v, match_id))

    trouves = []
    for c in chemins:
        url = "%s/%s" % (HOST, c)
        try:
            r = requests.get(url, auth=auth, timeout=25)
        except Exception as exc:
            print("  %-58s ERREUR %s" % (c, exc))
            continue
        if r.status_code != 200:
            print("  %-58s HTTP %s" % (c, r.status_code))
            continue
        try:
            js = r.json()
        except ValueError:
            print("  %-58s HTTP 200 mais pas du JSON" % c)
            continue

        ech = js[0] if isinstance(js, list) and js else js
        cles = list(ech.keys()) if isinstance(ech, dict) else []
        hits = [k for k in cles if interessant(k)]
        marque = "  <<< TAILLE ICI" if hits else ""
        print("  %-58s HTTP 200  %d clé(s)%s" % (c, len(cles), marque))
        if hits:
            for k in hits:
                print("        %s = %r" % (k, ech.get(k)))
            trouves.append(c)
        elif cles:
            print("        clés : %s" % ", ".join(map(str, cles[:14])))

    print("\n\n=== CONCLUSION ===")
    if trouves:
        print("Taille accessible via : %s" % ", ".join(trouves))
        print("-> je peux écrire le script de remplissage sur cette base.")
    else:
        print("Aucun endpoint testé ne renvoie de taille.")
        print("-> la donnée existe dans StatsBomb IQ mais n'est pas servie par")
        print("   l'API avec ce compte. Il faudra passer par une autre source.")


if __name__ == "__main__":
    main()
