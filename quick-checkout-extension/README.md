# ⚡ Quick Checkout — Extension Chrome pour Autocop × Vinted

Extension Chrome Manifest V3 qui transforme chaque annonce du feed Autocop en un checkout Vinted ultra-rapide.

---

## Fonctionnement

```
AUTOCOP détecte l'annonce
        ↓
  Feed Autocop affiché
        ↓
  [⚡ CHECKOUT] — bouton injecté par l'extension
        ↓
  Vérification API Vinted (article dispo ? prix inchangé ?)
        ↓
  Ouverture directe page Vinted + clic auto sur "Acheter"
        ↓
  Checkout Vinted — livraison + paiement déjà configurés
        ↓
  Confirmation humaine
```

---

## Installation

### 1. Pré-requis
- Google Chrome ou Chromium
- Compte Vinted connecté dans Chrome
- Autocop ouvert dans un onglet Chrome

### 2. Charger l'extension

1. Ouvrez `chrome://extensions/`
2. Activez le **Mode développeur** (coin supérieur droit)
3. Cliquez **Charger l'extension non empaquetée**
4. Sélectionnez le dossier `quick-checkout-extension/`
5. L'icône ⚡ apparaît dans la barre d'outils

### 3. Configuration initiale

1. Cliquez l'icône ⚡ pour ouvrir le popup
2. Sélectionnez votre **domaine Vinted** (ex: `vinted.fr`)
3. Cliquez **↺ Vérifier session** pour confirmer que Vinted est connecté
4. Ouvrez Autocop — les boutons `[⚡ CHECKOUT]` apparaissent sur chaque annonce

---

## Utilisation

1. Autocop détecte une nouvelle annonce → le bouton `⚡ CHECKOUT` apparaît sur la carte
2. Cliquez le bouton
3. L'extension :
   - Vérifie que l'article est toujours disponible (API Vinted)
   - Vérifie que le prix n'a pas changé
   - Ouvre la page Vinted et clique automatiquement sur "Acheter"
4. Le checkout Vinted s'ouvre avec vos informations déjà configurées
5. Confirmez le paiement

---

## Architecture technique

```
quick-checkout-extension/
├── manifest.json                  # Manifest V3
├── background/
│   └── service-worker.js          # SW — orchestration, API calls, métriques
├── content-scripts/
│   ├── autocop-detector.js        # Injection boutons sur autocop.app
│   └── vinted-checkout.js         # Auto-clic "Acheter" sur Vinted
├── popup/
│   ├── popup.html / .css / .js    # Interface utilisateur
├── utils/
│   ├── vinted-api.js              # Extraction ID, vérification article
│   ├── session-manager.js         # Gestion session (cookies + token chiffré)
│   └── logger.js                  # Logger sécurisé (masque tokens/cookies)
├── styles/
│   ├── autocop-injected.css       # Style bouton ⚡
│   └── vinted-overlay.css         # Overlay statut sur Vinted
├── config/
│   └── constants.js               # Constantes globales
├── icons/
│   └── icon{16,48,128}.png
└── tests/
    └── test-suite.js              # 42 tests unitaires
```

### Détection des annonces Autocop

L'extension utilise **trois couches** en parallèle :

1. **Network Interception** — surcharge `window.fetch` et `XMLHttpRequest` pour capturer les réponses JSON contenant les annonces avant même que le DOM ne soit construit → données les plus riches
2. **MutationObserver** — détecte l'apparition de nouvelles cartes dans le DOM (feed temps réel)
3. **Scan initial** — parcourt le DOM existant au chargement de la page

Cette approche multi-couches fonctionne indépendamment du framework frontend utilisé par Autocop (React, Vue, SPA ou HTML classique).

### Checkout Vinted

Vinted ne fournit pas d'endpoint public `/checkout?item_id=xxx`. Le flow le plus rapide techniquement est :

```
1. Ouvrir https://www.vinted.fr/items/{id}
2. Attendre le bouton "Acheter" (MutationObserver — compatible SPA)
3. Cliquer automatiquement
4. Vinted redirige vers son checkout
```

