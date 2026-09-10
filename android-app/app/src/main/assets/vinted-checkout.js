/**
 * Vinted Checkout Content Script — v3 (autobuy + Android)
 *
 * Injected into Vinted pages by the extension (and the Android WebView app).
 * Flow:
 *   1. Detect pending checkout (chrome.storage or sessionStorage for ongoing flow)
 *   2. Find & click "Acheter"
 *   3. [autobuy mode] Find & click delivery "Continuer"
 *   4. [autobuy mode] Find & click final "Payer"
 */

(function () {
  'use strict';

  if (window.__qcVintedLoaded) return;
  window.__qcVintedLoaded = true;

  const isMobile = () => window.matchMedia('(pointer: coarse)').matches;

  // ── Buy button selectors (all Vinted versions + locales) ───────────────────
  const BUY_BUTTON_SELECTORS = [
    '[data-testid="buy-now-button"]', '[data-testid="buyNowButton"]',
    '[data-testid="buy_now_button"]', '[data-testid="item-buy-button"]',
    '[data-testid="itemBuyButton"]',  '[data-testid="item-page-buy-button"]',
    '[data-js="buy-now"]', '[data-js="buyNow"]',
    '[data-qa="buy-now"]', '[data-action="buy-now"]', '[data-action="buy_now"]',
    'button[class*="buy-now"]', 'button[class*="buyNow"]', 'button[class*="buy_now"]',
    'a[class*="buy-now"]', 'a[class*="buyNow"]',
    'form[action*="buy"] button[type="submit"]',
    'form[action*="checkout"] button[type="submit"]',
  ];

  const BUY_BUTTON_TEXTS = [
    'acheter', 'buy now', 'buy', 'comprar', 'kaufen', 'acquista',
    'kopen', 'kupić', 'kupic', 'köp nu', 'osta nyt', 'køb nu',
    'kjøp nå', 'cumpara', 'vásárolj', 'koupit', 'купить',
  ];

  // ── Delivery step selectors (after clicking "Acheter") ─────────────────────
  const DELIVERY_SELECTORS = [
    '[data-testid="checkout-next"]',  '[data-testid="checkoutNext"]',
    '[data-testid="continue-button"]', '[data-testid="continueButton"]',
    '[data-testid="delivery-next"]',   '[data-testid="submit-delivery"]',
    '[data-testid="shipping-next"]',   '[data-testid="shippingNext"]',
    'button[class*="continue"]',       'button[class*="next-step"]',
  ];

  const DELIVERY_TEXTS = [
    'continuer', 'continue', 'suivant', 'next', 'weiter',
    'seguir', 'doorgaan', 'dalej', 'avanti', 'pokračovat',
    'videre', 'fortsätt', 'jatka',
  ];

  // ── Payment/confirm selectors (final step) ─────────────────────────────────
  const PAY_SELECTORS = [
    '[data-testid="submit-order"]',    '[data-testid="submitOrder"]',
    '[data-testid="pay-button"]',      '[data-testid="payButton"]',
    '[data-testid="confirm-payment"]', '[data-testid="confirmPayment"]',
    '[data-testid="place-order"]',     '[data-testid="placeOrder"]',
    '[data-testid="checkout-confirm"]','[data-testid="checkoutConfirm"]',
    'button[class*="pay"]',            'button[class*="submit-order"]',
    'button[class*="confirm-payment"]',
    'form[action*="transaction"] button[type="submit"]',
    'form[action*="checkout"] button[type="submit"]',
  ];

  const PAY_TEXTS = [
    'payer', 'confirmer et payer', 'pay', 'confirm and pay',
    'zahlen', 'bestätigen und zahlen', 'pagare', 'betalen en bevestigen',
    'zapłać', 'confirmar y pagar', 'confirmar e pagar',
    'passer la commande', 'valider ma commande', 'place order',
  ];

  // ── Session storage key for cross-navigation autobuy state ─────────────────
  const FLOW_KEY = 'qc_autobuy_flow';

  function getFlow() {
    try { return JSON.parse(sessionStorage.getItem(FLOW_KEY) || 'null'); } catch { return null; }
  }
  function setFlow(s) {
    try {
      if (s) sessionStorage.setItem(FLOW_KEY, JSON.stringify(s));
      else sessionStorage.removeItem(FLOW_KEY);
    } catch {}
  }

  // ── Element helpers ─────────────────────────────────────────────────────────

  function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      s.display !== 'none' && s.visibility !== 'hidden' &&
      s.opacity !== '0' && !el.disabled && !el.getAttribute('aria-disabled');
  }

  function findButton(selectors, texts) {
    for (const sel of selectors) {
      try {
        const el = document.querySelector(sel);
        if (el && isVisible(el)) return el;
      } catch {}
    }
    for (const el of document.querySelectorAll('button, a[role="button"], input[type="submit"]')) {
      const t = (el.textContent || el.value || '').trim().toLowerCase();
      if (texts.some(x => t === x || t.startsWith(x + ' ') || t.startsWith(x + '\n')) && isVisible(el)) {
        return el;
      }
    }
    return null;
  }

  function findBuyButton() { return findButton(BUY_BUTTON_SELECTORS, BUY_BUTTON_TEXTS); }
  function findDeliveryButton() { return findButton(DELIVERY_SELECTORS, DELIVERY_TEXTS); }
  function findPayButton() { return findButton(PAY_SELECTORS, PAY_TEXTS); }

  function waitFor(finder, timeoutMs) {
    return new Promise(resolve => {
      let done = false;
      const finish = b => { if (!done) { done = true; obs.disconnect(); clearTimeout(t); resolve(b); } };
      const obs = new MutationObserver(() => { const b = finder(); if (b) finish(b); });
      obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
      const t = setTimeout(() => finish(finder()), timeoutMs);
      const b = finder(); if (b) finish(b);
    });
  }

  async function tapButton(btn) {
    try { btn.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
    if (isMobile()) await sleep(150);
    btn.click();
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ── Overlay ─────────────────────────────────────────────────────────────────

  function getOrCreateOverlay() {
    let o = document.getElementById('qc-vinted-overlay');
    if (!o) {
      o = document.createElement('div');
      o.id = 'qc-vinted-overlay';
      o.innerHTML = `
        <div id="qc-overlay-inner">
          <span id="qc-overlay-icon"></span>
          <div id="qc-overlay-content">
            <span id="qc-overlay-msg"></span>
            <div id="qc-overlay-metrics"></div>
          </div>
          <button id="qc-overlay-close" aria-label="Fermer">✕</button>
        </div>`;
      document.body.appendChild(o);
      const close = e => { if(e){e.preventDefault();e.stopPropagation();} o.classList.add('qc-hidden'); };
      document.getElementById('qc-overlay-close').addEventListener('click', close);
      document.getElementById('qc-overlay-close').addEventListener('touchend', close, { passive: false });
    }
    return o;
  }

  function showOverlay(state, message, metrics) {
    const o = getOrCreateOverlay();
    const ICON = { loading: '⏳', success: '✅', error: '❌', warning: '⚠️' };
    document.getElementById('qc-overlay-icon').textContent = ICON[state] || '⚡';
    document.getElementById('qc-overlay-msg').textContent = message;
    const m = document.getElementById('qc-overlay-metrics');
    m.innerHTML = metrics ? `<small>ID: ${metrics.id || ''} · ${metrics.ms || ''}ms</small>` : '';
    o.className = `qc-overlay qc-overlay--${state}`;
    o.classList.remove('qc-hidden');
    if (state === 'success' || state === 'error') setTimeout(() => o.classList.add('qc-hidden'), 6000);
  }

  // ── Metrics reporting ────────────────────────────────────────────────────────

  async function reportMetrics(itemId, t_pageLoaded, t_btnFound, t_clicked, t_start) {
    try {
      await chrome.runtime.sendMessage({
        type: 'CHECKOUT_METRICS',
        itemId, t_pageLoaded, t_btnFound, t_clicked, t_start,
      });
    } catch { /* non-fatal — SW may be sleeping */ }
  }

  // ── Checkout flow ────────────────────────────────────────────────────────────

  async function runCheckoutFlow(itemId, t_start, autobuy) {
    const TO = isMobile() ? 10000 : 6000;
    const t_pageLoaded = Date.now();

    // ── Step 1: find & click "Acheter" ────────────────────────────────────────
    showOverlay('loading', "Recherche du bouton d'achat…");
    const buyBtn = await waitFor(findBuyButton, TO);

    if (!buyBtn) {
      setFlow(null);
      showOverlay('warning', "⚠️ Bouton d'achat introuvable — cliquez manuellement");
      return;
    }

    const t_btnFound = Date.now();

    if (autobuy) {
      // Store flow state BEFORE clicking (SPA may navigate away)
      setFlow({ step: 'delivery', itemId, t0: t_start });
    }

    await tapButton(buyBtn);
    const t_clicked = Date.now();

    await reportMetrics(itemId, t_pageLoaded, t_btnFound, t_clicked, t_start);

    if (!autobuy) {
      const ms = t_clicked - t_start;
      showOverlay('success', `✅ Checkout lancé (${ms}ms)`, { id: itemId, ms });
      return;
    }

    // ── Step 2 (autobuy): delivery "Continuer" ────────────────────────────────
    showOverlay('loading', '📦 Sélection de la livraison…');
    const TO_EXTRA = TO + 4000;
    const deliveryBtn = await waitFor(findDeliveryButton, TO_EXTRA);

    if (!deliveryBtn) {
      setFlow(null);
      showOverlay('warning', '⚠️ Étape livraison — cliquez "Continuer" manuellement');
      return;
    }

    setFlow({ step: 'payment', itemId, t0: t_start });
    await tapButton(deliveryBtn);

    // ── Step 3 (autobuy): payment "Payer" ────────────────────────────────────
    showOverlay('loading', '💳 Confirmation du paiement…');
    const payBtn = await waitFor(findPayButton, TO_EXTRA);

    if (!payBtn) {
      setFlow(null);
      showOverlay('warning', '⚠️ Étape paiement — cliquez "Payer" manuellement');
      return;
    }

    setFlow(null);
    await tapButton(payBtn);

    const totalMs = Date.now() - t_start;
    showOverlay('success', `🎉 Achat confirmé ! (${totalMs}ms)`, { id: itemId, ms: totalMs });
  }

  // ── Continue autobuy after SPA navigation ────────────────────────────────────

  async function continueFlow(flow) {
    const TO = (isMobile() ? 10000 : 6000) + 4000;

    if (flow.step === 'delivery') {
      showOverlay('loading', '📦 Sélection de la livraison…');
      const btn = await waitFor(findDeliveryButton, TO);
      if (!btn) {
        setFlow(null);
        showOverlay('warning', '⚠️ Étape livraison — cliquez "Continuer" manuellement');
        return;
      }
      setFlow({ step: 'payment', itemId: flow.itemId, t0: flow.t0 });
      await tapButton(btn);

      // Now wait for pay step (may or may not require a navigation)
      showOverlay('loading', '💳 Confirmation du paiement…');
      const payBtn = await waitFor(findPayButton, TO);
      if (!payBtn) {
        setFlow(null);
        showOverlay('warning', '⚠️ Étape paiement — cliquez "Payer" manuellement');
        return;
      }
      setFlow(null);
      await tapButton(payBtn);
      const ms = Date.now() - flow.t0;
      showOverlay('success', `🎉 Achat confirmé ! (${ms}ms)`, { id: flow.itemId, ms });

    } else if (flow.step === 'payment') {
      showOverlay('loading', '💳 Confirmation du paiement…');
      const btn = await waitFor(findPayButton, TO);
      if (!btn) {
        setFlow(null);
        showOverlay('warning', '⚠️ Étape paiement — cliquez "Payer" manuellement');
        return;
      }
      setFlow(null);
      await tapButton(btn);
      const ms = Date.now() - flow.t0;
      showOverlay('success', `🎉 Achat confirmé ! (${ms}ms)`, { id: flow.itemId, ms });
    }
  }

  // ── Main entry ───────────────────────────────────────────────────────────────

  async function run() {
    // 1. Continue an ongoing autobuy flow that survived SPA navigation
    const flow = getFlow();
    if (flow?.step) {
      await continueFlow(flow);
      return;
    }

    // 2. New checkout triggered by the extension
    let r;
    try {
      r = await chrome.storage.local.get(['qc_pending_checkout', 'qc_autobuy']);
    } catch { return; }

    const pending = r?.qc_pending_checkout;
    if (!pending?.itemId) return;

    if (Date.now() - (pending.ts || 0) > 30000) {
      await chrome.storage.local.remove('qc_pending_checkout');
      return;
    }
    await chrome.storage.local.remove('qc_pending_checkout');

    if (!window.location.href.includes(pending.itemId)) {
      showOverlay('warning', '⚠️ Page inattendue — vérifiez manuellement');
      return;
    }

    const autobuy = r?.qc_autobuy ?? false;
    const t_start = pending.metrics?.t0 || pending.ts;
    await runCheckoutFlow(pending.itemId, t_start, autobuy);
  }

  // ── SPA navigation detection (debounced 400ms) ───────────────────────────────

  let lastUrl = location.href;
  let navTimer = null;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      clearTimeout(navTimer);
      navTimer = setTimeout(run, 400);
    }
  }).observe(document, { subtree: true, childList: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }

})();
