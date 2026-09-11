/**
 * Vinted Checkout Content Script — v4 (turbo autobuy)
 *
 * Injected into Vinted pages by the Android WebView app.
 * Flow:
 *   1. Detect pending checkout (chrome.storage or sessionStorage for ongoing flow)
 *   2. Find & click "Acheter" (polling every 80ms, timeout 8s)
 *   3. [autobuy] Find & click delivery "Continuer"
 *   4. [autobuy] Find & click final "Payer"
 */

(function () {
  'use strict';

  if (window.__qcVintedLoaded) return;
  window.__qcVintedLoaded = true;

  const isMobile = () => window.matchMedia('(pointer: coarse)').matches;

  // ── Buy button selectors ────────────────────────────────────────────────────
  const BUY_BUTTON_SELECTORS = [
    '[data-testid="buy-now-button"]', '[data-testid="buyNowButton"]',
    '[data-testid="buy_now_button"]', '[data-testid="item-buy-button"]',
    '[data-testid="itemBuyButton"]',  '[data-testid="item-page-buy-button"]',
    '[data-testid="item-buy-now"]',   '[data-testid="buy-button"]',
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

  // ── Delivery step selectors ─────────────────────────────────────────────────
  const DELIVERY_SELECTORS = [
    '[data-testid="checkout-next"]',   '[data-testid="checkoutNext"]',
    '[data-testid="continue-button"]', '[data-testid="continueButton"]',
    '[data-testid="delivery-next"]',   '[data-testid="submit-delivery"]',
    '[data-testid="shipping-next"]',   '[data-testid="shippingNext"]',
    '[data-testid="delivery-submit"]', '[data-testid="order-next-step"]',
    'button[class*="continue"]',       'button[class*="next-step"]',
    'button[class*="delivery-next"]',
  ];

  const DELIVERY_TEXTS = [
    'continuer', 'continue', 'suivant', 'next', 'weiter',
    'seguir', 'doorgaan', 'dalej', 'avanti', 'pokračovat',
    'videre', 'fortsätt', 'jatka', 'valider la livraison',
    'confirmer la livraison',
  ];

  // ── Payment selectors ───────────────────────────────────────────────────────
  const PAY_SELECTORS = [
    '[data-testid="submit-order"]',    '[data-testid="submitOrder"]',
    '[data-testid="pay-button"]',      '[data-testid="payButton"]',
    '[data-testid="confirm-payment"]', '[data-testid="confirmPayment"]',
    '[data-testid="place-order"]',     '[data-testid="placeOrder"]',
    '[data-testid="checkout-confirm"]','[data-testid="checkoutConfirm"]',
    '[data-testid="order-confirm"]',   '[data-testid="payment-submit"]',
    'button[class*="pay"]',            'button[class*="submit-order"]',
    'button[class*="confirm-payment"]','button[class*="place-order"]',
    'form[action*="transaction"] button[type="submit"]',
    'form[action*="checkout"] button[type="submit"]',
    'form[action*="orders"] button[type="submit"]',
  ];

  const PAY_TEXTS = [
    'payer', 'confirmer et payer', 'pay', 'confirm and pay',
    'zahlen', 'bestätigen und zahlen', 'pagare', 'betalen en bevestigen',
    'zapłać', 'confirmar y pagar', 'confirmar e pagar',
    'passer la commande', 'valider ma commande', 'place order',
    'commander', 'finaliser la commande',
  ];

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

  // ── Element helpers ──────────────────────────────────────────────────────────

  function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      s.display !== 'none' && s.visibility !== 'hidden' &&
      s.opacity !== '0' && !el.disabled &&
      !el.getAttribute('aria-disabled') && !el.getAttribute('disabled');
  }

  function findButton(selectors, texts) {
    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (isVisible(el)) return el;
        }
      } catch {}
    }
    const candidates = document.querySelectorAll('button, a[role="button"], input[type="submit"], [role="button"]');
    for (const el of candidates) {
      const t = (el.textContent || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
      if (texts.some(x => t === x || t.startsWith(x + ' ') || t.startsWith(x + '\n') || t.includes(x)) && isVisible(el)) {
        return el;
      }
    }
    return null;
  }

  function findBuyButton() { return findButton(BUY_BUTTON_SELECTORS, BUY_BUTTON_TEXTS); }
  function findDeliveryButton() { return findButton(DELIVERY_SELECTORS, DELIVERY_TEXTS); }
  function findPayButton() { return findButton(PAY_SELECTORS, PAY_TEXTS); }

  // Fast polling with rAF — much faster than MutationObserver alone
  function waitFor(finder, timeoutMs) {
    return new Promise(function(resolve) {
      var done = false;
      var startTime = Date.now();

      function finish(b) {
        if (!done) {
          done = true;
          obs.disconnect();
          resolve(b);
        }
      }

      // Check immediately
      var found = finder();
      if (found) { return resolve(found); }

      // rAF polling — 60fps checks
      function rafPoll() {
        if (done) return;
        var elapsed = Date.now() - startTime;
        if (elapsed >= timeoutMs) { finish(finder()); return; }
        var b = finder();
        if (b) { finish(b); return; }
        requestAnimationFrame(rafPoll);
      }

      // MutationObserver as secondary trigger
      var obs = new MutationObserver(function() {
        var b = finder();
        if (b) finish(b);
      });
      try {
        obs.observe(document.body || document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style', 'disabled'] });
      } catch(e) {}

      requestAnimationFrame(rafPoll);
    });
  }

  async function tapButton(btn) {
    try { btn.scrollIntoView({ behavior: 'instant', block: 'center' }); } catch {}
    // Dispatch pointer events for better compatibility
    try {
      btn.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
      btn.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true }));
    } catch {}
    btn.click();
    // Focus to help React synthetic events
    try { btn.focus(); } catch {}
  }

  function sleep(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }

  // ── Overlay UI ───────────────────────────────────────────────────────────────

  function ensureOverlayStyles() {
    if (document.getElementById('qc-overlay-styles')) return;
    var s = document.createElement('style');
    s.id = 'qc-overlay-styles';
    s.textContent = `
      #qc-vinted-overlay {
        position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
        z-index: 2147483647; min-width: 240px; max-width: 90vw;
        font-family: -apple-system, system-ui, sans-serif; font-size: 14px;
        transition: opacity .25s, transform .25s;
      }
      #qc-vinted-overlay.qc-hidden { opacity: 0; pointer-events: none; transform: translateX(-50%) translateY(-8px); }
      #qc-overlay-inner {
        display: flex; align-items: center; gap: 10px; padding: 10px 14px;
        border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,.35);
        backdrop-filter: blur(8px);
      }
      .qc-overlay--loading  #qc-overlay-inner { background: rgba(40,40,60,.95); border: 1px solid #6C63FF; }
      .qc-overlay--success  #qc-overlay-inner { background: rgba(30,60,40,.95); border: 1px solid #52B788; }
      .qc-overlay--error    #qc-overlay-inner { background: rgba(60,20,20,.95); border: 1px solid #FF5555; }
      .qc-overlay--warning  #qc-overlay-inner { background: rgba(50,40,10,.95); border: 1px solid #FFC107; }
      #qc-overlay-icon { font-size: 20px; flex-shrink: 0; }
      #qc-overlay-content { flex: 1; }
      #qc-overlay-msg { color: #fff; display: block; font-weight: 500; }
      #qc-overlay-metrics { color: rgba(255,255,255,.6); font-size: 11px; margin-top: 2px; }
      #qc-overlay-close {
        background: none; border: none; color: rgba(255,255,255,.5); font-size: 16px;
        cursor: pointer; padding: 0 4px; line-height: 1; flex-shrink: 0;
      }
      #qc-overlay-close:hover { color: #fff; }
      #qc-overlay-progress {
        height: 3px; background: rgba(255,255,255,.15); border-radius: 2px; margin-top: 6px; overflow: hidden;
      }
      #qc-overlay-progress-bar {
        height: 100%; background: #6C63FF; border-radius: 2px; width: 0%;
        transition: width .3s ease;
      }
      .qc-overlay--success #qc-overlay-progress-bar { background: #52B788; }
      .qc-overlay--error   #qc-overlay-progress-bar { background: #FF5555; }
    `;
    (document.head || document.documentElement).appendChild(s);
  }

  function getOrCreateOverlay() {
    ensureOverlayStyles();
    var o = document.getElementById('qc-vinted-overlay');
    if (!o) {
      o = document.createElement('div');
      o.id = 'qc-vinted-overlay';
      o.innerHTML =
        '<div id="qc-overlay-inner">' +
          '<span id="qc-overlay-icon"></span>' +
          '<div id="qc-overlay-content">' +
            '<span id="qc-overlay-msg"></span>' +
            '<div id="qc-overlay-metrics"></div>' +
            '<div id="qc-overlay-progress"><div id="qc-overlay-progress-bar"></div></div>' +
          '</div>' +
          '<button id="qc-overlay-close" aria-label="Fermer">x</button>' +
        '</div>';
      document.body.appendChild(o);
      var closeBtn = document.getElementById('qc-overlay-close');
      function close(e) {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        o.classList.add('qc-hidden');
      }
      closeBtn.addEventListener('click', close);
      closeBtn.addEventListener('touchend', close, { passive: false });
    }
    return o;
  }

  var _progressTimer = null;
  var _progressVal = 0;

  function showOverlay(state, message, metrics, progress) {
    var o = getOrCreateOverlay();
    var ICON = { loading: '...', success: 'OK', error: 'X', warning: '!' };
    var EMOJI = { loading: '⏳', success: '✅', error: '❌', warning: '⚠️' };
    document.getElementById('qc-overlay-icon').textContent = EMOJI[state] || '⚡';
    document.getElementById('qc-overlay-msg').textContent = message;
    var m = document.getElementById('qc-overlay-metrics');
    m.innerHTML = metrics ? '<small>ID: ' + (metrics.id || '') + (metrics.ms ? ' · ' + metrics.ms + 'ms' : '') + '</small>' : '';

    // Progress bar
    var bar = document.getElementById('qc-overlay-progress-bar');
    if (typeof progress === 'number') {
      _progressVal = progress;
      bar.style.width = progress + '%';
    } else if (state === 'loading' && _progressVal < 90) {
      // Animate indeterminate
      clearInterval(_progressTimer);
      _progressVal = 0;
      _progressTimer = setInterval(function() {
        _progressVal = Math.min(_progressVal + 2, 85);
        bar.style.width = _progressVal + '%';
      }, 100);
    } else {
      clearInterval(_progressTimer);
      bar.style.width = state === 'success' ? '100%' : (state === 'error' ? '100%' : '0%');
    }

    o.className = 'qc-overlay qc-overlay--' + state;
    o.classList.remove('qc-hidden');
    if (state === 'success' || state === 'error') {
      setTimeout(function() { o.classList.add('qc-hidden'); clearInterval(_progressTimer); }, 5000);
    }
  }

  // ── Metrics reporting ────────────────────────────────────────────────────────

  async function reportMetrics(itemId, t_pageLoaded, t_btnFound, t_clicked, t_start) {
    try {
      await chrome.runtime.sendMessage({
        type: 'CHECKOUT_METRICS',
        itemId: itemId, t_pageLoaded: t_pageLoaded,
        t_btnFound: t_btnFound, t_clicked: t_clicked, t_start: t_start,
      });
    } catch {}
  }

  // ── Checkout flow ─────────────────────────────────────────────────────────────

  async function runCheckoutFlow(itemId, t_start, autobuy) {
    var TO_BUY = 8000;      // 8s to find buy button
    var TO_STEP = 12000;    // 12s for delivery/payment steps

    var t_pageLoaded = Date.now();

    // Step 1: find & click "Acheter"
    showOverlay('loading', 'Recherche du bouton Acheter...', null, 10);
    var buyBtn = await waitFor(findBuyButton, TO_BUY);

    if (!buyBtn) {
      setFlow(null);
      showOverlay('warning', 'Bouton Acheter introuvable — cliquez manuellement');
      return;
    }

    var t_btnFound = Date.now();
    showOverlay('loading', 'Clic sur Acheter...', null, 30);

    if (autobuy) {
      setFlow({ step: 'delivery', itemId: itemId, t0: t_start });
    }

    await tapButton(buyBtn);
    var t_clicked = Date.now();
    await reportMetrics(itemId, t_pageLoaded, t_btnFound, t_clicked, t_start);

    if (!autobuy) {
      var ms = t_clicked - t_start;
      showOverlay('success', 'Checkout lance (' + ms + 'ms)', { id: itemId, ms: ms }, 100);
      return;
    }

    // Step 2 (autobuy): delivery "Continuer"
    showOverlay('loading', 'Selection de la livraison...', null, 50);
    var deliveryBtn = await waitFor(findDeliveryButton, TO_STEP);

    if (!deliveryBtn) {
      setFlow(null);
      showOverlay('warning', 'Etape livraison — cliquez Continuer manuellement');
      return;
    }

    setFlow({ step: 'payment', itemId: itemId, t0: t_start });
    showOverlay('loading', 'Validation livraison...', null, 65);
    await tapButton(deliveryBtn);

    // Step 3 (autobuy): payment "Payer"
    showOverlay('loading', 'Confirmation du paiement...', null, 80);
    var payBtn = await waitFor(findPayButton, TO_STEP);

    if (!payBtn) {
      setFlow(null);
      showOverlay('warning', 'Etape paiement — cliquez Payer manuellement');
      return;
    }

    setFlow(null);
    showOverlay('loading', 'Paiement en cours...', null, 95);
    await tapButton(payBtn);

    var totalMs = Date.now() - t_start;
    clearInterval(_progressTimer);
    showOverlay('success', 'Achat confirme ! (' + totalMs + 'ms)', { id: itemId, ms: totalMs }, 100);
  }

  // ── Continue autobuy after SPA navigation ────────────────────────────────────

  async function continueFlow(flow) {
    var TO = 12000;

    if (flow.step === 'delivery') {
      showOverlay('loading', 'Selection de la livraison...', null, 50);
      var btn = await waitFor(findDeliveryButton, TO);
      if (!btn) {
        setFlow(null);
        showOverlay('warning', 'Etape livraison — cliquez Continuer manuellement');
        return;
      }
      setFlow({ step: 'payment', itemId: flow.itemId, t0: flow.t0 });
      showOverlay('loading', 'Validation livraison...', null, 65);
      await tapButton(btn);

      showOverlay('loading', 'Confirmation du paiement...', null, 80);
      var payBtn = await waitFor(findPayButton, TO);
      if (!payBtn) {
        setFlow(null);
        showOverlay('warning', 'Etape paiement — cliquez Payer manuellement');
        return;
      }
      setFlow(null);
      showOverlay('loading', 'Paiement en cours...', null, 95);
      await tapButton(payBtn);
      var ms = Date.now() - flow.t0;
      clearInterval(_progressTimer);
      showOverlay('success', 'Achat confirme ! (' + ms + 'ms)', { id: flow.itemId, ms: ms }, 100);

    } else if (flow.step === 'payment') {
      showOverlay('loading', 'Confirmation du paiement...', null, 80);
      var btn2 = await waitFor(findPayButton, TO);
      if (!btn2) {
        setFlow(null);
        showOverlay('warning', 'Etape paiement — cliquez Payer manuellement');
        return;
      }
      setFlow(null);
      showOverlay('loading', 'Paiement en cours...', null, 95);
      await tapButton(btn2);
      var ms2 = Date.now() - flow.t0;
      clearInterval(_progressTimer);
      showOverlay('success', 'Achat confirme ! (' + ms2 + 'ms)', { id: flow.itemId, ms: ms2 }, 100);
    }
  }

  // ── Main entry ───────────────────────────────────────────────────────────────

  async function run() {
    // 1. Continue ongoing autobuy flow after SPA navigation
    var flow = getFlow();
    if (flow && flow.step) {
      await continueFlow(flow);
      return;
    }

    // 2. New checkout triggered by the app
    var r;
    try {
      r = await chrome.storage.local.get(['qc_pending_checkout', 'qc_autobuy']);
    } catch { return; }

    var pending = r && r.qc_pending_checkout;
    if (!pending || !pending.itemId) return;

    if (Date.now() - (pending.ts || 0) > 30000) {
      await chrome.storage.local.remove('qc_pending_checkout');
      return;
    }
    await chrome.storage.local.remove('qc_pending_checkout');

    if (!window.location.href.includes(pending.itemId)) {
      showOverlay('warning', 'Page inattendue — verifiez manuellement');
      return;
    }

    var autobuy = r && r.qc_autobuy === true;
    var t_start = (pending.metrics && pending.metrics.t0) || pending.ts;
    await runCheckoutFlow(pending.itemId, t_start, autobuy);
  }

  // ── SPA navigation detection (debounced 100ms — was 400ms) ──────────────────

  var lastUrl = location.href;
  var navTimer = null;
  new MutationObserver(function() {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      clearTimeout(navTimer);
      navTimer = setTimeout(run, 100);
    }
  }).observe(document, { subtree: true, childList: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }

})();
