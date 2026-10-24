"use strict";

/* CRI frontend redesign
 * Backend contract intentionally preserved:
 * /api/ticker, /api/ohlcv, /api/forecast, /api/performance,
 * /api/backtest, /api/explain, /api/status and /api/admin/prepare.
 */
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const MODEL_NAMES = { historical_22d: "Historical 22d", garch_1_1: "GARCH(1,1)", har_rv: "HAR-RV", xgboost: "XGBoost" };
const MODEL_COLORS = { historical_22d: "#8290a3", garch_1_1: "#f2b64b", har_rv: "#31c7ff", xgboost: "#9a82ff" };
const TF_TO_BINANCE = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d" };
const PREF_KEY = "cri_frontend_prefs_v2";
const THEME_KEY = "cri_theme";
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"];
const TIP_DEFS = { "vol:": "volatility", "fvol:": "forecast vol", "var:": "VaR", "es:": "ES", "qlike:": "QLIKE", "breach:": "breach", "rv:": "realized vol", "oos:": "out-of-sample" };

const state = {
  symbols: [...DEFAULT_SYMBOLS],
  symbol: "BTCUSDT", tf: "1h", method: "forecast_based", position: 10000, leverage: 1,
  candles: [], view: null, perfView: null, btView: null, forecast: null, performance: null, backtest: null, explain: null,
  loadedTabs: new Set(), ws: null, wsBase: "wss://data-stream.binance.vision", wsTimer: null,
  pollTimer: null, lastTickAt: 0, jobPoll: null, chartHover: -1, wsRetries: 0,
};

const fmtNum = (v, d = 2) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtUSD = (v, d = 0) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: d, minimumFractionDigits: d });
const fmtPct = (v, d = 1) => v == null || !Number.isFinite(Number(v)) ? "—" : `${fmtNum(v, d)}%`;
const localTime = (iso) => { try { return iso ? new Date(iso).toLocaleString("vi-VN", { hour12: false }) : "—"; } catch { return iso || "—"; } };
const localTs = (ms) => { try { return new Date(ms).toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return "—"; } };
const symbolLabel = () => state.symbol.replace("USDT", "/USDT");
const shortSymbol = (s) => s.replace("USDT", "");
const statusLabel = (value) => ({ success: "Thành công", completed: "Hoàn tất", running: "Đang chạy", failed: "Thất bại", error: "Lỗi", queued: "Đang chờ", pending: "Đang chờ", ready: "Sẵn sàng", stale: "Cũ", missing: "Thiếu dữ liệu" }[String(value || "").toLowerCase()] || value || "—");
const jobLabel = (value) => ({ prepare: "Chuẩn bị dữ liệu", update: "Cập nhật dữ liệu", retrain: "Huấn luyện lại mô hình" }[value] || value);
const viewLabel = (value) => ({ models: "phân tích mô hình", backtest: "kiểm định", explain: "giải thích mô hình", data: "dữ liệu & hệ thống" }[value] || value);
const setText = (selector, value) => { const node = $(selector); if (node) node.textContent = value == null ? "—" : value; };

async function api(path, options) {
  const response = await fetch(path, options);
  let data = null; try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const error = new Error(data?.detail?.message || data?.detail || `HTTP ${response.status}`);
    error.code = data?.detail?.code || data?.code; throw error;
  }
  return data;
}
function toast(message, error = false) {
  const node = $("#toast"); if (!node) return;
  node.textContent = message; node.className = `toast${error ? " error" : ""}`;
  clearTimeout(node._timer); node._timer = setTimeout(() => node.classList.add("hidden"), 6000);
}
function tipPop(message, anchor = null, ms = 4500) {
  const node = $("#tip-pop"); if (!node) return;
  node.textContent = message; node.classList.remove("hidden");
  if (anchor) {
    setTimeout(() => {
      const rect = anchor.getBoundingClientRect(), bw = node.offsetWidth || 200, bh = node.offsetHeight || 40;
      node.style.left = `${Math.min(window.innerWidth - bw - 12, Math.max(8, rect.left + rect.width / 2 - bw / 2))}px`;
      node.style.top = `${Math.max(8, rect.top - bh - 10)}px`;
    }, 0);
  }
  clearTimeout(node._timer); node._timer = setTimeout(() => node.classList.add("hidden"), ms);
}
function setConnection(mode, label) {
  const node = $("#conn-badge"); if (!node) return;
  node.className = `status-pill ${mode}`; node.innerHTML = `<span class="status-dot"></span>${label}`;
}
function savePrefs() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify({ symbol: state.symbol, tf: state.tf, method: state.method, position: state.position, leverage: state.leverage, view: document.querySelector(".nav-item.active")?.dataset.view || "dashboard" })); } catch { /* storage disabled */ }
}
function loadPrefs() {
  let prefs = {}; try { prefs = JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); } catch { /* invalid storage */ }
  if (state.symbols.includes(prefs.symbol)) state.symbol = prefs.symbol;
  if (Object.keys(TF_TO_BINANCE).includes(prefs.tf)) state.tf = prefs.tf;
  if (["forecast_based", "historical_simulation", "parametric_student_t"].includes(prefs.method)) state.method = prefs.method;
  if (Number(prefs.position) > 0) state.position = Number(prefs.position);
  if ([1,2,5,10].includes(Number(prefs.leverage))) state.leverage = Number(prefs.leverage);
  setTheme(localStorage.getItem(THEME_KEY) || "dark");
  syncControls();
  if (["risk", "models", "backtest", "explain", "data"].includes(prefs.view)) setView(prefs.view);
}

/* Theme + navigation */
function setTheme(theme) {
  const actual = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = actual;
  try { localStorage.setItem(THEME_KEY, actual); } catch {}
  const button = $("#theme-toggle"); if (button) { button.textContent = actual === "dark" ? "☼" : "☾"; button.title = actual === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"; }
  if (state.candles.length) drawMainChart();
  if (state.performance) drawPerformance();
  if (state.backtest) drawBacktest();
}
function setView(view) {
  const titles = {
    dashboard: ["Tổng quan", "Tổng quan thị trường", "Biến động trực tiếp, dự báo mô hình và tín hiệu rủi ro đuôi cho tài sản số."],
    risk: ["Theo dõi rủi ro", "Triển vọng rủi ro", "So sánh giả định tổn thất và theo dõi trạng thái biến động hiện tại."],
    models: ["Phân tích mô hình", "Đánh giá dự báo", "So sánh các mô hình biến động ngoài mẫu."],
    backtest: ["Kiểm định", "Kiểm định VaR", "Kiểm tra tỷ lệ vi phạm và độ bao phủ theo thời gian."],
    explain: ["Giải thích mô hình", "Minh bạch mô hình", "Tìm hiểu biến đầu vào, giả định và các giới hạn đã biết."],
    data: ["Dữ liệu & hệ thống", "Tập dữ liệu và tình trạng hệ thống", "Quản lý dữ liệu nguồn, file mô hình và tác vụ nền."],
  };
  const meta = titles[view] || titles.dashboard;
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$('[data-view-panel]').forEach((panel) => panel.classList.toggle("hidden", panel.dataset.viewPanel !== view));
  setText("#breadcrumb-title", meta[0]); setText("#page-title", meta[1]); setText("#page-subtitle", meta[2]);
  savePrefs(); lazyLoad(view);
}
function bindNavigation() {
  $$(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => { setView(button.dataset.view); $("#sidebar")?.classList.remove("open"); }));
  $$('[data-view-jump]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.viewJump)));
  $("#mobile-menu")?.addEventListener("click", () => $("#sidebar")?.classList.toggle("open"));
  $("#theme-toggle")?.addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  const search = $("#global-search");
  const dd = $("#coin-dropdown");
  const showDropdown = (q="") => {
    if (!dd) return;
    renderSymbolSwitcher(state.symbols, q);
    dd.classList.remove("hidden");
  };
  const hideDropdown = () => dd?.classList.add("hidden");
  search?.addEventListener("focus", () => showDropdown(search.value.trim()));
  search?.addEventListener("input", (event) => {
    const query = event.target.value.trim();
    if (!query) { hideDropdown(); return; }
    showDropdown(query);
  });
  search?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { hideDropdown(); return; }
    if (event.key !== "Enter") return;
    event.preventDefault();
    const visible = $$("#coin-dropdown button");
    if (visible.length) switchSymbol(visible[0].dataset.symbol);
    else tipPop("Không tìm thấy loại tiền khớp với từ khóa.", search);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-wrap")) hideDropdown();
  });
}

