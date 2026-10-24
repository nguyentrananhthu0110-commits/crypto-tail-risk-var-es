"use strict";

/* CRI frontend redesign
 * Backend contract intentionally preserved:
 * /api/ticker, /api/ohlcv, /api/forecast, /api/performance,
 * /api/backtest, /api/explain, /api/status and /api/admin/*.
 */
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const MODEL_NAMES = { historical_22d: "Historical 22d", garch_1_1: "GARCH(1,1)", har_rv: "HAR-RV", xgboost: "XGBoost" };
const MODEL_COLORS = { historical_22d: "#8290a3", garch_1_1: "#f2b64b", har_rv: "#31c7ff", xgboost: "#9a82ff" };
const TF_TO_BINANCE = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d" };
const PREF_KEY = "cri_frontend_prefs_v2";
const THEME_KEY = "cri_theme";
const state = {
  symbol: "BTCUSDT", tf: "1h", method: "forecast_based", position: 10000,
  candles: [], view: null, forecast: null, performance: null, backtest: null, explain: null,
  loadedTabs: new Set(), ws: null, wsBase: "wss://data-stream.binance.vision", wsTimer: null,
  pollTimer: null, lastTickAt: 0, jobPoll: null, chartHover: -1,
};

const fmtNum = (v, d = 2) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtUSD = (v, d = 0) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: d, minimumFractionDigits: d });
const fmtPct = (v, d = 1) => v == null || !Number.isFinite(Number(v)) ? "—" : `${fmtNum(v, d)}%`;
const localTime = (iso) => { try { return iso ? new Date(iso).toLocaleString("vi-VN", { hour12: false }) : "—"; } catch { return iso || "—"; } };
const localTs = (ms) => { try { return new Date(ms).toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return "—"; } };
const symbolLabel = () => state.symbol.replace("USDT", "/USDT");
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
function setConnection(mode, label) {
  const node = $("#conn-badge"); if (!node) return;
  node.className = `status-pill ${mode}`; node.innerHTML = `<span class="status-dot"></span>${label}`;
}
function savePrefs() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify({ symbol: state.symbol, tf: state.tf, method: state.method, position: state.position, view: document.querySelector(".nav-item.active")?.dataset.view || "dashboard" })); } catch { /* storage disabled */ }
}
function loadPrefs() {
  let prefs = {}; try { prefs = JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); } catch { /* invalid storage */ }
  if (["BTCUSDT", "ETHUSDT"].includes(prefs.symbol)) state.symbol = prefs.symbol;
  if (Object.keys(TF_TO_BINANCE).includes(prefs.tf)) state.tf = prefs.tf;
  if (["forecast_based", "historical_simulation", "parametric_student_t"].includes(prefs.method)) state.method = prefs.method;
  if (Number(prefs.position) > 0) state.position = Number(prefs.position);
  setTheme(localStorage.getItem(THEME_KEY) || "dark");
  syncControls();
  if (["risk", "models", "backtest", "explain", "data"].includes(prefs.view)) setView(prefs.view);
}

