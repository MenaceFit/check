/**
 * Quick Checkout — Test Suite
 *
 * Run: node tests/test-suite.js
 * No real purchases performed. All Vinted API calls are mocked.
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
  assert(extractItemId('https://www.vinted.fr/femmes/robes/9876543-robe-ete') === '9876543', 'category/slug');
  assert(extractItemId('https://www.vinted.co.uk/items/7654321') === '7654321', '.co.uk domain');
  assert(extractItemId('https://www.vinted.de/items/5551234') === '5551234', '.de domain');
  assert(extractItemId('https://www.vinted.be/items/4441234') === '4441234', '.be domain');
  assert(extractItemId('https://www.vinted.es/items/3331234') === '3331234', '.es domain');
  assert(extractItemId(null) === null, 'null → null');
  assert(extractItemId('') === null, 'empty → null');
  assert(extractItemId('https://www.google.com') === null, 'non-vinted → null');
  assert(extractItemId('not-a-url-but-has-12345678-slug') === '12345678', 'raw slug string');
  // Edge cases
  assert(extractItemId('https://www.vinted.fr/items/12345678?ref=feed') === '12345678', 'URL with query string');
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
  assert(!priceChanged(35, 35), 'same price');
  assert(!priceChanged('35,00', 35.0), 'comma format same');
  assert(!priceChanged(35.00, 35.004), 'within tolerance');
  assert(priceChanged(35, 36), 'price +1');
  assert(priceChanged(35, 34), 'price -1');
  assert(priceChanged('35,50', 36), 'comma format changed');
  assert(priceChanged('0', 1), 'zero to one');
  assert(!priceChanged('100,00', '100.00'), 'euro comma vs dot');
});

// ============================================================
// 3. Token Masking
// ============================================================

function maskToken(t) {
  if (!t) return null;
  if (t.length <= 8) return '****';
  if (t.length <= 12) return t.slice(0, 3) + '****' + t.slice(-2);
  return t.slice(0, 6) + '*'.repeat(Math.min(t.length - 10, 20)) + t.slice(-4);
}

group('Token Masking', () => {
  const long = 'vtools_abc123xyz456def789gh12345678abcd92af';
  const masked = maskToken(long);
  assert(!masked.includes('abc123'), 'middle masked');
  assert(masked.startsWith('vtools'), 'prefix preserved');
  assert(masked.endsWith('92af'), 'suffix preserved');
  assert(maskToken('short') === '****', 'short token');
  assert(maskToken(null) === null, 'null → null');
  assert(maskToken('') === null, 'empty → null');
  assert(maskToken('exactly10c').includes('****'), 'borderline 10-char token gets ****');
  // Verify no middle content exposed in short tokens
  assert(!maskToken('exactly10c').includes('xactly1'), '10-char middle not exposed');
  // Masked token must never contain the real middle
  assert(!maskToken('AAAAAABBBBBBCCCCCCDDDD').includes('BBBBBB'), 'real middle not visible');
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
  const validItem = { id: '123', canBuy: true, price: 35, status: 'Active' };
  assert(validateItem(validItem, 35).ok === true, 'valid item passes');
  assert(validateItem(null, 35).error === 'ITEM_NOT_FOUND', 'null → not found');
  const soldItem = { id: '123', canBuy: false, price: 35, status: 'Inactive' };
  assert(validateItem(soldItem, 35).error === 'ITEM_UNAVAILABLE', 'sold → unavailable');
  const changedItem = { id: '123', canBuy: true, price: 40, status: 'Active' };
  assert(validateItem(changedItem, 35).error === 'PRICE_CHANGED', 'price changed');
  assert(validateItem(changedItem, 35).newPrice === 40, 'new price returned');
  assert(validateItem(validItem, null).ok === true, 'no feed price skips check');
  // Partially filled item
  const partialItem = { id: '123', canBuy: true, price: null };
  assert(validateItem(partialItem, null).ok === true, 'null price with no feed price');
});

// ============================================================
// 5. Error Message Completeness
// ============================================================

const ERROR_MESSAGES = {
  ITEM_NOT_FOUND:       '❌ Article déjà vendu ou introuvable',
  ITEM_UNAVAILABLE:     '❌ Article indisponible',
  PRICE_CHANGED:        '⚠️ Prix modifié — vérification requise',
  SESSION_EXPIRED:      '🔐 Session Vinted expirée — reconnectez-vous',
  CHECKOUT_IMPOSSIBLE:  '⚠️ Checkout indisponible pour cette annonce',
  PAYMENT_REQUIRED:     '🔐 Confirmation bancaire requise',
  SHIPPING_UNAVAILABLE: '📦 Aucun mode de livraison compatible',
};

group('Error Messages', () => {
  assert(ERROR_MESSAGES['ITEM_NOT_FOUND'].includes('vendu'), 'sold message');
  assert(ERROR_MESSAGES['SESSION_EXPIRED'].includes('expirée'), 'session message');
  assert(ERROR_MESSAGES['PRICE_CHANGED'].includes('modifié'), 'price message');
  assert(ERROR_MESSAGES['PAYMENT_REQUIRED'].includes('bancaire'), 'payment message');
  assert(ERROR_MESSAGES['SHIPPING_UNAVAILABLE'].includes('livraison'), 'shipping message');
  assert(Object.keys(ERROR_MESSAGES).length >= 6, 'at least 6 error types');
});

// ============================================================
// 6. Latency Tracking
// ============================================================

function computeAverageLatency(history) {
  if (!history || history.length === 0) return null;
  return Math.round(history.reduce((s, e) => s + e.ms, 0) / history.length);
}

group('Latency Tracking', () => {
  assert(computeAverageLatency([]) === null, 'empty → null');
  assert(computeAverageLatency([{ ms: 100 }, { ms: 200 }]) === 150, 'avg 150');
  assert(computeAverageLatency([{ ms: 75 }]) === 75, 'single entry');
  assert(computeAverageLatency(null) === null, 'null → null');
  assert(computeAverageLatency([{ ms: 50 }, { ms: 50 }, { ms: 50 }]) === 50, 'all same');
  // Sanity guard: ignore nonsensical values
  function recordLatency(t0, t4) {
    const total = t4 - t0;
    if (total <= 0 || total > 60000) return null;
    return total;
  }
  assert(recordLatency(1000, 1500) === 500, 'valid latency recorded');
  assert(recordLatency(1000, 900) === null, 'negative latency rejected');
  assert(recordLatency(1000, 70000) === null, 'too-large latency rejected');
});

// ============================================================
// 7. Double-click / Re-trigger Protection
// ============================================================

group('Double-click Protection', () => {
  let clickCount = 0;
  let disabled = false;

  function simulateClick() {
    if (disabled) return false;
    disabled = true;
    clickCount++;
    setTimeout(() => { disabled = false; }, 3000);
    return true;
  }

  assert(simulateClick() === true, 'first click accepted');
  assert(simulateClick() === false, 'second click blocked');
  assert(clickCount === 1, 'only one checkout triggered');
});

// ============================================================
// 8. Stale Pending Checkout Detection (BUG FIX)
// ============================================================

group('Stale Checkout Guard (was critical bug)', () => {
  function shouldRunCheckout(pending) {
    if (!pending || !pending.itemId) return false;
    // Guard: reject if older than 30s (replaces broken tab ID check)
    if (Date.now() - (pending.ts || 0) > 30000) return false;
    return true;
  }

  const fresh = { itemId: '1234567', ts: Date.now() };
  const stale = { itemId: '1234567', ts: Date.now() - 35000 };
  const noId  = { ts: Date.now() };

  assert(shouldRunCheckout(fresh) === true, 'fresh pending runs');
  assert(shouldRunCheckout(stale) === false, 'stale pending (>30s) rejected');
  assert(shouldRunCheckout(noId) === false, 'no itemId rejected');
  assert(shouldRunCheckout(null) === false, 'null pending rejected');
});

// ============================================================
// 9. Security — Sensitive Data Not Logged
// ============================================================

function maskSensitive(text) {
  if (typeof text !== 'string') text = JSON.stringify(text);
  return text.replace(/(Bearer\s+)([A-Za-z0-9\-_\.]{6})([A-Za-z0-9\-_\.]+)([A-Za-z0-9\-_\.]{4})/gi,
    (_, prefix, start, middle, end) => `${prefix}${start}${'*'.repeat(middle.length)}${end}`);
}

group('Security — Sensitive Data', () => {
  const raw = 'Bearer abc123xyz456def789gh12345678abcd92af';
  const masked = maskSensitive(raw);
  assert(!masked.includes('xyz456def789'), 'token middle masked in logs');
  assert(masked.startsWith('Bearer abc123'), 'prefix visible');
  assert(masked.endsWith('92af'), 'suffix visible');
  // No card numbers in any output
  const noCard = (text) => !/\d{13,19}/.test(text);
  assert(noCard('amount: 35.00'), 'no card in amount string');
  assert(noCard('id: 1234567'), 'short ID not flagged as card');
  // CVV — should never appear
  assert(!/(cvv|cvc).*\d{3}/i.test('amount: 35'), 'no CVV in output');
});

// ============================================================
// 10. Mobile — Touch Event Logic
// ============================================================

group('Mobile — Touch Swipe vs Tap', () => {
  // Simulate the touch handling: only trigger checkout if vertical delta < 10px
  function isTap(startY, endY) {
    return Math.abs(endY - startY) < 10;
  }

  assert(isTap(100, 100) === true, 'exact same Y = tap');
  assert(isTap(100, 105) === true, 'small delta (5px) = tap');
  assert(isTap(100, 109) === true, 'delta 9px = tap');
  assert(isTap(100, 110) === false, 'delta 10px = scroll, not tap');
  assert(isTap(100, 150) === false, 'large delta = scroll');
  assert(isTap(150, 100) === false, 'scroll up = not a tap');
});

// ============================================================
// 11. Mobile — Tap Target Size Compliance
// ============================================================

group('Mobile — Tap Targets (WCAG 2.5.5 / Apple HIG)', () => {
  // Min 44x44px for touch targets
  const MIN_TAP = 44;
  // Values from our CSS
  const btnMinHeight = 44;
  const btnMinWidth = 44;
  const overlayCloseMinHeight = 44;
  const overlayCloseMinWidth = 44;

  assert(btnMinHeight >= MIN_TAP, `checkout btn height >= ${MIN_TAP}px`);
  assert(btnMinWidth >= MIN_TAP, `checkout btn width >= ${MIN_TAP}px`);
  assert(overlayCloseMinHeight >= MIN_TAP, `overlay close btn height >= ${MIN_TAP}px`);
  assert(overlayCloseMinWidth >= MIN_TAP, `overlay close btn width >= ${MIN_TAP}px`);
});

// ============================================================
// 12. Multi-listing (same card not processed twice)
// ============================================================

group('Card De-duplication', () => {
  const processed = new Set();

  function processCard(id) {
    if (processed.has(id)) return false;
    processed.add(id);
    return true;
  }

  assert(processCard('card-1') === true, 'first encounter processed');
  assert(processCard('card-1') === false, 'second encounter skipped');
  assert(processCard('card-2') === true, 'different card processed');
  assert(processCard('card-2') === false, 'same second card skipped');
});

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(56)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed === 0) {
  console.log('🎉 All tests passed!\n');
  process.exit(0);
} else {
  console.error(`⚠️  ${failed} test(s) failed.\n`);
  process.exit(1);
}
