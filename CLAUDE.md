# CLAUDE.md — ligue2-effectifs

Document de continuite de session. A lire en debut de chaque session avant toute modif.
Objectif : afficher l effectif de chaque club de Ligue 2 sur un terrain, format "EFFECTIF"
(cadre navy/or, photos buste, drapeau, numero, taille/age, buts/passes, "G" pour les gauchers),
+ un constructeur de compo. Mise a jour automatisable via GitHub Actions.

## Liens
- Repo (public) : https://github.com/Sika344/ligue2-effectifs  (compte Sika344)
- Site : https://sika344.github.io/ligue2-effectifs/  (board)  +  /compo.html  (compo)
- Pages : branche `main`, dossier `/` (le site lit `ligue2.json` au chargement, cote client).

## Stack
HTML/CSS/JS statique (pas de build) servi par GitHub Pages. Donnees en JSON dans le repo.
Pipelines Python lances sur GitHub Actions (pas en local). Pas de Vercel ici.

## Arborescence (roles)
- `index.html` — board EFFECTIF (placement 2D auto par poste), bandeau image + titre
  American Typewriter, case "Masquer ceux qui ne jouent pas", export PNG + Keynote.
- `compo.html` — constructeur de XI (memes cartes/visuel), export PNG + Keynote.
- `fetch_statsbomb.py` — **PIPELINE ACTIF**. StatsBomb player-stats -> `ligue2.json`,
  fusion avec LFP. Contient POS / POS_NAME / map_pos, flag(), TEAM_NAME_MAP, FOOT_OVERRIDES.
- `enrich_photos_lfp.py` — recupere LFP (ma-api.ligue1.fr) -> `photos_lfp.json`
  (numero, nom, norm, foot, cc nationalite, url photo buste). A relancer apres mercato.
- `ligue2.json` — donnees lues par le site (regenere par fetch_statsbomb).
- `photos_lfp.json` — photos/pied/nationalite/numero LFP (regenere par enrich).
- `fetch_api.py` / `fetch_tm.py` / `fetch_ligue2.py` — anciens pipelines FotMob/RapidAPI/
  Transfermarkt, **dormants** (FotMob a ete coupe, garde en backup).
- `probe*` , `_debug.json`, `*log.txt` — artefacts de diagnostic.
- `.github/workflows/` — voir plus bas.

## Donnees : StatsBomb (stats) + LFP (photos)
FotMob a ete **coupe** : plus aucun appel ni dependance de donnees (les logos de club sont
des URLs figees qui se reportent d un run a l autre via l ancien `ligue2.json`).

### StatsBomb (via `statsbombpy`)
- Source de verite : roster, minutes, matchs, **buts/passes**, **poste**, taille, age, pied.
- Endpoint : `sb.player_season_stats(competition_id=8, season_id=318)` (1 seul appel).
- **Ligue 2 = competition_id 8**, **saison 2025/2026 = season_id 318**.
- Identifiants en **secrets Actions** : `SB_USERNAME`, `SB_PASSWORD` (jamais dans le code/chat).
- Host API `data.statsbombservices.com` : **injoignable depuis le sandbox Claude** (host_not_allowed)
  -> tout fetch StatsBomb tourne sur Actions.
- Buts/passes = per-90 x 90s joues (`player_season_goals_90` * `player_season_90s_played`).
- Pied = `player_season_left_foot_ratio` (>=0.6 gaucher, <=0.4 droitier ; 0.4-0.6 = repli LFP).
- Poste = `primary_position` (StatsBomb renvoie un libelle type "Left Wing" -> mappe par POS_NAME ;
  gere aussi l id entier). ~6% de joueurs (tres peu de minutes) sans poste -> repli ancien JSON.
- player-stats **ne donne PAS** le numero de maillot, la photo, ni la nationalite du joueur
  (le `country_id` = pays de la competition). -> ces 3 champs viennent de LFP.

### LFP (ma-api.ligue1.fr, public, sans auth)
- Fournit : numero, photo buste officielle, pied (preferredFoot), **nationalite (countryShortCode, ISO3)**.
- Endpoints : `championship-club/{cid}` -> playersIds ; `championship-player/{pid}` -> nom,
  birthDate, countryShortCode, preferredFoot, assets.bustPictures.medium.
- `cid = l1_championship_club_2025_{shortId}` ; map shortId par club dans `enrich_photos_lfp.py` (CLUBS).
- Reachable depuis Actions, **bloque depuis le sandbox Claude**.

### Mapping equipes (StatsBomb -> cles canoniques)
Fige dans `fetch_statsbomb.py` (TEAM_NAME_MAP), ex : Bastia->SC Bastia, FC Annecy->Annecy FC,
Grenoble Foot->Grenoble, Red Star FC->Red Star, Stade Lavallois->Laval, Stade de Reims->Reims,
US Boulogne->Boulogne, Saint-Étienne->Saint-Etienne. Les 18 cles : Amiens, Annecy FC, Boulogne,
Clermont Foot, Dunkerque, Grenoble, Guingamp, Laval, Le Mans, Montpellier, Nancy, Pau, Red Star,
Reims, Rodez, SC Bastia, Saint-Etienne, Troyes.

