#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_individual.py — données joueur pour l'onglet « Individual » (spider chart).

SORTIE : individual_<saison>.json, contenant les VALEURS BRUTES par joueur.

POURQUOI PAS DE PERCENTILES ICI : le seuil de minutes est réglable dans la page.
Or changer le seuil change le groupe de comparaison, donc TOUS les percentiles.
Les calculer côté Python les figerait sur un seuil unique. Ils sont donc calculés
dans le navigateur, à chaque déplacement du curseur.

SUR LA RÉSOLUTION DES MÉTRIQUES : les noms de colonnes de `player_season_stats`
varient selon le niveau de collecte de l'abonnement. Plutôt que de coder en dur
des noms supposés et de produire des colonnes vides sans le dire, chaque métrique
porte une liste de noms candidats. Le script ne retient qu'une correspondance
EXACTE ; s'il n'en trouve aucune, il ne devine pas : il inscrit la métrique dans
`diagnostic.non_resolues` avec les colonnes les plus ressemblantes, à trancher à
la main. Le JSON embarque aussi la liste complète des colonnes disponibles.

SAISON : la sortie est TOUJOURS suffixée — individual_2026-2027.json,
individual_2025-2026.json. Contrairement aux autres build_*.py, aucune saison
ne produit de nom nu : season.js ne lit que des noms suffixés.
La saison se passe en argv[1] ou via la variable d'environnement SEASON.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' python build_individual.py 2026-2027
"""

import os
import sys
import json
import math
import difflib
import datetime

from statsbombpy import sb

COMPETITION_ID = 8              # Ligue 2
CURRENT_SEASON = "2025-2026"    # saison retenue si SEASON est vide
SEASON_IDS = {
    "2025-2026": 318,
    "2026-2027": 351,
}

# ---------------------------------------------------------------------------
# Les métriques demandées, dans l'ordre de la maquette. 27 sur 28 : « Corner xG »
# est retiré faute de donnée (voir plus bas).
#   cle    : identifiant court utilisé par le JSON et la page
#   label  : libellé affiché sur l'axe du radar
#   cands  : noms de colonnes candidats, essayés dans l'ordre
#   calc   : métrique dérivée — somme de plusieurs colonnes (ex. buts + passes déc.)
#   sens   : +1 si « plus c'est haut, mieux c'est », -1 sinon (pertes, fautes…)
# ---------------------------------------------------------------------------
METRIQUES = [
    dict(cle="obv_off", label="OBV off", famille="off", sens=+1, calc=[
        "player_season_obv_pass_90",
        "player_season_obv_dribble_carry_90",
        "player_season_obv_shot_90"]),
    # Aucune colonne d'xG « tout compris » dans les 237 disponibles : StatsBomb
    # ne fournit que le non-penalty. Cet axe est donc un DOUBLON de NP xG, gardé
    # à la demande. Deux axes identiques gonflent la surface du polygone : à
    # n'utiliser qu'en connaissance de cause.
    dict(cle="xg", label="xG", famille="off", sens=+1, cands=[
        "player_season_np_xg_90"]),
    dict(cle="box_touches", label="Box touches", famille="off", sens=+1, cands=[
        "player_season_touches_inside_box_90"]),
    dict(cle="key_passes", label="Key passes", famille="off", sens=+1, cands=[
        "player_season_key_passes_90"]),
    # xG Assisted : l'xG du tir qu'a produit la passe du joueur. Mesure ce qu'il
    # crée pour les autres, indépendamment de leur réussite devant le but.
    # Version TOUTE SITUATION — `op_xa_90` (jeu courant) et `sp_xa_90` (coups de
    # pied arrêtés) existent aussi si l'on veut séparer les deux un jour.
    dict(cle="xa", label="xG Assisted", famille="off", sens=+1, cands=[
        "player_season_xa_90"]),
    dict(cle="obv_def", label="OBV def", famille="def", sens=+1, cands=[
        "player_season_obv_defensive_action_90",
        "player_season_obv_defensive_actions_90"]),
    dict(cle="def_actions", label="Def actions", famille="def", sens=+1, cands=[
        "player_season_defensive_actions_90",
        "player_season_defensive_action_90",
        "player_season_padj_defensive_actions_90"]),
    dict(cle="pressures", label="Pressures", famille="def", sens=+1, cands=[
        "player_season_pressures_90", "player_season_padj_pressures_90"]),
    dict(cle="high_recov", label="High recov.", famille="def", sens=+1, cands=[
        "player_season_high_recoveries_90",
        "player_season_counterpressures_90"]),
    dict(cle="obv_lb", label="OBV line-break", famille="off", sens=+1, cands=[
        "player_season_obv_lbp_90"]),
    # Seuil 5 m sur les trois disponibles (2/5/10, emboîtés) : à 2 m presque
    # toute passe réussie qualifie, à 10 m l'événement devient trop rare pour
    # être stable. Une seule ligne à changer si l'on veut un autre seuil.
    dict(cle="lbp_space", label="LBP→space", famille="off", sens=+1, cands=[
        "player_season_lbp_to_space_5_90"]),
    dict(cle="obv_lb_f3", label="OBV LB (f3)", famille="off", sens=+1, cands=[
        "player_season_f3_obv_lbp_90"]),
    dict(cle="lbp_space_f3", label="LBP→space (f3)", famille="off", sens=+1, cands=[
        "player_season_f3_lbp_to_space_5_90"]),
    dict(cle="goal_involv", label="Goal involv.", famille="off", sens=+1, calc=[
        "player_season_goals_90", "player_season_assists_90"]),
    dict(cle="np_xg", label="NP xG", famille="off", sens=+1, cands=[
        "player_season_np_xg_90", "player_season_npxg_90"]),
    dict(cle="shots", label="Shots", famille="off", sens=+1, cands=[
        "player_season_shots_90", "player_season_np_shots_90"]),
    dict(cle="xg_per_shot", label="xG/shot", famille="off", sens=+1, cands=[
        "player_season_np_xg_per_shot", "player_season_xg_per_shot"]),
    # « Corner xG » retiré : rien dans les 237 colonnes ne mesure l'xG sur
    # corner côté tireur. Laisser l'axe afficherait zéro pour tout le monde,
    # ce qui se lirait comme une faiblesse générale plutôt que comme une absence.
    dict(cle="penalties", label="Penalties", famille="off", sens=+1, cands=[
        "player_season_penalty_wins_90"]),
    dict(cle="deep_prog", label="Deep prog.", famille="off", sens=+1, cands=[
        "player_season_deep_progressions_90"]),
    dict(cle="deep_compl", label="Deep compl.", famille="off", sens=+1, cands=[
        "player_season_deep_completions_90"]),
    dict(cle="passes_box", label="Passes in box", famille="off", sens=+1, cands=[
        "player_season_passes_inside_box_90",
        "player_season_op_passes_into_box_90"]),
    dict(cle="dribbles", label="Succ. dribbles", famille="off", sens=+1, cands=[
        "player_season_successful_dribbles_90", "player_season_dribbles_90"]),
    dict(cle="crosses", label="Crosses", famille="off", sens=+1, cands=[
        "player_season_crosses_90", "player_season_op_crosses_90"]),
    dict(cle="box_crosses", label="Box crosses %", famille="off", sens=+1, cands=[
        "player_season_box_cross_ratio"]),
    dict(cle="op_passes", label="OP passes", famille="off", sens=+1, cands=[
        "player_season_op_passes_90"]),
    dict(cle="passing_pct", label="Passing %", famille="off", sens=+1, cands=[
        "player_season_passing_ratio", "player_season_pass_completion_ratio"]),
    dict(cle="fouls", label="Fouls", famille="def", sens=-1, cands=[
        "player_season_fouls_90", "player_season_fouls_committed_90"]),
    dict(cle="cards", label="Cards", famille="def", sens=-1, calc=[
        "player_season_yellow_cards_90", "player_season_red_cards_90"]),
]

# ---------------------------------------------------------------------------
# CATALOGUE AUTOMATIQUE
# Les 28 métriques ci-dessus sont écrites à la main : libellé soigné, sources
# multiples, familles vérifiées. Mais l'abonnement en expose plus de 200. Les
# saisir une à une serait long et surtout intenable — chaque évolution de
# l'offre StatsBomb rendrait la liste fausse en silence.
# On les dérive donc du NOM de colonne, par règles. Une colonne déjà utilisée
# par une métrique manuelle n'est jamais reprise : pas de doublon.
# ---------------------------------------------------------------------------
PREFIXE = "player_season_"

# Identité et volumes de jeu : ce ne sont pas des métriques de performance.
ADMIN = {
    "minutes", "appearances", "starting_appearances", "90s_played",
    "average_minutes", "most_recent_match", "most_recent_match_position",
    "360_minutes",
}

# L'ordre compte : la première règle qui correspond l'emporte, donc les
# marqueurs les plus spécifiques (gardien) passent avant les plus larges.
REGLES_FAM = [
    ("gk",  ("gk_", "_gk", "goalkeeper", "save", "faced", "claim", "punch",
             "sweeper", "clcaa", "positive_outcome_score", "goals_conceded")),
    ("def", ("tackle", "interception", "block", "clearance", "pressure",
             "counterpress", "aggressive", "defensive_action", "aerial",
             "duel", "dribbled_past", "recover", "challenge", "obv_defensive",
             "fouls_90", "fouls_committed")),
    ("off", ("xg", "xa", "shot", "goal", "assist", "dribble", "carry", "cross",
             "box", "deep_", "key_pass", "through", "lbp", "obv_", "touches",
             "space", "directness", "transition", "f3_", "fhalf_", "long_ball",
             "forward_pass", "pass_into", "passes_into", "op_passes")),
]

# Axe à inverser : une valeur BASSE y vaut mieux. On n'y met QUE des choses
# indiscutablement subies ou fautives. Les passes vers l'arrière ou latérales
# en sont volontairement absentes : ce sont des descriptions de style, pas des
# défauts, et les compter comme tels imposerait un jugement que la donnée ne
# porte pas.
NEGATIF = ("turnover", "dispossess", "miscontrol", "error", "card", "fouls_90",
           "fouls_committed", "dribbled_past_90", "conceded", "faced")

ABREV = {
    "np": "NP", "xg": "xG", "xa": "xA", "obv": "OBV", "lbp": "LBP",
    "padj": "PAdj", "op": "OP", "sp": "SP", "gk": "GK", "f3": "F3",
    "fhalf": "F½", "psxg": "PSxG", "npxgxa": "NPxG+xA", "xgchain": "xGChain",
    "xgbuildup": "xGBuildup", "clcaa": "CLCAA", "da": "DA", "ot": "OT",
    "npot": "NPOT",
}
# Mots raccourcis : un libellé d'axe de radar qui dépasse la trentaine de
# caractères déborde sur ses voisins et rend la planche illisible.
# Le vocabulaire des métriques est celui de StatsBomb, donc anglais. Les
# raccourcis le restent : mélanger « Moy » et « Space Received » donnait des
# libellés bâtards, illisibles dans les deux langues.
COURT = {
    "average": "Avg", "avg": "Avg", "proportion": "Prop", "possession": "Poss",
    "received": "Recv", "distance": "Dist", "player": "", "actions": "Actions",
    "successful": "Succ", "completed": "Compl",
    "inside": "", "and": "+", "into": "→", "responsibility": "Resp",
    "weighted": "Wtd", "change": "Δ", "expectation": "Expected",
    "above": ">", "directness": "Direct", "expected": "Expected",
    "possessions": "Poss", "receipts": "Receipts",
}


# ---------------------------------------------------------------------------
# NOMS OFFICIELS StatsBomb
# Les libellés déduits du nom de colonne sont parfois opaques, parfois faux.
# `challenge_ratio` devenait « Challenge % » — introuvable pour qui cherche la
# défense en un contre un, que StatsBomb appelle « Tackle/Dribbled Past% ».
# Pire, `dribble_faced_ratio` tombait en famille GARDIEN et en axe inversé
# parce que la règle attrape le mot « faced » : c'est une métrique DÉFENSIVE
# où une valeur haute est bonne.
# Cette table reprend les intitulés du glossaire technique. `fam` et `sens` n'y
# figurent que là où la règle automatique se trompe.
# ---------------------------------------------------------------------------
OFFICIEL = {
    # -- duels défensifs
    "challenge_ratio":            ("Tackle/Dribbled Past %", "def", +1),
    "dribble_faced_ratio":        ("Dribbles Stopped %",     "def", +1),
    "dribbled_past_90":           ("Dribbled Past",          "def", -1),
    "aerial_ratio":               ("Aerial Win %",           "def", +1),
    "aerial_wins_90":             ("Aerial Wins",            "def", +1),
    "errors_90":                  ("Errors",                 "def", -1),
    # -- défense générale
    "aggressive_actions_90":      ("Aggressive Actions",     "def", +1),
    "ball_recoveries_90":         ("Ball Recoveries",        "def", +1),
    "fhalf_ball_recoveries_90":   ("Ball Recoveries A½",     "def", +1),
    "blocks_per_shot":            ("Blocks/Shot",            "def", +1),
    "clearances_90":              ("Clearances",             "def", +1),
    "padj_clearances_90":         ("PAdj Clearances",        "def", +1),
    "interceptions_90":           ("Interceptions",          "def", +1),
    "padj_interceptions_90":      ("PAdj Interceptions",     "def", +1),
    "tackles_90":                 ("Tackles",                "def", +1),
    "padj_tackles_90":            ("PAdj Tackles",           "def", +1),
    "tackles_and_interceptions_90":      ("Tackles + Int",   "def", +1),
    "padj_tackles_and_interceptions_90": ("PAdj Tackles + Int", "def", +1),
    "defensive_action_regains_90":       ("Defensive Regains", "def", +1),
    "da_aggressive_distance":     ("Def Action Dist",        "def", +1),
    "average_x_defensive_action": ("Def Action X",           "def", +1),
    "average_x_pressure":         ("Pressure X",             "def", +1),
    "counterpressures_90":        ("Counterpressures",       "def", +1),
    "counterpressure_regains_90": ("Counterpress Regains",   "def", +1),
    "padj_pressures_90":          ("PAdj Pressures",         "def", +1),
    "pressure_regains_90":        ("Pressure Regains",       "def", +1),
    "yellow_cards_90":            ("Yellow Cards",           "def", -1),
    "red_cards_90":               ("Red Cards",              "def", -1),
    # -- duels offensifs
    "turnovers_90":               ("Turnovers",              "off", -1),
    "dispossessions_90":          ("Dispossessed",           "off", -1),
    "failed_dribbles_90":         ("Failed Dribbles",        "off", -1),
    "dribble_ratio":              ("Dribble %",              "off", +1),
    "dribbles_90":                ("Dribbles",               "off", +1),
    "fouls_won_90":               ("Fouls Won",              "off", +1),
    # -- tirs et création
    "goal_conversion_ratio":      ("Goal Conversion %",      "off", +1),
    "shot_on_target_ratio":       ("Shooting %",             "off", +1),
    "shot_touch_ratio":           ("Shot Touch %",           "off", +1),
    "np_psxg_90":                 ("NP PSxG",                "off", +1),
    "op_xa_90":                   ("Open Play xG Assisted",  "off", +1),
    "sp_xa_90":                   ("Set Piece xG Assisted",  "off", +1),
    "op_key_passes_90":           ("Open Play Key Passes",   "off", +1),
    "sp_key_passes_90":           ("Set Piece Key Passes",   "off", +1),
    "op_assists_90":              ("Open Play Assists",      "off", +1),
    "sp_assists_90":              ("Set Piece Assists",      "off", +1),
    "assists_90":                 ("Assists",                "off", +1),
    "npxgxa_90":                  ("NP xG + xG Assisted",    "off", +1),
    "xgchain_90":                 ("xGChain",                "off", +1),
    "xgbuildup_90":               ("xGBuildup",              "off", +1),
    "op_xgchain_90":              ("OP xGChain",             "off", +1),
    "op_xgbuildup_90":            ("OP xGBuildup",           "off", +1),
    # -- corrections de classement : SUBIR la pression relève de la
    #    construction, pas de la défense. Ma règle attrapait le mot
    #    « pressure » et rangeait ces métriques de passe du mauvais côté.
    "pressured_long_balls_90":    ("Pressured Long Balls",   "off", +1),
    "unpressured_long_balls_90":  ("Unpressured Long Balls", "off", +1),
    "pressured_passing_ratio":    ("Pressured Passing %",    "off", +1),
    "pressured_pass_length_ratio":("Pressured Pass Length %", "off", +1),
    "pressured_change_in_pass_length": ("Pressured Δ Pass Length", "off", +1),
    "pass_into_pressure_ratio":   ("Pass Into Pressure %",   "off", -1),
    # -- libellés qui mélangeaient français et anglais
    "expected_defensive_actions_90":       ("Expected Def Actions", "def", +1),
    "defensive_actions_above_expectation_90": ("Def Actions > Expected", "def", +1),
    "clearance_90":               ("Clearances",             "def", +1),
    "fhalf_counterpressures_90":  ("Counterpressures A½",    "def", +1),
    "fhalf_counterpressures_ratio": ("Counterpressures A½ %", "def", +1),
    "fhalf_pressures_90":         ("Pressures A½",           "def", +1),
    "fhalf_pressures_ratio":      ("Pressures A½ %",         "def", +1),
}


def _fam(col):
    n = col.lower()
    for fam, mots in REGLES_FAM:
        if any(m in n for m in mots):
            return fam
    return "off"           # passe et possession : versant offensif du jeu


def _sens(col):
    return -1 if any(m in col.lower() for m in NEGATIF) else 1


def _libelle(col):
    base = col[len(PREFIXE):] if col.startswith(PREFIXE) else col
    ratio = base.endswith("_ratio")
    if ratio:
        base = base[:-6]
    if base.endswith("_90"):
        base = base[:-3]
    mots = []
    for m in base.split("_"):
        if m in ABREV:
            mots.append(ABREV[m])
        else:
            c = COURT.get(m, None)
            if c == "":
                continue
            mots.append(c if c else m.capitalize())
    lab = " ".join(mots)
    return lab + " %" if ratio else lab


def catalogue(colonnes, deja):
    """Colonnes exploitables non déjà couvertes par une métrique manuelle.

    Deux pièges évités ici.

    1. StatsBomb publie souvent le CUMUL et la CADENCE de la même chose —
       `xgchain` et `xgchain_90`. Retirer le suffixe pour former la clé les
       rendait identiques : six métriques se marchaient dessus et la sélection
       dans la page devenait imprévisible. On ne garde que la cadence quand elle
       existe ; le sélecteur « par 90 / total saison » reconstitue le cumul.

    2. La clé reste le nom de colonne complet, jamais tronqué : c'est le seul
       identifiant dont l'unicité soit garantie par la source elle-même."""
    bases = {c[len(PREFIXE):] for c in colonnes if c.startswith(PREFIXE)}
    avec_cadence = {b[:-3] for b in bases if b.endswith("_90")}
    out, vues = [], set()
    for c in sorted(colonnes):
        if not c.startswith(PREFIXE):
            continue
        base = c[len(PREFIXE):]
        if base in ADMIN or c in deja:
            continue
        if not base.endswith("_90") and base in avec_cadence:
            continue                       # cumul doublonnant une cadence
        cle = base[:-3] if base.endswith("_90") else base
        if cle in vues:                    # ceinture et bretelles
            cle = base
        vues.add(cle)
        off = OFFICIEL.get(base)
        lab = off[0] if off else _libelle(c)
        fam = off[1] if off else _fam(c)
        sn = off[2] if off else _sens(c)
        out.append(dict(cle=cle, label=lab, sens=sn, famille=fam, cands=[c]))
    return out


