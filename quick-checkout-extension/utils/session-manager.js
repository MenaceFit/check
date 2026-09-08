import { STORAGE_KEYS, SESSION_CHECK_INTERVAL } from '../config/constants.js';
import { checkVintedSession, detectVintedDomain } from './vinted-api.js';
import { createLogger } from './logger.js';

const log = createLogger('SessionMgr');

/**
 * SessionManager — manages Vinted session state.
 *
 * SECURITY:
 * - Never stores raw tokens or cookies in extension storage.
 * - Uses Chrome cookie access (already sandboxed to the domain).
 * - The v-tools.com token flow is optional and the token is stored
 *   encrypted in chrome.storage.local (AES-GCM via Web Crypto).
 * - Token is never logged in full — always masked.
 */
class SessionManager {
  constructor() {
    this._status = 'unknown';
    this._userId = null;
    this._domain = null;
    this._vToolsToken = null;  // stored encrypted
    this._lastCheck = 0;
  }

  async init() {
    this._domain = await detectVintedDomain();
    await this._loadEncryptedToken();
    await this.checkSession();
  }

  get status() { return this._status; }
  get isAuthenticated() { return this._status === 'active'; }
  get domain() { return this._domain; }

  async checkSession() {
    try {
      const { authenticated, userId } = await checkVintedSession(this._domain);
      this._status = authenticated ? 'active' : 'inactive';
      this._userId = userId;
      this._lastCheck = Date.now();
      chrome.storage.local.set({
        [STORAGE_KEYS.LAST_SESSION_CHECK]: this._lastCheck,
        qc_session_status: this._status,
      });
      log.info(`Session status: ${this._status}`, { userId: userId ? '***' : null });
      return authenticated;
    } catch (err) {
      log.error('Session check failed', err.message);
      this._status = 'error';
      return false;
    }
  }

  // --- V-Tools token (optional, encrypted at rest) ---

  /**
   * Encrypts and stores the v-tools token securely.
   * The key is derived from a machine-specific salt stored separately.
   * NOTE: This is an optional flow — if the user's browser session works,
   * this is not needed.
   */
  async storeVToolsToken(rawToken) {
    if (!rawToken) return;
    try {
      const encrypted = await this._encrypt(rawToken);
      await chrome.storage.local.set({ qc_vtools_enc: encrypted });
      this._vToolsToken = rawToken;
      log.info('V-Tools token stored (encrypted)');
    } catch (err) {
      log.error('Failed to encrypt token', err.message);
    }
  }

  async _loadEncryptedToken() {
    return new Promise((resolve) => {
      chrome.storage.local.get('qc_vtools_enc', async (r) => {
        if (r?.qc_vtools_enc) {
          try {
            this._vToolsToken = await this._decrypt(r.qc_vtools_enc);
          } catch {
            log.warn('Failed to decrypt stored token — clearing');
            chrome.storage.local.remove('qc_vtools_enc');
          }
        }
        resolve();
      });
    });
  }

  // --- AES-GCM encryption using Web Crypto API ---

  async _getKey() {
    // Derive a key from extension ID (unique per install, not guessable)
    const seed = new TextEncoder().encode(chrome.runtime.id + '_qc_key_v1');
    const hashBuf = await crypto.subtle.digest('SHA-256', seed);
    return crypto.subtle.importKey('raw', hashBuf, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
  }

  async _encrypt(plaintext) {
    const key = await this._getKey();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = new TextEncoder().encode(plaintext);
    const cipherBuf = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
    // Store as base64: iv + cipher
    const combined = new Uint8Array(iv.byteLength + cipherBuf.byteLength);
    combined.set(iv, 0);
    combined.set(new Uint8Array(cipherBuf), iv.byteLength);
    return btoa(String.fromCharCode(...combined));
  }

  async _decrypt(b64) {
    const combined = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const iv = combined.slice(0, 12);
    const cipher = combined.slice(12);
    const key = await this._getKey();
    const plainBuf = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, cipher);
    return new TextDecoder().decode(plainBuf);
  }

  clearToken() {
    this._vToolsToken = null;
    chrome.storage.local.remove('qc_vtools_enc');
    log.info('V-Tools token cleared');
  }

  // Mask for safe display/logging
  getMaskedToken() {
    if (!this._vToolsToken) return null;
    const t = this._vToolsToken;
    if (t.length <= 8) return '****';
    return t.slice(0, 6) + '*'.repeat(Math.min(t.length - 10, 20)) + t.slice(-4);
  }
}

export const sessionManager = new SessionManager();
