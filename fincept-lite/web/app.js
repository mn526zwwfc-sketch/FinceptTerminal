/* Fincept Lite — terminal web. Vanilla JS, sin build. */
"use strict";

// ── utilidades ──────────────────────────────────────────────────────────────
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtPx = window.fmtPx, fmtChg = window.fmtChg;
const fmtN = (v, d = 2) => (v == null || !isFinite(v) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const fmtPct = (v, d = 2) => (v == null || !isFinite(v) ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(d) + "%");
const fmtFrac = (v) => fmtPct(v == null ? null : v * 100);
const fmtVol = (v) => { if (!v) return "—"; const a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(2) + "M" : a >= 1e3 ? (v / 1e3).toFixed(1) + "K" : String(v); };
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "muted");
const ago = (ts) => { const s = Math.max(0, Date.now() / 1000 - ts); return s < 60 ? `${s | 0}s` : s < 3600 ? `${(s / 60) | 0}m` : s < 86400 ? `${(s / 3600) | 0}h` : `${(s / 86400) | 0}d`; };
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : ""); // nunca javascript:, data:…
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem("fl:" + k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("fl:" + k, JSON.stringify(v)); } catch { /* modo privado */ } },
  del(k) { try { localStorage.removeItem("fl:" + k); } catch { /* */ } },
};

function toast(msg, kind = "") {
  const d = document.createElement("div");
  d.className = kind; d.textContent = msg;
  $("#toast").appendChild(d);
  setTimeout(() => d.remove(), kind === "err" ? 6000 : 3500);
}

function md(text) { // markdown mínimo y seguro (escapa primero)
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|\s)_(.+?)_(?=\s|$|[.,;:])/g, "$1<i>$2</i>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

const S = { apiKey: null, session: null, user: null, health: {}, focus: store.get("focus") || "AAPL", screen: null };

// ── API (cabeceras X-API-Key / X-Session-Token como el HttpClient del terminal) ──
async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (S.apiKey) headers["X-API-Key"] = S.apiKey;
  if (S.session) headers["X-Session-Token"] = S.session;
  let r;
  try {
    r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    return { success: false, message: "Sin conexión con el servidor" };
  }
  if (r.status === 401 && S.apiKey) { logout("Sesión caducada o abierta en otro dispositivo"); return { success: false, message: "401" }; }
  let j = {};
  try { j = await r.json(); } catch { /* cuerpo vacío */ }
  if (r.status === 422 && Array.isArray(j.detail)) return { success: false, message: j.detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("\n") };
  if (r.status === 402) return { success: false, message: j.message, error: j.error };
  if (!r.ok && j.success === undefined) return { success: false, message: (j.detail && (j.detail.message || j.detail)) || `HTTP ${r.status}` };
  return j;
}
const tool = (name, args = {}) => api("/api/tools/call", { method: "POST", body: { name, arguments: args } });

// ── cliente DataHub (WebSocket) ─────────────────────────────────────────────
const Hub = {
  ws: null, subs: new Map(), retry: 0, msgs: 0,
  connect() {
    if (!S.apiKey) return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ op: "auth", api_key: S.apiKey }));
      this.retry = 0; setWs(true);
      const topics = [...this.subs.keys()];
      if (topics.length) ws.send(JSON.stringify({ op: "sub", topics }));
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      this.msgs++;
      $("#lastmsg").textContent = `${m.type} ${m.topic || ""}`.trim() + " · " + new Date().toLocaleTimeString("es-ES");
      if (m.type === "hello") return;
      const s = this.subs.get(m.topic);
      if (!s) return;
      if (m.type === "update") s.last = m.data;
      for (const cb of s.cbs) { try { cb(m.type === "update" ? m.data : null, m); } catch (err) { console.error(err); } }
    };
    ws.onclose = () => {
      setWs(false);
      if (this.ws !== ws || !S.apiKey) return;
      const wait = Math.min(15000, 500 * 2 ** this.retry++);
      setTimeout(() => this.ws === ws && this.connect(), wait);
    };
  },
  close() { const ws = this.ws; this.ws = null; ws && ws.close(); this.subs.clear(); },
  send(o) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(o)); },
  /** Suscripción con refcount: un solo "sub" al servidor por tópico; el último valor se entrega al instante. */
  sub(topic, cb) {
    let s = this.subs.get(topic);
    if (!s) { s = { cbs: new Set(), last: undefined }; this.subs.set(topic, s); this.send({ op: "sub", topics: [topic] }); }
    s.cbs.add(cb);
    if (s.last !== undefined) cb(s.last, { type: "update", topic });
    updTopics();
    return () => {
      s.cbs.delete(cb);
      if (!s.cbs.size) { this.subs.delete(topic); this.send({ op: "unsub", topics: [topic] }); }
      updTopics();
    };
  },
};
function setWs(on) {
  $("#wsdot").classList.toggle("on", on);
  $("#wsstate").textContent = on ? "DATAHUB CONECTADO" : "RECONECTANDO…";
}
function updTopics() { $("#topics").textContent = `${Hub.subs.size} tópicos`; }

// ── contexto de pantalla (todo lo que se registra se limpia al salir) ──────
function makeCtx() {
  const cleanups = [];
  let disposed = false;
  // Un render asíncrono puede terminar después de cambiar de pantalla: lo que registre
  // entonces se limpia en el acto en lugar de quedar suscrito para siempre.
  const keep = (fn) => { if (disposed) { try { fn(); } catch { /* */ } } else cleanups.push(fn); };
  return {
    get disposed() { return disposed; },
    sub(topic, cb) { keep(Hub.sub(topic, cb)); },
    every(fn, ms) { const id = setInterval(fn, ms); keep(() => clearInterval(id)); },
    on(el, ev, fn) { el.addEventListener(ev, fn); keep(() => el.removeEventListener(ev, fn)); },
    add(fn) { keep(fn); },
    dispose() { disposed = true; cleanups.splice(0).forEach((f) => { try { f(); } catch { /* */ } }); },
  };
}

// ── componentes reutilizables ───────────────────────────────────────────────
function panel(title, body = "", extra = "", cls_ = "") {
  return `<section class="panel ${cls_}"><header>${title}<span class="sp"></span>${extra}</header><div class="body">${body}</div></section>`;
}

/** Tabla de cotizaciones en vivo: cada fila escucha market:quote:<SYM>. */
function liveQuotes(ctx, container, symbols, { cols = ["sym", "last", "chg", "pct"], onRemove } = {}) {
  const head = { sym: "Símbolo", name: "Nombre", last: "Último", chg: "Var", pct: "Var %", high: "Máx", low: "Mín", vol: "Volumen" };
  container.innerHTML = `<table><thead><tr>${cols.map((c) => `<th class="${c === "sym" || c === "name" ? "" : "num"}">${head[c]}</th>`).join("")}${onRemove ? "<th></th>" : ""}</tr></thead><tbody>${symbols.map((s) => `<tr class="click" data-sym="${esc(s)}">${cols.map((c) => `<td class="${c === "sym" ? "sym" : c === "name" ? "muted" : "num"}" data-c="${c}">${c === "sym" ? esc(s) : "…"}</td>`).join("")}${onRemove ? `<td class="num"><button class="btn small" data-rm="${esc(s)}">✕</button></td>` : ""}</tr>`).join("")}</tbody></table>`;
  ctx.on(container, "click", (e) => {
    const rm = e.target.closest("[data-rm]");
    if (rm) { e.stopPropagation(); onRemove(rm.dataset.rm); return; }
    const tr = e.target.closest("tr[data-sym]");
    if (tr) go("equity", tr.dataset.sym);
  });
  for (const s of symbols) {
    const tr = container.querySelector(`tr[data-sym="${CSS.escape(s)}"]`);
    let prev = null;
    ctx.sub(`market:quote:${s}`, (q, m) => {
      if (!q) { if (m && m.type === "error" && !m.stale) tr.querySelector('[data-c="last"]').textContent = "n/d"; return; }
      const set = (c, html, k) => { const td = tr.querySelector(`[data-c="${c}"]`); if (td) { td.innerHTML = html; if (k) td.className = "num " + k; } };
      set("sym", esc(q.symbol) + (q.source === "sim" ? '<span class="src">SIM</span>' : ""));
      set("name", esc(q.name));
      set("last", fmtPx(q.price));
      set("chg", fmtChg(q.change, q.price), cls(q.change));
      set("pct", fmtPct(q.change_pct), cls(q.change_pct));
      set("high", fmtPx(q.high)); set("low", fmtPx(q.low)); set("vol", fmtVol(q.volume));
      if (prev != null && q.price !== prev) {
        const td = tr.querySelector('[data-c="last"]');
        td.classList.remove("flash-up", "flash-down"); void td.offsetWidth;
        td.classList.add(q.price > prev ? "flash-up" : "flash-down");
      }
      prev = q.price;
    });
  }
}

function chartPanel(ctx, el, symbol, { period = "6mo", height = 340 } = {}) {
  el.innerHTML = `<div class="row" style="padding:4px 6px">
      <div class="seg" data-k="period">${["1d", "5d", "1mo", "6mo", "1y", "5y"].map((p) => `<button data-v="${p}" class="${p === period ? "on" : ""}">${p.toUpperCase()}</button>`).join("")}</div>
      <div class="seg" data-k="type"><button data-v="candle" class="on">VELAS</button><button data-v="line">LÍNEA</button></div>
      <span class="dim" data-info></span></div>
    <div class="chartbox" style="height:${height}px"><canvas class="chart"></canvas></div>`;
  const chart = new FChart(el.querySelector("canvas"));
  let type = "candle", candles = [], prevClose = null;
  async function load(p) {
    period = p;
    el.querySelector("[data-info]").textContent = "cargando…";
    const r = await api(`/market/history/${encodeURIComponent(symbol)}?period=${p}`);
    if (!r.success) { el.querySelector("[data-info]").textContent = r.message; return; }
    candles = r.data.candles;
    chart.setCandles(candles, { type, sma: p === "1d" || p === "5d" ? [] : [20, 50], prevClose, label: symbol });
    el.querySelector("[data-info]").textContent = `${candles.length} velas · ${r.data.interval} · ${r.data.source}`;
  }
  ctx.on(el, "click", (e) => {
    const b = e.target.closest(".seg button"); if (!b) return;
    const seg = b.parentElement; $$("button", seg).forEach((x) => x.classList.toggle("on", x === b));
    if (seg.dataset.k === "period") load(b.dataset.v);
    else { type = b.dataset.v; chart.setCandles(candles, { type, sma: chart.opts.sma, prevClose, label: symbol }); }
  });
  ctx.sub(`market:quote:${symbol}`, (q) => { // la última vela sigue al precio en vivo
    if (!q) return;
    prevClose = q.prev_close;
    if (!candles.length) return;
    const last = candles[candles.length - 1];
    last.c = q.price; last.h = Math.max(last.h, q.price); last.l = Math.min(last.l, q.price);
    chart.opts.prevClose = prevClose; chart.setCandles(candles, chart.opts);
  });
  load(period);
}

function orderTicket(ctx, el, symbol) {
  el.innerHTML = `<div class="form">
    <label>Símbolo</label><input class="f" data-f="symbol" value="${esc(symbol || "")}">
    <label>Lado</label><div class="seg" data-k="side"><button data-v="buy" class="on">COMPRA</button><button data-v="sell">VENTA</button></div>
    <label>Cantidad</label><input class="f" data-f="qty" type="number" min="0" step="any" value="10">
    <label>Tipo</label><div class="seg" data-k="type"><button data-v="market" class="on">MKT</button><button data-v="limit">LMT</button><button data-v="stop">STP</button></div>
    <label>Precio</label><input class="f" data-f="price" type="number" step="any" placeholder="solo LMT / STP" disabled>
    <span></span><button class="btn buy" data-go>ENVIAR ORDEN (PAPER)</button></div>
    <div class="dim" style="margin-top:6px">Dinero simulado. Las órdenes LMT/STP las ejecuta el OrderMatcher al cruzar precio.</div>`;
  const st = { side: "buy", type: "market" };
  ctx.on(el, "click", async (e) => {
    const b = e.target.closest(".seg button");
    if (b) {
      const seg = b.parentElement; $$("button", seg).forEach((x) => x.classList.toggle("on", x === b));
      st[seg.dataset.k] = b.dataset.v;
      el.querySelector('[data-f="price"]').disabled = st.type === "market";
      const go_ = el.querySelector("[data-go]"); go_.className = "btn " + (st.side === "buy" ? "buy" : "sell");
      return;
    }
    if (!e.target.closest("[data-go]")) return;
    const f = (k) => el.querySelector(`[data-f="${k}"]`).value.trim();
    const body = { symbol: f("symbol"), side: st.side, qty: parseFloat(f("qty")), type: st.type };
    if (st.type === "limit") body.limit_price = parseFloat(f("price"));
    if (st.type === "stop") body.stop_price = parseFloat(f("price"));
    const r = await api("/paper/orders", { method: "POST", body });
    toast(r.success ? `${r.message}: ${body.side.toUpperCase()} ${body.qty} ${body.symbol.toUpperCase()}${r.data.filled_price ? " @ " + fmtPx(r.data.filled_price) : ""}` : r.message, r.success ? "ok" : "err");
  });
}

