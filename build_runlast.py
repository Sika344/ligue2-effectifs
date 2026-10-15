#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_runlast.py — franchissements de la dernière ligne adverse, en construction.

Écrit runlast_<saison>.json. Alimente la plaque « Construction » de attacking.html.

============================================================== CE QU'ON MESURE
Pour chaque image 360 prise pendant une phase de CONSTRUCTION de l'équipe :

  PRÉSENCE        nombre de ses joueurs situés au-delà de la dernière ligne
                  défensive adverse, à cet instant.
  FRANCHISSEMENT  un joueur au-delà de la ligne alors qu'il ne l'était pas sur
                  l'image précédente de la même possession.

Les deux sont publiés côte à côte, parce qu'ils ne disent pas la même chose :
beaucoup de présence et peu de franchissements décrit une équipe qui stationne
dans le dos de la défense ; l'inverse décrit une équipe qui attaque la
profondeur par des courses.

------------------------------------------------- CE QUE LE 360 NE PERMET PAS
Le 360 donne des PHOTOS, pas un film : une position à l'instant d'un événement,
pas une trajectoire. Un « franchissement » est donc une DÉDUCTION entre deux
images successives, et non une course observée. Avec environ une image par
événement, deux images consécutives sont séparées de quelques secondes : un
joueur peut franchir et revenir sans qu'on le voie, ou être compté une fois
pour un mouvement qui en comptait deux. Le chiffre décrit une tendance, pas un
décompte exact.

------------------------------------------------------- LA DERNIÈRE LIGNE
Les coordonnées d'une image sont dans le repère de l'équipe qui joue l'action :
elle attaque vers x=120. La dernière ligne adverse est donc l'abscisse du
défenseur de champ le plus PROCHE de son propre but, c'est-à-dire le x maximal
parmi les adversaires hors gardien. Un joueur « au-delà » a un x supérieur.

IMAGES ÉCARTÉES : la caméra ne voit pas tout le terrain. Si les défenseurs les
plus reculés sont hors champ, la ligne calculée serait trop avancée et on
compterait des franchissements imaginaires. On exige donc au moins
ADV_MINIMUM défenseurs de champ visibles. Sur Montpellier - Grenoble, cela
retient 69 % des images. Le taux retenu est publié avec les chiffres : un
pourcentage sans sa base ne veut rien dire.

------------------------------------------------------------- CONSTRUCTION
Même définition que la page SportsCode, calée avec Geoffrey : une possession
part d'une situation CONTRÔLÉE — ni phase arrêtée, ni relance de but, ni
transition. Les `play_pattern` retenus sont donc « Regular Play », « From
Keeper » et « Other ».

----------------------------------------------------------------- LES ZONES
Quatre quarts de 30 unités StatsBomb, dans le sens de jeu de l'équipe :
  1 basse (0-30) · 2 médiane basse (30-60) · 3 médiane haute (60-90) · 4 haute (90-120)

Le résultat est CROISÉ : zone du ballon × zone du franchissement. Attention,
franchir la dernière ligne se produit presque toujours haut sur le terrain :
la colonne « zone du franchissement » sera très concentrée, et beaucoup de
cases resteront à 0 ou 1. C'est une conséquence du croisement, pas une erreur.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' SEASON='2026-2027' python build_runlast.py
"""

import os
import sys
import json
import datetime

import requests
from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {"2025-2026": 318, "2026-2027": 351}

BASE = "https://data.statsbombservices.com/api/v2/360-frames/"
AUTH = (os.environ.get("SB_USERNAME", ""), os.environ.get("SB_PASSWORD", ""))
HEAD = {"User-Agent": "ligue2-effectifs/1.0"}

# Nombre minimal d'adversaires de champ visibles pour que la ligne calculée
# soit crédible. En dessous, l'image est écartée et comptée comme telle.
ADV_MINIMUM = 8

# Situations de construction, au sens retenu avec Geoffrey.
PATTERNS_CONSTRUCTION = {"Regular Play", "From Keeper", "Other"}

ZONES = [(0, 30), (30, 60), (60, 90), (90, 120)]
ZONE_NOMS = ["Basse", "Médiane basse", "Médiane haute", "Haute"]
SHOOTOUT_PERIOD = 5


def now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def resolve_season():
    label = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "")).strip()
    if not label:
        label = CURRENT_SEASON
    sid = SEASON_IDS.get(label)
    if sid is None:
        comps = sb.competitions()
        hit = comps[(comps["competition_id"] == COMPETITION_ID)
                    & (comps["season_name"] == label.replace("-", "/"))]
        if hit.empty:
            raise SystemExit("saison introuvable : %s" % label)
        sid = int(hit.iloc[0]["season_id"])
    return label, sid, "runlast_%s.json" % label


def zone_de(x):
    """Quart de terrain, ou None si l'abscisse manque."""
    if x is None or x != x:
        return None
    for i, (a, b) in enumerate(ZONES):
        if x >= a and (x < b or b >= 120):
            return i
    return None


