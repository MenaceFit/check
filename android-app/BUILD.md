# Quick Checkout — Build Instructions (Android)

## Prerequisites
- Android Studio (Hedgehog 2023.1.1+) **or** Android SDK command-line tools
- Java 17+ (bundled with Android Studio)
- Internet access (to download Gradle + dependencies on first build)

## Build with Android Studio (recommended — 2 clicks)

1. Open Android Studio → **File → Open** → select the `android-app/` folder
2. Wait for Gradle sync (first time ~2 min)
3. **Build → Build Bundle(s) / APK(s) → Build APK(s)**
4. APK is at `app/build/outputs/apk/debug/app-debug.apk`

## Build from command line

```bash
cd android-app
chmod +x gradlew

# Debug APK (no signing needed)
./gradlew assembleDebug

# APK path:
# app/build/outputs/apk/debug/app-debug.apk
```

## Install on device

```bash
# Via USB (ADB)
adb install app/build/outputs/apk/debug/app-debug.apk

# Or copy the APK to the device and open it (enable Unknown Sources in Settings)
```

## What the app does

- Opens **autocop.app** in a full-screen WebView
- Injects `autocop-detector.js` — adds ⚡ CHECKOUT buttons on each listing card
- When you tap ⚡ CHECKOUT, navigates to the Vinted item page
- Injects `vinted-checkout.js` — auto-clicks "Acheter"
- **Autobuy mode** (toggle in the app): also clicks "Continuer" (delivery) and "Payer" (payment)
- Uses your existing Vinted login session (cookies are shared in the WebView)

## First-time setup in the app

1. The app opens autocop.app — log in if you haven't already
2. Open any Vinted link once to log in to Vinted inside the WebView
3. Come back to autocop.app — ⚡ buttons appear on listing cards
4. Tap ⚡ CHECKOUT on any listing to start the checkout flow

## DuckDuckGo

DuckDuckGo on Android does not support extensions and does not expose a WebView
injection API — this APK replaces it entirely.
