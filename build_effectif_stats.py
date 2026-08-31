#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_effectif_stats.py — injecte les statistiques joueur (buts, passes
décisives, minutes) dans les effectifs `ligue2_<saison>.json`.

------------------------------------------------------------------ POURQUOI
Les effectifs viennent de la LFP (build_ligue2_lfp.py) : photos, numéros,
tailles, pieds… mais AUCUNE statistique. Les champs `g` et `a` existaient dans
le fichier, tous à zéro, et les pages les affichaient tels quels — d'où des
cartes joueur vides sur toute la saison 2026-2027.

Le fichier 2025-2026 portait bien des stats, mais elles y avaient été mises
par une manipulation ponctuelle, jamais scriptée : rien ne les régénérait.
Pire, l'archive `ligue2_2026-2027_AVANT_LFP.json` montre que 2026-2027 a un
temps porté les stats de la saison 318, c'est-à-dire **celles de 2025-2026**.
Ce script existe pour que chaque saison porte ses propres chiffres, et pour
que la fusion LFP ne puisse plus les effacer silencieusement.

------------------------------------------------------------------ SOURCE
StatsBomb `player_season_stats`, colonnes :
    player_season_goals_90 · player_season_assists_90 · player_season_minutes

Les totaux sont reconstitués par  valeur_90 × (minutes / 90). C'est exact :
StatsBomb calcule ces cadences à partir des totaux, la division est donc
réversible. Contrôlé sur 2025-2026 contre les valeurs déjà en place :
221 joueurs sur 222 identiques sur les buts ET sur les passes décisives.
(Le seul écart, Yohann Demoncy, vient d'un total de minutes périmé côté
fichier — 220 contre 979 — pas de la formule.)

--------------------------------------------------------------- APPARIEMENT
Le fichier LFP ne contient pas d'identifiant StatsBomb : il faut rapprocher
les noms. Quatre passes, de la plus sûre à la plus tolérante, et l'on
s'arrête à la première qui tranche :
    1. nom complet identique après normalisation
    2. inclusion des mots (« Salomon Sambia » ⊂ « Salomon Junior Sambia »)
    3. nom de famille seul, à condition qu'il soit unique dans l'équipe
    4. similarité ≥ 0,80 ET nettement devant le suivant

La passe 4 n'est pas un luxe : la LFP écrit NGAPANDOUENTNBU là où StatsBomb
écrit Ngapandouetnbu, Bouabdeli contre Bouabdelli, Sarikaya contre Sarıkaya.
Six joueurs de 2026-2027 ne se rattrapent que par là.

Les joueurs qu'aucune passe ne rattrape sont ABSENTS de la liste LFP (recrues
récentes, jeunes non listés) : ils n'ont pas de carte à alimenter. Le script
les compte et les nomme dans son journal plutôt que d'inventer un rattachement.

------------------------------------------------------------------- SORTIE
Réécrit `ligue2_<saison>.json` en place, en ajoutant sur chaque joueur apparié
    "g"     buts
    "a"     passes décisives
    "mins"  minutes jouées (entier)
    "sbId"  identifiant StatsBomb, pour que les prochains passages n'aient
            plus à deviner le nom
et à la racine  "statsSource" / "statsUpdated", qui servent de trace : un
fichier sans ces deux clés n'a jamais reçu de statistiques.

USAGE LOCAL :
    SB_USERNAME='…' SB_PASSWORD='…' SEASON='2026-2027' python build_effectif_stats.py
