# 🎯 LBC Sniper — Guide d'installation

Ce guide se suit en une dizaine de minutes. Il est écrit pour **Windows** ; les commandes pour Mac/Linux sont indiquées à part.

---

## 1. Installer Python (une seule fois)

1. Téléchargez **Python 3.10 ou plus récent** : <https://www.python.org/downloads/>
2. Pendant l'installation, **cochez « Add python.exe to PATH »** (case en bas de la première fenêtre), puis *Install Now*.

---

## 2. Créer le bot Discord (5 minutes)

### 2.1 Créer l'application
1. Ouvrez <https://discord.com/developers/applications> et connectez-vous.
2. Cliquez **New Application**, donnez un nom (ex. *LBC Sniper*), acceptez et validez.

### 2.2 Récupérer le token
1. Dans le menu de gauche, ouvrez **Bot**.
2. Cliquez **Reset Token**, confirmez, puis **Copy**.
3. Gardez ce token de côté pour l'étape 4. **Ne le partagez jamais** : il donne le contrôle total du bot. S'il fuite, refaites *Reset Token*.

> Aucun « Privileged Gateway Intent » n'est nécessaire : laissez-les tous désactivés.

### 2.3 Inviter le bot sur votre serveur
1. Dans le menu de gauche, ouvrez **OAuth2** puis **URL Generator**.
2. Dans **Scopes**, cochez **`bot`** et **`applications.commands`**.
3. Dans **Bot Permissions**, cochez **View Channels**, **Send Messages** et **Embed Links**.
4. Copiez l'URL générée en bas de page, ouvrez-la dans le navigateur, choisissez votre serveur et validez.

> Raccourci : dans **General Information**, copiez l'*Application ID* et remplacez `VOTRE_ID` dans cette URL :
> `https://discord.com/oauth2/authorize?client_id=VOTRE_ID&permissions=19456&scope=bot%20applications.commands`

### 2.4 Récupérer les identifiants Discord (mode développeur)
1. Dans Discord, ouvrez **Paramètres utilisateur → Avancés** et activez **Mode développeur**.
2. Faites un clic droit sur **votre serveur**, puis **Copier l'identifiant du serveur**. Ce sera `DISCORD_GUILD_ID`.
3. Faites un clic droit sur **le salon** qui recevra les alertes, puis **Copier l'identifiant du salon**. Il vous servira dans le dashboard. Vous pourrez aussi le choisir dans une liste déroulante une fois le bot connecté.

---

## 3. Installer LBC Sniper

1. Dézippez `lbc-sniper.zip` où vous voulez (ex. `C:\LBC-Sniper`).
2. Double-cliquez sur **`install.bat`**. Cela crée un environnement Python isolé et installe les dépendances, en 1 à 2 minutes.

*Mac / Linux :*
```bash
cd lbc-sniper
./install.sh
```

---

## 4. Configurer le fichier `.env`

L'installation a créé un fichier **`.env`**. Ouvrez-le avec le Bloc-notes et remplissez au minimum :

```ini
DISCORD_TOKEN=collez_ici_le_token_du_bot
DISCORD_GUILD_ID=collez_ici_l_id_de_votre_serveur
```

Les autres réglages sont optionnels :

| Variable | Défaut | Rôle |
|---|---|---|
| `DASHBOARD_PORT` | `8080` | Port du dashboard |
| `DASHBOARD_HOST` | `127.0.0.1` | `127.0.0.1` = dashboard accessible uniquement depuis ce PC |
| `DASHBOARD_PASSWORD` | *(vide)* | Mot de passe du dashboard (**obligatoire** si vous l'ouvrez au réseau) |
| `LBC_MIN_INTERVAL` | `10` | Intervalle minimum (s) entre deux vérifications d'une recherche |
| `LBC_MAX_REQUESTS_PER_MINUTE` | `30` | Plafond global de requêtes vers Leboncoin |

---

## 5. Lancer

Double-cliquez sur **`start.bat`**. Une fenêtre noire s'ouvre (laissez-la ouverte : c'est le bot qui tourne), puis le dashboard s'ouvre automatiquement sur **<http://localhost:8080>**.

*Mac / Linux :* `./start.sh`, puis ouvrez <http://localhost:8080>.

Dans le dashboard, en bas à gauche, **« Bot : LBC Sniper#1234 »** doit passer au vert après quelques secondes.

---

## 6. Créer votre première alerte

1. Sur **leboncoin.fr**, faites votre recherche normalement avec **tous vos filtres** (catégorie, prix, lieu, livraison, état…).
2. **Copiez l'URL** de la page de résultats.
3. Dans le dashboard, cliquez **＋ Nouvelle recherche**, collez l'URL dans le cadre orange, puis cliquez **Importer**. Tous les filtres sont repris automatiquement, y compris les filtres propres à une catégorie (kilométrage, année, état…), qui deviennent des **champs personnalisés**.
4. Choisissez le **salon Discord**, réglez l'**intervalle**, et ajoutez si besoin :
   - des **mots exclus** (ex. `hs, pour pièces, échange, cassé`) ;
   - des **mots obligatoires** ;
   - un **âge maximum**, pour ignorer les vieilles annonces « remontées » ;
   - une **mention**, par exemple `@everyone` ou `<@&ID_DU_ROLE>`, pour recevoir une notification push ;
   - les **champs à afficher** dans le message Discord.
