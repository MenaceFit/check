/* LBC Sniper — dashboard (JavaScript sans dépendance) */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  meta: null,
  searches: [],
  status: null,
  settings: {},
  feed: [],
  editingId: null,
  live: false,
};

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (res.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error("Non authentifié");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error((data && data.detail) || `Erreur HTTP ${res.status}`);
  return data;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ------------------------------------------------------------- formats
const fmtPrice = (p) => (p === null || p === undefined ? "—" : `${Number(p).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} €`);
function fmtAgo(iso) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 5) return "à l'instant";
  if (s < 60) return `il y a ${Math.round(s)} s`;
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return new Date(iso).toLocaleString("fr-FR");
}
function fmtLatency(s) {
  if (s === null || s === undefined) return "—";
  if (s < 90) return `${Math.max(0, Math.round(s))} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
const stateLabel = {
  ok: ["ok", "Active"], error: ["err", "Erreur"], paused: ["warn", "Pause globale"],
  starting: ["warn", "Démarrage"], disabled: ["", "Désactivée"], stopped: ["", "Arrêtée"],
};

// --------------------------------------------------------------- login
function showLogin() {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#login-password").focus();
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/login", { method: "POST", body: { password: $("#login-password").value } });
    $("#login").classList.add("hidden");
    boot();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});
$("#logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

// ---------------------------------------------------------------- tabs
function showTab(name) {
  if (!$(`#tab-${name}`)) name = "dashboard";
  $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${name}`));
  $$("nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === name));
  if (name === "ads") loadAds();
  if (name === "logs") loadLogs();
  if (name === "settings") renderSettings();
}
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

// ------------------------------------------------------------- loading
async function refreshAll() {
  const [searches, status] = await Promise.all([api("/api/searches"), api("/api/status")]);
  state.searches = searches;
  state.status = status;
  renderStats();
  renderWatchers();
  renderSearchList();
  renderSidebar();
  renderAdsFilter();
}

async function loadFeed() {
  const rows = await api("/api/ads?limit=40");
  state.feed = rows.map((r) => ({ ...r, search_name: searchName(r.search_id) }));
  renderFeed();
}

function searchName(id) {
  const s = state.searches.find((x) => x.id === id);
  return s ? s.config.name : `#${id}`;
}

// ------------------------------------------------------------ dashboard
function renderStats() {
  const st = state.status || {};
  const active = state.searches.filter((s) => s.config.enabled).length;
  const lat = state.searches.map((s) => s.counts.avg_latency_s).filter((x) => x !== null && x !== undefined);
  const avg = lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null;
  const found = state.searches.reduce((a, s) => a + (s.counts.found || 0), 0);
  const cards = [
    ["Recherches actives", `${active}<span class="muted small"> / ${state.searches.length}</span>`, st.paused ? "⏸️ pause globale" : "surveillance en cours"],
    ["Alertes Discord", st.notifications_sent ?? 0, `${st.notifications_failed ?? 0} échec(s) depuis le démarrage`],
    ["Annonces détectées", found, "dans l'historique"],
    ["Délai moyen", fmtLatency(avg), "entre publication et alerte"],
    ["Requêtes / min", `${st.requests_last_minute ?? 0}<span class="muted small"> / ${st.requests_limit_per_minute ?? "?"}</span>`, `${st.requests_total ?? 0} au total`],
    ["Latence Leboncoin", st.last_http_latency_ms ? `${st.last_http_latency_ms} ms` : "—", "dernière requête"],
  ];
  $("#stats").innerHTML = cards
    .map(([l, v, s]) => `<div class="stat"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${esc(s)}</div></div>`)
    .join("");
  $("#pause-all").textContent = st.paused ? "▶️ Tout relancer" : "⏸️ Tout mettre en pause";
}