/* Theme + navigation */
function setTheme(theme) {
  const actual = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = actual;
  try { localStorage.setItem(THEME_KEY, actual); } catch {}
  const button = $("#theme-toggle"); if (button) { button.textContent = actual === "dark" ? "☼" : "☾"; button.title = actual === "dark" ? "Switch to light mode" : "Switch to dark mode"; }
  if (state.candles.length) drawMainChart();
  if (state.performance) drawPerformance();
  if (state.backtest) drawBacktest();
}
function setView(view) {
  const titles = {
    dashboard: ["Dashboard", "Market overview", "Real-time volatility, model forecasts and tail-risk signals for digital assets."],
    risk: ["Risk Monitor", "Risk outlook", "Compare loss assumptions and monitor the current volatility regime."],
    models: ["Model Analytics", "Forecast evaluation", "Out-of-sample comparison of volatility models."],
    backtest: ["Backtesting", "VaR validation", "Check breach rates and coverage diagnostics over time."],
    explain: ["Explainability", "Model transparency", "Understand features, assumptions and known limitations."],
    data: ["Data & System", "Datasets and system health", "Manage source data, model artifacts and background jobs."],
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
  $("#global-search")?.addEventListener("input", (event) => {
    const query = event.target.value.trim().toLowerCase();
    $$(".nav-item[data-view]").forEach((item) => { item.hidden = Boolean(query) && !item.textContent.toLowerCase().includes(query); });
  });
}

/* Main market chart */
function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  return { text: css.getPropertyValue("--muted-2").trim() || "#647285", grid: css.getPropertyValue("--line-soft").trim() || "rgba(147,163,183,.14)", up: css.getPropertyValue("--positive").trim() || "#00c805", down: css.getPropertyValue("--negative").trim() || "#ff4a4a", bg: css.getPropertyValue("--bg").trim() || "#0c1016" };
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
  if (!data.length) { ctx.fillStyle = theme.text; ctx.textAlign = "center"; ctx.font = "12px sans-serif"; ctx.fillText("No market data available", width / 2, height / 2); return; }
  const from = state.view ? Math.max(0, state.view[0]) : Math.max(0, data.length - 160), to = state.view ? Math.min(data.length, state.view[1]) : data.length;
  const visible = data.slice(from, to), left = 10, right = 76, top = 16, bottom = 30, volume = 50, plotW = width - left - right, plotH = height - top - bottom - volume;
  let high = Math.max(...visible.map((c) => c.h)), low = Math.min(...visible.map((c) => c.l)), maxVolume = Math.max(...visible.map((c) => c.v), 1); const pad = (high - low || high * .01) * .08; high += pad; low -= pad;
  const step = plotW / Math.max(visible.length, 1), candleW = Math.max(1.5, Math.min(12, step * .64)); const x = (i) => left + (i + .5) * step; const y = (price) => top + (high - price) / (high - low) * plotH;
  ctx.font = "10px Consolas, monospace"; ctx.lineWidth = 1;
  for (let g = 0; g <= 5; g++) { const price = low + (high - low) * g / 5, yy = y(price); ctx.strokeStyle = theme.grid; ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke(); ctx.fillStyle = theme.text; ctx.textAlign = "left"; ctx.fillText(fmtUSD(price, price > 100 ? 0 : 2), width - right + 8, yy + 3); }
  visible.forEach((c, i) => { const xx = x(i), up = c.c >= c.o, color = up ? theme.up : theme.down; ctx.strokeStyle = color; ctx.beginPath(); ctx.moveTo(xx, y(c.h)); ctx.lineTo(xx, y(c.l)); ctx.stroke(); ctx.fillStyle = color; const y1 = y(Math.max(c.o, c.c)), y2 = y(Math.min(c.o, c.c)); ctx.fillRect(xx - candleW / 2, y1, candleW, Math.max(1, y2 - y1)); const vh = (c.v / maxVolume) * (volume - 10); ctx.globalAlpha = .35; ctx.fillRect(xx - candleW / 2, top + plotH + volume - vh, candleW, vh); ctx.globalAlpha = 1; });
  ctx.fillStyle = theme.text; ctx.textAlign = "center"; const every = Math.max(1, Math.floor(visible.length / 6)); for (let i = 0; i < visible.length; i += every) ctx.fillText(localTs(visible[i].t), x(i), height - 7);
  const last = data[data.length - 1]; ctx.setLineDash([4, 4]); ctx.strokeStyle = theme.text; ctx.globalAlpha = .55; ctx.beginPath(); ctx.moveTo(left, y(last.c)); ctx.lineTo(width - right, y(last.c)); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
  setText("#chart-meta", `${symbolLabel()} · ${state.tf} · ${visible.length}/${data.length} candles · last ${last.closed ? "closed" : "forming"}`);
}
function bindChartEvents() {
  $("#chart-reset")?.addEventListener("click", () => { state.view = null; state.chartHover = -1; drawMainChart(); });
  window.addEventListener("resize", () => { drawMainChart(); if (state.performance) drawPerformance(); if (state.backtest) drawBacktest(); });
}