5. Cliquez **👀 Prévisualiser** pour voir ce que la recherche ramène, puis **💾 Enregistrer**.
6. Cliquez **📨 Test** pour recevoir un message d'exemple dans Discord.

> Au premier passage, les annonces **déjà en ligne sont mémorisées sans alerte** pour ne pas vous inonder. Ensuite, chaque nouvelle annonce arrive dans Discord dès qu'elle est détectée.
> Si vous voulez aussi recevoir les annonces déjà en ligne, cochez *« Envoyer aussi les annonces déjà en ligne au 1er passage »*.

Vous pouvez aussi tout faire **depuis Discord** :

| Commande | Effet |
|---|---|
| `/lbc ajouter url:<lien leboncoin>` | crée une alerte dans le salon courant |
| `/lbc status` | état de toutes les recherches |
| `/lbc tester` | les 5 annonces les plus récentes d'une recherche |
| `/lbc pause` et `/lbc reprendre` | met en pause ou relance une recherche |
| `/lbc toutpause` | coupe ou relance toute la surveillance |

---

## 7. Vitesse : ce qu'il faut savoir

- **Délai d'une alerte ≈ intervalle de vérification + temps de modération Leboncoin.** Une annonce n'apparaît dans les résultats qu'après la validation de Leboncoin, qui prend souvent quelques minutes. Le bot ne peut pas voir une annonce avant qu'elle soit publique. Le délai réellement mesuré s'affiche dans chaque alerte (**⚡ Détectée … après publication**) et dans le dashboard.
- Toutes les recherches tournent **en parallèle** sur une connexion persistante, et les alertes partent dès qu'une nouvelle annonce est vue.
- **Le budget de requêtes est partagé** : avec le plafond de 30 requêtes/min, vous pouvez par exemple faire tourner 5 recherches toutes les 10 s, ou 15 recherches toutes les 30 s.
- **Ne descendez pas trop bas.** Leboncoin est protégé contre les robots : en cas de blocage (erreur 403 ou captcha), le bot **ralentit tout seul** (attente qui double à chaque échec), puis repart normalement. Si les blocages sont fréquents, augmentez l'intervalle.
- Faites tourner le bot **depuis votre connexion internet personnelle**. Les serveurs loués (VPS, cloud) sont souvent bloqués d'office par Leboncoin.
- Le PC doit rester allumé avec la fenêtre ouverte. Pour du 24h/24, utilisez un petit serveur à la maison (Raspberry Pi, NAS) avec Docker, voir plus bas.

---

## 8. Alternative sans bot : webhook Discord

Si vous ne voulez pas créer de bot, ouvrez les **Paramètres du salon → Intégrations → Webhooks → Nouveau webhook → Copier l'URL**. Collez cette URL dans le champ **Webhook** d'une recherche, ou dans les paramètres par défaut. Les alertes fonctionnent pareil, mais sans les commandes `/lbc` ni le bouton « Voir l'annonce ».

---

## 9. Docker (optionnel, pour un serveur 24h/24)

```bash
cp .env.example .env    # remplissez DISCORD_TOKEN
docker compose up -d --build
```
Le dashboard est sur <http://localhost:8080> et les données restent dans `./data`.

---

## 10. Dépannage

| Problème | Solution |
|---|---|
| `Python est introuvable` | Réinstallez Python en cochant **Add python.exe to PATH**. |
| Bot « déconnecté » dans le dashboard | Token incorrect : refaites *Reset Token* et recollez-le dans `.env`, puis relancez `start.bat`. |
| Les commandes `/lbc` n'apparaissent pas | Renseignez `DISCORD_GUILD_ID` (apparition immédiate) ; sinon, attendez jusqu'à 1 h. Vérifiez que le bot a été invité avec le scope `applications.commands`. |
| « Missing Access » ou rien n'arrive dans le salon | Le bot doit pouvoir **voir le salon, y écrire et intégrer des liens**. Vérifiez les permissions du salon. |
| `Leboncoin a refusé la requête (HTTP 403)` | Protection anti-robot : le bot ralentit automatiquement. Augmentez l'intervalle ou baissez `LBC_MAX_REQUESTS_PER_MINUTE`. Dans **Paramètres**, essayez la source « Page web uniquement ». |
| Le port 8080 est déjà utilisé | Changez `DASHBOARD_PORT` dans `.env`. |
| Repartir de zéro | Fermez le bot et supprimez le dossier `data/`. |

Pour **sauvegarder vos recherches**, allez dans **Paramètres → Exporter**. Le fichier JSON se réimporte avec **Importer**.

---

⚠️ *Usage personnel uniquement. Les conditions d'utilisation de Leboncoin encadrent l'accès automatisé à leur site : gardez des intervalles raisonnables. Vous utilisez cet outil sous votre propre responsabilité.*
