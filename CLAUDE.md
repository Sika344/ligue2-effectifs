# CLAUDE.md — Projet `ligue2-effectifs`

> Mémoire de contexte pour reprendre le projet sans repartir de zéro.
> **Dernière mise à jour :** session du 8 juillet 2026.

---

## 1. Vue d'ensemble

Site public de stats football (Ligue 2) hébergé sur **GitHub Pages**.

- **Repo :** `Sika344/ligue2-effectifs`
- **Live :** `https://sika344.github.io/ligue2-effectifs/`
- **Collaborateur :** Maxime Duplaa (RC Strasbourg)
- **Saison de référence (courante) :** Ligue 2 2025/2026 — StatsBomb `competition_id=8`, `season_id=318`

### Pages HTML
| Fichier | Rôle |
|---|---|
| `index.html` | EFFECTIF (effectif complet, terrain + cartes joueurs) |
| `compo.html` | COMPO (compo avec stats buts/passes par joueur) |
| `compo-sans-stats.html` | COMPO sans stats (`const stats=""`) |
| `analytics.html` | Analytics 360 |
| `rapport-pre-match.html` | Rapport pré-match interactif (multi-slides) |

---

## 2. Workflow de déploiement (IMPORTANT)

Claude **n'a pas** d'accès en écriture GitHub. Le cycle est :

1. Claude lit les fichiers publics via
   `curl -s "https://raw.githubusercontent.com/Sika344/ligue2-effectifs/main/<fichier>?t=$(date +%s)"`
   → le **cache-buster `?t=`** est indispensable (raw.githubusercontent met agressivement en cache).
2. Claude prépare les fichiers édités dans les outputs.
3. **Geoffrey déploie manuellement** par glisser-déposer sur
   `github.com/Sika344/ligue2-effectifs/upload/main` → Commit changes.
   → **Astuce :** supprimer l'ancien fichier du dossier Téléchargements avant de re-télécharger, sinon doublons `fichier (1).html`. Les fichiers de **même nom** écrasent l'existant (pas de doublon côté repo).
4. Délai normal de ~1–10 min après commit avant mise à jour live (cache CDN GitHub Pages).

**À ne pas oublier :**
- L'API REST `api.github.com` est **systématiquement rate-limitée** depuis l'IP partagée de Claude → inutilisable. Pour diagnostiquer un run Actions, Geoffrey consulte directement l'onglet **Actions** sur GitHub.
- Validation syntaxique JS : extraire les blocs `<script>` inline avec Python (`re.findall`) puis `node --check`.
- Validation Python : `python3 -m py_compile build_inposs.py`.

---

## 3. Pipeline de données

- **Source :** API StatsBomb. Credentials en **GitHub Actions secrets** :
  `SB_USERNAME`, `SB_PASSWORD` (⚠️ nom correct = `SB_USERNAME`, pas `SB_SURNAME`).