/* REST + WebSocket */
function updateTicker(price, change, stale) {
  setText("#kpi-price", price == null ? "—" : fmtUSD(price, Number(price) >= 1000 ? 0 : 2));
  const node = $("#kpi-change"); if (node) { node.textContent = `24h: ${fmtPct(change, 2)}`; node.className = `metric-delta ${Number(change) >= 0 ? "up" : "down"}`; }
  setText("#price-src", stale ? "Cached market data" : "Binance Public Data");
  setConnection(stale ? "offline" : "live", stale ? "Cached" : "Live");
}
async function loadChart() {
  $("#chart-loading")?.classList.remove("hidden");
  try {
    const candles = await api(`/api/ohlcv?symbol=${state.symbol}&interval=${state.tf}&limit=500`);
    state.candles = (candles.candles || []).map(normalizeCandle).filter((c) => Number.isFinite(c.c) && Number.isFinite(c.t)); state.view = null;
    updateTicker(candles.price, candles.change_pct_24h, candles.stale);
    const ticker = await api(`/api/ticker?symbol=${state.symbol}`); updateTicker(ticker.price, ticker.change_pct_24h, ticker.stale);
    if (candles.stale) showStale("Live source unavailable — chart is using the latest saved data."); else hideStale();
  } catch (error) { toast(`Could not load chart: ${error.message}`, true); setConnection("offline", "Offline"); state.candles = []; }
  $("#chart-loading")?.classList.add("hidden"); drawMainChart();
}
function wsUrl() { return `${state.wsBase}/ws/${state.symbol.toLowerCase()}@kline_${TF_TO_BINANCE[state.tf]}`; }
function connectWS() {
  clearTimeout(state.wsTimer); try { state.ws?.close(); } catch {}
  try { state.ws = new WebSocket(wsUrl()); } catch { scheduleWSReconnect(); return; }
  state.ws.onopen = () => { setConnection("live", "Live"); clearInterval(state.pollTimer); state.pollTimer = null; };
  state.ws.onmessage = (event) => { try { const message = JSON.parse(event.data), k = message.k; if (!k) return; const next = normalizeCandle({ t: k.t, o: k.o, h: k.h, l: k.l, c: k.c, v: k.v, closed: k.x }); const current = state.candles[state.candles.length - 1]; if (current && current.t === next.t) state.candles[state.candles.length - 1] = next; else state.candles.push(next); state.lastTickAt = Date.now(); updateTicker(next.c, null, false); drawMainChart(); } catch { /* malformed stream message */ } };
  state.ws.onclose = () => { setConnection("reconnecting", "Reconnecting"); scheduleWSReconnect(); startPolling(); };
  state.ws.onerror = () => { try { state.ws.close(); } catch {} };
}
function scheduleWSReconnect() { clearTimeout(state.wsTimer); state.wsTimer = setTimeout(connectWS, 3000); }
function startPolling() { if (state.pollTimer) return; state.pollTimer = setInterval(() => loadChart(), 30000); }
function showStale(message) { $("#stale-banner")?.classList.remove("hidden"); setText("#stale-text", message); }
function hideStale() { $("#stale-banner")?.classList.add("hidden"); }

