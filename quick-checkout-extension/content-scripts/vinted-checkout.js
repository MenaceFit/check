/**
 * Vinted Checkout Content Script
 *
 * Injected into Vinted pages. Handles:
 * 1. Auto-clicking the "Acheter" / "Buy Now" button when opened
 *    via Quick Checkout
 * 2. Reporting page load metrics back to the service worker
 * 3. Showing a Quick Checkout overlay status
 */

(function () {
  'use strict';

  if (window.__qcVintedLoaded) return;
  window.__qcVintedLoaded = true;

  // Detect mobile/touch device
  const isMobile = () => window.matchMedia('(pointer: coarse)').matches;

  // --- Selectors for Vinted's "Buy Now" button ---
  // Exhaustive list — covers all locales and past/present Vinted DOM structures.
  // Listed in priority order (most specific first).
  const BUY_BUTTON_SELECTORS = [
    // data-testid (most stable across Vinted versions)
    '[data-testid="buy-now-button"]',
    '[data-testid="buyNowButton"]',
    '[data-testid="buy_now_button"]',
    '[data-testid="item-buy-button"]',
    '[data-testid="itemBuyButton"]',
    '[data-testid="item-page-buy-button"]',
    // data-js / data-qa / data-action attributes
    '[data-js="buy-now"]',
    '[data-js="buyNow"]',
    '[data-qa="buy-now"]',
    '[data-action="buy-now"]',
    '[data-action="buy_now"]',
    // Class-based heuristics
    'button[class*="buy-now"]',
    'button[class*="buyNow"]',
    'button[class*="buy_now"]',
    'a[class*="buy-now"]',
    'a[class*="buyNow"]',
    // Form submit on item pages
    'form[action*="buy"] button[type="submit"]',
    'form[action*="checkout"] button[type="submit"]',
    // Catch-all: buttons (filtered by text below)
    'button',
    'a[role="button"]',
  ];

  const BUY_BUTTON_TEXTS = [
    'acheter',         // FR / BE
    'buy now',         // EN
    'buy',             // EN short
    'comprar',         // ES / PT
    'kaufen',          // DE
    'acquista',        // IT
    'kopen',           // NL / BE
    'kupić',           // PL
    'kupic',           // PL (no diacritic)
    'köp nu',          // SE
    'osta nyt',        // FI
    'køb nu',          // DK
    'kjøp nå',         // NO
    'cumpara',         // RO
    'vásárolj',        // HU
    'koupit',          // CZ
    'купить',          // RU
  ];

  function findBuyButton() {
    // Try specific selectors first (all but the last two catch-alls)
    for (const sel of BUY_BUTTON_SELECTORS.slice(0, -2)) {
      try {
        const el = document.querySelector(sel);
        if (el && isVisible(el)) return el;
      } catch { /* invalid selector — skip */ }
    }
    // Text fallback: scan all buttons and role=button anchors
    const candidates = document.querySelectorAll('button, a[role="button"]');
    for (const btn of candidates) {
      const text = (btn.textContent || '').trim().toLowerCase();
      if (BUY_BUTTON_TEXTS.some(t => text.startsWith(t) || text === t) && isVisible(btn)) {
        return btn;
      }
    }
    return null;
  }

  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return (
      rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.opacity !== '0' &&
      !el.disabled &&
      !el.getAttribute('aria-disabled')
    );
  }

  // --- Overlay UI ---

  function getOrCreateOverlay() {
    let overlay = document.getElementById('qc-vinted-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'qc-vinted-overlay';
      overlay.innerHTML = `
        <div id="qc-overlay-inner">
          <span id="qc-overlay-icon"></span>
          <div id="qc-overlay-content">
            <span id="qc-overlay-msg"></span>
            <div id="qc-overlay-metrics"></div>
          </div>
          <button id="qc-overlay-close" aria-label="Fermer">✕</button>
        </div>
      `;
      document.body.appendChild(overlay);

      const closeBtn = document.getElementById('qc-overlay-close');

      const closeOverlay = (e) => {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        overlay.classList.add('qc-hidden');
      };

      closeBtn.addEventListener('click', closeOverlay);
      closeBtn.addEventListener('touchend', closeOverlay, { passive: false });
    }
    return overlay;
  }

  function showOverlay(state, message, metrics) {
    const overlay = getOrCreateOverlay();
    const icon = { loading: '⏳', success: '✅', error: '❌', warning: '⚠️' };
    document.getElementById('qc-overlay-icon').textContent = icon[state] || '⚡';
    document.getElementById('qc-overlay-msg').textContent = message;

    const metricsEl = document.getElementById('qc-overlay-metrics');
    if (metrics) {
      metricsEl.innerHTML = `<small>ID: ${metrics.id || ''} · ${metrics.ms || ''}ms</small>`;
    } else {
      metricsEl.innerHTML = '';
    }

    overlay.className = `qc-overlay qc-overlay--${state}`;
    overlay.classList.remove('qc-hidden');

    if (state === 'success' || state === 'error') {
      setTimeout(() => overlay.classList.add('qc-hidden'), 6000);
    }
  }

  // --- Wait for buy button (dual strategy: rAF + MutationObserver) ---

  function waitForBuyButton(timeoutMs) {
    return new Promise((resolve) => {
      let resolved = false;

      const done = (btn) => {
        if (resolved) return;
        resolved = true;
        obs.disconnect();
        clearTimeout(timer);
        resolve(btn);
      };

      // rAF polling
      const check = () => {
        if (resolved) return;
        const btn = findBuyButton();
        if (btn) { done(btn); return; }
        if (Date.now() < deadline) requestAnimationFrame(check);
      };

      // MutationObserver (SPA DOM updates)
      const obs = new MutationObserver(() => {
        const btn = findBuyButton();
        if (btn) done(btn);
      });
      obs.observe(document.body || document.documentElement, { childList: true, subtree: true });

      const deadline = Date.now() + timeoutMs;
      const timer = setTimeout(() => done(findBuyButton()), timeoutMs);
      check();
    });
  }

  // --- Main Logic ---

  async function run() {
    let r;
    try {
      r = await chrome.storage.local.get('qc_pending_checkout');
    } catch {
      return; // Extension context invalidated (e.g. extension reloaded)
    }
    const pending = r?.qc_pending_checkout;

    if (!pending || !pending.itemId) return;

    // Reject stale pending (older than 30s)
    if (Date.now() - (pending.ts || 0) > 30000) {
      await chrome.storage.local.remove('qc_pending_checkout');
      return;
    }

    // Clear immediately to prevent re-trigger on navigation
    await chrome.storage.local.remove('qc_pending_checkout');

    const t_pageLoaded = Date.now();

    showOverlay('loading', "Recherche du bouton d'achat…");

    // Verify we're on the right item page
    if (!window.location.href.includes(pending.itemId)) {
      showOverlay('warning', '⚠️ Page inattendue — vérifiez manuellement');
      return;
    }

    // Mobile gets more time since pages load slower on 4G
    const timeout = isMobile() ? 10000 : 6000;
    const btn = await waitForBuyButton(timeout);

    if (!btn) {
      showOverlay('warning', '⚠️ Bouton d\'achat introuvable — cliquez manuellement');
      return;
    }

    const t_btnFound = Date.now();
    const elapsed = t_btnFound - (pending.metrics?.t0 || pending.ts || t_btnFound);
    showOverlay('loading', '⚡ Ouverture du checkout…', { id: pending.itemId, ms: elapsed });

    // Scroll button into view on mobile before clicking
    try { btn.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}

    // Small delay on mobile to let scroll settle before click
    if (isMobile()) {
      await new Promise(res => setTimeout(res, 150));
    }

    btn.click();

    const t_clicked = Date.now();
    const totalElapsed = t_clicked - (pending.metrics?.t0 || pending.ts || t_clicked);

    showOverlay('success', `✅ Checkout lancé (${totalElapsed}ms)`, {
      id: pending.itemId,
      ms: totalElapsed,
    });

    // Report metrics back to service worker
    try {
      await chrome.runtime.sendMessage({
        type: 'CHECKOUT_METRICS',
        itemId: pending.itemId,
        t_pageLoaded,
        t_btnFound,
        t_clicked,
        t_start: pending.metrics?.t0 || pending.ts,
      });
    } catch { /* service worker may be inactive — non-fatal */ }
  }

  // --- SPA navigation detection (debounced) ---

  let lastUrl = location.href;
  let navTimer = null;

  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      clearTimeout(navTimer);
      // Give the SPA 400ms to stabilize before running
      navTimer = setTimeout(run, 400);
    }
  }).observe(document, { subtree: true, childList: true });

  // Run on initial page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }

})();
