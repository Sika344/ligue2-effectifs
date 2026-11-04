#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_ligue2_lfp.py — reconstruit ligue2_<saison>.json depuis les effectifs LFP.

La LFP (ma-api.ligue1.fr) fait autorite sur QUI est dans l'effectif : elle donne
numero, nom, prenom, date de naissance, poste, pied, nationalite et photo buste.
Elle ne donne PAS la taille : on va la chercher dans le fichier precedent
(issu de Transfermarkt), par appariement de noms en plusieurs passes.

Consequence voulue : les joueurs partis au mercato disparaissent, les recrues
apparaissent. Les recrues n'ont pas de taille tant qu'on ne l'a pas recuperee
ailleurs.

NE TOUCHE JAMAIS aux fichiers d'une autre saison.

USAGE : python build_ligue2_lfp.py [--write]
"""
import json, re, sys, unicodedata, difflib, datetime

SAISON = "2026-2027"
LFP    = "lfp_effectifs_%s.json" % SAISON
CIBLE  = "ligue2_%s.json" % SAISON
WRITE  = "--write" in sys.argv

ORDRE = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def age_de(dob):
    if not dob:
        return None
    try:
        n = datetime.date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    t = datetime.date.today()
    return t.year - n.year - ((t.month, t.day) < (n.month, n.day))


def main():
    lfp = json.load(open(LFP, encoding="utf-8"))["clubs"]
    anc = json.load(open(CIBLE, encoding="utf-8"))

    # carte code pays -> emoji drapeau, reprise de l'ancien fichier
    drapeaux = {}
    for v in anc["teams"].values():
        for p in v["squad"]:
            if p.get("ccode") and p.get("flag"):
                drapeaux.setdefault(p["ccode"], p["flag"])

    st = dict(joueurs=0, taille=0, sans_taille=0, num=0)
    lignes = []
    teams = {}

    for club, joueurs in sorted(lfp.items()):
        vieux = (anc["teams"].get(club) or {}).get("squad", [])
        libres = list(range(len(vieux)))

        def taille_pour(complet, nom):
            """Taille reprise de l'ancien effectif. Quatre passes, de la plus
               sure a la plus permissive ; unicite exigee, sinon on renonce."""
            def choisir(cands):
                if len(cands) != 1:
                    return None
                k = cands[0]
                libres.remove(k)
                return vieux[k].get("height")

            # 1. nom complet identique
            a = norm(complet)
            r = choisir([k for k in libres if a and norm(vieux[k].get("fullname")) == a])
            if r is not None:
                return r
            # 2. nom de famille identique
            b = norm(nom)
            r = choisir([k for k in libres if b and norm(vieux[k].get("name")) == b])
            if r is not None:
                return r
            # 3. inclusion des mots du nom de famille
            tj = set(b.split())
            r = choisir([k for k in libres if tj and
                         (tj <= set(norm(vieux[k].get("name")).split())
                          or set(norm(vieux[k].get("name")).split()) <= tj)])
            if r is not None:
                return r
            # 4. nom complet approchant (coquilles d'une source a l'autre)
            return choisir([k for k in libres if a and
                            difflib.SequenceMatcher(
                                None, a, norm(vieux[k].get("fullname"))).ratio() >= 0.86])

        squad = []
        for e in joueurs:
            nom = (e.get("last") or "").upper()
            complet = (" ".join(x for x in (e.get("first"), e.get("last")) if x)).strip()
            h = taille_pour(complet, nom)
            num = e.get("num")
            squad.append({
                "num": num if num is not None else "?",
                "name": nom,
                "fullname": complet,
                "flag": drapeaux.get(e.get("cc"), ""),
                "ccode": e.get("cc"),
                "height": h,
                "age": age_de(e.get("dob")),
                "dob": (str(e.get("dob"))[:10] if e.get("dob") else None),
                "pos": e.get("pos") or "MID",
                "posDesc": e.get("pos") or "MID",
                # SILHOUETTE ≠ PHOTO. Quand la LFP n'a pas le portrait d'un
                # joueur, elle sert une silhouette grise générique — URL en
                # « defaultAssets », 6 ko au lieu de 85. On marquait pourtant
                # « photoLFP: True » sans distinction, et le site affichait ce
                # bonhomme gris en croyant montrer le joueur. C'était le cas de
                # Cristian Castro Devenish et de 81 autres.
                # On laisse donc la photo vide : la page retombe alors sur son
                # propre avatar, plus sobre, et le compte des vraies photos
                # redevient juste.
                "photo": (None if e.get("photo_generique") else e.get("photo")),
                "photoLFP": not e.get("photo_generique") and bool(e.get("photo")),
                "foot": e.get("foot"),
                "g": 0, "a": 0,
            })
            st["joueurs"] += 1
            st["taille" if h else "sans_taille"] += 1
            if num is not None:
                st["num"] += 1

        squad.sort(key=lambda p: (ORDRE.get(p["pos"], 9),
                                  p["num"] if isinstance(p["num"], int) else 999))
        logo = (anc["teams"].get(club) or {}).get("logo")
        teams[club] = {"logo": logo, "squad": squad}
        lignes.append((club, len(squad), sum(1 for p in squad if p["height"]), len(vieux)))

    doc = {"season": SAISON, "source": "LFP (ma-api.ligue1.fr) + tailles Transfermarkt",
           "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "teams": teams}

    print("%-16s %8s %8s %10s" % ("CLUB", "joueurs", "tailles", "avant"))
    for c, n, h, v in lignes:
        print("  %-16s %6d %8d %10d" % (c, n, h, v))
    print()
    for k, lbl in [("joueurs", "joueurs"), ("taille", "tailles recuperees"),
                   ("sans_taille", "sans taille"), ("num", "numeros de maillot")]:
        print("  %-24s %d" % (lbl, st[k]))

    if WRITE:
        json.dump(doc, open(CIBLE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n%s reecrit." % CIBLE)
    else:
        print("\n(simulation — relancer avec --write)")


if __name__ == "__main__":
    main()
