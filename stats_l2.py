#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stats_l2.py — injecte les buts / passes décisives / matchs d'UNE saison de Ligue 2
dans un ligue2.json existant, SANS toucher au reste (photos LFP, foot, num, pos…).

Pourquoi ce script : `fetch_tm.py` régénère tout le fichier et écrase les photos LFP
ajoutées localement. Ici on ne modifie que les clés `g`, `a`, `m` de chaque joueur.

⚠️ PIÈGE Transfermarkt : la page /leistungsdaten/verein/<id>/plus/1 SANS `reldata`
renvoie la saison EN COURS. En intersaison elle vaut 0 partout — c'est la cause des
« 0 buts / 0 passes » sur tout le site. Il faut `reldata/FR2%26<saison>`.

Usage :
    python stats_l2.py                       # stats L2 2025-26 -> ligue2.json (sur place)
    python stats_l2.py --season 2024
    python stats_l2.py --in ligue2.json --out ligue2.json
    python stats_l2.py --comp ""             # toutes compétitions (coupes incluses)

Dépendances : pip install requests beautifulsoup4 lxml
À lancer EN LOCAL (IP résidentielle) si Transfermarkt bloque.
"""
import sys, re, json, time, unicodedata, collections, difflib
import requests
from bs4 import BeautifulSoup

BASE = "https://www.transfermarkt.fr"
SLEEP = 3


def opt(flag, default=None):
    if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv):
        return sys.argv[sys.argv.index(flag) + 1]
    return default


SEASON = int(opt("--season", 2025))
COMP = opt("--comp", "FR2")
IN = opt("--in", "ligue2.json")
OUT = opt("--out", IN)
CACHE = opt("--cache", "_stats_cache.json")   # relit le scrape si présent (--no-cache pour forcer)
USE_CACHE = "--no-cache" not in sys.argv

# "Everson Jr" (TM) == "Everson Junior" (ligue2.json)
ALIAS = {"jr": "junior", "jnr": "junior"}

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})


def get(url, tries=3):
    for k in range(tries):
        r = S.get(url, timeout=45, allow_redirects=True)
        if r.status_code == 200:
            return r.text
        time.sleep(3 * (k + 1))
    r.raise_for_status()


def strip_accents(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s):
    """Clé de rapprochement : sans accents, minuscule, sans ponctuation."""
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def toks(s):
    return [ALIAS.get(t, t) for t in norm(s).split()]


def key(s):
    return " ".join(toks(s))


def squash(s):
    return "".join(toks(s))


def get_clubs(season):
    html = get(f"{BASE}/ligue-2/startseite/wettbewerb/FR2/saison_id/{season}")
    soup = BeautifulSoup(html, "lxml")
    clubs, seen = [], set()
    for a in soup.select("table.items a[href*='/startseite/verein/']"):
        m = re.search(r"/([^/]+)/startseite/verein/(\d+)", a.get("href", ""))
        if not m:
            continue
        cid = int(m.group(2))
        if cid in seen:
            continue
        seen.add(cid)
        clubs.append({"slug": m.group(1), "id": cid, "name": a.get_text(strip=True) or m.group(1)})
    return clubs


def perf_url(slug, cid, season, comp):
    if comp:
        return f"{BASE}/{slug}/leistungsdaten/verein/{cid}/reldata/{comp}%26{season}/plus/1"
    return f"{BASE}/{slug}/leistungsdaten/verein/{cid}/plus/1?saison_id={season}"


def get_perf(slug, cid, season, comp):
    """-> [{'tid','name','g','a','m'}] pour un club sur une saison."""
    soup = BeautifulSoup(get(perf_url(slug, cid, season, comp)), "lxml")
    table = soup.select_one("table.items")
    if not table and comp:
        soup = BeautifulSoup(get(perf_url(slug, cid, season, "")), "lxml")
        table = soup.select_one("table.items")
    if not table:
        return []
    hrow = table.select_one("thead tr") or table.select_one("tr")
    cells = hrow.find_all(["th", "td"], recursive=False) if hrow else []
    base = None
    for i, c in enumerate(cells):
        lab = norm((c.get("title") or "") + " " + c.get_text(" ", strip=True))
        if "effectif" in lab:
            base = i
            break
    if base is None:
        base = 4
    mi, gi, ai = base + 1, base + 2, base + 3
    out, seen = [], set()
    for tr in table.select("tbody tr"):
        link = tr.select_one("a[href*='/profil/spieler/']")
        if not link:
            continue
        m = re.search(r"/profil/spieler/(\d+)", link.get("href", ""))
        if not m:
            continue
        tid = int(m.group(1))
        tds = tr.find_all("td", recursive=False)
        if mi >= len(tds) or tds[mi].get_text(strip=True) == "" or tid in seen:
            continue
        seen.add(tid)

        def cell(i):
            if i >= len(tds):
                return 0
            t = tds[i].get_text(strip=True).replace("\xa0", "")
            if t in ("", "-", "\u2011"):
                return 0
            t = re.sub(r"[^\d]", "", t)
            return int(t) if t.isdigit() else 0

        out.append({"tid": tid, "name": link.get_text(strip=True),
                    "g": cell(gi), "a": cell(ai), "m": cell(mi)})
    return out


def scrape(season, comp):
    clubs = get_clubs(season)
    print(f"  {len(clubs)} clubs\n")
    time.sleep(SLEEP)
    raw = {}
    for i, c in enumerate(clubs, 1):
        try:
            rows = get_perf(c["slug"], c["id"], season, comp)
        except Exception as e:
            print(f"  [{i}/{len(clubs)}] {c['slug']}: ERREUR {e}")
            rows = []
        raw[c["slug"]] = rows
        print(f"  [{i}/{len(clubs)}] {c['slug']:<22} {len(rows):>3} joueurs | "
              f"{sum(r['g'] for r in rows):>3} buts")
        time.sleep(SLEEP)
    return raw


def build_index(raw):
    """exact: clé -> lignes ; sur: patronyme -> lignes."""
    exact, sur = collections.defaultdict(list), collections.defaultdict(list)
    for rows in raw.values():
        for r in rows:
            r = dict(r, tk=toks(r["name"]))
            exact[key(r["name"])].append(r)
            exact[squash(r["name"])].append(r)
            if r["tk"]:
                sur[r["tk"][-1]].append(r)
    return exact, sur


def agg(rows):
    """Cumule si le joueur a été transféré en cours de saison (2 clubs)."""
    uniq = {r["tid"]: r for r in rows}
    return {f: sum(r[f] for r in uniq.values()) for f in ("g", "a", "m")}


def match(p, exact, sur):
    """3 passes, de la plus sûre à la plus permissive. Renvoie (stats, passe) ou (None, None).

    Volontairement conservateur : on n'utilise que `fullname` (jamais le patronyme seul,
    qui produit des faux positifs du type « Élie N'Gatta » -> « Ange Loïc N'Gatta »),
    et P2/P3 exigent prénom ET patronyme concordants.
    """
    n = p.get("fullname") or p.get("name")
    if not n:
        return None, None
    tk = toks(n)

    # P1 — égalité stricte (après alias jr/junior)
    for k in (key(n), squash(n)):
        if k in exact:
            return agg(exact[k]), "P1"
    if len(tk) < 2:
        return None, None
    st = set(tk)

    # P2 — un nom est inclus dans l'autre, mêmes 1er et dernier tokens, candidat unique
    cand = {r["tid"]: r for r in sur.get(tk[-1], [])
            if r["tk"] and r["tk"][0] == tk[0] and (st <= set(r["tk"]) or set(r["tk"]) <= st)}
    if len(cand) == 1:
        return agg(list(cand.values())), "P2"

    # P3 — même patronyme unique + orthographe très proche (Gauthier/Gautier, Anto/Antoine)
    cand = {r["tid"]: r for r in sur.get(tk[-1], [])}
    if len(cand) == 1:
        r = next(iter(cand.values()))
        ratio = lambda a, b: difflib.SequenceMatcher(None, a, b).ratio()
        if ratio(" ".join(tk), " ".join(r["tk"])) >= 0.86 and ratio(tk[0], r["tk"][0]) >= 0.70:
            return agg([r]), "P3"
    return None, None


def main():
    label = f"{SEASON}-{SEASON + 1}"
    print(f"Stats Ligue 2 {label} (comp={COMP or 'toutes'}) -> fusion dans {IN}")

    raw = None
    if USE_CACHE:
        try:
            raw = json.load(open(CACHE, encoding="utf-8"))
            print(f"  cache relu : {CACHE} ({sum(len(v) for v in raw.values())} lignes)")
        except OSError:
            raw = None
    if raw is None:
        raw = scrape(SEASON, COMP)
        json.dump(raw, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  cache écrit : {CACHE}")

    exact, sur = build_index(raw)
    print(f"  {sum(len(v) for v in raw.values())} lignes de stats indexées.\n")

    data = json.load(open(IN, encoding="utf-8"))
    counts = collections.Counter()
    unmatched = []
    for club, v in data["teams"].items():
        for pl in v["squad"]:
            s, how = match(pl, exact, sur)
            counts[how or "MISS"] += 1
            if s:
                pl["g"], pl["a"], pl["m"] = s["g"], s["a"], s["m"]
            else:
                pl["g"], pl["a"], pl["m"] = 0, 0, 0
                unmatched.append(f"{club}/{pl.get('fullname')}")

    data["statsSeason"] = label
    data["statsComp"] = COMP or "all"
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    tot = sum(counts.values())
    ok = tot - counts["MISS"]
    print(f"✅ {OUT} — {ok}/{tot} joueurs appariés ({100 * ok // tot}%) "
          f"[P1 {counts['P1']} · P2 {counts['P2']} · P3 {counts['P3']}]")
    print(f"   {counts['MISS']} sans stats L2 {label} : recrues, jeunes, joueurs venus "
          f"d'une autre division -> 0 but / 0 passe (valeur correcte).")


if __name__ == "__main__":
    main()
