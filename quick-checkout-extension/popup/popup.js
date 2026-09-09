/* global chrome */
'use strict';

// ---- DOM refs ----
const $ = id => document.getElementById(id);

const toggleEnabled   = $('toggle-enabled');
const selectDomain    = $('select-domain');
const btnCheckSession = $('btn-check-session');
const btnDebug        = $('btn-debug');
const btnClearLogs    = $('btn-clear-logs');
const debugPanel      = $('debug-panel');
const debugLog        = $('debug-log');
const tokenInput      = $('token-input');
const tokenSave       = $('token-save');
const tokenClear      = $('token-clear');
const tokenStatus     = $('token-status');
const metricsLatency    = $('metrics-latency');
const metricsCount      = $('metrics-count');
const metricsLast       = $('metrics-last');
const lastCheckoutRow   = $('last-checkout-row');

// Status elements
const statusVinted   = $('status-vinted');
const statusSession  = $('status-session');
const statusAutocop  = $('status-autocop');
const statusCheckout = $('status-checkout');

// ---- Status rendering ----

function setStatus(el, state, text) {
  el.className = `status-indicator ${state}`;
  el.querySelector('.status-text').textContent = text;
}

function applyStatus(s) {
  // Vinted: always "supported" — shows link to vinted
  setStatus(statusVinted, 'ok', `🟢 ${s.vintedDomain}`);

  // Session
  if (s.sessionStatus === 'active') {
    setStatus(statusSession, 'ok', '🟢 Active');
  } else if (s.sessionStatus === 'inactive') {
    setStatus(statusSession, 'err', '🔴 Non connecté');
  } else {
    setStatus(statusSession, 'warn', '🟡 Inconnue');
  }

  // Autocop
  if (s.autocopDetected) {
    setStatus(statusAutocop, 'ok', '🟢 Détecté');
  } else {
    setStatus(statusAutocop, 'warn', '🟡 Non ouvert');
  }

  // Checkout ready
  const checkoutReady = s.enabled && s.sessionStatus === 'active';
  if (!s.enabled) {
    setStatus(statusCheckout, 'warn', '⏸ Désactivé');
  } else if (checkoutReady) {
    setStatus(statusCheckout, 'ok', '🟢 Prêt');
  } else {
    setStatus(statusCheckout, 'warn', '🟡 En attente');
  }

  // Toggle
  toggleEnabled.checked = s.enabled ?? true;

  // Domain
  selectDomain.value = s.vintedDomain ?? 'www.vinted.fr';

  // Metrics
  const latencies = s.latencyHistory ?? [];
  if (latencies.length > 0) {
    const avg = Math.round(latencies.reduce((a, b) => a + b.ms, 0) / latencies.length);
    metricsLatency.textContent = `${avg} ms`;
  } else {
    metricsLatency.textContent = '— ms';
  }
  metricsCount.textContent = s.checkoutCount ?? 0;

  // Last checkout
  if (s.lastCheckout) {
    const lc = s.lastCheckout;
    const age = Math.round((Date.now() - lc.ts) / 1000);
    const ageStr = age < 60 ? `${age}s` : `${Math.round(age/60)}min`;
    const label = lc.title
      ? `${lc.title.slice(0, 30)}… · ${lc.totalMs}ms · il y a ${ageStr}`
      : `#${lc.itemId} · ${lc.totalMs}ms · il y a ${ageStr}`;
    metricsLast.textContent = label;
    metricsLast.title = lc.title ?? '';
    lastCheckoutRow.style.display = 'flex';
  } else {
    lastCheckoutRow.style.display = 'none';
  }

  // Token
  if (s.maskedToken) {
    tokenStatus.style.display = 'block';
    tokenStatus.textContent = `Token actif : ${s.maskedToken}`;
    tokenClear.style.display = 'inline-block';
  } else {
    tokenStatus.style.display = 'none';
    tokenClear.style.display = 'none';
  }
}

// ---- Load initial status ----

async function loadStatus() {
  try {
    const s = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
    if (s?.ok) applyStatus(s);
  } catch (e) {
    setStatus(statusVinted, 'err', '❌ Extension error');
    setStatus(statusSession, 'err', '—');
    setStatus(statusAutocop, 'err', '—');
    setStatus(statusCheckout, 'err', '—');
  }
}

// ---- Event Listeners ----

toggleEnabled.addEventListener('change', async () => {
  await chrome.runtime.sendMessage({ type: 'TOGGLE_ENABLED' });
  await loadStatus();
});

selectDomain.addEventListener('change', async () => {
  await chrome.runtime.sendMessage({ type: 'SET_VINTED_DOMAIN', domain: selectDomain.value });
  await loadStatus();
});

btnCheckSession.addEventListener('click', async () => {
  btnCheckSession.disabled = true;
  btnCheckSession.textContent = '⏳ Vérification…';
  await chrome.runtime.sendMessage({ type: 'CHECK_SESSION' });
  await loadStatus();
  btnCheckSession.disabled = false;
  btnCheckSession.textContent = '↺ Vérifier session';
});

// Debug toggle
let debugVisible = false;
btnDebug.addEventListener('click', async () => {
  debugVisible = !debugVisible;
  debugPanel.style.display = debugVisible ? 'block' : 'none';
  btnDebug.textContent = debugVisible ? '✖ Fermer debug' : '🔍 Debug';

  if (debugVisible) {
    await chrome.runtime.sendMessage({ type: 'TOGGLE_DEBUG' });
    await refreshLogs();
  } else {
    await chrome.runtime.sendMessage({ type: 'TOGGLE_DEBUG' });
  }
});

btnClearLogs.addEventListener('click', async () => {
  await chrome.runtime.sendMessage({ type: 'CLEAR_LOGS' });
  debugLog.innerHTML = '<span class="log-info">Logs effacés.</span>';
});

async function refreshLogs() {
  const r = await chrome.runtime.sendMessage({ type: 'GET_LOGS' });
  const logs = r?.logs ?? [];
  if (logs.length === 0) {
    debugLog.innerHTML = '<span class="log-info">Aucun log.</span>';
    return;
  }
  debugLog.innerHTML = logs.slice(-50).map(l => {
    const time = new Date(l.ts).toISOString().slice(11, 23);
    const cls = `log-${l.level}`;
    const data = l.data ? ` ${l.data}` : '';
    return `<span class="${cls}">[${time}][${l.module}] ${l.message}${data}</span>`;
  }).join('\n');
  debugLog.scrollTop = debugLog.scrollHeight;
}

// Token management
tokenSave.addEventListener('click', async () => {
  const raw = tokenInput.value.trim();
  if (!raw) return;
  tokenInput.value = '';
  const r = await chrome.runtime.sendMessage({ type: 'STORE_VTOOLS_TOKEN', token: raw });
  if (r?.ok) {
    tokenStatus.style.display = 'block';
    tokenStatus.textContent = `Token enregistré : ${r.masked}`;
    tokenClear.style.display = 'inline-block';
  }
});

tokenClear.addEventListener('click', async () => {
  await chrome.runtime.sendMessage({ type: 'CLEAR_VTOOLS_TOKEN' });
  tokenStatus.style.display = 'none';
  tokenClear.style.display = 'none';
});

// ---- Init ----

loadStatus();

// Auto-refresh every 10s while popup is open
setInterval(loadStatus, 10000);