function renderWatchers() {
  const el = $("#watchers");
  if (!state.searches.length) {
    el.innerHTML = `<div class="empty">Aucune recherche.<br><br><button class="btn primary" data-action="new-search">＋ Créer ma première recherche</button></div>`;
    return;
  }
  el.innerHTML = state.searches
    .map((s) => {
      const st = s.status || {};
      const [cls, label] = stateLabel[st.state] || ["", st.state || "—"];
      const next = st.next_run_in !== undefined && st.next_run_in !== null ? `prochaine dans ${Math.round(st.next_run_in)} s` : "";
      return `<div class="watcher">
        <span class="dot ${cls}"></span>
        <div><div class="name">${esc(s.config.name)}</div>
          <div class="meta">${label} • toutes les ${st.interval || s.config.interval_seconds} s ${next ? "• " + next : ""}
          ${st.last_error ? `<br><span class="error">${esc(st.last_error)}</span>` : ""}</div></div>
        <button class="btn small" data-action="run" data-id="${s.id}" ${s.config.enabled ? "" : "disabled"}>▶ Lancer</button>
      </div>`;
    })
    .join("");
}

function feedItem(r, fresh = false) {
  const ad = r.ad;
  const img = ad.images && ad.images[0] ? `<img src="${esc(ad.images[0])}" loading="lazy" alt="">` : `<div class="thumb-ph">📦</div>`;
  const badge = r.notified
    ? `<span class="badge ok">envoyée</span>`
    : `<span class="badge ${r.reject_reason.startsWith("envoi") ? "err" : ""}" title="${esc(r.reject_reason)}">${esc(r.reject_reason || "non envoyée")}</span>`;
  return `<a class="feed-item ${fresh ? "fresh" : ""}" href="${esc(ad.url)}" target="_blank" rel="noopener">
    ${img}
    <div style="min-width:0"><div class="title">${esc(ad.title)}</div>
      <div class="meta">${esc(r.search_name || "")} • ${esc(ad.city || "")} ${esc(ad.zipcode || "")} • ⚡ ${fmtLatency(r.latency_s)} • ${fmtAgo(r.found_at)}</div>
      <div class="meta">${badge}</div></div>
    <div class="price">${fmtPrice(ad.price)}</div>
  </a>`;
}

function renderFeed(freshId = null) {
  const el = $("#live-feed");
  if (!state.feed.length) {
    el.innerHTML = `<div class="empty">En attente de nouvelles annonces…<br><span class="small">Au premier passage, les annonces déjà en ligne sont mémorisées sans alerte.</span></div>`;
    return;
  }
  el.innerHTML = state.feed.map((r) => feedItem(r, r.id === freshId)).join("");
}

function renderSidebar() {
  const st = state.status || {};
  const bot = (state.meta && state.meta.bot) || {};
  $("#engine-pill").innerHTML = `<span class="dot ${st.paused ? "warn" : "ok"}"></span> Moteur ${st.paused ? "en pause" : "actif"}`;
  $("#bot-pill").innerHTML = bot.connected
    ? `<span class="dot ok"></span> Bot : ${esc(bot.user)}`
    : `<span class="dot ${bot.configured ? "err" : ""}"></span> Bot ${bot.configured ? "déconnecté" : "non configuré"}`;
  $("#live-pill").innerHTML = `<span class="dot ${state.live ? "ok" : "err"}"></span> Temps réel ${state.live ? "connecté" : "coupé"}`;
}

// ------------------------------------------------------------ searches
function criteriaBadges(c) {
  const b = [];
  if (c.keywords) b.push(`🔤 ${c.keywords}${c.title_only ? " (titre)" : ""}`);
  if (c.category) b.push(`🗂️ cat. ${c.category}`);
  if (c.price_min !== null || c.price_max !== null) b.push(`💶 ${c.price_min ?? 0} – ${c.price_max ?? "∞"} €`);
  if (c.locations.length) b.push(`📍 ${c.locations.map((l) => l.label || l.city || l.department_id || l.region_id).join(", ")}`);
  else b.push("📍 Toute la France");
  if (c.owner_type !== "all") b.push(c.owner_type === "private" ? "👤 Particuliers" : "🏢 Pros");
  if (c.shippable_only) b.push("📦 Livraison");
  if (c.extra_filters.length) b.push(`🧩 ${c.extra_filters.length} champ(s) perso`);
  if (c.exclude_words.length) b.push(`🚫 ${c.exclude_words.length} mot(s) exclu(s)`);
  if (c.max_age_minutes) b.push(`⏱️ < ${c.max_age_minutes} min`);
  return b.map((x) => `<span class="badge">${esc(x)}</span>`).join("");
}

