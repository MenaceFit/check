/**
 * Autocop Detector — Content Script
 *
 * Injected into autocop.app pages.
 *
 * Strategy (multi-layer, in priority order):
 * 1. Network interception — listen to XHR/fetch for listing JSON responses
 * 2. DOM observation — watch for new listing cards appearing (MutationObserver)
 * 3. Link scanning — find all <a> hrefs pointing to Vinted
 *
 * When a listing is detected, a [⚡ CHECKOUT] button is injected into the card.
 */

(function () {
  'use strict';

  // Avoid double-injection
  if (window.__qcAutocopLoaded) return;
  window.__qcAutocopLoaded = true;

  // ---- State ----
  let enabled = true;
  let debugMode = false;
  const processedCards = new WeakSet();

  // ---- Helpers ----

  function log(...args) {
    if (debugMode) console.debug('[QC:Autocop]', ...args);
  }

  function extractVintedIdFromUrl(url) {
    if (!url) return null;
    // /items/1234567
    let m = url.match(/\/items\/(\d+)/);
    if (m) return m[1];
    // /-1234567 or /1234567-slug
    m = url.match(/[-/](\d{7,})/);
    if (m) return m[1];
    return null;
  }

  function isVintedUrl(url) {
    return url && /vinted\.(fr|be|es|de|it|co\.uk|nl|pl|pt|com)/.test(url);
  }

  // ---- Network Interception ----
  // Intercept fetch/XHR to capture listing data before DOM is even built

  const _origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await _origFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
      if (url && /items|listings|products|feed/i.test(url)) {
        const cloned = resp.clone();
        cloned.json().then(data => {
          handleNetworkData(data, url);
        }).catch(() => {});
      }
    } catch {}
    return resp;
  };

  const _origXHR = window.XMLHttpRequest.prototype.open;
  const _origSend = window.XMLHttpRequest.prototype.send;
  window.XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__qcUrl = url;
    return _origXHR.apply(this, [method, url, ...rest]);
  };
  window.XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', function () {
      try {
        if (this.__qcUrl && /items|listings|products|feed/i.test(this.__qcUrl)) {
          const data = JSON.parse(this.responseText);
          handleNetworkData(data, this.__qcUrl);
        }
      } catch {}
    });
    return _origSend.apply(this, args);
  };

  function handleNetworkData(data, sourceUrl) {
    // Try to extract item data from various response shapes
    const items = data?.items ?? data?.listings ?? data?.products ?? data?.data?.items ?? [];
    if (!Array.isArray(items) || items.length === 0) return;
    log(`Network: ${items.length} items from ${sourceUrl}`);
    items.forEach(item => {
      const id = String(item.id ?? item.item_id ?? '');
      const vintedUrl = item.url ?? item.link ?? item.vinted_url ?? '';
      if (!id && !isVintedUrl(vintedUrl)) return;
      window.__qcNetworkListings = window.__qcNetworkListings || {};
      window.__qcNetworkListings[id || extractVintedIdFromUrl(vintedUrl)] = {
        id: id || extractVintedIdFromUrl(vintedUrl),
        title: item.title ?? item.name ?? '',
        price: item.price ?? item.price_numeric ?? '',
        currency: item.currency ?? '€',
        size: item.size ?? item.size_title ?? '',
        brand: item.brand ?? item.brand_title ?? '',
        url: vintedUrl,
        image: item.photo ?? item.image ?? item.photos?.[0] ?? '',
        seller: item.user ?? item.seller ?? '',
        ts: Date.now(),
      };
    });
  }

  // ---- DOM Injection ----

  function buildListing(card) {
    // Try to find a Vinted URL in or near this card
    const anchors = card.querySelectorAll('a[href]');
    let vintedUrl = null;
    let anchor = null;

    for (const a of anchors) {
      if (isVintedUrl(a.href)) {
        vintedUrl = a.href;
        anchor = a;
        break;
      }
    }

    // Also check the card itself
    if (!vintedUrl && card.tagName === 'A' && isVintedUrl(card.href)) {
      vintedUrl = card.href;
      anchor = card;
    }

    if (!vintedUrl) return null;

    const itemId = extractVintedIdFromUrl(vintedUrl);
    if (!itemId) return null;

    // Try to get enriched data from network interception cache
    const cached = window.__qcNetworkListings?.[itemId];

    // Extract from DOM as fallback
    const priceEl = card.querySelector('[class*="price"], [class*="Price"], .price, [data-testid*="price"]');
    const titleEl = card.querySelector('[class*="title"], [class*="Title"], [class*="name"], h2, h3, strong');
    const imgEl = card.querySelector('img');

    return {
      id: itemId,
      title: cached?.title || titleEl?.textContent?.trim() || 'Article Vinted',
      price: cached?.price || priceEl?.textContent?.replace(/[^0-9,.]/g, '')?.trim() || '',
      currency: cached?.currency || '€',
      size: cached?.size || '',
      brand: cached?.brand || '',
      url: vintedUrl,
      image: cached?.image || imgEl?.src || '',
      seller: cached?.seller || '',
      ts: Date.now(),
    };
  }

  function injectButton(card, listing) {
    if (processedCards.has(card)) return;
    processedCards.add(card);

    const btn = document.createElement('button');
    btn.className = 'qc-checkout-btn';
    btn.innerHTML = '⚡ CHECKOUT';
    btn.title = `Quick Checkout — ${listing.title} ${listing.price}${listing.currency}`;
    btn.setAttribute('data-qc-id', listing.id);

    // Prevent card click from firing when button is clicked
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!enabled) {
        showFeedback(btn, '⏸ Désactivé', 'warning');
        return;
      }
      triggerCheckout(btn, listing);
    });

    // Insert at top-right of card
    const container = document.createElement('div');
    container.className = 'qc-btn-container';
    container.appendChild(btn);

    // Try smart insertion
    const cardStyle = getComputedStyle(card);
    if (cardStyle.position === 'static') {
      card.style.position = 'relative';
    }
    card.appendChild(container);

    log('Button injected', { id: listing.id, title: listing.title });
  }

  async function triggerCheckout(btn, listing) {
    btn.disabled = true;
    btn.innerHTML = '⏳ Vérification…';
    const t0 = Date.now();

    try {
      const resp = await chrome.runtime.sendMessage({
        type: 'QUICK_CHECKOUT',
        listing,
        t0,
      });

      if (resp?.ok) {
        const ms = resp.metrics?.t4_total_ms ?? (Date.now() - t0);
        showFeedback(btn, `✅ Checkout (${ms}ms)`, 'success');
        btn.innerHTML = '✅ Ouvert';
        setTimeout(() => {
          btn.innerHTML = '⚡ CHECKOUT';
          btn.disabled = false;
        }, 3000);
      } else {
        showFeedback(btn, resp?.message || '❌ Erreur', 'error');
        btn.innerHTML = '⚡ CHECKOUT';
        btn.disabled = false;
      }
    } catch (err) {
      showFeedback(btn, '❌ Extension non disponible', 'error');
      btn.innerHTML = '⚡ CHECKOUT';
      btn.disabled = false;
    }
  }

  function showFeedback(btn, text, type) {
    let fb = btn.parentElement?.querySelector('.qc-feedback');
    if (!fb) {
      fb = document.createElement('div');
      fb.className = 'qc-feedback';
      btn.parentElement?.appendChild(fb);
    }
    fb.textContent = text;
    fb.className = `qc-feedback qc-feedback--${type}`;
    fb.style.display = 'block';
    clearTimeout(fb.__qcTimer);
    fb.__qcTimer = setTimeout(() => { fb.style.display = 'none'; }, 4000);
  }

  // ---- Card Detection ----

  const CARD_SELECTORS = [
    // Generic Autocop card patterns (update after inspecting DOM)
    '[class*="item"]',
    '[class*="product"]',
    '[class*="listing"]',
    '[class*="card"]',
    '[class*="feed"]',
    '[data-testid*="item"]',
    '[data-testid*="listing"]',
    '[data-testid*="card"]',
    // Direct article / li elements that contain Vinted links
    'article',
    'li',
  ];

  function isValidCard(el) {
    // Must contain at least one Vinted link
    const hasVintedLink = !!el.querySelector('a[href*="vinted."]') ||
      (el.tagName === 'A' && isVintedUrl(el.href));
    // Must have reasonable size (not tiny nav items)
    if (!hasVintedLink) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 80 && rect.height > 80;
  }

  function scanCards() {
    for (const sel of CARD_SELECTORS) {
      const elements = document.querySelectorAll(sel);
      for (const el of elements) {
        if (processedCards.has(el)) continue;
        if (!isValidCard(el)) continue;
        const listing = buildListing(el);
        if (listing) {
          injectButton(el, listing);
        }
      }
    }
  }

  // ---- MutationObserver ----

  const observer = new MutationObserver((mutations) => {
    let shouldScan = false;
    for (const m of mutations) {
      if (m.addedNodes.length > 0) {
        shouldScan = true;
        break;
      }
    }
    if (shouldScan) {
      requestAnimationFrame(scanCards);
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Initial scan
  scanCards();

  // ---- Settings sync ----

  chrome.storage.local.get(['qc_enabled', 'qc_debug_mode'], (r) => {
    enabled = r?.qc_enabled ?? true;
    debugMode = r?.qc_debug_mode ?? false;
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes.qc_enabled) enabled = changes.qc_enabled.newValue;
    if (changes.qc_debug_mode) debugMode = changes.qc_debug_mode.newValue;
  });

  log('Autocop detector loaded on', window.location.href);
})();
