package com.autocop.quickcheckout;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import android.app.AlertDialog;

public class SettingsDialog {

    private static final String[] DOMAINS = {
        "www.vinted.fr", "www.vinted.be", "www.vinted.es", "www.vinted.de",
        "www.vinted.it", "www.vinted.co.uk", "www.vinted.nl", "www.vinted.pl",
        "www.vinted.pt", "www.vinted.com"
    };
    private static final String[] DOMAIN_LABELS = {
        "FR  vinted.fr (France)",   "BE  vinted.be (Belgique)",
        "ES  vinted.es (Espagne)",  "DE  vinted.de (Allemagne)",
        "IT  vinted.it (Italie)",   "UK  vinted.co.uk",
        "NL  vinted.nl (Pays-Bas)", "PL  vinted.pl (Pologne)",
        "PT  vinted.pt (Portugal)", "INT vinted.com"
    };

    public static void show(final MainActivity activity) {
        final CheckoutBridge bridge = new CheckoutBridge(activity);
        Context ctx = activity;
        int p = dp(ctx, 16);

        ScrollView scroll = new ScrollView(ctx);
        LinearLayout root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#1a1a2e"));
        root.setPadding(p, p, p, dp(ctx, 24));
        scroll.addView(root);

        // ── Header ─────────────────────────────────────────────────────────────
        LinearLayout headerRow = row(ctx);
        TextView appTitle = new TextView(ctx);
        appTitle.setText("Quick Checkout");
        appTitle.setTextColor(Color.WHITE);
        appTitle.setTextSize(17);
        appTitle.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        headerRow.addView(appTitle, stretchParam());
        TextView ver = new TextView(ctx);
        ver.setText("v1.4.0");
        ver.setTextColor(Color.parseColor("#6C63FF"));
        ver.setTextSize(12);
        headerRow.addView(ver);
        root.addView(headerRow, wrapParams(ctx, 0, 4, 0, 14));

        // ── Marche ─────────────────────────────────────────────────────────────
        LinearLayout sectionDomain = section(ctx);
        sectionDomain.addView(sectionTitle(ctx, "Marche Vinted"));
        sectionDomain.addView(hint(ctx, "Selectionnez le pays ou vous achetez sur Vinted."));

        final Spinner domainSpinner = new Spinner(ctx);
        ArrayAdapter<String> adapter = new ArrayAdapter<String>(ctx,
            android.R.layout.simple_spinner_dropdown_item, DOMAIN_LABELS);
        domainSpinner.setAdapter(adapter);
        String currentDomain = bridge.getVintedDomain();
        for (int i = 0; i < DOMAINS.length; i++) {
            if (DOMAINS[i].equals(currentDomain)) { domainSpinner.setSelection(i); break; }
        }
        sectionDomain.addView(domainSpinner, wrapParams(ctx, 0, 8, 0, 0));
        root.addView(sectionDomain, wrapParams(ctx, 0, 0, 0, 10));

        // ── Autobuy ────────────────────────────────────────────────────────────
        LinearLayout sectionAutobuy = section(ctx);
        sectionAutobuy.addView(sectionTitle(ctx, "Autobuy"));

        LinearLayout autobuyRow = row(ctx);
        autobuyRow.addView(label(ctx, "Achat automatique complet"), stretchParam());
        final Switch autobuySwitch = new Switch(ctx);
        autobuySwitch.setChecked(bridge.getAutobuy());
        autobuyRow.addView(autobuySwitch);
        sectionAutobuy.addView(autobuyRow, wrapParams(ctx, 0, 6, 0, 4));

        final TextView autobuyWarn = hint(ctx,
            "ATTENTION : En autobuy l'achat est finalise automatiquement :\n" +
            "Acheter -> Livraison -> Payer\n" +
            "Assurez-vous d'avoir adresse et paiement enregistres.");
        autobuyWarn.setTextColor(Color.parseColor("#FFC107"));
        autobuyWarn.setVisibility(autobuySwitch.isChecked() ? View.VISIBLE : View.GONE);
        sectionAutobuy.addView(autobuyWarn, wrapParams(ctx, 0, 0, 0, 0));

        autobuySwitch.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton b, boolean on) {
                autobuyWarn.setVisibility(on ? View.VISIBLE : View.GONE);
            }
        });
        root.addView(sectionAutobuy, wrapParams(ctx, 0, 0, 0, 10));

        // ── Token ──────────────────────────────────────────────────────────────
        LinearLayout sectionToken = section(ctx);
        sectionToken.addView(sectionTitle(ctx, "Token Vinted (optionnel)"));

        final String savedToken = bridge.getToken();

        // Status row
        LinearLayout statusRow = row(ctx);
        final TextView statusDot = new TextView(ctx);
        statusDot.setTextSize(20);
        statusDot.setPadding(0, 0, dp(ctx, 6), 0);
        final TextView statusLbl = new TextView(ctx);
        statusLbl.setTextSize(12);
        if (savedToken.isEmpty()) {
            statusDot.setText("o");
            statusDot.setTextColor(Color.parseColor("#888888"));
            statusLbl.setText("Aucun token — connexion simple");
            statusLbl.setTextColor(Color.parseColor("#888888"));
        } else {
            statusDot.setText("o");
            statusDot.setTextColor(Color.parseColor("#52B788"));
            statusLbl.setText("Token actif — verification activee");
            statusLbl.setTextColor(Color.parseColor("#52B788"));
        }
        statusRow.addView(statusDot);
        statusRow.addView(statusLbl, stretchParam());
        sectionToken.addView(statusRow, wrapParams(ctx, 0, 4, 0, 6));

        sectionToken.addView(hint(ctx,
            "Recupere automatiquement apres connexion Vinted. " +
            "Permet la verification de disponibilite avant achat."));

        LinearLayout tokenRow = row(ctx);
        final EditText tokenField = new EditText(ctx);
        tokenField.setHint("Se connecte automatiquement...");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenField.setTextColor(Color.WHITE);
        tokenField.setHintTextColor(Color.parseColor("#555566"));
        tokenField.setSaveEnabled(false);
        tokenField.setText(savedToken);
        tokenRow.addView(tokenField, stretchParam());

        final TextView eyeBtn = new TextView(ctx);
        eyeBtn.setText("O");
        eyeBtn.setTextSize(18);
        eyeBtn.setPadding(dp(ctx, 8), 0, 0, 0);
        eyeBtn.setTextColor(Color.parseColor("#6C63FF"));
        final boolean[] visible = {false};
        eyeBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                visible[0] = !visible[0];
                tokenField.setInputType(visible[0]
                    ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
                    : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
                tokenField.setSelection(tokenField.getText().length());
            }
        });
        tokenRow.addView(eyeBtn);
        sectionToken.addView(tokenRow, wrapParams(ctx, 0, 8, 0, 4));

        Button fetchTokenBtn = new Button(ctx);
        fetchTokenBtn.setText("Recuperer le token depuis Vinted");
        fetchTokenBtn.setTextColor(Color.WHITE);
        fetchTokenBtn.setBackgroundColor(Color.parseColor("#2D6A4F"));
        sectionToken.addView(fetchTokenBtn, wrapParams(ctx, 0, 4, 0, 4));

        final TextView tokenStatus = hint(ctx, "");
        sectionToken.addView(tokenStatus, wrapParams(ctx, 0, 0, 0, 4));

        fetchTokenBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                activity.extractAndSaveVintedToken(
                    "https://" + DOMAINS[domainSpinner.getSelectedItemPosition()] + "/items");
                String tok = bridge.getToken();
                if (!tok.isEmpty()) {
                    tokenField.setText(tok);
                    tokenStatus.setText("Token recupere avec succes !");
                    tokenStatus.setTextColor(Color.parseColor("#52B788"));
                    statusDot.setText("o");
                    statusDot.setTextColor(Color.parseColor("#52B788"));
                    statusLbl.setText("Token actif — verification activee");
                    statusLbl.setTextColor(Color.parseColor("#52B788"));
                } else {
                    tokenStatus.setText("Pas de token trouve. Connectez-vous d'abord.");
                    tokenStatus.setTextColor(Color.parseColor("#FFC107"));
                }
            }
        });

        final TextView clearTokenBtn = new TextView(ctx);
        clearTokenBtn.setText("Effacer le token");
        clearTokenBtn.setTextColor(Color.parseColor("#FF5555"));
        clearTokenBtn.setTextSize(12);
        clearTokenBtn.setPadding(0, dp(ctx, 4), 0, dp(ctx, 4));
        clearTokenBtn.setVisibility(savedToken.isEmpty() ? View.GONE : View.VISIBLE);
        clearTokenBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                tokenField.setText("");
                clearTokenBtn.setVisibility(View.GONE);
                tokenStatus.setText("");
                statusDot.setText("o");
                statusDot.setTextColor(Color.parseColor("#888888"));
                statusLbl.setText("Aucun token — connexion simple");
                statusLbl.setTextColor(Color.parseColor("#888888"));
            }
        });
        sectionToken.addView(clearTokenBtn, wrapParams(ctx, 0, 0, 0, 0));
        root.addView(sectionToken, wrapParams(ctx, 0, 0, 0, 10));

        // ── Connexion Vinted ───────────────────────────────────────────────────
        LinearLayout sectionLogin = section(ctx);
        sectionLogin.addView(sectionTitle(ctx, "Connexion Vinted"));
        sectionLogin.addView(hint(ctx,
            "L'app utilise votre session Vinted. Connectez-vous pour " +
            "activer la recuperation automatique du token."));

        final Button loginBtn = new Button(ctx);
        loginBtn.setText("Ouvrir Vinted pour se connecter");
        loginBtn.setTextColor(Color.WHITE);
        loginBtn.setBackgroundColor(Color.parseColor("#6C63FF"));
        sectionLogin.addView(loginBtn, wrapParams(ctx, 0, 8, 0, 10));

        // Deconnexion / clear cookies
        sectionLogin.addView(divider(ctx));
        sectionLogin.addView(sectionTitle(ctx, "Deconnexion"));
        sectionLogin.addView(hint(ctx,
            "Efface les cookies de session Vinted (vous deconnecte) " +
            "et supprime le token stocke."));

        final Button logoutBtn = new Button(ctx);
        logoutBtn.setText("Effacer les cookies Vinted");
        logoutBtn.setTextColor(Color.WHITE);
        logoutBtn.setBackgroundColor(Color.parseColor("#8B0000"));
        sectionLogin.addView(logoutBtn, wrapParams(ctx, 0, 8, 0, 0));
        root.addView(sectionLogin, wrapParams(ctx, 0, 0, 0, 0));

        // ── Build dialog ───────────────────────────────────────────────────────
        final AlertDialog dialog = new AlertDialog.Builder(activity)
            .setView(scroll)
            .setPositiveButton("Enregistrer", null)
            .setNegativeButton("Annuler", null)
            .create();

        dialog.show();

        // Style dialog buttons
        android.widget.Button pos = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
        android.widget.Button neg = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
        if (pos != null) pos.setTextColor(Color.parseColor("#6C63FF"));
        if (neg != null) neg.setTextColor(Color.parseColor("#888888"));

        // Wire login button
        loginBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                final String domain = DOMAINS[domainSpinner.getSelectedItemPosition()];
                bridge.setVintedDomain(domain);
                dialog.dismiss();
                activity.webView.post(new Runnable() {
                    @Override
                    public void run() {
                        activity.webView.loadUrl("https://" + domain + "/member/login_form");
                    }
                });
            }
        });

        // Wire logout / clear cookies button
        logoutBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                activity.clearVintedCookies();
                bridge.setToken("");
                tokenField.setText("");
                clearTokenBtn.setVisibility(View.GONE);
                tokenStatus.setText("Cookies et token effaces.");
                tokenStatus.setTextColor(Color.parseColor("#FFC107"));
                statusDot.setText("o");
                statusDot.setTextColor(Color.parseColor("#888888"));
                statusLbl.setText("Aucun token — connexion simple");
                statusLbl.setTextColor(Color.parseColor("#888888"));
                Toast.makeText(activity, "Deconnecte de Vinted", Toast.LENGTH_SHORT).show();
            }
        });

        // Wire save button
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                final String domain  = DOMAINS[domainSpinner.getSelectedItemPosition()];
                final boolean autobuy = autobuySwitch.isChecked();
                final String token    = tokenField.getText().toString().trim();

                bridge.setVintedDomain(domain);
                bridge.setAutobuy(autobuy);
                bridge.setToken(token);

                if (activity.webView != null) {
                    final String js =
                        "if(window.__QCBridge)__QCBridge.storageSet('{\"qc_autobuy\":" +
                        autobuy + "}');";
                    activity.webView.post(new Runnable() {
                        @Override
                        public void run() {
                            activity.webView.evaluateJavascript(js, null);
                        }
                    });
                }

                Toast.makeText(activity, "Reglages enregistres !", Toast.LENGTH_SHORT).show();
                dialog.dismiss();
            }
        });
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private static LinearLayout section(Context ctx) {
        LinearLayout ll = new LinearLayout(ctx);
        ll.setOrientation(LinearLayout.VERTICAL);
        int p = dp(ctx, 14);
        ll.setPadding(p, p, p, p);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#16213e"));
        bg.setCornerRadius(dp(ctx, 12));
        ll.setBackground(bg);
        return ll;
    }

    private static TextView sectionTitle(Context ctx, String text) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(14);
        tv.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        tv.setPadding(0, 0, 0, dp(ctx, 4));
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
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 1);
        lp.setMargins(0, dp(ctx, 10), 0, dp(ctx, 10));
        v.setLayoutParams(lp);
        return v;
    }

    private static LinearLayout row(Context ctx) {
        LinearLayout r = new LinearLayout(ctx);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        return r;
    }

    private static LinearLayout.LayoutParams stretchParam() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private static LinearLayout.LayoutParams wrapParams(Context ctx, int l, int t, int r, int b) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(ctx, t), 0, dp(ctx, b));
        return lp;
    }

    private static int dp(Context ctx, int dp) {
        return Math.round(dp * ctx.getResources().getDisplayMetrics().density);
    }
}
