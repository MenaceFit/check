package com.autocop.quickcheckout;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Build;
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

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * Quick Checkout for Autocop × Vinted — Android WebView App
 *
 * Architecture:
 *  - One full-screen WebView that loads autocop.app
 *  - After each page load, autocop-detector.js + autocop-injected.css are injected
 *  - A JavaScript bridge (CheckoutBridge) replaces chrome.runtime.sendMessage
 *  - When the user taps ⚡ CHECKOUT, the bridge navigates to the Vinted item page
 *  - vinted-checkout.js is then injected into the Vinted page to auto-click "Acheter"
 */
public class MainActivity extends Activity {

    private static final String TAG = "QC-Android";
    private static final String AUTOCOP_URL = "https://autocop.app";
    private static final String PREFS = "qc_prefs";

    private WebView webView;
    private ProgressBar progressBar;
    private SharedPreferences prefs;

    // Injected JS/CSS assets (loaded once)
    private String autocopDetectorJs;
    private String vintedCheckoutJs;
    private String autocopInjectedCss;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        // Full-screen, keeps screen on during checkout
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // Load asset files
        autocopDetectorJs  = loadAsset("autocop-detector.js");
        vintedCheckoutJs   = loadAsset("vinted-checkout.js");
        autocopInjectedCss = loadAsset("autocop-injected.css");

        // Layout
        RelativeLayout root = new RelativeLayout(this);
        root.setBackgroundColor(Color.parseColor("#0f1117"));

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setIndeterminate(false);
        progressBar.setVisibility(View.GONE);
        RelativeLayout.LayoutParams pbParams = new RelativeLayout.LayoutParams(
                RelativeLayout.LayoutParams.MATCH_PARENT, 6);
        pbParams.addRule(RelativeLayout.ALIGN_PARENT_TOP);
        root.addView(progressBar, pbParams);

        webView = new WebView(this);
        RelativeLayout.LayoutParams wvParams = new RelativeLayout.LayoutParams(
                RelativeLayout.LayoutParams.MATCH_PARENT,
                RelativeLayout.LayoutParams.MATCH_PARENT);
        wvParams.addRule(RelativeLayout.BELOW, progressBar.getId());
        root.addView(webView, wvParams);
        setContentView(root);

        // WebView settings
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUserAgentString(
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        );

        // Enable cookies (needed for Vinted session)
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);

        // JavaScript bridge — replaces chrome.runtime.sendMessage in the injected scripts
        CheckoutBridge bridge = new CheckoutBridge(this, webView, prefs,
                vintedCheckoutJs, autocopInjectedCss);
        webView.addJavascriptInterface(bridge, "__QCBridge");

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                progressBar.setProgress(newProgress);
                progressBar.setVisibility(newProgress < 100 ? View.VISIBLE : View.GONE);
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                Log.d(TAG, "Loading: " + url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                Log.d(TAG, "Loaded: " + url);
                injectIntoPage(url);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                // Stay within the WebView for both autocop.app and vinted.*
                String url = req.getUrl().toString();
                if (url.startsWith("https://autocop.app") ||
                    url.startsWith("https://www.autocop.app") ||
                    url.contains("vinted.")) {
                    return false; // let the WebView handle it
                }
                // External links: could open in browser, but for safety stay inside
                return false;
            }
        });

        webView.loadUrl(AUTOCOP_URL);
    }

    private void injectIntoPage(String url) {
        boolean isAutocop = url.contains("autocop.app");
        boolean isVinted  = url.contains("vinted.");

        if (isAutocop && autocopDetectorJs != null) {
            // Inject CSS first (via JS)
            if (autocopInjectedCss != null) {
                String escapedCss = autocopInjectedCss.replace("\\", "\\\\")
                        .replace("'", "\\'").replace("\n", "\\n").replace("\r", "");
                String cssJs = "(function(){" +
                        "if(document.getElementById('qc-style'))return;" +
                        "var s=document.createElement('style');" +
                        "s.id='qc-style';" +
                        "s.textContent='" + escapedCss + "';" +
                        "document.head.appendChild(s);" +
                        "})();";
                webView.evaluateJavascript(cssJs, null);
            }

            // Patch chrome.runtime.sendMessage to use our bridge
            String patch = "(function(){" +
                "if(window.__qcBridgePatched)return;" +
                "window.__qcBridgePatched=true;" +
                "window.chrome={runtime:{" +
                "  sendMessage:function(msg,cb){" +
                "    try{" +
                "      var r=__QCBridge.sendMessage(JSON.stringify(msg));" +
                "      if(cb)cb(r?JSON.parse(r):null);" +
                "      return Promise.resolve(r?JSON.parse(r):null);" +
                "    }catch(e){" +
                "      if(cb)cb(null);" +
                "      return Promise.reject(e);" +
                "    }" +
                "  }," +
                "  onMessage:{addListener:function(){}}" +
                "}," +
                "storage:{local:{" +
                "  get:function(k,cb){" +
                "    try{var r=JSON.parse(__QCBridge.storageGet(JSON.stringify(k)));if(cb)cb(r);}catch(e){if(cb)cb({});}" +
                "    return Promise.resolve({});" +
                "  }," +
                "  set:function(v,cb){__QCBridge.storageSet(JSON.stringify(v));if(cb)cb();}," +
                "  remove:function(k,cb){__QCBridge.storageRemove(JSON.stringify(k));if(cb)cb();}," +
                "  onChanged:{addListener:function(){}}" +
                "}}}" +
                "};})();";

            webView.evaluateJavascript(patch, null);
            webView.evaluateJavascript(autocopDetectorJs, null);
        }

        if (isVinted && vintedCheckoutJs != null) {
            // Patch chrome.storage for the Vinted checkout script
            String patch = "(function(){" +
                "if(window.__qcBridgePatched)return;" +
                "window.__qcBridgePatched=true;" +
                "window.chrome={" +
                "storage:{local:{" +
                "  get:function(k,cb){" +
                "    try{var r=JSON.parse(__QCBridge.storageGet(JSON.stringify(k)));if(cb)cb(r);}catch(e){if(cb)cb({});}" +
                "    return Promise.resolve({});" +
                "  }," +
                "  set:function(v,cb){__QCBridge.storageSet(JSON.stringify(v));if(cb)cb();}," +
                "  remove:function(k,cb){__QCBridge.storageRemove(JSON.stringify(k));if(cb)cb();}," +
                "  onChanged:{addListener:function(){}}" +
                "}}," +
                "runtime:{sendMessage:function(m,cb){if(cb)cb(null);return Promise.resolve(null);}}" +
                "};" +
                "})();";

            webView.evaluateJavascript(patch, null);
            webView.evaluateJavascript(vintedCheckoutJs, null);
        }
    }

    private String loadAsset(String name) {
        try (InputStream is = getAssets().open(name)) {
            byte[] buf = new byte[is.available()];
            is.read(buf);
            return new String(buf, StandardCharsets.UTF_8);
        } catch (IOException e) {
            Log.e(TAG, "Failed to load asset: " + name, e);
            return null;
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) webView.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) { webView.destroy(); webView = null; }
        super.onDestroy();
    }
}