function renderSearchList() {
  const el = $("#search-list");
  if (!state.searches.length) {
    el.innerHTML = `<div class="card empty">Aucune recherche pour l'instant.<br><br><button class="btn primary" data-action="new-search">＋ Nouvelle recherche</button></div>`;
    return;
  }
  el.innerHTML = state.searches
    .map((s) => {
      const c = s.config, st = s.status || {}, n = s.counts || {};
      const [cls, label] = stateLabel[st.state] || ["", st.state || "—"];
      const dest = c.discord_channel_id ? `salon ${c.discord_channel_id}` : c.webhook_url ? "webhook" : "salon par défaut";
      return `<div class="card search-card">
        <div class="top">
          <div><h3>${esc(c.name)}</h3><div class="muted small"><span class="dot ${cls}"></span> ${label} • toutes les ${st.interval || c.interval_seconds} s • ${esc(dest)}</div></div>
          <label class="check" title="Activer / désactiver"><input type="checkbox" data-action="toggle" data-id="${s.id}" ${c.enabled ? "checked" : ""}></label>
        </div>
        <div class="criteria">${criteriaBadges(c)}</div>
        <div class="numbers">
          <div><b>${n.notified || 0}</b><span>alertes</span></div>
          <div><b>${n.found || 0}</b><span>détectées</span></div>
          <div><b>${fmtLatency(n.avg_latency_s)}</b><span>délai moyen</span></div>
        </div>
        ${st.last_error ? `<div class="err">⚠️ ${esc(st.last_error)}</div>` : ""}
        <div class="buttons">
          <button class="btn small primary" data-action="edit" data-id="${s.id}">✏️ Modifier</button>
          <button class="btn small" data-action="run" data-id="${s.id}" ${c.enabled ? "" : "disabled"}>▶ Lancer</button>
          <button class="btn small" data-action="test" data-id="${s.id}">📨 Test</button>
          <a class="btn small" href="${esc(s.web_url)}" target="_blank" rel="noopener">↗ LBC</a>
          <button class="btn small" data-action="duplicate" data-id="${s.id}">⧉</button>
          <button class="btn small" data-action="reset" data-id="${s.id}" title="Oublier les annonces déjà vues">♻</button>
          <button class="btn small danger" data-action="delete" data-id="${s.id}">🗑</button>
        </div>
      </div>`;
    })
    .join("");
}

// -------------------------------------------------------------------- ads
function adCard(r) {
  const ad = r.ad;
  const img = ad.images && ad.images[0] ? `<img src="${esc(ad.images[0])}" loading="lazy" alt="">` : `<div class="img-ph">📦</div>`;
  const accepted = r.accepted !== undefined ? r.accepted : r.notified;
  const reason = r.reason !== undefined ? r.reason : r.reject_reason;
  const ship = ad.shippable === true ? "📦 livraison" : ad.shippable === false ? "🤝 main propre" : "";
  return `<a class="ad-card ${accepted ? "" : "rejected"}" href="${esc(ad.url)}" target="_blank" rel="noopener">
    ${img}
    <div class="body">
      <div class="price">${fmtPrice(ad.price)}</div>
      <div class="title">${esc(ad.title)}</div>
      <div class="meta">📍 ${esc(ad.city || "—")} ${esc(ad.zipcode || "")} ${ship ? "• " + ship : ""}</div>
      <div class="meta">${ad.owner_type ? "👤 " + esc(ad.owner_type) + " • " : ""}🕒 ${fmtAgo(ad.published_at)}</div>
      <div>${accepted ? '<span class="badge ok">✓ correspond</span>' : `<span class="badge">${esc(reason || "non envoyée")}</span>`}
        ${r.search_id ? `<span class="badge accent">${esc(searchName(r.search_id))}</span>` : ""}</div>
    </div></a>`;
}

