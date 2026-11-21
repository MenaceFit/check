# 🎯 LBC Sniper

Alertes **Leboncoin en temps réel sur Discord**, avec un **dashboard web** pour tout configurer.

➡️ **Installation pas à pas : [INSTALLATION.md](INSTALLATION.md)**

## Fonctionnalités

- **Surveillance en continu** : toutes les recherches tournent en parallèle, chacune avec son propre intervalle. L'appli utilise l'API JSON de Leboncoin, et la page web en secours.
- **Alertes Discord riches** : prix, lieu, heure de publication, délai de détection, vendeur, livraison, caractéristiques, photo et bouton « Voir l'annonce ». Les mentions `@everyone` ou de rôle sont possibles.
- **Bot Discord** avec commandes `/lbc` (`ajouter`, `status`, `tester`, `pause`, `reprendre`, `toutpause`), ou un simple **webhook** si vous préférez.
- **Dashboard complet** :
  - import d'une recherche en collant son URL leboncoin.fr ;
  - **champs personnalisés** : n'importe quel filtre Leboncoin (kilométrage, année, état, marque…) ;
  - localisations multiples (ville + rayon, département, région) ;
  - filtres locaux : mots exclus, mots obligatoires, âge maximum ;
  - choix des champs affichés dans Discord, couleur, mention ;
  - prévisualisation des résultats et message test ;
  - flux d'annonces en direct, statistiques (délai moyen, requêtes/min…), journal ;
  - pause globale, export et import des recherches, mot de passe optionnel.
- **Protection anti-blocage** : plafond global de requêtes par minute, attente exponentielle en cas de refus (403, captcha), alerte Discord si une recherche échoue plusieurs fois.
- Annonces déjà vues mémorisées dans SQLite : **aucun doublon**, même après redémarrage.

## Démarrage rapide

```bash
# Windows : install.bat puis start.bat
./install.sh        # Mac / Linux
nano .env           # DISCORD_TOKEN=...
./start.sh          # puis http://localhost:8080
```

## Structure

```
lbcsniper/
  __main__.py      point d'entrée (dashboard + bot + moteur dans un seul process)
  engine.py        moteur de surveillance (1 tâche asyncio par recherche)
  lbc/client.py    client HTTP/2 Leboncoin (API + page web, limiteur, détection de blocage)
  lbc/query.py     URL leboncoin.fr ⇄ configuration ⇄ requête API
  lbc/parse.py     normalisation des annonces
  filters.py       filtres locaux
  notifier.py      messages Discord (bot ou webhook)
  bot.py           bot Discord + commandes /lbc
  db.py            stockage SQLite
  web/             dashboard (FastAPI + HTML/JS sans build)
tests/             tests automatisés (pytest)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