# Colonnes d'identité — mêmes candidats, même méthode.
IDENT = {
    "id":      ["player_id"],
    "nom":     ["player_name"],
    "equipe":  ["team_name", "team"],
    "poste":   ["primary_position", "player_season_most_recent_match_position"],
    "minutes": ["player_season_minutes"],
    "m90":     ["player_season_90s_played"],
    "matchs":  ["player_season_appearances"],
    "titu":    ["player_season_starting_appearances"],
    # Taille et poids mesurés par StatsBomb : ils font autorité sur les fiches
    # LFP et Transfermarkt, qui se contredisent régulièrement.
    "taille":  ["player_height"],
    "poids":   ["player_weight"],
    # Part des passes du pied gauche, calculée sur les actions RÉELLES du match.
    # Le glossaire StatsBomb tranche ainsi : « Players can be considered
    # left-footed when this value is over 60% (and right-footed at less than
    # 40%) ». Entre les deux, le joueur est ambidextre et rien n'est conclu.
    "pied_g":  ["player_season_left_foot_ratio"],
}


def resolve_season():
    """Saison cible = argv[1], sinon $SEASON, sinon CURRENT_SEASON."""
    label = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "")).strip()
    if not label:
        label = CURRENT_SEASON
    sid = SEASON_IDS.get(label)
    if sid is None:
        print(f"ERREUR : saison « {label} » inconnue. Connues : "
              f"{', '.join(sorted(SEASON_IDS))}", file=sys.stderr)
        sys.exit(1)
    # TOUJOURS suffixé, sans exception. Les autres build_*.py écrivent un nom nu
    # quand la saison demandée vaut CURRENT_SEASON — et season.js, qui ne lit que
    # des noms suffixés, ne trouve alors rien. C'est exactement ce qui est arrivé
    # au premier run 2025-2026 : le fichier a bien été produit, sous le nom
    # individual.json, invisible pour le site.
    out = f"individual_{label}.json"
    return label, sid, out


