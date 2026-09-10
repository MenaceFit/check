# Quick Checkout — Build Instructions (Android)

## Prérequis
- Android Studio (Hedgehog 2023.1.1+) **ou** Android SDK command-line tools
- Java 17+ (fourni avec Android Studio)
- Connexion Internet (pour télécharger Gradle + dépendances au premier build)

## Build avec Android Studio (recommandé — 2 clics)

1. Ouvrir Android Studio → **File → Open** → sélectionner le dossier `android-app/`
2. Attendre la sync Gradle (environ 2 min la première fois)
3. **Build → Build Bundle(s) / APK(s) → Build APK(s)**
4. L'APK est dans `app/build/outputs/apk/debug/app-debug.apk`

## Build en ligne de commande

```bash
cd android-app
chmod +x gradlew

# APK debug (pas besoin de signature)
./gradlew assembleDebug

# Chemin de l'APK :
# app/build/outputs/apk/debug/app-debug.apk
```

## Installer sur l'appareil

```bash
# Via USB (ADB)
adb install app/build/outputs/apk/debug/app-debug.apk

# Ou copier l'APK sur le téléphone et l'ouvrir
# (activer "Sources inconnues" dans les réglages Android)
```

## Ce que fait l'app

- Ouvre **autocop.app** dans un WebView plein écran
- Injecte `autocop-detector.js` — ajoute un bouton ⚡ CHECKOUT sur chaque carte du feed
- Quand vous tapez ⚡ CHECKOUT, navigue vers la page article Vinted
- Injecte `vinted-checkout.js` — clique automatiquement sur "Acheter"
- **Mode Autobuy** (réglable dans les paramètres) : clique aussi sur "Continuer" (livraison)
  puis sur "Payer" (paiement) — achat entièrement automatique

## Premier lancement

1. L'app s'ouvre sur autocop.app — les **réglages** s'affichent automatiquement
2. Configurer :
   - **Marché Vinted** : `🇫🇷 vinted.fr` (France) est sélectionné par défaut
   - **Autobuy** : activez si vous voulez l'achat entièrement automatique
   - **Token Vinted** : optionnel — votre Bearer token pour la vérification API
3. Appuyer sur **"Ouvrir Vinted pour se connecter"** si vous n'êtes pas encore connecté
4. Revenir sur autocop.app → les boutons ⚡ apparaissent sur les cartes
5. Taper ⚡ CHECKOUT sur un article pour lancer le checkout

## Paramètres (bouton ⚙️ en bas à droite)

| Paramètre | Description |
|-----------|-------------|
| Marché Vinted | Domaine Vinted selon votre pays (fr, be, es, de, it...) |
| Autobuy | Achat automatique complet sans confirmation manuelle |
| Token Vinted | Bearer token API (optionnel, pour vérification de dispo) |

## Obtenir votre token Vinted (optionnel)

Le token Bearer Vinted se trouve dans les requêtes réseau de l'app Vinted :
1. Sur un téléphone Android : activer le mode développeur + proxy Charles/mitmproxy
2. Chercher une requête vers `api.vinted.fr` — copier le header `Authorization: Bearer eyJ...`
3. Coller le token dans les réglages de l'app (sans le mot "Bearer")

## DuckDuckGo

DuckDuckGo sur Android ne supporte pas les extensions et n'expose pas d'API WebView —
cette APK le remplace complètement. Utilisez **Kiwi Browser** si vous préférez une
solution basée sur les extensions Chrome.
