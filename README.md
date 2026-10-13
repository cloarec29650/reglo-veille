# Reglo · Veille marché QHSE / RSE automatisée

Collecte chaque semaine des signaux de marché et produit un **digest** en deux formats, à partager à l'équipe :
- `reports/veille-AAAA-Sxx.html` : page autonome (CSS intégré), à ouvrir dans un navigateur ou à envoyer par email ;
- `reports/veille-AAAA-Sxx.md` : même contenu en Markdown (aperçu VS Code : `Ctrl+Shift+V`).

Sans IA générative : classement par mots-clés, données ouvertes officielles.

| Volet | Sources | Ce que ça alimente |
|---|---|---|
| Presse & tendances | ~22 recherches métier Bing News (DUERP, faute inexcusable, VSME, ICPE, logiciel QHSE…) + flux spécialisés (ANACT, Actu-Environnement, Qualiblog…) et généralistes | Veille stratégique, environnement externe (PESTEL) |
| Réglementation | EUR-Lex (SPARQL Cellar) : actes et propositions UE sur la durabilité, la santé-sécurité, REACH, ESRS, CSRD, CS3D | Veille réglementaire, argumentaire produit |
| Concurrents | Pages publiques (changements, alerte prix), blogs, mentions dans la presse, annonces légales BODACC par SIREN | Mapping concurrentiel, positionnement |
| Indicateurs marché | Assurance Maladie (entreprises par taille et secteur), BOAMP (appels d'offres), France Travail (offres d'emploi, optionnel) | Étude de marché, taille du marché, segmentation |
| Sinistralité AT/MP | Assurance Maladie (accidents du travail, maladies professionnelles par secteur) | Segmentation, priorisation des secteurs, argumentaire |

## Installation

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Utilisation

```bash
.venv\Scripts\python -m veille run                        # collecte tout + digest des 7 derniers jours
.venv\Scripts\python -m veille run --open                 # idem, puis ouvre le digest HTML dans le navigateur
.venv\Scripts\python -m veille run --only press,atmp      # volets choisis : press, competitors, market, atmp
.venv\Scripts\python -m veille digest --days 30           # régénère un digest sur 30 jours, sans collecter
.venv\Scripts\python -m pytest                            # tests (hors ligne)
```

- **Premier passage** : les pages concurrentes sont enregistrées comme **référence** ; les changements
  apparaissent à partir du passage suivant.
- **France Travail** : créer une application gratuite sur francetravail.io (API « Offres d'emploi v2 »), puis
  définir `FT_CLIENT_ID` et `FT_CLIENT_SECRET` dans l'environnement. Sans ces variables, le volet est ignoré.
  **Ne jamais écrire ces identifiants dans un fichier du projet.**

## Dashboard (Streamlit)

```bash
.venv\Scripts\streamlit run dashboard.py      # ou double-clic sur lancer_dashboard.bat
```

Ouvre http://localhost:8501. Le dashboard lit l'historique `data/veille.sqlite` et propose :
- **Presse** : articles filtrables (thème, source, recherche), répartition par thème ;
- **Concurrents** : changements détectés (ajouts / retraits, alerte prix), pages suivies, mentions presse ;
- **Marché & segmentation** : entreprises par tranche, **calcul interactif du marché adressable** (tranches et
  prix au choix), nuage secteurs « taille du segment × indice de fréquence AT » ;
- **Sinistralité AT/MP** : indice de fréquence par secteur vs moyenne nationale ;
- **Appels d'offres** et **Sources** (état de chaque source).

Le bouton **Lancer une collecte** (barre latérale) rafraîchit les données et régénère le digest.
Chaque graphique a son tableau « Voir les données ». Thème : `.streamlit/config.toml` ; couleurs des
graphiques : constantes en tête de `dashboard.py` (à aligner sur la charte Reglo).

> Après une modification de `dashboard.py`, relancer Streamlit : la détection automatique des changements
> ne fonctionne pas toujours dans un dossier OneDrive.

## Mise en ligne (Streamlit Community Cloud)

Le dépôt est conçu pour être **privé** : la base contient des extraits de presse et le texte des pages
concurrentes, qui n'ont pas à être publics.

1. **GitHub** : créer un dépôt **privé** vide (ex. `reglo-veille`), puis depuis ce dossier :
   `git remote add origin https://github.com/<compte>/reglo-veille.git` et `git push -u origin main`.
2. **Streamlit** : sur https://share.streamlit.io, se connecter avec GitHub (autoriser l'accès aux dépôts
   privés), *Create app* → dépôt `reglo-veille`, branche `main`, fichier `dashboard.py`,
   *Advanced settings* → Python **3.11**.
3. **Partage** : dans les réglages de l'app, *Sharing* → laisser l'app privée et inviter l'email de chaque
   personne. Elle se connecte avec Google ou par un lien reçu par email.
4. **Collecte automatique** : actuellement depuis un PC (voir « Automatiser ») ; chaque passage pousse la
   base et le digest dans le dépôt, et Streamlit redéploie l'app à chaque commit. Le workflow
   `.github/workflows/veille.yml` reste disponible en lancement manuel (onglet *Actions* → *Veille quotidienne*).

