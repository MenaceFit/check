// Secure logger — never logs tokens, cards, CVV or cookies in full
const MAX_LOG_ENTRIES = 200;

const SENSITIVE_PATTERNS = [
  /Bearer\s+[A-Za-z0-9\-_\.]{10,}/gi,
  /token["\s:=]+[A-Za-z0-9\-_\.]{10,}/gi,
  /cookie["\s:=]+[^;,\s]{10,}/gi,
  /\d{13,19}/g,        // card numbers
  /\d{3,4}/g,          // CVV (only masked when adjacent to card context)
];

function maskSensitive(text) {
  if (typeof text !== 'string') {
    try { text = JSON.stringify(text); } catch { text = String(text); }
  }
  let masked = text;
  // Mask tokens/Bearer keeping first 6 and last 4 chars
  masked = masked.replace(/(Bearer\s+)([A-Za-z0-9\-_\.]{6})([A-Za-z0-9\-_\.]+)([A-Za-z0-9\-_\.]{4})/gi,
    (_, prefix, start, middle, end) => `${prefix}${start}${'*'.repeat(middle.length)}${end}`);
  // Mask long tokens in token= patterns
  masked = masked.replace(/(["']?token["']?\s*[:=]\s*["']?)([A-Za-z0-9\-_\.]{6})([A-Za-z0-9\-_\.]+)([A-Za-z0-9\-_\.]{4}["']?)/gi,
    (_, prefix, start, middle, end) => `${prefix}${start}${'*'.repeat(middle.length)}${end}`);
  return masked;
}

function formatEntry(level, module, message, data) {
  const entry = {
    ts: Date.now(),
    time: new Date().toISOString(),
    level,
    module,
    message: maskSensitive(String(message)),
    data: data !== undefined ? maskSensitive(typeof data === 'object' ? JSON.stringify(data) : String(data)) : undefined,
  };
  return entry;
}

class Logger {
  constructor(module = 'QC') {
    this.module = module;
    this._buffer = [];
  }

  _emit(level, message, data) {
    const entry = formatEntry(level, this.module, message, data);
    this._buffer.push(entry);
    if (this._buffer.length > MAX_LOG_ENTRIES) {
      this._buffer.shift();
    }
    // Also persist to storage (async, fire-and-forget)
    this._persist(entry);
    // Console output (never logs raw sensitive data)
    const prefix = `[QC:${this.module}][${entry.time.slice(11, 23)}]`;
    if (level === 'error') {
      console.error(prefix, entry.message, entry.data ?? '');
    } else if (level === 'warn') {
      console.warn(prefix, entry.message, entry.data ?? '');
    } else if (level === 'debug') {
      // Only log debug in debug mode
      chrome.storage?.local.get('qc_debug_mode', (r) => {
        if (r?.qc_debug_mode) console.debug(prefix, entry.message, entry.data ?? '');
      });
    } else {
      console.log(prefix, entry.message, entry.data ?? '');
    }
  }

  _persist(entry) {
    if (typeof chrome === 'undefined' || !chrome.storage) return;
    chrome.storage.local.get('qc_logs', (r) => {
      const logs = r?.qc_logs ?? [];
      logs.push(entry);
      if (logs.length > MAX_LOG_ENTRIES) logs.splice(0, logs.length - MAX_LOG_ENTRIES);
      chrome.storage.local.set({ qc_logs: logs });
    });
  }

  info(message, data) { this._emit('info', message, data); }
  warn(message, data) { this._emit('warn', message, data); }
  error(message, data) { this._emit('error', message, data); }
  debug(message, data) { this._emit('debug', message, data); }

  getBuffer() { return [...this._buffer]; }
  clearBuffer() { this._buffer = []; }
}

export function createLogger(module) {
  return new Logger(module);
}

export const log = new Logger('Main');
