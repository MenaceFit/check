package com.autocop.quickcheckout;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.Iterator;

/**
 * JavaScript bridge exposed as window.__QCBridge inside the WebView.
 *
 * Replaces chrome.runtime.sendMessage + chrome.storage.local so the injected
 * content scripts work without the Chrome Extension API.
 *
 * Storage design:
 *   - Everything stored as strings in SharedPreferences ("qc_storage")
 *   - Booleans → "true" / "false"
 *   - JSON objects/arrays → their toString() representation
 *   - Parsed back to proper JS types in storageGet (object → JSONObject, bool → boolean, etc.)
 *
 * Config (domain, token) lives in a separate "qc_prefs" file to keep
 * extension-storage separate from app settings.
 *
 * All @JavascriptInterface methods run on a background thread — UI operations
 * must be posted via activity.runOnUiThread().
 */
public class CheckoutBridge {

    private static final String TAG          = "QC-Bridge";
    private static final String PREFS_STORE  = "qc_storage";

    private final MainActivity        activity;
    private final WebView             webView;
    private final SharedPreferences   prefs;    // app config: domain, token, first_launch
    private final SharedPreferences   store;    // chrome.storage.local equivalent

    public CheckoutBridge(MainActivity activity) {
        this.activity = activity;
        this.webView  = activity.webView;
        this.prefs    = activity.prefs;
        this.store    = activity.getSharedPreferences(PREFS_STORE, Context.MODE_PRIVATE);
    }

    // ── chrome.runtime.sendMessage ────────────────────────────────────────────

    @JavascriptInterface
    public String sendMessage(String jsonMsg) {
        try {
            JSONObject msg  = new JSONObject(jsonMsg);
            String     type = msg.optString("type", "");
            Log.d(TAG, "sendMessage: " + type);

            switch (type) {
                case "QUICK_CHECKOUT":   return handleCheckout(msg);
                case "CHECKOUT_METRICS": logMetrics(msg);           return ok();
                case "GET_CONFIG":       return buildConfig();
                case "PING":             return "{\"ok\":true,\"pong\":true}";
                default:
                    Log.w(TAG, "Unknown message type: " + type);
                    return "{\"ok\":false,\"error\":\"unknown_type\"}";
            }
        } catch (JSONException e) {
            Log.e(TAG, "sendMessage JSON error", e);
            return "{\"ok\":false,\"error\":\"json_error\"}";
        }
    }

    // ── QUICK_CHECKOUT handler ────────────────────────────────────────────────

    private String handleCheckout(JSONObject msg) throws JSONException {
        JSONObject listing = msg.optJSONObject("listing");
        if (listing == null) return err("no_listing");

        String itemId = listing.optString("id", "").trim();
        if (itemId.isEmpty()) return err("no_item_id");

        long    t0      = msg.optLong("t0", System.currentTimeMillis());
        boolean autobuy = "true".equals(store.getString("qc_autobuy", "false"));
        String  domain  = prefs.getString("qc_vinted_domain", "www.vinted.fr");

        // Persist pending checkout so vinted-checkout.js can read it after navigation
        JSONObject pending = new JSONObject();
        pending.put("itemId",  itemId);
        pending.put("ts",      t0);
        pending.put("autobuy", autobuy);
        storeWrite("qc_pending_checkout", pending.toString());
        storeWrite("qc_autobuy",          String.valueOf(autobuy));

        String vintedUrl = "https://" + domain + "/items/" + itemId;
        Log.i(TAG, "Checkout → " + vintedUrl + "  autobuy=" + autobuy);

        // Navigate on the UI thread
        activity.runOnUiThread(() -> webView.loadUrl(vintedUrl));

        long elapsed = System.currentTimeMillis() - t0;
        return "{\"ok\":true,\"metrics\":{\"t4_total_ms\":" + elapsed + "}}";
    }

    private void logMetrics(JSONObject msg) {
        try {
            long   tStart   = msg.optLong("t_start",   0);
            long   tClicked = msg.optLong("t_clicked",  0);
            String itemId   = msg.optString("itemId",  "?");
            if (tStart > 0 && tClicked > 0) {
                Log.i(TAG, "Checkout[" + itemId + "] done in " + (tClicked - tStart) + "ms");
            }
        } catch (Exception e) {
            Log.w(TAG, "logMetrics: " + e.getMessage());
        }
    }

    // ── GET_CONFIG — called by JS when it needs app settings ─────────────────

    @JavascriptInterface
    public String buildConfig() {
        try {
            JSONObject cfg = new JSONObject();
            cfg.put("autobuy",  "true".equals(store.getString("qc_autobuy", "false")));
            cfg.put("domain",   prefs.getString("qc_vinted_domain", "www.vinted.fr"));
            cfg.put("hasToken", !prefs.getString("qc_token", "").isEmpty());
            cfg.put("version",  "1.3.0");
            return cfg.toString();
        } catch (JSONException e) {
            return "{\"ok\":false}";
        }
    }

    // ── chrome.storage.local.get ──────────────────────────────────────────────
    //
    // Input: JSON.stringify of either
    //   - an array  ["key1","key2"]
    //   - an object {"key1":default1}
    //   - a single quoted key  "keyName"
    //
    // Output: JSON object {"key1": value1, ...}
    //   Values are typed: booleans as boolean, numbers as number, objects as object.

