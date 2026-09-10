package com.autocop.quickcheckout;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.RelativeLayout;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * Quick Checkout — Android WebView App
 *
 * Loads autocop.app in a full-screen WebView and injects the Quick Checkout
 * content scripts (autocop-detector.js + vinted-checkout.js) after each page
 * load.  A JavaScript bridge (__QCBridge) replaces chrome.runtime / chrome.storage
 * so the scripts work without the Chrome extension API.
 *
 * User flow:
 *  1. App opens → autocop.app (must be logged in)
 *  2. autocop-detector.js injects ⚡ CHECKOUT buttons on each listing card
 *  3. Tap ⚡ → bridge stores pending checkout, navigates to vinted.fr/items/{id}
 *  4. vinted-checkout.js reads the pending checkout, clicks "Acheter"
 *  5. [autobuy] clicks "Continuer" then "Payer" automatically
 *
 * Settings (⚙️ button):  domain · autobuy · Bearer token (for API pre-check)
 */
public class MainActivity extends AppCompatActivity {

    static final String TAG    = "QC-Android";
    static final String PREFS  = "qc_prefs";
    static final String KEY_FIRST_LAUNCH = "first_launch";

    static final String AUTOCOP_URL = "https://autocop.app";

    WebView webView;
    SharedPreferences prefs;

    private ProgressBar progressBar;
    private String autocopDetectorJs;
    private String vintedCheckoutJs;
    private String autocopInjectedCss;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        // Keep screen on while app is in foreground (useful during checkout)
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // Load bundled scripts/styles from assets/
        autocopDetectorJs  = loadAsset("autocop-detector.js");
        vintedCheckoutJs   = loadAsset("vinted-checkout.js");
        autocopInjectedCss = loadAsset("autocop-injected.css");

        // ── Layout ────────────────────────────────────────────────────────────
        RelativeLayout root = new RelativeLayout(this);
        root.setBackgroundColor(Color.parseColor("#0f1117"));

        // Thin progress bar at the top
        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setVisibility(View.GONE);
        progressBar.setId(View.generateViewId());
        RelativeLayout.LayoutParams pbp =
            new RelativeLayout.LayoutParams(RelativeLayout.LayoutParams.MATCH_PARENT, 6);
        pbp.addRule(RelativeLayout.ALIGN_PARENT_TOP);
        root.addView(progressBar, pbp);

        // Full-screen WebView below the progress bar
        webView = new WebView(this);
        webView.setId(View.generateViewId());
        RelativeLayout.LayoutParams wvp = new RelativeLayout.LayoutParams(
            RelativeLayout.LayoutParams.MATCH_PARENT,
            RelativeLayout.LayoutParams.MATCH_PARENT);
        wvp.addRule(RelativeLayout.BELOW, progressBar.getId());
        root.addView(webView, wvp);

        // ⚙️ settings button — bottom-right floating
        int fabSizePx = dp(52);
        int fabMarginPx = dp(16);
        TextView fab = new TextView(this);
        fab.setText("⚙");
        fab.setTextSize(22);
        fab.setTextColor(Color.WHITE);
        fab.setGravity(android.view.Gravity.CENTER);
        fab.setElevation(dp(4));
        GradientDrawable fabBg = new GradientDrawable();
        fabBg.setShape(GradientDrawable.OVAL);
        fabBg.setColor(Color.parseColor("#6C63FF"));
        fab.setBackground(fabBg);
        fab.setAlpha(0.90f);
        RelativeLayout.LayoutParams fabp =
            new RelativeLayout.LayoutParams(fabSizePx, fabSizePx);
        fabp.addRule(RelativeLayout.ALIGN_PARENT_BOTTOM);
        fabp.addRule(RelativeLayout.ALIGN_PARENT_END);
        fabp.setMargins(0, 0, fabMarginPx, fabMarginPx);
        root.addView(fab, fabp);

        fab.setOnClickListener(v -> SettingsDialog.show(this));

        setContentView(root);

