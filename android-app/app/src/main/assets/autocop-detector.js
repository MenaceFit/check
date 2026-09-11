/**
 * Autocop Detector — Content Script v2 (turbo)
 *
 * Injected into autocop.app.
 * Scans for Vinted links, injects CHECKOUT buttons.
 * Pre-checks item availability via Vinted API when token available.
 */

(function () {
  'use strict';

  if (window.__qcAutocopLoaded) return;
  window.__qcAutocopLoaded = true;

  var enabled = true;
  var debugMode = false;
  var bearerToken = '';
  var vintedDomain = 'www.vinted.fr';
  const processedLinks = new WeakSet();

  function log() {
    if (!debugMode) return;
    var args = Array.prototype.slice.call(arguments);
    args.unshift('[QC:Autocop]');
    console.debug.apply(console, args);
  }

  // ── Load config from bridge ─────────────────────────────────────────────────

  function loadConfig() {
    try {
      var cfg = JSON.parse(__QCBridge.buildConfig());
      vintedDomain = cfg.domain || 'www.vinted.fr';
    } catch {}
    try {
      chrome.storage.local.get(['qc_enabled', 'qc_debug_mode'], function(r) {
        if (r) {
          enabled = r.qc_enabled !== false;
          debugMode = r.qc_debug_mode === true;
        }
      });
    } catch {}
    // Load token via custom bridge method
    try {
      chrome.storage.local.get(['qc_token'], function(r) {
        if (r && r.qc_token) bearerToken = r.qc_token;
      });
    } catch {}
  }

  loadConfig();

  // ── ID extraction ───────────────────────────────────────────────────────────

  function extractVintedId(url) {
    if (!url) return null;
    var m = url.match(/\/items\/(\d+)/);
    if (m) return m[1];
    m = url.match(/[-/](\d{7,})/);
    if (m) return m[1];
    return null;
  }

  function isVintedUrl(url) {
    return url && /vinted\.(fr|be|es|de|it|co\.uk|nl|pl|pt|com)/i.test(url);
  }

  // ── Network cache ───────────────────────────────────────────────────────────

  const _origFetch = window.fetch;
  window.fetch = async function () {
    var args = arguments;
    var resp = await _origFetch.apply(this, args);
    try {
      var url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
      if (/items|listings|products|feed|search/i.test(url)) {
        resp.clone().json().then(function(data) { cacheNetworkData(data); }).catch(function() {});
      }
    } catch {}
    return resp;
  };

  const _origOpen = window.XMLHttpRequest.prototype.open;
  const _origSend = window.XMLHttpRequest.prototype.send;
  window.XMLHttpRequest.prototype.open = function (method, url) {
    this.__qcUrl = url;
    return _origOpen.apply(this, arguments);
  };
  window.XMLHttpRequest.prototype.send = function () {
    this.addEventListener('load', function () {
      try {
        if (/items|listings|products|feed/i.test(this.__qcUrl || '')) {
          cacheNetworkData(JSON.parse(this.responseText));
        }
      } catch {}
    });
    return _origSend.apply(this, arguments);
  };

  function cacheNetworkData(data) {
    var items = (data && (data.items || data.listings || data.products || (data.data && data.data.items))) || [];
    if (!Array.isArray(items) || items.length === 0) return;
    window.__qcCache = window.__qcCache || {};
    items.forEach(function(item) {
      var id = String((item.id || item.item_id || extractVintedId((item.url || '')) || ''));
      if (!id) return;
      window.__qcCache[id] = {
        id: id,
        title: item.title || item.name || '',
        price: item.price || item.price_numeric || '',
        currency: item.currency || '€',
        size: item.size_title || item.size || '',
        brand: item.brand_title || item.brand || '',
        url: item.url || '',
        image: (item.photos && item.photos[0] && item.photos[0].url) || item.photo || '',
        available: item.can_be_sold !== false && item.is_for_sale !== false,
      };
    });
  }

  // ── Availability check via API (async, non-blocking) ───────────────────────

  var _availCache = {};  // itemId -> { ok: bool, ts: number }

  async function checkAvailability(itemId) {
    if (!bearerToken) return null;
    var now = Date.now();
    if (_availCache[itemId] && now - _availCache[itemId].ts < 30000) {
      return _availCache[itemId].ok;
    }
    try {
      var domain = vintedDomain || 'www.vinted.fr';
      var resp = await _origFetch('https://' + domain + '/api/v2/items/' + itemId, {
        headers: {
          'Authorization': 'Bearer ' + bearerToken,
          'Accept': 'application/json',
        },
        credentials: 'include',
      });
      if (!resp.ok) return null;
      var data = await resp.json();
      var item = (data && (data.item || data.data));
      if (!item) return null;
      var ok = item.can_be_sold !== false && item.is_for_sale !== false && item.status !== 'sold';
      _availCache[itemId] = { ok: ok, ts: now };
      return ok;
    } catch { return null; }
  }

  // ── DOM helpers ─────────────────────────────────────────────────────────────

  function findCardContainer(anchor) {
    var el = anchor.parentElement;
    var candidate = anchor;
    for (var depth = 0; depth < 10 && el; depth++) {
      var rect = el.getBoundingClientRect();
      if (rect.width >= 80 && rect.height >= 80) {
        candidate = el;
        var parentVintedLinks = el.parentElement
          ? el.parentElement.querySelectorAll('a[href*="vinted."]').length : 0;
        if (parentVintedLinks > 3) break;
      }
      el = el.parentElement;
    }
    return candidate;
  }

  function buildListing(anchor) {
    var url = anchor.href;
    if (!isVintedUrl(url)) return null;
    var id = extractVintedId(url);
    if (!id) return null;

    var cached = window.__qcCache && window.__qcCache[id];
    var card = findCardContainer(anchor);
    var priceEl = card.querySelector('[class*="price" i], [data-testid*="price" i], .price');
    var titleEl = card.querySelector('[class*="title" i], [class*="name" i], [data-testid*="title" i], h2, h3, strong, b');
    var imgEl = card.querySelector('img[src], img[data-src]');
    var rawPrice = priceEl ? (priceEl.textContent || '').replace(/[^0-9,.]/g, '').trim() : '';

    return {
      id: id,
      title: (cached && cached.title) || (titleEl && titleEl.textContent && titleEl.textContent.trim()) || 'Article Vinted',
      price: (cached && cached.price) || rawPrice || '',
      currency: (cached && cached.currency) || '€',
      size: (cached && cached.size) || '',
      brand: (cached && cached.brand) || '',
      url: url,
      image: (cached && cached.image) || (imgEl && (imgEl.src || imgEl.dataset.src)) || '',
      ts: Date.now(),
    };
  }

  // ── Button injection ────────────────────────────────────────────────────────

  function injectButton(anchor, listing) {
    if (processedLinks.has(anchor)) return;
    processedLinks.add(anchor);

    var card = findCardContainer(anchor);

    var btn = document.createElement('button');
    btn.className = 'qc-checkout-btn';
    btn.setAttribute('data-qc-id', listing.id);

    var priceStr = listing.price ? ' ' + listing.price + listing.currency : '';
    btn.innerHTML = '<span class="qc-btn-icon">&#x26A1;</span><span class="qc-btn-text">CHECKOUT' + priceStr + '</span>';
    btn.title = 'Quick Checkout — ' + listing.title + priceStr;

    // Check availability asynchronously and update button
    if (bearerToken && listing.id) {
      checkAvailability(listing.id).then(function(ok) {
        if (ok === false) {
          btn.innerHTML = '<span class="qc-btn-icon">&#x274C;</span><span class="qc-btn-text">VENDU</span>';
          btn.classList.add('qc-btn-sold');
          btn.disabled = true;
        } else if (ok === true) {
          btn.classList.add('qc-btn-available');
        }
      });
    }

    var handleActivate = function(e) {
      e.preventDefault();
      e.stopPropagation();
      if (!enabled) {
        showFeedback(btn, 'Desactive', 'warning');
        return;
      }
      if (btn.disabled) return;
      triggerCheckout(btn, listing);
    };

    btn.addEventListener('click', handleActivate);

    var touchStartY = 0;
    btn.addEventListener('touchstart', function(e) {
      touchStartY = (e.touches[0] && e.touches[0].clientY) || 0;
    }, { passive: true });
    btn.addEventListener('touchend', function(e) {
      var dy = Math.abs(((e.changedTouches[0] && e.changedTouches[0].clientY) || 0) - touchStartY);
      if (dy < 10) handleActivate(e);
    }, { passive: false });

    var container = document.createElement('div');
    container.className = 'qc-btn-container';
    container.appendChild(btn);

    if (getComputedStyle(card).position === 'static') {
      card.style.position = 'relative';
    }
    card.appendChild(container);
    log('Button injected', listing.id);
  }

  // ── Checkout trigger ─────────────────────────────────────────────────────────

  async function triggerCheckout(btn, listing) {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.innerHTML = '<span class="qc-btn-icon">&#x23F3;</span><span class="qc-btn-text">...</span>';
    var t0 = Date.now();

    try {
      var resp = await chrome.runtime.sendMessage({
        type: 'QUICK_CHECKOUT',
        listing: listing,
        t0: t0,
      });

      if (resp && resp.ok) {
        var ms = (resp.metrics && resp.metrics.t4_total_ms) || (Date.now() - t0);
        btn.innerHTML = '<span class="qc-btn-icon">&#x2705;</span><span class="qc-btn-text">' + ms + 'ms</span>';
        showFeedback(btn, 'Checkout ouvert (' + ms + 'ms)', 'success');
        setTimeout(function() {
          btn.innerHTML = '<span class="qc-btn-icon">&#x26A1;</span><span class="qc-btn-text">CHECKOUT</span>';
          btn.disabled = false;
        }, 3000);
      } else {
        showFeedback(btn, (resp && resp.message) || 'Erreur', 'error');
        btn.innerHTML = '<span class="qc-btn-icon">&#x26A1;</span><span class="qc-btn-text">CHECKOUT</span>';
        btn.disabled = false;
      }
    } catch {
      showFeedback(btn, 'Extension non disponible', 'error');
      btn.innerHTML = '<span class="qc-btn-icon">&#x26A1;</span><span class="qc-btn-text">CHECKOUT</span>';
      btn.disabled = false;
    }
  }

  function showFeedback(btn, text, type) {
    var container = btn.closest('.qc-btn-container');
    if (!container) return;
    var fb = container.querySelector('.qc-feedback');
    if (!fb) {
      fb = document.createElement('div');
      fb.className = 'qc-feedback';
      container.appendChild(fb);
    }
    fb.textContent = text;
    fb.className = 'qc-feedback qc-feedback--' + type;
    fb.style.display = 'block';
    clearTimeout(fb.__qcTimer);
    fb.__qcTimer = setTimeout(function() { fb.style.display = 'none'; }, 4000);
  }

  // ── Scan ─────────────────────────────────────────────────────────────────────

  function scanForVintedLinks() {
    var anchors = document.querySelectorAll('a[href*="vinted."]');
    for (var i = 0; i < anchors.length; i++) {
      var anchor = anchors[i];
      if (processedLinks.has(anchor)) continue;
      var listing = buildListing(anchor);
      if (listing) injectButton(anchor, listing);
    }
  }

  // ── MutationObserver (real-time feed) ───────────────────────────────────────

  var _scanPending = false;
  var observer = new MutationObserver(function(mutations) {
    var hasNew = false;
    for (var i = 0; i < mutations.length; i++) {
      if (mutations[i].addedNodes.length > 0) { hasNew = true; break; }
    }
    if (hasNew && !_scanPending) {
      _scanPending = true;
      requestAnimationFrame(function() {
        _scanPending = false;
        scanForVintedLinks();
      });
    }
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  // Initial scans
  scanForVintedLinks();
  document.addEventListener('DOMContentLoaded', scanForVintedLinks);
  window.addEventListener('load', scanForVintedLinks);

  // Reload token when storage changes
  chrome.storage.onChanged.addListener(function(changes) {
    if (changes.qc_enabled) enabled = changes.qc_enabled.newValue;
    if (changes.qc_debug_mode) debugMode = changes.qc_debug_mode.newValue;
    if (changes.qc_token) bearerToken = changes.qc_token.newValue || '';
    if (changes.qc_vinted_domain) vintedDomain = changes.qc_vinted_domain.newValue || 'www.vinted.fr';
  });

  log('Autocop detector ready');
})();