/* Forecast and risk */
function renderForecast(f) {
  state.forecast = f; $("#empty-state")?.classList.add("hidden");
  const regime = f.regime || {}, risk = f.risk?.[state.method] || f.risk?.forecast_based || {};
  setText("#kpi-regime", regime.label_vi || regime.label || "—"); setText("#kpi-regime-sub", regime.percentile_vs_train == null ? "Training percentile" : `Percentile ${fmtNum(regime.percentile_vs_train, 0)} vs training`);
  setText("#kpi-fvol", fmtPct(f.forecast_vol_annualized_pct, 1)); setText("#kpi-fvol-sub", `1-day · daily ${fmtPct(Number(f.forecast_vol_daily || 0) * 100, 2)}`);
  setRiskMetrics(f); setText("#kpi-updated", localTime(f.generated_at_utc)); setText("#last-sync", localTime(f.generated_at_utc));
  if (f.interpretation?.market_summary) { $("#summary-band")?.classList.remove("hidden"); setText("#summary-text", f.interpretation.market_summary); }
  setText("#regime-desc", regime.description || "—"); setText("#risk-regime-label", regime.label_vi || regime.label || "—");
  const pct = Number(regime.percentile_vs_train); if (Number.isFinite(pct)) $("#regime-marker").style.left = `${Math.min(98, Math.max(2, pct))}%`;
  const kv = $("#vol-kv"); if (kv) kv.innerHTML = `<dt>Forecast volatility (annualized)</dt><dd>${fmtPct(f.forecast_vol_annualized_pct, 1)}</dd><dt>Latest realized volatility</dt><dd>${fmtPct(f.current_realized_vol_annualized_pct, 1)}</dd><dt>Training percentile</dt><dd>${Number.isFinite(pct) ? fmtPct(pct, 0) : "—"}</dd><dt>Selected model</dt><dd>${MODEL_NAMES[f.selected_model] || f.selected_model || "—"}</dd>`;
  renderModelList(f.models_vol_annualized_pct, f.selected_model, "#model-vol-list"); renderModelList(f.models_vol_annualized_pct, f.selected_model, "#risk-model-list");
  setText("#regime-desc", regime.description || "—");
  setText("#risk-interpretation", f.interpretation?.risk_summary || "Risk estimate based on the selected model and method.");
  setText("#risk-method-note", riskMethodNote(f));
  const wrong = f.interpretation?.what_could_be_wrong || []; const limits = f.limitations || [];
  if ($("#wrong-list")) $("#wrong-list").innerHTML = wrong.map((item) => `<li>${item}</li>`).join("") || "<li>No additional notes.</li>";
  if ($("#limit-list")) $("#limit-list").innerHTML = limits.map((item) => `<li>${item}</li>`).join("") || "<li>See the methodology notes.</li>";
  if ($("#method-defs")) $("#method-defs").innerHTML = `<p><b>Convention:</b> ${f.risk?.convention || "Loss is positive."}</p><p><b>Model selection:</b> ${f.risk?.selection_rule || "Lowest out-of-sample QLIKE."}</p><p>Forecast volatility measures expected movement size, not price direction. VaR is a threshold; ES describes the average loss beyond that threshold.</p>`;
}
function renderModelList(models = {}, selected, selector) {
  const node = $(selector); if (!node) return;
  node.innerHTML = Object.entries(models).map(([key, value]) => `<div class="model-row"><span>${MODEL_NAMES[key] || key}${key === selected ? `<span class="best-tag">selected</span>` : ""}</span><b>${fmtPct(value, 1)}</b></div>`).join("") || `<div class="panel-copy">No model estimates available.</div>`;
}
function riskMethodNote(f) {
  const selected = MODEL_NAMES[f.selected_model] || f.selected_model || "selected model"; const r = f.risk?.[state.method];
  if (state.method === "forecast_based") return `Forecast-based VaR uses ${selected} volatility with a Student-t tail (df ${fmtNum(r?.t_df, 1)}).`;
  if (state.method === "historical_simulation") return `Historical simulation uses the most recent ${r?.n_obs || "available"} daily returns without a parametric distribution.`;
  return `Parametric Student-t is fitted to the full daily return history (df ${fmtNum(r?.params?.df, 1)}).`;
}
function setRiskMetrics(f) {
  const chosen = f.risk?.[state.method] || f.risk?.forecast_based || {};
  const update = (id, value) => setText(id, fmtUSD(value)); const updatePct = (id, value) => setText(id, `${fmtPct(value, 2)} of position`);
  update("#r-var95", chosen.var_95); update("#r-es95", chosen.es_95); update("#r-var99", chosen.var_99); update("#r-es99", chosen.es_99);
  update("#risk-var95-large", chosen.var_95); update("#risk-es95-large", chosen.es_95); update("#risk-var99-large", chosen.var_99); update("#risk-es99-large", chosen.es_99);
  updatePct("#r-es95-pct", chosen.es_95_pct); updatePct("#risk-es95-pct", chosen.es_95_pct); updatePct("#risk-var95-pct", chosen.var_95_pct); updatePct("#risk-var99-pct", chosen.var_99_pct); updatePct("#risk-es99-pct", chosen.es_99_pct);
  setText("#kpi-var", fmtUSD(f.risk?.forecast_based?.var_95)); setText("#kpi-var-sub", `${fmtPct(f.risk?.forecast_based?.var_95_pct, 2)} · 1-day`);
  const label = f.regime?.label_vi || f.regime?.label || "—"; setText("#risk-badge", label);
}
async function loadForecast() {
  try { renderForecast(await api(`/api/forecast?symbol=${state.symbol}&position_usd=${state.position}`)); }
  catch (error) { state.forecast = null; $("#empty-state")?.classList.remove("hidden"); setText("#empty-title", error.code === "MODEL_CORRUPTED" ? "Model file unavailable" : "Model chưa được khởi tạo"); setText("#empty-text", error.message || "Prepare data and train a model to enable forecasts."); }
}

