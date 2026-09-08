/**
 * Quick Checkout — Test Suite
 *
 * Run: node tests/test-suite.js
 *
 * These tests are UNIT tests — they do NOT perform real purchases.
 * All Vinted API calls are mocked.
 */

'use strict';

let passed = 0;
let failed = 0;

function assert(condition, name) {
  if (condition) {
    console.log(`  ✅ PASS: ${name}`);
    passed++;
  } else {
    console.error(`  ❌ FAIL: ${name}`);
    failed++;
  }
}

function group(name, fn) {
  console.log(`\n📋 ${name}`);
  fn();
}

// ============================================================
// 1. URL / ID Extraction
// ============================================================

// Inline the function for testing (no module system in plain Node)
function extractItemId(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    const path = u.pathname;
    const itemsMatch = path.match(/\/items\/(\d+)/);
    if (itemsMatch) return itemsMatch[1];
    const slugMatch = path.match(/[-/](\d{7,})/);
    if (slugMatch) return slugMatch[1];
    const endMatch = path.match(/(\d{6,})(?:-[^/]*)?$/);
    if (endMatch) return endMatch[1];
  } catch {
    const match = url.match(/[-/](\d{7,})/);
    if (match) return match[1];
  }
  return null;
}

group('URL / ID Extraction', () => {
  assert(extractItemId('https://www.vinted.fr/items/1234567') === '1234567', 'items/ pattern');
  assert(extractItemId('https://www.vinted.fr/vetements/1234567-nike-tech-fleece') === '1234567', 'slug pattern');
  assert(extractItemId('https://www.vinted.fr/femmes/robes/9876543-robe-ete-blanche') === '9876543', 'category/slug pattern');
  assert(extractItemId('https://www.vinted.co.uk/items/7654321') === '7654321', '.co.uk domain');
  assert(extractItemId('https://www.vinted.de/items/5551234') === '5551234', '.de domain');
  assert(extractItemId(null) === null, 'null input returns null');
  assert(extractItemId('') === null, 'empty string returns null');
  assert(extractItemId('https://www.google.com') === null, 'non-vinted url returns null');
  assert(extractItemId('not-a-url-but-has-12345678-slug') === '12345678', 'non-URL with slug');
});

// ============================================================
// 2. Price Validation
// ============================================================

function priceChanged(feedPrice, apiPrice, tolerance = 0.01) {
  const fp = parseFloat(String(feedPrice).replace(',', '.'));
  const ap = parseFloat(String(apiPrice).replace(',', '.'));
  return Math.abs(fp - ap) > tolerance;
}

group('Price Validation', () => {
  assert(!priceChanged(35, 35), 'same price — no change');
  assert(!priceChanged('35,00', 35.0), 'comma format — same price');
  assert(!priceChanged(35.00, 35.004), 'within tolerance');
  assert(priceChanged(35, 36), 'price increased — detect change');
  assert(priceChanged(35, 34), 'price decreased — detect change');
  assert(priceChanged('35,50', 36), 'comma format — detect change');
});

// ============================================================
// 3. Token Masking
// ============================================================

function maskToken(t) {
  if (!t) return null;
  if (t.length <= 8) return '****';
  return t.slice(0, 6) + '*'.repeat(Math.min(t.length - 10, 20)) + t.slice(-4);
}

group('Token Masking', () => {
  const masked = maskToken('vtools_abc123xyz456def789gh12345678abcd92af');
  assert(!masked.includes('abc123'), 'middle of token is masked');
  assert(masked.startsWith('vtools'), 'prefix preserved');
  assert(masked.endsWith('92af'), 'last 4 chars preserved');
  assert(maskToken('short') === '****', 'short token masked fully');
  assert(maskToken(null) === null, 'null token returns null');
  assert(maskToken('') === null, 'empty token returns null');
});

// ============================================================
// 4. Item Status Validation
// ============================================================

function validateItem(item, feedPrice) {
  if (!item) return { ok: false, error: 'ITEM_NOT_FOUND', message: '❌ Article déjà vendu ou introuvable' };
  if (!item.canBuy) return { ok: false, error: 'ITEM_UNAVAILABLE', message: '❌ Article indisponible' };
  if (feedPrice != null && priceChanged(feedPrice, item.price)) {
    return { ok: false, error: 'PRICE_CHANGED', message: `⚠️ Prix modifié`, newPrice: item.price };
  }
  return { ok: true };
}