/* Symbol switcher — dropdown only on search */
function renderSymbolSwitcher(symbols = state.symbols, query = "") {
  const dd = $("#coin-dropdown"); if (!dd) return;
  const q = query.trim().toLowerCase();
  const filtered = symbols.filter((s) => !q || shortSymbol(s).toLowerCase().includes(q) || s.toLowerCase().includes(q)).slice(0, 50);
  if (!filtered.length) {
    dd.innerHTML = `<div style="padding:10px;color:var(--muted);font-size:12px">Không có loại tiền nào khớp "${query}".</div>`;
    return;
  }
  dd.innerHTML = filtered.map((symbol) => {
    const label = shortSymbol(symbol);
    return `<button data-symbol="${symbol}" class="${symbol===state.symbol?"active":""}" role="option"><span class="coin-sym">${label} <small style="color:var(--muted)">/ USDT</small></span><span class="coin-price">${symbol===state.symbol?"đang xem":"chọn"}</span></button>`;
  }).join("");
  $$("#coin-dropdown button").forEach((button) => {
    button.addEventListener("click", () => {
      $("#coin-dropdown")?.classList.add("hidden");
      $("#global-search").value = "";
      switchSymbol(button.dataset.symbol);
    });
  });
}

function switchSymbol(symbol) {
  if (state.symbol === symbol) return;
  state.symbol = symbol; state.loadedTabs.clear(); state.performance = state.backtest = state.explain = null; state.perfView=null; state.btView=null;
  syncControls(); savePrefs(); loadAll();
}
function syncControls() {
  if ($("#current-coin")) $("#current-coin").textContent = symbolLabel();
  $$("#leverage-seg button").forEach((button) => button.classList.toggle("active", Number(button.dataset.lev) === state.leverage));
  $$("#tf-seg button").forEach((button) => button.classList.toggle("active", button.dataset.tf === state.tf));
  $$("#method-seg button").forEach((button) => button.classList.toggle("active", button.dataset.method === state.method));
  if ($("#position-input")) $("#position-input").value = state.position;
  setText("#chart-title", symbolLabel());
}

/* Main market chart */
function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  return { text: css.getPropertyValue("--muted-2").trim() || "#647285", grid: css.getPropertyValue("--line-soft").trim() || "rgba(147,163,183,.14)", up: css.getPropertyValue("--positive").trim() || "#00c805", down: css.getPropertyValue("--negative").trim() || "#ff4a4a", bg: css.getPropertyValue("--bg").trim() || "#0c1016" };
}
function visibleRange() {
  const total = state.candles.length;
  if (!total) return [0, 0];
  if (!state.view) return [Math.max(0, total - 160), total];
  return [Math.max(0, state.view[0]), Math.min(total, state.view[1])];
}
function chartIndexFromEvent(event) {
  const canvas = $("#main-chart"); if (!canvas || !state.candles.length) return -1;
  const rect = canvas.getBoundingClientRect(), [from, to] = visibleRange();
  const plotLeft = 10, plotRight = 76, plotWidth = Math.max(1, rect.width - plotLeft - plotRight);
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - plotLeft) / plotWidth));
  return Math.max(from, Math.min(to - 1, from + Math.floor(ratio * (to - from))));
}
function renderChartTooltip(event, index) {
  const tip = $("#chart-tooltip"), candle = state.candles[index]; if (!tip || !candle) return;
  const change = candle.o ? (candle.c / candle.o - 1) * 100 : 0;
  tip.textContent = `${localTs(candle.t)}${candle.closed ? "" : " (đang hình thành)"}\nM ${fmtUSD(candle.o)}   C ${fmtUSD(candle.c)}\nCao ${fmtUSD(candle.h)}   Thấp ${fmtUSD(candle.l)}\n${change >= 0 ? "+" : ""}${fmtNum(change, 2)}% · KL ${fmtNum(candle.v, 2)}`;
  tip.classList.remove("hidden"); tip.style.left = `${Math.min(window.innerWidth - 260, event.clientX + 14)}px`; tip.style.top = `${Math.max(12, event.clientY - 90)}px`;
}
function normalizeCandle(row) {
  return { t: Number(row.t ?? row.open_time ?? row.timestamp ?? row.time), o: Number(row.o ?? row.open), h: Number(row.h ?? row.high), l: Number(row.l ?? row.low), c: Number(row.c ?? row.close), v: Number(row.v ?? row.volume ?? 0), closed: row.closed !== false };
}
function canvasSize(id, height) {
  const canvas = $(id); if (!canvas || !canvas.clientWidth) return null;
  const ratio = window.devicePixelRatio || 1, width = canvas.clientWidth;
  canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0); return { canvas, ctx, width, height };
}
function drawMainChart() {
  const size = canvasSize("#main-chart", window.innerWidth < 680 ? 350 : 430); if (!size) return;
  const { ctx, width, height } = size, data = state.candles, theme = chartTheme(); ctx.clearRect(0, 0, width, height);
  if (!data.length) { ctx.fillStyle = theme.text; ctx.textAlign = "center"; ctx.font = "12px sans-serif"; ctx.fillText("Chưa có dữ liệu thị trường", width / 2, height / 2); return; }
  const from = state.view ? Math.max(0, state.view[0]) : Math.max(0, data.length - 160);
  const to = state.view ? Math.min(data.length, state.view[1]) : data.length;
  const visible = data.slice(from, to);
  let high = Math.max(...visible.map((c) => c.h)), low = Math.min(...visible.map((c) => c.l)), maxVolume = Math.max(...visible.map((c) => c.v), 1);
  const pad = (high - low || high * 0.01) * 0.08; high += pad; low -= pad;
  const left = 10, right = 76, top = 12, bottom = 30, volume = 50, plotH = height - top - bottom - volume;
  const plotW = width - left - right;
  const step = plotW / Math.max(visible.length, 1);
  const candleW = Math.max(1.5, Math.min(12, step * 0.64));
  const x = (i) => left + (i + 0.5) * step;
  const y = (price) => top + (high - price) / (high - low) * plotH;
  ctx.font = "10px Consolas, monospace"; ctx.lineWidth = 1;
  for (let g = 0; g <= 5; g++) { const price = low + (high - low) * g / 5, yy = y(price); ctx.strokeStyle = theme.grid; ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke(); ctx.fillStyle = theme.text; ctx.textAlign = "left"; ctx.fillText(fmtUSD(price, price > 100 ? 0 : 2), width - right + 8, yy + 3); }
  visible.forEach((c, i) => { const xx = x(i), up = c.c >= c.o, color = up ? theme.up : theme.down; ctx.strokeStyle = color; ctx.beginPath(); ctx.moveTo(xx, y(c.h)); ctx.lineTo(xx, y(c.l)); ctx.stroke(); ctx.fillStyle = color; const y1 = y(Math.max(c.o, c.c)), y2 = y(Math.min(c.o, c.c)); ctx.fillRect(xx - candleW / 2, y1, candleW, Math.max(1, y2 - y1)); const vh = (c.v / maxVolume) * (volume - 10); ctx.globalAlpha = 0.35; ctx.fillRect(xx - candleW / 2, top + plotH + volume - vh, candleW, vh); ctx.globalAlpha = 1; });
  ctx.fillStyle = theme.text; ctx.textAlign = "center"; const every = Math.max(1, Math.floor(visible.length / 6)); for (let i = 0; i < visible.length; i += every) ctx.fillText(localTs(visible[i].t), x(i), height - 7);
  const last = data[data.length - 1]; ctx.setLineDash([4, 4]); ctx.strokeStyle = theme.text; ctx.globalAlpha = 0.55; ctx.beginPath(); ctx.moveTo(left, y(last.c)); ctx.lineTo(width - right, y(last.c)); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
  setText("#chart-meta", `${symbolLabel()} · ${state.tf} · ${visible.length}/${data.length} nến · nến cuối ${last.closed ? "đã đóng" : "đang hình thành"}`);
}
function bindChartEvents() {
  const canvas = $("#main-chart"); if (!canvas) return;
  let drag = null;
  $("#chart-reset")?.addEventListener("click", () => { state.view = null; state.chartHover = -1; $("#chart-tooltip")?.classList.add("hidden"); drawMainChart(); });
  $("#chart-reset-perf")?.addEventListener("click", ()=>{ state.perfView=null; drawPerformance(); });
  $("#chart-reset-bt")?.addEventListener("click", ()=>{ state.btView=null; drawBacktest(); });
  canvas.addEventListener("mousemove", (event) => {
    const index = chartIndexFromEvent(event); if (index < 0) return;
    if (drag) {
      const [from, to] = drag.range, span = to - from, pixelsPerCandle = Math.max(2, canvas.clientWidth / Math.max(1, span));
      const shift = Math.round((drag.startX - event.clientX) / pixelsPerCandle), nextFrom = Math.max(0, Math.min(state.candles.length - span, from + shift));
      state.view = [nextFrom, nextFrom + span]; $("#chart-tooltip")?.classList.add("hidden"); drawMainChart(); return;
    }
    state.chartHover = index; renderChartTooltip(event, index); drawMainChart();
  });
  canvas.addEventListener("mouseleave", () => { drag = null; state.chartHover = -1; $("#chart-tooltip")?.classList.add("hidden"); drawMainChart(); });
  canvas.addEventListener("mousedown", (event) => { drag = { startX: event.clientX, range: visibleRange() }; canvas.style.cursor = "grabbing"; });
  window.addEventListener("mouseup", () => { drag = null; if (canvas) canvas.style.cursor = "crosshair"; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault(); const [from, to] = visibleRange(), span = to - from, focus = chartIndexFromEvent(event); if (!span || focus < 0) return;
    const nextSpan = Math.max(20, Math.min(state.candles.length, Math.round(span * (event.deltaY > 0 ? 1.25 : 0.8)))), ratio = (focus - from) / Math.max(1, span);
    const nextFrom = Math.max(0, Math.min(state.candles.length - nextSpan, Math.round(focus - nextSpan * ratio))); state.view = [nextFrom, nextFrom + nextSpan]; drawMainChart();
  }, { passive: false });
  window.addEventListener("resize", () => { drawMainChart(); if (state.performance) drawPerformance(); if (state.backtest) drawBacktest(); });
}