/* Model analytics and backtesting */
function drawLineChart(id, series, labels = [], height = 300, zeroBase = false) {
  const size = canvasSize(id, window.innerWidth < 680 ? Math.min(height, 250) : height); if (!size) return null;
  const { ctx, width, height: h } = size, theme = chartTheme(), left = 8, right = 62, top = 12, bottom = 24, plotW = width - left - right, plotH = h - top - bottom; let values = series.flatMap((s) => s.data).filter((v) => Number.isFinite(v)); if (!values.length) return null;
  let hi = Math.max(...values), lo = Math.min(...values); if (zeroBase) lo = Math.min(0, lo); const span = hi - lo || 1; hi += span * .08; lo -= span * .04; const count = Math.max(...series.map((s) => s.data.length), 1); const x = (i) => left + plotW * (count <= 1 ? 0 : i / (count - 1)); const y = (v) => top + (hi - v) / (hi - lo) * plotH;
  ctx.font = "10px Consolas, monospace"; for (let g = 0; g <= 4; g++) { const value = lo + (hi - lo) * g / 4, yy = y(value); ctx.strokeStyle = theme.grid; ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke(); ctx.fillStyle = theme.text; ctx.textAlign = "left"; ctx.fillText(fmtNum(value, 2), width - right + 7, yy + 3); } if (labels.length) { const every = Math.max(1, Math.floor(labels.length / 6)); ctx.fillStyle = theme.text; for (let i = 0; i < labels.length; i += every) { ctx.textAlign = "center"; ctx.fillText(labels[i], x(i), h - 7); } }
  series.forEach((item) => { ctx.strokeStyle = item.color; ctx.lineWidth = item.width || 1.5; ctx.beginPath(); let started = false; item.data.forEach((value, index) => { if (!Number.isFinite(value)) return; const xx = x(index), yy = y(value); if (!started) { ctx.moveTo(xx, yy); started = true; } else ctx.lineTo(xx, yy); }); ctx.stroke(); }); return { ctx, x, y };
}
async function loadPerformance() {
  const data = await api(`/api/performance?symbol=${state.symbol}`); state.performance = data;
  const keys = Object.keys(data.forecasts_vol_daily || {}); if ($("#perf-legend")) $("#perf-legend").innerHTML = `<span><i class="sw" style="background:#eef3f8"></i>Actual</span>${keys.map((key) => `<span><i class="sw" style="background:${MODEL_COLORS[key] || "#57a6ff"}"></i>${MODEL_NAMES[key] || key}</span>`).join("")}`;
  setText("#perf-note", `${data.note || "Out-of-sample model comparison."} Selected: ${MODEL_NAMES[data.selected_model] || data.selected_model || "—"}.`);
  if ($("#metrics-table tbody")) $("#metrics-table tbody").innerHTML = Object.entries(data.metrics || {}).map(([key, metric]) => `<tr class="${key === data.selected_model ? "best" : ""}"><td>${MODEL_NAMES[key] || key}</td><td>${fmtPct(Number(metric.mae_vol) * 100, 2)}</td><td>${fmtPct(Number(metric.rmse_vol) * 100, 2)}</td><td>${fmtNum(metric.qlike, 3)}</td><td>${metric.n ?? "—"}</td><td>${key === data.selected_model ? "Selected by QLIKE" : "—"}</td></tr>`).join("") || `<tr><td colspan="6">No performance data.</td></tr>`;
  if ($("#dm-box")) $("#dm-box").innerHTML = Object.entries(data.diebold_mariano || {}).map(([key, value]) => `<p><b>${key.replace("_vs_", " vs ")}</b>: ${value.p_value == null ? "Insufficient data" : `DM ${fmtNum(value.statistic, 2)}, p-value ${fmtNum(value.p_value, 3)} (n=${value.n})`}</p>`).join("") || "<p>No DM tests available.</p>";
  drawPerformance();
}
function drawPerformance() { const p = state.performance; if (!p) return; const series = [{ data: (p.actual_vol_daily || []).map((v) => Number(v) * 100), color: "#eef3f8", width: 1.8 }]; Object.entries(p.forecasts_vol_daily || {}).forEach(([key, values]) => series.push({ data: values.map((v) => v == null ? null : Number(v) * 100), color: MODEL_COLORS[key] || "#57a6ff", width: key === p.selected_model ? 2.2 : 1.2 })); drawLineChart("#perf-chart", series, p.dates || [], 300); }
function renderBacktestSummary(node, summary, level) { if (!node || !summary) return; node.innerHTML = `<dl class="definition-list"><dt>Test days</dt><dd>${summary.n ?? "—"}</dd><dt>Breaches</dt><dd>${summary.breaches ?? "—"} (${fmtPct(Number(summary.breach_rate || 0) * 100, 1)})</dd><dt>Kupiec</dt><dd>${summary.kupiec?.p_value == null ? "Insufficient data" : `p ${fmtNum(summary.kupiec.p_value, 3)}`}</dd><dt>Christoffersen</dt><dd>${summary.christoffersen?.p_value_conditional_coverage == null ? "Insufficient data" : `p ${fmtNum(summary.christoffersen.p_value_conditional_coverage, 3)}`}</dd><dt>Expected rate</dt><dd>${fmtPct(100 - level, 0)}</dd></dl>`; }
async function loadBacktest() {
  const data = await api(`/api/backtest?symbol=${state.symbol}`); state.backtest = data; setText("#bt-method", `${data.method || "Rolling backtest"} · position ${fmtUSD(data.reference_position_usd)}`); renderBacktestSummary($("#bt95"), data.summary_95, 95); renderBacktestSummary($("#bt99"), data.summary_99, 99);
  if ($("#breach-table tbody")) $("#breach-table tbody").innerHTML = (data.series || []).filter((row) => row.breach95).map((row) => `<tr><td>${row.date}</td><td>${fmtUSD(row.loss_usd)}</td><td>${fmtUSD(row.var95_usd)}</td><td>${fmtUSD(row.var99_usd)}</td><td>${row.breach99 ? "VaR99" : "VaR95"}</td></tr>`).join("") || `<tr><td colspan="5">No breaches in the test period.</td></tr>`;
  drawBacktest();
}
function drawBacktest() { const b = state.backtest; if (!b) return; const rows = b.series || []; const chart = drawLineChart("#bt-chart", [{ data: rows.map((r) => r.loss_usd), color: "#8290a3" }, { data: rows.map((r) => r.var95_usd), color: "#31c7ff" }, { data: rows.map((r) => r.var99_usd), color: "#f2b64b" }], rows.map((r) => r.date), 280, true); if (!chart) return; const size = canvasSize("#bt-chart", window.innerWidth < 680 ? 250 : 280); if (!size) return; rows.forEach((row, index) => { if (row.breach95) { size.ctx.fillStyle = "#ff4a4a"; size.ctx.beginPath(); size.ctx.arc(chart.x(index), chart.y(row.loss_usd), 3, 0, Math.PI * 2); size.ctx.fill(); } }); }

