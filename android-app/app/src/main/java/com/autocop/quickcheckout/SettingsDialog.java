package com.autocop.quickcheckout;

import android.content.Context;
import android.graphics.Color;
import android.text.InputType;
import android.view.View;
import android.widget.*;
import android.app.AlertDialog;

/**
 * Native settings dialog — opened by the ⚙️ FAB button.
 *
 * Lets the user configure:
 *  - Vinted domain (market / country)
 *  - Autobuy on/off
 *  - Vinted Bearer token (optional — used for future API verification)
 *  - Quick link to log in to Vinted inside the WebView
 */
public class SettingsDialog {

    // Vinted markets in order of relevance (France first since user uses Google FR)
    private static final String[] DOMAINS = {
        "www.vinted.fr", "www.vinted.be", "www.vinted.es", "www.vinted.de",
        "www.vinted.it", "www.vinted.co.uk", "www.vinted.nl", "www.vinted.pl",
        "www.vinted.pt", "www.vinted.com"
    };
    private static final String[] DOMAIN_LABELS = {
        "🇫🇷  vinted.fr (France)",  "🇧🇪  vinted.be (Belgique)",
        "🇪🇸  vinted.es (Espagne)", "🇩🇪  vinted.de (Allemagne)",
        "🇮🇹  vinted.it (Italie)",  "🇬🇧  vinted.co.uk (UK)",
        "🇳🇱  vinted.nl (Pays-Bas)","🇵🇱  vinted.pl (Pologne)",
        "🇵🇹  vinted.pt (Portugal)", "🌍  vinted.com (International)"
    };