"""

import os
import re
import sys
import json
import math
import difflib
import datetime
import unicodedata

from statsbombpy import sb

COMPETITION_ID = 8
CURRENT_SEASON = "2025-2026"
SEASON_IDS = {
    "2025-2026": 318,
    "2026-2027": 351,
}

COL_GOALS = "player_season_goals_90"
COL_ASSISTS = "player_season_assists_90"
COL_MINUTES = "player_season_minutes"

# Seuil de similarité de la 4e passe, et écart minimal avec le 2e candidat.
# 0,80 rattrape Ngapandouentnbu (0,85) sans confondre deux frères ; l'écart de
# 0,08 refuse de trancher quand deux joueurs se ressemblent autant l'un que
# l'autre — mieux vaut un joueur sans stats qu'un joueur avec celles d'un autre.
SEUIL_SIM = 0.80
ECART_SIM = 0.08


def lookup_season_id(label):
    """Résout un libellé de saison via l'API quand il n'est pas dans la table."""
    comps = sb.competitions()
    hit = comps[(comps["competition_id"] == COMPETITION_ID)
                & (comps["season_name"] == label)]
    if hit.empty:
        raise SystemExit("saison introuvable pour la Ligue 2 : %s" % label)
    return int(hit.iloc[0]["season_id"])


def texte(v):
    """Chaîne propre depuis une cellule pandas, ou "" si la donnée manque.

    À NE PAS remplacer par `a or b` : une cellule vide arrive en float('nan'),
    qui est VRAI en Python. Un simple `known_name or name` gardait donc le nan,
    tous les joueurs sans surnom s'appelaient « nan », et la déduplication par
    nom n'en laissait qu'un par club — 67 joueurs enrichis au lieu de 311.
    """
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "<na>") else s


def nn(s):
    """Minuscules, sans accents, sans ponctuation. « Sarıkaya » → « sarikaya »."""
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_club(s):
    """Comme nn(), en retirant les mots de club : « FC Annecy » = « Annecy FC »."""
    s = nn(s)
    s = re.sub(r"\b(fc|sc|us|as|stade|de|du|foot|club)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_team(club, noms):
    """Rapproche un nom d'équipe StatsBomb d'une clé de ligue2_<saison>.json.

    Même logique que matchTeam() dans rapport-pre-match.html, pour que les deux
    bouts de la chaîne apparient les 18 clubs de la même façon.
    """
    a = norm_club(club)
    for t in noms:
        if norm_club(t) == a:
            return t
    for t in noms:
        b = norm_club(t)
        if b and (a in b or b in a):
            return t
    for t in noms:
        b = norm_club(t)
        at, bt = a.split(), b.split()
        if any(len(x) >= 4 and any(y.startswith(x) or x.startswith(y) for y in bt)
               for x in at):
            return t
    return None


def similitude(a, b):
    """Similarité de deux noms, insensible à l'ordre des mots.

    La LFP et StatsBomb n'ordonnent pas toujours prénom et nom de la même
    façon : « Evan's Jean-Lambert » chez l'une, « Jean Lambert Evans » chez
    l'autre. Comparés dans l'ordre, ces deux noms se ressemblent peu ; mots
    triés, ils se superposent. On garde le meilleur des deux points de vue.
    """
    direct = difflib.SequenceMatcher(None, a, b).ratio()
    tri_a = " ".join(sorted(a.split()))
    tri_b = " ".join(sorted(b.split()))
    return max(direct, difflib.SequenceMatcher(None, tri_a, tri_b).ratio())


def _essai(nom_sb, libres, passe):
    """Une seule passe d'appariement, contre les cartes encore libres."""
    a = nn(nom_sb)
    toks = set(a.split())

    if passe == "exact":
        for q in libres:
            if nn(q.get("fullname")) == a:
                return q, "exact"
        return None, None

    if passe == "inclusion":
        for q in libres:
            b = set(nn(q.get("fullname")).split())
            if b and toks and (b & toks) and (b <= toks or toks <= b):
                return q, "inclusion"
        return None, None

    if passe == "nom":
        cands = [q for q in libres if nn(q.get("name")) and nn(q.get("name")) in toks]
        if len(cands) == 1:
            return cands[0], "nom de famille"
        return None, None

    scores = sorted(((similitude(a, nn(q.get("fullname"))), q)
                     for q in libres), key=lambda x: -x[0])
    if scores and scores[0][0] >= SEUIL_SIM:
        if len(scores) < 2 or scores[0][0] - scores[1][0] >= ECART_SIM:
            return scores[0][1], "orthographe %.2f" % scores[0][0]
    return None, None


PASSES = ("exact", "inclusion", "nom", "orthographe")


