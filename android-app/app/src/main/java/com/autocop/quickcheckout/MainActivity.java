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
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.RelativeLayout;
import android.widget.TextView;

import android.app.Activity;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {

    static final String TAG    = "QC-Android";
    static final String PREFS  = "qc_prefs";
    static final String KEY_FIRST_LAUNCH = "first_launch";

    static final String AUTOCOP_URL = "https://autocop.app";

    // ── IAB vendor / tracker domains to block ────────────────────────────────
    // Full third-party ad networks, analytics, fingerprinting, and consent mgmt
    private static final String[] BLOCKED_DOMAINS = {
        // Google advertising & tracking (Maps/Search API allowed separately)
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "google-analytics.com", "googletagmanager.com", "googletagservices.com",
        "adservice.google.com", "adservice.google.fr", "adservice.google.co.uk",
        "pagead2.googlesyndication.com", "stats.g.doubleclick.net",
        // Facebook / Meta
        "connect.facebook.net", "facebook.net", "fbcdn.net",
        "pixel.facebook.com",
        // IAB vendor networks (RTB / programmatic)
        "criteo.com", "criteo.net",
        "adnxs.com",                    // AppNexus / Xandr
        "rubiconproject.com",           // Magnite
        "pubmatic.com",
        "openx.net",
        "casalemedia.com",              // Index Exchange
        "indexexchange.com",
        "33across.com",
        "bidswitch.net",
        "sovrn.com", "lijit.com",
        "contextweb.com",               // PulsePoint
        "rhythmone.com",
        "smartadserver.com",
        "teads.tv", "teads.com",
        "outbrain.com",
        "taboola.com",
        "advertising.com",              // Oath/Verizon Media
        "adtech.de",
        "yieldmanager.com",
        "adadvisor.net",
        "adgrx.com",
        "adscale.de",
        // Consent management platforms (IAB CMP)
        "quantcast.com", "quantcast.mgr.consensu.org",
        "consensu.org",
        "onetrust.com", "cookielaw.org",
        "trustarc.com",
        "sourcepoint.com",
        "didomi.io",
        "usercentrics.eu",
        // Analytics / tracking SDKs
        "scorecardresearch.com",
        "quantserve.com",
        "hotjar.com",
        "segment.com", "segment.io",
        "cdn.segment.com",
        "mixpanel.com",
        "amplitude.com",
        "heap.io",
        "fullstory.com",
        // Marketing automation
        "braze.com", "appboy.com",
        "adjust.com", "adjust.io",
        "appsflyer.com",
        "branch.io",
        "localytics.com",
        "moengage.com",
        "klaviyo.com",
        "mailchimp.com",
        // Ad quality / brand safety
        "moatads.com",
        "adsafeprotected.com",
        "doubleverify.com",
        "adloox.com",
        "jads.co",
        // Social retargeting pixels
        "bat.bing.com",
        "analytics.twitter.com",
        "static.ads-twitter.com",
        "snap.licdn.com",
        "px.ads.linkedin.com",
        "analytics.tiktok.com",
        "sc-static.net",               // Snapchat
        "tr.snapchat.com",
        "ads.pinterest.com",
        "ct.pinterest.com",
        // Device fingerprinting
        "botd.fpjs.io",
        "api.fpjs.io",
        "fp.iesnare.com",
        "mpsnare.iesnare.com",
        "iovation.com",
        "threatmetrix.com",
        "siftscience.com",
        // Retargeting / audience
        "rtd.mxptint.net",
        "adhigh.net",
        "adform.net",
        "nextroll.com",
        "perfectaudience.com",
        "adroll.com",
    };

    WebView webView;
    SharedPreferences prefs;

    private ProgressBar progressBar;
    private String autocopDetectorJs;
    private String vintedCheckoutJs;
    private String autocopInjectedCss;
    private String privacyShieldJs;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        autocopDetectorJs  = loadAsset("autocop-detector.js");
        vintedCheckoutJs   = loadAsset("vinted-checkout.js");
        autocopInjectedCss = loadAsset("autocop-injected.css");
        privacyShieldJs    = buildPrivacyShieldJs();

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
        fab.setText("S");
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
        // Block third-party cookies from trackers
        ws.setUserAgentString(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
        );

        CookieManager.getInstance().setAcceptCookie(true);
        // Disable third-party cookies — trackers can't set cookies from blocked domains
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);

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

            // ── Network-level IAB / tracker blocking ──────────────────────────
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view,
                    WebResourceRequest request) {
                String host = request.getUrl().getHost();
                if (host != null && isBlockedDomain(host.toLowerCase())) {
                    Log.d(TAG, "Blocked tracker: " + host);
                    return emptyResponse();
                }
                return null;
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

    // ── Domain blocking ───────────────────────────────────────────────────────

    private boolean isBlockedDomain(String host) {
        for (String blocked : BLOCKED_DOMAINS) {
            if (host.equals(blocked) || host.endsWith("." + blocked)) {
                return true;
            }
        }
        return false;
    }

    private WebResourceResponse emptyResponse() {
        return new WebResourceResponse(
            "text/plain", "UTF-8",
            new ByteArrayInputStream(new byte[0]));
    }

    // ── Page injection ────────────────────────────────────────────────────────

    void injectIntoPage(String url) {
        if (url == null || url.startsWith("about:") || url.startsWith("data:")) return;

        boolean isAutocop = url.contains("autocop.app");
        boolean isVinted  = !isAutocop && url.contains("vinted.");

        if (isVinted) {
            extractAndSaveVintedToken(url);
        }

        // Inject privacy shield on all pages (denies TCF consent, removes fingerprint APIs)
        webView.evaluateJavascript(privacyShieldJs, null);

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

    // ── Privacy shield JS — denies IAB TCF, removes fingerprint APIs ──────────

    private String buildPrivacyShieldJs() {
        return "(function(){" +
            "if(window.__qcPrivacyShield)return;" +
            "window.__qcPrivacyShield=true;" +

            // Override IAB TCF API — deny all purposes and vendors
            "var _denyAll={" +
            "  gdprApplies:true," +
            "  cmpId:0,cmpVersion:0," +
            "  tcString:''," +
            "  isServiceSpecific:false," +
            "  useNonStandardStacks:false," +
            "  purposeOneTreatment:false," +
            "  publisherCC:'FR'," +
            "  eventStatus:'tcloaded'," +
            "  cmpStatus:'loaded'," +
            "  listenerId:0," +
            "  purpose:{consents:{},legitimateInterests:{}}," +
            "  vendor:{consents:{},legitimateInterests:{}}," +
            "  specialFeatureOptins:{}," +
            "  publisher:{consents:{},legitimateInterests:{}," +
            "    customPurpose:{consents:{},legitimateInterests:{}}," +
            "    restrictions:{}}" +
            "};" +
            "window.__tcfapi=function(cmd,v,cb,param){" +
            "  if(typeof cb==='function')cb(Object.assign({},_denyAll),true);" +
            "};" +

            // Clear IAB consent localStorage keys
            "try{" +
            "  var keys=['euconsent-v2','CookieConsent','consent_string','gdpr_consent'," +
            "    '__cmp','_sp_v1_consent','_sp_v1_seen_notice','eupubconsent'," +
            "    'cmapi_gtm_bl','cmapi_cookie_privacy'];" +
            "  keys.forEach(function(k){try{localStorage.removeItem(k);}catch(e){}});" +
            "}catch(e){}" +

            // Delete known tracking/consent cookies via document.cookie (JS-accessible ones)
            "try{" +
            "  var trackCookies=['_ga','_gid','_gat','_gcl_au','_gcl_aw','_fbp','_fbc'," +
            "    'fr','datr','sb','wd','xs','c_user','_pinterest_sess','muc_ads'," +
            "    'euconsent-v2','CookieConsent','OptanonConsent','OptanonAlertBoxClosed'];" +
            "  trackCookies.forEach(function(name){" +
            "    document.cookie=name+'=; Max-Age=0; Path=/; Domain='+location.hostname;" +
            "    document.cookie=name+'=; Max-Age=0; Path=/; Domain=.'+location.hostname;" +
            "  });" +
            "}catch(e){}" +

            "})();";
    }

    // ── Full cookie + storage clearing ───────────────────────────────────────

    void clearVintedCookies() {
        try {
            CookieManager cm = CookieManager.getInstance();

            // All Vinted domains + subdomains
            String[] vintedDomains = {
                "https://www.vinted.fr",    "https://vinted.fr",
                "https://www.vinted.be",    "https://vinted.be",
                "https://www.vinted.es",    "https://vinted.es",
                "https://www.vinted.de",    "https://vinted.de",
                "https://www.vinted.it",    "https://vinted.it",
                "https://www.vinted.co.uk", "https://vinted.co.uk",
                "https://www.vinted.nl",    "https://vinted.nl",
                "https://www.vinted.pl",    "https://vinted.pl",
                "https://www.vinted.pt",    "https://vinted.pt",
                "https://www.vinted.com",   "https://vinted.com",
            };

            // Identity & device cookies to explicitly expire first
            String[] identityCookies = {
                "access_token_web", "refresh_token_web",
                "user_id", "_vinted_fr_session", "_vinted_session",
                "anon_id", "device_id", "remember_user_token",
                "access_token", "refresh_token",
                "visitor_id", "country_code",
                // Tracking cookies Vinted uses
                "_ga", "_gid", "_gcl_au", "_fbp", "_fbc",
                "euconsent-v2", "OptanonConsent", "CookieConsent",
            };

            for (String domainUrl : vintedDomains) {
                // Expire each known identity/device cookie explicitly
                for (String name : identityCookies) {
                    cm.setCookie(domainUrl, name + "=; Max-Age=0; Path=/; SameSite=None; Secure");
                }
                // Also expire everything the CookieManager knows about this domain
                String allCookies = cm.getCookie(domainUrl);
                if (allCookies != null) {
                    for (String part : allCookies.split(";")) {
                        String name = part.trim().split("=")[0].trim();
                        if (!name.isEmpty()) {
                            cm.setCookie(domainUrl, name + "=; Max-Age=0; Path=/");
                        }
                    }
                }
            }

            // Nuclear option: remove ALL cookies from the WebView store
            cm.removeAllCookies(null);
            cm.flush();

            // Clear WebStorage (localStorage / sessionStorage / IndexedDB)
            WebStorage.getInstance().deleteAllData();

            // Clear WebView cache, history, and form data
            if (webView != null) {
                webView.clearCache(true);
                webView.clearHistory();
                webView.clearFormData();
            }

            // Clear stored token
            prefs.edit().remove("qc_token").apply();

            Log.i(TAG, "Full Vinted session cleared (cookies + storage + cache)");
        } catch (Exception e) {
            Log.e(TAG, "clearVintedCookies error", e);
        }
    }

    // ── Token extraction from Vinted cookies ─────────────────────────────────

    void extractAndSaveVintedToken(String url) {
        try {
            String domain = "https://www.vinted.fr";
            if      (url.contains("vinted.be"))     domain = "https://www.vinted.be";
            else if (url.contains("vinted.es"))      domain = "https://www.vinted.es";
            else if (url.contains("vinted.de"))      domain = "https://www.vinted.de";
            else if (url.contains("vinted.it"))      domain = "https://www.vinted.it";
            else if (url.contains("vinted.co.uk"))   domain = "https://www.vinted.co.uk";
            else if (url.contains("vinted.nl"))      domain = "https://www.vinted.nl";
            else if (url.contains("vinted.pl"))      domain = "https://www.vinted.pl";
            else if (url.contains("vinted.pt"))      domain = "https://www.vinted.pt";
            else if (url.contains("vinted.com"))     domain = "https://www.vinted.com";

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

    // ── CSS injection ─────────────────────────────────────────────────────────

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

    // ── Bridge patch: polyfill chrome.runtime + chrome.storage ───────────────

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