/* REST + WebSocket */
function updatePrice(price) {
  const priceNode = $("#kpi-price");
  if (priceNode) { priceNode.classList.remove("skeleton"); priceNode.textContent = price == null ? "—" : fmtUSD(price, Number(price) >= 1000 ? 0 : 2); }
  setText("#kpi-updated", new Date().toLocaleTimeString("vi-VN", { hour12: false }));
}
function updateTicker(price, change, stale) {
  updatePrice(price);
  const node = $("#kpi-change"); if (node) { const positive = Number(change) >= 0; node.textContent = `24h: ${change == null ? "—" : `${positive ? "▲" : "▼"} ${fmtPct(Math.abs(change), 2)}`}`; node.className = `metric-delta ${change == null ? "muted" : positive ? "up" : "down"}`; }
  setText("#price-src", stale ? "Dữ liệu thị trường đã lưu" : "Dữ liệu công khai Binance");
  setConnection(stale ? "offline" : "live", stale ? "Đã lưu" : "Trực tiếp");
}
async function loadChart() {
  $("#chart-loading")?.classList.remove("hidden");
  try {
    const candles = await api(`/api/ohlcv?symbol=${state.symbol}&interval=${state.tf}&limit=500`);
    state.candles = (candles.candles || []).map(normalizeCandle).filter((c) => Number.isFinite(c.c) && Number.isFinite(c.t)); state.view = null;
    updateTicker(candles.price, candles.change_pct_24h, candles.stale);
    const ticker = await api(`/api/ticker?symbol=${state.symbol}`); updateTicker(ticker.price, ticker.change_pct_24h, ticker.stale);
    if (candles.stale) showStale("Không kết nối được nguồn trực tiếp — biểu đồ đang dùng dữ liệu đã lưu."); else hideStale();
  } catch (error) { toast(`Không tải được biểu đồ: ${error.message}`, true); setConnection("offline", "Ngoại tuyến"); state.candles = []; }
  $("#chart-loading")?.classList.add("hidden"); drawMainChart();
}
function wsUrl() { const symbol = state.symbol.toLowerCase(); return `${state.wsBase}/stream?streams=${symbol}@kline_${TF_TO_BINANCE[state.tf]}/${symbol}@miniTicker`; }
function connectWS() {
  clearTimeout(state.wsTimer); if (state.ws) { state.ws.onclose = null; try { state.ws.close(); } catch {} }
  try { state.ws = new WebSocket(wsUrl()); } catch { scheduleWSReconnect(); return; }
  state.ws.onopen = () => { state.wsRetries = 0; setConnection("live", "Trực tiếp"); clearInterval(state.pollTimer); state.pollTimer = null; };
  state.ws.onmessage = (event) => { try { const message = JSON.parse(event.data), data = message.data || message; state.lastTickAt = Date.now(); if (data.e === "kline" && data.k) { const k = data.k, next = normalizeCandle({ t: k.t, o: k.o, h: k.h, l: k.l, c: k.c, v: k.v, closed: k.x }); const current = state.candles[state.candles.length - 1]; if (current && current.t === next.t) state.candles[state.candles.length - 1] = next; else { state.candles.push(next); if (state.candles.length > 1000) state.candles.shift(); } updatePrice(next.c); drawMainChart(); } else if (data.e === "24hrMiniTicker") { const price = Number(data.c), open = Number(data.o); updateTicker(price, open ? (price / open - 1) * 100 : null, false); } } catch { /* bỏ qua gói tin không hợp lệ */ } };
  state.ws.onclose = () => { setConnection("reconnecting", "Đang kết nối lại"); scheduleWSReconnect(); startPolling(); };
  state.ws.onerror = () => { try { state.ws.close(); } catch {} };
}
function scheduleWSReconnect() { clearTimeout(state.wsTimer); const delay = Math.min(30000, 1000 * 2 ** Math.min(state.wsRetries, 5)) + Math.round(Math.random() * 700); state.wsRetries += 1; state.wsTimer = setTimeout(connectWS, delay); }
function startPolling() { if (state.pollTimer) return; state.pollTimer = setInterval(() => loadChart(), 15000); }
function showStale(message) { $("#stale-banner")?.classList.remove("hidden"); setText("#stale-text", message); }
// không phải giá trực tiếp: khi stale, dữ liệu hiển thị là dữ liệu đã lưu, không phải giá trực tiếp
function hideStale() { $("#stale-banner")?.classList.add("hidden"); }