    @JavascriptInterface
    public String storageGet(String keysJson) {
        try {
            if (keysJson == null || keysJson.isEmpty()) return "{}";
            JSONObject result  = new JSONObject();
            String     trimmed = keysJson.trim();

            if (trimmed.startsWith("[")) {
                JSONArray keys = new JSONArray(trimmed);
                for (int i = 0; i < keys.length(); i++) {
                    readKey(result, keys.getString(i));
                }
            } else if (trimmed.startsWith("{")) {
                JSONObject req = new JSONObject(trimmed);
                for (Iterator<String> it = req.keys(); it.hasNext(); ) {
                    readKey(result, it.next());
                }
            } else {
                // Single string key, possibly JSON-quoted ("keyName" or keyName)
                readKey(result, trimmed.replaceAll("^\"|\"$", ""));
            }
            return result.toString();
        } catch (JSONException e) {
            Log.e(TAG, "storageGet error for: " + keysJson, e);
            return "{}";
        }
    }

    /** Reads one key from SharedPreferences and puts it (with proper type) into out. */
    private void readKey(JSONObject out, String key) throws JSONException {
        String raw = store.getString(key, null);
        if (raw == null) return;  // key not present → omit (JS code uses ?? defaults)

        // JSON object
        if (raw.startsWith("{")) {
            try { out.put(key, new JSONObject(raw)); return; } catch (JSONException ignored) {}
        }
        // JSON array
        if (raw.startsWith("[")) {
            try { out.put(key, new JSONArray(raw)); return; } catch (JSONException ignored) {}
        }
        // Boolean
        if ("true".equals(raw))  { out.put(key, true);  return; }
        if ("false".equals(raw)) { out.put(key, false); return; }
        // Integer
        try { out.put(key, Long.parseLong(raw)); return; } catch (NumberFormatException ignored) {}
        // Float
        try { out.put(key, Double.parseDouble(raw)); return; } catch (NumberFormatException ignored) {}
        // Plain string
        out.put(key, raw);
    }

    // ── chrome.storage.local.set ──────────────────────────────────────────────

    @JavascriptInterface
    public void storageSet(String valuesJson) {
        try {
            JSONObject            obj    = new JSONObject(valuesJson);
            SharedPreferences.Editor ed = store.edit();
            for (Iterator<String> it = obj.keys(); it.hasNext(); ) {
                String k = it.next();
                Object v = obj.get(k);
                if (v == JSONObject.NULL) {
                    ed.remove(k);
                } else if (v instanceof JSONObject || v instanceof JSONArray) {
                    ed.putString(k, v.toString());
                } else {
                    // Booleans, numbers, strings → store as their string representation
                    ed.putString(k, String.valueOf(v));
                }
            }
            ed.apply();
        } catch (JSONException e) {
            Log.e(TAG, "storageSet error", e);
        }
    }

    // ── chrome.storage.local.remove ───────────────────────────────────────────

    @JavascriptInterface
    public void storageRemove(String keyJson) {
        try {
            String trimmed = keyJson.trim();
            SharedPreferences.Editor ed = store.edit();
            if (trimmed.startsWith("[")) {
                JSONArray arr = new JSONArray(trimmed);
                for (int i = 0; i < arr.length(); i++) ed.remove(arr.getString(i));
            } else {
                ed.remove(trimmed.replaceAll("^\"|\"$", ""));
            }
            ed.apply();
        } catch (JSONException e) {
            Log.e(TAG, "storageRemove error", e);
        }
    }

    // ── Convenience methods callable from SettingsDialog ─────────────────────

    void setAutobuy(boolean enabled) {
        storeWrite("qc_autobuy", String.valueOf(enabled));
        Log.i(TAG, "Autobuy " + (enabled ? "ON" : "OFF"));
    }

    boolean getAutobuy() {
        return "true".equals(store.getString("qc_autobuy", "false"));
    }

    void setVintedDomain(String domain) {
        if (domain != null && !domain.isEmpty()) {
            prefs.edit().putString("qc_vinted_domain", domain).apply();
        }
    }

    String getVintedDomain() {
        return prefs.getString("qc_vinted_domain", "www.vinted.fr");
    }

    void setToken(String token) {
        if (token == null || token.isEmpty()) {
            prefs.edit().remove("qc_token").apply();
        } else {
            prefs.edit().putString("qc_token", token).apply();
        }
        Log.i(TAG, "Token " + (token == null || token.isEmpty() ? "cleared" : "set (" + maskToken(token) + ")"));
    }

    String getToken() {
        return prefs.getString("qc_token", "");
    }

    private static String maskToken(String t) {
        if (t == null || t.length() <= 8)  return "****";
        if (t.length() <= 12) return t.substring(0, 3) + "****" + t.substring(t.length() - 2);
        return t.substring(0, 6) + "****" + t.substring(t.length() - 4);
    }

    // ── Internal helpers ──────────────────────────────────────────────────────

    private void storeWrite(String key, String value) {
        store.edit().putString(key, value).apply();
    }

    private String ok()            { return "{\"ok\":true}"; }
    private String err(String msg) { return "{\"ok\":false,\"error\":\"" + msg + "\"}"; }
}
