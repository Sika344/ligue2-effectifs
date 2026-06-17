# Effectifs Ligue 2 — site

Mini-site affichant l'effectif de chaque club de Ligue 2 sur un terrain (format « EFFECTIF »).

- **Front** : `index.html` (vanilla, zéro dépendance) — lit `ligue2.json`, hébergé sur GitHub Pages.
- **Données** : `fetch_tm.py` scrape Transfermarkt et écrit `ligue2.json`.

## Mettre à jour les données (en local, sur ton Mac)

Transfermarkt bloque les IP datacenter : le scraper tourne donc **localement**, pas dans le cloud.

```bash
git clone https://github.com/Sika344/ligue2-effectifs.git
cd ligue2-effectifs
pip install requests beautifulsoup4 lxml

python fetch_tm.py 2025 --push   # scrape la saison 2025-26, écrit ligue2.json, commit & push
```

Le site se met à jour automatiquement après le push (~1 min, le temps du build Pages).
Pour une autre saison : `python fetch_tm.py 2024`.

## Source alternative (optionnelle)
`fetch_ligue2.py` + le workflow *MAJ effectifs (API-Football)* permettent d'alimenter le site
via API-Football (clé en secret `API_FOOTBALL_KEY`) si tu réactives ce compte. Onglet Actions → Run workflow.