async function loadExplain() {
  const data = await api(`/api/explain?symbol=${state.symbol}`); state.explain = data; const max = Math.max(...(data.feature_importance || []).map((x) => Number(x.share)), .001);
  if ($("#importance-list")) $("#importance-list").innerHTML = (data.feature_importance || []).map((item) => `<div class="importance-row"><span title="${data.feature_schema?.[item.feature] || ""}">${item.feature}</span><div class="importance-bar"><div class="importance-fill" style="width:${(Number(item.share) / max * 100).toFixed(1)}%"></div></div><b>${fmtPct(Number(item.share) * 100, 0)}</b></div>`).join("") || "<p class='panel-copy'>No feature importance available.</p>";
  setText("#importance-note", `${data.importance_method || "Feature importance"}. Hover a feature name for its definition.`); if ($("#method-params")) $("#method-params").textContent = JSON.stringify({ garch: data.garch, har_rv: data.har, xgboost_engine: data.xgboost_engine, xgboost_params: data.xgboost_params }, null, 2);
}

/* Data status and background jobs */
function disableJobButtons(disabled) { ["#btn-prepare-browser", "#btn-prepare-data", "#btn-update", "#btn-retrain"].forEach((id) => { if ($(id)) $(id).disabled = disabled; }); }
async function loadStatus(withQuality = false) {
  const status = await api(`/api/status${withQuality ? "?include_quality=true" : ""}`); state.wsBase = status.config?.binance_ws_base || state.wsBase; setText("#last-sync", localTime(status.server_time_utc || new Date().toISOString()));
  if ($("#dataset-table tbody")) $("#dataset-table tbody").innerHTML = (status.datasets || []).map((row) => `<tr><td>${row.symbol}</td><td>${row.interval}</td><td>${Number(row.rows || 0).toLocaleString()}</td><td>${localTime(row.last_update_utc)}</td><td>${row.status}</td></tr>`).join("") || `<tr><td colspan="5">No datasets available.</td></tr>`;
  if ($("#jobs-table tbody")) $("#jobs-table tbody").innerHTML = (status.recent_jobs || []).map((row) => `<tr><td>${row.job_type}</td><td>${row.symbol || "—"}</td><td>${localTime(row.finished_at_utc)}</td><td>${row.status}</td></tr>`).join("") || `<tr><td colspan="4">No recent jobs.</td></tr>`;
  const jobs = status.background_jobs || {}; const running = Object.values(jobs).some((job) => job.running); disableJobButtons(running); const info = Object.entries(jobs).filter(([, job]) => job.last).map(([name, job]) => `${name}: ${job.running ? "running…" : job.last.status}`).join(" · "); setText("#job-status", info ? `Background jobs — ${info}` : "");
  if (status.data_quality && $("#quality-table tbody")) $("#quality-table tbody").innerHTML = status.data_quality.map((row) => `<tr><td>${row.symbol} ${row.interval}</td><td>${row.file_state}</td><td>${Number(row.rows || 0).toLocaleString()}</td><td>${row.gap_count ?? "—"}</td><td>${row.duplicates ?? "—"}</td><td>${row.ohlc_violations ?? "—"}</td><td>${row.start_utc ? `${localTime(row.start_utc)} → ${localTime(row.end_utc)}` : row.note || "—"}</td></tr>`).join("");
  if (status.models && $("#model-files-note")) $("#model-files-note").textContent = Object.entries(status.models).map(([symbol, model]) => `${symbol}: ${model.status}${model.guidance ? ` · ${model.guidance}` : ""}`).join(" | "); return status;
}
async function startJob(kind) {
  const endpoint = kind === "prepare" ? "/api/admin/prepare" : `/api/admin/${kind}?symbol=${state.symbol}`;
  try { const result = await api(endpoint, { method: "POST" }); toast(result.message || `Started ${kind}.`); setView("data"); watchJob(kind); } catch (error) { toast(error.message, true); }
}
function watchJob(kind) { clearInterval(state.jobPoll); const started = Date.now(); disableJobButtons(true); state.jobPoll = setInterval(async () => { try { const status = await loadStatus(false), job = status.background_jobs?.[kind]; if (!job) return; if (job.running) { setText("#job-status", `Running ${kind}… ${Math.round((Date.now() - started) / 1000)}s`); return; } clearInterval(state.jobPoll); state.jobPoll = null; disableJobButtons(false); if (job.last?.status === "success") { toast(`${kind} completed successfully.`); state.loadedTabs.clear(); state.performance = state.backtest = state.explain = null; await loadForecast(); } else toast(`${kind} failed. Existing artifacts were preserved.`, true); } catch { clearInterval(state.jobPoll); state.jobPoll = null; disableJobButtons(false); } }, 3000); }