def apparie_equipe(noms_sb, squad, variantes=None):
    """Apparie TOUS les joueurs d'une équipe, par vagues de confiance décroissante.

    Traiter les joueurs un par un jusqu'au bout des quatre passes était faux :
    à Reims, « Eloge Patrick Zabi Gueu » raflait la carte de John Patrick par
    la passe « nom de famille » (patrick ∈ ses prénoms), et écrasait ensuite
    « John Joe Patrick Finn Benoa » qui, lui, la méritait par inclusion.
    Le dernier arrivé gagnait, en silence.

    On fait donc toutes les correspondances exactes d'abord, puis les
    inclusions, etc. Une carte prise n'est plus proposée : le match le plus
    sûr l'emporte, quel que soit l'ordre des lignes reçues de StatsBomb.

    `variantes` : {nom : [autres écritures]}. On y met le nom d'usage renvoyé
    par StatsBomb, car c'est souvent celui que la LFP retient — Loni Quenabio
    y figure sous « Loni », exactement comme sur sa fiche LFP « Loni Laurent ».
    Sans cet essai, il n'était pas apparié et se retrouvait DEUX FOIS dans
    l'effectif, sa fiche LFP et une fiche créée, avec le même identifiant.

    Retourne {nom_sb: (joueur, méthode)} et la liste des noms non appariés.
    """
    variantes = variantes or {}
    resultat = {}
    pris = set()
    restants = list(noms_sb)

    for passe in PASSES:
        encore = []
        for nom in restants:
            libres = [q for q in squad if id(q) not in pris]
            q, methode = _essai(nom, libres, passe)
            if q is None:
                for autre in variantes.get(nom, []):
                    q, methode = _essai(autre, libres, passe)
                    if q is not None:
                        methode += " (nom d'usage)"
                        break
            if q is None:
                encore.append(nom)
            else:
                pris.add(id(q))
                resultat[nom] = (q, methode)
        restants = encore

    return resultat, restants


# StatsBomb -> vocabulaire de posDesc du site (voir roleOf() dans index.html).
# Vocabulaire fermé et stable : 23 valeurs relevées sur les deux saisons.
POSTES = {
    "Goalkeeper":                    ("GK",  "GK"),
    "Centre Back":                   ("CB",  "DEF"),
    "Left Centre Back":              ("CB",  "DEF"),
    "Right Centre Back":             ("CB",  "DEF"),
    "Left Back":                     ("LB",  "DEF"),
    "Right Back":                    ("RB",  "DEF"),
    "Left Wing Back":                ("LWB", "DEF"),
    "Right Wing Back":               ("RWB", "DEF"),
    "Centre Defensive Midfielder":   ("CDM", "MID"),
    "Left Defensive Midfielder":     ("CDM", "MID"),
    "Right Defensive Midfielder":    ("CDM", "MID"),
    "Left Centre Midfielder":        ("CM",  "MID"),
    "Right Centre Midfielder":       ("CM",  "MID"),
    "Centre Attacking Midfielder":   ("CAM", "MID"),
    "Left Attacking Midfielder":     ("CAM", "MID"),
    "Right Attacking Midfielder":    ("CAM", "MID"),
    "Left Midfielder":               ("LM",  "MID"),
    "Right Midfielder":              ("RM",  "MID"),
    "Left Wing":                     ("LW",  "ATT"),
    "Right Wing":                    ("RW",  "ATT"),
    "Centre Forward":                ("ST",  "ATT"),
    "Left Centre Forward":           ("ST",  "ATT"),
    "Right Centre Forward":          ("ST",  "ATT"),
}


def numeros_maillot(season_id, cherches):
    """Numéros de maillot des joueurs demandés, via les feuilles de match.

    `player_season_stats` ne porte pas le numéro. Or index.html n'affiche que
    les joueurs qui en ont un : un joueur ajouté sans numéro resterait
    invisible, ce qui viderait l'ajout de son intérêt.

    On parcourt les feuilles de match du plus RÉCENT au plus ancien — un joueur
    peut avoir changé de numéro — et on s'arrête dès que tout le monde est
    trouvé. En pratique deux ou trois feuilles suffisent.

    `cherches` : ensemble d'identifiants StatsBomb. Retourne {id: numéro}.
    """
    trouves = {}
    if not cherches:
        return trouves
    try:
        ms = sb.matches(competition_id=COMPETITION_ID, season_id=season_id)
    except Exception as exc:
        print("   !! feuilles de match indisponibles (%s) — pas de numéros" % exc)
        return trouves

    if "match_date" in ms.columns:
        ms = ms.sort_values("match_date", ascending=False)

    lus = 0
    for mid in ms["match_id"]:
        if len(trouves) >= len(cherches):
            break
        try:
            lu = sb.lineups(match_id=int(mid))
        except Exception:
            continue
        lus += 1
        if not isinstance(lu, dict):
            continue
        for df in lu.values():
            if "jersey_number" not in df.columns or "player_id" not in df.columns:
                continue
            for _, r in df.iterrows():
                try:
                    pid = int(r["player_id"])
                except (TypeError, ValueError):
                    continue
                if pid not in cherches or pid in trouves:
                    continue
                num = r.get("jersey_number")
                if num is not None and num == num:      # écarte NaN
                    trouves[pid] = int(num)
    print("   %d numéros retrouvés sur %d cherchés (%d feuilles lues)"
          % (len(trouves), len(cherches), lus))
    return trouves