def get_frames(match_id):
    try:
        r = requests.get(BASE + str(match_id), auth=AUTH, headers=HEAD, timeout=120)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as exc:
        print("   !! frames %s : %s" % (match_id, exc))
        return None


def matchs_joues(season_id):
    """Matchs effectivement disputés.

    Le score d'une rencontre à venir vaut NaN, et NaN n'est pas None : tester
    `is not None` laisserait passer tout le calendrier. NaN est la seule valeur
    différente d'elle-même, d'où le test retenu.
    """
    m = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)
    out = []
    for _, r in m.iterrows():
        hs = r.get("home_score")
        if hs is None or hs != hs:
            continue
        out.append({"match_id": int(r["match_id"]),
                    "date": str(r.get("match_date", ""))[:10],
                    "home": r.get("home_team", ""), "away": r.get("away_team", "")})
    out.sort(key=lambda x: x["date"])
    return out


def index_evenements(match_id):
    """event_uuid -> {team, possession, pattern, x du ballon, période, seconde}."""
    try:
        ev = sb.events(match_id=match_id)
    except Exception as exc:
        print("   !! events %s : %s" % (match_id, exc))
        return {}
    cols = ev.columns
    idx = {}
    for _, r in ev.iterrows():
        eid = r.get("id")
        if not isinstance(eid, str):
            continue
        loc = r.get("location") if "location" in cols else None
        x = None
        if isinstance(loc, list) and loc:
            try:
                x = float(loc[0])
            except (TypeError, ValueError):
                x = None
        per = r.get("period")
        idx[eid] = {
            "team": r.get("team") if isinstance(r.get("team"), str) else None,
            "poss": r.get("possession"),
            "pattern": r.get("play_pattern") if isinstance(r.get("play_pattern"), str) else None,
            "x": x,
            "per": int(per) if per == per and per is not None else None,
            "min": int(r.get("minute")) if r.get("minute") == r.get("minute") else None,
            "sec": int(r.get("second")) if r.get("second") == r.get("second") else None,
        }
    return idx