/* Events + lazy loading */
function syncControls() { $$("#symbol-switch button").forEach((button) => button.classList.toggle("active", button.dataset.symbol === state.symbol)); $$("#tf-seg button").forEach((button) => button.classList.toggle("active", button.dataset.tf === state.tf)); $$("#method-seg button").forEach((button) => button.classList.toggle("active", button.dataset.method === state.method)); if ($("#position-input")) $("#position-input").value = state.position; setText("#chart-title", symbolLabel()); }
function switchSymbol(symbol) { if (state.symbol === symbol) return; state.symbol = symbol; state.loadedTabs.clear(); state.performance = state.backtest = state.explain = null; syncControls(); savePrefs(); loadAll(); }
async function lazyLoad(view) {
  if (state.loadedTabs.has(view)) { if (view === "models") drawPerformance(); if (view === "backtest") drawBacktest(); return; }
  try { if (view === "models") await loadPerformance(); else if (view === "backtest") await loadBacktest(); else if (view === "explain") await loadExplain(); else if (view === "data") await loadStatus(true); else return; state.loadedTabs.add(view); } catch (error) { toast(`Could not load ${view}: ${error.message}`, true); }
}
async function loadAll() { await loadChart(); connectWS(); await loadForecast(); try { await loadStatus(false); } catch (error) { toast(`Status unavailable: ${error.message}`, true); } const active = document.querySelector(".nav-item.active")?.dataset.view || "dashboard"; lazyLoad(active); }