        // ── WebView configuration ─────────────────────────────────────────────
        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setLoadWithOverviewMode(true);
        ws.setUseWideViewPort(true);
        ws.setSupportZoom(false);
        ws.setBuiltInZoomControls(false);
        ws.setDisplayZoomControls(false);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);
        // Mimic a real Android Chrome browser so Vinted renders correctly
        ws.setUserAgentString(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
        );

        // Persist cookies across sessions (required for Vinted login)
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        // ── JavaScript bridge ─────────────────────────────────────────────────
        CheckoutBridge bridge = new CheckoutBridge(this);
        webView.addJavascriptInterface(bridge, "__QCBridge");

        // ── WebChromeClient (progress bar) ────────────────────────────────────
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int p) {
                progressBar.setProgress(p);
                progressBar.setVisibility(p < 100 ? View.VISIBLE : View.GONE);
            }
        });

        // ── WebViewClient (injection) ─────────────────────────────────────────
        webView.setWebViewClient(new WebViewClient() {
            @Override public void onPageStarted(WebView v, String url, Bitmap fav) {
                Log.d(TAG, "Loading: " + url);
            }

            @Override public void onPageFinished(WebView v, String url) {
                Log.d(TAG, "Loaded: " + url);
                injectIntoPage(url);
            }

            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                // Keep everything (autocop + Vinted) inside the WebView
                return false;
            }
        });

        // Show settings on first launch so the user can configure the domain
        boolean firstLaunch = prefs.getBoolean(KEY_FIRST_LAUNCH, true);
        if (firstLaunch) {
            prefs.edit().putBoolean(KEY_FIRST_LAUNCH, false).apply();
            webView.postDelayed(() -> SettingsDialog.show(this), 1200);
        }

        webView.loadUrl(AUTOCOP_URL);
    }

    // ── Script injection ──────────────────────────────────────────────────────

    void injectIntoPage(String url) {
        if (url == null || url.startsWith("about:") || url.startsWith("data:")) return;

        boolean isAutocop = url.contains("autocop.app");
        boolean isVinted  = !isAutocop && url.contains("vinted.");

        if (isAutocop && autocopDetectorJs != null) {
            injectCss(autocopInjectedCss);
            webView.evaluateJavascript(buildBridgePatch(true), null);
            webView.evaluateJavascript(autocopDetectorJs, null);
        }

        if (isVinted && vintedCheckoutJs != null) {
            webView.evaluateJavascript(buildBridgePatch(false), null);
            webView.evaluateJavascript(vintedCheckoutJs, null);
        }
    }

    private void injectCss(String css) {
        if (css == null) return;
        String escaped = css
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "");
        webView.evaluateJavascript(
            "(function(){" +
            "  if(document.getElementById('qc-style'))return;" +
            "  var s=document.createElement('style');" +
            "  s.id='qc-style';" +
            "  s.textContent='" + escaped + "';" +
            "  (document.head||document.documentElement).appendChild(s);" +
            "})();", null);
    }

    /**
     * Builds the window.chrome polyfill that replaces chrome.runtime + chrome.storage.local
     * with calls to __QCBridge (the Java JavascriptInterface).
     *
     * CRITICAL FIX: storage.local.get must return Promise.resolve(r) with the ACTUAL
     * data, not Promise.resolve({}).  vinted-checkout.js uses `await chrome.storage.local.get()`
     * and relies on the resolved value.
     *
     * @param withRuntime true on autocop.app (needs sendMessage); false on Vinted (no-op runtime)
     */
    private String buildBridgePatch(boolean withRuntime) {
        // Storage polyfill — all three methods return real Promises
        String storage =
            "local:{" +
            "  get:function(k,cb){" +
            "    var r={};" +
            "    try{r=JSON.parse(__QCBridge.storageGet(JSON.stringify(k)));}catch(e){}" +
            "    if(cb)cb(r);" +
            "    return Promise.resolve(r);" +
            "  }," +
            "  set:function(v,cb){" +
            "    try{__QCBridge.storageSet(JSON.stringify(v));}catch(e){}" +
            "    if(cb)cb();" +
            "    return Promise.resolve();" +
            "  }," +
            "  remove:function(k,cb){" +
            "    try{__QCBridge.storageRemove(JSON.stringify(k));}catch(e){}" +
            "    if(cb)cb();" +
            "    return Promise.resolve();" +
            "  }," +
            "  onChanged:{addListener:function(){}}" +
            "}";

        // runtime.sendMessage is only wired up on autocop.app; on Vinted it's a no-op
        String runtime = withRuntime
            ? "sendMessage:function(msg,cb){" +
              "  var parsed=null;" +
              "  try{var r=__QCBridge.sendMessage(JSON.stringify(msg));parsed=r?JSON.parse(r):null;}catch(e){}" +
              "  if(cb)cb(parsed);" +
              "  return parsed?Promise.resolve(parsed):Promise.reject(new Error('bridge error'));" +
              "}," +
              "onMessage:{addListener:function(){}}"
            : "sendMessage:function(m,cb){if(cb)cb(null);return Promise.resolve(null);}," +
              "onMessage:{addListener:function(){}}";

        return "(function(){" +
            "if(window.__qcBridgePatched)return;" +
            "window.__qcBridgePatched=true;" +
            "window.chrome={runtime:{" + runtime + "},storage:{" + storage + "}};" +
            "})();";
    }

    // ── Asset loading ─────────────────────────────────────────────────────────

    String loadAsset(String name) {
        try (InputStream is = getAssets().open(name)) {
            byte[] buf = new byte[is.available()];
            int n = is.read(buf);
            return new String(buf, 0, n, StandardCharsets.UTF_8);
        } catch (IOException e) {
            Log.e(TAG, "Failed to load asset: " + name, e);
            return null;
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    int dp(int dp) {
        return Math.round(dp * getResources().getDisplayMetrics().density);
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onPause() {
        super.onPause();
        if (webView != null) webView.onPause();
        CookieManager.getInstance().flush();
    }

    @Override protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override protected void onDestroy() {
        if (webView != null) { webView.destroy(); webView = null; }
        super.onDestroy();
    }
}