/* Explanation texts: ý nghĩa, tại sao số lại như vậy, hiệu ứng */
function riskExplainText(f) {
  const r = f.risk?.[state.method] || f.risk?.forecast_based || {};
  const selected = MODEL_NAMES[f.selected_model] || f.selected_model || "mô hình mặc định";
  if (state.method === "forecast_based") {
    return `VaR theo dự báo lấy biến động 1 ngày của ${selected}, kết hợp phần đuôi Student-t (df ${fmtNum(r.t_df, 1)}) và quy mô theo vị thế ${fmtUSD(r.reference_position_usd ?? state.position)}. Hiệu ứng: biến động dự báo càng cao → VaR/ES càng lớn → cần nắm giữ tài sản bảo vệ nhiều hơn; VaR không phải mức lỗ tối đa, chỉ là ngưỡng có khoảng 5% xác suất vượt qua trong 1 ngày.`;
  }
  if (state.method === "historical_simulation") {
    return `Mô phỏng lịch sử lấy ${r.n_obs || "nhiều"} lợi suất ngày gần nhất, tính ngưỡng trực tiếp từ quan sát thực, không áp đặt phân phối nào. Hiệu ứng: phản ánh đúng các cú sốc lịch sử, nhưng nếu tài sản này chưa từng trải qua giai đoạn khủng hoảng thì ngưỡng có thể bị đánh giá thấp.`;
  }
  return `Student-t tham số được ước lượng trên toàn bộ lịch sử lợi suất ngày (df ${fmtNum(r.params?.df, 1)}). Hiệu ứng: phân phối Student-t có đuôi dày hơn chuẩn ⇒ ES thường cao hơn VaR tương ứng, phù hợp với tài sản crypto có độ nhạy cao.`;
}
function modelsExplainText(p) {
  const best = MODEL_NAMES[p.selected_model] || p.selected_model || "—";
  const m = p.metrics?.[p.selected_model];
  const mae = m?.mae_vol == null ? "—" : fmtPct(m.mae_vol * 100, 2);
  const rmse = m?.rmse_vol == null ? "—" : fmtPct(m.rmse_vol * 100, 2);
  const qlike = m?.qlike == null ? "—" : fmtNum(m.qlike, 3);
  return `Mô hình ${best} được chọn vì có QLIKE ngoài mẫu thấp nhất (${qlike}). MAE = ${mae}, RMSE = ${rmse} cho sai số dự báo biến động trung bình (phần trăm). Hiệu ứng: QLIKE càng thấp ⇒ ước lượng biến động đi kèm VaR/ES càng tin cậy ⇒ vị thế quản trị rủi ro dựa trên các ngưỡng này càng ổn định.`;
}
function backtestExplainText(b) {
  const s95 = b.summary_95 || {}; const s99 = b.summary_99 || {};
  return `Kỳ hạn kiểm tra ${s95.n ?? "—"} ngày; kỳ vọng vi phạm VaR 95% là 5%, thực tế ${fmtPct(Number((s95.breach_rate || 0)) * 100, 1)}% (${s95.breaches ?? "—"} lần). Kupiec p = ${s95.kupiec?.p_value == null ? "không đủ dữ liệu" : fmtNum(s95.kupiec.p_value, 3)}; Christoffersen p = ${s95.christoffersen?.p_value_conditional_coverage == null ? "không đủ dữ liệu" : fmtNum(s95.christoffersen.p_value_conditional_coverage, 3)}. Hiệu ứng: p-value nhỏ ⇒ mô hình vi phạm đều đặn (thiếu hoặc thừa rủi ro) ⇒ không nên dựa vào ngưỡng này để đặt vị thế lớn.`;
}

/* Forecast and risk */
function renderForecast(f) {
  state.forecast = f; $("#empty-state")?.classList.add("hidden");
  const regime = f.regime || {}, risk = f.risk?.[state.method] || f.risk?.forecast_based || {};
  setText("#kpi-regime", regime.label_vi || regime.label || "—"); setText("#kpi-regime-sub", regime.percentile_vs_train == null ? "Phân vị tập huấn luyện" : `Phân vị ${fmtNum(regime.percentile_vs_train, 0)} so với tập huấn luyện`);
  setText("#kpi-fvol", fmtPct(f.forecast_vol_annualized_pct, 1)); setText("#kpi-fvol-sub", `1 ngày · ngày ${fmtPct(Number(f.forecast_vol_daily || 0) * 100, 2)}`);
  setRiskMetrics(f); setText("#kpi-updated", localTime(f.generated_at_utc)); setText("#last-sync", localTime(f.generated_at_utc));
  if (f.interpretation?.market_summary) { $("#summary-band")?.classList.remove("hidden"); setText("#summary-text", f.interpretation.market_summary); }
  setText("#regime-desc", regime.description || "—"); setText("#risk-regime-label", regime.label_vi || regime.label || "—");
  const pct = Number(regime.percentile_vs_train); if (Number.isFinite(pct)) $("#regime-marker").style.left = `${Math.min(98, Math.max(2, pct))}%`;
  const kv = $("#vol-kv"); if (kv) kv.innerHTML = `<dt>Biến động dự báo (năm hóa)</dt><dd>${fmtPct(f.forecast_vol_annualized_pct, 1)}</dd><dt>Biến động thực tế gần nhất</dt><dd>${fmtPct(f.current_realized_vol_annualized_pct, 1)}</dd><dt>Phân vị tập huấn luyện</dt><dd>${Number.isFinite(pct) ? fmtPct(pct, 0) : "—"}</dd><dt>Mô hình đang chọn</dt><dd>${MODEL_NAMES[f.selected_model] || f.selected_model || "—"}</dd>`;
  renderModelList(f.models_vol_annualized_pct, f.selected_model, "#model-vol-list"); renderModelList(f.models_vol_annualized_pct, f.selected_model, "#risk-model-list");
  setText("#regime-desc", regime.description || "—");
  setText("#risk-interpretation", f.interpretation?.risk_summary || "Ước lượng rủi ro dựa trên mô hình và phương pháp đang chọn.");
  setText("#risk-method-note", riskMethodNote(f));
  setText("#risk-explain-text", riskExplainText(f));
  const wrong = f.interpretation?.what_could_be_wrong || []; const limits = f.limitations || [];
  if ($("#wrong-list")) $("#wrong-list").innerHTML = wrong.map((item) => `<li>${item}</li>`).join("") || "<li>Không có ghi chú bổ sung.</li>";
  if ($("#limit-list")) $("#limit-list").innerHTML = limits.map((item) => `<li>${item}</li>`).join("") || "<li>Xem phần phương pháp để biết thêm chi tiết.</li>";
  if ($("#method-defs")) $("#method-defs").innerHTML = `<p><b>Quy ước:</b> ${f.risk?.convention || "Tổn thất được biểu diễn bằng số dương."}</p><p><b>Cách chọn mô hình:</b> ${f.risk?.selection_rule || "Chọn mô hình có QLIKE ngoài mẫu thấp nhất."}</p><p>Biến động dự báo đo quy mô dao động kỳ vọng, không dự báo hướng giá. VaR là ngưỡng tổn thất; ES mô tả mức lỗ trung bình vượt ngưỡng đó.</p>`;
}
function renderModelList(models = {}, selected, selector) {
  const node = $(selector); if (!node) return;
  node.innerHTML = Object.entries(models).map(([key, value]) => `<div class="model-row"><span>${MODEL_NAMES[key] || key}${key === selected ? `<span class="best-tag">đang dùng</span>` : ""}</span><b>${fmtPct(value, 1)}</b></div>`).join("") || `<div class="panel-copy">Chưa có ước lượng mô hình.</div>`;
}
function riskMethodNote(f) {
  const selected = MODEL_NAMES[f.selected_model] || f.selected_model || "mô hình đang chọn"; const r = f.risk?.[state.method];
  if (state.method === "forecast_based") return `VaR theo dự báo dùng biến động của ${selected} kết hợp phần đuôi Student-t (df ${fmtNum(r?.t_df, 1)}).`;
  if (state.method === "historical_simulation") return `Mô phỏng lịch sử dùng ${r?.n_obs || "các"} lợi suất ngày gần nhất, không áp đặt phân phối tham số.`;
  return `Student-t tham số được ước lượng trên toàn bộ lịch sử lợi suất ngày (df ${fmtNum(r?.params?.df, 1)}).`;
}
function setRiskMetrics(f) {
  const chosenRaw = f.risk?.[state.method] || f.risk?.forecast_based || {};
  const lev = Number(state.leverage) || 1;
  const scale = (v) => v == null ? v : Number(v) * lev;
  const chosen = { var_95: scale(chosenRaw.var_95), es_95: scale(chosenRaw.es_95), var_99: scale(chosenRaw.var_99), es_99: scale(chosenRaw.es_99), var_95_pct: chosenRaw.var_95_pct!=null?Number(chosenRaw.var_95_pct)*lev:null, var_99_pct: chosenRaw.var_99_pct!=null?Number(chosenRaw.var_99_pct)*lev:null, es_95_pct: chosenRaw.es_95_pct!=null?Number(chosenRaw.es_95_pct)*lev:null, es_99_pct: chosenRaw.es_99_pct!=null?Number(chosenRaw.es_99_pct)*lev:null };
  const update = (id, value) => setText(id, fmtUSD(value)); const updatePct = (id, value) => setText(id, `${fmtPct(value, 2)} của vị thế`);
  update("#r-var95", chosen.var_95); update("#r-es95", chosen.es_95); update("#r-var99", chosen.var_99); update("#r-es99", chosen.es_99);
  update("#risk-var95-large", chosen.var_95); update("#risk-es95-large", chosen.es_95); update("#risk-var99-large", chosen.var_99); update("#risk-es99-large", chosen.es_99);
  updatePct("#r-es95-pct", chosen.es_95_pct); updatePct("#risk-es95-pct", chosen.es_95_pct); updatePct("#risk-var95-pct", chosen.var_95_pct); updatePct("#risk-var99-pct", chosen.var_99_pct); updatePct("#risk-es99-pct", chosen.es_99_pct);
  setText("#kpi-var", fmtUSD(scale(f.risk?.forecast_based?.var_95))); setText("#kpi-var-sub", `${fmtPct(scale(f.risk?.forecast_based?.var_95_pct), 2)} · 1 ngày${lev>1?` · ${lev}× đòn bẩy`:""}`);
  const label = f.regime?.label_vi || f.regime?.label || "—"; setText("#risk-badge", label);
  setText("#risk-model-note", `Phương pháp: ${state.method === "forecast_based" ? "Theo dự báo" : state.method === "historical_simulation" ? "Mô phỏng lịch sử" : "Student-t"} · ${MODEL_NAMES[f.selected_model] || f.selected_model || "—"}${lev>1?` · ${lev}× đòn bẩy`:""}`);
  const note = $("#leverage-note"); if(note) note.textContent = lev>1 ? `Đòn bẩy ${lev}× đang áp dụng: mọi ngưỡng tổn thất đã nhân ${lev}. VD: VaR gốc ${fmtUSD(chosenRaw.var_95)} → ${fmtUSD(chosen.var_95)}.` : "Đòn bẩy khuếch đại tuyến tính VaR/ES: Tổn thất có đòn bẩy = Tổn thất gốc × đòn bẩy.";
}
async function loadForecast() {
  try {
    const f = await api(`/api/forecast?symbol=${state.symbol}&position_usd=${state.position}`);
    renderForecast(f);
  } catch (error) {
    state.forecast = null;
    const empty = $("#empty-state"); empty?.classList.remove("hidden");
    if (error.code === "MODEL_CORRUPTED") { setText("#empty-title", "Không đọc được file mô hình"); setText("#empty-text", error.message || "Hãy chạy cập nhật --retrain hoặc nạp dữ liệu lại để tạo lại mô hình."); }
    else if (error.code === "MODEL_NOT_INITIALIZED") {
      setText("#empty-title", `Chưa có mô hình rủi ro cho ${shortSymbol(state.symbol)}`);
      setText("#empty-text", `Biểu đồ giá của ${symbolLabel()} vẫn chạy trực tiếp từ Binance, nhưng chỉ số VaR/ES cần mô hình đã huấn luyện. Bấm nút bên dưới để tải dữ liệu và huấn luyện loại tiền này (chạy nền, không khóa giao diện).`);
      const btn = $("#btn-prepare-symbol"); if (btn) { btn.classList.remove("hidden"); btn.onclick = () => startJob("prepare", state.symbol); }
    } else { setText("#empty-title", "Mô hình chưa được khởi tạo"); setText("#empty-text", error.message || "Hãy nạp dữ liệu và huấn luyện mô hình để bật dự báo."); }
    const btn = $("#btn-prepare-symbol"); if (btn && error.code !== "MODEL_NOT_INITIALIZED") btn.classList.add("hidden");
  }
}

