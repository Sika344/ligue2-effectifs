#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_mauritanie.py — recense les joueurs MAURITANIENS présents dans les
données StatsBomb et produit un classeur Excel.

Calqué sur build_benin.py : mêmes onglets, mêmes colonnes, même méthode.
Seuls changent le pays visé, les témoins et la liste de sélection.

Sans rapport avec le site : ce script ne lit ni n'écrit aucun fichier du
dépôt. Il produit joueurs_mauritanie.xlsx, récupéré comme artefact du run.

================================================================ LA MÉTHODE
StatsBomb ne donne pas « Mauritanie » en clair : `player_season_stats` porte
un `country_id` numérique et rien d'autre. On procède donc en deux temps.

1. IDENTIFIER le code pays. On cherche des internationaux mauritaniens
   connus dans les compétitions couvertes, on lit leur `country_id`, et on
   retient le code porté par le plus de témoins DISTINCTS.

2. BALAYER les compétitions et récolter tous les joueurs portant ce code.

Si l'étape 1 échoue, le script S'ARRÊTE sans rien écrire. Un classeur vide
serait ambigu — on ne saurait pas s'il n'y a pas de Mauritaniens ou si le
filtre n'a pas fonctionné.

=========================================== POURQUOI C'EST PLUS DÉLICAT ICI
Deux différences par rapport au Bénin, qui ont dicté les garde-fous ajoutés.

a) L'HOMONYMIE. Beaucoup d'internationaux mauritaniens portent des noms
   très répandus en Afrique de l'Ouest — Mamadou Diop, Lamine Ba, Ibrahima
   Keïta, Khadim Diaw, Mamadou Fofana. Un homonyme sénégalais ou malien
   voterait pour le MAUVAIS code pays. Ces noms sont donc volontairement
   ÉCARTÉS des témoins, malgré leur présence en sélection : ils restent dans
   l'onglet 2, mais ne servent pas à identifier le pays.

b) LA BINATIONALITÉ. Une partie de la sélection est née en France. Si
   StatsBomb enregistrait le pays de naissance, ces joueurs voteraient pour
   la France. Le fichier Bénin a montré que ce n'est pas le cas — Cédric
   Hountondji, né à Marseille, y portait bien le code béninois — mais on ne
   le suppose pas : le script IMPRIME le détail du vote, nom par nom et code
   par code, pour qu'on puisse le relire.

D'où deux exigences qui n'existaient pas dans la version Bénin :
   - au moins TEMOINS_MINIMUM témoins distincts pour retenir un code ;
   - la variable CODE_PAYS permet de forcer le code à la main si le vote
     ressort ambigu, sans retoucher le script.

============================================================== LA COUVERTURE
La licence couvre une soixantaine de compétitions, essentiellement
européennes, plus le Brésil, l'Argentine, le Mexique, la MLS et l'Arabie
saoudite. Une bonne partie de la sélection mauritanienne évolue ailleurs —
Mauritanie, Maroc, Koweït, Égypte, Arabie du Golfe — et n'apparaîtra donc
PAS, quoi qu'on fasse.

Le second onglet liste la sélection connue et marque, pour chaque joueur,
s'il a été retrouvé. C'est la seule façon honnête de montrer ce qui manque.

USAGE :
    SB_USERNAME='…' SB_PASSWORD='…' SAISONS=3 python build_mauritanie.py
    SB_USERNAME='…' SB_PASSWORD='…' CODE_PAYS=142 python build_mauritanie.py
