/**
 * Autocop Detector — Content Script
 *
 * Injected into autocop.app.
 *
 * Stratégie (confirmée) : chaque carte du feed contient un lien direct vers Vinted.
 * On part donc du lien, pas des class names d'Autocop (qui peuvent changer).
 *
 * Couches de détection :
 * 1. Scan DOM : trouve les <a href="...vinted..."> et remonte au conteneur carte
 * 2. MutationObserver : re-scanne à chaque nouveau nœud (feed temps réel)
 * 3. Network interception (fetch/XHR) : enrichit les données si l'API répond en JSON
 */

(function () {
  'use strict';

  if (window.__qcAutocopLoaded) return;
  window.__qcAutocopLoaded = true;

  // ---- State ----
  let enabled = true;
  let debugMode = false;
  const processedLinks = new WeakSet(); // clé = l'élément <a> Vinted

  // ---- Logger ----
  function log(...args) {
    if (debugMode) console.debug('[QC:Autocop]', ...args);
  }

  // ---- Extraction ID ----
  function extractVintedId(url) {
    if (!url) return null;
    // /items/1234567
    let m = url.match(/\/items\/(\d+)/);
    if (m) return m[1];
    // /-1234567-slug ou /categorie/1234567-slug
    m = url.match(/[-/](\d{7,})/);
    if (m) return m[1];
    return null;
  }

  function isVintedUrl(url) {
    return url && /vinted\.(fr|be|es|de|it|co\.uk|nl|pl|pt|com)/i.test(url);
  }

  // ---- Cache réseau (optionnel, enrichit les données) ----
  const _origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await _origFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
      if (/items|listings|products|feed|search/i.test(url)) {
        resp.clone().json().then(data => cacheNetworkData(data)).catch(() => {});
      }
    } catch {}
    return resp;
  };

  const _origOpen = window.XMLHttpRequest.prototype.open;
  const _origSend = window.XMLHttpRequest.prototype.send;
  window.XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__qcUrl = url;
    return _origOpen.apply(this, [method, url, ...rest]);
  };
  window.XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', function () {
      try {
        if (/items|listings|products|feed/i.test(this.__qcUrl ?? '')) {
          cacheNetworkData(JSON.parse(this.responseText));
        }
      } catch {}
    });
    return _origSend.apply(this, args);
  };

  function cacheNetworkData(data) {
    const items = data?.items ?? data?.listings ?? data?.products ?? data?.data?.items ?? [];
    if (!Array.isArray(items) || items.length === 0) return;
    window.__qcCache = window.__qcCache || {};
    items.forEach(item => {
      const id = String(item.id ?? item.item_id ?? extractVintedId(item.url ?? '') ?? '');
      if (!id) return;
      window.__qcCache[id] = {
        id,
        title: item.title ?? item.name ?? '',
        price: item.price ?? item.price_numeric ?? '',
        currency: item.currency ?? '€',
        size: item.size_title ?? item.size ?? '',
        brand: item.brand_title ?? item.brand ?? '',
        url: item.url ?? '',
        image: item.photos?.[0]?.url ?? item.photo ?? '',
      };
    });
  }

  // ---- Remontée DOM : du lien vers la carte ----
  /**
   * Partant d'un <a href="...vinted..."> on remonte le DOM jusqu'à trouver
   * un conteneur "carte" raisonnable.
   * Heuristique : on remonte tant que le parent contient peu d'autres liens
   * Vinted et a une taille suffisante (>80px dans les deux sens).
   */
  function findCardContainer(anchor) {
    let el = anchor.parentElement;
    let candidate = anchor;

    for (let depth = 0; depth < 10 && el; depth++) {
      const rect = el.getBoundingClientRect();
      // Dès qu'on a une zone ≥ 80×80, c'est un bon candidat
      if (rect.width >= 80 && rect.height >= 80) {
        candidate = el;
        // On continue à remonter un peu pour trouver la vraie carte
        // mais on s'arrête si le parent contient plusieurs autres liens Vinted
        // (ça voudrait dire qu'on est dans le conteneur de tout le feed)
        const parentVintedLinks = el.parentElement
          ? el.parentElement.querySelectorAll('a[href*="vinted."]').length
          : 0;
        if (parentVintedLinks > 3) break; // on est probablement déjà sur la carte
      }
      el = el.parentElement;
    }

    return candidate;
  }

  // ---- Données de la carte ----
  function buildListing(anchor) {
    const url = anchor.href;
    if (!isVintedUrl(url)) return null;

    const id = extractVintedId(url);
    if (!id) return null;

    // Données enrichies depuis le cache réseau si disponibles
    const cached = window.__qcCache?.[id];

    // Fallback DOM : cherche dans le voisinage de l'anchor
    const card = findCardContainer(anchor);
    const priceEl = card.querySelector(
      '[class*="price" i], [data-testid*="price" i], .price'
    );
    const titleEl = card.querySelector(
      '[class*="title" i], [class*="name" i], [data-testid*="title" i], h2, h3, strong, b'
    );
    const imgEl = card.querySelector('img[src], img[data-src]');

    const rawPrice = priceEl?.textContent?.replace(/[^0-9,.]/g, '').trim() ?? '';

    return {
      id,
      title: cached?.title || titleEl?.textContent?.trim() || 'Article Vinted',
      price: cached?.price || rawPrice || '',
      currency: cached?.currency || '€',
      size: cached?.size || '',
      brand: cached?.brand || '',
      url,
      image: cached?.image || imgEl?.src || imgEl?.dataset?.src || '',
      ts: Date.now(),
    };
  }

  // ---- Injection du bouton ----
  function injectButton(anchor, listing) {
    if (processedLinks.has(anchor)) return;
    processedLinks.add(anchor);

    const card = findCardContainer(anchor);

    const btn = document.createElement('button');
    btn.className = 'qc-checkout-btn';
    btn.innerHTML = '⚡ CHECKOUT';
    btn.title = `Quick Checkout — ${listing.title}${listing.price ? ' · ' + listing.price + listing.currency : ''}`;
    btn.setAttribute('data-qc-id', listing.id);

    // Handler partagé click + touch
    const handleActivate = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!enabled) {
        showFeedback(btn, '⏸ Désactivé', 'warning');
        return;
      }
      triggerCheckout(btn, listing);
    };

    btn.addEventListener('click', handleActivate);

    // Touch : touchend sans swipe = tap (élimine le délai 300ms)
    let touchStartY = 0;
    btn.addEventListener('touchstart', (e) => {
      touchStartY = e.touches[0]?.clientY ?? 0;
    }, { passive: true });
    btn.addEventListener('touchend', (e) => {
      const dy = Math.abs((e.changedTouches[0]?.clientY ?? 0) - touchStartY);
      if (dy < 10) handleActivate(e);
    }, { passive: false });

    // Conteneur positionné sur la carte
    const container = document.createElement('div');
    container.className = 'qc-btn-container';
    container.appendChild(btn);

    if (getComputedStyle(card).position === 'static') {
      card.style.position = 'relative';
    }
    card.appendChild(container);

    log('Button injected', { id: listing.id, title: listing.title, price: listing.price });
  }

  // ---- Déclenchement du checkout ----
  async function triggerCheckout(btn, listing) {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.innerHTML = '⏳…';
    const t0 = Date.now();

    try {
      const resp = await chrome.runtime.sendMessage({
        type: 'QUICK_CHECKOUT',
        listing,
        t0,
      });

      if (resp?.ok) {
        const ms = resp.metrics?.t4_total_ms ?? (Date.now() - t0);
        btn.innerHTML = `✅ ${ms}ms`;
        showFeedback(btn, `✅ Checkout ouvert (${ms}ms)`, 'success');
        setTimeout(() => {
          btn.innerHTML = '⚡ CHECKOUT';
          btn.disabled = false;
        }, 3000);
      } else {
        showFeedback(btn, resp?.message || '❌ Erreur', 'error');
        btn.innerHTML = '⚡ CHECKOUT';
        btn.disabled = false;
      }
    } catch {
      showFeedback(btn, '❌ Extension non disponible', 'error');
      btn.innerHTML = '⚡ CHECKOUT';
      btn.disabled = false;
    }
  }

  function showFeedback(btn, text, type) {
    let fb = btn.closest('.qc-btn-container')?.querySelector('.qc-feedback');
    if (!fb) {
      fb = document.createElement('div');
      fb.className = 'qc-feedback';
      btn.closest('.qc-btn-container')?.appendChild(fb);
    }
    fb.textContent = text;
    fb.className = `qc-feedback qc-feedback--${type}`;
    fb.style.display = 'block';
    clearTimeout(fb.__qcTimer);
    fb.__qcTimer = setTimeout(() => { fb.style.display = 'none'; }, 4000);
  }

  // ---- Scan principal ----
  function scanForVintedLinks() {
    const anchors = document.querySelectorAll('a[href*="vinted."]');
    for (const anchor of anchors) {
      if (processedLinks.has(anchor)) continue;
      const listing = buildListing(anchor);
      if (listing) injectButton(anchor, listing);
    }
  }

  // ---- MutationObserver (feed temps réel) ----
  const observer = new MutationObserver((mutations) => {
    let hasNew = false;
    for (const m of mutations) {
      if (m.addedNodes.length > 0) { hasNew = true; break; }
    }
    if (hasNew) requestAnimationFrame(scanForVintedLinks);
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  // Scan initial + après chargement complet
  scanForVintedLinks();
  document.addEventListener('DOMContentLoaded', scanForVintedLinks);
  window.addEventListener('load', scanForVintedLinks);

  // ---- Sync paramètres ----
  chrome.storage.local.get(['qc_enabled', 'qc_debug_mode'], (r) => {
    enabled = r?.qc_enabled ?? true;
    debugMode = r?.qc_debug_mode ?? false;
  });
  chrome.storage.onChanged.addListener((changes) => {
    if ('qc_enabled' in changes) enabled = changes.qc_enabled.newValue;
    if ('qc_debug_mode' in changes) debugMode = changes.qc_debug_mode.newValue;
  });

  log('Autocop detector ready —', document.querySelectorAll('a[href*="vinted."]').length, 'Vinted links found on load');
})();
