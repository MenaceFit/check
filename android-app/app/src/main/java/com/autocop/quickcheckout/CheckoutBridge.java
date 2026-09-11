package com.autocop.quickcheckout;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Iterator;

/**
 * JavaScript bridge exposed as window.__QCBridge inside the WebView.
 *
 * Replaces chrome.runtime.sendMessage + chrome.storage.local so the injected
 * content scripts work without the Chrome Extension API.
 */
public class CheckoutBridge {

    private static final String TAG          = "QC-Bridge";
    private static final String PREFS_STORE  = "qc_storage";
    private static final int    API_TIMEOUT  = 4000; // ms

    private final MainActivity        activity;
    private final WebView             webView;
    private final SharedPreferences   prefs;
    private final SharedPreferences   store;

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

    // ── QUICK_CHECKOUT ────────────────────────────────────────────────────────

    private String handleCheckout(JSONObject msg) throws JSONException {
        JSONObject listing = msg.optJSONObject("listing");
        if (listing == null) return err("no_listing");

        String itemId = listing.optString("id", "").trim();
        if (itemId.isEmpty()) return err("no_item_id");

        long    t0      = msg.optLong("t0", System.currentTimeMillis());
        boolean autobuy = "true".equals(store.getString("qc_autobuy", "false"));
        String  domain  = prefs.getString("qc_vinted_domain", "www.vinted.fr");
        String  token   = prefs.getString("qc_token", "");

        // Optional fast API pre-check (non-blocking the navigation)
        // We fire-and-forget: navigate immediately, let JS handle if item gone
        boolean doPrecheck = !token.isEmpty();
        if (doPrecheck) {
            final String fItemId = itemId;
            final String fDomain = domain;
            final String fToken  = token;
            new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        boolean available = apiCheckItem(fDomain, fItemId, fToken);
                        if (!available) {
                            Log.i(TAG, "Item " + fItemId + " not available per API pre-check");
                            activity.runOnUiThread(new Runnable() {
                                @Override
                                public void run() {
                                    android.widget.Toast.makeText(activity,
                                        "Article deja vendu ou indisponible",
                                        android.widget.Toast.LENGTH_SHORT).show();
                                }
                            });
                        }
                    } catch (Exception e) {
                        Log.d(TAG, "API pre-check skipped: " + e.getMessage());
                    }
                }
            }).start();
        }

        // Persist pending checkout
        JSONObject pending = new JSONObject();
        pending.put("itemId",  itemId);
        pending.put("ts",      t0);
        pending.put("autobuy", autobuy);
        storeWrite("qc_pending_checkout", pending.toString());
        storeWrite("qc_autobuy",          String.valueOf(autobuy));

        String vintedUrl = "https://" + domain + "/items/" + itemId;
        Log.i(TAG, "Checkout -> " + vintedUrl + "  autobuy=" + autobuy);

        final String finalUrl = vintedUrl;
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                webView.loadUrl(finalUrl);
            }
        });

        long elapsed = System.currentTimeMillis() - t0;
        return "{\"ok\":true,\"metrics\":{\"t4_total_ms\":" + elapsed + "}}";
    }

    /**
     * Quick Vinted API check to see if an item is still for sale.
     * Returns true if available (or unknown), false if confirmed sold.
     */
    private boolean apiCheckItem(String domain, String itemId, String token) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL("https://" + domain + "/api/v2/items/" + itemId);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(API_TIMEOUT);
            conn.setReadTimeout(API_TIMEOUT);
            conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("User-Agent",
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36");

            int code = conn.getResponseCode();
            if (code == 404) return false; // definitely gone
            if (code != 200) return true;  // assume available on other errors

            BufferedReader br = new BufferedReader(
                new InputStreamReader(conn.getInputStream(), "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) sb.append(line);
            br.close();

            JSONObject resp = new JSONObject(sb.toString());
            JSONObject item = resp.optJSONObject("item");
            if (item == null) item = resp.optJSONObject("data");
            if (item == null) return true;

            boolean canBeSold = item.optBoolean("can_be_sold", true);
            boolean isForSale = item.optBoolean("is_for_sale", true);
            String  status    = item.optString("status", "");
            return canBeSold && isForSale && !status.equals("sold");

        } catch (Exception e) {
            Log.d(TAG, "apiCheckItem: " + e.getMessage());
            return true; // network error → assume available
        } finally {
            if (conn != null) conn.disconnect();
        }
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

    // ── GET_CONFIG ────────────────────────────────────────────────────────────

    @JavascriptInterface
    public String buildConfig() {
        try {
            JSONObject cfg = new JSONObject();
            cfg.put("autobuy",  "true".equals(store.getString("qc_autobuy", "false")));
            cfg.put("domain",   prefs.getString("qc_vinted_domain", "www.vinted.fr"));
            cfg.put("hasToken", !prefs.getString("qc_token", "").isEmpty());
            cfg.put("version",  "1.4.0");
            return cfg.toString();
        } catch (JSONException e) {
            return "{\"ok\":false}";
        }
    }

    // ── chrome.storage.local.get ──────────────────────────────────────────────

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
                readKey(result, trimmed.replaceAll("^\"|\"$", ""));
            }
            // Also expose token for content scripts
            if (trimmed.contains("qc_token") || trimmed.equals("\"qc_token\"")) {
                String tok = prefs.getString("qc_token", "");
                if (!tok.isEmpty()) result.put("qc_token", tok);
            }
            return result.toString();
        } catch (JSONException e) {
            Log.e(TAG, "storageGet error for: " + keysJson, e);
            return "{}";
        }
    }

    private void readKey(JSONObject out, String key) throws JSONException {
        // Token lives in prefs, not store
        if ("qc_token".equals(key)) {
            String tok = prefs.getString("qc_token", "");
            if (!tok.isEmpty()) out.put(key, tok);
            return;
        }
        if ("qc_vinted_domain".equals(key)) {
            out.put(key, prefs.getString("qc_vinted_domain", "www.vinted.fr"));
            return;
        }

        String raw = store.getString(key, null);
        if (raw == null) return;

        if (raw.startsWith("{")) {
            try { out.put(key, new JSONObject(raw)); return; } catch (JSONException ignored) {}
        }
        if (raw.startsWith("[")) {
            try { out.put(key, new JSONArray(raw)); return; } catch (JSONException ignored) {}
        }
        if ("true".equals(raw))  { out.put(key, true);  return; }
        if ("false".equals(raw)) { out.put(key, false); return; }
        try { out.put(key, Long.parseLong(raw)); return; } catch (NumberFormatException ignored) {}
        try { out.put(key, Double.parseDouble(raw)); return; } catch (NumberFormatException ignored) {}
        out.put(key, raw);
    }

    // ── chrome.storage.local.set ──────────────────────────────────────────────

    @JavascriptInterface
    public void storageSet(String valuesJson) {
        try {
            JSONObject obj = new JSONObject(valuesJson);
            SharedPreferences.Editor ed = store.edit();
            for (Iterator<String> it = obj.keys(); it.hasNext(); ) {
                String k = it.next();
                Object v = obj.get(k);
                if (v == JSONObject.NULL) {
                    ed.remove(k);
                } else if (v instanceof JSONObject || v instanceof JSONArray) {
                    ed.putString(k, v.toString());
                } else {
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

    // ── Convenience methods ───────────────────────────────────────────────────

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

    private void storeWrite(String key, String value) {
        store.edit().putString(key, value).apply();
    }

    private String ok()            { return "{\"ok\":true}"; }
    private String err(String msg) { return "{\"ok\":false,\"error\":\"" + msg + "\"}"; }
}