    public static void show(MainActivity activity) {
        CheckoutBridge bridge = new CheckoutBridge(activity);
        Context ctx = activity;
        int pad = dp(ctx, 20);

        // Root scroll
        ScrollView scroll = new ScrollView(ctx);
        LinearLayout root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#1a1a2e"));
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        // ── Section: Domain ───────────────────────────────────────────────────
        root.addView(sectionTitle(ctx, "🌍  Marché Vinted"));
        root.addView(hint(ctx, "Sélectionnez le pays où vous achetez sur Vinted."));

        Spinner domainSpinner = new Spinner(ctx);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(ctx,
            android.R.layout.simple_spinner_dropdown_item, DOMAIN_LABELS);
        domainSpinner.setAdapter(adapter);
        String currentDomain = bridge.getVintedDomain();
        for (int i = 0; i < DOMAINS.length; i++) {
            if (DOMAINS[i].equals(currentDomain)) { domainSpinner.setSelection(i); break; }
        }
        root.addView(domainSpinner, wrapParams(ctx, 0, 6, 0, 20));

        // ── Section: Autobuy ──────────────────────────────────────────────────
        root.addView(divider(ctx));
        root.addView(sectionTitle(ctx, "🤖  Autobuy"));

        LinearLayout autobuyRow = row(ctx);
        TextView autobuyLbl = label(ctx, "Achat automatique complet");
        autobuyRow.addView(autobuyLbl, stretchParam());
        Switch autobuySwitch = new Switch(ctx);
        autobuySwitch.setChecked(bridge.getAutobuy());
        autobuyRow.addView(autobuySwitch);
        root.addView(autobuyRow, wrapParams(ctx, 0, 8, 0, 4));

        TextView autobuyWarn = hint(ctx,
            "⚠️  En mode autobuy, l'achat est finalisé automatiquement :\n" +
            "Acheter → Livraison Continuer → Payer\n" +
            "Assurez-vous d'avoir une adresse et un paiement enregistrés sur Vinted.");
        autobuyWarn.setTextColor(Color.parseColor("#FFC107"));
        autobuyWarn.setVisibility(autobuySwitch.isChecked() ? View.VISIBLE : View.GONE);
        root.addView(autobuyWarn, wrapParams(ctx, 0, 0, 0, 16));
        autobuySwitch.setOnCheckedChangeListener((b, on) ->
            autobuyWarn.setVisibility(on ? View.VISIBLE : View.GONE));

        // ── Section: Token ────────────────────────────────────────────────────
        root.addView(divider(ctx));
        root.addView(sectionTitle(ctx, "🔑  Token Vinted (optionnel)"));
        root.addView(hint(ctx,
            "Bearer token de l'API Vinted. Permet de vérifier la disponibilité " +
            "d'un article avant de naviguer vers sa page. Laissez vide pour désactiver."));

        LinearLayout tokenRow = row(ctx);
        EditText tokenField = new EditText(ctx);
        tokenField.setHint("eyJ0eXAiOiJKV1QiLCJhbGciOiJS...");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenField.setTextColor(Color.WHITE);
        tokenField.setHintTextColor(Color.parseColor("#555566"));
        tokenField.setSaveEnabled(false);
        String savedToken = bridge.getToken();
        tokenField.setText(savedToken);
        tokenRow.addView(tokenField, stretchParam());

        // Show/hide toggle
        TextView eyeBtn = new TextView(ctx);
        eyeBtn.setText("👁");
        eyeBtn.setTextSize(18);
        eyeBtn.setPadding(dp(ctx, 8), 0, 0, 0);
        eyeBtn.setTextColor(Color.parseColor("#6C63FF"));
        final boolean[] visible = {false};
        eyeBtn.setOnClickListener(v -> {
            visible[0] = !visible[0];
            tokenField.setInputType(visible[0]
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            tokenField.setSelection(tokenField.getText().length());
        });
        tokenRow.addView(eyeBtn);
        root.addView(tokenRow, wrapParams(ctx, 0, 8, 0, 4));

        // Clear token link
        TextView clearBtn = new TextView(ctx);
        clearBtn.setText("Effacer le token");
        clearBtn.setTextColor(Color.parseColor("#FF5555"));
        clearBtn.setTextSize(12);
        clearBtn.setPadding(0, dp(ctx, 4), 0, dp(ctx, 4));
        clearBtn.setVisibility(savedToken.isEmpty() ? View.GONE : View.VISIBLE);
        clearBtn.setOnClickListener(v -> {
            tokenField.setText("");
            clearBtn.setVisibility(View.GONE);
        });
        root.addView(clearBtn, wrapParams(ctx, 0, 0, 0, 16));

        // ── Section: Vinted login ─────────────────────────────────────────────
        root.addView(divider(ctx));
        root.addView(sectionTitle(ctx, "🔓  Connexion Vinted"));
        root.addView(hint(ctx,
            "L'app utilise votre session Vinted (cookies). Si vous n'êtes pas encore " +
            "connecté(e), appuyez sur le bouton ci-dessous pour ouvrir la page de connexion."));

        Button loginBtn = new Button(ctx);
        loginBtn.setText("Ouvrir Vinted pour se connecter");
        loginBtn.setTextColor(Color.WHITE);
        loginBtn.setBackgroundColor(Color.parseColor("#6C63FF"));
        root.addView(loginBtn, wrapParams(ctx, 0, 8, 0, 4));

        // ── Build the dialog ──────────────────────────────────────────────────
        AlertDialog dialog = new AlertDialog.Builder(activity)
            .setView(scroll)
            .setPositiveButton("Enregistrer", null)
            .setNegativeButton("Annuler", null)
            .create();

        loginBtn.setOnClickListener(v -> {
            // Save first so domain is correct before navigating
            String domain = DOMAINS[domainSpinner.getSelectedItemPosition()];
            bridge.setVintedDomain(domain);
            dialog.dismiss();
            activity.webView.post(() ->
                activity.webView.loadUrl("https://" + domain + "/member/login_form"));
        });

        dialog.show();

        // Positive button saves without dismissing until validated
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String domain  = DOMAINS[domainSpinner.getSelectedItemPosition()];
            boolean autobuy = autobuySwitch.isChecked();
            String token    = tokenField.getText().toString().trim();

            bridge.setVintedDomain(domain);
            bridge.setAutobuy(autobuy);
            bridge.setToken(token);

            // Push autobuy state into the WebView's storage so live scripts see it
            if (activity.webView != null) {
                activity.webView.post(() ->
                    activity.webView.evaluateJavascript(
                        "if(window.__QCBridge)__QCBridge.storageSet('{\"qc_autobuy\":" +
                        autobuy + "}');", null));
            }

            Toast.makeText(activity, "✅ Réglages enregistrés !", Toast.LENGTH_SHORT).show();
            dialog.dismiss();
        });
    }

    // ── View helpers ──────────────────────────────────────────────────────────

    private static TextView sectionTitle(Context ctx, String text) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(15);
        tv.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        tv.setPadding(0, dp(ctx, 8), 0, dp(ctx, 4));
        return tv;
    }

    private static TextView label(Context ctx, String text) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.parseColor("#CCCCCC"));
        tv.setTextSize(14);
        return tv;
    }

    private static TextView hint(Context ctx, String text) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.parseColor("#888888"));
        tv.setTextSize(12);
        return tv;
    }

    private static View divider(Context ctx) {
        View v = new View(ctx);
        v.setBackgroundColor(Color.parseColor("#333355"));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 1);
        p.setMargins(0, dp(ctx, 12), 0, dp(ctx, 8));
        v.setLayoutParams(p);
        return v;
    }

    private static LinearLayout row(Context ctx) {
        LinearLayout r = new LinearLayout(ctx);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(android.view.Gravity.CENTER_VERTICAL);
        return r;
    }

    private static LinearLayout.LayoutParams stretchParam() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private static LinearLayout.LayoutParams wrapParams(Context ctx, int l, int t, int r, int b) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.setMargins(0, dp(ctx, t), 0, dp(ctx, b));
        return p;
    }

    private static int dp(Context ctx, int dp) {
        return Math.round(dp * ctx.getResources().getDisplayMetrics().density);
    }
}
