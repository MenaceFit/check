import { VINTED_DOMAINS, VINTED_API_PATH, VINTED_ITEM_ID_REGEX } from '../config/constants.js';
import { createLogger } from './logger.js';

const log = createLogger('VintedAPI');

/**
 * Extracts item ID from any Vinted URL.
 * Vinted URL patterns:
 *   https://www.vinted.fr/vetements/123456-nike-tech-fleece-noir
 *   https://www.vinted.fr/items/123456
 *   https://www.vinted.fr/femmes/robes/123456-robe-ete
 */
export function extractItemId(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    const path = u.pathname;

    // Pattern 1: /items/123456
    const itemsMatch = path.match(/\/items\/(\d+)/);
    if (itemsMatch) return itemsMatch[1];

    // Pattern 2: /something/123456-slug or /something-123456
    // Vinted item IDs are typically 7-10 digits
    const slugMatch = path.match(/[-/](\d{7,})/);
    if (slugMatch) return slugMatch[1];

    // Pattern 3: ends with digits (fallback)
    const endMatch = path.match(/(\d{6,})(?:-[^/]*)?$/);
    if (endMatch) return endMatch[1];
  } catch {
    // Not a URL — try as raw path
    const match = url.match(/[-/](\d{7,})/);
    if (match) return match[1];
  }
  return null;
}

/**
 * Determines if a URL is a Vinted listing URL.
 */
export function isVintedListingUrl(url) {
  if (!url) return false;
  try {
    const hostname = new URL(url).hostname;
    return VINTED_DOMAINS.some(d => hostname.endsWith(d));
  } catch { return false; }
}

/**
 * Detects the Vinted domain from cookies available to the extension
 * or defaults to the user-configured domain.
 */
export async function detectVintedDomain() {
  return new Promise((resolve) => {
    chrome.storage.local.get('qc_vinted_domain', (r) => {
      resolve(r?.qc_vinted_domain || 'www.vinted.fr');
    });
  });
}

/**
 * Checks if the user has an active Vinted session by reading cookies.
 * Returns { authenticated: boolean, userId: string|null }
 */
export async function checkVintedSession(domain) {
  const d = domain || await detectVintedDomain();
  return new Promise((resolve) => {
    chrome.cookies.getAll({ domain: d }, (cookies) => {
      if (chrome.runtime.lastError) {
        log.warn('Cookie access error', chrome.runtime.lastError.message);
        resolve({ authenticated: false, userId: null });
        return;
      }
      // Vinted sets session cookies — look for auth indicators
      // Common cookie names: _vinted_fr_session, access_token, user_id
      const sessionCookie = cookies.find(c =>
        c.name.includes('session') || c.name.includes('access_token') || c.name === 'anon_id'
      );
      const userCookie = cookies.find(c =>
        c.name === 'user_id' || c.name === '_user_id' || c.name.includes('user')
      );

      // A session cookie present means the browser is logged into Vinted
      const authenticated = !!sessionCookie && cookies.length > 3;
      const userId = userCookie?.value ?? null;

      log.debug('Session check', { domain: d, cookieCount: cookies.length, authenticated });
      resolve({ authenticated, userId });
    });
  });
}

/**
 * Fetches item details from Vinted public API.
 * Uses the browser's existing session (cookies sent automatically via fetch in content script).
 * This is called FROM the background service worker using the user's cookies.
 */
export async function fetchItemDetails(itemId, domain) {
  const d = domain || await detectVintedDomain();
  const url = `https://${d}${VINTED_API_PATH}${'/items'}/${itemId}`;

  log.debug('Fetching item details', { itemId, domain: d });
  const t0 = performance.now();

  const resp = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
    },
  });

  const latency = Math.round(performance.now() - t0);
  log.debug('Item fetch response', { status: resp.status, latency });

  if (!resp.ok) {
    if (resp.status === 404) throw new Error('ITEM_NOT_FOUND');
    if (resp.status === 401) throw new Error('SESSION_EXPIRED');
    throw new Error(`API_ERROR_${resp.status}`);
  }

  const data = await resp.json();
  const item = data?.item;
  if (!item) throw new Error('INVALID_RESPONSE');

  return {
    id: String(item.id),
    title: item.title,
    price: item.price_numeric ?? item.price,
    currency: item.currency,
    status: item.status,
    canBuy: item.can_buy ?? (item.status === 'Active'),
    sellerId: item.user?.id,
    sellerLogin: item.user?.login,
    size: item.size_title,
    brand: item.brand_title,
    photos: item.photos?.map(p => p.url) ?? [],
    url: item.url,
    latency,
  };
}

/**
 * Builds the direct Vinted checkout/buy URL for an item.
 * Vinted's "Buy Now" flow navigates to:
 *   https://www.vinted.fr/items/{id}/buy_now  (POST via form, but GET opens item page + triggers buy)
 * The most reliable direct path is to open the item page and let the content script
 * auto-click the buy button.
 */
export function buildBuyNowUrl(itemId, domain) {
  return `https://${domain}/items/${itemId}`;
}

/**
 * Builds the direct checkout URL (if Vinted exposes it).
 * Vinted's checkout is at /checkout after adding to transaction.
 */
export function buildCheckoutUrl(domain) {
  return `https://${domain}/checkout`;
}
