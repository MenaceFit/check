package com.autocop.quickcheckout;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
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
        "FR  vinted.fr (France)",   "BE  vinted.be (Belgique)",
        "ES  vinted.es (Espagne)",  "DE  vinted.de (Allemagne)",
        "IT  vinted.it (Italie)",   "UK  vinted.co.uk",
        "NL  vinted.nl (Pays-Bas)", "PL  vinted.pl (Pologne)",
        "PT  vinted.pt (Portugal)", "INT vinted.com"
    };

    private static final int COL_BG       = 0xFF1a1a2e;
    private static final int COL_CARD     = 0xFF16213e;
    private static final int COL_ACCENT   = 0xFF6C63FF;
    private static final int COL_GREEN    = 0xFF52B788;
    private static final int COL_GREEN2   = 0xFF2D6A4F;
    private static final int COL_YELLOW   = 0xFFFFC107;
    private static final int COL_RED      = 0xFFFF5555;
    private static final int COL_WHITE    = 0xFFFFFFFF;
    private static final int COL_GREY     = 0xFF888888;
    private static final int COL_DIVIDER  = 0xFF333355;

    public static void show(final MainActivity activity) {
        final CheckoutBridge bridge = new CheckoutBridge(activity);
        Context ctx = activity;
        int pad = dp(ctx, 16);

        ScrollView scroll = new ScrollView(ctx);
        LinearLayout root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(COL_BG);
        root.setPadding(pad, pad, pad, dp(ctx, 24));
        scroll.addView(root);

        // ── Header ─────────────────────────────────────────────────────────────
        LinearLayout headerRow = row(ctx);
        TextView appTitle = new TextView(ctx);
        appTitle.setText("Quick Checkout");
        appTitle.setTextColor(COL_WHITE);
        appTitle.setTextSize(18);
        appTitle.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        headerRow.addView(appTitle, stretchParam());

        TextView version = new TextView(ctx);
        version.setText("v1.4.0");
        version.setTextColor(COL_ACCENT);
        version.setTextSize(12);
        headerRow.addView(version);
        root.addView(headerRow, wrapParams(ctx, 0, 4, 0, 16));

        // ── Marche Vinted ──────────────────────────────────────────────────────
        root.addView(card(ctx, buildDomainSection(ctx, bridge)));

        // ── Autobuy ────────────────────────────────────────────────────────────
        root.addView(spacer(ctx, 12));
        root.addView(card(ctx, buildAutobuySection(ctx, bridge)));

        // ── Token ──────────────────────────────────────────────────────────────
        root.addView(spacer(ctx, 12));
        final View[] tokenViews = new View[3]; // [0]=field row, [1]=status, [2]=clearBtn
        root.addView(card(ctx, buildTokenSection(ctx, activity, bridge, tokenViews)));

        final EditText tokenField = (EditText) tokenViews[0];
        final TextView tokenStatus = (TextView) tokenViews[1];
        final TextView clearBtn = (TextView) tokenViews[2];

        // ── Connexion ──────────────────────────────────────────────────────────
        root.addView(spacer(ctx, 12));

        final AlertDialog[] dialogRef = new AlertDialog[1];

        LinearLayout loginCard = buildLoginSection(ctx, activity, bridge, dialogRef);
        root.addView(card(ctx, loginCard));

        // ── Build dialog ───────────────────────────────────────────────────────
        final AlertDialog dialog = new AlertDialog.Builder(activity)
            .setView(scroll)
            .setPositiveButton("Enregistrer", null)
            .setNegativeButton("Annuler", null)
            .create();

        dialogRef[0] = dialog;

        dialog.show();

        // Style buttons
        Button pos = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
        Button neg = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
        if (pos != null) { pos.setTextColor(COL_ACCENT); }
        if (neg != null) { neg.setTextColor(COL_GREY); }

        // Wire up login button (needs dialog reference)
        Button loginBtn = (Button) loginCard.getTag();
        if (loginBtn != null) {
            // get spinner from domain section (stored as tag on root's first card)
            View domainCard = root.getChildAt(1);
            final Spinner domainSpinner = domainCard != null
                ? (Spinner) domainCard.findViewWithTag("domainSpinner") : null;

            loginBtn.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    final String domain = domainSpinner != null
                        ? DOMAINS[domainSpinner.getSelectedItemPosition()]
                        : bridge.getVintedDomain();
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
        }

        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                View domainCard = root.getChildAt(1);
                Spinner domainSpinner = domainCard != null
                    ? (Spinner) domainCard.findViewWithTag("domainSpinner") : null;

                final String domain  = domainSpinner != null
                    ? DOMAINS[domainSpinner.getSelectedItemPosition()]
                    : bridge.getVintedDomain();

                View autobuyCard = root.getChildAt(3);
                Switch autobuySwitch = autobuyCard != null
                    ? (Switch) autobuyCard.findViewWithTag("autobuySwitch") : null;
                final boolean autobuy = autobuySwitch != null
                    ? autobuySwitch.isChecked() : bridge.getAutobuy();

                final String token = tokenField != null
                    ? tokenField.getText().toString().trim() : "";

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

    private static LinearLayout buildDomainSection(Context ctx, CheckoutBridge bridge) {
        LinearLayout ll = new LinearLayout(ctx);
        ll.setOrientation(LinearLayout.VERTICAL);

        ll.addView(sectionTitle(ctx, "Marche Vinted"));
        ll.addView(hint(ctx, "Selectionnez le pays ou vous achetez."));

        final Spinner domainSpinner = new Spinner(ctx);
        domainSpinner.setTag("domainSpinner");
        ArrayAdapter<String> adapter = new ArrayAdapter<String>(ctx,
            android.R.layout.simple_spinner_dropdown_item, DOMAIN_LABELS);
        domainSpinner.setAdapter(adapter);
        String currentDomain = bridge.getVintedDomain();
        for (int i = 0; i < DOMAINS.length; i++) {
            if (DOMAINS[i].equals(currentDomain)) { domainSpinner.setSelection(i); break; }
        }
        ll.addView(domainSpinner, wrapParams(ctx, 0, 8, 0, 0));
        return ll;
    }

    private static LinearLayout buildAutobuySection(Context ctx, CheckoutBridge bridge) {
        LinearLayout ll = new LinearLayout(ctx);
        ll.setOrientation(LinearLayout.VERTICAL);

        ll.addView(sectionTitle(ctx, "Autobuy"));

        LinearLayout autobuyRow = row(ctx);
        TextView autobuyLbl = label(ctx, "Achat automatique complet");
        autobuyRow.addView(autobuyLbl, stretchParam());

        final Switch autobuySwitch = new Switch(ctx);
        autobuySwitch.setTag("autobuySwitch");
        autobuySwitch.setChecked(bridge.getAutobuy());
        autobuyRow.addView(autobuySwitch);
        ll.addView(autobuyRow, wrapParams(ctx, 0, 8, 0, 4));

        final TextView autobuyWarn = hint(ctx,
            "ATTENTION : En mode autobuy, l'achat est finalise automatiquement :\n" +
            "Acheter -> Livraison -> Payer\n" +
            "Assurez-vous d'avoir une adresse et un paiement enregistres sur Vinted.");
        autobuyWarn.setTextColor(COL_YELLOW);
        autobuyWarn.setVisibility(autobuySwitch.isChecked() ? View.VISIBLE : View.GONE);
        ll.addView(autobuyWarn, wrapParams(ctx, 0, 4, 0, 0));

        autobuySwitch.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton b, boolean on) {
                autobuyWarn.setVisibility(on ? View.VISIBLE : View.GONE);
            }
        });

        return ll;
    }

    private static LinearLayout buildTokenSection(Context ctx,
            final MainActivity activity, final CheckoutBridge bridge, final View[] out) {
        LinearLayout ll = new LinearLayout(ctx);
        ll.setOrientation(LinearLayout.VERTICAL);

        ll.addView(sectionTitle(ctx, "Token Vinted (optionnel)"));

        // Token status indicator
        final String savedToken = bridge.getToken();
        LinearLayout statusRow = row(ctx);
        final TextView statusDot = new TextView(ctx);
        statusDot.setTextSize(14);
        statusDot.setPadding(0, 0, dp(ctx, 6), 0);
        final TextView statusLabel = new TextView(ctx);
        statusLabel.setTextSize(12);

        if (savedToken.isEmpty()) {
            statusDot.setText("O");
            statusDot.setTextColor(COL_GREY);
            statusLabel.setText("Aucun token — connexion simple");
            statusLabel.setTextColor(COL_GREY);
        } else {
            statusDot.setText("O");
            statusDot.setTextColor(COL_GREEN);
            statusLabel.setText("Token actif — pre-verification activee");
            statusLabel.setTextColor(COL_GREEN);
        }
        statusRow.addView(statusDot);
        statusRow.addView(statusLabel, stretchParam());
        ll.addView(statusRow, wrapParams(ctx, 0, 4, 0, 8));

        ll.addView(hint(ctx,
            "Le token permet de verifier la disponibilite avant achat. " +
            "Il est recupere automatiquement depuis Vinted."));

        // Token field row
        LinearLayout tokenRow = row(ctx);
        final EditText tokenField = new EditText(ctx);
        tokenField.setHint("Recupere automatiquement depuis Vinted...");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenField.setTextColor(COL_WHITE);
        tokenField.setHintTextColor(COL_GREY);
        tokenField.setSaveEnabled(false);
        tokenField.setText(savedToken);
        tokenRow.addView(tokenField, stretchParam());

        final TextView eyeBtn = new TextView(ctx);
        eyeBtn.setText("O");
        eyeBtn.setTextSize(18);
        eyeBtn.setPadding(dp(ctx, 8), 0, 0, 0);
        eyeBtn.setTextColor(COL_ACCENT);
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
        ll.addView(tokenRow, wrapParams(ctx, 0, 8, 0, 4));

        // Fetch button
        Button fetchTokenBtn = new Button(ctx);
        fetchTokenBtn.setText("Recuperer le token depuis Vinted");
        fetchTokenBtn.setTextColor(COL_WHITE);
        fetchTokenBtn.setBackgroundColor(COL_GREEN2);
        ll.addView(fetchTokenBtn, wrapParams(ctx, 0, 6, 0, 4));

        final TextView tokenStatusTv = hint(ctx, "");
        ll.addView(tokenStatusTv, wrapParams(ctx, 0, 0, 0, 4));

        fetchTokenBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                activity.extractAndSaveVintedToken("https://www.vinted.fr/items");
                String tok = bridge.getToken();
                if (!tok.isEmpty()) {
                    tokenField.setText(tok);
                    tokenStatusTv.setText("Token recupere avec succes !");
                    tokenStatusTv.setTextColor(COL_GREEN);
                    statusDot.setText("O");
                    statusDot.setTextColor(COL_GREEN);
                    statusLabel.setText("Token actif — pre-verification activee");
                    statusLabel.setTextColor(COL_GREEN);
                } else {
                    tokenStatusTv.setText("Pas de token trouve. Connectez-vous d'abord.");
                    tokenStatusTv.setTextColor(COL_YELLOW);
                }
            }
        });

        final TextView clearBtn = new TextView(ctx);
        clearBtn.setText("Effacer le token");
        clearBtn.setTextColor(COL_RED);
        clearBtn.setTextSize(12);
        clearBtn.setPadding(0, dp(ctx, 4), 0, dp(ctx, 4));
        clearBtn.setVisibility(savedToken.isEmpty() ? View.GONE : View.VISIBLE);
        clearBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                tokenField.setText("");
                clearBtn.setVisibility(View.GONE);
                tokenStatusTv.setText("");
                statusDot.setText("O");
                statusDot.setTextColor(COL_GREY);
                statusLabel.setText("Aucun token — connexion simple");
                statusLabel.setTextColor(COL_GREY);
            }
        });
        ll.addView(clearBtn, wrapParams(ctx, 0, 0, 0, 0));

        out[0] = tokenField;
        out[1] = tokenStatusTv;
        out[2] = clearBtn;

        return ll;
    }

    private static LinearLayout buildLoginSection(Context ctx,
            final MainActivity activity, final CheckoutBridge bridge,
            final AlertDialog[] dialogRef) {
        LinearLayout ll = new LinearLayout(ctx);
        ll.setOrientation(LinearLayout.VERTICAL);

        ll.addView(sectionTitle(ctx, "Connexion Vinted"));
        ll.addView(hint(ctx,
            "L'app utilise votre session Vinted (cookies). Connectez-vous " +
            "pour activer la recuperation automatique du token."));

        Button loginBtn = new Button(ctx);
        loginBtn.setText("Ouvrir Vinted pour se connecter");
        loginBtn.setTextColor(COL_WHITE);
        loginBtn.setBackgroundColor(COL_ACCENT);
        ll.addView(loginBtn, wrapParams(ctx, 0, 8, 0, 0));

        // Store loginBtn as tag so caller can wire it up with dialog ref
        ll.setTag(loginBtn);
        return ll;
    }

    // ── Card wrapper ──────────────────────────────────────────────────────────

    private static View card(Context ctx, LinearLayout content) {
        LinearLayout card = new LinearLayout(ctx);
        card.setOrientation(LinearLayout.VERTICAL);
        int p = dp(ctx, 14);
        card.setPadding(p, p, p, p);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(COL_CARD);
        bg.setCornerRadius(dp(ctx, 12));
        card.setBackground(bg);
        // Pass through tag (for spinner lookup)
        if (content.getTag() != null) card.setTag(content.getTag());
        // Move findViewWithTag to work on the card's children
        int childCount = content.getChildCount();
        for (int i = 0; i < childCount; i++) {
            View child = content.getChildAt(i);
            // keep children — will be transferred below
        }
        content.setTag(null);
        // Re-parent: move views from content to card
        while (content.getChildCount() > 0) {
            View child = content.getChildAt(0);
            content.removeViewAt(0);
            card.addView(child);
        }
        // Keep the spinner tag on the card itself
        View spinner = card.findViewWithTag("domainSpinner");
        // (tag stays on the spinner itself)
        return card;
    }

    private static View spacer(Context ctx, int heightDp) {
        View v = new View(ctx);
        v.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(ctx, heightDp)));
        return v;
    }

    // ── Widget helpers ────────────────────────────────────────────────────────

    private static TextView sectionTitle(Context ctx, String text) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(COL_WHITE);
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
        tv.setTextColor(COL_GREY);
        tv.setTextSize(12);
        return tv;
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