function renderAdsFilter() {
  const sel = $("#ads-filter-search");
  const cur = sel.value;
  sel.innerHTML = `<option value="">Toutes les recherches</option>` + state.searches.map((s) => `<option value="${s.id}">${esc(s.config.name)}</option>`).join("");
  sel.value = cur;
}

async function loadAds() {
  const sid = $("#ads-filter-search").value;
  const only = $("#ads-only-notified").checked;
  const rows = await api(`/api/ads?limit=200${sid ? "&search_id=" + sid : ""}${only ? "&notified=true" : ""}`);
  $("#ads-grid").innerHTML = rows.length ? rows.map(adCard).join("") : `<div class="empty">Aucune annonce pour l'instant.</div>`;
}
$("#ads-filter-search").addEventListener("change", loadAds);
$("#ads-only-notified").addEventListener("change", loadAds);
$("#ads-refresh").addEventListener("click", loadAds);

// ------------------------------------------------------------------- logs
function logLine(l) {
  const t = new Date(l.ts).toLocaleTimeString("fr-FR");
  return `<div class="log"><span class="muted">${t}</span><span class="lvl-${esc(l.level)}">${esc(l.level)}</span><span>${esc(l.message)}</span></div>`;
}
async function loadLogs() {
  const logs = await api("/api/logs");
  $("#log-list").innerHTML = logs.reverse().map(logLine).join("") || `<div class="empty">Rien à signaler.</div>`;
}

// --------------------------------------------------------------- settings
function channelOptions(selected) {
  const ch = (state.meta && state.meta.bot && state.meta.bot.channels) || [];
  const opts = [`<option value="">— choisir un salon —</option>`].concat(
    ch.map((c) => `<option value="${c.id}" ${c.id === selected ? "selected" : ""}>${esc(c.guild)} › ${esc(c.name)}</option>`)
  );
  return opts.join("");
}

async function renderSettings() {
  state.settings = await api("/api/settings");
  const f = $("#settings-form");
  for (const [k, v] of Object.entries(state.settings)) {
    const input = f.elements[k];
    if (input) input.value = v ?? "";
  }
  $("#set-default-channel-select").innerHTML = channelOptions(state.settings.default_channel_id);
  const bot = state.meta.bot;
  $("#bot-info").innerHTML = bot.connected
    ? `<p><span class="dot ok"></span> Connecté en tant que <b>${esc(bot.user)}</b> — ${bot.channels.length} salon(s) accessible(s).</p>
       <p><a class="btn" href="${esc(bot.invite_url)}" target="_blank" rel="noopener">➕ Inviter le bot sur un autre serveur</a></p>
       <p class="muted small">Commandes : <code>/lbc status</code> <code>/lbc ajouter</code> <code>/lbc tester</code> <code>/lbc pause</code> <code>/lbc reprendre</code> <code>/lbc toutpause</code></p>`
    : bot.configured
      ? `<p><span class="dot err"></span> Le token est renseigné mais le bot n'est pas connecté. Vérifiez le token dans <code>.env</code> et le journal.</p>`
      : `<p><span class="dot"></span> Aucun <code>DISCORD_TOKEN</code> dans <code>.env</code>. Seuls les webhooks fonctionnent. Voir <b>INSTALLATION.md</b>.</p>`;
  $("#limits").innerHTML = `Intervalle minimum par recherche : <b>${state.meta.min_interval} s</b><br>Plafond global : <b>${state.meta.max_requests_per_minute} requêtes / minute</b><br><span class="small">Modifiables dans <code>.env</code> (LBC_MIN_INTERVAL, LBC_MAX_REQUESTS_PER_MINUTE).</span>`;
}
$("#set-default-channel-select").addEventListener("change", (e) => { if (e.target.value) $("#set-default-channel").value = e.target.value; });
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = {
    default_channel_id: f.elements.default_channel_id.value.trim(),
    default_webhook_url: f.elements.default_webhook_url.value.trim(),
    alert_channel_id: f.elements.alert_channel_id.value.trim(),
    source_mode: f.elements.source_mode.value,
    keep_ads: parseInt(f.elements.keep_ads.value, 10) || 3000,
  };
  try {
    await api("/api/settings", { method: "PUT", body });
    toast("Paramètres enregistrés", "ok");
  } catch (err) { toast(err.message, "err"); }
});
$("#import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const res = await api("/api/import", { method: "POST", body: data });
    toast(`${res.created.length} recherche(s) importée(s)`, "ok");
    refreshAll();
  } catch (err) { toast("Import impossible : " + err.message, "err"); }
  e.target.value = "";
});
$("#pause-all").addEventListener("click", async () => {
  await api("/api/settings", { method: "PUT", body: { paused: !(state.status && state.status.paused) } });
  await refreshAll();
});

