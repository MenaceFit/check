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
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.RelativeLayout;
import android.widget.TextView;

import android.app.Activity;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {

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

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        autocopDetectorJs  = loadAsset("autocop-detector.js");
        vintedCheckoutJs   = loadAsset("vinted-checkout.js");
        autocopInjectedCss = loadAsset("autocop-injected.css");

        RelativeLayout root = new RelativeLayout(this);
        root.setBackgroundColor(Color.parseColor("#0f1117"));

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setVisibility(View.GONE);
        progressBar.setId(View.generateViewId());
        RelativeLayout.LayoutParams pbp =
            new RelativeLayout.LayoutParams(RelativeLayout.LayoutParams.MATCH_PARENT, 6);
        pbp.addRule(RelativeLayout.ALIGN_PARENT_TOP);
        root.addView(progressBar, pbp);

        webView = new WebView(this);
        webView.setId(View.generateViewId());
        RelativeLayout.LayoutParams wvp = new RelativeLayout.LayoutParams(
            RelativeLayout.LayoutParams.MATCH_PARENT,
            RelativeLayout.LayoutParams.MATCH_PARENT);
        wvp.addRule(RelativeLayout.BELOW, progressBar.getId());
        root.addView(webView, wvp);

        int fabSizePx = dp(52);
        int fabMarginPx = dp(16);
        final TextView fab = new TextView(this);
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

        fab.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                SettingsDialog.show(MainActivity.this);
            }
        });

        setContentView(root);

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
        ws.setUserAgentString(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
        );

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        CheckoutBridge bridge = new CheckoutBridge(this);
        webView.addJavascriptInterface(bridge, "__QCBridge");

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int p) {
                progressBar.setProgress(p);
                progressBar.setVisibility(p < 100 ? View.VISIBLE : View.GONE);
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView v, String url, Bitmap fav) {
                Log.d(TAG, "Loading: " + url);
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                Log.d(TAG, "Loaded: " + url);
                injectIntoPage(url);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                return false;
            }
        });

        boolean firstLaunch = prefs.getBoolean(KEY_FIRST_LAUNCH, true);
        if (firstLaunch) {
            prefs.edit().putBoolean(KEY_FIRST_LAUNCH, false).apply();
            webView.postDelayed(new Runnable() {
                @Override
                public void run() {
                    SettingsDialog.show(MainActivity.this);
                }
            }, 1200);
        }

        webView.loadUrl(AUTOCOP_URL);
    }

    void injectIntoPage(String url) {
        if (url == null || url.startsWith("about:") || url.startsWith("data:")) return;

        boolean isAutocop = url.contains("autocop.app");
        boolean isVinted  = !isAutocop && url.contains("vinted.");

        if (isVinted) {
            extractAndSaveVintedToken(url);
        }

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

    void clearVintedCookies() {
        try {
            CookieManager cm = CookieManager.getInstance();
            // Clear cookies for all Vinted domains
            String[] vintedDomains = {
                "https://www.vinted.fr", "https://www.vinted.be", "https://www.vinted.es",
                "https://www.vinted.de", "https://www.vinted.it", "https://www.vinted.co.uk",
                "https://www.vinted.nl", "https://www.vinted.pl", "https://www.vinted.pt",
                "https://www.vinted.com"
            };
            for (String domain : vintedDomains) {
                String cookies = cm.getCookie(domain);
                if (cookies == null) continue;
                for (String part : cookies.split(";")) {
                    String name = part.trim().split("=")[0];
                    if (!name.isEmpty()) {
                        cm.setCookie(domain, name + "=; Max-Age=0; Path=/");
                    }
                }
            }
            cm.removeAllCookies(null);
            cm.flush();
            // Clear stored token too
            prefs.edit().remove("qc_token").apply();
            Log.i(TAG, "Vinted cookies cleared");
        } catch (Exception e) {
            Log.e(TAG, "clearVintedCookies error", e);
        }
    }

    void extractAndSaveVintedToken(String url) {
        try {
            String domain = "https://www.vinted.fr";
            if (url.contains("vinted.be"))     domain = "https://www.vinted.be";
            else if (url.contains("vinted.es")) domain = "https://www.vinted.es";
            else if (url.contains("vinted.de")) domain = "https://www.vinted.de";
            else if (url.contains("vinted.co.uk")) domain = "https://www.vinted.co.uk";

            String cookies = CookieManager.getInstance().getCookie(domain);
            if (cookies == null) return;

            for (String part : cookies.split(";")) {
                String trimmed = part.trim();
                if (trimmed.startsWith("access_token_web=")) {
                    String token = trimmed.substring("access_token_web=".length()).trim();
                    if (!token.isEmpty()) {
                        String existing = prefs.getString("qc_token", "");
                        if (!token.equals(existing)) {
                            prefs.edit().putString("qc_token", token).apply();
                            Log.i(TAG, "Token Vinted mis a jour automatiquement");
                            android.widget.Toast.makeText(this,
                                "Token Vinted mis a jour automatiquement",
                                android.widget.Toast.LENGTH_SHORT).show();
                        }
                    }
                    break;
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "extractAndSaveVintedToken error", e);
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

    private String buildBridgePatch(boolean withRuntime) {
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

    int dp(int dp) {
        return Math.round(dp * getResources().getDisplayMetrics().density);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) webView.onPause();
        CookieManager.getInstance().flush();
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
