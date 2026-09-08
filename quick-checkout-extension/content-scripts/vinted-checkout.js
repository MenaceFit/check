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

  // --- Selectors for Vinted's "Buy Now" button ---
  // These are heuristic — Vinted may change class names.
  // Listed in priority order (most specific first).
  const BUY_BUTTON_SELECTORS = [
    // French
    '[data-testid="buy-now-button"]',
    '[data-testid="buyNowButton"]',
    'button[class*="buy-now"]',
    'button[class*="buyNow"]',
    // Data attributes
    '[data-js="buy-now"]',
    '[data-qa="buy-now"]',
    // Text-based fallbacks (case-insensitive)
    'button',   // filtered by text below
  ];

  const BUY_BUTTON_TEXTS = ['acheter', 'buy now', 'comprar', 'kaufen', 'acquista', 'kopen', 'kupić', 'comprar'];

  function findBuyButton() {
    // Try specific selectors first
    for (const sel of BUY_BUTTON_SELECTORS.slice(0, -1)) {
      const el = document.querySelector(sel);
      if (el && isVisible(el)) return el;
    }
    // Text fallback
    const buttons = document.querySelectorAll('button, a[role="button"]');
    for (const btn of buttons) {
      const text = (btn.textContent || '').trim().toLowerCase();
      if (BUY_BUTTON_TEXTS.some(t => text.startsWith(t)) && isVisible(btn)) {
        return btn;
      }
    }
    return null;
  }

  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden' &&
      style.opacity !== '0' && !el.disabled;
  }

  // --- Overlay UI ---

  function showOverlay(state, message, metrics) {
    let overlay = document.getElementById('qc-vinted-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'qc-vinted-overlay';
      overlay.innerHTML = `
        <div id="qc-overlay-inner">
          <span id="qc-overlay-icon"></span>
          <span id="qc-overlay-msg"></span>
          <div id="qc-overlay-metrics"></div>
          <button id="qc-overlay-close">✕</button>
        </div>
      `;
      document.body.appendChild(overlay);
      document.getElementById('qc-overlay-close').addEventListener('click', () => {
        overlay.classList.add('qc-hidden');
      });
    }

    const icon = { loading: '⏳', success: '✅', error: '❌', warning: '⚠️' };
    document.getElementById('qc-overlay-icon').textContent = icon[state] || '⚡';
    document.getElementById('qc-overlay-msg').textContent = message;

    if (metrics) {
      document.getElementById('qc-overlay-metrics').innerHTML =
        `<small>ID: ${metrics.id || ''} | ${metrics.ms || ''}ms</small>`;
    }

    overlay.className = `qc-overlay qc-overlay--${state}`;
    overlay.classList.remove('qc-hidden');

    if (state === 'success' || state === 'error') {
      setTimeout(() => overlay.classList.add('qc-hidden'), 5000);
    }
  }

  // --- Main Logic ---

  async function run() {
    // Read pending checkout from storage
    const r = await chrome.storage.local.get('qc_pending_checkout');
    const pending = r?.qc_pending_checkout;

    if (!pending || !pending.itemId) return; // No pending checkout
    if (pending.tabId && pending.tabId !== (await getCurrentTabId())) return; // Not our tab

    // Clear the pending flag immediately to avoid re-triggering
    await chrome.storage.local.remove('qc_pending_checkout');

    const t_pageLoaded = Date.now();
    const totalMs = t_pageLoaded - (pending.ts || t_pageLoaded);

    showOverlay('loading', '⏳ Recherche du bouton d\'achat…');

    // Check the URL contains our item ID
    const currentUrl = window.location.href;
    const urlHasId = currentUrl.includes(pending.itemId);
    if (!urlHasId) {
      showOverlay('warning', '⚠️ Page inattendue — vérifiez manuellement');
      return;
    }

    // Wait for the buy button to appear (Vinted is a SPA)
    const btn = await waitForBuyButton(5000);

    if (!btn) {
      showOverlay('warning', '⚠️ Bouton d\'achat introuvable — cliquez manuellement');
      return;
    }

    const t_btnFound = Date.now();
    showOverlay('loading', '⚡ Ouverture du checkout…', { id: pending.itemId, ms: t_btnFound - (pending.ts || t_btnFound) });

    // Click the buy button
    btn.click();

    const t_clicked = Date.now();
    showOverlay('success', `✅ Checkout lancé (${t_clicked - (pending.ts || t_clicked)}ms)`, {
      id: pending.itemId,
      ms: t_clicked - (pending.ts || t_clicked),
    });

    // Report metrics back
    chrome.runtime.sendMessage({
      type: 'CHECKOUT_METRICS',
      itemId: pending.itemId,
      t_pageLoaded,
      t_btnFound,
      t_clicked,
      t_start: pending.ts,
    });
  }

  function waitForBuyButton(timeoutMs) {
    return new Promise((resolve) => {
      const deadline = Date.now() + timeoutMs;

      const check = () => {
        const btn = findBuyButton();
        if (btn) { resolve(btn); return; }
        if (Date.now() > deadline) { resolve(null); return; }
        requestAnimationFrame(check);
      };

      // Also set up a MutationObserver for SPAs
      const obs = new MutationObserver(() => {
        const btn = findBuyButton();
        if (btn) { obs.disconnect(); resolve(btn); }
      });
      obs.observe(document.body, { childList: true, subtree: true });

      setTimeout(() => { obs.disconnect(); resolve(findBuyButton()); }, timeoutMs);
      check();
    });
  }

  async function getCurrentTabId() {
    return new Promise(resolve => {
      chrome.runtime.sendMessage({ type: 'PING' }, () => {
        // We can't directly get our own tab ID from content script without messaging
        // Use a workaround: check storage for the tab ID
        resolve(null); // null = don't filter by tab ID
      });
    });
  }

  // Run when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }

  // Also run on SPA navigation
  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      setTimeout(run, 300);
    }
  }).observe(document, { subtree: true, childList: true });

})();
