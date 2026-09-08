// Vinted domains supported
export const VINTED_DOMAINS = [
  'vinted.fr',
  'vinted.be',
  'vinted.es',
  'vinted.de',
  'vinted.it',
  'vinted.co.uk',
  'vinted.nl',
  'vinted.pl',
  'vinted.pt',
  'vinted.com',
];

// Vinted API base path
export const VINTED_API_PATH = '/api/v2';

// Vinted item endpoint
export const VINTED_ITEM_ENDPOINT = '/items';

// Regex to extract item ID from Vinted URLs
// e.g. https://www.vinted.fr/vetements/123456-nike-tech
// e.g. https://www.vinted.fr/items/123456
export const VINTED_ITEM_ID_REGEX = /\/items\/(\d+)|[-/](\d{6,})-|[-/](\d{6,})$/;

// Extension storage keys
export const STORAGE_KEYS = {
  ENABLED: 'qc_enabled',
  DEBUG_MODE: 'qc_debug_mode',
  VINTED_DOMAIN: 'qc_vinted_domain',
  LAST_SESSION_CHECK: 'qc_last_session_check',
  CHECKOUT_COUNT: 'qc_checkout_count',
  LATENCY_HISTORY: 'qc_latency_history',
};

// Session check interval (ms)
export const SESSION_CHECK_INTERVAL = 60000;

// Max latency history entries
export const MAX_LATENCY_ENTRIES = 20;

// Checkout timeout (ms) — abort if checkout takes longer
export const CHECKOUT_TIMEOUT = 8000;
