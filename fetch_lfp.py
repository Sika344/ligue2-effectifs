#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_lfp.py — récupère les effectifs officiels LFP et écrit
lfp_effectifs_<saison>.json, que build_ligue2_lfp.py transforme ensuite en
ligue2_<saison>.json.

------------------------------------------------------------------ POURQUOI
Ce fichier n'était produit par AUCUN script : il avait été récupéré à la main,
via le navigateur, le 7 août 2026. Dix semaines plus tard il était périmé —
Téji Savanier, arrivé à Metz depuis, n'y figurait pas, et des dizaines de
photos publiées entre-temps manquaient. Ce script rend la récupération
reproductible.

------------------------------------------------------------------- API LFP
Deux points d'entrée publics, sans authentification :
  /championship-clubs?championship=4   les 18 clubs de Ligue 2 et, pour chacun,
                                       la liste des identifiants de ses joueurs
  /championship-player/<id>            la fiche d'un joueur

Il n'existe pas de point d'entrée qui renvoie tous les joueurs d'un coup : on
interroge donc environ 550 fiches, une par joueur. Compte deux à trois minutes.

---------------------------------------------------------------- LES PHOTOS
La LFP sert une SILHOUETTE GÉNÉRIQUE quand elle n'a pas la photo d'un joueur.
L'URL contient alors « defaultAssets » et l'image pèse 6 ko au lieu de 85.
C'est ce qui faisait passer Cristian Castro Devenish pour « photographié »
alors que le site affichait un bonhomme gris. On marque donc explicitement ces
cas, pour que la suite de la chaîne ne les confonde pas avec de vraies photos.

------------------------------------------------------------------ LE PIED
L'API ne donne pas le pied fort. Il est donc REPRIS du fichier précédent, où
il avait été corrigé à la main à partir de StatsBomb — 89 pieds rectifiés en
août. Sans cette reprise, ce travail serait perdu à chaque récupération.

USAGE :
    SAISON=2026-2027 python fetch_lfp.py            # écrit le fichier
    SAISON=2026-2027 python fetch_lfp.py --dry-run  # n'écrit rien
