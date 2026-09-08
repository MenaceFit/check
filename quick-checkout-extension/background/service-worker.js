/**
 * Quick Checkout — Background Service Worker
 *
 * Handles:
 * - Session management
 * - Item verification via Vinted API
 * - Checkout tab orchestration
 * - Metrics tracking
 * - Messages from content scripts & popup
 */

import { sessionManager } from '../utils/session-manager.js';
import { fetchItemDetails, buildBuyNowUrl, detectVintedDomain } from '../utils/vinted-api.js';
import { createLogger } from '../utils/logger.js';
import { STORAGE_KEYS, MAX_LATENCY_ENTRIES, CHECKOUT_TIMEOUT } from '../config/constants.js';

const log = createLogger('SW');

// --- Lifecycle ---

chrome.runtime.onInstalled.addListener(async () => {
  log.info('Extension installed/updated');
  await chrome.storage.local.set({
    [STORAGE_KEYS.ENABLED]: true,
    [STORAGE_KEYS.DEBUG_MODE]: false,
    qc_checkout_count: 0,
    qc_latency_history: [],
    qc_session_status: 'unknown',
  });
  await sessionManager.init();
});

chrome.runtime.onStartup.addListener(async () => {
  log.info('Browser startup — checking session');
  await sessionManager.init();
});

// Periodic session re-check via alarms
chrome.alarms.create('session-check', { periodInMinutes: 5 });
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'session-check') {
    await sessionManager.checkSession();
  }
});

// --- Message Router ---

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handleMessage(msg, sender)
    .then(sendResponse)
    .catch(err => {
      log.error('Message handler error', err.message);
      sendResponse({ ok: false, error: err.message });
    });
  return true; // keep channel open for async response
});

async function handleMessage(msg, sender) {
  switch (msg.type) {

    case 'PING':
      return { ok: true, pong: true };

    case 'GET_STATUS':
      return await getStatus();

    case 'TOGGLE_ENABLED': {
      const r = await chrome.storage.local.get(STORAGE_KEYS.ENABLED);
      const newVal = !r[STORAGE_KEYS.ENABLED];
      await chrome.storage.local.set({ [STORAGE_KEYS.ENABLED]: newVal });
      log.info(`Extension ${newVal ? 'enabled' : 'disabled'}`);
      return { ok: true, enabled: newVal };
    }

    case 'TOGGLE_DEBUG': {
      const r = await chrome.storage.local.get(STORAGE_KEYS.DEBUG_MODE);
      const newVal = !r[STORAGE_KEYS.DEBUG_MODE];
      await chrome.storage.local.set({ [STORAGE_KEYS.DEBUG_MODE]: newVal });
      log.info(`Debug mode ${newVal ? 'ON' : 'OFF'}`);
      return { ok: true, debugMode: newVal };
    }

    case 'SET_VINTED_DOMAIN': {
      await chrome.storage.local.set({ [STORAGE_KEYS.VINTED_DOMAIN]: msg.domain });
      await sessionManager.init();
      return { ok: true };
    }

    case 'CHECK_SESSION':
      await sessionManager.init();
      return { ok: true, status: sessionManager.status };

    case 'STORE_VTOOLS_TOKEN':
      if (!msg.token) return { ok: false, error: 'No token provided' };
      await sessionManager.storeVToolsToken(msg.token);
      return { ok: true, masked: sessionManager.getMaskedToken() };

    case 'CLEAR_VTOOLS_TOKEN':
      sessionManager.clearToken();
      return { ok: true };

    case 'QUICK_CHECKOUT':
      return await initiateQuickCheckout(msg.listing, msg.t0);

    case 'CHECKOUT_METRICS': {
      // Reported by vinted-checkout.js after the buy button is clicked
      log.info('Checkout completed on Vinted', {
        itemId: msg.itemId,
        total_ms: msg.t_clicked - msg.t_start,
        btn_find_ms: msg.t_btnFound - msg.t_pageLoaded,
      });
      await recordLatency({ t0: msg.t_start, t4: msg.t_clicked });
      return { ok: true };
    }

    case 'GET_LOGS': {
      const r = await chrome.storage.local.get('qc_logs');
      return { ok: true, logs: r?.qc_logs ?? [] };
    }

    case 'CLEAR_LOGS':
      await chrome.storage.local.remove('qc_logs');
      return { ok: true };

    default:
      return { ok: false, error: `Unknown message type: ${msg.type}` };
  }
}

// --- Status ---