function bindEvents() {
  $$("#symbol-switch button").forEach((button) => button.addEventListener("click", () => switchSymbol(button.dataset.symbol)));
  $$("#tf-seg button").forEach((button) => button.addEventListener("click", async () => { state.tf = button.dataset.tf; syncControls(); savePrefs(); await loadChart(); connectWS(); }));
  $$("#method-seg button").forEach((button) => button.addEventListener("click", () => { state.method = button.dataset.method; syncControls(); savePrefs(); if (state.forecast) setRiskMetrics(state.forecast); }));
  $("#position-input")?.addEventListener("input", (event) => { const value = Number(event.target.value); if (value > 0) { state.position = value; savePrefs(); clearTimeout(state._positionTimer); state._positionTimer = setTimeout(loadForecast, 450); } });
  $("#refresh-all")?.addEventListener("click", () => loadAll()); $("#btn-retry-live")?.addEventListener("click", () => { loadChart(); connectWS(); }); $("#btn-prepare-browser")?.addEventListener("click", () => startJob("prepare")); $("#btn-prepare-data")?.addEventListener("click", () => startJob("prepare")); $("#btn-update")?.addEventListener("click", () => startJob("update")); $("#btn-retrain")?.addEventListener("click", () => { if (confirm("Retrain all models for the selected asset?")) startJob("retrain"); }); $("#btn-refresh-status")?.addEventListener("click", () => loadStatus(true));
}

loadPrefs(); bindNavigation(); bindChartEvents(); bindEvents(); loadAll().catch((error) => toast(`Initialization error: ${error.message}`, true));