def fiche_joueur(row, numero):
    """Construit une entrée d'effectif pour un joueur absent de la liste LFP."""
    nom_complet = texte(row.get("player_name")) or texte(row.get("player_known_name"))
    morceaux = nom_complet.split()
    poste, famille = POSTES.get(texte(row.get("primary_position")), (None, None))

    age = None
    naissance = texte(row.get("birth_date"))[:10]
    if len(naissance) == 10:
        try:
            n = datetime.date.fromisoformat(naissance)
            a = datetime.date.today()
            age = a.year - n.year - ((a.month, a.day) < (n.month, n.day))
        except ValueError:
            age = None

    taille = None
    try:
        h = float(row.get("player_height"))
        if h == h and 140 <= h <= 220:
            taille = int(round(h))
    except (TypeError, ValueError):
        pass

    return {
        "num": numero,
        "name": (morceaux[-1] if morceaux else nom_complet).upper(),
        "fullname": nom_complet,
        "pos": famille or "MID",
        "posDesc": poste or "CM",
        "height": taille,
        "age": age,
        # Pas de photo : la page bascule sur l'avatar générique, comme pour
        # tout joueur dont la LFP n'a pas encore publié le portrait.
        "photo": "",
        "photoLFP": False,
        # Trace explicite : cette fiche vient de StatsBomb, pas de la LFP.
        # Un prochain rafraîchissement LFP la remplacera si le joueur y entre.
        "ajouteStatsBomb": True,
    }