async function getStatus() {
  const r = await chrome.storage.local.get([
    STORAGE_KEYS.ENABLED,
    STORAGE_KEYS.DEBUG_MODE,
    STORAGE_KEYS.VINTED_DOMAIN,
    'qc_session_status',
    'qc_checkout_count',
    'qc_latency_history',
  ]);

  // Check if autocop is open in any tab
  const autocopTabs = await chrome.tabs.query({ url: '*://*.autocop.app/*' });

  return {
    ok: true,
    enabled: r[STORAGE_KEYS.ENABLED] ?? true,
    debugMode: r[STORAGE_KEYS.DEBUG_MODE] ?? false,
    vintedDomain: r[STORAGE_KEYS.VINTED_DOMAIN] ?? 'www.vinted.fr',
    sessionStatus: r['qc_session_status'] ?? 'unknown',
    autocopDetected: autocopTabs.length > 0,
    checkoutCount: r['qc_checkout_count'] ?? 0,
    latencyHistory: r['qc_latency_history'] ?? [],
    maskedToken: sessionManager.getMaskedToken(),
  };
}

// --- Quick Checkout Core ---

async function initiateQuickCheckout(listing, t0) {
  t0 = t0 || Date.now();
  const metrics = { t0, t1: null, t2: null, t3: null, t4: null };

  log.info('Quick Checkout initiated', {
    id: listing.id,
    title: listing.title?.slice(0, 40),
    price: listing.price,
  });

  // T1 — ID recovered
  const itemId = listing.id;
  if (!itemId) {
    return { ok: false, error: 'MISSING_ID', message: 'ID annonce introuvable' };
  }
  metrics.t1 = Date.now();

  const domain = await detectVintedDomain();

  // T2 — Item verification
  let item;
  try {
    item = await fetchItemDetails(itemId, domain);
    metrics.t2 = Date.now();
  } catch (err) {
    log.warn('Item verification failed', err.message);
    const errorMap = {
      ITEM_NOT_FOUND: { error: 'ITEM_NOT_FOUND', message: '❌ Article déjà vendu ou introuvable' },
      SESSION_EXPIRED: { error: 'SESSION_EXPIRED', message: '🔐 Session Vinted expirée — reconnectez-vous' },
    };
    return { ok: false, ...(errorMap[err.message] ?? { error: err.message, message: `⚠️ Erreur API: ${err.message}` }) };
  }

  // Verify item is still available
  if (!item.canBuy) {
    log.warn('Item not buyable', { id: itemId, status: item.status });
    return { ok: false, error: 'ITEM_UNAVAILABLE', message: '❌ Article indisponible' };
  }

  // Price check against what was shown in the feed
  if (listing.price && item.price) {
    const feedPrice = parseFloat(String(listing.price).replace(',', '.'));
    const apiPrice = parseFloat(String(item.price).replace(',', '.'));
    if (Math.abs(feedPrice - apiPrice) > 0.01) {
      log.warn('Price mismatch', { feed: feedPrice, api: apiPrice });
      return {
        ok: false,
        error: 'PRICE_CHANGED',
        message: `⚠️ Prix modifié : ${feedPrice}€ → ${apiPrice}€`,
        newPrice: apiPrice,
      };
    }
  }

  // T3 — Open checkout tab
  const buyUrl = buildBuyNowUrl(itemId, domain);
  metrics.t3 = Date.now();

  const tab = await openCheckoutTab(buyUrl, itemId, metrics);
  metrics.t4 = Date.now();

  // Record latency
  await recordLatency(metrics);

  const totalMs = metrics.t4 - metrics.t0;
  log.info('Checkout opened', {
    itemId,
    totalMs,
    tabId: tab?.id,
  });

  return {
    ok: true,
    item,
    metrics: {
      t0: metrics.t0,
      t1_id_ms: metrics.t1 - metrics.t0,
      t2_verify_ms: metrics.t2 - metrics.t1,
      t3_navigate_ms: metrics.t3 - metrics.t2,
      t4_total_ms: totalMs,
    },
    tabId: tab?.id,
  };
}

async function openCheckoutTab(url, itemId, metrics) {
  // First check if Vinted is already open in a tab
  const domain = await detectVintedDomain();
  const existing = await chrome.tabs.query({ url: `*://${domain}/*` });

  let tab;
  if (existing.length > 0) {
    // Reuse existing Vinted tab
    tab = existing[0];
    await chrome.tabs.update(tab.id, { url, active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
  } else {
    // Open new tab
    tab = await chrome.tabs.create({ url, active: true });
  }

  // Tell the vinted content script to trigger buy once page loads
  // We set a flag in storage that the content script polls
  await chrome.storage.local.set({
    qc_pending_checkout: {
      itemId,
      tabId: tab.id,
      ts: Date.now(),
      metrics,
    },
  });

  return tab;
}

async function recordLatency(metrics) {
  if (!metrics.t0 || !metrics.t4) return;
  const total = metrics.t4 - metrics.t0;
  if (total <= 0 || total > 60000) return; // sanity guard
  const r = await chrome.storage.local.get(['qc_latency_history', 'qc_checkout_count']);
  const history = r.qc_latency_history ?? [];
  history.push({ ts: Date.now(), ms: total });
  if (history.length > MAX_LATENCY_ENTRIES) history.shift();

  await chrome.storage.local.set({
    qc_latency_history: history,
    qc_checkout_count: (r.qc_checkout_count ?? 0) + 1,
  });
}