### Corrections manuelles
`FOOT_OVERRIDES` dans `fetch_statsbomb.py` : force le pied quand StatsBomb ET LFP se trompent.
Cle = (cle equipe, nom normalise), valeur "left"/"right". Ex : ("Amiens","kaiboue"):"left".

## Format `ligue2.json`
```
{ season, updated, source, teams: { "<Club>": { logo, squad: [ player, ... ] } } }
player = { num, name, fullname, flag, ccode, height, age, pos, posDesc,
           g, a, mins, apps, starts, photo, photoLFP, foot, sbId }
```
- `pos` grossier (GK/DEF/MID/ATT), `posDesc` detaille (CB, LB, RW, CDM, ST...).
- `foot` == "left" => badge "G". `num` null => joueur non affiche par le board.

## Workflows (.github/workflows)
- **update_statsbomb.yml** (manuel) : lance `fetch_statsbomb.py`, commit `ligue2.json`.
  Inputs pre-remplis comp_id=8 / season_id=318. Secrets SB_USERNAME/SB_PASSWORD. -> MAJ effectifs.
- **enrich.yml** (manuel) : lance `enrich_photos_lfp.py`, commit `photos_lfp.json` (~5 min, ~570 appels LFP).
  A relancer apres un mercato (nouvelles photos/numeros/nationalites), puis relancer update_statsbomb.
- update_api.yml / update.yml / probe*.yml : anciens (FotMob/diagnostic), dormants.
Lancement : onglet Actions -> choisir le workflow -> Run workflow.

## Front-end (rappels d implementation)
- **Carte** : photo buste centree (transparent), colonne gauche (drapeau au-dessus du numero)
  en absolute a gauche, puis nom (MAJ), "taille cm - age ans", boite stats (chiffre orange +
  icone). Badge "G" rouge en haut pres de la tete (foot==="left"). Largeur carte ~132px,
  photo height 66 / max-width 110 (la hauteur pilote le ratio, pas de deformation).
- **Icones stats** : ballon + chaussure en **PNG data-URI** (consts BALL / BOOT). Rendu en
  `<img>` car html2canvas ne sait PAS rendre les emojis ni le SVG inline.
- **Placement (index.html)** : roleOf() classe par 1er token de posDesc ; GK en haut,
  attaquants en bas. Cote equipe inverse a l ecran (GK en haut) => lateraux/ailiers
  GAUCHE a droite de l ecran : DL->x88, DR->x12, ML->x91, MR->x9.
- **Terrain** : clair (`#f3f5f8`->`#e9edf2`), lignes grises. Arc de surface : extremites
  445/555, rayon 66 (corrige).
- **Bandeau** : image navy/or HD en data-URI (const BANNER) en fond du header ; titre
  "EFFECTIF" en American Typewriter (repli Georgia serif), graisse normale.
- **Filtre** : case "Masquer ceux qui ne jouent pas" -> cache `mins < 90` (repli heuristique
  age/numero si pas de minutes). Garde au moins 11 joueurs.
- **Exports** :
  - PNG (#dl) : board capture a plat (html2canvas, scale 2). Les `<img>` http passent par le
    proxy images.weserv.nl pour eviter le canvas tainted ; les data-URI sont laisses tels quels.
  - Keynote .pptx (#dlk) : `pptxLayered()` -> fond = board sans les cartes (image pleine page) +
    **chaque carte exportee en image separee et positionnee** => deplacable dans Keynote.
    Les menus (compo) et emplacements vides sont masques a l export.

## Conventions / regles de travail
- Commits en **francais**, messages clairs.
- **Toujours `git pull --rebase` avant de pousser** (collaboration a 2 -> conflits sur
  ligue2.json/photos_lfp.json sinon).
- Valider avant commit : `python -m py_compile <fichier>.py` et `node --check`/parse du JS.
- Le sandbox Claude n a acces reseau qu a github/pypi/npm. github.io, StatsBomb, LFP, weserv
  sont **bloques** -> le code qui les appelle tourne sur Actions ; Claude lit les resultats
  committes via raw.githubusercontent.com ou l API contents (plus fraiche).
- Claude pousse sur GitHub avec un PAT fourni en debut de session ; il ne possede pas d acces
  direct Pages/StatsBomb/LFP (ceux-ci passent par Actions + secrets).
- Apres un push, Pages reconstruit tout seul ; verifier l etat via l API pages/builds/latest.

## Travail a 2
- Se repartir les fichiers (front vs pipeline) pour ne pas editer le meme en parallele.
- **Ne pas lancer deux fois le meme workflow en parallele** (deux commits de ligue2.json = conflit).
- Petits commits frequents, pull --rebase systematique.

## Securite
- Aucun secret dans le repo ni dans ce fichier. StatsBomb -> secrets Actions uniquement.
- Un PAT colle dans un chat est expose : utiliser un PAT fine-grained limite a ce repo, a
  expiration courte, et le revoquer apres usage.

## TODO / pistes
- Optionnel : poste de repli via `secondary_position` pour les ~6% sans poste detaille.
- Optionnel : cron sur update_statsbomb (ex. hebdo) pour automatiser totalement.
- Optionnel : memes bandeau/police sur compo.html.
- Lister les joueurs en zone de pied ambigue (ratio 40-60%) pour validation manuelle.
