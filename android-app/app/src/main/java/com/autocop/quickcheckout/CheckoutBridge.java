package com.autocop.quickcheckout;

import android.content.SharedPreferences;
import android.util.Log;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.Iterator;

/**
 * JavaScript bridge injected as window.__QCBridge.
 *
 * Replaces chrome.runtime.sendMessage + chrome.storage.local in the injected
 * content scripts so they work inside an Android WebView without the Chrome
 * extension APIs.
 *
 * All methods annotated with @JavascriptInterface run on a background thread.
 */
public class CheckoutBridge {

    private static final String TAG = "QC-Bridge";
    private static final String PREFS_STORAGE = "qc_storage";

    private final MainActivity activity;
    private final WebView webView;
    private final SharedPreferences prefs;
    private final SharedPreferences storage;
    private final String vintedCheckoutJs;
    private final String autocopInjectedCss;

    public CheckoutBridge(MainActivity activity, WebView webView,
                          SharedPreferences prefs,
                          String vintedCheckoutJs, String autocopInjectedCss) {
        this.activity          = activity;
        this.webView           = webView;
        this.prefs             = prefs;
        this.vintedCheckoutJs  = vintedCheckoutJs;
        this.autocopInjectedCss = autocopInjectedCss;
        this.storage = activity.getSharedPreferences(PREFS_STORAGE, android.content.Context.MODE_PRIVATE);
    }

    // ── chrome.runtime.sendMessage replacement ─────────────────────────────────

    @JavascriptInterface
    public String sendMessage(String jsonMsg) {
        try {
            JSONObject msg = new JSONObject(jsonMsg);
            String type = msg.optString("type", "");
            Log.d(TAG, "sendMessage: " + type);

            switch (type) {
                case "QUICK_CHECKOUT":
                    return handleQuickCheckout(msg);
                case "CHECKOUT_METRICS":
                    handleMetrics(msg);
                    return jsonOk();
                case "PING":
                    return "{\"ok\":true,\"pong\":true}";
                default:
                    Log.w(TAG, "Unhandled message type: " + type);
                    return "{\"ok\":false,\"error\":\"Unknown type\"}";
            }
        } catch (JSONException e) {
            Log.e(TAG, "JSON error in sendMessage", e);
            return "{\"ok\":false,\"error\":\"JSON error\"}";
        }
    }

    private String handleQuickCheckout(JSONObject msg) throws JSONException {
        JSONObject listing = msg.optJSONObject("listing");
        if (listing == null) return "{\"ok\":false,\"error\":\"No listing\"}";

        String itemId = listing.optString("id");
        if (itemId.isEmpty()) return "{\"ok\":false,\"error\":\"No itemId\"}";

        long t0 = msg.optLong("t0", System.currentTimeMillis());
        boolean autobuy = storage.getBoolean("qc_autobuy", false);

        // Store pending checkout in prefs so vinted-checkout.js can read it
        JSONObject pending = new JSONObject();
        pending.put("itemId", itemId);
        pending.put("ts", t0);
        pending.put("autobuy", autobuy);
        storage.edit().putString("qc_pending_checkout", pending.toString()).apply();
        storage.edit().putBoolean("qc_autobuy", autobuy).apply();

        // Navigate the WebView to the Vinted item page
        String domain = prefs.getString("qc_vinted_domain", "www.vinted.fr");
        final String vintedUrl = "https://" + domain + "/items/" + itemId;

        activity.runOnUiThread(() -> webView.loadUrl(vintedUrl));

        long totalMs = System.currentTimeMillis() - t0;
        return "{\"ok\":true,\"metrics\":{\"t4_total_ms\":" + totalMs + "}}";
    }

    private void handleMetrics(JSONObject msg) {
        try {
            long t_start   = msg.optLong("t_start", 0);
            long t_clicked = msg.optLong("t_clicked", 0);
            if (t_start > 0 && t_clicked > 0) {
                long total = t_clicked - t_start;
                Log.i(TAG, "Checkout completed in " + total + "ms for item " +
                        msg.optString("itemId"));
            }
        } catch (Exception e) {
            Log.e(TAG, "Metrics error", e);
        }
    }

    // ── chrome.storage.local replacement ──────────────────────────────────────

    @JavascriptInterface
    public String storageGet(String keysJson) {
        try {
            JSONObject result = new JSONObject();
            if (keysJson.startsWith("[")) {
                JSONArray keys = new JSONArray(keysJson);
                for (int i = 0; i < keys.length(); i++) {
                    String k = keys.getString(i);
                    String v = storage.getString(k, null);
                    if (v != null) {
                        try { result.put(k, new JSONObject(v)); } catch (JSONException ex) {
                            try { result.put(k, new JSONArray(v)); } catch (JSONException ex2) {
                                // Scalar
                                if ("true".equals(v)) result.put(k, true);
                                else if ("false".equals(v)) result.put(k, false);
                                else { try { result.put(k, Long.parseLong(v)); } catch (NumberFormatException nfe) { result.put(k, v); } }
                            }
                        }
                    }
                }
            } else if (keysJson.startsWith("{")) {
                JSONObject req = new JSONObject(keysJson);
                Iterator<String> it = req.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    String v = storage.getString(k, null);
                    if (v != null) result.put(k, v);
                }
            } else {
                // Single key (string)
                String k = keysJson.replaceAll("\"", "");
                String v = storage.getString(k, null);
                if (v != null) result.put(k, v);
            }
            return result.toString();
        } catch (JSONException e) {
            Log.e(TAG, "storageGet error", e);
            return "{}";
        }
    }

    @JavascriptInterface
    public void storageSet(String valuesJson) {
        try {
            JSONObject obj = new JSONObject(valuesJson);
            SharedPreferences.Editor editor = storage.edit();
            Iterator<String> it = obj.keys();
            while (it.hasNext()) {
                String k = it.next();
                Object v = obj.get(k);
                if (v instanceof Boolean) editor.putBoolean(k, (Boolean) v);
                else editor.putString(k, v.toString());
            }
            editor.apply();
        } catch (JSONException e) {
            Log.e(TAG, "storageSet error", e);
        }
    }

    @JavascriptInterface
    public void storageRemove(String keyJson) {
        try {
            String k = keyJson.replaceAll("\"", "").replaceAll("[\\[\\]]", "");
            storage.edit().remove(k).apply();
        } catch (Exception e) {
            Log.e(TAG, "storageRemove error", e);
        }
    }

    // ── Settings helpers ───────────────────────────────────────────────────────

    @JavascriptInterface
    public void setAutobuy(boolean enabled) {
        storage.edit().putBoolean("qc_autobuy", enabled).apply();
        Log.i(TAG, "Autobuy " + (enabled ? "ON" : "OFF"));
    }

    @JavascriptInterface
    public boolean getAutobuy() {
        return storage.getBoolean("qc_autobuy", false);
    }

    @JavascriptInterface
    public void setVintedDomain(String domain) {
        prefs.edit().putString("qc_vinted_domain", domain).apply();
    }

    private String jsonOk() { return "{\"ok\":true}"; }
}
