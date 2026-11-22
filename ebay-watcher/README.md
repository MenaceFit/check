# eBay Watcher

Surveille eBay en continu et t'alerte dès qu'une **nouvelle annonce** correspondant à tes mots-clés est publiée,
sur **plusieurs pays à la fois** (France, Royaume-Uni, Allemagne, Italie, Espagne, États-Unis, Belgique, Pays-Bas,
Autriche, Suisse, Irlande, Pologne, Canada, Australie).

- Interface terminal complète : flux des annonces en direct, gestion des recherches, paramètres
- Fichier `config.toml` lisible et modifiable à la main (mots-clés, pays, prix, mots exclus…)
- Alertes **Discord** et **Telegram** (avec photo, prix, frais de port et lien), plus un bip sonore
- Aucune clé requise (lecture des pages eBay), ou **API officielle eBay** en option
- Pas de doublons : une annonce visible sur eBay FR et DE ne déclenche qu'une seule alerte
- Mémoire persistante (SQLite) : un redémarrage ne renvoie pas les anciennes annonces

## Démarrage rapide

Prérequis : **Python 3.11 ou plus récent** ([python.org](https://www.python.org/downloads/), coche « Add to PATH » sous Windows).

| Système | Lancer |
|---|---|
| Windows | double-clic sur `run.bat` |
| macOS / Linux | `./run.sh` |

Le premier lancement installe tout automatiquement dans `.venv/` et crée `config.toml`.
**Commence par lancer le diagnostic**, qui teste en 10 secondes la connexion à chaque pays :

```bat
run.bat doctor          (Windows)
./run.sh doctor         (macOS / Linux)
```

## L'interface

```
run.bat           (ou ./run.sh)
```

| Touche | Action |
|---|---|
| `S` | démarrer / arrêter la surveillance |
| `A` | ajouter une recherche |
| `E` / Entrée | modifier la recherche sélectionnée (onglet ②) |
| `T` | activer / désactiver une recherche |
| `D` | supprimer une recherche |
| `O` / Entrée | ouvrir l'annonce sélectionnée dans le navigateur (onglet ①) |
| `P` | paramètres : intervalle, Discord, Telegram, API… |
| `R` | recharger `config.toml` après une modification à la main |
| `1` `2` `3` | onglets Annonces / Recherches / Journal |
| `Q` | quitter |

Le bas de l'écran montre l'état de chaque cible (recherche × pays) : dernier contrôle, nombre d'annonces lues,
nouvelles trouvées, erreurs éventuelles.

## Le fichier `config.toml`

Chaque recherche est un bloc `[[searches]]` :

```toml
[[searches]]
name = "Switch OLED"
keywords = "nintendo switch oled"        # syntaxe eBay acceptée : -mot, "phrase exacte"
countries = ["fr", "uk", "de"]           # fr uk de it es us be nl at ch ie pl ca au
min_price = 120
max_price = 260
currency = "EUR"                         # devise de min/max, convertie pour chaque pays
exclude = ["boite vide", "coque", "hs"]  # ignore l'annonce si un de ces mots est dans le titre
buying_format = "all"                    # all | bin (achat immédiat) | auction (enchères)
condition = "all"                        # all | new | used
category_id = ""                         # optionnel : n° de catégorie eBay
enabled = true
```

Toutes les options sont commentées dans le fichier généré. Tu peux modifier le fichier pendant que le bot tourne,
puis appuyer sur `R`. Une erreur de syntaxe est signalée et l'ancienne config reste active.

### Notifications

- **Discord** : dans un salon, va dans Modifier le salon > Intégrations > Webhooks > Nouveau webhook > Copier l'URL,
  puis colle l'URL dans `[notifications.discord] webhook_url` ou via `P`.
- **Telegram** : crée un bot avec [@BotFather](https://t.me/BotFather) (tu obtiens le `bot_token`), envoie-lui un
  message, puis récupère ton `chat_id` avec [@userinfobot](https://t.me/userinfobot).
- Pour vérifier : `run.bat test-notify` ou la touche `N` dans l'interface.

## Autres commandes

```bash
run.bat search "lego technic 42143" -c fr it es --max-price 400   # recherche ponctuelle, plus récentes en premier
run.bat search "ps5" -c uk --all                                    # affiche aussi ce que les filtres rejettent
run.bat run                                                         # surveillance sans interface (serveur / VPS)
run.bat doctor -c fr uk de -k "iphone"                              # diagnostic réseau + parsing
run.bat --config autre.toml                                         # utiliser un autre fichier
run.bat -v run                                                      # journal détaillé dans ebaywatch.log
```

## Fonctionnement et réglages

1. Pour chaque recherche et chaque pays, le bot lit la page de recherche eBay **triée par « Plus récentes »**
   (`_sop=10`), avec les filtres prix, format et état appliqués côté eBay.
2. Au **premier passage**, les annonces déjà en ligne sont mémorisées **sans alerte**. Seules les annonces publiées
   ensuite déclenchent une notification. Pour être alerté aussi des annonces existantes, mets
   `notify_existing_on_start = true`.
3. Chaque annonce jamais vue est revérifiée côté client : tous les mots-clés doivent être dans le titre
   (`strict_title_match`), aucun mot exclu, prix dans la fourchette après conversion de devise. Elle est ensuite
   notifiée et enregistrée dans `ebaywatch.db`.
4. La section « Résultats correspondant à moins de mots » d'eBay est ignorée : pas de faux positifs.
5. **Annonces sponsorisées** : eBay glisse d'anciennes annonces sponsorisées dans les résultats, et le badge
   « Sponsorisé » ne peut pas servir à les repérer (eBay le place dans toutes les cartes pour piéger les robots).
   Le bot s'appuie donc sur l'ordre chronologique : une vraie nouveauté apparaît tout en haut. Une annonce inconnue
   placée sous au moins `sponsored_guard` (3) annonces déjà connues est ignorée.
6. **Mises en page eBay** : le bot reconnaît les trois mises en page actuelles d'eBay (`s-card`, `search-evo` en
   déploiement sur .co.uk et .com, et l'ancienne `s-item`). Si eBay renomme ses classes CSS, un mode de secours
   repère les annonces par la structure de la page. Il a été testé en renommant toutes les classes des pages de test.

**Intervalle** : 45 à 90 s est le bon compromis. eBay met environ une minute à indexer une nouvelle annonce, donc
descendre sous 30 s n'apporte rien et augmente le risque de blocage. Le bot espace automatiquement ses requêtes :
délai minimal par site, variation aléatoire de ±15 %, 3 requêtes simultanées au maximum. En cas d'erreur, il attend
de plus en plus longtemps avant de réessayer (jusqu'à 30 min si eBay le bloque).

### Si un pays affiche « BLOQUÉ »

eBay protège son site contre les robots (Akamai). Depuis une connexion internet classique (box), la lecture des
pages fonctionne normalement à un rythme raisonnable. En revanche, les IP de **datacenters, VPS et VPN** sont
souvent refusées (erreur 403). Dans ce cas :

- lance le bot depuis ta connexion personnelle, sans VPN ;
- augmente `interval_seconds` et réduis le nombre de pays ;
- ou passe sur **l'API officielle** (voir ci-dessous) : c'est la solution la plus fiable.

### API officielle eBay (optionnel, recommandé sur serveur)

1. Crée un compte gratuit sur [developer.ebay.com](https://developer.ebay.com/), puis va dans *Application Keys*
   et crée un keyset **Production**.
2. Copie l'**App ID** dans `client_id` et le **Cert ID** dans `client_secret`, section `[api]`.
3. Mets `backend = "api"`, puis lance `run.bat doctor`.

L'API donne la date exacte de mise en ligne de chaque annonce, ne se fait jamais bloquer et autorise 5 000 appels
par jour gratuitement. C'est assez pour environ 3 cibles toutes les 60 s, ou 6 cibles toutes les 2 min.

## Développement

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 146 tests, ~30 s
```

| Module | Rôle |
|---|---|
| `ebaywatch/parser.py` | analyse des pages eBay : mises en page `s-card`, `search-evo` et `s-item`, plus un mode de secours structurel indépendant des classes CSS |
| `ebaywatch/sources/` | backends `html` (pages eBay) et `api` (Browse API, OAuth avec jeton en cache) |
| `ebaywatch/engine.py` | planification, détection des nouveautés, déduplication, backoff |
| `ebaywatch/store.py` | SQLite (WAL) : annonces vues, baselines, historique |
| `ebaywatch/notifiers/` | Discord, Telegram, file d'envoi avec reprise automatique (gère les limites de débit 429) |
| `ebaywatch/tui/` | interface Textual |
| `tests/` | tests unitaires, intégration bout en bout sur un vrai serveur HTTP local (faux eBay + faux Discord/Telegram), test de charge, tests de l'interface pilotée au clavier |

> Utilise cet outil de manière raisonnable : les conditions d'utilisation d'eBay encadrent l'accès automatisé.
> L'API officielle est la voie prévue par eBay pour ce besoin.