/* Model analytics and backtesting */
function drawLineChart(id, series, labels = [], height = 300, zeroBase = false) {
  const size = canvasSize(id, window.innerWidth < 680 ? Math.min(height, 250) : height); if (!size) return null;
  const { ctx, width, height: h } = size, theme = chartTheme(), left = 8, right = 62, top = 12, bottom = 24, plotW = width - left - right, plotH = h - top - bottom;
  let values = series.flatMap((s) => s.data).filter((v) => Number.isFinite(v));
  if (!values.length) return null;
  let hi = Math.max(...values), lo = Math.min(...values); if (zeroBase) lo = Math.min(0, lo); const span = hi - lo || 1; hi += span * 0.08; lo -= span * 0.04;
  const count = Math.max(...series.map((s) => s.data.length), 1);
  const x = (i) => left + plotW * (count <= 1 ? 0 : i / (count - 1));
  const y = (v) => top + (hi - v) / (hi - lo) * plotH;
  ctx.clearRect(0, 0, width, h);
  // subtle background gradient
  const grad = ctx.createLinearGradient(0,0,0,h); grad.addColorStop(0, theme.bg + '12'); grad.addColorStop(1, 'transparent'); ctx.fillStyle=grad; ctx.fillRect(left, top, plotW, plotH);
  ctx.strokeStyle = theme.grid; ctx.lineWidth = 1; ctx.setLineDash([3,4]);
  for (let g = 0; g <= 4; g++) { const v = lo + (hi - lo) * g / 4, yy = y(v); ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke(); }
  ctx.setLineDash([]);
  series.forEach((s) => { const pts = s.data.map((v, i) => ({ x: x(i), y: Number.isFinite(v) ? y(v) : null })).filter((p) => p.y != null); if (pts.length < 2) return; ctx.strokeStyle = s.color || "#57a6ff"; ctx.lineWidth = s.width || 2; ctx.lineJoin='round'; ctx.lineCap='round'; ctx.shadowColor=s.color||"#57a6ff"; ctx.shadowBlur=s.width>1.5?6:0; ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y); for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y); ctx.stroke(); ctx.shadowBlur=0; });
  if (labels.length) { ctx.fillStyle = theme.text; ctx.textAlign = "center"; ctx.font = "10px sans-serif"; const every = Math.max(1, Math.floor(labels.length / 6)); for (let i = 0; i < labels.length; i += every) ctx.fillText(labels[i], x(i), h - 6); }
  return { ctx, x, y, width, height: h };
}
async function loadPerformance() {
  const data = await api(`/api/performance?symbol=${state.symbol}`); state.performance = data; setText("#perf-note", `${data.note || "So sánh các mô hình ngoài mẫu."} Đang chọn: ${MODEL_NAMES[data.selected_model] || data.selected_model || "—"}.`);
  if ($("#perf-legend")) $("#perf-legend").innerHTML = `<span><i class="sw" style="background:#22c55e"></i>Thực tế</span>${Object.keys(data.forecasts_vol_daily || {}).map((key) => `<span><i class="sw" style="background:${MODEL_COLORS[key] || "#57a6ff"}"></i>${MODEL_NAMES[key] || key}</span>`).join("")}`;
  const series = [{ data: (data.actual_vol_daily || []).map((v) => v == null ? null : Number(v) * 100), color: "#22c55e" }];
  Object.entries(data.forecasts_vol_daily || {}).forEach(([key, values]) => series.push({ data: values.map((v) => v == null ? null : Number(v) * 100), color: MODEL_COLORS[key] || "#57a6ff", width: key === data.selected_model ? 2.2 : 1.2 }));
  drawLineChart("#perf-chart", series, data.dates || [], 300);
  if ($("#metrics-table tbody")) $("#metrics-table tbody").innerHTML = Object.entries(data.metrics || {}).map(([key, metric]) => `<tr class="${key === data.selected_model ? "best" : ""}"><td>${MODEL_NAMES[key] || key}</td><td>${fmtPct(Number(metric.mae_vol) * 100, 2)}</td><td>${fmtPct(Number(metric.rmse_vol) * 100, 2)}</td><td>${fmtNum(metric.qlike, 3)}</td><td>${metric.n ?? "—"}</td><td>${key === data.selected_model ? "Tốt nhất theo QLIKE" : "—"}</td></tr>`).join("") || `<tr><td colspan="6">Chưa có dữ liệu hiệu quả mô hình.</td></tr>`;
  setText("#models-explain-text", modelsExplainText(data));
  const list = $("#models-explain-list"); if (list) {
    list.innerHTML = [
      `MAE (${fmtPct(Number(data.metrics?.[data.selected_model]?.mae_vol || 0) * 100, 2)}): sai số trung bình của dự báo biến động so với thực tế — càng thấp, dự báo càng sát thực tế.`,
      `RMSE (${fmtPct(Number(data.metrics?.[data.selected_model]?.rmse_vol || 0) * 100, 2)}): phạt sai số lớn nặng hơn MAE — dùng để phát hiện mô hình hay bị lệch khi biến động đột ngột.`,
      `QLIKE (${fmtNum(data.metrics?.[data.selected_model]?.qlike || 0, 3)}): hàm mất mát phù hợp biến động, tiêu chí chọn mô hình chính của dashboard — mô hình có QLIKE ngoài mẫu thấp nhất được dùng cho VaR/ES.`,
    ].map((t) => `<li>${t}</li>`).join("");
  }
  drawPerformance();
}
function perfVisibleRange(){
  const p=state.performance; if(!p||!p.dates) return [0,0];
  const total=p.dates.length; if(!total) return [0,0];
  if(!state.perfView) return [0,total];
  return [Math.max(0,state.perfView[0]), Math.min(total,state.perfView[1])];
}
function perfIndexFromEvent(e){
  const cvs=document.querySelector("#perf-chart"); if(!cvs) return -1;
  const rect=cvs.getBoundingClientRect(); const [f,t]=perfVisibleRange(); const span=t-f||1;
  const left=8,right=62, plotW=Math.max(1,rect.width-left-right);
  const ratio=Math.max(0,Math.min(1,(e.clientX-rect.left-left)/plotW));
  return f + Math.floor(ratio*span);
}
function drawPerformance() {
  const p = state.performance; if (!p) return;
  const [pf,pt]=perfVisibleRange(); const slice=(arr)=>arr?arr.slice(pf,pt):[];
  const labels=slice(p.dates||[]);
  const series = [{ data: slice((p.actual_vol_daily || []).map((v) => v == null ? null : Number(v) * 100)), color: "#22c55e" }];
  Object.entries(p.forecasts_vol_daily || {}).forEach(([key, values]) => series.push({ data: slice(values.map((v) => v == null ? null : Number(v) * 100)), color: MODEL_COLORS[key] || "#57a6ff", width: key === p.selected_model ? 2.2 : 1.2 }));
  drawLineChart("#perf-chart", series, labels, 300);
  bindPerfTooltip();
}
function bindPerfTooltip(){
  const cvs = document.querySelector("#perf-chart"); if(!cvs || cvs._boundPerf) return; cvs._boundPerf=true;
  let drag=null;
  cvs.addEventListener("mousedown", (e)=>{ drag={startX:e.clientX, range:perfVisibleRange()}; cvs.style.cursor="grabbing"; });
  window.addEventListener("mouseup", ()=>{ drag=null; if(cvs) cvs.style.cursor="crosshair"; });
  cvs.addEventListener("mousemove", (e)=>{
    const p = state.performance; if(!p) return;
    if(drag){
      const [f,t]=drag.range; const span=t-f||1; const pixelsPer=Math.max(2,cvs.clientWidth/Math.max(1,span));
      const shift=Math.round((drag.startX-e.clientX)/pixelsPer);
      const total=(p.dates||[]).length;
      let nf=Math.max(0,Math.min(total-span, f+shift)); state.perfView=[nf,nf+span]; drawPerformance(); return;
    }
    const idx=perfIndexFromEvent(e);
    const labels=p.dates||[]; if(idx<0||idx>=labels.length) return;
    const vals = [`Ngày: ${labels[idx]||""}`, `Thực tế: ${fmtPct((p.actual_vol_daily||[])[idx]*100||0,2)}`];
    Object.entries(p.forecasts_vol_daily||{}).forEach(([k,v])=>{ const val=v[idx]; if(val!=null) vals.push(`${MODEL_NAMES[k]||k}: ${fmtPct(val*100,2)}`); });
    const tip=document.querySelector("#chart-tooltip"); if(tip){ tip.textContent=vals.join("\n"); tip.classList.remove("hidden"); tip.style.left=`${Math.min(window.innerWidth-260,e.clientX+14)}px`; tip.style.top=`${Math.max(12,e.clientY-70)}px`; }
  });
  cvs.addEventListener("mouseleave", ()=> { drag=null; document.querySelector("#chart-tooltip")?.classList.add("hidden"); });
  cvs.addEventListener("wheel", (e)=>{
    e.preventDefault(); const p=state.performance; if(!p) return;
    const total=(p.dates||[]).length; const [f,t]=perfVisibleRange(); const span=t-f||1; if(!span) return;
    const focus=perfIndexFromEvent(e);
    const nextSpan=Math.max(20, Math.min(total, Math.round(span*(e.deltaY>0?1.25:0.8))));
    const ratio=(focus-f)/Math.max(1,span); let nf=Math.round(focus - nextSpan*ratio);
    nf=Math.max(0,Math.min(total-nextSpan,nf)); state.perfView=[nf,nf+nextSpan]; drawPerformance();
  }, {passive:false});
}
function renderBacktestSummary(node, summary, level) { if (!node || !summary) return; node.innerHTML = `<dl class="definition-list"><dt>Số ngày kiểm tra</dt><dd>${summary.n ?? "—"}</dd><dt>Số lần vi phạm</dt><dd>${summary.breaches ?? "—"} (${fmtPct(Number(summary.breach_rate || 0) * 100, 1)})</dd><dt>Kupiec</dt><dd>${summary.kupiec?.p_value == null ? "Không đủ dữ liệu" : `p ${fmtNum(summary.kupiec.p_value, 3)}`}</dd><dt>Christoffersen</dt><dd>${summary.christoffersen?.p_value_conditional_coverage == null ? "Không đủ dữ liệu" : `p ${fmtNum(summary.christoffersen.p_value_conditional_coverage, 3)}`}</dd><dt>Tỷ lệ kỳ vọng</dt><dd>${fmtPct(100 - level, 0)}</dd></dl>`; }
async function loadBacktest() {
  const data = await api(`/api/backtest?symbol=${state.symbol}`); state.backtest = data; setText("#bt-method", `${data.method || "Kiểm định rolling"} · vị thế ${fmtUSD(data.reference_position_usd)}`);
  renderBacktestSummary($("#bt95"), data.summary_95, 95); renderBacktestSummary($("#bt99"), data.summary_99, 99);
  if ($("#breach-table tbody")) $("#breach-table tbody").innerHTML = (data.series || []).filter((row) => row.breach95).map((row) => `<tr><td>${row.date}</td><td>${fmtUSD(row.loss_usd)}</td><td>${fmtUSD(row.var95_usd)}</td><td>${fmtUSD(row.var99_usd)}</td><td>${row.breach99 ? "Vượt VaR99" : "Vượt VaR95"}</td></tr>`).join("") || `<tr><td colspan="5">Không có vi phạm trong kỳ kiểm tra.</td></tr>`;
  setText("#bt-explain-text", backtestExplainText(data));
  const list = $("#bt-explain-list"); if (list) {
    list.innerHTML = [
      `Kupiec kiểm tra xem số lần vi phạm có khớp tỷ lệ kỳ vọng (5% hoặc 1%) hay không — p-value lớn có nghĩa mô hình chuẩn xác về tỉ lệ vi phạm.`,
      `Christoffersen kiểm tra các vi phạm có liền tiếp nhau hay không — vi phạm dồn thành cụm có ý nghĩa rủi ro cao hơn vi phạm đơn lẻ.`,
      `Nếu tỷ lệ vi phạm thực tế cao hơn kỳ vọng nhiều, ngưỡng VaR đang đánh giá thiếu rủi ro → cần nắm giữ tài sản bảo vệ lớn hơn hoặc giảm vị thế.`,
    ].map((t) => `<li>${t}</li>`).join("");
  }
  drawBacktest();
}
function btVisibleRange(){
  const b=state.backtest; if(!b||!b.series) return [0,0];
  const total=b.series.length; if(!total) return [0,0];
  if(!state.btView) return [0,total];
  return [Math.max(0,state.btView[0]), Math.min(total,state.btView[1])];
}
function btIndexFromEvent(e){
  const cvs=document.querySelector("#bt-chart"); if(!cvs) return -1;
  const rect=cvs.getBoundingClientRect(); const [f,t]=btVisibleRange(); const span=t-f||1;
  const left=8,right=62, plotW=Math.max(1,rect.width-left-right);
  const ratio=Math.max(0,Math.min(1,(e.clientX-rect.left-left)/plotW));
  return f + Math.floor(ratio*span);
}
function fillBtLegend(){ const el=document.querySelector('#bt-legend'); if(el) el.innerHTML=`<span><i class="sw" style="background:#8290a3"></i>Tổn thất thực tế (Loss)</span><span><i class="sw" style="background:#31c7ff"></i>VaR 95%</span><span><i class="sw" style="background:#f2b64b"></i>VaR 99%</span><span><i style="display:inline-block;width:6px;height:6px;background:#ff4a4a;border-radius:50%;margin-right:4px;vertical-align:middle"></i>Vi phạm</span>`; }
function drawBacktest() {
  const b = state.backtest; if (!b) return;
  const [bf,bt]=btVisibleRange();
  fillBtLegend();
  const rowsSlice = (b.series||[]).slice(bf,bt);
  const labels = rowsSlice.map(r=>r.date);
  const chart = drawLineChart("#bt-chart", [{ data: rowsSlice.map((r) => r.loss_usd), color: "#8290a3" }, { data: rowsSlice.map((r) => r.var95_usd), color: "#31c7ff" }, { data: rowsSlice.map((r) => r.var99_usd), color: "#f2b64b" }], labels, 280, true);
  if (!chart) return;
  rowsSlice.forEach((row, index) => { if (row.breach95) { chart.ctx.fillStyle = "#ff4a4a"; chart.ctx.beginPath(); chart.ctx.arc(chart.x(index), chart.y(row.loss_usd), 3, 0, Math.PI * 2); chart.ctx.fill(); } });
  bindBtTooltip();
}
function bindBtTooltip(){
  const cvs=document.querySelector("#bt-chart"); if(!cvs || cvs._boundBt) return; cvs._boundBt=true;
  let drag=null;
  cvs.addEventListener("mousedown",(e)=>{ drag={startX:e.clientX, range:btVisibleRange()}; cvs.style.cursor="grabbing"; });
  window.addEventListener("mouseup",()=>{ drag=null; if(cvs) cvs.style.cursor="crosshair"; });
  cvs.addEventListener("mousemove",(e)=>{
    const b=state.backtest; if(!b) return;
    if(drag){
      const [f,t]=drag.range; const span=t-f||1; const total=(b.series||[]).length; const pixelsPer=Math.max(2,cvs.clientWidth/Math.max(1,span));
      const shift=Math.round((drag.startX-e.clientX)/pixelsPer);
      let nf=Math.max(0,Math.min(total-span,f+shift)); state.btView=[nf,nf+span]; drawBacktest(); return;
    }
    const rows=b.series||[]; if(!rows.length) return;
    const idx=btIndexFromEvent(e); if(idx<0||idx>=rows.length) return;
    const r=rows[idx];
    const vals=[`Ngày: ${r.date}`, `Loss: ${fmtUSD(r.loss_usd)}`, `VaR95: ${fmtUSD(r.var95_usd)}`, `VaR99: ${fmtUSD(r.var99_usd)}`, r.breach95 ? (r.breach99 ? "Vi phạm VaR99" : "Vi phạm VaR95") : "Không vi phạm"];
    const tip=document.querySelector("#chart-tooltip"); if(tip){ tip.textContent=vals.join("\n"); tip.classList.remove("hidden"); tip.style.left=`${Math.min(window.innerWidth-260,e.clientX+14)}px`; tip.style.top=`${Math.max(12,e.clientY-70)}px`; }
  });
  cvs.addEventListener("mouseleave",()=> { drag=null; document.querySelector("#chart-tooltip")?.classList.add("hidden"); });
  cvs.addEventListener("wheel",(e)=>{
    e.preventDefault(); const b=state.backtest; if(!b) return;
    const total=(b.series||[]).length; const [f,t]=btVisibleRange(); const span=t-f||1;
    const focus=btIndexFromEvent(e); const nextSpan=Math.max(20, Math.min(total, Math.round(span*(e.deltaY>0?1.25:0.8))));
    const ratio=(focus-f)/Math.max(1,span); let nf=Math.round(focus-nextSpan*ratio);
    nf=Math.max(0,Math.min(total-nextSpan,nf)); state.btView=[nf,nf+nextSpan]; drawBacktest();
  },{passive:false});
}