def ligne_et_audela(ff):
    """(abscisse de la dernière ligne, [x des coéquipiers au-delà]) ou None.

    None signifie « image inexploitable » : pas assez d'adversaires visibles
    pour que la ligne veuille dire quelque chose.
    """
    champ_adv = [p for p in ff if not p.get("m") and not p.get("k")
                 and p.get("x") is not None]
    if len(champ_adv) < ADV_MINIMUM:
        return None
    ligne = max(p["x"] for p in champ_adv)
    audela = [p["x"] for p in ff
              if p.get("m") and not p.get("a") and p.get("x") is not None
              and p["x"] > ligne]
    return ligne, audela


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        raise SystemExit("ERREUR : SB_USERNAME / SB_PASSWORD manquants.")

    label, season_id, sortie = resolve_season()
    print("Saison %s (season_id=%s) -> %s" % (label, season_id, sortie))

    ms = matchs_joues(season_id)
    print("%d matchs joués à traiter" % len(ms))
    if not ms:
        raise SystemExit("aucun match joué : rien à calculer.")

    # équipe -> compteurs
    teams = {}

    def fiche(t):
        return teams.setdefault(t, {
            "matches": 0,
            "frames_vues": 0, "frames_retenues": 0,
            # croisement zone du ballon x zone du franchissement
            "cross_pass": [[0] * 4 for _ in range(4)],
            "cross_pres": [[0] * 4 for _ in range(4)],
            # totaux par zone du ballon, toutes zones de franchissement
            "par_zone_ballon": [{"franch": 0, "presence": 0, "images": 0} for _ in range(4)],
            "franch_total": 0, "presence_total": 0,
        })

    traites = 0
    for m in ms:
        fr = get_frames(m["match_id"])
        if not fr:
            print("   %s %s - %s : pas de 360" % (m["date"], m["home"], m["away"]))
            continue
        idx = index_evenements(m["match_id"])
        if not idx:
            continue

        # On range les images dans l'ordre du match, par possession, pour
        # pouvoir comparer une image à la précédente de la MÊME possession.
        images = []
        for f in fr:
            e = idx.get(f.get("event_uuid"))
            if not e or not e["team"]:
                continue
            if e["per"] == SHOOTOUT_PERIOD:
                continue
            if e["pattern"] not in PATTERNS_CONSTRUCTION:
                continue
            ff = []
            for p in (f.get("freeze_frame") or []):
                loc = p.get("location") or [None, None]
                ff.append({"x": loc[0], "y": loc[1], "m": bool(p.get("teammate")),
                           "a": bool(p.get("actor")), "k": bool(p.get("keeper"))})
            if not ff:
                continue
            images.append({"e": e, "ff": ff})
        images.sort(key=lambda im: ((im["e"]["per"] or 0), (im["e"]["min"] or 0),
                                    (im["e"]["sec"] or 0)))

        vus = set()
        # état précédent : (possession) -> ensemble des y des joueurs au-delà.
        # On compare par ABSCISSE arrondie faute d'identifiant de joueur dans la
        # freeze frame : c'est une approximation, assumée et documentée.
        precedent = {}

        for im in images:
            e, ff = im["e"], im["ff"]
            t = e["team"]
            f_t = fiche(t)
            vus.add(t)
            f_t["frames_vues"] += 1

            res = ligne_et_audela(ff)
            if res is None:
                continue
            f_t["frames_retenues"] += 1
            ligne, audela = res

            zb = zone_de(e["x"])
            if zb is None:
                continue
            f_t["par_zone_ballon"][zb]["images"] += 1

            # présence : combien sont au-delà, maintenant
            f_t["presence_total"] += len(audela)
            f_t["par_zone_ballon"][zb]["presence"] += len(audela)
            for xr in audela:
                zc = zone_de(xr)
                if zc is not None:
                    f_t["cross_pres"][zb][zc] += 1

            # franchissements : au-delà maintenant, pas sur l'image précédente
            cle = (t, e["per"], e["poss"])
            avant = precedent.get(cle, set())
            maintenant = {round(x) for x in audela}
            nouveaux = maintenant - avant
            precedent[cle] = maintenant
            f_t["franch_total"] += len(nouveaux)
            f_t["par_zone_ballon"][zb]["franch"] += len(nouveaux)
            for xr in nouveaux:
                zc = zone_de(xr)
                if zc is not None:
                    f_t["cross_pass"][zb][zc] += 1

        for t in vus:
            fiche(t)["matches"] += 1
        traites += 1
        if traites % 10 == 0:
            print("   %d matchs traités…" % traites)

    if not teams:
        raise SystemExit("ÉCHEC : aucune image exploitable — le 360 semble absent "
                         "sur cette saison. Rien n'a été écrit.")

    # Contrôle : les totaux doivent correspondre aux croisements.
    for t, f in teams.items():
        sc = sum(sum(r) for r in f["cross_pass"])
        sp = sum(sum(r) for r in f["cross_pres"])
        if sc > f["franch_total"] or sp > f["presence_total"]:
            raise AssertionError("%s : croisement incohérent (%d/%d, %d/%d)"
                                 % (t, sc, f["franch_total"], sp, f["presence_total"]))

    out = {"competition": "Ligue 2", "season": label, "season_id": season_id,
           "updated": now(), "zones": ZONE_NOMS,
           "adv_minimum": ADV_MINIMUM, "teams": teams}
    with open(sortie, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)

    print("\n--- Résultat ---")
    for t, f in sorted(teams.items()):
        part = (100.0 * f["frames_retenues"] / f["frames_vues"]) if f["frames_vues"] else 0
        pm = (f["franch_total"] / f["matches"]) if f["matches"] else 0
        print("   %-16s %2d matchs | %5d images vues, %5d retenues (%2.0f %%) | "
              "%4d franchissements (%.1f/match)"
              % (t, f["matches"], f["frames_vues"], f["frames_retenues"], part,
                 f["franch_total"], pm))
    print("\n%s écrit : %d équipes." % (sortie, len(teams)))


if __name__ == "__main__":
    main()
