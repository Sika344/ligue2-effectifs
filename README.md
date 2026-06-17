# Effectifs Ligue 2 — live

Mini-site affichant l'effectif de chaque club de Ligue 2 sur un terrain, au format « EFFECTIF ».

- **Front** : `index.html` (vanilla, zéro dépendance), lit `ligue2.json`.
- **Données** : API-Football (`league=62`), récupérées par `fetch_ligue2.py`.
- **Auto-actualisation** : GitHub Actions, tous les lundis (cron) + déclenchement manuel.

## Configuration
La clé API est stockée dans le secret de dépôt `API_FOOTBALL_KEY` (Settings → Secrets and variables → Actions).
Le plan gratuit d'API-Football ne donne accès qu'aux saisons 2022→2024 : le pipeline est calé sur `SEASON=2024`.

## Lancer la récupération
Onglet **Actions** → *MAJ effectifs Ligue 2* → **Run workflow**.
Le job écrit `ligue2.json` et le commite ; le site se met à jour automatiquement.