En ligne, le dashboard est en **lecture seule** (pas de bouton de collecte) : le disque de Streamlit Cloud
est temporaire et les visiteurs ne doivent pas déclencher de collecte.

## Direction visuelle

Digest HTML et dashboard partagent une même identité, tirée du vocabulaire QHSE : **un registre d'inspection**.

| Rôle | Valeur |
|---|---|
| Fond « papier de rapport » | `#f3f5f6` |
| Encre ardoise | `#1b2430` (secondaire `#5b6672`, filets `#d3d9de`) |
| Liens | bleu « obligation » ISO 7010 `#005387` |
| Série des graphiques | `#1f6fb0` (validé : plage de luminosité et contraste) |
| Typographie | Barlow Condensed (titres, numéro de semaine), Barlow (texte) |

Pour passer à la charte Reglo : variables CSS de `veille/html_export.py`, constantes et `PAGE_CSS`
de `dashboard.py`, thème de `.streamlit/config.toml`.

## Configurer (`config.yaml`)

Tout ce qui relève de **l'analyse** est un choix de l'équipe, à justifier :
- `themes` : thèmes et mots-clés ; `core: true` = un article qui touche ce thème est retenu.
- `competitors` : concurrents suivis, catégorie, pages (ajouter les pages **tarifs**), noms détectés dans la presse.
- `market.target_size_orders` : tranches d'effectif ciblées (par défaut 10 à 499 salariés).
- `market.annual_price_by_size_order` : hypothèses de prix annuel → calcul du **marché adressable en €**.
- `tenders.keywords`, `jobs.keywords` : termes recherchés dans BOAMP et France Travail.

## Automatiser

**Windows (mode actuel)** : la tâche planifiée « Reglo - Veille quotidienne » lance `run_veille.bat` chaque
jour à 8 h (ou dès le démarrage du PC si 8 h a été manquée). Le script collecte, régénère le digest, commite
`data/veille.sqlite` et `reports/` s'il y a du nouveau, puis pousse sur GitHub. Journal : `data\veille.log`.

```powershell
Start-ScheduledTask -TaskName "Reglo - Veille quotidienne"     # lancer maintenant
Get-ScheduledTaskInfo -TaskName "Reglo - Veille quotidienne"   # dernier et prochain passage
Disable-ScheduledTask -TaskName "Reglo - Veille quotidienne"   # suspendre
```

**Une seule source doit écrire la base** : pour revenir à GitHub Actions (compte débloqué), réactiver le bloc
`schedule` du workflow et désactiver la tâche Windows.

**VPS (plus tard)** : même principe via `cron`, par exemple
`0 6 * * * cd /opt/veille && .venv/bin/python -m veille run && git add data reports && git commit -m veille && git push`.

## Architecture

```
config.yaml                 sources, thèmes, concurrents, hypothèses
dashboard.py                dashboard Streamlit
veille/
├── __main__.py             ligne de commande (run / digest)
├── http.py                 client poli : robots.txt, délai entre requêtes, user-agent identifié
├── text.py                 nettoyage et normalisation
├── classify.py             thèmes + concurrents cités, score de pertinence (sans LLM)
├── storage.py              SQLite (data/veille.sqlite) : historique complet
├── digest.py               rapport Markdown hebdomadaire
├── html_export.py          page HTML autonome (charte : variables CSS en tête de fichier)
├── queries.py              lecture de l'historique en DataFrames (pour le dashboard)
└── collectors/
    ├── press.py            flux RSS
    ├── competitors.py      instantanés de pages + différences
    ├── market.py           Assurance Maladie (taille du marché), BOAMP, France Travail
    └── atmp.py             sinistralité AT/MP par secteur
tests/                      tests hors ligne (pytest)
reports/                    digests générés
```

Chaîne de traitement : **collecte → nettoyage → classement → déduplication → stockage historisé → restitution**.
Une source en panne n'arrête pas les autres ; son état apparaît dans la section « Sources & méthode » du digest.

## Éthique, droit et limites

- **robots.txt respecté**, user-agent identifié, au moins 1,5 s entre deux requêtes vers un même site.
- **Sites qui refusent les robots (401/403)** : pas de contournement (pas d'usurpation de navigateur),
  la source passe en « suivi manuel ». Écartés à ce jour : Google News (robots.txt), Éditions Tissot,
  Tennaxia, Ennov, Greenly (403).
- **Droit voisin de la presse** : seuls le titre, le lien et un extrait court (≤ 280 caractères) sont conservés.
- **Pas de données personnelles** collectées (pas de LinkedIn, pas de profils).
- Données **Assurance Maladie = régime général** : le régime agricole (MSA) n'y figure pas.
- Le classement par mots-clés produit des faux positifs et des oublis : ajuster `themes` au fil des digests.
- Les chiffres sont des données brutes datées : **l'interprétation et les choix stratégiques restent à l'équipe.**
