# eBay Watcher

Surveille eBay en continu et t'alerte dès qu'une **nouvelle annonce** correspondant à tes mots-clés est publiée,
sur **plusieurs pays à la fois** (France, Royaume-Uni, Allemagne, Italie, Espagne, États-Unis, Belgique, Pays-Bas,
Autriche, Suisse, Irlande, Pologne, Canada, Australie).

- Interface terminal complète : flux des annonces en direct, gestion des recherches, paramètres
- Fichier `config.toml` lisible et modifiable à la main (mots-clés, pays, prix, mots exclus…)
- Alertes **Discord** et **Telegram** (avec photo, prix, frais de port et lien), plus un bip sonore
- **API officielle eBay** (gratuite, jamais bloquée) avec assistant de configuration, ou lecture des pages sans clé
- Pas de doublons : une annonce visible sur eBay FR et DE ne déclenche qu'une seule alerte
- Mémoire persistante (SQLite) : un redémarrage ne renvoie pas les anciennes annonces

## Démarrage rapide

Prérequis : **Python 3.11 ou plus récent** ([python.org](https://www.python.org/downloads/), coche « Add to PATH » sous Windows).

| Système | Lancer |
|---|---|
| Windows | double-clic sur `run.bat` |
| macOS / Linux | `./run.sh` |

Le premier lancement installe tout automatiquement dans `.venv/` et crée `config.toml`.
**Commence par lancer le diagnostic**, qui teste en 10 secondes la connexion à chaque pays.
S'il affiche **BLOQUÉ**, configure l'API officielle (voir plus bas, 5 minutes) : `run.bat setup-api`.

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
| `P` | paramètres : intervalle, Discord, Telegram… |
| `K` | clés de l'API officielle eBay (assistant + vérification) |
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

### Si `doctor` affiche « BLOQUÉ (403) » : utilise l'API officielle (5 minutes)

eBay protège ses pages avec un anti-robot (Akamai). Il bloque de plus en plus les programmes qui lisent ses pages,
y compris depuis une connexion internet classique. Le bot ne contourne pas cette protection. La solution fiable
est **l'API officielle d'eBay** : gratuite, prévue pour ça, et jamais bloquée.

1. Va sur [developer.ebay.com](https://developer.ebay.com/) → **Join**. Tu peux te connecter avec ton compte eBay.
   La validation du compte développeur peut prendre un peu de temps (jusqu'à 1 jour ouvré).
2. Menu **Application Keys** → donne un nom à l'application (ex. `ebaywatch`) → **Create a keyset** dans la
   colonne **Production** (pas Sandbox).
3. Si le keyset Production est marqué *disabled* : **Alerts & Notifications** → Production →
   **Marketplace Account Deletion** → coche **Exempted from Marketplace Account Deletion** → raison
   **I do not persist eBay data** → Submit. Le bot ne stocke aucune donnée de compte eBay.
4. Lance `run.bat setup-api` (ou touche **K** dans l'interface) et colle l'**App ID** (Client ID, contient
   `-PRD-`) puis le **Cert ID** (Client Secret).

Le bot vérifie aussitôt les clés auprès d'eBay en lançant une vraie recherche, et ne les enregistre que si elles
fonctionnent. Avec `backend = "auto"` (le réglage par défaut), il utilise l'API dès que les clés sont présentes.

**Quota** : l'API autorise 5 000 appels par jour. Chaque recherche × pays coûte un appel par vérification, et le bot
allonge automatiquement l'intervalle pour ne jamais dépasser le quota :

| Recherches × pays | Intervalle minimal |
|---|---|
| 1 | 19 s |
| 3 | 55 s |
| 6 | 110 s |
| 9 | 164 s |

Pour plus de cibles en temps réel, eBay accorde des quotas plus élevés via son « Application Growth Check ».

## Développement

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 160 tests, ~40 s
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