// ----------------------------------------------------------------- editor
const DEFAULT_CFG = {
  name: "Nouvelle recherche", enabled: true, keywords: "", title_only: false, category: "", locations: [],
  price_min: null, price_max: null, owner_type: "all", shippable_only: false, extra_filters: [],
  exclude_words: [], required_words: [], required_mode: "any", max_age_minutes: null,
  discord_channel_id: "", webhook_url: "", mention: "", embed_color: "#ff6e14",
  display_fields: ["price", "location", "date", "latency", "seller", "shipping", "image"],
  interval_seconds: 30, notify_existing_on_start: false, limit: 35,
};

function locationRow(l = {}) {
  const div = document.createElement("div");
  div.className = "item loc";
  div.innerHTML = `
    <select data-k="type">
      <option value="city">Ville + rayon</option><option value="department">Département</option><option value="region">Région</option>
    </select>
    <input data-k="city" placeholder="Ville">
    <input data-k="zipcode" placeholder="Code postal">
    <input data-k="lat" type="number" step="any" placeholder="Latitude">
    <input data-k="lng" type="number" step="any" placeholder="Longitude">
    <input data-k="radius_km" type="number" step="any" min="0" placeholder="Rayon km">
    <button type="button" class="btn small danger" data-remove>✕</button>`;
  const set = (k, v) => { const i = div.querySelector(`[data-k=${k}]`); if (i) i.value = v ?? ""; };
  set("type", l.type || "city");
  if (l.type === "department") set("city", l.department_id);
  else if (l.type === "region") set("city", l.region_id);
  else set("city", l.city);
  ["zipcode", "lat", "lng", "radius_km"].forEach((k) => set(k, l[k]));
  div.dataset.label = l.label || "";
  div.dataset.defaultRadius = l.default_radius || "";
  const sync = () => {
    const t = div.querySelector("[data-k=type]").value;
    div.querySelector("[data-k=city]").placeholder = t === "city" ? "Ville" : t === "department" ? "N° département (ex : 69)" : "N° région (ex : 22)";
    ["zipcode", "lat", "lng", "radius_km"].forEach((k) => (div.querySelector(`[data-k=${k}]`).style.visibility = t === "city" ? "visible" : "hidden"));
  };
  div.querySelector("[data-k=type]").addEventListener("change", sync);
  div.querySelector("[data-remove]").addEventListener("click", () => div.remove());
  sync();
  return div;
}

function readLocation(div) {
  const g = (k) => div.querySelector(`[data-k=${k}]`).value.trim();
  const num = (k) => (g(k) === "" ? null : Number(g(k)));
  const type = g("type");
  if (type === "department") return { type, department_id: g("city"), label: `Département ${g("city")}` };
  if (type === "region") return { type, region_id: g("city"), label: `Région ${g("city")}` };
  return {
    type, city: g("city"), zipcode: g("zipcode"), lat: num("lat"), lng: num("lng"), radius_km: num("radius_km"),
    default_radius: div.dataset.defaultRadius ? Number(div.dataset.defaultRadius) : null,
    label: div.dataset.label || `${g("city")} ${g("zipcode")}`.trim(),
  };
}

