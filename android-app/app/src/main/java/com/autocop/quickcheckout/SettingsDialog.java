package com.autocop.quickcheckout;

import android.content.Context;
import android.graphics.Color;
import android.text.InputType;
import android.view.View;
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
        "FR  vinted.fr (France)",  "BE  vinted.be (Belgique)",
        "ES  vinted.es (Espagne)", "DE  vinted.de (Allemagne)",
        "IT  vinted.it (Italie)",  "UK  vinted.co.uk",
        "NL  vinted.nl (Pays-Bas)","PL  vinted.pl (Pologne)",
        "PT  vinted.pt (Portugal)", "INT vinted.com"
    };

    public static void show(final MainActivity activity) {
        final CheckoutBridge bridge = new CheckoutBridge(activity);
        Context ctx = activity;
        int pad = dp(ctx, 20);

        ScrollView scroll = new ScrollView(ctx);
        LinearLayout root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#1a1a2e"));
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        // Domain
        root.addView(sectionTitle(ctx, "Marche Vinted"));
        root.addView(hint(ctx, "Selectionnez le pays ou vous achetez sur Vinted."));

        final Spinner domainSpinner = new Spinner(ctx);
        ArrayAdapter<String> adapter = new ArrayAdapter<String>(ctx,
            android.R.layout.simple_spinner_dropdown_item, DOMAIN_LABELS);
        domainSpinner.setAdapter(adapter);
        String currentDomain = bridge.getVintedDomain();
        for (int i = 0; i < DOMAINS.length; i++) {
            if (DOMAINS[i].equals(currentDomain)) { domainSpinner.setSelection(i); break; }
        }
        root.addView(domainSpinner, wrapParams(ctx, 0, 6, 0, 20));

        // Autobuy
        root.addView(divider(ctx));
        root.addView(sectionTitle(ctx, "Autobuy"));

        LinearLayout autobuyRow = row(ctx);
        TextView autobuyLbl = label(ctx, "Achat automatique complet");
        autobuyRow.addView(autobuyLbl, stretchParam());
        final Switch autobuySwitch = new Switch(ctx);
        autobuySwitch.setChecked(bridge.getAutobuy());
        autobuyRow.addView(autobuySwitch);
        root.addView(autobuyRow, wrapParams(ctx, 0, 8, 0, 4));

        final TextView autobuyWarn = hint(ctx,
            "ATTENTION : En mode autobuy, l'achat est finalise automatiquement :\n" +
            "Acheter -> Livraison Continuer -> Payer\n" +
            "Assurez-vous d'avoir une adresse et un paiement enregistres sur Vinted.");
        autobuyWarn.setTextColor(Color.parseColor("#FFC107"));
        autobuyWarn.setVisibility(autobuySwitch.isChecked() ? View.VISIBLE : View.GONE);
        root.addView(autobuyWarn, wrapParams(ctx, 0, 0, 0, 16));

        autobuySwitch.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton b, boolean on) {
                autobuyWarn.setVisibility(on ? View.VISIBLE : View.GONE);
            }
        });

        // Token
        root.addView(divider(ctx));
        root.addView(sectionTitle(ctx, "Token Vinted"));
        root.addView(hint(ctx,
            "Recupere automatiquement depuis votre session Vinted. " +
            "Connectez-vous d'abord via le bouton ci-dessous, puis revenez ici."));

        LinearLayout tokenRow = row(ctx);
        final EditText tokenField = new EditText(ctx);
        tokenField.setHint("eyJ0eXAiOiJKV1QiLCJhbGciOiJS...");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenField.setTextColor(Color.WHITE);
        tokenField.setHintTextColor(Color.parseColor("#555566"));
        tokenField.setSaveEnabled(false);
        final String savedToken = bridge.getToken();
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
        root.addView(tokenRow, wrapParams(ctx, 0, 8, 0, 4));

        // Auto-fetch token button
        Button fetchTokenBtn = new Button(ctx);
        fetchTokenBtn.setText("Recuperer le token depuis Vinted");
        fetchTokenBtn.setTextColor(Color.WHITE);
        fetchTokenBtn.setBackgroundColor(Color.parseColor("#2D6A4F"));
        root.addView(fetchTokenBtn, wrapParams(ctx, 0, 6, 0, 4));

        final TextView tokenStatus = hint(ctx, "");
        root.addView(tokenStatus, wrapParams(ctx, 0, 0, 0, 8));

        fetchTokenBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                activity.extractAndSaveVintedToken("https://www.vinted.fr/items");
                String tok = bridge.getToken();
                if (!tok.isEmpty()) {
                    tokenField.setText(tok);
                    tokenStatus.setText("Token recupere avec succes !");
                    tokenStatus.setTextColor(Color.parseColor("#52B788"));
                } else {
                    tokenStatus.setText("Pas de token trouve. Connectez-vous d'abord a Vinted.");
                    tokenStatus.setTextColor(Color.parseColor("#FFC107"));
                }
            }
        });

        final TextView clearBtn = new TextView(ctx);
        clearBtn.setText("Effacer le token");
        clearBtn.setTextColor(Color.parseColor("#FF5555"));
        clearBtn.setTextSize(12);
        clearBtn.setPadding(0, dp(ctx, 4), 0, dp(ctx, 4));
        clearBtn.setVisibility(savedToken.isEmpty() ? View.GONE : View.VISIBLE);
        clearBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                tokenField.setText("");
                clearBtn.setVisibility(View.GONE);
                tokenStatus.setText("");
            }
        });
        root.addView(clearBtn, wrapParams(ctx, 0, 0, 0, 16));

        // Vinted login
        root.addView(divider(ctx));
        root.addView(sectionTitle(ctx, "Connexion Vinted"));
        root.addView(hint(ctx,
            "L'app utilise votre session Vinted (cookies). Si vous n'etes pas encore " +
            "connecte(e), appuyez sur le bouton ci-dessous pour ouvrir la page de connexion."));

        Button loginBtn = new Button(ctx);
        loginBtn.setText("Ouvrir Vinted pour se connecter");
        loginBtn.setTextColor(Color.WHITE);
        loginBtn.setBackgroundColor(Color.parseColor("#6C63FF"));
        root.addView(loginBtn, wrapParams(ctx, 0, 8, 0, 4));

        final AlertDialog dialog = new AlertDialog.Builder(activity)
            .setView(scroll)
            .setPositiveButton("Enregistrer", null)
            .setNegativeButton("Annuler", null)
            .create();

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

        dialog.show();

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