- Les scripts `build_*.py` sont **committés à la racine du repo** (l'Action en a besoin pour tourner) ; **seuls les credentials ne sont jamais committés** (ils passent par les secrets, lus automatiquement par `statsbombpy`).
- ⚠️ `build_rapport.py` n'est **PAS** dans le repo (local Mac uniquement). `fetch_tm.py` et `fetch_ligue2.py` y sont.
- **Tous les scripts sont saison-conscients** (cf. §12) : sortie non suffixée pour la saison courante, suffixée sinon.
- `shot_type == "Penalty"` **exclu** du NP xG et du Set pieces xG. `period == 5` (tirs au but) exclu des comptages d'événements.

### Fichiers JSON générés (saison courante)
| JSON | Généré par | Workflow | Cron |
|---|---|---|---|
| `ligue2.json` | (Actions LFP, photos + logos joueurs/clubs) | — | — |
| `xg.json` | `build_xg.py` | `xg.yml` | 04:30 UTC |
| `inposs.json` | `build_inposs.py` | `inposs.yml` | 04:45 UTC |

⚠️ **Piège YAML :** le bloc de triggers doit être indenté de 2 espaces sous `on:`, sinon erreur *"No event triggers defined in `on:`"*. Placer les `.yml` dans `.github/workflows/` (pas à la racine).

⚠️ **Décalage de rosters `ligue2.json` vs `inposs.json` :** `ligue2.json` (source des **écussons**, noms LFP) ne contient pas forcément les mêmes 18 clubs qu'`inposs.json` (source des **valeurs**, noms StatsBomb). Actuellement `ligue2.json` liste Dijon/Metz/Nantes/Sochaux alors qu'`inposs.json` a Amiens/Bastia/Le Mans/Troyes. Géré côté HTML par une **carte d'écussons de secours** (cf. §6).

---

## 4. Ce qui a été fait à la DERNIÈRE session (7 juil. 2026)

### 4.1 Sélecteur de saison — FINALISÉ & déployé (cf. §5)
La liste déroulante saison (2026-2027 / 2025-2026 / 2024-2025) est intégrée et testée sur `rapport-pre-match.html`.

### 4.2 Diapo IN-POSSESSION — équipes montées/descendues affichées
- **Problème :** les strip plots ne dessinaient que les équipes présentes dans `ligue2.json` ∩ `inposs.json`. Amiens, Bastia, **Le Mans**, **Troyes (ESTAC)** avaient leurs valeurs KPI mais **pas d'écusson** → écartés.
- **Correctif :** ajout de la carte `INP_CRESTS` (écussons fotmob de secours) + réécriture de `inpRows` pour **itérer sur toutes les équipes ayant une valeur dans `inposs.json`**, le logo venant de `ligue2.json` (via `matchTeam`) sinon de la carte de secours.

### 4.3 Diapo IN-POSSESSION — 2 nouveaux KPI (6 → 8)
- **Set pieces xG** : somme des `shot_statsbomb_xg` hors penalty sur coups de pied arrêtés (`play_pattern` ∈ {`From Corner`, `From Free Kick`, `From Throw In`}), moyenne/match (arrondi 3).
- **Counter attacking shots conceded** : miroir de « Counter attacking shots » = tirs `From Counter` **de l'adversaire** dans les matchs de l'équipe, moyenne/match (arrondi 2).
- Ajoutés **côté HTML** (`INP_KPIS` + `INP_SUBTITLE`, panneaux en 4e rangée, disposition 2 colonnes inchangée) **et côté `build_inposs.py`** (compteurs `setpiece_xg` / `counter_conceded`, sortie dans `teams_out`). La grille passe à 8 panneaux (4×2).

---

## 5. Sélecteur de saison (DÉPLOYÉ)

Liste déroulante en tête de `rapport-pre-match.html` (à gauche du sélecteur de club).

**Conventions :**
- `CURRENT_SEASON = "2025-2026"` ; `SEASONS = ["2026-2027","2025-2026","2024-2025"]` (ordre d'affichage).
- **2025-2026 (courante) INCHANGÉE :** DATA bakée dans le HTML + JSON **non suffixés** (`ligue2.json`, `xg.json`, `inposs.json`). Ces blobs sont **mis en cache au démarrage** (`CUR`) → retour instantané sur la saison courante.
- **Saisons non-courantes :** JSON **suffixés** `rapport_<saison>.json` (format `{clubs, byClub}`, équivalent de `DATA`), `ligue2_<saison>.json`, `xg_<saison>.json`, `inposs_<saison>.json`.
- **Fallback gracieux :** si `rapport_<saison>.json` est absent → message **« Données à venir pour cette saison. »** (donc 2026-2027 vide tant que la saison n'a pas commencé).

**Implémentation JS (dans `rapport-pre-match.html`) :**
- `let SEASON_DATA = DATA;` — données de la saison active (remplace les usages directs de `DATA` dans `renderClub`, `clubColor`, `buildClubSelect`).
- `loadSeason(season)` — charge les 4 sources de façon saison-consciente ; applique `PLAYER_OVERRIDES` sur `LIGUE2`.
- `buildClubSelect()` — remplit le `<select>` club, sélectionne Montpellier par défaut, ou affiche « données à venir ».
- `fetchJSON(url)` — helper `fetch` + cache-buster + catch → null.
- `start()` — remplit le `<select>` saison et appelle `loadSeason(CURRENT_SEASON)`.

**Pour remplir une saison passée :** déposer `rapport_<saison>.json` + les 3 JSON suffixés. **Aucune modif HTML nécessaire.** (Générer les JSON suffixés = adapter `build_*.py` avec le `season_id` StatsBomb correspondant.)

---

## 6. Diapo IN-POSSESSION — état détaillé

`inposs.json` : `{competition, season, season_id, updated, kpis, teams}`, `teams[nomStatsBomb][kpi] = valeur`.

### Les 8 KPI (ordre = `INP_KPIS` HTML = `KPIS` Python)
| KPI | Définition | Agrégation |
|---|---|---|
| NP xG | somme `shot_statsbomb_xg` hors penalty | moyenne/match |
| Directness | vitesse de progression vers le but (m/s) | agrégat saison (prog_m / dur_s) |
| Box Penetration | entrées surface (passes complétées + conduites) | moyenne/match |
| Counter attacking shots | tirs `play_pattern == "From Counter"` | moyenne/match |
| Cross to pass ratio – Box entry | part des entrées surface par centre (%) | agrégat saison |
| Crosses into box | centres (`pass_cross`) finissant dans la surface | moyenne/match |
| **Set pieces xG** | xG hors penalty sur `From Corner`/`From Free Kick`/`From Throw In` | moyenne/match |
| **Counter attacking shots conceded** | tirs `From Counter` de l'adversaire | moyenne/match |

- Rendu : 8 panneaux, grille `.inpgrid` 2 colonnes (`:nth-child(2n)` supprime la bordure droite), P50/P90, MHSC en surbrillance (`.sel`), autres `.dim`.
- Chaque panneau lit `INP.teams[team][kpi]`. Un panneau sans données affiche « Données indisponibles » (donc pas de blocage tant qu'`inposs.json` ne contient pas la clé).
- Géométrie StatsBomb : terrain 120×80 yards, attaque vers `x=120` ; surface adverse `x∈[102,120]`, `y∈[18,62]` ; distances ×0.9144 (m) pour Directness.

### Écussons de secours (`INP_CRESTS`, clé = nom StatsBomb → URL fotmob)
Pour les équipes montées/descendues absentes de `ligue2.json`. Format logo fotmob :
`https://images.fotmob.com/image_resources/logo/teamlogo/<id>.png`

| Équipe (nom StatsBomb) | fotmob id | Statut |
|---|---|---|
| Troyes | 10242 | montée (ESTAC) |
| Le Mans | 8682 | montée |
| Amiens | 8587 | descente |
| Bastia | 7794 | descente |

`inpLogo(nom)` : cherche le logo dans `ligue2.json` (nom direct puis `matchTeam`), sinon `INP_CRESTS[nom]`, sinon "". Étendre cette carte pour toute équipe manquante d'un `ligue2_<saison>.json`.

---

## 7. Design des pages COMPO (état)

- `.header` : bandeau texture diagonale navy+or en base64 JPEG inline.
- Écussons clubs : `drop-shadow`.
- Terrain pleine largeur (`.board` fond `#fff`, `padding:0`, `overflow:hidden`, `border-radius:0`).
- Équerres or `.corner` masquées (`display:none`).
- Lignes de stats buts/passes en flexbox (`align-items:center`), icônes 15px.
- `compo-sans-stats.html` : `const stats=""` pour supprimer les stats.

---

## 8. Export Keynote / PNG (pptxgenjs)

- **html2canvas** peu fiable pour les éléments en CSS `transform` et le gros texte gras → les rendre en **shapes/text natifs pptxgenjs**.
- Jetons de match : ellipses natives pptxgenjs depuis `getBoundingClientRect`.
- Titres de match masqués pendant la capture de fond, puis redessinés en texte natif avec runs colorés par équipe.
- Écussons : overlays `<img>` (pas `<image>` SVG) ; inlining via proxy weserv.nl dans `snap()` / `snapLayeredBoard()`.
- ⚠️ Capitalisation : le bundle expose **`PptxGenJS`** → `new (window.PptxGenJS||window.pptxgenjs)()`.
- Les écussons de secours (`INP_CRESTS`, fotmob) passent par le même pipeline `<img>` → export OK.

---

## 9. `PLAYER_OVERRIDES` (correctifs joueurs)

Injecté dans les pages effectif ; clé = `sbId`. Corrige n°/nom mal étiquetés et masque les partis :
- `132337` → EVERSON JR #77 (était DA SILVA #37) ; `166384` → #24 ; `440216` → #14.
- `hide: true` : Omeragic (30661), Coulibaly (32672), Chotard (29969).
- Extraction nom composé brésilien : StatsBomb prend le **dernier token** → **ne pas re-investiguer l'algo upstream**, utiliser la map d'overrides.

---

## 10. Pièges documentés (rappel)

- Rate-limit API GitHub sur IP partagée → utiliser `raw.githubusercontent.com`.
- Indentation YAML des triggers `on:` (cf. §3) ; `.yml` dans `.github/workflows/`.
- `xg.yml` avait été mal placé à la racine ; `inposs.yml` avait été committé vide (1 octet).
- Typo secret `SB_SURNAME` → correct : `SB_USERNAME`.
- Rosters `ligue2.json` ≠ `inposs.json` → carte `INP_CRESTS` (cf. §6).
- Credentials StatsBomb déjà exposés en chat par le passé → rotation du mot de passe recommandée (non confirmée).

---

## 11. Point de reprise immédiat

✅ **FAIT (vérifié le 8 juil. 2026)** — `inposs.json` régénéré le 2026-07-07T14:29:49Z : 8 KPI × 18 équipes, **aucune clé manquante**. Les panneaux *Set pieces xG* (MHSC 0.523) et *Counter attacking shots conceded* (MHSC 0.12) se remplissent. `INP_KPIS` / `INP_CRESTS` / sélecteur de saison présents dans le HTML live, JS validé `node --check`.

➡️ **En cours : activer le sélecteur sur 2024-2025.** Les 3 scripts sont paramétrés (cf. §12). Il manque **`rapport_2024-2025.json`**, généré par `build_rapport.py` — script **absent du repo**, à récupérer en local.

---

## 12. Générer une saison passée

Le sélecteur de saison exige **4 JSON suffixés** (`loadSeason()` les charge en parallèle) ; si `rapport_<saison>.json` manque → « Données à venir pour cette saison. »

| JSON | Produit par | Où le lancer |
|---|---|---|
| `rapport_2024-2025.json` | `build_rapport.py` | **local** (script hors repo) |
| `ligue2_2024-2025.json` | `fetch_tm.py 2024` | **local** (Transfermarkt bloque les IP datacenter) |
| `xg_2024-2025.json` | `build_xg.py` | **Action** *Build xG (15 min)* → Run workflow → saison |
| `inposs_2024-2025.json` | `build_inposs.py` | **Action** *Build in-possession KPIs* → Run workflow → saison |

### Convention commune (les 3 scripts patchés)
- `CURRENT_SEASON = "2025-2026"` (`CURRENT_TM_SEASON = 2025` dans `fetch_tm.py`).
- Saison courante → sortie **non suffixée** (`inposs.json`, `xg.json`, `ligue2.json`). Autre saison → **`<base>_<saison>.json`**.
- Saison lue depuis **`argv[1]`**, sinon **`$SEASON`**, sinon `CURRENT_SEASON`. (`argv[1]` prime.)
- `build_*.py` : le **`season_id` StatsBomb est résolu automatiquement** par `lookup_season_id()` via `sb.competitions()` (libellé `2024-2025` → `2024/2025`). En cas d'échec, le log de l'Action **imprime la liste des saisons disponibles** avec leurs ids. Les ids connus sont mémorisés dans `SEASON_IDS` (`{"2025-2026": 318}`) pour éviter l'appel réseau.
- Workflows : `workflow_dispatch.inputs.season` (défaut `""` = saison courante), passé en `env: SEASON`. Le **cron reste sur la saison courante**. `concurrency.group` inclut la saison → un run manuel n'annule pas le cron.
- Étape commit : glob `inposs*.json` / `xg*.json` → committe le fichier suffixé sans modif du YAML.

### Marche à suivre
1. Local : `python fetch_tm.py 2024` → `ligue2_2024-2025.json`.
2. Local : `build_rapport.py` en mode 2024-2025 → `rapport_2024-2025.json` (format `{clubs, byClub}`).
3. Actions → *Build xG (15 min)* → Run workflow → `season = 2024-2025` (auto-commit).
4. Actions → *Build in-possession KPIs* → Run workflow → `season = 2024-2025` (auto-commit).
5. Déposer les 2 JSON locaux à la racine du repo.
6. Vérifier `INP_CRESTS` : compléter uniquement pour les clubs 24-25 **absents de `ligue2_2024-2025.json`** (a priori aucun, puisque `fetch_tm.py` récupère les écussons de tous les clubs de la saison scrapée).

**Aucune modification de `rapport-pre-match.html` n'est nécessaire.**