async function loadExplain() {
  const data = await api(`/api/explain?symbol=${state.symbol}`); state.explain = data; const max = Math.max(...(data.feature_importance || []).map((x) => Number(x.share)), .001);
  if ($("#importance-list")) $("#importance-list").innerHTML = (data.feature_importance || []).map((item) => `<div class="importance-row"><span title="${data.feature_schema?.[item.feature] || ""}">${item.feature}</span><div class="importance-bar"><div class="importance-fill" style="width:${(Number(item.share) / max * 100).toFixed(1)}%"></div></div><b>${fmtPct(Number(item.share) * 100, 0)}</b></div>`).join("") || "<p class='panel-copy'>Chưa có dữ liệu mức độ quan trọng của biến.</p>";
  setText("#importance-note", `${data.importance_method || "Mức độ quan trọng của biến"}. Di chuột lên tên biến để xem định nghĩa.`); if ($("#method-params")) $("#method-params").textContent = JSON.stringify({ garch: data.garch, har_rv: data.har, xgboost_engine: data.xgboost_engine, xgboost_params: data.xgboost_params }, null, 2);
}

/* Data status and background jobs */
function disableJobButtons(disabled) { ["#btn-prepare-browser", "#btn-prepare-data", "#btn-update", "#btn-retrain", "#btn-prepare-symbol"].forEach((id) => { if ($(id)) $(id).disabled = disabled; }); }
async function loadStatus(withQuality = false) {
  const status = await api(`/api/status${withQuality ? "?include_quality=true" : ""}`);
  state.wsBase = status.config?.binance_ws_base || state.wsBase;
  const cfgSymbols = status.config?.symbols;
  if (Array.isArray(cfgSymbols) && cfgSymbols.length && JSON.stringify(cfgSymbols) !== JSON.stringify(state.symbols)) {
    state.symbols = cfgSymbols;
    if (!state.symbols.includes(state.symbol)) state.symbol = state.symbols[0];
    renderSymbolSwitcher(state.symbols, $("#global-search")?.value?.trim() || "");
  }
  setText("#last-sync", localTime(status.server_time_utc || new Date().toISOString()));
  if ($("#dataset-table tbody")) $("#dataset-table tbody").innerHTML = (status.datasets || []).map((row) => `<tr><td>${row.symbol}</td><td>${row.interval}</td><td>${Number(row.rows || 0).toLocaleString()}</td><td>${localTime(row.last_update_utc)}</td><td>${statusLabel(row.status)}</td></tr>`).join("") || `<tr><td colspan="5">Chưa có bộ dữ liệu.</td></tr>`;
  if ($("#jobs-table tbody")) $("#jobs-table tbody").innerHTML = (status.recent_jobs || []).map((row) => `<tr><td>${jobLabel(row.job_type)}</td><td>${row.symbol || "—"}</td><td>${localTime(row.finished_at_utc)}</td><td>${statusLabel(row.status)}</td></tr>`).join("") || `<tr><td colspan="4">Chưa có tác vụ gần đây.</td></tr>`;
  const jobs = status.background_jobs || {}; const running = Object.values(jobs).some((job) => job.running); disableJobButtons(running);
  const info = Object.entries(jobs).filter(([, job]) => job.last).map(([name, job]) => `${jobLabel(name)}: ${job.running ? "đang chạy…" : statusLabel(job.last.status)}`).join(" · ");
  setText("#job-status", info ? `Tác vụ nền — ${info}` : "");
  if (status.data_quality && $("#quality-table tbody")) $("#quality-table tbody").innerHTML = status.data_quality.map((row) => `<tr><td>${row.symbol} ${row.interval}</td><td>${row.file_state}</td><td>${Number(row.rows || 0).toLocaleString()}</td><td>${row.gap_count ?? "—"}</td><td>${row.duplicates ?? "—"}</td><td>${row.ohlc_violations ?? "—"}</td><td>${row.start_utc ? `${localTime(row.start_utc)} → ${localTime(row.end_utc)}` : row.note || "—"}</td></tr>`).join("");
  if (status.models && $("#model-files-note")) $("#model-files-note").textContent = Object.entries(status.models).map(([symbol, model]) => `${symbol}: ${statusLabel(model.status)}${model.guidance ? ` · ${model.guidance}` : ""}`).join(" | ");
  return status;
}
async function startJob(kind, symbol = null) {
  const endpoint = kind === "prepare" ? symbol ? `/api/admin/prepare?symbol=${encodeURIComponent(symbol)}` : "/api/admin/prepare" : `/api/admin/${kind}?symbol=${encodeURIComponent(symbol || state.symbol)}`;
  try { const result = await api(endpoint, { method: "POST" }); toast(result.message || `Đã bắt đầu: ${jobLabel(kind)}.`); setView("data"); watchJob(kind); } catch (error) { toast(error.message, true); }
}
function watchJob(kind) { clearInterval(state.jobPoll); const started = Date.now(); disableJobButtons(true); state.jobPoll = setInterval(async () => { try { const status = await loadStatus(false), job = status.background_jobs?.[kind]; if (!job) return; if (job.running) { setText("#job-status", `${jobLabel(kind)} đang chạy… ${Math.round((Date.now() - started) / 1000)} giây`); return; } clearInterval(state.jobPoll); state.jobPoll = null; disableJobButtons(false); if (job.last?.status === "success") { toast(`${jobLabel(kind)} đã hoàn tất.`); state.loadedTabs.clear(); state.performance = state.backtest = state.explain = null; await loadForecast(); } else toast(`${jobLabel(kind)} thất bại. Các file kết quả hiện có được giữ nguyên.`, true); } catch { clearInterval(state.jobPoll); state.jobPoll = null; disableJobButtons(false); } }, 3000); }

