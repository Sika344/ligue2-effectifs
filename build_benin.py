#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_benin.py — recense les joueurs BÉNINOIS présents dans les données
StatsBomb et produit un classeur Excel.

Sans rapport avec le site : ce script ne lit ni n'écrit aucun fichier du
dépôt. Il produit joueurs_benin.xlsx, récupéré comme artefact du run.

================================================================ LA MÉTHODE
StatsBomb ne donne pas « Bénin » en clair : `player_season_stats` porte un
`country_id` numérique et rien d'autre. On procède donc en deux temps.

1. IDENTIFIER le code pays. On cherche des internationaux béninois connus
   dans les compétitions couvertes, on lit leur `country_id`, et on retient
   le code le plus fréquent. Une seule correspondance ne suffirait pas : un
   homonyme fausserait tout le reste.

2. BALAYER les compétitions et récolter tous les joueurs portant ce code.

Si l'étape 1 échoue, le script S'ARRÊTE sans rien écrire. Un classeur vide
serait ambigu — on ne saurait pas s'il n'y a pas de Béninois ou si le filtre
n'a pas fonctionné.

============================================================== LA COUVERTURE
La licence couvre une soixantaine de compétitions, essentiellement
européennes, plus le Brésil, l'Argentine, le Mexique, la MLS et l'Arabie
saoudite. Une bonne partie des internationaux béninois évolue ailleurs —
Égypte, Tunisie, Maroc, Nigéria, Afrique du Sud, Roumanie, Chypre,
Luxembourg — et n'apparaîtra donc PAS, quoi qu'on fasse.

Le second onglet liste la sélection connue et marque, pour chaque joueur,
s'il a été retrouvé. C'est la seule façon honnête de montrer ce qui manque.

USAGE :
    SB_USERNAME='…' SB_PASSWORD='…' SAISONS=3 python build_benin.py
