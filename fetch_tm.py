#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper Transfermarkt -> ligue2.json (à lancer EN LOCAL sur ton Mac, IP résidentielle).
Dépendances :  pip install requests beautifulsoup4 lxml
Usage       :  python fetch_tm.py            # saison 2025 (2025-26)
               python fetch_tm.py 2024        # autre saison
               python fetch_tm.py 2025 --push # scrape + git commit/push automatique

Sortie : ligue2.json (format attendu par index.html).
Si une page se parse mal, le HTML brut est sauvé dans _tm_sample.html : envoie-le moi.
"""
import sys, re, json, time, subprocess, unicodedata
import requests
from bs4 import BeautifulSoup

SEASON = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2025
PUSH   = "--push" in sys.argv
BASE   = "https://www.transfermarkt.fr"
SLEEP  = 4                     # politesse entre clubs

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
})

# nationalité (nom FR affiché par transfermarkt.fr) -> code ISO-2 -> emoji
NAT2CC = {
 "France":"FR","Cameroun":"CM","Sénégal":"SN","Mali":"ML","Côte d'Ivoire":"CI","Maroc":"MA",
 "Algérie":"DZ","Tunisie":"TN","Guinée":"GN","Guinée-Bissau":"GW","Nigeria":"NG","Nigéria":"NG",
 "Ghana":"GH","Congo":"CG","RD Congo":"CD","Congo DR":"CD","Gabon":"GA","Burkina Faso":"BF",
 "Cap-Vert":"CV","Comores":"KM","Madagascar":"MG","Angola":"AO","Bénin":"BJ","Togo":"TG",
 "Mauritanie":"MR","Tchad":"TD","Niger":"NE","Centrafrique":"CF","Brésil":"BR","Argentine":"AR",
 "Colombie":"CO","Uruguay":"UY","Chili":"CL","Pérou":"PE","Portugal":"PT","Espagne":"ES",
 "Serbie":"RS","Croatie":"HR","Albanie":"AL","Suisse":"CH","Belgique":"BE","Pays-Bas":"NL",
 "Allemagne":"DE","Italie":"IT","Angleterre":"GB","Écosse":"GB","Pays de Galles":"GB",
 "Irlande":"IE","Irlande du Nord":"GB","Turquie":"TR","Grèce":"GR","Pologne":"PL","Roumanie":"RO",
 "République tchèque":"CZ","Tchéquie":"CZ","Autriche":"AT","Danemark":"DK","Suède":"SE",
 "Norvège":"NO","Finlande":"FI","Liban":"LB","Israël":"IL","Japon":"JP","Corée du Sud":"KR",
 "États-Unis":"US","Canada":"CA","Arménie":"AM","Géorgie":"GE","Kosovo":"XK",
 "Macédoine du Nord":"MK","Bosnie-Herzégovine":"BA","Monténégro":"ME","Slovénie":"SI",
 "Slovaquie":"SK","Ukraine":"UA","Russie":"RU","Guinée équatoriale":"GQ","Jamaïque":"JM",
 "Gambie":"GM","Haïti":"HT","Cap Vert":"CV","Curaçao":"CW","Luxembourg":"LU","Croate":"HR",
 "Guadeloupe":"GP","Martinique":"MQ","Guyane Française":"GF","Guyane française":"GF","République Centrafricaine":"CF","Kenya":"KE","Nouvelle-Zélande":"NZ","Malte":"MT","Estonie":"EE","Réunion":"RE","Nouvelle-Calédonie":"NC","Tahiti":"PF",
}
def _norm(s):  # comparaison insensible aux accents
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()
NAT_NORM = {_norm(k): v for k, v in NAT2CC.items()}

def flag(nat):
    if not nat: return "\U0001F3F3"
    cc = NAT2CC.get(nat) or NAT_NORM.get(_norm(nat))
    if not cc or len(cc) != 2: return "\U0001F3F3"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc.upper())

def pos_group(txt):
    t = _norm(txt or "")
    if "gardien" in t: return "GK"
    if "defenseur" in t or "arriere" in t or "libero" in t: return "DEF"
    if "milieu" in t: return "MID"
    if "avant" in t or "ailier" in t or "attaquant" in t or "buteur" in t: return "ATT"
    return "MID"

def get(url):
    last = None
    for attempt in range(4):
        try:
            r = S.get(url, timeout=45, allow_redirects=True)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(SLEEP * (attempt + 1))
    raise last

def get_clubs(season):
    html = get(f"{BASE}/ligue-2/startseite/wettbewerb/FR2/saison_id/{season}")
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    clubs, seen = [], set()
    if not table:
        with open("_tm_sample.html", "w", encoding="utf-8") as f: f.write(html)
        return clubs
    for tr in table.select("tbody > tr"):
        a = tr.select_one("td.hauptlink a[href*='/verein/']") or tr.select_one("a[href*='/startseite/verein/']")
        if not a: continue
        href = a.get("href", "")
        m = re.search(r"/verein/(\d+)", href)
        if not m or m.group(1) in seen: continue
        cid = m.group(1); seen.add(cid)
        name = (a.get("title") or a.get_text(strip=True)).strip()
        slug = href.strip("/").split("/")[0] or "-"
        cimg = tr.select_one("img[src*='/wappen/']")
        crest = (cimg.get("data-src") or cimg.get("src")) if cimg else None
        if crest: crest = crest.replace("/tiny/", "/head/").split("?")[0]
        clubs.append({"id": cid, "slug": slug, "name": name, "crest": crest})
    return clubs

def parse_squad(html):
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    out = []
    if not table: return out, False
    for tr in table.select("tbody > tr"):
        link = tr.select_one("a[href*='/profil/spieler/']")
        if not link: continue
        name = link.get_text(strip=True)
        if not name: continue
        mtid = re.search(r"/profil/spieler/(\d+)", link.get("href", ""))
        tid = int(mtid.group(1)) if mtid else None
        num_el = tr.select_one(".rn_nummer")
        num = (num_el.get_text(strip=True) if num_el else "") or "?"
        if num in ("", "-", "‑"): num = "?"
        img = tr.select_one("img.bilderrahmen-fixed") or tr.select_one("td img[src*='/portrait/']")
        photo = None
        if img:
            photo = img.get("data-src") or img.get("src")
            if photo and "data:image" in photo: photo = img.get("data-src")
            if photo: photo = photo.replace("/small/", "/medium/").split("?")[0]
        inline = tr.select_one("table.inline-table")
        pos_raw = ""
        if inline:
            rows = inline.select("tr")
            if len(rows) >= 2: pos_raw = rows[-1].get_text(strip=True)
        flagimg = tr.select_one("img.flaggenrahmen")
        nat = flagimg.get("title") if flagimg else None
        rowtxt = tr.get_text(" ", strip=True)
        mh = re.search(r"(\d),(\d{2})\s*m(?![a-z])", rowtxt)
        height = (mh.group(1) + mh.group(2)) if mh else None
        ages = [int(x) for x in re.findall(r"\((\d{1,2})\)", rowtxt) if 14 <= int(x) <= 50]
        age = ages[0] if ages else None
        out.append({
            "num": int(num) if str(num).isdigit() else "?",
            "name": name.upper(), "flag": flag(nat), "nat": nat,
            "height": height, "age": age,
            "pos": pos_group(pos_raw), "photo": photo, "tid": tid,
        })
    order = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}
    out.sort(key=lambda p: (order.get(p["pos"], 9), p["num"] if isinstance(p["num"], int) else 999))
    return out, True

def get_perf(slug, cid):
    """Page 'performances' du club -> {tid: {'g':buts, 'a':passes décisives, 'm':matchs}}."""
    html = get(f"{BASE}/{slug}/leistungsdaten/verein/{cid}/plus/1")
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if not table:
        return {}, html
    hrow = table.select_one("thead tr") or table.select_one("tr")
    cells = hrow.find_all(["th", "td"], recursive=False) if hrow else []
    base = None
    for i, cell in enumerate(cells):
        lab = _norm((cell.get("title") or "") + " " + cell.get_text(" ", strip=True))
        if "effectif" in lab:
            base = i
            break
    anchored = base is not None
    if base is None:
        base = 4                       # repli : #, Joueur, Âge, Nat., Dans l'effectif
    mi, gi, ai = base + 1, base + 2, base + 3   # matchs, buts, passes décisives
    perf = {}
    for tr in table.select("tbody tr"):
        link = tr.select_one("a[href*='/profil/spieler/']")
        if not link:
            continue
        m = re.search(r"/profil/spieler/(\d+)", link.get("href", ""))
        if not m:
            continue
        tid = int(m.group(1))
        tds = tr.find_all("td", recursive=False)
        # TM rend 2 <tr> par joueur : la 2e est vide -> on la saute et on garde la 1re
        if mi >= len(tds) or tds[mi].get_text(strip=True) == "":
            continue
        if tid in perf:
            continue
        def cell(idx):
            if idx is None or idx >= len(tds):
                return None
            t = tds[idx].get_text(strip=True).replace("\xa0", "")
            if t in ("", "-", "\u2011"):
                return 0
            t = re.sub(r"[^\d]", "", t)
            return int(t) if t.isdigit() else None
        perf[tid] = {"g": cell(gi), "a": cell(ai), "m": cell(mi)}
    found = anchored
    return perf, (None if found else html)

def main():
    print(f"Saison {SEASON} — récupération des clubs de Ligue 2…")
    clubs = get_clubs(SEASON)
    if not clubs:
        print("❌ Aucun club trouvé. HTML sauvé dans _tm_sample.html — envoie-le moi."); sys.exit(1)
    print(f"  {len(clubs)} clubs : {', '.join(c['name'] for c in clubs)}")
    teams, sample_saved, perf_sample_saved = {}, False, False
    for i, c in enumerate(clubs, 1):
        url = f"{BASE}/{c['slug']}/kader/verein/{c['id']}/saison_id/{SEASON}/plus/1"
        try:
            html = get(url)
            squad, ok = parse_squad(html)
        except Exception as e:
            print(f"  [{i}/{len(clubs)}] {c['name']}: erreur {e}"); squad = []
        if not squad and not sample_saved:
            with open("_tm_sample.html", "w", encoding="utf-8") as f: f.write(html)
            sample_saved = True
            print(f"     ⚠ 0 joueur — HTML de {c['name']} sauvé dans _tm_sample.html (envoie-le moi)")
        # buts / passes décisives / matchs (page performances)
        if squad:
            time.sleep(SLEEP)
            try:
                perf, psample = get_perf(c["slug"], c["id"])
            except Exception as e:
                perf, psample = {}, None
                print(f"     ⚠ perfs {c['name']}: {e}")
            if psample and not perf_sample_saved:
                with open("_tm_perf_sample.html", "w", encoding="utf-8") as f: f.write(psample)
                perf_sample_saved = True
                print("     ⚠ colonnes buts/passes introuvables — _tm_perf_sample.html sauvé (envoie-le moi)")
            for p in squad:
                pr = perf.get(p.get("tid"))
                if pr:
                    p["g"], p["a"], p["m"] = pr["g"], pr["a"], pr["m"]
        for p in squad:
            p.pop("tid", None)
        teams[c["name"]] = {"logo": c["crest"], "squad": squad}
        nb = sum((p.get("g") or 0) for p in squad)
        print(f"  [{i}/{len(clubs)}] {c['name']}: {len(squad)} joueurs, {nb} buts")
        time.sleep(SLEEP)

    payload = {"season": f"{SEASON}-{SEASON+1}", "updated": time.strftime("%Y-%m-%d %H:%M"), "teams": teams}
    with open("ligue2.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    total = sum(len(v["squad"]) for v in teams.values())
    print(f"\n✅ ligue2.json écrit — {len(teams)} clubs / {total} joueurs")

    if PUSH:
        print("→ commit & push…")
        subprocess.run(["git", "add", "ligue2.json"], check=False)
        subprocess.run(["git", "commit", "-m", f"MAJ effectifs Ligue 2 (TM) {time.strftime('%F')}"], check=False)
        subprocess.run(["git", "push"], check=False)

if __name__ == "__main__":
    main()