function extraRow(f = {}) {
  const div = document.createElement("div");
  div.className = "item extra";
  div.innerHTML = `
    <input data-k="key" placeholder="clé (ex : mileage)">
    <select data-k="kind"><option value="enum">Valeurs</option><option value="range">Plage</option></select>
    <div class="row">
      <input data-k="values" placeholder="valeurs séparées par des virgules">
      <input data-k="min" type="number" step="any" placeholder="min">
      <input data-k="max" type="number" step="any" placeholder="max">
    </div>
    <button type="button" class="btn small danger" data-remove>✕</button>`;
  div.querySelector("[data-k=key]").value = f.key || "";
  div.querySelector("[data-k=kind]").value = f.kind || "enum";
  div.querySelector("[data-k=values]").value = (f.values || []).join(",");
  div.querySelector("[data-k=min]").value = f.min ?? "";
  div.querySelector("[data-k=max]").value = f.max ?? "";
  const sync = () => {
    const range = div.querySelector("[data-k=kind]").value === "range";
    div.querySelector("[data-k=values]").classList.toggle("hidden", range);
    div.querySelector("[data-k=min]").classList.toggle("hidden", !range);
    div.querySelector("[data-k=max]").classList.toggle("hidden", !range);
  };
  div.querySelector("[data-k=kind]").addEventListener("change", sync);
  div.querySelector("[data-remove]").addEventListener("click", () => div.remove());
  sync();
  return div;
}

function readExtra(div) {
  const g = (k) => div.querySelector(`[data-k=${k}]`).value.trim();
  const num = (k) => (g(k) === "" ? null : Number(g(k)));
  return { key: g("key"), kind: g("kind"), values: g("values").split(",").map((x) => x.trim()).filter(Boolean), min: num("min"), max: num("max") };
}

function fillEditor(cfg) {
  const f = $("#editor-form");
  const c = { ...DEFAULT_CFG, ...cfg };
  for (const name of ["name", "interval_seconds", "keywords", "category", "price_min", "price_max", "owner_type", "required_mode",
    "max_age_minutes", "discord_channel_id", "webhook_url", "mention", "embed_color", "limit"]) {
    f.elements[name].value = c[name] ?? "";
  }
  for (const name of ["enabled", "notify_existing_on_start", "title_only", "shippable_only"]) f.elements[name].checked = !!c[name];
  f.elements.exclude_words.value = (c.exclude_words || []).join(", ");
  f.elements.required_words.value = (c.required_words || []).join(", ");
  $("#locations").replaceChildren(...(c.locations || []).map(locationRow));
  $("#extras").replaceChildren(...(c.extra_filters || []).map(extraRow));
  $("#channel-select").innerHTML = channelOptions(c.discord_channel_id);
  const fields = state.meta.display_fields;
  $("#display-fields").innerHTML = Object.entries(fields)
    .map(([k, label]) => `<label class="chip ${c.display_fields.includes(k) ? "on" : ""}"><input type="checkbox" value="${k}" ${c.display_fields.includes(k) ? "checked" : ""}>${esc(label)}</label>`)
    .join("");
  $$("#display-fields .chip input").forEach((i) => i.addEventListener("change", () => i.parentElement.classList.toggle("on", i.checked)));
  $("#interval-hint").textContent = `minimum ${state.meta.min_interval} s`;
  f.elements.interval_seconds.min = state.meta.min_interval;
  updateLbcLink();
}