/* Events + lazy loading */
async function lazyLoad(view) {
  if (state.loadedTabs.has(view)) { if (view === "models") drawPerformance(); if (view === "backtest") drawBacktest(); return; }
  try { if (view === "models") await loadPerformance(); else if (view === "backtest") await loadBacktest(); else if (view === "explain") await loadExplain(); else if (view === "data") await loadStatus(true); else return; state.loadedTabs.add(view); } catch (error) { toast(`Không tải được ${viewLabel(view)}: ${error.message}`, true); }
}
async function loadAll() {
  await loadChart(); connectWS(); await loadForecast();
  try { await loadStatus(false); } catch (error) { toast(`Không lấy được trạng thái hệ thống: ${error.message}`, true); renderSymbolSwitcher(state.symbols); }
  const active = document.querySelector(".nav-item.active")?.dataset.view || "dashboard";
  lazyLoad(active);
}

function bindEvents() {
  $$("#tf-seg button").forEach((button) => button.addEventListener("click", async () => { state.tf = button.dataset.tf; syncControls(); savePrefs(); await loadChart(); connectWS(); }));
  $$("#method-seg button").forEach((button) => button.addEventListener("click", () => { state.method = button.dataset.method; syncControls(); savePrefs(); if (state.forecast) setRiskMetrics(state.forecast); setText("#risk-explain-text", riskExplainText(state.forecast)); }));
  $("#position-input")?.addEventListener("input", (event) => { const value = Number(event.target.value); if (value > 0) { state.position = value; savePrefs(); clearTimeout(state._positionTimer); state._positionTimer = setTimeout(loadForecast, 450); } });
  $$("#leverage-seg button").forEach((button) => button.addEventListener("click", () => {
    state.leverage = Number(button.dataset.lev) || 1;
    syncControls(); savePrefs();
    if (state.forecast) setRiskMetrics(state.forecast);
    toast(`Đã chọn đòn bẩy ${state.leverage}× — VaR/ES đã được co giãn tuyến tính.`);
  }));
  /* help-chip nho o goc KPI */
  $$(".help-chip").forEach((chip) => chip.addEventListener("click", (event) => {
    event.stopPropagation();
    const messages = {
      "help-price": "Giá thị trường thời gian thực từ Binance (miniTicker/WebSocket), cập nhật mỗi khi có tick mới. Chỉ số 24h so sánh giá hiện tại với giá mở 24 giờ trước; không dùng cho dự báo rủi ro.",
      "help-fvol": "Biến động dự báo 1 ngày, được năm hóa bằng √365. Đo quy mô dao động kỳ vọng của giá, KHÔNG dự báo giá tăng hay giảm. Dùng để co giãn VaR/ES.",
      "help-var": "VaR 95% = ngưỡng tổn thất (USD) trên vị thế tham chiếu mà mô hình ước tính có ~5% xác suất vượt qua trong 1 ngày. VaR không phải mức lỗ tối đa; ngày kích hoạt có thể vượt xa số này.",
      "help-regime": "Trạng thái biến động (Thấp/Bình thường/Cao/Stress) là phân vị của biến động dự báo so với toàn bộ thời gian huấn luyện. Phân vị cao ⇒ thị trường đang trong vùng stress ⇒ VaR/ES được co giãn lên cao hơn.",
      "help-models": "Hình 2 — Biến động thực tế (đỏ) vs 4 mô hình dự báo. MAE/RMSE đo sai số, QLIKE (Patton 2011) là tiêu chí chọn mô hình vì phạt mạnh khi dự báo thấp hơn thực tế. Diebold-Mariano kiểm tra chênh lệch có ý nghĩa thống kê (p<0.05). Kéo chuột để di chuyển, lăn chuột để zoom như chart chính.",
      "help-backtest": "Hình 3 — Loss (xám) vs VaR 95% (xanh) / 99% (vàng), chấm đỏ là ngày vi phạm. Kupiec kiểm tra tỷ lệ vi phạm đúng kỳ vọng (5%/1%), Christoffersen kiểm tra vi phạm có cụm không. Basel: <4 vi phạm/năm (250 ngày, 99%) là xanh.",
      "help-var95": "VaR 95% = ngưỡng lỗ sao cho chỉ 5% ngày vượt qua. Ví dụ $384 nghĩa là với vị thế $5k, 95% ngày lỗ < $384, 5% ngày lỗ nặng hơn. Không phải lỗ tối đa.",
      "help-es95": "ES 95% = lỗ trung bình trong 5% ngày tệ nhất. Nếu VaR95=$384 thì ES95=$576 nghĩa là khi đã vượt VaR, lỗ trung bình sẽ ~$576.",
      "help-var99": "VaR 99% = ngưỡng khắt khe hơn (chỉ 1% ngày vượt). $679 nghĩa là chỉ 1% ngày lỗ >$679. Dùng cho stress test.",
      "help-es99": "ES 99% = lỗ trung bình trong 1% ngày tệ nhất. $948 là mức lỗ kỳ vọng nếu rơi vào đuôi cực đoan 1%.",
    };
    tipPop(messages[chip.id] || "Không có giải thích.", chip);
  }));
  $("#refresh-all")?.addEventListener("click", () => loadAll()); $("#btn-retry-live")?.addEventListener("click", () => { loadChart(); connectWS(); });
  $("#btn-prepare-browser")?.addEventListener("click", () => startJob("prepare"));
  $("#btn-prepare-data")?.addEventListener("click", () => startJob("prepare"));
  $("#btn-update")?.addEventListener("click", () => startJob("update"));
  $("#btn-retrain")?.addEventListener("click", () => { if (confirm("Bạn có chắc muốn huấn luyện lại toàn bộ mô hình cho tài sản đang chọn không?")) startJob("retrain"); });
  $("#btn-refresh-status")?.addEventListener("click", () => loadStatus(true));
  $("#btn-pdf-models")?.addEventListener("click", () => window.open(`/api/report?symbol=${state.symbol}`, "_blank"));
}

loadPrefs(); renderSymbolSwitcher(state.symbols); bindNavigation(); bindChartEvents(); bindEvents(); loadAll().catch((error) => toast(`Initialization error: ${error.message}`, true));