def premier_present(cands, colonnes):
    """Première colonne candidate réellement présente. Aucune supposition."""
    for c in cands:
        if c in colonnes:
            return c
    return None


def nombre(v):
    """float exploitable, ou None. NaN et vides deviennent None, pas 0 :
    un 0 signifierait « le joueur n'en a fait aucun », or on ne le sait pas."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        print("ERREUR : SB_USERNAME / SB_PASSWORD manquants.", file=sys.stderr)
        sys.exit(1)

    label, sid, out_path = resolve_season()
    print(f"Saison {label} (season_id={sid}) -> {out_path}")

    print("Appel player_season_stats…")
    df = sb.player_season_stats(competition_id=COMPETITION_ID, season_id=sid)
    if df is None or len(df) == 0:
        print("ERREUR : aucune ligne renvoyée.", file=sys.stderr)
        sys.exit(1)

    colonnes = list(df.columns)
    print(f"{len(df)} joueurs, {len(colonnes)} colonnes disponibles.")

    # ---- résolution des colonnes d'identité --------------------------------
    ident_res, ident_manq = {}, []
    for cle, cands in IDENT.items():
        c = premier_present(cands, colonnes)
        if c:
            ident_res[cle] = c
        else:
            ident_manq.append(cle)
    if "id" not in ident_res or "nom" not in ident_res:
        print("ERREUR : impossible d'identifier les joueurs (player_id/player_name "
              "absents). Colonnes reçues : " + ", ".join(colonnes[:40]), file=sys.stderr)
        sys.exit(1)

    # ---- résolution des métriques ------------------------------------------
    resolues, non_resolues = [], []
    for m in METRIQUES:
        if m.get("calc"):
            trouvees = [c for c in m["calc"] if c in colonnes]
            if len(trouvees) == len(m["calc"]):
                resolues.append(dict(m, source=trouvees, mode="somme"))
            else:
                manquantes = [c for c in m["calc"] if c not in colonnes]
                non_resolues.append(dict(cle=m["cle"], label=m["label"],
                                         attendu=manquantes,
                                         proches=suggestions(manquantes, colonnes)))
            continue
        c = premier_present(m["cands"], colonnes)
        if c:
            resolues.append(dict(m, source=[c], mode="direct"))
        else:
            non_resolues.append(dict(cle=m["cle"], label=m["label"],
                                     attendu=m["cands"],
                                     proches=suggestions(m["cands"], colonnes)))

    manuelles = len(resolues)

    # Puis tout le reste du catalogue. Ces métriques-là sont exactes par
    # construction — on ne retient que des colonnes réellement présentes.
    deja = set()
    for m in resolues:
        deja.update(m["source"])
    for m in catalogue(colonnes, deja):
        resolues.append(dict(m, source=m["cands"], mode="direct"))

    print(f"\nMétriques résolues : {manuelles}/{len(METRIQUES)} écrites à la main"
          f" + {len(resolues) - manuelles} issues du catalogue"
          f" = {len(resolues)} au total")
    for m in resolues[:manuelles]:
        print(f"  ✓ {m['label']:<16} <- {' + '.join(m['source'])}")
    import collections as _c
    rep = _c.Counter(m["famille"] for m in resolues)
    print("  familles :", dict(rep))
    if non_resolues:
        print(f"\nMétriques NON résolues : {len(non_resolues)}")
        for m in non_resolues:
            pr = ", ".join(m["proches"][:3]) or "aucune colonne ressemblante"
            print(f"  ✗ {m['label']:<16} attendu {m['attendu'][0]}")
            print(f"      colonnes proches : {pr}")

    # ---- extraction --------------------------------------------------------
    joueurs = []
    for _, r in df.iterrows():
        p = {
            "id": r.get(ident_res["id"]),
            "nom": r.get(ident_res["nom"]),
        }
        for cle in ("equipe", "poste"):
            if cle in ident_res:
                v = r.get(ident_res[cle])
                p[cle] = None if v != v else v          # NaN -> None
        for cle in ("minutes", "m90", "matchs", "titu", "taille", "poids", "pied_g"):
            if cle in ident_res:
                p[cle] = nombre(r.get(ident_res[cle]))

        vals = {}
        for m in resolues:
            if m["mode"] == "somme":
                parts = [nombre(r.get(c)) for c in m["source"]]
                v = None if all(x is None for x in parts) else sum(x or 0 for x in parts)
            else:
                v = nombre(r.get(m["source"][0]))
            if v is not None:
                vals[m["cle"]] = round(v, 4)
        p["vals"] = vals
        joueurs.append(p)

    joueurs.sort(key=lambda p: (-(p.get("minutes") or 0), str(p.get("nom"))))

    postes = {}
    for p in joueurs:
        postes[p.get("poste") or "?"] = postes.get(p.get("poste") or "?", 0) + 1

    sortie = {
        "season": label,
        "source": "StatsBomb player_season_stats",
        "updated": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%d %H:%M UTC"),
        # `famille` pilote le classement de la page : défensif à gauche du
        # radar, offensif à droite, gardien à part.
        "metrics": [{"cle": m["cle"], "label": m["label"], "sens": m["sens"],
                     "famille": m.get("famille", "off"),
                     "source": m["source"]} for m in resolues],
        "postes": dict(sorted(postes.items(), key=lambda kv: -kv[1])),
        "players": joueurs,
        # Le diagnostic voyage AVEC les données : sans lui, une métrique absente
        # se lirait comme une métrique à zéro.
        "diagnostic": {
            "colonnes_disponibles": colonnes,
            "identite_manquante": ident_manq,
            "non_resolues": non_resolues,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{out_path} écrit : {len(joueurs)} joueurs, "
          f"{len(resolues)} métriques, {len(postes)} postes.")


def suggestions(attendus, colonnes):
    """Colonnes réelles les plus proches — pour trancher à la main, jamais
    appliquées automatiquement : un mauvais rapprochement produirait un radar
    faux et silencieux."""
    out = []
    for a in attendus:
        out += difflib.get_close_matches(a, colonnes, n=3, cutoff=0.6)
    vus, uniq = set(), []
    for c in out:
        if c not in vus:
            vus.add(c)
            uniq.append(c)
    return uniq


if __name__ == "__main__":
    main()