"""

import os
import sys
import datetime
import collections

from statsbombpy import sb

SORTIE = "joueurs_mauritanie.xlsx"
NB_SAISONS = int(os.environ.get("SAISONS", "3"))

# Nombre de témoins DISTINCTS exigés pour retenir un code pays. À 1, un seul
# homonyme suffirait à emporter le vote ; à 3, il en faudrait trois qui se
# trompent de la même façon.
TEMOINS_MINIMUM = int(os.environ.get("TEMOINS_MINIMUM", "3"))

# Permet de forcer le code pays si le vote ressort ambigu. Vide = vote normal.
CODE_FORCE = os.environ.get("CODE_PAYS", "").strip()

# Internationaux mauritaniens servant à identifier le code pays. Écrits sans
# accent : la comparaison se fait sur une forme normalisée.
#
# CRITÈRE DE SÉLECTION : un nom distinctif, peu susceptible d'être porté par
# un homonyme sénégalais, malien ou guinéen dans les mêmes compétitions. Sont
# ÉCARTÉS pour cette raison, bien qu'internationaux mauritaniens :
#   Mamadou Diop, Babacar Diop, Babacar Niasse, Lamine Ba, Ibrahima Keita,
#   Khadim Diaw, Baila Diallo, Mamadou Diallo, Mamadou Fofana.
# Mamadou Fofana est le cas d'école : il existe un Mamadou Fofana malien,
# défenseur passé par Amiens et Metz, donc dans des compétitions couvertes.
TEMOINS = [
    "Djeidi Gassama", "Aboubakary Koita", "Jordan Lefort", "Bahmed Deuff",
    "Hemeya Tanji", "Aboubakar Kamara", "El Hacen El Id", "Oumar Ngom",
    "Papa Ndiaga Yade", "Abdoullah Ba", "Idrissa Thiam", "Sidi Bouna Amar",
    "Ahmed Salem M'Bareck", "Dawda Camara", "Mohamed Ali Diadie",
    "Beyatt Lekwiri", "Mohamed Dellahi Yali", "Souleymane Anne",
    "Nouh Med El Abd", "Yacoub Sidi", "Demine Saleck", "Mohsine Bodda",
    "Abdalahi Mahmoud", "Aly Abeid",
]

# Sélection mauritanienne de septembre 2026, éliminatoires de la CAN 2027
# (matchs contre la Centrafrique le 24 et le Bénin le 29). Sert de liste de
# référence pour le second onglet.
#
# Le poste est celui du communiqué repris par AfricaSoccer. Attention : la
# FFRIM classait Ngom, Mahmoud, Sidi, Deuff et Bodda parmi les DÉFENSEURS,
# là où ce communiqué en fait des milieux. La répartition annoncée (3 gardiens,
# 9 défenseurs, 7 milieux, 8 attaquants) ne colle avec aucune des deux. Le
# poste est donc indicatif : il ne sert à rien dans le calcul, seule la
# colonne « Poste » de l'onglet 1, qui vient de StatsBomb, est fiable.
#
# Le club n'était publié que pour une partie du groupe ; « — » signifie
# « non publié dans la source », pas « sans club ». Il n'entre pas non plus
# dans le calcul : la correspondance se fait sur le nom.
SELECTION = [
    ("Babacar Niasse", "Gardien", "Difaâ Hassani El Jadida", "Maroc"),
    ("Mamadou Diop", "Gardien", "AJ Auxerre", "France"),
    ("Babacar Diop", "Gardien", "FC Nouadhibou", "Mauritanie"),

    ("Lamine Ba", "Défenseur", "—", "—"),
    ("Jordan Lefort", "Défenseur", "—", "—"),
    ("Demine Saleck", "Défenseur", "—", "—"),
    ("Mohamed Ali Diadie", "Défenseur", "—", "—"),
    ("Nouh Med El Abd", "Défenseur", "—", "—"),
    ("Ibrahima Keita", "Défenseur", "—", "—"),
    ("Aly Abeid", "Défenseur", "—", "—"),
    ("Khadim Diaw", "Défenseur", "—", "—"),
    ("Baila Diallo", "Défenseur", "—", "—"),

    ("Oumar Ngom", "Milieu", "US Lecce", "Italie"),
    ("Abdalahi Mahmoud", "Milieu", "FC Nouadhibou", "Mauritanie"),
    ("Yacoub Sidi", "Milieu", "Al-Nasr", "Koweït"),
    ("Bahmed Deuff", "Milieu", "Royal Antwerp", "Belgique"),
    ("Mohsine Bodda", "Milieu", "AS Douanes", "Mauritanie"),
    ("Mamadou Fofana", "Milieu", "Blau-Weiss Linz", "Autriche"),
    ("Abdoullah Ba", "Milieu", "—", "—"),

    ("Aboubakary Koita", "Attaquant", "—", "—"),
    ("Djeidi Gassama", "Attaquant", "—", "—"),
    ("Papa Ndiaga Yade", "Attaquant", "—", "—"),
    ("Mamadou Diallo", "Attaquant", "—", "—"),
    ("Idrissa Thiam", "Attaquant", "—", "—"),
    ("Hemeya Tanji", "Attaquant", "—", "—"),
    ("Ahmed Salem M'Bareck", "Attaquant", "—", "—"),
    ("Dawda Camara", "Attaquant", "—", "—"),

    # Absents de cette liste, mais internationaux mauritaniens connus : on les
    # garde, ils peuvent être dans les données.
    ("Aboubakar Kamara", "Attaquant", "—", "—"),
    ("El Hacen El Id", "Milieu", "—", "—"),
    ("Sidi Bouna Amar", "Attaquant", "—", "—"),
    ("Beyatt Lekwiri", "Défenseur", "—", "—"),
]

# Colonnes du classeur : (clé StatsBomb, intitulé, thème, décimales).
# `None` en clé = champ d'identité calculé dans le script.
# Strictement identiques à celles du fichier Bénin, demande explicite.
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

    # --- BLOC SOUS PRESSION -------------------------------------------------
    # Le cœur de la demande : à quel point le joueur se dégrade quand on vient
    # le chercher. Les trois premières colonnes vont ensemble et se lisent
    # ensemble — l'écart seul ne veut rien dire. Perdre 5 points en partant de
    # 92 % n'est pas perdre 5 points en partant de 61 %.
    #
    # Une clé peut être un TUPLE : le script prend la première qui existe
    # réellement dans les données. StatsBomb a renommé ces champs au fil des
    # versions d'API et je n'ai pas pu vérifier lequel répond sur ta licence
    # sans lancer le script. Plutôt que de parier sur un nom, on les essaie
    # tous, et le run imprime la liste exacte des colonnes « pressure » vues.
    (("player_season_pressured_passing_ratio",
      "player_season_pressured_pass_ratio"),  "Passes sous pression %",   "Sous pression", 3),
    (("player_season_unpressured_passing_ratio",
      "player_season_unpressured_pass_ratio"), "Passes sans pression %",  "Sous pression", 3),
    # Calculée dans le script : sous pression − sans pression. NÉGATIVE pour
    # presque tout le monde ; c'est son ampleur qui parle. Proche de zéro =
    # le joueur ne se dégrade pas quand il est pressé.
    (None,                                    "Écart sous pression",      "Sous pression", 3),
    # Le réflexe de dégagement : balancer long dès qu'on est pressé. Une
    # cadence élevée ici, avec un écart très négatif, dessine le même joueur.
    (("player_season_pressured_long_balls_90",
      "player_season_pressured_long_ball_90"), "Longs ballons sous pression /90", "Sous pression", 2),
    # Combien de fois il est pressé, tout simplement. Sert de dénominateur de
    # lecture : un écart calculé sur trois ballons pressés ne vaut rien.
    (("player_season_pressured_action_rate",
      "player_season_pressured_actions_90",
      "player_season_times_pressured_90"),    "Fois pressé /90",          "Sous pression", 2),

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
    "Sous pression": "FFEDE7F6",
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
    """Valeur d'une colonne. `cle` peut être un tuple de noms candidats : on
    renvoie la première colonne qui existe ET qui porte une valeur. Utile pour
    les champs que StatsBomb a renommés d'une version d'API à l'autre."""
    for k in (cle if isinstance(cle, tuple) else (cle,)):
        if k not in row:
            continue
        v = row[k]
        # NaN n'est pas None et NaN == NaN est faux : c'est le seul test fiable.
        if v is None or v != v:
            continue
        return v
    return None


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
    # code -> ensemble des noms de témoins qui portent ce code. On compte les
    # noms DISTINCTS, pas les lignes : un témoin qui joue trois compétitions
    # ne doit pas peser trois voix.
    vus = collections.defaultdict(set)
    colonnes_pression = set()
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
        # On relève le nom EXACT de tout champ contenant « pressur ». C'est la
        # seule façon de savoir ce que la licence expose vraiment, au lieu de
        # le deviner. Imprimé en fin de run, donc lisible dans le résumé.
        colonnes_pression.update(c for c in df.columns if "pressur" in str(c).lower())
        for _, r in df.iterrows():
            n = nn(r.get("player_name"))
            if n in temoins:
                c = r.get("country_id")
                if c is not None and c == c:
                    vus[int(c)].add(n)
        if i % 25 == 0:
            print("   %d/%d balayées…" % (i, len(cibles)))

    # --- le vote, imprimé en entier : c'est la pièce à relire en cas de doute
    print("\nRépartition des témoins par code pays :")
    for c, noms_c in sorted(vus.items(), key=lambda kv: -len(kv[1])):
        print("   code %-6s %2d témoin(s) : %s"
              % (c, len(noms_c), ", ".join(sorted(noms_c))))
    manquants = temoins - set().union(*vus.values()) if vus else temoins
    if manquants:
        print("   %d témoin(s) introuvable(s) dans les données : %s"
              % (len(manquants), ", ".join(sorted(manquants))))

    if CODE_FORCE:
        code = int(CODE_FORCE)
        print("\nCode pays FORCÉ à la main : %s (CODE_PAYS)" % code)
    else:
        if not vus:
            raise SystemExit(
                "\nÉCHEC : aucun international mauritanien retrouvé parmi les "
                "témoins.\nImpossible d'identifier le code pays — rien n'a été "
                "écrit. Vérifie que la licence couvre bien des championnats où "
                "ils jouent.")
        classement = sorted(vus.items(), key=lambda kv: -len(kv[1]))
        code, noms_c = classement[0]
        if len(noms_c) < TEMOINS_MINIMUM:
            raise SystemExit(
                "\nÉCHEC : le code le mieux placé (%s) n'est porté que par %d "
                "témoin(s), il en faut %d.\nRien n'a été écrit : avec si peu "
                "d'appui, un homonyme suffirait à tout fausser. Relis la "
                "répartition ci-dessus, et relance avec CODE_PAYS=<code> si tu "
                "sais lequel est le bon."
                % (code, len(noms_c), TEMOINS_MINIMUM))
        print("\nCode pays retenu : %s (%d témoins distincts)" % (code, len(noms_c)))
        # Un second code à égalité, ou presque, est le signe qu'une partie des
        # témoins est enregistrée sous une autre nationalité. On le dit.
        if len(classement) > 1:
            c2, n2 = classement[1]
            if len(n2) >= len(noms_c) - 1:
                print("   !! ATTENTION : le code %s est porté par %d témoin(s), "
                      "presque autant.\n      Le vote est serré — vérifie la "
                      "répartition ci-dessus avant d'exploiter le fichier."
                      % (c2, len(n2)))

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
            # L'écart est calculé ici, pas lu : StatsBomb publie les deux
            # pourcentages, pas leur différence. Si l'un des deux manque, on
            # laisse vide — un écart calculé contre zéro serait un mensonge.
            sp = ligne.get("Passes sous pression %")
            hp = ligne.get("Passes sans pression %")
            ligne["Écart sous pression"] = (
                sp - hp if (sp is not None and hp is not None) else None)
            lignes.append(ligne)

    # Un joueur peut figurer dans plusieurs compétitions la même saison
    # (championnat + coupe d'Europe) : ce sont des lignes distinctes, voulues.
    lignes.sort(key=lambda x: (nn(x.get("Joueur")), str(x.get("Saison")),
                               str(x.get("Compétition"))))
    noms = {nn(x["Joueur"]) for x in lignes}
    print("%d lignes | %d joueurs distincts | %d compétitions illisibles"
          % (len(lignes), len(noms), echecs))

    # --- contrôle du bloc « sous pression »
    # Des colonnes vides passeraient inaperçues dans un classeur de 43 colonnes.
    # On dit le taux de remplissage, et on crie si c'est zéro.
    print("\nChamps « pressure » exposés par la licence (%d) :" % len(colonnes_pression))
    for c in sorted(colonnes_pression):
        print("   %s" % c)
    titres_p = [t for _c, t, th, _d in COLONNES if th == "Sous pression"]
    if lignes:
        for t in titres_p:
            n = sum(1 for l in lignes if l.get(t) is not None)
            print("   %-34s %3d/%d lignes remplies" % (t, n, len(lignes)))
        if not any(l.get(t) is not None for l in lignes for t in titres_p):
            print("\n   !! AUCUNE donnée sous pression récupérée. Les colonnes du bloc\n"
                  "      sortiront vides. Regarde la liste des champs ci-dessus : si elle\n"
                  "      contient un nom proche, dis-le-moi et je corrige la clé.")

    ecrire(lignes, noms, code, vus, colonnes_pression)