function readEditor() {
  const f = $("#editor-form");
  const intOrNull = (v) => (v === "" || v === null ? null : parseInt(v, 10));
  return {
    name: f.elements.name.value.trim() || "Sans nom",
    enabled: f.elements.enabled.checked,
    keywords: f.elements.keywords.value.trim(),
    title_only: f.elements.title_only.checked,
    category: f.elements.category.value.trim(),
    locations: $$("#locations .item").map(readLocation).filter((l) => l.city || l.department_id || l.region_id),
    price_min: intOrNull(f.elements.price_min.value),
    price_max: intOrNull(f.elements.price_max.value),
    owner_type: f.elements.owner_type.value,
    shippable_only: f.elements.shippable_only.checked,
    extra_filters: $$("#extras .item").map(readExtra).filter((x) => x.key),
    exclude_words: f.elements.exclude_words.value,
    required_words: f.elements.required_words.value,
    required_mode: f.elements.required_mode.value,
    max_age_minutes: intOrNull(f.elements.max_age_minutes.value),
    discord_channel_id: f.elements.discord_channel_id.value.trim(),
    webhook_url: f.elements.webhook_url.value.trim(),
    mention: f.elements.mention.value.trim(),
    embed_color: f.elements.embed_color.value,
    display_fields: $$("#display-fields input:checked").map((i) => i.value),
    interval_seconds: parseInt(f.elements.interval_seconds.value, 10) || 30,
    notify_existing_on_start: f.elements.notify_existing_on_start.checked,
    limit: parseInt(f.elements.limit.value, 10) || 35,
  };
}

let linkTimer = null;
function updateLbcLink() {
  clearTimeout(linkTimer);
  linkTimer = setTimeout(async () => {
    try {
      const r = await api("/api/build-url", { method: "POST", body: readEditor() });
      $("#editor-open-lbc").href = r.url;
    } catch { /* formulaire incomplet */ }
  }, 300);
}

function openEditor(search = null) {
  state.editingId = search ? search.id : null;
  $("#editor-title").textContent = search ? `Modifier « ${search.config.name} »` : "Nouvelle recherche";
  const base = search ? search.config : { ...DEFAULT_CFG, discord_channel_id: state.settings.default_channel_id || "" };
  fillEditor(base);
  $("#import-url").value = "";
  $("#editor").classList.remove("hidden");
  $("#editor-form").elements.name.focus();
}

$("#editor-form").addEventListener("input", updateLbcLink);
$("#add-location").addEventListener("click", () => $("#locations").appendChild(locationRow()));
$("#add-extra").addEventListener("click", () => $("#extras").appendChild(extraRow()));
$("#channel-select").addEventListener("change", (e) => { if (e.target.value) $("#editor-form").elements.discord_channel_id.value = e.target.value; });

$("#import-url-btn").addEventListener("click", async () => {
  const url = $("#import-url").value.trim();
  if (!url) return toast("Collez d'abord une URL leboncoin.fr", "err");
  try {
    const current = readEditor();
    const cfg = await api("/api/parse-url", { method: "POST", body: { url, base: current } });
    fillEditor(cfg);
    toast("Filtres importés depuis Leboncoin ✓", "ok");
  } catch (err) { toast(err.message, "err"); }
});

async function withBusy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (err) { toast(err.message, "err"); } finally { btn.disabled = false; }
}

$("#editor-save").addEventListener("click", (e) => withBusy(e.target, async () => {
  const cfg = readEditor();
  if (!cfg.keywords && !cfg.category && !cfg.extra_filters.length && !cfg.locations.length) {
    if (!confirm("Aucun critère : cette recherche surveillera TOUTES les annonces de Leboncoin. Continuer ?")) return;
  }
  if (state.editingId) await api(`/api/searches/${state.editingId}`, { method: "PUT", body: cfg });
  else state.editingId = (await api("/api/searches", { method: "POST", body: cfg })).id;
  $("#editor").classList.add("hidden");
  toast("Recherche enregistrée — surveillance lancée 🚀", "ok");
  await refreshAll();
}));

$("#editor-preview").addEventListener("click", (e) => withBusy(e.target, async () => {
  const res = await api("/api/preview", { method: "POST", body: readEditor() });
  const ok = res.results.filter((r) => r.accepted).length;
  $("#preview-title").textContent = `Prévisualisation — ${res.count} annonce(s), ${ok} correspondent à vos filtres`;
  $("#preview-body").innerHTML = res.results.length ? res.results.map(adCard).join("") : `<div class="empty">Aucune annonce trouvée avec ces critères.</div>`;
  $("#preview").classList.remove("hidden");
}));

