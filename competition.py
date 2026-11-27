#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
competition.py — la compétition traitée par les scripts de génération.

Ce module est importé par tous les build_*.py du site. Il tient en un
endroit ce qui, avant, était écrit en dur dans chacun d'eux : l'identifiant
StatsBomb de la compétition, son nom, et le préfixe qui distingue ses
fichiers de sortie.

================================================================= L'USAGE
La compétition se choisit par la variable d'environnement COMP :

    COMP=8  (ou rien)   Ligue 2   -> xg_2026-2027.json
    COMP=7              Ligue 1   -> xg_L1_2026-2027.json

Le défaut est la Ligue 2. C'est délibéré : tous les workflows existants
tournent sans COMP, et doivent continuer de produire EXACTEMENT les mêmes
fichiers qu'avant. Un script qui ne reçoit rien se comporte comme avant
l'arrivée de la Ligue 1.

======================================= POURQUOI LA LIGUE 2 N'A PAS DE PRÉFIXE
Une soixantaine de fichiers Ligue 2 existent déjà sous leurs noms actuels,
produits et vérifiés depuis des mois, et `season.js` les lit sous ces noms.
Leur ajouter un préfixe aurait voulu dire tout renommer et tout relancer
pour n'y rien gagner. Le préfixe vide n'est pas un oubli : c'est la
garantie que l'ajout d'une compétition ne peut pas casser l'autre.

=========================================== POUR AJOUTER UNE COMPÉTITION
Une ligne dans NOMS et une dans PREFIXES. Les scripts suivent seuls.
Une compétition inconnue reçoit un préfixe « c<id>_ » plutôt qu'une
erreur : mieux vaut un fichier au nom inhabituel qu'une chaîne cassée.
"""

import os

# Identifiants StatsBomb. Vérifiés le 27/11/2026 sur le catalogue de la
# licence : les deux portent événements ET frames 360 pour 2026/2027.
NOMS = {
    8: "Ligue 2",
    7: "Ligue 1",
}

PREFIXES = {
    8: "",        # Ligue 2 : historique, aucun préfixe (voir ci-dessus)
    7: "L1_",
}

DEFAUT = 8


def _lire():
    v = (os.environ.get("COMP") or "").strip()
    if not v:
        return DEFAUT
    try:
        return int(v)
    except ValueError:
        raise SystemExit(
            "ERREUR : COMP='%s' n'est pas un nombre. Attendu : 8 (Ligue 2) "
            "ou 7 (Ligue 1)." % v)


COMPETITION_ID = _lire()
NOM = NOMS.get(COMPETITION_ID, "compétition %d" % COMPETITION_ID)
PREFIXE = PREFIXES.get(COMPETITION_ID, "c%d_" % COMPETITION_ID)


def sortie(base, label, current_season=None):
    """Nom du fichier de sortie pour ce jeu de données.

    `base` est le nom nu sans extension ("xg", "losses"…).

    En Ligue 2 sans préfixe, on conserve la convention historique : le
    fichier est nu quand la saison traitée est CURRENT_SEASON, suffixé
    sinon. Dès qu'un préfixe existe, le fichier est TOUJOURS suffixé —
    un « xg.json » de Ligue 1 écraserait celui de la Ligue 2, ce qui
    serait la pire façon possible de casser le site.
    """
    if PREFIXE or current_season is None or label != current_season:
        return "%s_%s%s.json" % (base, PREFIXE, label)
    return "%s.json" % base


# Annonce à l'import, et non par un appel que chaque script devrait penser à
# faire. Un run qui traite la mauvaise compétition serait autrement indétectable
# dans les journaux — on ne s'en apercevrait qu'en voyant des équipes de Ligue 1
# dans un fichier Ligue 2. Ici la ligne est garantie, dans tous les journaux.
print("Compétition : %s (id=%d, préfixe=%r)" % (NOM, COMPETITION_ID, PREFIXE))