def ecrire(lignes, noms, code, vus, colonnes_pression=()):
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
    ws2 = wb.create_sheet("Sélection Mauritanie")
    ws2["A1"] = ("Sélection mauritanienne de septembre 2026, éliminatoires de la CAN 2027. La "
                 "colonne de droite dit si le joueur a été retrouvé dans les données StatsBomb "
                 "couvertes par la licence. « — » en club signifie « non publié dans la source ».")
    ws2["A1"].font = Font(name="Arial", size=9, italic=True, color="FF666666")
    ws2.merge_cells("A1:E1")
    for j, t in enumerate(["Joueur", "Poste", "Club (sept. 2026)", "Pays du club",
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
    detail = sorted(vus.items(), key=lambda kv: -len(kv[1]))[:4]
    notes = [
        "Comment ce fichier a été fabriqué",
        "",
        "Source : StatsBomb, point d'entrée player_season_stats, via la licence du compte.",
        "Généré le : " + datetime.datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"),
        "Profondeur : les %d dernières saisons de chaque compétition couverte." % NB_SAISONS,
        "",
        "Identification des Mauritaniens",
        "StatsBomb ne donne pas le nom du pays, seulement un code numérique. Ce code a été",
        "identifié en cherchant des internationaux mauritaniens connus dans les données, puis",
        "en retenant le code porté par le plus de témoins distincts. Code retenu : %s." % code,
        "",
        "Détail du vote (code : nombre de témoins) :",
    ]
    for c, noms_c in detail:
        notes.append("   %s : %d — %s" % (c, len(noms_c), ", ".join(sorted(noms_c))))
    notes += [
        "",
        "Pourquoi certains internationaux ne servent pas de témoin",
        "Mamadou Diop, Lamine Ba, Ibrahima Keïta, Khadim Diaw, Baïla Diallo, Mamadou Diallo,",
        "Babacar Diop, Babacar Niasse et Mamadou Fofana portent des noms très répandus en",
        "Afrique de l'Ouest. Un homonyme sénégalais ou malien aurait voté pour le mauvais pays.",
        "Ils figurent dans l'onglet « Sélection Mauritanie », mais n'ont pas servi à identifier",
        "le code. Ils sont bien récoltés dans l'onglet 1 s'ils portent le code retenu.",
        "",
        "Ce que le fichier ne contient pas",
        "La licence couvre une soixantaine de compétitions, surtout européennes. Les joueurs",
        "évoluant en Mauritanie, au Maroc, au Koweït, en Égypte ou dans le Golfe n'y figurent",
        "pas, quelle que soit leur notoriété. L'onglet « Sélection Mauritanie » montre",
        "nommément qui manque.",
        "",
        "Une réserve sur les postes de l'onglet 2",
        "Les sources de presse se contredisent : la FFRIM classe Ngom, Mahmoud, Sidi, Deuff et",
        "Bodda parmi les défenseurs, le communiqué repris en fait des milieux, et la répartition",
        "annoncée (3-9-7-8) ne colle avec aucune des deux. Le poste de l'onglet 2 est donc",
        "indicatif. Seule la colonne « Poste » de l'onglet 1, qui vient de StatsBomb, est fiable.",
        "",
        "Le bloc « Sous pression »",
        "« Passes sous pression % » et « Passes sans pression % » viennent telles quelles de",
        "StatsBomb. « Écart sous pression » est calculé ici : la première moins la seconde.",
        "Il est négatif pour presque tout le monde — passer est plus dur quand on est pressé.",
        "C'est son AMPLEUR qui parle, et elle ne se lit pas seule : perdre 5 points en partant",
        "de 92 % n'est pas perdre 5 points en partant de 61 %. Regarde toujours les deux",
        "colonnes qui le précèdent, et « Fois pressé /90 » qui dit sur combien de ballons",
        "l'écart a été mesuré. Un écart calculé sur trois ballons pressés ne vaut rien.",
        "« Longs ballons sous pression /90 » complète le portrait : une cadence élevée ici",
        "avec un écart très négatif, c'est le joueur qui dégage dès qu'on vient le chercher.",
        "Si ces colonnes sortent vides, c'est que la licence n'expose pas ces champs ; le",
        "journal du run liste alors les noms exacts qu'elle expose.",
        "",
        "Lecture des colonnes",
        "Les valeurs suivies de « /90 » sont des cadences par 90 minutes, pas des totaux.",
        "Les pourcentages sont des fractions : 0,45 se lit 45 %.",
        "Un joueur ayant disputé peu de minutes a des cadences très instables : regarde",
        "toujours la colonne Minutes avant de comparer deux joueurs.",
    ]
    gras = ("Identification des Mauritaniens",
            "Le bloc « Sous pression »",
            "Pourquoi certains internationaux ne servent pas de témoin",
            "Ce que le fichier ne contient pas",
            "Une réserve sur les postes de l'onglet 2",
            "Lecture des colonnes")
    for i, t in enumerate(notes, 1):
        c = ws3.cell(row=i, column=1, value=t)
        c.font = Font(name="Arial", size=10, bold=(i == 1 or t in gras))
    ws3.column_dimensions["A"].width = 100

    wb.save(SORTIE)
    print("\n%s écrit : %d lignes, %d joueurs." % (SORTIE, len(lignes), len(noms)))


if __name__ == "__main__":
    main()