$("#editor-test").addEventListener("click", (e) => withBusy(e.target, async () => {
  if (!state.editingId) return toast("Enregistrez d'abord la recherche pour envoyer un test.", "err");
  await api(`/api/searches/${state.editingId}`, { method: "PUT", body: readEditor() });
  const r = await api(`/api/searches/${state.editingId}/test-notification`, { method: "POST" });
  toast(`Message test envoyé (${r.via}) ✓`, "ok");
}));

$$("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest(".modal").classList.add("hidden")));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $$(".modal").forEach((m) => m.classList.add("hidden"));
});

// --------------------------------------------------- actions délégées
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-action]");
  if (!el || el.tagName === "INPUT") return;
  const id = el.dataset.id ? Number(el.dataset.id) : null;
  const search = state.searches.find((s) => s.id === id);
  try {
    switch (el.dataset.action) {
      case "new-search": openEditor(); break;
      case "edit": openEditor(search); break;
      case "run":
        el.disabled = true;
        await api(`/api/searches/${id}/run`, { method: "POST" });
        toast("Recherche lancée ✓", "ok");
        await refreshAll();
        break;
      case "test": {
        const r = await api(`/api/searches/${id}/test-notification`, { method: "POST" });
        toast(`Message test envoyé (${r.via}) ✓`, "ok");
        break;
      }
      case "duplicate": await api(`/api/searches/${id}/duplicate`, { method: "POST" }); await refreshAll(); break;
      case "reset":
        if (confirm("Oublier les annonces déjà vues ? Le prochain passage les mémorisera à nouveau sans alerte.")) {
          await api(`/api/searches/${id}/reset`, { method: "POST" });
          toast("Mémoire réinitialisée", "ok");
        }
        break;
      case "delete":
        if (confirm(`Supprimer « ${search.config.name} » et son historique ?`)) {
          await api(`/api/searches/${id}`, { method: "DELETE" });
          await refreshAll();
        }
        break;
    }
  } catch (err) { toast(err.message, "err"); } finally { if (el.dataset.action === "run") el.disabled = false; }
});
document.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.dataset.action !== "toggle") return;
  try {
    await api(`/api/searches/${el.dataset.id}/toggle`, { method: "POST" });
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

// ----------------------------------------------------------- temps réel
let refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refreshAll().catch(() => {}), 700);
}

function connectStream() {
  const es = new EventSource("/api/stream");
  es.onopen = () => { state.live = true; renderSidebar(); };
  es.onerror = () => { state.live = false; renderSidebar(); };
  es.addEventListener("ad", (ev) => {
    const data = JSON.parse(ev.data).data;
    state.feed.unshift(data);
    state.feed = state.feed.slice(0, 60);
    renderFeed(data.id);
    if (data.notified) toast(`🆕 ${data.ad.title} — ${fmtPrice(data.ad.price)}`, "ok");
    scheduleRefresh();
  });
  es.addEventListener("status", scheduleRefresh);
  es.addEventListener("searches", scheduleRefresh);
  es.addEventListener("settings", scheduleRefresh);
  es.addEventListener("log", (ev) => {
    const l = JSON.parse(ev.data).data;
    if (!$("#tab-logs").classList.contains("hidden")) $("#log-list").insertAdjacentHTML("afterbegin", logLine(l));
    if (l.level === "ERROR") toast(l.message, "err");
  });
}

// ------------------------------------------------------------------ boot
async function boot() {
  try {
    const me = await api("/api/me");
    if (me.auth_required && !me.authenticated) return showLogin();
    $("#logout").classList.toggle("hidden", !me.auth_required);
    $("#app").classList.remove("hidden");
    state.meta = await api("/api/meta");
    state.settings = await api("/api/settings");
    await refreshAll();
    await loadFeed();
    showTab(location.hash.slice(1) || "dashboard");
    connectStream();
    setInterval(() => refreshAll().catch(() => {}), 5000);
    setInterval(async () => { try { state.meta = await api("/api/meta"); renderSidebar(); } catch {} }, 20000);
  } catch (err) {
    if (err.message !== "Non authentifié") toast(err.message, "err");
  }
}
boot();