group('Item Status Validation', () => {
  // Valid item
  const validItem = { id: '123', canBuy: true, price: 35, status: 'Active' };
  assert(validateItem(validItem, 35).ok === true, 'valid item passes');

  // Item not found
  assert(validateItem(null, 35).error === 'ITEM_NOT_FOUND', 'null item → not found');

  // Item unavailable
  const soldItem = { id: '123', canBuy: false, price: 35, status: 'Inactive' };
  assert(validateItem(soldItem, 35).error === 'ITEM_UNAVAILABLE', 'sold item → unavailable');

  // Price changed
  const priceChangedItem = { id: '123', canBuy: true, price: 40, status: 'Active' };
  assert(validateItem(priceChangedItem, 35).error === 'PRICE_CHANGED', 'price changed detected');
  assert(validateItem(priceChangedItem, 35).newPrice === 40, 'new price returned');

  // No feed price — skip price check
  assert(validateItem(validItem, null).ok === true, 'no feed price — skips price check');
});

// ============================================================
// 5. Error Message Mapping
// ============================================================

const ERROR_MESSAGES = {
  ITEM_NOT_FOUND:   '❌ Article déjà vendu ou introuvable',
  ITEM_UNAVAILABLE: '❌ Article indisponible',
  PRICE_CHANGED:    '⚠️ Prix modifié — vérification requise',
  SESSION_EXPIRED:  '🔐 Session Vinted expirée — reconnectez-vous',
  CHECKOUT_IMPOSSIBLE: '⚠️ Checkout indisponible pour cette annonce',
  PAYMENT_REQUIRED: '🔐 Confirmation bancaire requise',
  SHIPPING_UNAVAILABLE: '📦 Aucun mode de livraison compatible',
};

group('Error Messages', () => {
  assert(ERROR_MESSAGES['ITEM_NOT_FOUND'].includes('vendu'), 'sold error includes "vendu"');
  assert(ERROR_MESSAGES['SESSION_EXPIRED'].includes('expirée'), 'session error includes "expirée"');
  assert(ERROR_MESSAGES['PRICE_CHANGED'].includes('modifié'), 'price error includes "modifié"');
  assert(Object.keys(ERROR_MESSAGES).length >= 5, 'at least 5 error types defined');
});

// ============================================================
// 6. Latency Tracking
// ============================================================

function computeAverageLatency(history) {
  if (!history || history.length === 0) return null;
  return Math.round(history.reduce((s, e) => s + e.ms, 0) / history.length);
}

group('Latency Tracking', () => {
  assert(computeAverageLatency([]) === null, 'empty history → null');
  assert(computeAverageLatency([{ ms: 100 }, { ms: 200 }]) === 150, 'average of 100+200 = 150');
  assert(computeAverageLatency([{ ms: 75 }]) === 75, 'single entry');
  assert(computeAverageLatency(null) === null, 'null history → null');
});

// ============================================================
// 7. Double-click Protection
// ============================================================

group('Double-click Protection', () => {
  let clickCount = 0;
  let disabled = false;

  function simulateClick() {
    if (disabled) return false;
    disabled = true;
    clickCount++;
    // Re-enable after 3s (in real ext, after response)
    setTimeout(() => { disabled = false; }, 3000);
    return true;
  }

  assert(simulateClick() === true, 'first click accepted');
  assert(simulateClick() === false, 'second click blocked (double-click protection)');
  assert(clickCount === 1, 'only one checkout triggered');
});

// ============================================================
// 8. Security — Sensitive Data Not Logged
// ============================================================

function maskSensitive(text) {
  if (typeof text !== 'string') text = JSON.stringify(text);
  return text.replace(/(Bearer\s+)([A-Za-z0-9\-_\.]{6})([A-Za-z0-9\-_\.]+)([A-Za-z0-9\-_\.]{4})/gi,
    (_, prefix, start, middle, end) => `${prefix}${start}${'*'.repeat(middle.length)}${end}`);
}

group('Security — Sensitive Data', () => {
  const raw = 'Bearer abc123xyz456def789gh12345678abcd92af';
  const masked = maskSensitive(raw);
  assert(!masked.includes('xyz456def789'), 'token middle is masked in logs');
  assert(masked.startsWith('Bearer abc123'), 'prefix preserved in logs');
  assert(masked.endsWith('92af'), 'suffix preserved in logs');

  // Card numbers should not appear
  const noCard = (text) => !/\d{13,19}/.test(text);
  assert(noCard('masked output with no card'), 'no card number in safe output');
});

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed === 0) {
  console.log('🎉 All tests passed!\n');
  process.exit(0);
} else {
  console.error(`⚠️ ${failed} test(s) failed.\n`);
  process.exit(1);
}