Le content script `vinted-checkout.js` gère ce clic automatique via une liste de sélecteurs CSS priorisés et un fallback par texte du bouton.

---

## Sécurité

- **Aucune donnée bancaire stockée** — l'extension utilise uniquement le paiement déjà enregistré sur votre compte Vinted
- **Cookies jamais transmis à un tiers** — seul Chrome y accède, en lecture seule
- **Token V-Tools chiffré** (AES-GCM, Web Crypto API) — la clé est dérivée de l'ID de l'extension, unique par installation
- **Logs masqués** — les tokens sont tronqués (`vtools_abc123****92af`)
- **Permissions minimales** — `cookies`, `tabs`, `storage`, `scripting`, `alarms`
- **CSP stricte** — aucun script externe, aucune connexion non déclarée

### Token V-Tools (optionnel)

Le token disponible sur https://login.v-tools.com est **optionnel**. L'extension fonctionne en priorité avec la session Vinted déjà présente dans Chrome.

Si vous souhaitez l'utiliser :
1. Obtenez votre token sur login.v-tools.com
2. Collez-le dans le popup → section "🔑 Token V-Tools"
3. Il est chiffré immédiatement et le token brut n'est jamais stocké en clair

---

## Mode Debug

1. Cliquez **🔍 Debug** dans le popup
2. Les logs s'affichent en temps réel
3. Les informations sensibles sont automatiquement masquées
4. Cliquez **Effacer** pour vider les logs

Logs disponibles :
- Annonce détectée (ID, titre, prix)
- Vérification API (statut, latence)
- Ouverture checkout (timestamps)
- Erreurs détaillées

---

## Métriques de latence

| Point | Description |
|-------|-------------|
| T0 | Clic sur ⚡ CHECKOUT |
| T1 | ID de l'annonce récupéré |
| T2 | Vérification API Vinted terminée |
| T3 | Onglet Vinted ouvert |
| T4 | Bouton "Acheter" cliqué |

Le popup affiche la **latence moyenne** sur les 20 derniers checkouts.

---

## Gestion des erreurs

| Erreur | Message affiché |
|--------|----------------|
| Article vendu | ❌ Article déjà vendu ou introuvable |
| Session expirée | 🔐 Session Vinted expirée — reconnectez-vous |
| Prix modifié | ⚠️ Prix modifié — vérification requise |
| Article indisponible | ❌ Article indisponible |
| Checkout impossible | ⚠️ Checkout indisponible pour cette annonce |
| Livraison indisponible | 📦 Aucun mode de livraison compatible |
| Authentification 3DS | 🔐 Confirmation bancaire requise |

---

## Adaptation si Vinted change son interface

Si Vinted modifie les noms de classes ou les sélecteurs du bouton "Acheter" :

1. Ouvrez `content-scripts/vinted-checkout.js`
2. Mettez à jour le tableau `BUY_BUTTON_SELECTORS` (ligne ~15) avec le nouveau sélecteur
3. Rechargez l'extension dans `chrome://extensions/`

Aucune recompilation nécessaire.

---

## Tests

```bash
node tests/test-suite.js
```

42 tests couvrant :
- Extraction d'ID depuis les URLs Vinted
- Validation du prix
- Masquage des tokens
- Statut des articles
- Messages d'erreur
- Tracking de latence
- Protection double-clic
- Sécurité des logs

---

## Limitations connues

1. **Bouton "Acheter" Vinted** — les sélecteurs CSS sont heuristiques. Si Vinted déploie une mise à jour majeure, il faudra mettre à jour `BUY_BUTTON_SELECTORS`.
2. **SPA Vinted** — le content script attend le rendu dynamique via MutationObserver, ce qui ajoute ~100-500ms selon la vitesse de la connexion.
3. **3-D Secure** — si votre banque demande une confirmation, l'extension laisse Vinted gérer cela normalement.
4. **Autocop DOM** — les sélecteurs de cartes sont génériques. Si Autocop change de structure, il peut être nécessaire de mettre à jour `CARD_SELECTORS` dans `autocop-detector.js`.