"""

import os
import re
import sys
import json
import time
import datetime
import unicodedata

import requests

SAISON = os.environ.get("SAISON", "2026-2027")
CHAMPIONNAT = 4                       # 4 = Ligue 2 (1 = Ligue 1)
BASE = "https://ma-api.ligue1.fr"
SORTIE = "lfp_effectifs_%s.json" % SAISON
DRY = "--dry-run" in sys.argv

# Nom court LFP -> clé employée par tout le site. Table EXPLICITE : un
# rapprochement flou se tromperait un jour sans prévenir, et ces clés servent
# à joindre les effectifs aux données StatsBomb dans toutes les pages.
CLUBS = {
    "FC Annecy": "Annecy FC",
    "Boulogne": "Boulogne",
    "Clermont": "Clermont Foot",
    "Dijon FCO": "Dijon",
    "Dunkerque": "Dunkerque",
    "Grenoble": "Grenoble",
    "EA Guingamp": "Guingamp",
    "Laval MFC": "Laval",
    "FC Metz": "Metz",
    "Montpellier": "Montpellier",
    "Nancy": "Nancy",
    "FC Nantes": "Nantes",
    "Pau FC": "Pau",
    "Red Star FC": "Red Star",
    "Reims": "Reims",
    "Rodez AF": "Rodez",
    "ASSE": "Saint-Etienne",
    "FCSM": "Sochaux",
}

# Codes de poste de l'API. Un code inconnu fait ÉCHOUER le script : mieux vaut
# s'arrêter que ranger silencieusement un joueur au mauvais poste.
POSTES = {1: "GK", 2: "DEF", 3: "MID", 4: "ATT"}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ligue2-effectifs/1.0"})


def nn(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def get(chemin, essais=3):
    for i in range(essais):
        try:
            r = SESSION.get(BASE + chemin, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def pieds_precedents():
    """{(club, nom normalisé): pied} depuis le fichier existant."""
    try:
        with open(SORTIE, encoding="utf-8") as fh:
            anc = json.load(fh)
    except Exception:
        print("   (pas de fichier précédent : les pieds seront vides)")
        return {}
    out = {}
    for club, lst in (anc.get("clubs") or {}).items():
        for p in lst:
            if p.get("foot"):
                out[(club, nn(p.get("last")) + "|" + nn(p.get("first"))[:1])] = p["foot"]
    print("   %d pieds repris du fichier précédent" % len(out))
    return out


def main():
    print("Saison %s — championnat %d -> %s" % (SAISON, CHAMPIONNAT, SORTIE))
    pieds = pieds_precedents()

    data = get("/championship-clubs?championship=%d" % CHAMPIONNAT)
    if not data or "championshipsClubs" not in data:
        raise SystemExit("ÉCHEC : liste des clubs illisible.")

    clubs_api = []
    for c in data["championshipsClubs"].values():
        ch = (c.get("championships") or {}).get(str(CHAMPIONNAT))
        if not (ch and ch.get("active")):
            continue
        clubs_api.append((c.get("shortName"), ch.get("playersIds") or []))

    inconnus = [n for n, _ in clubs_api if n not in CLUBS]
    if inconnus:
        raise SystemExit(
            "ÉCHEC : clubs non reconnus : %s\nAjoute-les à la table CLUBS — un "
            "club mal nommé casserait la jointure avec les données StatsBomb."
            % ", ".join(map(str, inconnus)))
    if len(clubs_api) != 18:
        print("   !! %d clubs actifs au lieu de 18" % len(clubs_api))

    sortie = {}
    total = sans_photo = silhouette = 0
    for court, ids in sorted(clubs_api, key=lambda x: CLUBS[x[0]]):
        cle = CLUBS[court]
        squad = []
        for pid in ids:
            r = get("/championship-player/%s" % pid)
            if not r:
                continue
            p = r
            if len(r) == 1 and isinstance(list(r.values())[0], dict):
                p = list(r.values())[0]
            c4 = (p.get("championships") or {}).get(str(CHAMPIONNAT)) or {}
            if not c4.get("active"):
                continue

            pos_code = c4.get("position")
            if pos_code not in POSTES:
                raise SystemExit(
                    "ÉCHEC : code de poste inconnu (%r) pour %s %s. Complète la "
                    "table POSTES." % (pos_code, p.get("firstName"), p.get("lastName")))

            photo = None
            bust = ((c4.get("assets") or {}).get("bustPictures") or {})
            photo = bust.get("large") or bust.get("medium") or bust.get("small")
            generique = bool(photo and "defaultAssets" in photo)

            last = p.get("lastName") or ""
            first = p.get("firstName") or ""
            squad.append({
                "num": c4.get("jerseyNumber"),
                "last": last,
                "first": first,
                "dob": (p.get("birthDate") or "")[:10] or None,
                "foot": pieds.get((cle, nn(last) + "|" + nn(first)[:1])),
                "cc": p.get("countryShortCode"),
                "pos": POSTES[pos_code],
                "photo": photo,
                # Marqueur explicite : une silhouette n'est pas une photo.
                "photo_generique": generique,
            })
            total += 1
            if not photo:
                sans_photo += 1
            elif generique:
                silhouette += 1

        squad.sort(key=lambda x: ({"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}.get(x["pos"], 9),
                                  x["num"] if isinstance(x["num"], int) else 999))
        sortie[cle] = squad
        print("   %-16s %2d joueurs" % (cle, len(squad)))

    if total < 400:
        raise SystemExit("ÉCHEC : %d joueurs seulement — récupération incomplète, "
                         "rien n'a été écrit." % total)

    out = {
        "source": "ma-api.ligue1.fr",
        "saison_lfp": int(SAISON[:4]) + 0,
        "competition": "Ligue 2",
        "genere": datetime.datetime.utcnow().isoformat() + "Z",
        "note": "effectifs officiels LFP %s" % SAISON,
        "clubs": sortie,
    }
    print("\n--- Résultat ---")
    print("   %d joueurs | sans photo : %d | silhouette générique : %d | vraies photos : %d"
          % (total, sans_photo, silhouette, total - sans_photo - silhouette))
    if DRY:
        print("   --dry-run : rien n'a été écrit.")
        return
    with open(SORTIE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("   %s écrit." % SORTIE)


if __name__ == "__main__":
    main()