// ── pantallas ───────────────────────────────────────────────────────────────
const SETS = {
  "EE. UU.": ["^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX"],
  "Europa y Asia": ["^IBEX", "^GDAXI", "^FTSE", "^N225", "^HSI"],
  "Divisas": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDMXN=X"],
  "Materias primas": ["GC=F", "SI=F", "CL=F", "NG=F"],
  "Cripto": ["BTC-USD", "ETH-USD", "SOL-USD"],
  "Megacaps": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"],
};
const TAPE = ["^GSPC", "^DJI", "^IXIC", "^IBEX", "^GDAXI", "^FTSE", "^N225", "EURUSD=X", "GC=F", "CL=F", "BTC-USD", "ETH-USD", "^VIX", "^TNX"];

async function firstWatchlist() {
  const r = await api("/v1/watchlists");
  return r.success && r.data.length ? r.data[0] : { name: "—", symbols: [] };
}

function newsList(items) {
  if (!items || !items.length) return '<div class="empty">Sin titulares</div>';
  return items.map((n) => `<div class="news-item"><div class="t">${safeUrl(n.link) ? `<a href="${esc(safeUrl(n.link))}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}</div>
    <div class="m"><span class="chip ${esc(n.sentiment)}">${esc(n.sentiment)}</span> ${esc(n.source)} · hace ${ago(n.published)}</div></div>`).join("");
}

const SCREENS = {
  dashboard: { key: "F1", label: "DASHBOARD", async render(el, ctx) {
    el.innerHTML = `<div class="kpis" id="d-kpis" style="margin-bottom:6px"></div><div class="grid dash">
      ${panel("Monitor de mercado", "", "<small>DataHub · market:quote:*</small>", "")}
      ${panel(`Gráfico · <span class="cyan">${esc(S.focus)}</span>`, "", '<button class="btn small" data-eq>ABRIR ▸</button>', "chartpanel")}
      ${panel("Watchlist", "", '<small id="d-wln"></small>')}
      ${panel("Titulares", "", "<small>news:top</small>", "span3")}</div>`;
    const [mon, ch, wl, nw] = $$(".panel .body", el);
    mon.classList.add("flush"); wl.classList.add("flush"); ch.classList.add("flush");
    liveQuotes(ctx, mon, ["^GSPC", "^IXIC", "^IBEX", "^GDAXI", "EURUSD=X", "GC=F", "CL=F", "BTC-USD", "^VIX"]);
    chartPanel(ctx, ch, S.focus, { height: 300 });
    ctx.on($("[data-eq]", el), "click", () => go("equity", S.focus));
    const w = await firstWatchlist();
    $("#d-wln").textContent = w.name;
    liveQuotes(ctx, wl, w.symbols.slice(0, 12));
    nw.style.maxHeight = "260px";
    ctx.sub("news:top", (items) => { if (items) nw.innerHTML = newsList(items.slice(0, 14)); });
    const kp = $("#d-kpis");
    const paint = (a) => { if (!a) return; kp.innerHTML = [["Equity paper", fmtN(a.equity)], ["Caja", fmtN(a.cash)], ["P&L total", `<span class="${cls(a.total_pnl)}">${fmtN(a.total_pnl)} (${fmtPct(a.total_pnl_pct)})</span>`], ["Posiciones", a.positions.length], ["Órdenes abiertas", a.open_orders], ["Créditos", fmtN(S.user.credit_balance)]].map(([l, v]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join(""); };
    const a = await api("/paper/account"); if (a.success) paint(a.data);
    ctx.sub(`paper:${S.user.id}:account`, paint);
  } },

  markets: { key: "F2", label: "MARKETS", render(el, ctx) {
    el.innerHTML = `<div class="grid g3">${Object.keys(SETS).map((k) => panel(esc(k), "", `<small>${SETS[k].length}</small>`)).join("")}</div>`;
    $$(".panel .body", el).forEach((b, i) => { b.classList.add("flush"); liveQuotes(ctx, b, Object.values(SETS)[i], { cols: ["sym", "last", "chg", "pct", "high", "low"] }); });
  } },

  news: { key: "F3", label: "NEWS", render(el, ctx) {
    el.innerHTML = panel("Noticias · RSS agregado, deduplicado, con sentimiento", "", `<input class="f" id="n-q" placeholder="filtrar…" style="width:220px">`);
    const body = $(".body", el); let items = [];
    const paint = () => {
      const q = $("#n-q").value.toLowerCase();
      const list = items.filter((n) => !q || n.title.toLowerCase().includes(q) || n.summary.toLowerCase().includes(q));
      body.innerHTML = list.length ? list.map((n) => `<div class="news-item"><div class="t">${safeUrl(n.link) ? `<a href="${esc(safeUrl(n.link))}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}</div><div class="m"><span class="chip ${esc(n.sentiment)}">${esc(n.sentiment)} ${n.sentiment_score}</span> ${esc(n.source)} · ${new Date(n.published * 1000).toLocaleString("es-ES")}</div>${n.summary ? `<p>${esc(n.summary)}</p>` : ""}</div>`).join("") : '<div class="empty">Sin resultados</div>';
    };
    ctx.on($("#n-q"), "input", paint);
    ctx.sub("news:top", (d) => { if (d) { items = d; paint(); } });
  } },

  portfolio: { key: "F4", label: "PORTFOLIO", async render(el, ctx) {
    el.innerHTML = `<div class="kpis" id="p-kpis" style="margin-bottom:6px"></div><div class="grid g2">
      ${panel("Posiciones", "", '<button class="btn small" id="p-reset">RESET CUENTA</button>', "span2")}
      ${panel("Ticket de orden", "")}${panel("Órdenes", "", "<small>paper:&lt;uid&gt;:account</small>")}</div>`;
    const [posEl, tkEl, ordEl] = $$(".panel .body", el);
    posEl.classList.add("flush"); ordEl.classList.add("flush");
    orderTicket(ctx, tkEl, S.focus);
    let acc = null; const quoteSubs = new Map();
    const paint = () => {
      if (!acc) return;
      let mv = 0, upnl = 0;
      for (const p of acc.positions) { p.market_value = p.last * p.qty; p.unrealized_pnl = (p.last - p.avg_price) * p.qty; mv += p.market_value; upnl += p.unrealized_pnl; }
      const eq = acc.cash + mv, tot = eq - acc.initial_cash;
      $("#p-kpis").innerHTML = [["Equity", fmtN(eq)], ["Caja", fmtN(acc.cash)], ["Valor posiciones", fmtN(mv)], ["P&L no realizado", `<span class="${cls(upnl)}">${fmtN(upnl)}</span>`], ["P&L realizado", `<span class="${cls(acc.realized_pnl)}">${fmtN(acc.realized_pnl)}</span>`], ["P&L total", `<span class="${cls(tot)}">${fmtN(tot)} (${fmtPct(tot / acc.initial_cash * 100)})</span>`]].map(([l, v]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
      posEl.innerHTML = acc.positions.length ? `<table><thead><tr><th>Símbolo</th><th class="num">Cant.</th><th class="num">Precio medio</th><th class="num">Último</th><th class="num">Valor</th><th class="num">P&L</th><th class="num">P&L %</th><th></th></tr></thead><tbody>${acc.positions.map((p) => `<tr class="click" data-sym="${esc(p.symbol)}"><td class="sym">${esc(p.symbol)}</td><td class="num">${fmtN(p.qty, 4).replace(/\.?0+$/, "")}</td><td class="num">${fmtPx(p.avg_price)}</td><td class="num">${fmtPx(p.last)}</td><td class="num">${fmtN(p.market_value)}</td><td class="num ${cls(p.unrealized_pnl)}">${fmtN(p.unrealized_pnl)}</td><td class="num ${cls(p.unrealized_pnl)}">${fmtPct((p.last / p.avg_price - 1) * 100)}</td><td class="num"><button class="btn small sell" data-close="${esc(p.symbol)}" data-qty="${p.qty}">CERRAR</button></td></tr>`).join("")}</tbody></table>` : '<div class="empty">Sin posiciones — usa el ticket o el comando <code>BUY 10 AAPL</code></div>';
      ordEl.innerHTML = acc.orders && acc.orders.length ? `<table><thead><tr><th>#</th><th>Hora</th><th>Símbolo</th><th>Lado</th><th class="num">Cant.</th><th>Tipo</th><th class="num">Precio</th><th>Estado</th><th>Origen</th><th></th></tr></thead><tbody>${acc.orders.map((o) => `<tr><td class="dim">${o.id}</td><td class="dim">${new Date(o.created_at * 1000).toLocaleTimeString("es-ES")}</td><td class="sym">${esc(o.symbol)}</td><td class="${o.side === "buy" ? "pos" : "neg"}">${o.side.toUpperCase()}</td><td class="num">${o.qty}</td><td>${o.type.toUpperCase()}</td><td class="num">${fmtPx(o.filled_price || o.limit_price || o.stop_price)}</td><td class="${o.status === "filled" ? "pos" : o.status === "open" ? "warn" : "dim"}" title="${esc(o.note)}">${o.status.toUpperCase()}</td><td class="dim">${esc(o.source)}</td><td>${o.status === "open" ? `<button class="btn small" data-cancel="${o.id}">✕</button>` : ""}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Sin órdenes</div>';
    };
    const setAcc = (a) => {
      if (!a) return; acc = a;
      const want = new Set(a.positions.map((p) => p.symbol));
      for (const [s, un] of quoteSubs) if (!want.has(s)) { un(); quoteSubs.delete(s); }
      for (const s of want) if (!quoteSubs.has(s)) quoteSubs.set(s, Hub.sub(`market:quote:${s}`, (q) => { if (!q || !acc) return; const p = acc.positions.find((x) => x.symbol === s); if (p) { p.last = q.price; paint(); } }));
      paint();
    };
    ctx.add(() => quoteSubs.forEach((un) => un()));
    ctx.on(el, "click", async (e) => {
      const c = e.target.closest("[data-cancel]"), x = e.target.closest("[data-close]");
      if (c) { const r = await api(`/paper/orders/${c.dataset.cancel}`, { method: "DELETE" }); toast(r.message, r.success ? "ok" : "err"); }
      else if (x) { const r = await api("/paper/orders", { method: "POST", body: { symbol: x.dataset.close, side: "sell", qty: parseFloat(x.dataset.qty) } }); toast(r.message, r.success ? "ok" : "err"); }
      else if (e.target.id === "p-reset") { if (confirm("¿Resetear la cuenta paper a 100.000 USD?")) { const r = await api("/paper/reset", { method: "POST" }); toast(r.message, "ok"); } }
      else { const tr = e.target.closest("tr[data-sym]"); if (tr) go("equity", tr.dataset.sym); }
    });
    const r = await api("/paper/account"); if (r.success) setAcc(r.data);
    ctx.sub(`paper:${S.user.id}:account`, setAcc);
  } },

  backtest: { key: "F5", label: "BACKTEST", render(el, ctx) {
    const kpi = (rows) => rows.map(([l, v, c]) => `<div class="kpi"><div class="l">${l}</div><div class="v ${c || ""}">${v}</div></div>`).join("");
    const opt = (v, cur) => `<option ${v === cur ? "selected" : ""}>${v}</option>`;
    el.innerHTML = `<div class="grid g2">${panel("Estrategia · cruce de medias (SMA) · largo / fuera", `<div class="form">
      <label>Símbolo</label><input class="f" id="b-sym" value="${esc(S.focus)}"><label>Periodo</label><select class="f" id="b-per">${["1y", "2y", "5y", "10y"].map((p) => opt(p, "5y")).join("")}</select>
      <label>SMA rápida / lenta</label><div class="row"><input class="f" id="b-f" type="number" value="20" style="width:80px"><input class="f" id="b-s" type="number" value="50" style="width:80px"></div>
      <label>Capital</label><input class="f" id="b-c" type="number" value="10000">
      <label>Comisión / slippage (pb por lado)</label><div class="row"><input class="f" id="b-com" type="number" value="5" step="any" style="width:80px"><input class="f" id="b-slp" type="number" value="5" step="any" style="width:80px"></div>
      <span></span><button class="btn primary" id="b-run">EJECUTAR BACKTEST</button></div>
      <div id="b-kpis" class="kpis" style="margin-top:10px"></div>`)}
      ${panel('Curva de equity · <span class="muted">estrategia vs buy &amp; hold (gris)</span>', '<div class="chartbox" style="height:300px"><canvas class="chart" id="b-chart"></canvas></div>')}
      ${panel("Robustez · Monte Carlo (bootstrap, 1 año)", '<div class="empty">—</div>')}
      ${panel("Operaciones", '<div class="empty">Ejecuta un backtest</div>')}
      ${panel("Validación fuera de muestra", `<div class="row"><button class="btn" id="b-ho">HOLD-OUT 70/30 (5 años)</button><button class="btn" id="b-wf">WALK-FORWARD (10 años)</button><span class="dim">Re-optimiza solo con datos pasados y mide en datos no vistos.</span></div><div id="b-val" style="margin-top:8px"><div class="empty">El rendimiento optimizado sobre todo el histórico está sesgado al alza: usa estas pruebas para ver qué sobrevive fuera de muestra.</div></div><div class="chartbox" style="height:240px;display:none" id="b-wfbox"><canvas class="chart" id="b-wfchart"></canvas></div>`, "", "span2")}
      ${panel("Supuestos del motor", '<div id="b-ass" class="help"></div>', "", "span2")}</div>`;
    const chart = new FChart($("#b-chart")), wfChart = new FChart($("#b-wfchart"));
    const [, , mcEl, trEl] = $$(".panel .body", el);
    const costs = () => ({ commission_bps: +$("#b-com").value, slippage_bps: +$("#b-slp").value });
    const run = async () => {
      const body = { symbol: $("#b-sym").value, period: $("#b-per").value, fast: +$("#b-f").value, slow: +$("#b-s").value, initial_cash: +$("#b-c").value, ...costs() };
      $("#b-run").disabled = true;
      const r = await api("/backtest/sma", { method: "POST", body });
      $("#b-run").disabled = false;
      if (!r.success) return toast(r.message, "err");
      const d = r.data, pf = d.profit_factor;
      $("#b-kpis").innerHTML = kpi([["Rentabilidad", fmtFrac(d.total_return), cls(d.total_return)], ["Buy & hold", fmtFrac(d.buy_and_hold_return), cls(d.buy_and_hold_return)], ["Exceso vs B&H", fmtFrac(d.excess_return), cls(d.excess_return)], ["CAGR", fmtFrac(d.cagr), cls(d.cagr)], ["Sharpe", fmtN(d.sharpe)], ["Sortino", fmtN(d.sortino)], ["Máx. drawdown", fmtFrac(d.max_drawdown), "neg"], ["Calmar", fmtN(d.calmar)], ["Exposición", fmtFrac(d.exposure).replace("+", "")], ["Costes pagados", fmtN(d.costs_paid)], ["Operaciones cerradas", d.round_trips], ["Win rate", d.win_rate == null ? "—" : fmtFrac(d.win_rate).replace("+", "")], ["Profit factor", pf == null ? "—" : fmtN(pf)], ["Trade medio", d.avg_trade == null ? "—" : fmtFrac(d.avg_trade), cls(d.avg_trade)]]);
      chart.setLine(d.equity_curve.map((p) => ({ t: p.t, v: p.equity, b: p.benchmark })), { label: `${d.strategy} · ${d.symbol}${d.source === "sim" ? " · SIM" : ""}` });
      const mc = d.monte_carlo;
      mcEl.innerHTML = mc ? `<div class="kpis">${kpi([["Rentab. 1a · p5", fmtFrac(mc.return_p5), cls(mc.return_p5)], ["Rentab. 1a · mediana", fmtFrac(mc.return_p50), cls(mc.return_p50)], ["Rentab. 1a · p95", fmtFrac(mc.return_p95), cls(mc.return_p95)], ["Prob. de pérdida 1a", fmtFrac(mc.prob_loss).replace("+", ""), "warn"], ["Máx. DD mediano", fmtFrac(mc.max_drawdown_p50), "neg"], ["Máx. DD peor 5%", fmtFrac(mc.max_drawdown_p5), "neg"]])}</div><div class="dim" style="margin-top:6px">${mc.simulations} simulaciones remuestreando los retornos diarios de la estrategia (semilla ${mc.seed}). Ignora la autocorrelación: es una banda orientativa, no una predicción.</div>` : '<div class="empty">—</div>';
      trEl.classList.add("flush"); trEl.style.maxHeight = "330px";
      trEl.innerHTML = d.trade_log.length ? `<table><thead><tr><th>Fecha</th><th>Lado</th><th class="num">Precio (con slippage)</th><th class="num">P&L operación</th></tr></thead><tbody>${d.trade_log.slice().reverse().map((t) => `<tr><td>${new Date(t.t * 1000).toLocaleDateString("es-ES")}</td><td class="${t.side === "buy" ? "pos" : "neg"}">${t.side.toUpperCase()}</td><td class="num">${fmtPx(t.price)}</td><td class="num ${cls(t.pnl_pct)}">${t.pnl_pct == null ? "" : fmtFrac(t.pnl_pct)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Sin operaciones en el periodo</div>';
      $("#b-ass").innerHTML = d.assumptions.map((x) => `<div>• ${esc(x)}</div>`).join("");
    };
    const valEl = $("#b-val");
    ctx.on($("#b-run"), "click", run);
    ctx.on($("#b-ho"), "click", async () => {
      valEl.innerHTML = '<div class="empty">Optimizando en el 70% inicial y evaluando en el 30% reservado…</div>'; $("#b-wfbox").style.display = "none";
      const r = await tool("optimize_sma_cross", { symbol: $("#b-sym").value, ...costs() });
      if (!r.success) { valEl.innerHTML = `<div class="empty">${esc(r.message)}</div>`; return; }
      const d = r.data, day = (t) => new Date(t * 1000).toLocaleDateString("es-ES");
      valEl.innerHTML = `<div class="help">In-sample ${day(d.in_sample.from)}–${day(d.in_sample.to)} · hold-out ${day(d.hold_out.from)}–${day(d.hold_out.to)} (B&H en hold-out ${fmtFrac(d.hold_out.buy_and_hold_return)}) · ${d.tested} combinaciones. <span class="warn">${esc(d.warning)}</span></div>
        <table><thead><tr><th class="num">Rápida</th><th class="num">Lenta</th><th class="num">Sharpe IS</th><th class="num">Rentab. IS</th><th class="num">Sharpe OOS</th><th class="num">Rentab. OOS</th><th class="num">Máx DD OOS</th></tr></thead><tbody>${d.top10.map((x) => `<tr class="click" data-f="${x.fast}" data-s="${x.slow}"><td class="num">${x.fast}</td><td class="num">${x.slow}</td><td class="num dim">${fmtN(x.sharpe)}</td><td class="num dim">${fmtFrac(x.total_return)}</td><td class="num ${cls(x.oos_sharpe)}">${fmtN(x.oos_sharpe)}</td><td class="num ${cls(x.oos_return)}">${fmtFrac(x.oos_return)}</td><td class="num neg">${fmtFrac(x.oos_max_drawdown)}</td></tr>`).join("")}</tbody></table>`;
    });
    ctx.on($("#b-wf"), "click", async () => {
      valEl.innerHTML = '<div class="empty">Walk-forward: re-optimizando cada 6 meses con los 2 años previos…</div>';
      const r = await api("/backtest/walk-forward", { method: "POST", body: { symbol: $("#b-sym").value, ...costs() } });
      if (!r.success) { valEl.innerHTML = `<div class="empty">${esc(r.message)}</div>`; return; }
      const d = r.data, day = (t) => new Date(t * 1000).toLocaleDateString("es-ES");
      valEl.innerHTML = `<div class="kpis" style="margin-bottom:8px">${kpi([["Rentab. OOS encadenada", fmtFrac(d.oos.total_return), cls(d.oos.total_return)], ["Buy & hold mismo tramo", fmtFrac(d.benchmark.total_return), cls(d.benchmark.total_return)], ["Exceso", fmtFrac(d.excess_return), cls(d.excess_return)], ["Sharpe OOS", fmtN(d.oos.sharpe)], ["Máx. DD OOS", fmtFrac(d.oos.max_drawdown), "neg"], ["Eficiencia WF", d.wf_efficiency == null ? "—" : fmtN(d.wf_efficiency), d.wf_efficiency != null && d.wf_efficiency < 0.5 ? "warn" : ""], ["Estabilidad parámetros", fmtFrac(d.param_stability).replace("+", "")]])}</div>
        <table><thead><tr><th>Entrenamiento</th><th>Prueba (OOS)</th><th class="num">Parámetros</th><th class="num">Sharpe IS</th><th class="num">Rentab. OOS</th><th class="num">B&H</th><th class="num">Ops</th></tr></thead><tbody>${d.splits.map((x) => `<tr><td class="dim">${day(x.train_from)} → ${day(x.train_to)}</td><td>${day(x.test_from)} → ${day(x.test_to)}</td><td class="num">${x.fast}/${x.slow}</td><td class="num dim">${fmtN(x.is_sharpe)}</td><td class="num ${cls(x.oos_return)}">${fmtFrac(x.oos_return)}</td><td class="num ${cls(x.benchmark_return)}">${fmtFrac(x.benchmark_return)}</td><td class="num">${x.oos_trades}</td></tr>`).join("")}</tbody></table>
        <div class="dim" style="margin-top:6px">Eficiencia WF = Sharpe OOS / Sharpe IS medio (por debajo de ~0,5 suele indicar sobreajuste). Estabilidad = 1 si siempre se eligieron los mismos parámetros.</div>`;
      $("#b-wfbox").style.display = "";
      wfChart.setLine(d.equity_curve.map((p) => ({ t: p.t, v: p.equity, b: p.benchmark })), { label: `Walk-forward OOS · ${d.symbol}${d.source === "sim" ? " · SIM" : ""}` });
    });
    ctx.on(valEl, "click", (e) => { const tr = e.target.closest("tr[data-f]"); if (tr) { $("#b-f").value = tr.dataset.f; $("#b-s").value = tr.dataset.s; run(); } });
    run();
  } },

  watchlist: { key: "F6", label: "WATCHLIST", async render(el, ctx) {
    el.innerHTML = panel("Watchlists · sincronizadas por /v1 (finceptgo)", "", `<div class="seg" id="w-tabs"></div><input class="f" id="w-add" placeholder="añadir símbolo + Enter" style="width:170px"><button class="btn small" id="w-new">+ LISTA</button><button class="btn small" id="w-del">BORRAR LISTA</button>`);
    const body = $(".body", el); body.classList.add("flush");
    let lists = [], cur = 0, inner = null;
    const show = () => {
      $("#w-tabs").innerHTML = lists.map((l, i) => `<button data-i="${i}" class="${i === cur ? "on" : ""}">${esc(l.name)}</button>`).join("");
      if (inner) inner.dispose();
      inner = makeCtx();
      const l = lists[cur];
      if (!l) { body.innerHTML = '<div class="empty">Sin listas</div>'; return; }
      if (!l.symbols.length) { body.innerHTML = '<div class="empty">Lista vacía — añade símbolos arriba</div>'; return; }
      liveQuotes(inner, body, l.symbols, { cols: ["sym", "name", "last", "chg", "pct", "high", "low", "vol"], onRemove: (s) => save(l.symbols.filter((x) => x !== s)) });
    };
    ctx.add(() => inner && inner.dispose());
    const save = async (symbols) => {
      const l = lists[cur];
      const r = await api(`/v1/watchlists/${l.id}`, { method: "PUT", body: { name: l.name, symbols } });
      if (!r.success) return toast(r.message, "err");
      lists[cur] = r.data; show();
    };
    const reload = async () => { const r = await api("/v1/watchlists"); lists = r.success ? r.data : []; cur = Math.min(cur, Math.max(0, lists.length - 1)); show(); };
    ctx.on($("#w-tabs"), "click", (e) => { const b = e.target.closest("button"); if (b) { cur = +b.dataset.i; show(); } });
    ctx.on($("#w-add"), "keydown", (e) => { if (e.key === "Enter" && e.target.value.trim()) { const s = e.target.value.trim().toUpperCase(); e.target.value = ""; if (lists[cur]) save([...lists[cur].symbols, s]); } });
    ctx.on($("#w-new"), "click", async () => { const n = prompt("Nombre de la nueva lista"); if (!n) return; const r = await api("/v1/watchlists", { method: "POST", body: { name: n, symbols: [] } }); if (!r.success) return toast(r.message, "err"); await reload(); cur = lists.length - 1; show(); });
    ctx.on($("#w-del"), "click", async () => { const l = lists[cur]; if (!l || !confirm(`¿Borrar "${l.name}"?`)) return; await api(`/v1/watchlists/${l.id}`, { method: "DELETE" }); cur = 0; reload(); });
    reload();
  } },

  quantlib: { key: "F7", label: "QUANTLIB", render(el, ctx) {
    el.innerHTML = `<div class="grid g2">${panel("Black-Scholes · precio y griegas", `<div class="form">
      <label>Tipo</label><div class="seg" id="q-type"><button data-v="call" class="on">CALL</button><button data-v="put">PUT</button></div>
      <label>Spot</label><input class="f" id="q-S" type="number" value="100" step="any"><label>Strike</label><input class="f" id="q-K" type="number" value="105" step="any">
      <label>Días</label><input class="f" id="q-T" type="number" value="30"><label>Tipo interés %</label><input class="f" id="q-r" type="number" value="4" step="any">
      <label>Volatilidad %</label><input class="f" id="q-v" type="number" value="25" step="any"><label>Dividendo %</label><input class="f" id="q-q" type="number" value="0" step="any">
      <span></span><div class="row"><button class="btn primary" id="q-go">CALCULAR</button><button class="btn" id="q-spot">SPOT DE ${esc(S.focus)}</button></div></div>
      <div id="q-out" class="kpis" style="margin-top:10px"></div>
      <div class="row" style="margin-top:10px"><label class="dim">PRIMA DE MERCADO</label><input class="f" id="q-mkt" type="number" step="any" style="width:100px"><button class="btn" id="q-iv">VOL. IMPLÍCITA</button><span id="q-ivout" class="cyan"></span></div>`)}
      ${panel("Riesgo de un activo", `<div class="row"><input class="f" id="r-sym" value="${esc(S.focus)}" style="width:120px"><select class="f" id="r-per"><option>6mo</option><option selected>1y</option><option>2y</option><option>5y</option></select><select class="f" id="r-cf"><option value="0.95">VaR 95%</option><option value="0.99">VaR 99%</option></select><button class="btn primary" id="r-go">ANALIZAR</button></div><div id="r-out" class="kpis" style="margin-top:10px"></div>`)}</div>`;
    let type = "call";
    const v = (id) => parseFloat($(id).value);
    const body = () => ({ spot: v("#q-S"), strike: v("#q-K"), time_to_expiry: v("#q-T") / 365, rate: v("#q-r") / 100, volatility: v("#q-v") / 100, dividend_yield: v("#q-q") / 100, option_type: type });
    const calc = async () => {
      const r = await api("/quantlib/pricing/bs/greeks", { method: "POST", body: body() });
      if (!r.success) return toast(r.message, "err");
      const g = r.data;
      $("#q-out").innerHTML = [["Prima", fmtN(g.price, 4)], ["Delta", fmtN(g.delta, 4)], ["Gamma", fmtN(g.gamma, 5)], ["Vega (1 pt)", fmtN(g.vega, 4)], ["Theta (día)", fmtN(g.theta, 4)], ["Rho (1 pt)", fmtN(g.rho, 4)]].map(([l, x]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${x}</div></div>`).join("");
      $("#q-mkt").value = g.price.toFixed(4);
    };
    ctx.on($("#q-type"), "click", (e) => { const b = e.target.closest("button"); if (!b) return; type = b.dataset.v; $$("#q-type button").forEach((x) => x.classList.toggle("on", x === b)); calc(); });
    ctx.on($("#q-go"), "click", calc);
    ctx.on($("#q-spot"), "click", async () => { const r = await api(`/market/price/${encodeURIComponent(S.focus)}`); if (r.success) { $("#q-S").value = r.data.price.toFixed(2); $("#q-K").value = (Math.round(r.data.price / 5) * 5).toFixed(0); calc(); } });
    ctx.on($("#q-iv"), "click", async () => { const b = body(); const r = await api("/quantlib/pricing/bs/implied-vol", { method: "POST", body: { price: v("#q-mkt"), spot: b.spot, strike: b.strike, time_to_expiry: b.time_to_expiry, rate: b.rate, option_type: type } }); $("#q-ivout").textContent = r.success ? `σ implícita = ${(r.data.implied_volatility * 100).toFixed(3)}%` : r.message; });
    ctx.on($("#r-go"), "click", async () => {
      const r = await api(`/market/risk/${encodeURIComponent($("#r-sym").value)}?period=${$("#r-per").value}&confidence=${$("#r-cf").value}`);
      if (!r.success) return toast(r.message, "err");
      const m = r.data;
      $("#r-out").innerHTML = [["Rentab. total", fmtFrac(m.total_return), cls(m.total_return)], ["Rentab. anual", fmtFrac(m.annualized_return), cls(m.annualized_return)], ["Vol. anual", fmtFrac(m.annualized_volatility).replace("+", ""), ""], ["Sharpe", fmtN(m.sharpe), ""], ["Sortino", fmtN(m.sortino), ""], ["Máx. drawdown", fmtFrac(m.max_drawdown), "neg"], [`VaR hist. ${m.confidence * 100}%`, fmtFrac(-m.var_historical), "neg"], ["CVaR hist.", fmtFrac(-m.cvar_historical), "neg"], ["VaR paramétrico", fmtFrac(-m.var_parametric), "neg"], ["Mejor día", fmtFrac(m.best_day), "pos"], ["Peor día", fmtFrac(m.worst_day), "neg"], ["Fuente", m.source.toUpperCase(), m.source === "sim" ? "warn" : ""]].map(([l, x, c]) => `<div class="kpi"><div class="l">${l}</div><div class="v ${c}">${x}</div></div>`).join("");
    });
    calc(); $("#r-go").click();
  } },

  macro: { key: "F8", label: "MACRO", async render(el, ctx) {
    el.innerHTML = `<div class="grid g2">${panel("Indicadores clave · DBnomics", '<div class="empty">Cargando series…</div>', "<small>BLS · FED · BCE · Eurostat · BEA</small>")}
      ${panel('Serie · <span id="m-title" class="cyan">—</span>', '<div class="chartbox" style="height:300px"><canvas class="chart"></canvas></div><div id="m-meta" class="dim"></div>')}
      ${panel("Buscar datasets en DBnomics", '<div class="row"><input class="f" id="m-q" placeholder="inflation, gdp, unemployment…" style="flex:1"><button class="btn" id="m-go">BUSCAR</button></div><div id="m-res" style="margin-top:6px"></div>', "", "span2")}</div>`;
    const chart = new FChart($("canvas", el));
    const [cards] = $$(".panel .body", el);
    const presets = (await api("/macro/presets")).data || [];
    const show = async (id, label) => {
      $("#m-title").textContent = label || id;
      const r = await api(`/macro/series?id=${encodeURIComponent(id)}&limit=240`);
      if (!r.success) { $("#m-meta").textContent = r.message; return; }
      const pts = r.data.observations.map((o) => ({ t: Date.parse(o.period.length === 7 ? o.period + "-01" : o.period.replace(/-Q(\d)/, (_, q) => `-${String((q - 1) * 3 + 1).padStart(2, "0")}-01`)) / 1000, v: o.value })).filter((p) => isFinite(p.t));
      chart.setLine(pts, { label: label || id, color: getComputedStyle(document.documentElement).getPropertyValue("--cyan").trim() });
      $("#m-meta").textContent = `${r.data.dataset || ""} · ${r.data.frequency || ""} · último ${r.data.last_period}: ${r.data.last_value} · ${id}`;
    };
    cards.classList.add("flush");
    cards.innerHTML = `<table><thead><tr><th>Indicador</th><th class="num">Último</th><th>Periodo</th><th>Serie</th></tr></thead><tbody>${presets.map((p) => `<tr class="click" data-id="${esc(p.id)}" data-l="${esc(p.label)}"><td>${esc(p.label)}</td><td class="num" data-v>…</td><td class="dim" data-p></td><td class="dim">${esc(p.id.split("/")[0])}</td></tr>`).join("")}</tbody></table>`;
    ctx.on(cards, "click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) show(tr.dataset.id, tr.dataset.l); });
    presets.forEach(async (p, i) => {
      const r = await api(`/macro/series?id=${encodeURIComponent(p.id)}&limit=2`);
      const tr = cards.querySelector(`tr[data-id="${CSS.escape(p.id)}"]`);
      if (!tr) return;
      tr.querySelector("[data-v]").textContent = r.success ? `${r.data.last_value} ${p.unit}` : "n/d";
      tr.querySelector("[data-p]").textContent = r.success ? r.data.last_period : r.message.slice(0, 30);
      if (i === 0 && r.success) show(p.id, p.label);
    });
    const search = async () => {
      const r = await api(`/macro/search?q=${encodeURIComponent($("#m-q").value)}`);
      $("#m-res").innerHTML = !r.success ? `<div class="empty">${esc(r.message)}</div>` : `<table><thead><tr><th>Proveedor</th><th>Dataset</th><th>Nombre</th><th class="num">Series</th></tr></thead><tbody>${r.data.map((d) => `<tr><td class="sym">${esc(d.provider)}</td><td class="cyan">${esc(d.dataset)}</td><td>${esc(d.name)}</td><td class="num">${fmtN(d.series_count, 0)}</td></tr>`).join("")}</tbody></table>`;
    };
    ctx.on($("#m-go"), "click", search);
    ctx.on($("#m-q"), "keydown", (e) => e.key === "Enter" && search());
  } },

  equity: { key: "F9", label: "EQUITY", async render(el, ctx, arg) {
    const sym = (arg || S.focus).toUpperCase();
    S.focus = sym; store.set("focus", sym);
    el.innerHTML = `<div class="quotehead" id="e-head"><span class="sym" style="font-size:20px">${esc(sym)}</span><span class="nm">…</span></div>
      <div class="grid dash">${panel("Datos", "", "")}${panel("Gráfico", "", "", "chartpanel")}${panel("Ticket paper", "")}
      ${panel("Técnico y riesgo", '<div class="empty">…</div>')}${panel("Noticias", '<div class="empty">…</div>', "", "span2")}</div>`;
    const [stEl, chEl, tkEl, taEl, nwEl] = $$(".panel .body", el);
    chEl.classList.add("flush");
    chartPanel(ctx, chEl, sym, { period: "6mo", height: 330 });
    orderTicket(ctx, tkEl, sym);
    ctx.sub(`market:quote:${sym}`, (q) => {
      if (!q) return;
      $("#e-head").innerHTML = `<span class="sym" style="font-size:20px">${esc(q.symbol)}</span><span class="nm">${esc(q.name)} · ${esc(q.exchange)} · ${esc(q.currency)}</span>
        <span class="px">${fmtPx(q.price)}</span><span class="${cls(q.change)}" style="font-size:16px">${q.change >= 0 ? "▲" : "▼"} ${fmtChg(Math.abs(q.change), q.price).replace("+", "")} (${fmtPct(q.change_pct)})</span>
        ${q.source === "sim" ? '<span class="badge sim">DATOS SIMULADOS</span>' : '<span class="badge live">YAHOO</span>'}<span class="dim">actualizado ${new Date(q.ts * 1000).toLocaleTimeString("es-ES")}</span>`;
      stEl.innerHTML = `<table><tbody>${[["Apertura", fmtPx(q.open)], ["Máximo", fmtPx(q.high)], ["Mínimo", fmtPx(q.low)], ["Cierre anterior", fmtPx(q.prev_close)], ["Volumen", fmtVol(q.volume)], ["Máx. 52 sem.", fmtPx(q.fifty_two_week_high)], ["Mín. 52 sem.", fmtPx(q.fifty_two_week_low)], ["Tipo", esc(q.type || "—")]].map(([l, v]) => `<tr><td class="muted">${l}</td><td class="num">${v}</td></tr>`).join("")}</tbody></table>`;
    });
    const [t, r, n] = await Promise.all([tool("get_technicals", { symbol: sym }), api(`/market/risk/${encodeURIComponent(sym)}`), api(`/market/news/${encodeURIComponent(sym)}?limit=12`)]);
    const rows = [];
    if (t.success) { const d = t.data; rows.push(["SMA 20", fmtPx(d.sma20)], ["SMA 50", fmtPx(d.sma50)], ["SMA 200", fmtPx(d.sma200)], ["RSI 14", `<span class="${d.rsi14 > 70 ? "neg" : d.rsi14 < 30 ? "pos" : ""}">${d.rsi14}</span>`], ["Tendencia", `<span class="${d.trend === "uptrend" ? "pos" : d.trend === "downtrend" ? "neg" : "warn"}">${d.trend}</span>`], ["Desde máx. 52s", fmtPct(d.pct_from_high)]); }
    if (r.success) { const m = r.data; rows.push(["Vol. anual", fmtFrac(m.annualized_volatility).replace("+", "")], ["Sharpe 1a", fmtN(m.sharpe)], ["Máx. DD 1a", `<span class="neg">${fmtFrac(m.max_drawdown)}</span>`], ["VaR 95% diario", `<span class="neg">${fmtFrac(-m.var_historical)}</span>`]); }
    taEl.innerHTML = rows.length ? `<table><tbody>${rows.map(([l, v]) => `<tr><td class="muted">${l}</td><td class="num">${v}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">${esc(t.message || r.message)}</div>`;
    nwEl.innerHTML = n.success ? newsList(n.data) : `<div class="empty">${esc(n.message)}</div>`;
  } },

  ai_chat: { key: "F10", label: "AI CHAT", render(el, ctx, arg) {
    let sid = store.get("chat_sid");
    el.innerHTML = `<section class="panel chat"><div class="msgs" id="c-msgs"></div><div class="composer"><textarea class="f" id="c-in" placeholder="Pregunta: «¿Cómo van NVDA y AAPL?», «riesgo de TSLA», «noticias de Apple», «tipos de la Fed y el BCE», «backtest de SPY»…   (Enter envía · Shift+Enter nueva línea)"></textarea><div style="display:grid;gap:4px"><button class="btn primary" id="c-send">ENVIAR</button><button class="btn small" id="c-new">NUEVA SESIÓN</button></div></div></section>`;
    const box = $("#c-msgs");
    const add = (who, html, k) => { const d = document.createElement("div"); d.className = "msg " + k; d.innerHTML = `<div class="who">${who}</div><div class="txt">${html}</div>`; box.appendChild(d); box.scrollTop = box.scrollHeight; return d; };
    let live = null, unsubLive = null;
    const watch = (s) => {
      if (unsubLive) unsubLive();
      unsubLive = Hub.sub(`chat:${S.user.id}:${s}`, (ev) => {
        if (!ev || !live) return;
        const chips = live.querySelector(".chips");
        if (ev.event === "tool_start") chips.insertAdjacentHTML("beforeend", `<span class="tc run" data-t="${esc(ev.tool)}">⚙ ${esc(ev.tool)}</span>`);
        if (ev.event === "tool_end") { const c = [...chips.querySelectorAll(`.tc.run[data-t="${CSS.escape(ev.tool)}"]`)][0]; if (c) { c.className = "tc " + (ev.ok ? "ok" : "err"); c.textContent = `${ev.ok ? "✓" : "✗"} ${ev.tool} ${ev.ms}ms`; } }
      });
    };
    ctx.add(() => unsubLive && unsubLive());
    const intro = () => add("FINCEPT AI", md(`Analista IA del terminal (${S.health.ai_mode === "claude" ? "Claude · tool use" : "modo offline, sin LLM"}). Uso las mismas tools que el servidor MCP: cotizaciones, histórico, noticias, macro DBnomics, riesgo, backtests y tu cuenta paper. No ejecuto órdenes: te doy el comando, p. ej. \`BUY 10 AAPL\`.`), "ai");
    const loadHistory = async () => {
      if (!sid) return intro();
      const r = await api(`/chat/sessions/${sid}`);
      if (!r.success || !r.data.messages.length) return intro();
      r.data.messages.forEach((m) => add(m.role === "user" ? S.user.username.toUpperCase() : "FINCEPT AI", m.role === "user" ? esc(m.text) : md(m.text), m.role === "user" ? "user" : "ai"));
    };
    const send = async (text) => {
      text = (text || $("#c-in").value).trim(); if (!text) return;
      $("#c-in").value = "";
      add(S.user.username.toUpperCase(), esc(text), "user");
      if (!sid) { sid = Math.random().toString(16).slice(2, 14); store.set("chat_sid", sid); }
      watch(sid);
      live = add("FINCEPT AI", '<span class="dim">pensando…</span><div class="chips"></div>', "ai");
      $("#c-send").disabled = true;
      const r = await api("/research/chat", { method: "POST", body: { message: text, session_id: sid } });
      $("#c-send").disabled = false;
      const chips = live.querySelector(".chips").outerHTML;
      if (!r.success) { live.querySelector(".txt").innerHTML = `<span class="neg">${esc(r.message)}</span>`; return; }
      live.querySelector(".txt").innerHTML = chips + md(r.data.reply) + (r.data.credits_charged ? `<div class="dim">−${r.data.credits_charged} créditos</div>` : "");
      box.scrollTop = box.scrollHeight; live = null; refreshUser();
    };
    ctx.on($("#c-send"), "click", () => send());
    ctx.on($("#c-in"), "keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    ctx.on($("#c-new"), "click", () => { sid = null; store.del("chat_sid"); box.innerHTML = ""; intro(); });
    loadHistory().then(() => { if (arg) send(arg); });
    $("#c-in").focus();
  } },

  mcp: { key: "F11", label: "MCP", async render(el, ctx) {
    const r = await api("/api/mcp/connect");
    if (!r.success) { el.innerHTML = `<div class="empty">${esc(r.message)}</div>`; return; }
    const d = r.data;
    const snip = (title, txt) => `<div style="margin-bottom:8px"><div class="row"><span class="dim">${title}</span><span class="sp" style="flex:1"></span><button class="btn small" data-copy="${esc(txt)}">COPIAR</button></div><pre class="code">${esc(txt)}</pre></div>`;
    el.innerHTML = `<div class="grid g2">
      ${panel("Servidor MCP · Streamable HTTP · JSON-RPC 2.0", `<table><tbody>
        <tr><td class="muted">URL</td><td class="cyan">${esc(d.url)}</td></tr>
        <tr><td class="muted">Token</td><td><span id="x-tok">${esc(d.token.slice(0, 10))}••••••••</span> <button class="btn small" id="x-show">VER</button> <button class="btn small" id="x-regen">REGENERAR</button></td></tr>
        <tr><td class="muted">Clientes vistos</td><td>${d.clients.length ? d.clients.map(esc).join(", ") : '<span class="dim">ninguno todavía</span>'}</td></tr>
        <tr><td class="muted">Toolset</td><td><div class="seg" id="x-ts"><button data-v="essentials" class="${d.toolset === "essentials" ? "on" : ""}">ESSENTIALS</button><button data-v="full" class="${d.toolset === "full" ? "on" : ""}">FULL</button></div></td></tr>
        <tr><td class="muted">Acciones</td><td><button class="btn small ${d.allow_actions ? "on" : ""}" id="x-act">${d.allow_actions ? "☑ PERMITIDAS" : "☐ BLOQUEADAS"}</button> <span class="dim">tools que cambian estado (órdenes, watchlists)</span></td></tr></tbody></table>
        <div class="help" style="margin-top:8px">Igual que el terminal real: solo loopback, Bearer obligatorio, Host/Origin validados (anti DNS-rebinding). <code>pt_place_order</code> pide además tu aprobación aquí en cada llamada.</div>`)}
      ${panel("Conectar un agente", snip("Claude Code", d.claude_code) + snip("Codex CLI · ~/.codex/config.toml", d.codex_toml) + snip("Cliente HTTP genérico (Cursor, etc.)", d.generic_json) + snip("Claude Desktop (puente stdio original de Fincept)", d.stdio_json))}
      ${panel("Consola MCP · prueba JSON-RPC desde aquí", `<div class="row"><select class="f" id="x-m"><option>tools/list</option><option selected>tools/call</option><option>initialize</option><option>ping</option></select><input class="f" id="x-tool" value="get_quote" style="width:150px"><input class="f" id="x-args" value='{"symbol":"${esc(S.focus)}"}' style="flex:1"><button class="btn primary" id="x-send">POST /mcp</button></div><pre class="code" id="x-out" style="max-height:300px">—</pre>`)}
      ${panel("Actividad externa", '<div class="empty">Sin llamadas todavía</div>', "<small>mcp:&lt;uid&gt;:activity</small>")}
      ${panel(`Catálogo · ${d.tools.length} tools + 8 meta-tools`, `<table><thead><tr><th>Tool</th><th>Categoría</th><th>Política</th><th>Descripción</th></tr></thead><tbody>${d.tools.map((t) => `<tr><td class="sym">${esc(t.name)}</td><td class="dim">${esc(t.category)}</td><td class="${t.needs_approval ? "neg" : t.destructive ? "warn" : "pos"}">${t.needs_approval ? "aprobación" : t.destructive ? "acción" : "lectura"}</td><td class="muted" style="white-space:normal">${esc(t.description)}</td></tr>`).join("")}</tbody></table>`, "", "span2")}</div>`;
    const [, , , actEl, catEl] = $$(".panel .body", el);
    actEl.classList.add("flush"); catEl.classList.add("flush");
    let token = d.token;
    ctx.on(el, "click", async (e) => {
      const c = e.target.closest("[data-copy]");
      if (c) { navigator.clipboard.writeText(c.dataset.copy).then(() => toast("Copiado", "ok"), () => toast("No se pudo copiar", "err")); return; }
      if (e.target.id === "x-show") $("#x-tok").textContent = token;
      if (e.target.id === "x-regen" && confirm("Regenerar revoca el token de todos los clientes configurados. ¿Seguir?")) { await api("/api/mcp/token/regenerate", { method: "POST" }); go("mcp"); }
      if (e.target.id === "x-act") { await api("/api/mcp/settings", { method: "PUT", body: { allow_actions: !d.allow_actions } }); go("mcp"); }
      const ts = e.target.closest("#x-ts button"); if (ts) { await api("/api/mcp/settings", { method: "PUT", body: { toolset: ts.dataset.v } }); go("mcp"); }
      if (e.target.id === "x-send") {
        const m = $("#x-m").value; let params = {};
        try { const args = JSON.parse($("#x-args").value || "{}"); params = m === "tools/call" ? { name: $("#x-tool").value, arguments: args } : m === "initialize" ? { protocolVersion: "2025-06-18", clientInfo: { name: "fincept-lite-console" } } : {}; } catch { return toast("JSON de argumentos inválido", "err"); }
        const res = await fetch("/mcp", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method: m, params }) });
        const txt = await res.text(); let pretty = txt;
        try { const j = JSON.parse(txt); if (j.result && j.result.content) j.result.content = j.result.content.map((c) => { try { return { ...c, text: JSON.parse(c.text) }; } catch { return c; } }); pretty = JSON.stringify(j, null, 2); } catch { /* */ }
        $("#x-out").textContent = `HTTP ${res.status}\n${pretty.slice(0, 20000)}`;
      }
    });
    ctx.sub(`mcp:${S.user.id}:activity`, (acts) => {
      if (!acts || !acts.length) return;
      actEl.innerHTML = `<table><thead><tr><th>Hora</th><th>Cliente</th><th>Tool</th><th>Resultado</th><th class="num">ms</th></tr></thead><tbody>${acts.map((a) => `<tr><td class="dim">${new Date(a.at * 1000).toLocaleTimeString("es-ES")}</td><td>${esc(a.client)}</td><td class="sym">${esc(a.tool)}</td><td class="${a.denied ? "warn" : a.success ? "pos" : "neg"}" title="${esc(a.summary)}">${a.denied ? "DENEGADA" : a.success ? "OK" : "ERROR"} <span class="dim">${esc(a.summary)}</span></td><td class="num">${a.duration_ms}</td></tr>`).join("")}</tbody></table>`;
    });
    if (d.activity.length) Hub.subs.get(`mcp:${S.user.id}:activity`)?.cbs.forEach((cb) => cb(d.activity));
  } },

  fund: { key: "", label: "FUND", async render(el, ctx) {
    const STAGES = [["memory", "Memoria · aprendizaje"], ["risk_gate", "Cortacircuitos"], ["macro", "Estratega macro"], ["sentiment", "Analista de sentimiento"], ["analysts", "Analistas + cuant"], ["risk", "Gestor de riesgos"], ["cio", "CIO · acta"], ["execution", "Trader (paper)"]];
    const DESK = { equities: "Renta variable", rates: "Renta fija", commodities: "Materias primas", fx: "Divisas", crypto: "Cripto" };
    const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%");
    el.innerHTML = `<div class="row" style="margin-bottom:6px">
        <button class="btn primary" id="f-run">CONVOCAR COMITÉ (PROPUESTA)</button>
        <button class="btn buy" id="f-exec" disabled>APROBAR Y EJECUTAR EN PAPER</button>
        <button class="btn sell" id="f-halt">PARADA DE EMERGENCIA</button>
        <span class="sp" style="flex:1"></span>
        <span class="badge sim">SOLO PAPER · DINERO SIMULADO</span>
        <button class="btn" id="f-auto">AUTOPILOTO: —</button>
        <select class="f" id="f-int">${[15, 30, 60, 240, 1440].map((m) => `<option value="${m}">cada ${m >= 60 ? m / 60 + " h" : m + " min"}</option>`).join("")}</select></div>
      <div class="grid dash">
        ${panel("Comité en vivo", `<table><tbody>${STAGES.map(([k, l]) => `<tr data-st="${k}"><td>${l}<div class="dim" data-ev style="font-size:10px"></div></td><td class="dim" data-m>—</td><td class="num dim" data-s>en espera</td></tr>`).join("")}</tbody></table>`, "<small>fund:&lt;uid&gt;:status</small>")}
        ${panel("Acta del comité (CIO)", '<div class="empty">Convoca el comité para ver la primera propuesta</div>', "", "chartpanel")}
        ${panel("Mesas · confianza aprendida", "")}
        ${panel("Asignación: actual → objetivo", "", '<small id="f-runlbl"></small>', "span2")}
        ${panel("Controles de riesgo", "")}
        ${panel("Órdenes", "", "", "span2")}
        ${panel("Historial de ciclos", "")}
        ${panel('Debate del activo · <span class="cyan" id="f-dsym">pulsa un activo</span>', '<div class="empty">Argumentos alcistas y bajistas de señales independientes (TradingAgents 2024; Huang et al. 2026)</div>', "", "span3")}
        ${panel("Base de investigación · papers que respaldan cada regla", '<div class="empty">Cargando…</div>', "<small>verificados en OpenAlex</small>", "span3")}</div>`;
    const [stEl, memoEl, deskEl, allocEl, riskEl, ordEl, histEl, dbEl, resEl] = $$(".panel .body", el);
    [stEl, allocEl, ordEl, histEl, deskEl, resEl].forEach((b) => b.classList.add("flush"));
    const STAGE_EV = { memory: "memory", risk_gate: "risk", macro: "macro", sentiment: "sentiment", analysts: "quant", risk: "risk", cio: "cio" };
    const doiLink = (doi, txt) => (doi ? `<a href="https://doi.org/${esc(doi)}" target="_blank" rel="noopener noreferrer">${txt}</a>` : txt);
    const showDebate = (sym) => {
      const v = run && run.report.views[sym]; if (!v || !v.debate) return;
      $("#f-dsym").textContent = `${sym} · veredicto ${v.debate.verdict} · desacuerdo ${v.debate.disagreement.toFixed(2)}`;
      const st = v.strategy;
      dbEl.innerHTML = `<div class="grid g2"><div><div class="pos" style="font-weight:700">A FAVOR</div>${v.debate.bull.map((b) => `<div>▲ ${esc(b)}</div>`).join("") || '<div class="dim">sin argumentos</div>'}</div>
        <div><div class="neg" style="font-weight:700">EN CONTRA</div>${v.debate.bear.map((b) => `<div>▼ ${esc(b)}</div>`).join("") || '<div class="dim">sin argumentos</div>'}</div></div>
        <div class="dim" style="margin-top:6px">Cuant: ${st.candidates.map((c) => `${esc(c.strategy)} IS ${c.is_sharpe.toFixed(2)} / OOS ${c.oos_sharpe.toFixed(2)}`).join(" · ")}. Elegida ${esc(st.strategy)} con Deflated Sharpe ${st.deflated_sharpe.toFixed(2)} (umbral 0,50) → confianza ${st.trust}. <a href="#" data-eq="${esc(sym)}">abrir ficha ▸</a></div>`;
    };
    api("/fund/research").then((r) => {
      if (!r.success) return;
      resEl.innerHTML = `<table><thead><tr><th>Año</th><th>Autores</th><th>Trabajo</th><th>Agente</th><th>Hallazgo</th><th>Cómo se aplica</th><th class="num">Citas</th></tr></thead><tbody>${r.data.slice().sort((a, b) => b.year - a.year).map((x) => `<tr><td>${x.year}</td><td class="dim">${esc(x.authors)}</td><td style="white-space:normal;min-width:220px">${doiLink(x.doi, esc(x.title))}<div class="dim">${esc(x.venue)}${x.verified ? "" : ' · <span class="warn">no indexado en OpenAlex</span>'}</div></td><td class="cyan">${esc(x.agent)}</td><td class="muted" style="white-space:normal;min-width:260px">${esc(x.finding)}</td><td style="white-space:normal;min-width:220px">${esc(x.applied)}</td><td class="num">${x.cited_by == null ? "—" : fmtN(x.cited_by, 0)}</td></tr>`).join("")}</tbody></table>`;
    });
    let state = null, run = null;
    const paintState = () => {
      $("#f-auto").textContent = `AUTOPILOTO: ${state.autopilot ? "ON" : "OFF"}`;
      $("#f-auto").classList.toggle("on", state.autopilot);
      $("#f-int").value = String(state.interval_min);
      $("#f-halt").textContent = state.halted ? "REANUDAR FONDO" : "PARADA DE EMERGENCIA";
      $("#f-halt").className = "btn " + (state.halted ? "buy" : "sell");
      histEl.innerHTML = state.runs.length ? `<table><thead><tr><th>#</th><th>Hora</th><th>Origen</th><th>Régimen</th><th class="num">Órdenes</th><th>Estado</th></tr></thead><tbody>${state.runs.map((r) => `<tr class="click" data-run="${r.id}"><td class="dim">${r.id}</td><td>${new Date(r.started * 1000).toLocaleString("es-ES")}</td><td class="dim">${esc(r.trigger)}</td><td>${esc(r.regime || "—")}</td><td class="num">${r.orders}</td><td class="${r.status === "executed" ? "pos" : r.status === "proposed" ? "warn" : "dim"}">${esc(r.status.toUpperCase())}${r.halted ? " · PARADO" : ""}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Sin ciclos todavía</div>';
    };
    const paintRun = (r) => {
      run = r; const d = r.report; if (!d) return;
      $("#f-runlbl").textContent = `ciclo #${r.id} · ${r.status} · equity ${fmtN(d.equity)} · datos ${d.data_source}`;
      $("#f-exec").disabled = r.status !== "proposed" || !d.orders.length;
      const cb = d.circuit_breaker, m = d.macro, s = d.sentiment;
      for (const [stage, key] of Object.entries(STAGE_EV)) {
        const cell = stEl.querySelector(`tr[data-st="${stage}"] [data-ev]`);
        const ev = (d.evidence || {})[key] || [];
        if (cell) cell.innerHTML = ev.map((x) => doiLink(x.doi, esc(x.short))).join(" · ");
      }
      memoEl.innerHTML = `<div class="row" style="margin-bottom:6px"><span class="chip ${m.regime === "risk_on" ? "positive" : m.regime === "risk_off" ? "negative" : ""}">régimen ${esc(m.regime)}</span><span class="chip">tipos ${esc(m.rates_direction)}</span><span class="chip ${s.avg_sentiment > 0 ? "positive" : s.avg_sentiment < 0 ? "negative" : ""}">sentimiento ${s.avg_sentiment.toFixed(2)}</span>${s.dropped_suspicious ? `<span class="chip negative">${s.dropped_suspicious} titular(es) descartado(s) por posible inyección</span>` : ""}${cb.halted ? `<span class="chip negative">CORTACIRCUITOS: ${esc(cb.reason)}</span>` : ""}</div>
        <div class="msg"><div class="txt">${md(d.memo_llm || d.memo)}</div></div>
        <div class="dim" style="margin-top:6px">${m.notes.map(esc).join(" · ")}${d.memo_llm ? " · acta redactada por Claude (no decide nada)" : ""}</div>`;
      const eq = d.equity, cur = (sym) => ((d.positions[sym] || 0) * (d.prices[sym] || 0)) / eq;
      const syms = [...new Set([...Object.keys(d.views), ...Object.keys(d.positions)])].sort((a, b) => (d.target[b] || 0) - (d.target[a] || 0));
      allocEl.innerHTML = `<table><thead><tr><th>Activo</th><th>Mesa</th><th class="num">Puntuación</th><th>Estrategia (cuant)</th><th class="num">Sharpe IS / OOS</th><th class="num">DSR</th><th>Debate</th><th class="num">Actual</th><th class="num">Objetivo</th></tr></thead><tbody>${syms.map((sym) => { const v = d.views[sym]; const st = v && v.strategy; return `<tr class="click" data-sym="${esc(sym)}"><td class="sym">${esc(sym)}</td><td class="dim">${esc(DESK[v ? v.desk : ""] || "—")}</td><td class="num ${v ? cls(v.score) : ""}">${v ? v.score.toFixed(2) : "—"}</td><td>${st ? `${esc(st.strategy)} <span class="${st.validated ? "pos" : "warn"}">${st.validated ? "✓ validada" : "✗ no validada"}</span>` : "—"}</td><td class="num dim">${st ? `${st.is_sharpe.toFixed(2)} / ${st.oos_sharpe.toFixed(2)}` : ""}</td><td class="num ${st && st.dsr_ok ? "pos" : "warn"}">${st && st.deflated_sharpe != null ? st.deflated_sharpe.toFixed(2) : "—"}</td><td class="${v && v.debate ? (v.debate.verdict === "alcista" ? "pos" : v.debate.verdict === "bajista" ? "neg" : "warn") : "dim"}">${v && v.debate ? `${v.debate.verdict} · ${v.debate.disagreement.toFixed(2)}` : "—"}</td><td class="num">${pct(cur(sym))}</td><td class="num ${(d.target[sym] || 0) > cur(sym) ? "pos" : (d.target[sym] || 0) < cur(sym) ? "neg" : ""}">${pct(d.target[sym] || 0)}</td></tr>`; }).join("")}</tbody></table>`;
      deskEl.innerHTML = `<table><thead><tr><th>Mesa</th><th class="num">Objetivo</th><th class="num">Límite</th><th class="num">Confianza</th><th class="num">Aciertos</th></tr></thead><tbody>${Object.keys(DESK).map((k) => { const t = Object.entries(d.target).filter(([s]) => d.views[s] && d.views[s].desk === k).reduce((a, [, w]) => a + w, 0); const L = d.learning[k]; return `<tr><td>${DESK[k]}</td><td class="num">${pct(t)}</td><td class="num dim">${pct(state.desk_max[k])}</td><td class="num ${(d.desk_trust[k] || 1) > 1 ? "pos" : (d.desk_trust[k] || 1) < 1 ? "neg" : ""}">${(d.desk_trust[k] || 1).toFixed(2)}</td><td class="num dim">${L ? `${(L.hit_rate * 100).toFixed(0)}% de ${L.calls}` : "—"}</td></tr>`; }).join("")}</tbody></table><div class="dim" style="padding:6px">Caja objetivo ${pct(1 - Object.values(d.target).reduce((a, b) => a + b, 0))}. La confianza sube cuando la mesa acierta la dirección y baja cuando falla (0,5–1,5).</div>`;
      const checks = [...d.risk_checks, ...d.order_checks];
      riskEl.innerHTML = checks.map((c) => `<div><span class="${c.status === "ok" ? "pos" : c.status === "blocked" ? "neg" : "warn"}">${esc(c.status.toUpperCase())}</span> ${esc(c.check)} <span class="dim">${esc(c.detail)}</span></div>`).join("") + `<div class="dim" style="margin-top:6px">Objetivo de vol ${pct(d.policy.target_vol)} · caja mín. ${pct(d.policy.min_cash)} · rotación máx. ${pct(d.policy.max_turnover)} · parada si drawdown &gt; ${pct(d.policy.max_drawdown_halt)} o ${d.policy.max_consecutive_losses} ciclos en pérdidas</div>`;
      const rows = (d.fills.length ? d.fills.map((f) => ({ ...f, st: "EJECUTADA", c: "pos" })) : d.orders.map((o) => ({ ...o, st: r.status === "proposed" ? "PROPUESTA" : "—", c: "warn" }))).concat((d.rejected || []).map((o) => ({ ...o, st: "RECHAZADA: " + o.reason, c: "neg" })));
      ordEl.innerHTML = rows.length ? `<table><thead><tr><th>Activo</th><th>Lado</th><th class="num">Cantidad</th><th class="num">Precio</th><th class="num">Nominal</th><th>Estado</th></tr></thead><tbody>${rows.map((o) => `<tr><td class="sym">${esc(o.symbol)}</td><td class="${o.side === "buy" ? "pos" : "neg"}">${o.side.toUpperCase()}</td><td class="num">${o.qty}</td><td class="num">${fmtPx(o.price)}</td><td class="num">${fmtN(o.qty * o.price)}</td><td class="${o.c}">${esc(o.st)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Sin órdenes: la cartera ya está dentro de las bandas de rebalanceo</div>';
    };
    const load = async () => { const r = await api("/fund/state"); if (!r.success) return toast(r.message, "err"); state = r.data; paintState(); if (r.data.last_run && !run) paintRun(r.data.last_run); };
    ctx.sub(`fund:${S.user.id}:status`, (e) => {
      if (!e) return;
      const tr = stEl.querySelector(`tr[data-st="${e.stage}"]`);
      if (tr) { tr.querySelector("[data-m]").textContent = e.msg; const s = tr.querySelector("[data-s]"); s.textContent = e.status === "running" ? "trabajando…" : e.status === "blocked" ? "BLOQUEO" : "✓"; s.className = "num " + (e.status === "running" ? "warn" : e.status === "blocked" ? "neg" : "pos"); }
    });
    ctx.on(el, "click", async (e) => {
      const id = e.target.id;
      if (id === "f-run") {
        $$("[data-s]", stEl).forEach((s) => { s.textContent = "en espera"; s.className = "num dim"; });
        e.target.disabled = true; const r = await api("/fund/cycle", { method: "POST", body: {} }); e.target.disabled = false;
        if (!r.success) return toast(r.message, "err");
        paintRun(r.data); toast(`Comité #${r.data.id}: ${r.data.report.orders.length} órdenes propuestas`, "ok"); load();
      } else if (id === "f-exec" && run) {
        if (!(await confirmModal("EJECUTAR PROPUESTA EN PAPER", `${run.report.orders.length} órdenes del ciclo #${run.id} con <b>dinero simulado</b>. Los límites de riesgo se revalidan antes de enviar.`))) return;
        const r = await api(`/fund/runs/${run.id}/execute`, { method: "POST" });
        if (!r.success) return toast(r.message, "err");
        paintRun(r.data); toast(`${r.data.report.fills.length} órdenes ejecutadas en paper`, "ok"); load();
      } else if (id === "f-halt") {
        const r = await api("/fund/halt", { method: "POST", body: { halted: !state.halted, reason: "parada manual desde la terminal" } });
        if (r.success) { toast(r.data.halted ? "Fondo parado: no se enviarán compras" : "Fondo reanudado", r.data.halted ? "err" : "ok"); load(); }
      } else if (id === "f-auto") {
        if (!state.autopilot && !(await confirmModal("ACTIVAR AUTOPILOTO", `El comité se convocará <b>${$("#f-int").selectedOptions[0].textContent}</b> y ejecutará sus propuestas automáticamente en la cuenta <b>paper</b>, con todos los límites y cortacircuitos activos. Puedes pararlo en cualquier momento.`))) return;
        const r = await api("/fund/autopilot", { method: "PUT", body: { on: !state.autopilot, interval_min: +$("#f-int").value } });
        if (!r.success) return toast(r.message, "err"); load();
      } else {
        const tr = e.target.closest("tr[data-run]"); if (tr) { const r = await api(`/fund/runs/${tr.dataset.run}`); if (r.success) paintRun(r.data); return; }
        const eq = e.target.closest("[data-eq]"); if (eq) { e.preventDefault(); go("equity", eq.dataset.eq); return; }
        const sy = e.target.closest("tr[data-sym]"); if (sy) showDebate(sy.dataset.sym);
      }
    });
    ctx.on($("#f-int"), "change", async () => { if (state.autopilot) { await api("/fund/autopilot", { method: "PUT", body: { on: true, interval_min: +$("#f-int").value } }); load(); } });
    load();
  } },

  profile: { key: "F12", label: "PROFILE", async render(el, ctx) {
    const [p, u, lh] = await Promise.all([api("/user/profile"), api("/user/usage"), api("/user/login-history")]);
    if (!p.success) { el.innerHTML = `<div class="empty">${esc(p.message)}</div>`; return; }
    const d = p.data;
    el.innerHTML = `<div class="grid g2">
      ${panel("Cuenta", `<table><tbody>${[["Usuario", esc(d.username)], ["Email", esc(d.email)], ["Plan", esc(d.account_type.toUpperCase())], ["Créditos", fmtN(d.credit_balance)], ["Verificado", d.is_verified ? "sí" : "no"], ["MFA (OTP por email)", `${d.mfa_enabled ? "activado" : "desactivado"} <button class="btn small" id="pf-mfa">${d.mfa_enabled ? "DESACTIVAR" : "ACTIVAR"}</button>`], ["Rate limit", `${d.rate_limit.remaining}/${d.rate_limit.limit} por ${d.rate_limit.window_seconds}s`], ["Alta", esc(d.created_at)], ["Último login", esc(d.last_login_at)], ["API key", `<span id="pf-key">${esc(S.apiKey.slice(0, 12))}••••</span> <button class="btn small" id="pf-regen">REGENERAR</button>`]].map(([l, v]) => `<tr><td class="muted">${l}</td><td>${v}</td></tr>`).join("")}</tbody></table><div class="row" style="margin-top:10px"><button class="btn sell" id="pf-out">CERRAR SESIÓN</button></div>`)}
      ${panel("Consumo de créditos · /user/usage", u.success && u.data.recent.length ? `<table><thead><tr><th>Fecha</th><th>Endpoint</th><th class="num">Créditos</th></tr></thead><tbody>${u.data.recent.map((x) => `<tr><td class="dim">${esc(x.at)}</td><td>${esc(x.endpoint)}</td><td class="num">${fmtN(x.credits)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Sin consumo (el chat con Claude cuesta 5 créditos por respuesta)</div>')}
      ${panel("Inspector del DataHub", "", "<small>/datahub/topics · cada 2 s</small>", "span2")}
      ${panel("Historial de accesos", lh.success ? `<table><thead><tr><th>Fecha</th><th>IP</th><th>Resultado</th><th>Agente</th></tr></thead><tbody>${lh.data.map((x) => `<tr><td class="dim">${esc(x.at)}</td><td>${esc(x.ip)}</td><td class="${x.success ? "pos" : "neg"}">${x.success ? "OK" : "FALLO"}</td><td class="dim" style="max-width:360px;overflow:hidden;text-overflow:ellipsis">${esc(x.user_agent)}</td></tr>`).join("")}</tbody></table>` : "", "", "span2")}</div>`;
    const hubEl = $$(".panel .body", el)[2]; hubEl.classList.add("flush");
    const paintHub = async () => {
      const r = await api("/datahub/topics"); if (!r.success) return;
      hubEl.innerHTML = `<table><thead><tr><th>Tópico</th><th class="num">Subs</th><th class="num">Edad</th><th class="num">TTL</th><th class="num">Min int.</th><th>Modo</th><th class="num">Refrescos</th><th class="num">Publicaciones</th><th>Estado</th></tr></thead><tbody>${r.data.map((t) => `<tr><td class="cyan">${esc(t.topic)}</td><td class="num">${t.subscribers}</td><td class="num">${t.age_ms == null ? "—" : (t.age_ms / 1000).toFixed(1) + "s"}</td><td class="num">${t.push_only ? "—" : t.ttl_ms / 1000 + "s"}</td><td class="num">${t.push_only ? "—" : t.min_interval_ms / 1000 + "s"}</td><td class="dim">${t.push_only ? "push" + (t.coalesce_ms ? ` · coalesce ${t.coalesce_ms}ms` : "") : "pull"}</td><td class="num">${t.refreshes}</td><td class="num">${t.publishes}</td><td class="${t.error ? "neg" : t.in_flight ? "warn" : "pos"}">${t.error ? esc(t.error) : t.in_flight ? "in_flight" : "ok"}</td></tr>`).join("")}</tbody></table>`;
    };
    paintHub(); ctx.every(paintHub, 2000);
    ctx.on(el, "click", async (e) => {
      if (e.target.id === "pf-out") { await api("/user/logout", { method: "POST" }); logout(); }
      if (e.target.id === "pf-regen" && confirm("La API key actual dejará de funcionar. ¿Regenerar?")) { const r = await api("/user/regenerate-api-key", { method: "POST" }); if (r.success) { S.apiKey = r.data.api_key; saveSession(); Hub.close(); Hub.connect(); toast("API key regenerada", "ok"); go("profile"); } }
      if (e.target.id === "pf-mfa") { await api(d.mfa_enabled ? "/user/mfa/disable" : "/user/mfa/enable", { method: "POST" }); go("profile"); }
    });
  } },
};

// ── navegación ──────────────────────────────────────────────────────────────
let curCtx = null;
async function go(name, arg) {
  const scr = SCREENS[name]; if (!scr || !S.user) return;
  if (curCtx) curCtx.dispose();
  const ctx = (curCtx = makeCtx());
  S.screen = name;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.s === name));
  const el = $("#screen"); el.scrollTop = 0; el.innerHTML = "";
  try { await scr.render(el, ctx, arg); } catch (err) {
    if (ctx.disposed) return; // la pantalla ya no está visible: su error no debe pisar la nueva
    console.error(err); el.innerHTML = `<div class="empty">Error: ${esc(err.message)}</div>`;
  }
}
function buildTabs() {
  $("#tabs").innerHTML = Object.entries(SCREENS).map(([k, s]) => `<button data-s="${k}"><kbd>${s.key}</kbd>${s.label}</button>`).join("");
  $("#tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) go(b.dataset.s); };
}

// ── barra de comandos ───────────────────────────────────────────────────────
const COMMANDS = [
  ["DASH", "Dashboard", "dashboard"], ["MKT", "Mercados", "markets"], ["NEWS", "Noticias", "news"], ["PORT", "Cartera paper", "portfolio"],
  ["BT", "Backtesting", "backtest"], ["WL", "Watchlists", "watchlist"], ["QL", "QuantLib (opciones, riesgo)", "quantlib"], ["MACRO", "Macro DBnomics", "macro"],
  ["AI", "Chat IA  ·  AI <pregunta>", "ai_chat"], ["MCP", "Servidor MCP", "mcp"], ["FUND", "Fondo IA multi-agente (paper)", "fund"], ["PROF", "Perfil / DataHub", "profile"], ["HELP", "Ayuda de comandos", null],
];
function helpModal() {
  modal("AYUDA · COMANDOS", `<div class="help">
    <div><code>AAPL</code> · <code>SAN.MC GO</code> · <code>BTC-USD</code> → ficha del activo (F9)</div>
    <div><code>BUY 10 AAPL</code> · <code>SELL 5 MSFT @ 420</code> · <code>BUY 1 NVDA STOP 150</code> → orden paper</div>
    <div><code>AI ¿cómo va el IBEX?</code> → pregunta al chat IA</div>
    <div>${COMMANDS.filter((c) => c[2]).map((c) => `<code>${c[0]}</code> ${esc(c[1])}`).join(" · ")}</div>
    <div style="margin-top:8px">Teclas: <code>F1</code>–<code>F12</code> pantallas · <code>/</code> o <code>Ctrl+K</code> foco en la barra · <code>Esc</code> cerrar.</div>
    <div>Símbolos estilo Yahoo: índices <code>^GSPC</code>, divisas <code>EURUSD=X</code>, futuros <code>GC=F</code>, España <code>.MC</code>, Londres <code>.L</code>.</div></div>`, [["CERRAR", null]]);
}
async function runCommand(raw) {
  const txt = raw.trim(); if (!txt) return;
  const up = txt.toUpperCase();
  const m = up.match(/^(BUY|SELL)\s+([\d.]+)\s+([\w^.=\-]+)(?:\s+(?:(@|LMT|LIMIT|STOP|STP)\s*([\d.]+)))?$/);
  if (m) {
    const [, side, qty, sym, kind, px] = m;
    const body = { symbol: sym, side: side.toLowerCase(), qty: parseFloat(qty), type: "market" };
    if (kind) { if (kind.startsWith("ST")) { body.type = "stop"; body.stop_price = parseFloat(px); } else { body.type = "limit"; body.limit_price = parseFloat(px); } }
    const ok = await confirmModal("CONFIRMAR ORDEN PAPER", `${side} <b class="sym">${qty} ${esc(sym)}</b> · ${body.type.toUpperCase()}${px ? " @ " + esc(px) : ""}<div class="dim" style="margin-top:6px">Dinero simulado (paper trading).</div>`);
    if (!ok) return;
    const r = await api("/paper/orders", { method: "POST", body });
    toast(r.success ? `${r.message}${r.data.filled_price ? " @ " + fmtPx(r.data.filled_price) : ""}` : r.message, r.success ? "ok" : "err");
    return;
  }
  if (up.startsWith("AI ")) return go("ai_chat", txt.slice(3));
  if (up === "HELP" || up === "?") return helpModal();
  const cmd = COMMANDS.find((c) => c[0] === up); if (cmd && cmd[2]) return go(cmd[2]);
  const scr = Object.entries(SCREENS).find(([, s]) => s.label === up || s.key === up); if (scr) return go(scr[0]);
  const sym = up.replace(/\s+(GO|EQ|DES|<GO>)$/, "");
  if (/^[\w^.=\-]{1,24}$/.test(sym)) return go("equity", sym);
  toast(`Comando no reconocido: ${txt}`, "err");
}
function setupCommandBar() {
  const inp = $("#cmd"), box = $("#suggest");
  let items = [], sel = -1, timer = null;
  const render = () => {
    box.innerHTML = items.map((it, i) => `<div class="${i === sel ? "sel" : ""}" data-i="${i}"><b>${esc(it.cmd)}</b><span>${esc(it.desc)}</span><em>${esc(it.kind)}</em></div>`).join("");
    box.classList.toggle("open", items.length > 0);
  };
  const pick = (i) => { const it = items[i]; items = []; render(); inp.value = ""; runCommand(it ? it.cmd : inp.value); };
  inp.addEventListener("input", () => {
    const q = inp.value.trim().toUpperCase(); sel = -1;
    items = q ? COMMANDS.filter((c) => c[0].startsWith(q.split(" ")[0])).map((c) => ({ cmd: c[0], desc: c[1], kind: "pantalla" })) : [];
    render();
    clearTimeout(timer);
    if (q.length >= 1 && !/^(BUY|SELL|AI)\b/.test(q)) timer = setTimeout(async () => {
      const r = await api(`/market/search?q=${encodeURIComponent(q)}&limit=8`);
      if (!r.success || inp.value.trim().toUpperCase() !== q) return;
      items = items.concat(r.data.map((s) => ({ cmd: s.symbol, desc: s.name, kind: `${s.type || ""} ${s.exchange || ""}`.trim() })));
      render();
    }, 220);
  });
  inp.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(items.length - 1, sel + 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(-1, sel - 1); render(); e.preventDefault(); }
    else if (e.key === "Enter") { e.preventDefault(); if (sel >= 0) pick(sel); else { const v = inp.value; inp.value = ""; items = []; render(); runCommand(v); } }
    else if (e.key === "Escape") { items = []; render(); inp.blur(); }
  });
  box.addEventListener("mousedown", (e) => { const d = e.target.closest("[data-i]"); if (d) { e.preventDefault(); pick(+d.dataset.i); } });
  inp.addEventListener("blur", () => setTimeout(() => { items = []; render(); }, 150));
}

// ── modales ─────────────────────────────────────────────────────────────────
function modal(title, html, buttons) {
  return new Promise((resolve) => {
    const ov = document.createElement("div"); ov.className = "overlay";
    ov.innerHTML = `<div class="modal"><header>${esc(title)}</header><div class="body">${html}<div class="row" style="justify-content:flex-end">${buttons.map(([l], i) => `<button class="btn ${i === 0 ? "primary" : ""}" data-b="${i}">${esc(l)}</button>`).join("")}</div></div></div>`;
    const close = (v) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    ov.addEventListener("click", (e) => { const b = e.target.closest("[data-b]"); if (b) close(buttons[+b.dataset.b][1]); else if (e.target === ov) close(null); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(ov);
    ov.querySelector(".btn.primary")?.focus();
  });
}
const confirmModal = (t, html) => modal(t, html, [["CONFIRMAR", true], ["CANCELAR", false]]);

// Aprobación por llamada para agentes externos (ToolApprovalDialog del terminal)
const shownApprovals = new Set();
function watchApprovals() {
  Hub.sub(`mcp:${S.user.id}:approvals`, async (d) => {
    for (const p of (d && d.pending) || []) {
      if (shownApprovals.has(p.id)) continue;
      shownApprovals.add(p.id);
      const ok = await modal("AGENTE EXTERNO · APROBACIÓN REQUERIDA", `<div><b class="cyan">${esc(p.client)}</b> quiere ejecutar <b class="sym">${esc(p.tool)}</b></div><pre class="code">${esc(p.summary)}</pre><div class="dim">Caduca en ${Math.max(0, Math.round(p.expires_at - Date.now() / 1000))} s. Si no respondes, se deniega.</div>`, [["APROBAR", true], ["DENEGAR", false]]);
      const r = await api(`/api/mcp/approvals/${p.id}`, { method: "POST", body: { approve: !!ok } });
      toast(r.success ? (ok ? "Llamada aprobada" : "Llamada denegada") : "La solicitud ya había caducado", r.success && ok ? "ok" : "");
    }
  });
}

// ── login (réplica del flujo de AuthManager) ────────────────────────────────
function saveSession() { store.set("session", { apiKey: S.apiKey, session: S.session }); }
function logout(msg) {
  const wasIn = !!S.apiKey || !document.getElementById("login");
  S.apiKey = S.session = S.user = null; store.del("session"); Hub.close();
  if (curCtx) curCtx.dispose();
  $("#screen").innerHTML = ""; $("#user").textContent = "";
  if (msg) toast(msg, "err");
  if (wasIn && !document.getElementById("login")) loginScreen();
}
function loginScreen() {
  const ov = document.createElement("div"); ov.className = "overlay"; ov.id = "login";
  ov.innerHTML = `<div class="modal" style="width:min(460px,100%)"><header>FINCEPT LITE · ACCESO</header><div class="body">
    <div class="login-art">█▀▀ █ █▄ █ █▀▀ █▀▀ █▀█ ▀█▀   █   █ ▀█▀ █▀▀\n█▀  █ █ ▀█ █▄▄ ██▄ █▀▀  █    █▄▄ █  █  ██▄</div>
    <div class="seg" id="l-tab"><button data-v="login" class="on">ENTRAR</button><button data-v="register">CREAR CUENTA</button></div>
    <div class="form" id="l-form"></div><div class="err" id="l-err"></div>
    <div class="row"><button class="btn primary" id="l-go">ENTRAR</button><button class="btn" id="l-demo">USAR CUENTA DEMO</button></div>
    <div class="dim">Réplica educativa de Fincept Terminal. Demo: demo@example.com / demo12345</div></div></div>`;
  document.body.appendChild(ov);
  let mode = "login", pendingEmail = null, otpKind = null;
  const form = $("#l-form", ov), err = $("#l-err", ov), goBtn = $("#l-go", ov);
  const fields = {
    login: [["email", "Email", "email"], ["password", "Contraseña", "password"]],
    register: [["username", "Usuario", "text"], ["email", "Email", "email"], ["password", "Contraseña (8+)", "password"], ["phone", "Teléfono", "text"], ["country_code", "Prefijo", "text"]],
    otp: [["otp", "Código OTP", "text"]],
  };
  const paint = () => {
    form.innerHTML = fields[mode].map(([k, l, t]) => `<label>${l}</label><input class="f" data-k="${k}" type="${t}" autocomplete="${t === "password" ? "current-password" : "on"}">`).join("");
    goBtn.textContent = mode === "register" ? "CREAR CUENTA" : mode === "otp" ? "VERIFICAR" : "ENTRAR";
    form.querySelector("input")?.focus();
  };
  const val = (k) => form.querySelector(`[data-k="${k}"]`)?.value.trim() || "";
  const done = async (data) => {
    S.apiKey = data.api_key; S.session = data.session_token; saveSession(); ov.remove(); await boot();
  };
  const handleLogin = async (email, password, force) => {
    const r = await api("/user/login", { method: "POST", body: { email, password, force_login: !!force } });
    if (!r.success) {
      err.textContent = r.message || "Error";
      if (r.needs_verification) { pendingEmail = email; otpKind = "verify"; mode = "otp"; paint(); if (r.dev_otp) err.innerHTML = `<span class="ok">DEV · código: ${esc(r.dev_otp)}</span>`; }
      return;
    }
    const d = r.data;
    if (d.active_session) {
      if (await confirmModal("SESIÓN ACTIVA", esc(d.message) + "<div class='dim' style='margin-top:6px'>¿Cerrar la otra sesión y entrar aquí? (force_login)</div>")) return handleLogin(email, password, true);
      return;
    }
    if (d.mfa_required) { pendingEmail = email; otpKind = "mfa"; mode = "otp"; paint(); err.innerHTML = d.dev_otp ? `<span class="ok">MFA · DEV código: ${esc(d.dev_otp)}</span>` : "Introduce el código enviado por email"; return; }
    done(d);
  };
  $("#l-tab", ov).onclick = (e) => { const b = e.target.closest("button"); if (!b) return; mode = b.dataset.v; $$("#l-tab button", ov).forEach((x) => x.classList.toggle("on", x === b)); err.textContent = ""; paint(); };
  goBtn.onclick = async () => {
    err.textContent = "";
    if (mode === "login") return handleLogin(val("email"), val("password"));
    if (mode === "register") {
      const body = { username: val("username"), email: val("email"), password: val("password"), phone: val("phone"), country_code: val("country_code") };
      const r = await api("/user/register", { method: "POST", body });
      if (!r.success) { err.textContent = r.message; return; }
      pendingEmail = body.email; otpKind = "verify"; mode = "otp"; paint();
      err.innerHTML = `<span class="ok">${esc(r.message)}${r.data.dev_otp ? ` · DEV código: ${esc(r.data.dev_otp)}` : ""}</span>`;
      return;
    }
    const r = await api(otpKind === "mfa" ? "/user/verify-mfa" : "/user/verify-otp", { method: "POST", body: { email: pendingEmail, otp: val("otp") } });
    if (!r.success) { err.textContent = r.message; return; }
    done(r.data);
  };
  ov.addEventListener("keydown", (e) => { if (e.key === "Enter") goBtn.click(); });
  $("#l-demo", ov).onclick = () => handleLogin("demo@example.com", "demo12345", true);
  paint();
}

// ── arranque ────────────────────────────────────────────────────────────────
async function refreshUser() {
  const p = await api("/user/profile"); if (!p.success) return false;
  S.user = p.data;
  $("#user").textContent = `${S.user.username.toUpperCase()} · ${fmtN(S.user.credit_balance, 0)} CR`;
  return true;
}
function paintBadges() {
  const h = S.health, mp = h.market_provider || {};
  const data = h.data_mode === "sim" ? '<span class="badge sim">DATOS SIM</span>' : mp.state === "cooldown" ? `<span class="badge sim" title="Yahoo devolvió 429; reintento en ${mp.cooldown_seconds}s">YAHOO PAUSADO · SIM</span>` : '<span class="badge live">LIVE · YAHOO</span>';
  $("#badges").innerHTML = data + `<span class="badge ai">IA ${h.ai_mode === "claude" ? "CLAUDE" : "OFFLINE"}</span>`;
  $("#ver").textContent = "v" + (h.version || "");
}
async function pollHealth() { try { S.health = await (await fetch("/health")).json(); paintBadges(); } catch { /* */ } }
function tape() {
  const el = $("#tape");
  el.innerHTML = TAPE.map((s) => `<span data-sym="${esc(s)}"><b>${esc(s)}</b><i>…</i></span>`).join("");
  el.onclick = (e) => { const sp = e.target.closest("[data-sym]"); if (sp) go("equity", sp.dataset.sym); };
  for (const s of TAPE) Hub.sub(`market:quote:${s}`, (q) => {
    if (!q) return;
    const sp = el.querySelector(`[data-sym="${CSS.escape(s)}"] i`);
    sp.innerHTML = `${fmtPx(q.price)} <span class="${cls(q.change_pct)}">${q.change_pct >= 0 ? "▲" : "▼"}${Math.abs(q.change_pct).toFixed(2)}%</span>`;
    sp.style.fontStyle = "normal";
  });
}
async function boot() {
  if (!(await refreshUser())) { logout(); return; }
  Hub.connect(); buildTabs(); tape(); watchApprovals();
  await pollHealth();
  go(store.get("screen") && SCREENS[store.get("screen")] ? store.get("screen") : "dashboard");
}

function clock() {
  const now = new Date();
  const ny = now.toLocaleTimeString("es-ES", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
  const md_ = now.toLocaleTimeString("es-ES", { timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit" });
  $("#clock").innerHTML = `<b>${now.toLocaleTimeString("es-ES")}</b> · NY ${ny} · MAD ${md_} · UTC ${now.toISOString().slice(11, 16)}`;
}

document.addEventListener("keydown", (e) => {
  const fk = /^F(\d{1,2})$/.exec(e.key);
  if (fk && S.user) {
    const scr = Object.entries(SCREENS).find(([, s]) => s.key === e.key);
    if (scr) { e.preventDefault(); go(scr[0]); }
    return;
  }
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
  if ((e.key === "/" && !typing) || (e.key === "k" && (e.ctrlKey || e.metaKey))) { e.preventDefault(); $("#cmd").focus(); }
});
window.addEventListener("beforeunload", () => S.screen && store.set("screen", S.screen));

(async function main() {
  setupCommandBar(); clock(); setInterval(clock, 1000);
  setInterval(pollHealth, 15000);
  setInterval(async () => { if (S.session) await api("/user/session-pulse"); }, 60000); // SessionGuard
  const saved = store.get("session");
  if (saved && saved.apiKey) { S.apiKey = saved.apiKey; S.session = saved.session; await boot(); }
  else loginScreen();
})();