"""

import os
import sys
import datetime
import collections

from statsbombpy import sb

SORTIE = "joueurs_benin.xlsx"
NB_SAISONS = int(os.environ.get("SAISONS", "3"))

# Internationaux béninois servant à identifier le code pays. Choisis parce
# qu'ils évoluent dans des championnats couverts par la licence, et écrits
# sans accent : la comparaison se fait sur une forme normalisée.
TEMOINS = [
    "Steve Mounie", "Andreas Hountondji", "Junior Olaitan", "Moise Adilehou",
    "Mohamed Tijani", "Imourane Hassane", "Matteo Ahlinvi", "Cedric Hountondji",
    "Olivier Verdon", "Jodel Dossou", "David Kiki", "Sessi D'Almeida",
    "Aiyegun Tosin", "Yohan Roche", "Saturnin Allagbe",
]

# Sélection béninoise de mars 2025 (source : CAF). Sert de liste de référence
# pour le second onglet. Le club est celui de l'époque : un joueur a pu
# changer depuis, ce qui explique certains « non retrouvé ».
SELECTION = [
    ("Saturnin Allagbé", "Gardien", "Botev Vratsa", "Bulgarie"),
    ("Marcel Dandjinou", "Gardien", "JDR Stars", "Afrique du Sud"),
    ("Serges Obassa", "Gardien", "Remo Stars", "Nigéria"),
    ("Moïse Adilehou", "Défenseur", "Laval", "France"),
    ("Brandon Agounon", "Défenseur", "Châteauroux", "France"),
    ("Rodrigue Fassinou", "Défenseur", "Coton Sport", "Bénin"),
    ("David Kiki", "Défenseur", "Steaua Bucarest", "Roumanie"),
    ("Rachid Moumini", "Défenseur", "Ayéma", "Bénin"),
    ("Tamimou Ouorou", "Défenseur", "Hatta", "Émirats arabes unis"),
    ("Yohan Roche", "Défenseur", "Petrolul 52", "Roumanie"),
    ("Rabiou Sankamao", "Défenseur", "Wydad Fès", "Maroc"),
    ("Mohamed Tijani", "Défenseur", "Yverdon Sport", "Suisse"),
    ("Mattéo Ahlinvi", "Milieu", "Arsenal Tula", "Russie"),
    ("Mariano Ahouangbo", "Milieu", "Soliman", "Tunisie"),
    ("Gislain Ahoudo", "Milieu", "Gabès", "Tunisie"),
    ("Samadou Attidjikou", "Milieu", "Al Masry", "Égypte"),
    ("Sessi d'Almeida", "Milieu", "Apollon Limassol", "Chypre"),
    ("Dodo Dokou", "Milieu", "Smouha", "Égypte"),
    ("Imourane Hassane", "Milieu", "Grasshoppers Zurich", "Suisse"),
    ("Jodel Dossou", "Attaquant", "Victoria Rosport", "Luxembourg"),
    ("Candas Fiogbé", "Attaquant", "Atalanta", "Italie"),
    ("Andréas Hountondji", "Attaquant", "Standard Liège", "Belgique"),
    ("Steve Mounié", "Attaquant", "FC Augsburg", "Allemagne"),
    ("Junior Olaitan", "Attaquant", "Grenoble", "France"),
    ("Steve-Waren Traoré", "Attaquant", "Haka", "Finlande"),
    # Absents de cette liste pour blessure ou raison disciplinaire, mais
    # internationaux béninois : on les garde, ils peuvent être dans les données.
    ("Aiyegun Tosin", "Attaquant", "—", "France"),
    ("Cédric Hountondji", "Défenseur", "—", "France"),
    ("Olivier Verdon", "Défenseur", "—", "—"),
]

# Colonnes du classeur : (clé StatsBomb, intitulé, thème, décimales).
# `None` en clé = champ d'identité calculé dans le script.
COLONNES = [
    (None,                                    "Joueur",              "Identité", None),
    (None,                                    "Équipe",              "Identité", None),
    (None,                                    "Compétition",         "Identité", None),
    (None,                                    "Pays",                "Identité", None),
    (None,                                    "Saison",              "Identité", None),
    ("primary_position",                      "Poste",               "Identité", None),
    (None,                                    "Âge",                 "Identité", 0),
    ("player_season_minutes",                 "Minutes",             "Identité", 0),
    ("player_season_appearances",             "Matchs",              "Identité", 0),
    ("player_season_starting_appearances",    "Titularisations",     "Identité", 0),

    ("player_season_goals_90",                "Buts /90",            "Offensif", 2),
    ("player_season_assists_90",              "Passes D /90",        "Offensif", 2),
    ("player_season_np_xg_90",                "xG hors pen /90",     "Offensif", 2),
    ("player_season_shots_90",                "Tirs /90",            "Offensif", 2),
    ("player_season_np_xg_per_shot",          "xG par tir",          "Offensif", 3),
    ("player_season_touches_inside_box_90",   "Touches surface /90", "Offensif", 2),
    ("player_season_conversion_ratio",        "Conversion %",        "Offensif", 3),

    ("player_season_xa_90",                   "xA /90",              "Création", 2),
    ("player_season_key_passes_90",           "Passes clés /90",     "Création", 2),
    ("player_season_op_passes_into_box_90",   "Passes surface /90",  "Création", 2),
    ("player_season_obv_pass_90",             "OBV passe /90",       "Création", 3),
    ("player_season_op_xgchain_90",           "xGChain /90",         "Création", 3),

    ("player_season_deep_progressions_90",    "Progressions /90",    "Progression", 2),
    ("player_season_carries_90",              "Conduites /90",       "Progression", 2),
    ("player_season_dribbles_90",             "Dribbles /90",        "Progression", 2),
    ("player_season_dribble_ratio",           "Dribbles réussis %",  "Progression", 3),
    ("player_season_passing_ratio",           "Passes réussies %",   "Progression", 3),

    ("player_season_tackles_and_interceptions_90", "Tacles + inter. /90", "Défensif", 2),
    ("player_season_padj_pressures_90",       "Pressions ajustées /90", "Défensif", 2),
    ("player_season_counterpressures_90",     "Contre-pressions /90", "Défensif", 2),
    ("player_season_ball_recoveries_90",      "Récupérations /90",   "Défensif", 2),
    ("player_season_aerial_ratio",            "Duels aériens %",     "Défensif", 3),
    ("player_season_aerial_wins_90",          "Duels aériens gagnés /90", "Défensif", 2),
    ("player_season_challenge_ratio",         "Duels 1v1 gagnés %",  "Défensif", 3),
    ("player_season_clearances_90",           "Dégagements /90",     "Défensif", 2),

    ("player_season_yellow_cards_90",         "Jaunes /90",          "Discipline", 3),
    ("player_season_red_cards_90",            "Rouges /90",          "Discipline", 3),
    ("player_season_fouls_90",                "Fautes /90",          "Discipline", 2),
]

THEMES = {
    "Identité":    "FFE8EAF0",
    "Offensif":    "FFE6F1FB",
    "Création":    "FFEAF3DE",
    "Progression": "FFFAEEDA",
    "Défensif":    "FFFAECE7",
    "Discipline":  "FFF1EFE8",
}


def nn(s):
    import unicodedata
    import re
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def val(row, cle):
    if cle not in row:
        return None
    v = row[cle]
    if v is None or v != v:
        return None
    return v


def age_de(dob):
    try:
        n = datetime.date.fromisoformat(str(dob)[:10])
    except Exception:
        return None
    a = datetime.date.today()
    return a.year - n.year - ((a.month, a.day) < (n.month, n.day))


def main():
    if not (os.environ.get("SB_USERNAME") and os.environ.get("SB_PASSWORD")):
        raise SystemExit("ERREUR : SB_USERNAME / SB_PASSWORD manquants.")

    comps = sb.competitions()
    print("Licence : %d combinaisons compétition-saison" % len(comps))

    # Les NB_SAISONS saisons les plus récentes de chaque compétition.
    cibles = []
    for cid, grp in comps.groupby("competition_id"):
        g = grp.sort_values("season_id", ascending=False).head(NB_SAISONS)
        for _, r in g.iterrows():
            cibles.append((int(cid), int(r["season_id"]),
                           str(r.get("competition_name") or ""),
                           str(r.get("country_name") or ""),
                           str(r.get("season_name") or "")))
    print("%d compétitions-saisons à balayer (%d dernières saisons)"
          % (len(cibles), NB_SAISONS))

    temoins = {nn(t) for t in TEMOINS}
    votes = collections.Counter()
    lignes = []
    cache = {}
    echecs = 0

    for i, (cid, sid, cnom, pays, snom) in enumerate(cibles, 1):
        try:
            df = sb.player_season_stats(competition_id=cid, season_id=sid)
        except Exception:
            echecs += 1
            continue
        if df is None or not len(df):
            continue
        cache[(cid, sid)] = (df, cnom, pays, snom)
        for _, r in df.iterrows():
            if nn(r.get("player_name")) in temoins:
                c = r.get("country_id")
                if c is not None and c == c:
                    votes[int(c)] += 1
        if i % 25 == 0:
            print("   %d/%d balayées…" % (i, len(cibles)))

    if not votes:
        raise SystemExit(
            "ÉCHEC : aucun international béninois retrouvé parmi les témoins.\n"
            "Impossible d'identifier le code pays — rien n'a été écrit. "
            "Vérifie que la licence couvre bien des championnats où ils jouent.")

    code, n = votes.most_common(1)[0]
    print("\nCode pays retenu : %s (%d correspondances parmi les témoins)" % (code, n))
    if len(votes) > 1:
        print("   !! autres codes vus : %s — un homonyme a pu fausser un vote"
              % dict(votes.most_common()[1:4]))

    for (cid, sid), (df, cnom, pays, snom) in cache.items():
        for _, r in df.iterrows():
            c = r.get("country_id")
            if c is None or c != c or int(c) != code:
                continue
            ligne = {"Compétition": cnom, "Pays": pays, "Saison": snom}
            ligne["Joueur"] = r.get("player_name")
            ligne["Équipe"] = r.get("team_name")
            ligne["Âge"] = age_de(r.get("birth_date"))
            for cle, titre, _theme, _dec in COLONNES:
                if cle:
                    ligne[titre] = val(r, cle)
            lignes.append(ligne)

    # Un joueur peut figurer dans plusieurs compétitions la même saison
    # (championnat + coupe d'Europe) : ce sont des lignes distinctes, voulues.
    lignes.sort(key=lambda x: (nn(x.get("Joueur")), str(x.get("Saison")),
                               str(x.get("Compétition"))))
    noms = {nn(x["Joueur"]) for x in lignes}
    print("%d lignes | %d joueurs distincts | %d compétitions illisibles"
          % (len(lignes), len(noms), echecs))

    ecrire(lignes, noms, code)


def ecrire(lignes, noms, code):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Joueurs"

    gris = Side(style="thin", color="FFD0D0D0")
    bord = Border(bottom=gris)

    # Deux lignes d'en-tête : le thème au-dessus, l'intitulé en dessous.
    for j, (cle, titre, theme, dec) in enumerate(COLONNES, 1):
        a = ws.cell(row=1, column=j, value=theme)
        a.font = Font(name="Arial", size=9, bold=True, color="FF4A4A4A")
        a.fill = PatternFill("solid", fgColor=THEMES.get(theme, "FFFFFFFF"))
        a.alignment = Alignment(horizontal="center")
        b = ws.cell(row=2, column=j, value=titre)
        b.font = Font(name="Arial", size=10, bold=True)
        b.fill = PatternFill("solid", fgColor=THEMES.get(theme, "FFFFFFFF"))
        b.alignment = Alignment(horizontal="center", wrap_text=True, vertical="center")
        b.border = bord

    for i, l in enumerate(lignes, 3):
        for j, (cle, titre, theme, dec) in enumerate(COLONNES, 1):
            c = ws.cell(row=i, column=j, value=l.get(titre))
            c.font = Font(name="Arial", size=10)
            if dec is not None:
                c.number_format = "0" if dec == 0 else "0." + "0" * dec
    ws.freeze_panes = "C3"
    ws.auto_filter.ref = "A2:%s%d" % (get_column_letter(len(COLONNES)), max(2, len(lignes) + 2))

    larg = {"Joueur": 26, "Équipe": 22, "Compétition": 24, "Pays": 14, "Saison": 12, "Poste": 22}
    for j, (cle, titre, theme, dec) in enumerate(COLONNES, 1):
        ws.column_dimensions[get_column_letter(j)].width = larg.get(titre, 13)

    # --- onglet 2 : la sélection connue, et ce qu'on en a retrouvé
    ws2 = wb.create_sheet("Sélection Bénin")
    ws2["A1"] = ("Sélection béninoise de mars 2025 (source : CAF). La colonne de droite dit si "
                 "le joueur a été retrouvé dans les données StatsBomb couvertes par la licence.")
    ws2["A1"].font = Font(name="Arial", size=9, italic=True, color="FF666666")
    ws2.merge_cells("A1:E1")
    for j, t in enumerate(["Joueur", "Poste", "Club (mars 2025)", "Pays du club",
                           "Présent dans StatsBomb"], 1):
        c = ws2.cell(row=2, column=j, value=t)
        c.font = Font(name="Arial", size=10, bold=True)
        c.fill = PatternFill("solid", fgColor="FFE8EAF0")
        c.border = bord
    for i, (nom, poste, club, pays) in enumerate(SELECTION, 3):
        trouve = nn(nom) in noms
        for j, v in enumerate([nom, poste, club, pays, "oui" if trouve else "non"], 1):
            c = ws2.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10,
                          color=("FF1B7F4B" if (j == 5 and trouve) else
                                 "FFB3261E" if j == 5 else "FF000000"))
    for j, w in enumerate([26, 14, 24, 20, 22], 1):
        ws2.column_dimensions[get_column_letter(j)].width = w
    ws2.freeze_panes = "A3"

    # --- onglet 3 : comment ce fichier a été fabriqué
    ws3 = wb.create_sheet("Méthode")
    notes = [
        "Comment ce fichier a été fabriqué",
        "",
        "Source : StatsBomb, point d'entrée player_season_stats, via la licence du compte.",
        "Généré le : " + datetime.datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"),
        "Profondeur : les %d dernières saisons de chaque compétition couverte." % NB_SAISONS,
        "",
        "Identification des Béninois",
        "StatsBomb ne donne pas le nom du pays, seulement un code numérique. Ce code a été",
        "identifié en cherchant des internationaux béninois connus dans les données, puis en",
        "retenant le code le plus fréquent parmi eux. Code retenu : %s." % code,
        "",
        "Ce que le fichier ne contient pas",
        "La licence couvre une soixantaine de compétitions, surtout européennes. Les joueurs",
        "évoluant en Égypte, Tunisie, Maroc, Nigéria, Afrique du Sud, Roumanie, Chypre ou au",
        "Luxembourg n'y figurent pas, quelle que soit leur notoriété. L'onglet « Sélection",
        "Bénin » montre nommément qui manque.",
        "",
        "Lecture des colonnes",
        "Les valeurs suivies de « /90 » sont des cadences par 90 minutes, pas des totaux.",
        "Les pourcentages sont des fractions : 0,45 se lit 45 %.",
        "Un joueur ayant disputé peu de minutes a des cadences très instables : regarde",
        "toujours la colonne Minutes avant de comparer deux joueurs.",
    ]
    for i, t in enumerate(notes, 1):
        c = ws3.cell(row=i, column=1, value=t)
        c.font = Font(name="Arial", size=10,
                      bold=(i == 1 or t in ("Identification des Béninois",
                                            "Ce que le fichier ne contient pas",
                                            "Lecture des colonnes")))
    ws3.column_dimensions["A"].width = 100

    wb.save(SORTIE)
    print("\n%s écrit : %d lignes, %d joueurs." % (SORTIE, len(lignes), len(noms)))


if __name__ == "__main__":
    main()