def total(cadence, minutes):
    """Passe d'une cadence /90 à un total. None si la donnée manque."""
    if cadence is None or minutes is None:
        return None
    try:
        return int(round(float(cadence) * float(minutes) / 90.0))
    except (TypeError, ValueError):
        return None


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    label = (arg or os.environ.get("SEASON", "")).strip() or CURRENT_SEASON
    season_id = SEASON_IDS.get(label) or lookup_season_id(label)

    chemin = "ligue2_%s.json" % label
    if not os.path.exists(chemin):
        # Le fichier d'effectif est produit par build_ligue2_lfp.py. S'il manque,
        # il n'y a rien à enrichir : on le dit et on sort proprement, sans faire
        # échouer la journée entière.
        print("!! %s absent — rien à enrichir." % chemin)
        return

    with open(chemin, encoding="utf-8") as f:
        data = json.load(f)

    print("Saison %s (season_id=%s) — %s" % (label, season_id, chemin))

    # Les fiches créées par un run précédent sont retirées d'entrée : elles
    # seront recréées plus bas à partir des données du jour. Sans ce ménage, une
    # fiche créée à tort survit indéfiniment — c'est ainsi que « Loni Quenabio »
    # est resté à Rodez à côté de sa vraie fiche LFP « Loni Laurent ». Le script
    # devient du même coup rejouable : deux passages donnent le même fichier.
    efface = 0
    for t in data["teams"].values():
        avant = len(t["squad"])
        t["squad"] = [p for p in t["squad"] if not p.get("ajouteStatsBomb")]
        efface += avant - len(t["squad"])
    if efface:
        print("   %d fiches du run précédent retirées avant reconstruction" % efface)

    stats = sb.player_season_stats(competition_id=COMPETITION_ID, season_id=season_id)
    manquantes = [c for c in (COL_GOALS, COL_ASSISTS, COL_MINUTES)
                  if c not in stats.columns]
    if manquantes:
        raise SystemExit("colonnes absentes de player_season_stats : %s"
                         % ", ".join(manquantes))
    print("   %d lignes reçues de StatsBomb" % len(stats))

    equipes = list(data["teams"])
    corr = {}
    for club in sorted({texte(r) for r in stats["team_name"] if texte(r)}):
        corr[club] = match_team(club, equipes)
    inconnues = [c for c, v in corr.items() if v is None]
    if inconnues:
        print("   !! équipes non rapprochées : %s" % ", ".join(inconnues))

    # Un même club ne doit pas être visé par deux noms StatsBomb : sinon le
    # second écraserait le premier sans que rien ne le signale.
    vus = {}
    for club, cible in corr.items():
        if cible:
            vus.setdefault(cible, []).append(club)
    for cible, sources in vus.items():
        if len(sources) > 1:
            print("   !! %s visé par plusieurs noms : %s" % (cible, ", ".join(sources)))

    methodes = {}
    orthographe = []
    absents = []
    touches = 0

    # Regroupement par club : l'appariement se décide à l'échelle de l'équipe,
    # pas ligne par ligne (voir apparie_equipe).
    par_club = {}
    sans_nom = 0
    lignes_club = 0          # lignes REÇUES dont le club est reconnu
    for _, row in stats.iterrows():
        club = corr.get(texte(row.get("team_name")))
        if not club:
            continue
        lignes_club += 1
        # player_name est toujours rempli ; player_known_name ne l'est que pour
        # les joueurs qui ont un nom d'usage. On part donc du nom officiel.
        nom = texte(row.get("player_name")) or texte(row.get("player_known_name"))
        if not nom:
            sans_nom += 1
            continue
        # Deux lignes pour un même nom dans un même club ne devraient pas
        # exister ; si cela arrive, on garde celle qui a le plus de minutes.
        prec = par_club.setdefault(club, {}).get(nom)
        if prec is None or float(row.get(COL_MINUTES) or 0) > float(prec.get(COL_MINUTES) or 0):
            par_club[club][nom] = row

    apparies_ids = set()      # cartes effectivement alimentées PAR CE RUN

    for club, lignes in par_club.items():
        squad = data["teams"][club]["squad"]
        variantes = {}
        for nom, row in lignes.items():
            usage = texte(row.get("player_known_name"))
            if usage and nn(usage) != nn(nom):
                variantes[nom] = [usage]
        apparies, rates = apparie_equipe(list(lignes), squad, variantes)

        for nom in rates:
            mins = lignes[nom].get(COL_MINUTES)
            absents.append((club, nom, int(round(float(mins or 0))), lignes[nom]))

        for nom, (joueur, methode) in apparies.items():
            row = lignes[nom]
            mins = row.get(COL_MINUTES)
            g = total(row.get(COL_GOALS), mins)
            a = total(row.get(COL_ASSISTS), mins)
            if g is None or a is None:
                continue

            joueur["g"] = g
            joueur["a"] = a
            joueur["mins"] = int(round(float(mins)))
            joueur["sbId"] = int(row["player_id"])
            apparies_ids.add(id(joueur))
            touches += 1
            cle = methode.split(" ")[0]
            methodes[cle] = methodes.get(cle, 0) + 1
            if methode.startswith("orthographe"):
                orthographe.append((club, nom, joueur.get("fullname"), methode))

    # GARDE-FOU, AVANT toute écriture. Le run du 28/08 s'est terminé en vert
    # avec 67 joueurs enrichis au lieu de 311 : le script « marchait », il
    # produisait juste un fichier presque vide, qui a été commité. Un taux
    # d'appariement anormalement bas trahit un défaut de lecture (colonne
    # renommée, valeurs manquantes) et doit faire ÉCHOUER l'étape sans rien
    # écrire, plutôt que de remplacer des données correctes par du vide.
    # Le dénominateur est le nombre de lignes REÇUES pour un club reconnu, et
    # non les lignes qui ont survécu au filtrage : sinon un défaut qui écarte
    # les lignes en amont se cache lui-même, en rétrécissant le dénominateur en
    # même temps que le numérateur. C'est exactement ce qui s'est passé.
    taux = (touches / lignes_club) if lignes_club else 0.0
    part_sans_nom = (sans_nom / lignes_club) if lignes_club else 0.0

    # Contrôle 1 — lecture des noms. C'est LE symptôme du défaut du 28/08 :
    # 272 lignes sur 341 arrivaient sans nom exploitable. En marche normale ce
    # chiffre est nul, donc le moindre écart notable est un défaut de code, pas
    # une particularité de la saison.
    if part_sans_nom > 0.05:
        raise SystemExit(
            "ÉCHEC : %d lignes sur %d (%.0f %%) arrivent sans nom de joueur.\n"
            "C'est un défaut de lecture, pas une donnée manquante. %s n'a PAS été\n"
            "modifié — vérifier les colonnes de player_season_stats."
            % (sans_nom, lignes_club, 100 * part_sans_nom, chemin))
    if sans_nom:
        print("   !! %d lignes StatsBomb sans nom de joueur" % sans_nom)

    # Contrôle 2 — filet large. Le taux d'appariement dépend légitimement de la
    # saison : sur 2025-2026 il tombe à 54 %, parce que la liste d'effectifs est
    # celle de 2026 et que beaucoup de joueurs sont partis depuis. On ne bloque
    # donc qu'en cas d'effondrement manifeste.
    if lignes_club and taux < 0.40:
        raise SystemExit(
            "ÉCHEC : seulement %d joueurs appariés sur %d lignes StatsBomb reçues "
            "(%.0f %%).\nAttendu : au moins 40 %%. %s n'a PAS été modifié."
            % (touches, lignes_club, 100 * taux, chemin))

    # --- Joueurs que StatsBomb connaît mais que la LFP n'a pas listés --------
    # Tamar Svetlin, n° 16 de Saint-Étienne, a joué 174 minutes et n'apparaît
    # nulle part dans l'effectif : la liste LFP est simplement en retard. On
    # crée donc leur fiche à partir de StatsBomb plutôt que de les perdre.
    # Seuls les joueurs qui ont effectivement joué sont ajoutés — sans minutes,
    # rien ne prouve qu'ils appartiennent au groupe.
    a_ajouter = [(club, nom, row) for club, nom, mins, row in absents if mins > 0]
    ajoutes = 0
    sans_numero = []

    # On ne crée des fiches que si la liste d'effectifs est bien CELLE de la
    # saison traitée. Sur une saison passée, la liste LFP disponible est celle
    # d'aujourd'hui : la moitié des joueurs sont partis, et il faudrait créer
    # 192 fiches sur 2025-2026 — des effectifs à 38 joueurs, illisibles sur la
    # vue terrain, et pas ce qui est demandé. Au-delà d'un joueur manquant sur
    # sept, on considère que la liste n'est pas contemporaine de la saison.
    effectif_total = sum(len(t["squad"]) for t in data["teams"].values())
    if a_ajouter and effectif_total and len(a_ajouter) > 0.15 * effectif_total:
        print("\n--- Création de fiches ABANDONNÉE ---")
        print("   %d joueurs manquants pour %d fiches d'effectif (%.0f %%)."
              % (len(a_ajouter), effectif_total, 100.0 * len(a_ajouter) / effectif_total))
        print("   La liste LFP n'est pas celle de cette saison : on enrichit")
        print("   les fiches existantes sans en créer.")
        a_ajouter = []

    if a_ajouter:
        besoins = set()
        for _, _, row in a_ajouter:
            try:
                besoins.add(int(row["player_id"]))
            except (TypeError, ValueError):
                pass
        print("\n--- Joueurs absents de la liste LFP : %d à créer ---" % len(a_ajouter))
        nums = numeros_maillot(season_id, besoins)

        deja = 0
        for club, nom, row in a_ajouter:
            try:
                pid = int(row["player_id"])
            except (TypeError, ValueError):
                continue
            # FILET DE SÉCURITÉ. Si une carte de l'effectif porte déjà cet
            # identifiant, c'est le même joueur : on l'alimente au lieu d'en
            # créer une seconde. Sans ce test, Loni Quenabio apparaissait deux
            # fois à Rodez — sa fiche LFP « Loni Laurent » et une fiche créée,
            # toutes deux avec l'identifiant 219141 et le numéro 24.
            jumeau = next((p for p in data["teams"][club]["squad"]
                           if p.get("sbId") == pid), None)
            if jumeau is not None:
                mins = row.get(COL_MINUTES)
                g = total(row.get(COL_GOALS), mins)
                a = total(row.get(COL_ASSISTS), mins)
                if g is not None and a is not None:
                    jumeau["g"], jumeau["a"] = g, a
                    jumeau["mins"] = int(round(float(mins)))
                    apparies_ids.add(id(jumeau))
                    touches += 1
                    deja += 1
                continue
            numero = nums.get(pid)
            if numero is None:
                # Sans numéro, index.html ne l'afficherait pas : mieux vaut ne
                # pas l'ajouter que de gonfler le fichier d'une fiche fantôme.
                sans_numero.append((club, nom))
                continue
            mins = row.get(COL_MINUTES)
            g = total(row.get(COL_GOALS), mins)
            a = total(row.get(COL_ASSISTS), mins)
            if g is None or a is None:
                continue
            fiche = fiche_joueur(row, numero)
            fiche["g"] = g
            fiche["a"] = a
            fiche["mins"] = int(round(float(mins)))
            fiche["sbId"] = pid
            data["teams"][club]["squad"].append(fiche)
            apparies_ids.add(id(fiche))
            ajoutes += 1
        print("   %d fiches créées" % ajoutes)
        if deja:
            print("   %d rattachés à une fiche existante par leur identifiant "
                  "(doublon évité)" % deja)
        if sans_numero:
            print("   %d écartés faute de numéro de maillot :" % len(sans_numero))
            for c, n in sans_numero[:10]:
                print("      %-14s %s" % (c, n))

    # Toute carte que CE RUN n'a pas alimentée repart à zéro.
    #
    # Le test précédent — « pas de sbId » — était insuffisant : une carte
    # appariée lors d'un run antérieur garde son identifiant, échappait donc à
    # la remise à zéro, et conservait indéfiniment des chiffres périmés. C'est
    # ainsi que « Loni Laurent » affichait encore 297 minutes d'avant la 4e
    # journée alors que ce run ne l'avait pas apparié.
    remis = 0
    for club in data["teams"]:
        for p in data["teams"][club]["squad"]:
            if id(p) not in apparies_ids:
                if p.get("g") or p.get("a") or p.get("mins"):
                    remis += 1
                p["g"], p["a"], p["mins"] = 0, 0, 0

    # CONTRÔLE FINAL. Un même identifiant StatsBomb sur deux cartes du même
    # club, c'est un joueur affiché en double sur le terrain. Le cas s'est
    # produit (Rodez, 219141) : on refuse désormais d'écrire un tel fichier.
    doublons = []
    for club, t in data["teams"].items():
        vus = {}
        for p in t["squad"]:
            sid = p.get("sbId")
            if sid is None:
                continue
            if sid in vus:
                doublons.append((club, sid, vus[sid], p.get("fullname")))
            else:
                vus[sid] = p.get("fullname")
    if doublons:
        for club, sid, a, b in doublons[:10]:
            print("   !! %s : identifiant %s porté par « %s » ET « %s »"
                  % (club, sid, a, b))
        raise SystemExit(
            "ÉCHEC : %d joueur(s) en double dans un effectif. %s n'a PAS été "
            "modifié." % (len(doublons), chemin))

    data["statsSource"] = "StatsBomb comp %d saison %d" % (COMPETITION_ID, season_id)
    data["statsUpdated"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    joueurs = [p for t in data["teams"].values() for p in t["squad"]]
    print("\n--- Appariement ---")
    for k, v in sorted(methodes.items(), key=lambda x: -x[1]):
        print("   %-16s %d" % (k, v))
    if orthographe:
        print("\n   rattrapés sur l'orthographe (à contrôler) :")
        for c, sb_nom, lfp_nom, m in orthographe:
            print("      %-14s %-30s -> %-30s %s" % (c, sb_nom, lfp_nom, m))
    restes = [(c, n, m) for c, n, m, _ in absents if m == 0]
    if restes:
        print("\n   %d joueurs StatsBomb absents de la liste LFP et sans minutes "
              "(non ajoutés) :" % len(restes))
        for c, n, m in restes[:10]:
            print("      %-14s %s" % (c, n))
    if remis:
        print("\n   %d joueurs remis à zéro (stats d'une autre saison)" % remis)

    print("\n--- Résultat ---")
    print("   %d joueurs enrichis sur %d lignes StatsBomb reçues (%.0f %%)"
          % (touches, lignes_club, 100 * taux))
    print("   %d joueurs enrichis sur %d dans l'effectif" % (touches, len(joueurs)))
    print("   buts cumulés : %d | passes décisives : %d"
          % (sum(p.get("g") or 0 for p in joueurs),
             sum(p.get("a") or 0 for p in joueurs)))
    print("   %s écrit." % chemin)


if __name__ == "__main__":
    main()
