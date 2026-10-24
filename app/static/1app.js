"use strict";
/* Crypto Risk Intelligence — frontend
 * - Giá/nến trực tiếp: Binance WebSocket công khai (kline + miniTicker), reconnect backoff+jitter.
 * - Fallback: polling REST qua backend khi WS gián đoạn; dữ liệu cũ luôn được gắn nhãn stale.
 * - Chart: canvas tự vẽ, cập nhật tăng dần nến đang hình thành, giữ zoom/pan khi có tick mới.
 */
const $ = (s) => document.querySelector(s);
const fmtUSD = (v, d = 0) => v == null || !isFinite(v) ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: d, minimumFractionDigits: d });
const fmtNum = (v, d = 2) => v == null || !isFinite(v) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const fmtPct = (v, d = 1) => v == null || !isFinite(v) ? "—" : fmtNum(v, d) + "%";
const fmtPrice = (v) => v == null ? "—" : fmtUSD(v, v >= 1000 ? 0 : 2);
const localTime = (iso) => { try { return new Date(iso).toLocaleString("vi-VN", { hour12: false }); } catch { return iso || "—"; } };
const localTs = (ms) => new Date(ms).toLocaleString("vi-VN", { hour12: false, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

const MODEL_NAMES = { historical_22d: "Historical 22 ngày (benchmark)", garch_1_1: "GARCH(1,1)", har_rv: "HAR-RV", xgboost: "XGBoost" };
const MODEL_COLORS = { historical_22d: "#8d99a8", garch_1_1: "#c9a227", har_rv: "#7fb069", xgboost: "#5b8def" };
const TIPS = {
  vol: "Trạng thái biến động được phân loại bằng phân vị realized volatility trên tập huấn luyện: Thấp < q25 · Bình thường q25–q75 · Cao q75–q90 · Stress > q90. Đây là so sánh với lịch sử, không phải dự đoán hướng giá.",
  fvol: "Forecasted volatility: độ lệch chuẩn lợi suất dự báo cho ngày tới, hiển thị dạng năm-hoá (×√365 vì crypto giao dịch mỗi ngày). Nó mô tả quy mô dao động, không nói giá tăng hay giảm.",
  var: "Value at Risk: ngưỡng lỗ tại mức tin cậy cho trước trong 1 ngày, trên vị thế tham chiếu. Ví dụ VaR 95% = X nghĩa là theo mô hình, xác suất đuôi lỗ vượt X khoảng 5%/ngày. VaR không phải mức lỗ tối đa.",
  es: "Expected Shortfall: mức lỗ trung bình có điều kiện trong nhóm kết quả tệ nhất vượt VaR (ví dụ 5% tệ nhất với ES 95%). ES cho biết 'khi xấu thì xấu cỡ nào' theo mô hình.",
  rv: "Realized volatility: biến động ĐÃ quan sát được trong quá khứ — ở ứng dụng này bằng căn bậc hai của tổng bình phương lợi suất 1 giờ trong ngày UTC. Khác với volatility dự báo, RV là số đo ngược về quá khứ.",
  oos: "Out-of-sample: phần dữ liệu theo thứ tự thời gian phía sau tập huấn luyện, không được dùng để ước lượng tham số. Hiệu quả ở đây mới phản ánh khả năng dự báo thật, tránh tự chấm điểm trên dữ liệu đã học.",
  qlike: "QLIKE (Patton 2011): hàm tổn thất để chấm dự báo phương sai so với realized variance. Thấp hơn là tốt hơn. QLIKE vững với nhiễu của proxy RV hơn MSE thông thường trong nhiều điều kiện.",
  breach: "VaR breach (vượt ngưỡng): ngày mà mức lỗ thực tế lớn hơn VaR đã dự báo cho đúng ngày đó. VaR 95% kỳ vọng khoảng 5% số ngày breach trong dài hạn nếu mô hình hiệu chuẩn tốt — breach đơn lẻ không tự nó chứng minh mô hình sai.",
};

const state = {
  symbol: "BTCUSDT", tf: "1h", method: "forecast_based", position: 10000,
  candles: [], view: null, forecast: null, performance: null, backtest: null, explain: null,
  ws: null, wsRetries: 0, wsTimer: null, pollTimer: null, lastTickAt: 0, ticker: null,
  wsBase: "wss://data-stream.binance.vision", loadedTabs: new Set(),
};

async function api(path, opts) {
  const r = await fetch(path, opts);
  let data = null; try { data = await r.json(); } catch {}
  if (!r.ok) throw new Error((data && data.detail && data.detail.message) || `HTTP ${r.status}`);
  return data;
}
function toast(msg, isError) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (isError ? " error" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 6000);
}
function setConn(mode, text) {
  const b = $("#conn-badge"); b.className = "badge " + mode;
  b.innerHTML = `<span class="dot"></span>${text}`;
}

/* ---------------- Candlestick chart ---------------- */
const chart = { drag: null, hover: -1 };
function chartDims() {
  const c = $("#main-chart"); const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = 460;
  if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); c.style.height = h + "px"; }
  return { ctx: c.getContext("2d"), w, h, dpr };
}
function visibleRange() {
  const n = state.candles.length;
  if (!n) return [0, 0];
  if (!state.view) return [Math.max(0, n - 220), n];
  const [a, b] = state.view; return [Math.max(0, a), Math.min(n, b)];
}
function drawChart() {
  const { ctx, w, h, dpr } = chartDims(); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const data = state.candles; const [i0, i1] = visibleRange();
  if (!data.length || i1 <= i0) {
    ctx.fillStyle = "#647183"; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Chưa có dữ liệu nến. Kiểm tra kết nối mạng rồi thử lại.", w / 2, h / 2); return;
  }
  const padR = 74, padL = 8, padT = 12, volH = 74, padB = 24, priceH = h - padT - volH - padB;
  const plotW = w - padL - padR, n = i1 - i0, step = plotW / n, cw = Math.max(1, Math.min(14, step * 0.68));
  let hi = -Infinity, lo = Infinity, vmax = 0;
  for (let i = i0; i < i1; i++) { hi = Math.max(hi, data[i].h); lo = Math.min(lo, data[i].l); vmax = Math.max(vmax, data[i].v); }
  const rangePad = (hi - lo) * 0.06 || hi * 0.01; hi += rangePad; lo -= rangePad;
  const X = (i) => padL + (i - i0 + 0.5) * step;
  const Y = (p) => padT + (hi - p) / (hi - lo) * priceH;
  ctx.font = "11px Consolas, monospace";
  // grid + trục giá
  for (let g = 0; g <= 5; g++) {
    const p = lo + (hi - lo) * g / 5, y = Y(p);
    ctx.strokeStyle = "#182030"; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = "#647183"; ctx.textAlign = "left"; ctx.fillText(fmtPrice(p), w - padR + 7, y + 4);
  }
  // trục thời gian (tối đa ~7 nhãn)
  ctx.textAlign = "center";
  const labelEvery = Math.max(1, Math.floor(n / 7));
  for (let i = i0; i < i1; i += labelEvery) ctx.fillText(localTs(data[i].t), X(i), h - 7);
  // volume
  const volTop = padT + priceH + 8;
  for (let i = i0; i < i1; i++) {
    const c = data[i], vh = vmax ? (c.v / vmax) * (volH - 12) : 0;
    ctx.fillStyle = c.c >= c.o ? "rgba(38,162,105,.55)" : "rgba(214,69,80,.55)";
    ctx.fillRect(X(i) - cw / 2, volTop + (volH - 12 - vh), cw, Math.max(1, vh));
  }
  ctx.fillStyle = "#647183"; ctx.textAlign = "left"; ctx.fillText("Volume", padL + 2, volTop + 10);
  // candles
  for (let i = i0; i < i1; i++) {
    const c = data[i], up = c.c >= c.o, col = up ? "#26a269" : "#d64550", x = X(i);
    ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(x, Y(c.h)); ctx.lineTo(x, Y(c.l)); ctx.stroke();
    ctx.fillStyle = col;
    const y1 = Y(Math.max(c.o, c.c)), y2 = Y(Math.min(c.o, c.c));
    ctx.fillRect(x - cw / 2, y1, cw, Math.max(1, y2 - y1));
    if (!c.closed) { ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.strokeRect(x - cw / 2 - 1.5, y1 - 1.5, cw + 3, Math.max(1, y2 - y1) + 3); }
  }
  // đường giá đóng gần nhất
  const last = data[data.length - 1];
  if (i1 === data.length) {
    ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(141,153,168,.5)";
    ctx.beginPath(); ctx.moveTo(padL, Y(last.c)); ctx.lineTo(w - padR, Y(last.c)); ctx.stroke(); ctx.setLineDash([]);
  }
  // crosshair
  if (chart.hover >= i0 && chart.hover < i1) {
    const x = X(chart.hover); ctx.strokeStyle = "rgba(141,153,168,.4)";
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, h - padB); ctx.stroke();
  }
  $("#chart-meta").textContent = `${state.symbol.replace("USDT", "/USDT")} · ${state.tf} · hiển thị ${n}/${data.length} nến · nến cuối ${last.closed ? "đã đóng" : "đang hình thành"}`;
}
function bindChartEvents() {
  const c = $("#main-chart"), tip = $("#chart-tooltip");
  const idxFromEvent = (e) => {
    const r = c.getBoundingClientRect(); const [i0, i1] = visibleRange();
    const plotW = r.width - 82; const rel = (e.clientX - r.left - 8) / plotW;
    return Math.max(i0, Math.min(i1 - 1, i0 + Math.floor(rel * (i1 - i0))));
  };
  c.addEventListener("mousemove", (e) => {
    if (chart.drag) {
      const [i0, i1] = chart.drag.view, span = i1 - i0;
      const dn = Math.round((chart.drag.x - e.clientX) / Math.max(2, (c.clientWidth - 82) / span));
      let a = Math.max(0, Math.min(state.candles.length - span, chart.drag.view[0] + dn));
      state.view = [a, a + span]; drawChart(); return;
    }
    const i = idxFromEvent(e); chart.hover = i; const cd = state.candles[i];
    if (cd) {
      const chg = cd.o ? (cd.c / cd.o - 1) * 100 : 0;
      tip.textContent = `${localTs(cd.t)}${cd.closed ? "" : " (đang hình thành)"}\nO ${fmtPrice(cd.o)}   H ${fmtPrice(cd.h)}\nL ${fmtPrice(cd.l)}   C ${fmtPrice(cd.c)}\n${chg >= 0 ? "+" : ""}${fmtNum(chg, 2)}% · Vol ${fmtNum(cd.v, 2)}`;
      const wr = c.parentElement.getBoundingClientRect(), r = c.getBoundingClientRect();
      tip.style.left = Math.min(r.width - 215, Math.max(4, e.clientX - wr.left + 14)) + "px";
      tip.style.top = Math.max(4, e.clientY - wr.top - 10) + "px";
      tip.classList.remove("hidden");
    }
    drawChart();
  });
  c.addEventListener("mouseleave", () => { chart.hover = -1; chart.drag = null; tip.classList.add("hidden"); drawChart(); });
  c.addEventListener("mousedown", (e) => { chart.drag = { x: e.clientX, view: visibleRange() }; });
  window.addEventListener("mouseup", () => chart.drag = null);
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [i0, i1] = visibleRange(), span = i1 - i0, focus = idxFromEvent(e);
    const factor = e.deltaY > 0 ? 1.25 : 0.8;
    const ns = Math.max(20, Math.min(state.candles.length, Math.round(span * factor)));
    const ratio = (focus - i0) / Math.max(1, span);
    let a = Math.max(0, Math.min(state.candles.length - ns, Math.round(focus - ns * ratio)));
    state.view = [a, a + ns]; drawChart();
  }, { passive: false });
  $("#chart-reset").addEventListener("click", () => { state.view = null; drawChart(); });
  window.addEventListener("resize", () => { drawChart(); drawPerf(); drawBacktest(); });
}

/* ---------------- Live data (WS + fallback polling) ---------------- */
function wsUrl() {
  const s = state.symbol.toLowerCase();
  return `${state.wsBase}/stream?streams=${s}@kline_${state.tf}/${s}@miniTicker`;
}
function connectWS() {
  closeWS();
  try { state.ws = new WebSocket(wsUrl()); } catch { scheduleReconnect(); return; }
  state.ws.onopen = () => { state.wsRetries = 0; setConn("live", "Trực tiếp · WebSocket"); stopPolling(); };
  state.ws.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    const d = m.data; if (!d) return;
    state.lastTickAt = Date.now();
    if (d.e === "kline" && d.k) {
      const k = d.k, candle = { t: k.t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v, closed: !!k.x };
      upsertCandle(candle);
      throttledDraw();
      updatePrice(candle.c);
    } else if (d.e === "24hrMiniTicker") {
      const p = +d.c, o = +d.o;
      updateTicker(p, o ? (p / o - 1) * 100 : null, false);
    }
  };
  state.ws.onclose = () => scheduleReconnect();
  state.ws.onerror = () => { try { state.ws.close(); } catch {} };
}
function closeWS() { if (state.ws) { state.ws.onclose = null; try { state.ws.close(); } catch {} state.ws = null; } clearTimeout(state.wsTimer); }
function scheduleReconnect() {
  setConn("reconnecting", "Đang kết nối lại…"); startPolling();
  const delay = Math.min(30000, 1000 * 2 ** state.wsRetries) + Math.random() * 700;
  state.wsRetries++;
  clearTimeout(state.wsTimer); state.wsTimer = setTimeout(connectWS, delay);
  if (state.wsRetries > 6) setConn("offline", "Mất kết nối WS · dùng REST dự phòng");
}
function upsertCandle(candle) {
  const arr = state.candles, wasAtEnd = !state.view || state.view[1] >= arr.length;
  if (arr.length && arr[arr.length - 1].t === candle.t) arr[arr.length - 1] = candle;
  else if (!arr.length || candle.t > arr[arr.length - 1].t) { arr.push(candle); if (arr.length > 1000) arr.shift(); }
  else { const i = arr.findIndex((x) => x.t === candle.t); if (i >= 0) arr[i] = candle; }
  if (wasAtEnd) state.view = null; // đang xem ở cuối -> tiếp tục bám giá mới; đang pan quá khứ -> giữ góc nhìn
}
let drawQueued = false;
function throttledDraw() { if (!drawQueued) { drawQueued = true; requestAnimationFrame(() => { drawQueued = false; drawChart(); }); } }
function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(async () => {
    try {
      const d = await api(`/api/ohlcv?symbol=${state.symbol}&interval=${state.tf}&limit=500`);
      state.candles = d.candles; drawChart();
      if (d.stale) showStale("Binance không phản hồi — đang hiển thị dữ liệu đã lưu cục bộ (không phải giá trực tiếp).");
    } catch {}
    try { const t = await api(`/api/ticker?symbol=${state.symbol}`); updateTicker(t.price, t.change_pct_24h, t.stale); } catch {}
  }, 15000);
}
function stopPolling() { clearInterval(state.pollTimer); state.pollTimer = null; hideStale(); }
function showStale(msg) { const b = $("#stale-banner"); $("#stale-text").textContent = "⚠ " + msg; b.classList.remove("hidden"); }
function hideStale() { $("#stale-banner").classList.add("hidden"); }

function updatePrice(p) {
  const el = $("#kpi-price"); el.classList.remove("skeleton"); el.textContent = fmtPrice(p);
  $("#kpi-updated").textContent = new Date().toLocaleTimeString("vi-VN", { hour12: false });
}
function updateTicker(price, changePct, stale) {
  updatePrice(price);
  if (changePct != null) {
    const el = $("#kpi-change");
    el.textContent = `24h: ${changePct >= 0 ? "▲" : "▼"} ${fmtPct(Math.abs(changePct), 2)}`;
    el.className = "kpi-sub " + (changePct >= 0 ? "up" : "down");
  }
  $("#price-src").textContent = stale ? "Dữ liệu đã lưu (stale)" : "Binance";
  if (stale) showStale("Đang hiển thị giá từ dữ liệu đã lưu cục bộ, không phải giá trực tiếp.");
}

/* ---------------- REST loads ---------------- */
async function loadChart() {
  $("#chart-loading").classList.remove("hidden");
  try {
    const d = await api(`/api/ohlcv?symbol=${state.symbol}&interval=${state.tf}&limit=500`);
    state.candles = d.candles; state.view = null; chart.hover = -1;
    if (d.stale) showStale("Không kết nối được Binance trực tiếp — biểu đồ dùng dữ liệu đã lưu cục bộ."); else hideStale();
    const t = await api(`/api/ticker?symbol=${state.symbol}`); updateTicker(t.price, t.change_pct_24h, t.stale);
  } catch (e) { toast("Không tải được biểu đồ: " + e.message, true); state.candles = []; }
  $("#chart-loading").classList.add("hidden"); drawChart();
}
async function loadForecast() {
  try {
    const f = await api(`/api/forecast?symbol=${state.symbol}&position_usd=${state.position}`);
    state.forecast = f; $("#empty-state").classList.add("hidden");
    renderForecast(f);
    const mb = $("#model-badge"); mb.className = "badge ready";
    mb.textContent = `Model: Ready · ${MODEL_NAMES[f.selected_model] || f.selected_model}`;
  } catch (e) {
    state.forecast = null; $("#empty-state").classList.remove("hidden");
    const corrupted = e.code === "MODEL_CORRUPTED";
    $("#empty-title").textContent = corrupted ? "File mô hình không đọc được" : "Model chưa được khởi tạo";
    $("#empty-text").textContent = corrupted
      ? "Bấm “Nạp dữ liệu & huấn luyện ngay” để tạo lại dữ liệu/mô hình ngay trong trình duyệt. " + (e.message || "")
      : "Bấm “Nạp dữ liệu & huấn luyện ngay” để tải lịch sử Binance public và huấn luyện BTC/ETH. Không cần CMD hay PowerShell.";
    const mb = $("#model-badge"); mb.className = "badge offline";
    mb.textContent = corrupted ? "Model: corrupted — cần huấn luyện lại" : "Model: chưa khởi tạo";
    ["#kpi-regime", "#kpi-fvol", "#kpi-var"].forEach((s) => $(s).textContent = "—");
    $("#summary-band").classList.add("hidden");
  }
}
function renderForecast(f) {
  const reg = f.regime, risk = f.risk[state.method];
  $("#summary-band").classList.remove("hidden");
  $("#summary-text").textContent = f.interpretation.market_summary;
  $("#kpi-regime").textContent = reg.label_vi;
  $("#kpi-regime-sub").textContent = reg.percentile_vs_train != null ? `Phân vị ~${fmtNum(reg.percentile_vs_train, 0)} so với tập huấn luyện` : "Theo phân vị tập huấn luyện";
  $("#kpi-fvol").textContent = fmtPct(f.forecast_vol_annualized_pct, 1);
  $("#kpi-fvol-sub").textContent = `Ngày: ${fmtPct(f.forecast_vol_daily * 100, 2)} · 7 ngày: ${fmtPct(f.forecast_vol_7d * 100, 1)} (mở rộng quy mô)`;
  renderRisk(f);
  $("#kpi-updated-sub").textContent = `Giá: trực tiếp · Model: ${localTime(f.generated_at_utc)} (ngày đóng cuối ${f.last_closed_day})`;
  // regime scale: ánh xạ percentile -> vị trí theo các đoạn 25/75/90
  const pct = reg.percentile_vs_train;
  if (pct != null) {
    const segs = [[0, 25, 0, 23.3], [25, 75, 23.3, 60.5], [75, 90, 60.5, 83.7], [90, 100, 83.7, 100]];
    let left = 50; for (const [a, b, x, y] of segs) if (pct >= a && pct <= b) left = x + (pct - a) / (b - a) * (y - x);
    $("#regime-marker").style.left = left + "%";
  }
  $("#regime-desc").textContent = reg.description;
  $("#vol-kv").innerHTML = `
    <dt>Volatility dự báo (năm-hoá)</dt><dd>${fmtPct(f.forecast_vol_annualized_pct, 1)}</dd>
    <dt>Realized vol ngày gần nhất</dt><dd>${fmtPct(f.current_realized_vol_annualized_pct, 1)}</dd>
    <dt>Phân vị so với tập huấn luyện</dt><dd>${pct != null ? fmtNum(pct, 0) + "%" : "—"}</dd>
    <dt>Kỳ huấn luyện</dt><dd>${f.train_period.start} → ${f.train_period.end}</dd>
    <dt>Kỳ kiểm tra out-of-sample</dt><dd>${f.test_period.start} → ${f.test_period.end}</dd>`;
  $("#model-vol-list").innerHTML = Object.entries(f.models_vol_annualized_pct).map(([k, v]) =>
    `<div class="model-row"><span>${MODEL_NAMES[k] || k}${k === f.selected_model ? '<span class="best-tag">đang dùng cho VaR</span>' : ""}</span><b>${fmtPct(v, 1)}</b></div>`).join("");
  $("#selected-note").textContent = f.interpretation.model_summary + " Thứ hạng này chỉ phản ánh kỳ kiểm tra hiện tại.";
  $("#wrong-list").innerHTML = (f.interpretation.what_could_be_wrong || []).map((x) => `<li>${x}</li>`).join("");
  $("#limit-list").innerHTML = (f.limitations || []).map((x) => `<li>${x}</li>`).join("");
  $("#method-defs").innerHTML = `
    <p><b>Quy ước:</b> ${f.risk.convention}</p>
    <p><b>Realized variance ngày</b> RV<sub>t</sub> = Σ (log-return 1 giờ trong ngày UTC)<sup>2</sup>; realized vol = √RV. Features tại ngày t chỉ dùng thông tin đến hết ngày t, mục tiêu là RV ngày t+1.</p>
    <p><b>GARCH(1,1):</b> σ²<sub>t</sub> = ω + αε²<sub>t−1</sub> + βσ²<sub>t−1</sub> trên log-return ngày. <b>HAR-RV:</b> RV<sub>t+1</sub> = β<sub>0</sub> + β<sub>d</sub>RV<sub>t</sub> + β<sub>w</sub>RV<sup>(5)</sup> + β<sub>m</sub>RV<sup>(22)</sup>. <b>XGBoost:</b> hồi quy RV ngày tới trên các lag RV/return/range/volume và RV chéo BTC↔ETH.</p>
    <p><b>VaR theo dự báo:</b> lợi suất kỳ tới = σ<sub>dự báo</sub> × ε, ε ~ Student-t chuẩn hoá (phương sai đơn vị, df ước lượng từ lợi suất lịch sử); ES tính bằng Monte Carlo hạt giống cố định (200.000 mô phỏng, tái lập được).</p>
    <p><b>Chọn mô hình cho VaR:</b> ${f.risk.selection_rule}.</p>`;
}
function renderRisk(f) {
  const m = f.risk[state.method]; const pos = f.risk.reference_position_usd;
  $("#r-var95").textContent = fmtUSD(m.var_95); $("#r-var95-pct").textContent = fmtPct(m.var_95_pct, 2) + " của vị thế";
  $("#r-es95").textContent = fmtUSD(m.es_95); $("#r-es95-pct").textContent = fmtPct(m.es_95_pct, 2) + " của vị thế";
  $("#r-var99").textContent = fmtUSD(m.var_99); $("#r-var99-pct").textContent = fmtPct(m.var_99_pct, 2) + " của vị thế";
  $("#r-es99").textContent = fmtUSD(m.es_99); $("#r-es99-pct").textContent = fmtPct(m.es_99_pct, 2) + " của vị thế";
  $("#kpi-var").textContent = fmtUSD(f.risk.forecast_based.var_95);
  $("#kpi-var-sub").textContent = `${fmtPct(f.risk.forecast_based.var_95_pct, 2)} trên vị thế ${fmtUSD(pos)} · 1 ngày`;
  const names = { forecast_based: `Phương pháp theo dự báo (${MODEL_NAMES[f.selected_model]}) — dùng volatility dự báo kết hợp đuôi Student-t (df=${fmtNum(f.risk.forecast_based.t_df, 1)}).`,
    historical_simulation: `Historical Simulation trên ${f.risk.historical_simulation.n_obs} lợi suất ngày gần nhất — không giả định dạng phân phối, nhưng chỉ phản ánh quá khứ đã quan sát.`,
    parametric_student_t: `Student-t tham số fit trên toàn bộ lợi suất ngày lịch sử (df=${fmtNum(f.risk.parametric_student_t.params.df, 1)}) — đuôi dày hơn phân phối chuẩn nhưng vẫn là giả định mô hình.` };
  $("#risk-method-note").textContent = names[state.method];
  $("#risk-interpretation").textContent = state.method === "forecast_based" ? f.interpretation.risk_summary :
    `Theo phương pháp đang chọn, VaR 95% trong 1 ngày là ${fmtUSD(m.var_95)} trên vị thế ${fmtUSD(pos)}. So sánh giữa các phương pháp giúp thấy độ nhạy với giả định — không có phương pháp nào là "đúng tuyệt đối".`;
}

/* ---------------- Performance & Backtest (lazy) ---------------- */
function setupCanvas(id, height) {
  const c = $(id), dpr = window.devicePixelRatio || 1, w = c.clientWidth;
  if (!w) return null;
  c.width = Math.round(w * dpr); c.height = Math.round(height * dpr); c.style.height = height + "px";
  const ctx = c.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h: height };
}
function lineSeries(ctx, w, h, series, opts = {}) {
  const padL = 8, padR = 64, padT = 10, padB = 22, plotW = w - padL - padR, plotH = h - padT - padB;
  let hi = -Infinity, lo = Infinity;
  series.forEach((s) => s.data.forEach((v) => { if (v != null && isFinite(v)) { hi = Math.max(hi, v); lo = Math.min(lo, v); } }));
  if (!isFinite(hi)) return null;
  if (opts.zeroBase) lo = Math.min(0, lo);
  const span = (hi - lo) || 1; hi += span * 0.08; lo -= span * 0.04;
  const n = Math.max(...series.map((s) => s.data.length));
  const X = (i) => padL + plotW * (n <= 1 ? 0 : i / (n - 1)), Y = (v) => padT + (hi - v) / (hi - lo) * plotH;
  ctx.font = "11px Consolas, monospace"; ctx.fillStyle = "#647183";
  for (let g = 0; g <= 4; g++) {
    const v = lo + (hi - lo) * g / 4, y = Y(v);
    ctx.strokeStyle = "#182030"; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.textAlign = "left"; ctx.fillText(opts.fmt ? opts.fmt(v) : fmtNum(v, 3), w - padR + 7, y + 4);
  }
  if (opts.labels) { const every = Math.max(1, Math.floor(n / 6)); for (let i = 0; i < n; i += every) { ctx.textAlign = i === 0 ? "left" : (i >= n - every ? "right" : "center"); ctx.fillText(opts.labels[i] || "", X(i), h - 6); } }
  if (opts.zeroBase && lo < 0) { ctx.strokeStyle = "#2a3548"; ctx.beginPath(); ctx.moveTo(padL, Y(0)); ctx.lineTo(w - padR, Y(0)); ctx.stroke(); }
  series.forEach((s) => {
    ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 1.6; ctx.beginPath();
    s.data.forEach((v, i) => { if (v == null || !isFinite(v)) return; const x = X(i), y = Y(v); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
    ctx.stroke(); ctx.lineWidth = 1;
  });
  return { X, Y };
}
async function loadPerformance() {
  const p = await api(`/api/performance?symbol=${state.symbol}`); state.performance = p;
  const keys = Object.keys(p.forecasts_vol_daily);
  $("#perf-legend").innerHTML = `<span><span class="sw" style="background:#e8edf3"></span>Thực tế</span>` +
    keys.map((k) => `<span><span class="sw" style="background:${MODEL_COLORS[k]}"></span>${MODEL_NAMES[k] || k}</span>`).join("");
  $("#perf-note").textContent = p.note + ` Mô hình được chọn: ${MODEL_NAMES[p.selected_model]} (QLIKE thấp nhất).`;
  $("#metrics-table tbody").innerHTML = Object.entries(p.metrics).map(([k, m]) =>
    `<tr class="${k === p.selected_model ? "best" : ""}"><td>${MODEL_NAMES[k] || k}</td><td>${fmtPct(m.mae_vol * 100, 2)}</td><td>${fmtPct(m.rmse_vol * 100, 2)}</td><td>${fmtNum(m.qlike, 3)}</td><td>${m.n}</td><td>${k === p.selected_model ? "Tốt nhất theo QLIKE" : ""}</td></tr>`).join("");
  $("#dm-box").innerHTML = Object.entries(p.diebold_mariano || {}).map(([k, v]) =>
    `<p><b>${k.replace("_vs_", " vs ").split(" ").map((x) => MODEL_NAMES[x] || x).join(" ")}</b>: ${v.p_value == null ? "không đủ dữ liệu" : `DM = ${fmtNum(v.statistic, 2)}, p-value = ${fmtNum(v.p_value, 3)} (n=${v.n})`}</p>`).join("") || "<p>Không có kiểm định.</p>";
  drawPerf();
}
function drawPerf() {
  const p = state.performance; if (!p) return;
  const s = setupCanvas("#perf-chart", 300); if (!s) return;
  const series = [{ data: p.actual_vol_daily.map((v) => v * 100), color: "#e8edf3", width: 1.8 }];
  for (const [k, arr] of Object.entries(p.forecasts_vol_daily))
    series.push({ data: arr.map((v) => v == null ? null : v * 100), color: MODEL_COLORS[k], width: k === p.selected_model ? 2 : 1.3 });
  lineSeries(s.ctx, s.w, s.h, series, { fmt: (v) => fmtNum(v, 1) + "%", labels: p.dates });
}
async function loadBacktest() {
  const b = await api(`/api/backtest?symbol=${state.symbol}`); state.backtest = b;
  $("#bt-method").textContent = b.method + ` · vị thế ${fmtUSD(b.reference_position_usd)}`;
  const renderSummary = (el, s, level) => {
    const kup = s.kupiec, chr = s.christoffersen;
    el.innerHTML = `<dl class="kv">
      <dt>Số ngày kiểm tra</dt><dd>${s.n}</dd>
      <dt>Số lần breach</dt><dd>${s.breaches} (${fmtPct(s.breach_rate * 100, 1)}; kỳ vọng ${fmtPct(100 - level, 0)})</dd>
      ${kup.status === "ok" ? `<dt>Kupiec (unconditional)</dt><dd>p = ${fmtNum(kup.p_value, 3)}</dd><dt>Kết luận</dt><dd style="font-weight:500;text-align:left">${kup.verdict}</dd>` : `<dt>Kupiec</dt><dd>Không đủ dữ liệu</dd>`}
      ${chr.status === "ok" ? `<dt>Christoffersen (conditional)</dt><dd>p = ${fmtNum(chr.p_value_conditional_coverage, 3)}</dd>` : `<dt>Christoffersen</dt><dd>Không đủ dữ liệu</dd>`}
      ${s.quantile_loss != null ? `<dt>Quantile loss (VaR${level})</dt><dd>${fmtNum(s.quantile_loss, 1)}</dd>` : ""}</dl>`;
  };
  renderSummary($("#bt95"), b.summary_95, 95); renderSummary($("#bt99"), b.summary_99, 99);
  $("#breach-table tbody").innerHTML = b.series.filter((r) => r.breach95).map((r) =>
    `<tr><td>${r.date}</td><td>${fmtUSD(r.loss_usd)}</td><td>${fmtUSD(r.var95_usd)}</td><td>${fmtUSD(r.var99_usd)}</td><td>${r.breach99 ? "Vượt VaR99" : "Vượt VaR95"}</td></tr>`).join("") || `<tr><td colspan="5">Không có breach trong kỳ kiểm tra.</td></tr>`;
  drawBacktest();
}
function drawBacktest() {
  const b = state.backtest; if (!b) return;
  const s = setupCanvas("#bt-chart", 280); if (!s) return;
  const rows = b.series;
  const xy = lineSeries(s.ctx, s.w, s.h, [
    { data: rows.map((r) => r.loss_usd), color: "#8d99a8", width: 1.3 },
    { data: rows.map((r) => r.var95_usd), color: "#5b8def", width: 1.6 },
    { data: rows.map((r) => r.var99_usd), color: "#d9a441", width: 1.3 },
  ], { fmt: (v) => "$" + fmtNum(v, 0), labels: rows.map((r) => r.date), zeroBase: true });
  if (!xy) return;
  rows.forEach((r, i) => { if (r.breach95) { s.ctx.fillStyle = "#d64550"; s.ctx.beginPath(); s.ctx.arc(xy.X(i), xy.Y(r.loss_usd), 3.4, 0, 7); s.ctx.fill(); } });
  s.ctx.font = "11px sans-serif"; s.ctx.fillStyle = "#8d99a8"; s.ctx.textAlign = "left";
  s.ctx.fillText("— Lỗ thực tế   — VaR95   — VaR99   ● breach", 10, 14);
}
async function loadExplain() {
  const ex = await api(`/api/explain?symbol=${state.symbol}`); state.explain = ex;
  const max = Math.max(...ex.feature_importance.map((x) => x.share), 0.001);
  $("#importance-list").innerHTML = ex.feature_importance.map((x) =>
    `<div class="imp-row"><span title="${ex.feature_schema[x.feature] || ""}">${x.feature}</span><div class="imp-bar"><div class="imp-fill" style="width:${(x.share / max * 100).toFixed(1)}%"></div></div><span>${fmtPct(x.share * 100, 0)}</span></div>`).join("");
  $("#importance-note").textContent = ex.importance_method + " Di chuột lên tên feature để xem định nghĩa.";
  $("#method-params").textContent = JSON.stringify({ garch: ex.garch, har_rv: ex.har, xgboost_engine: ex.xgboost_engine, xgboost_params: ex.xgboost_params }, null, 2);
}
async function loadStatus(withQuality = false) {
  const st = await api(`/api/status${withQuality ? "?include_quality=true" : ""}`);
  state.wsBase = st.config.binance_ws_base || state.wsBase;
  $("#dataset-table tbody").innerHTML = (st.datasets || []).map((d) =>
    `<tr><td>${d.symbol}</td><td>${d.interval}</td><td>${Number(d.rows).toLocaleString()}</td><td>${localTime(d.last_update_utc)}</td><td>${d.status}</td></tr>`).join("") || `<tr><td colspan="5">Chưa có dataset.</td></tr>`;
  $("#jobs-table tbody").innerHTML = (st.recent_jobs || []).map((j) =>
    `<tr><td>${j.job_type}</td><td>${j.symbol || ""}</td><td>${localTime(j.finished_at_utc)}</td><td>${j.status}</td></tr>`).join("");
  const bg = st.background_jobs || {};
  const parts = Object.entries(bg).filter(([, v]) => v.last).map(([k, v]) => `${k}: ${v.running ? "đang chạy…" : v.last.status + (v.last.error ? " (" + v.last.error + ")" : "")}`);
  $("#job-status").textContent = parts.length ? "Tác vụ nền — " + parts.join(" · ") : "";
  const anyRunning = Object.values(bg).some((v) => v.running);
  setJobButtonsDisabled(anyRunning);
  if (st.data_quality) {
    $("#quality-table tbody").innerHTML = st.data_quality.map((q) =>
      `<tr><td>${q.symbol} ${q.interval}</td><td>${q.file_state}</td><td>${Number(q.rows || 0).toLocaleString()}</td><td>${q.gap_count ?? "—"}</td><td>${q.duplicates ?? "—"}</td><td>${q.ohlc_violations ?? "—"}</td><td>${q.start_utc ? localTime(q.start_utc) + " → " + localTime(q.end_utc) : (q.note || "—")}</td></tr>`).join("");
  }
  const mAll = st.models || {};
  $("#model-files-note").textContent = Object.entries(mAll).map(([s, m]) =>
    `${s}: ${m.status}${m.model_files ? " · files=" + m.model_files.overall + " (" + Object.entries(m.model_files.files).map(([k, v]) => k + ":" + v).join(", ") + ")" : ""}${m.guidance ? " · " + m.guidance : ""}`).join("  |  ");
  const m = st.models[state.symbol];
  if (m && (m.status === "ready" || m.status === "ready_with_warnings") && !state.forecast) loadForecast();
  return st;
}

let jobPoll = null;
function setJobButtonsDisabled(disabled) {
  document.querySelectorAll("#btn-prepare-browser, #btn-prepare-data, #btn-update, #btn-retrain")
    .forEach((b) => { if (b) b.disabled = disabled; });
}
function watchJob(kind) {
  clearInterval(jobPoll);
  const started = Date.now();
  setJobButtonsDisabled(true);
  $("#job-status").textContent = `Đang chạy tác vụ “${kind}” ở nền… Giao diện vẫn dùng bình thường. Tác vụ không huỷ giữa chừng để tránh ghi dữ liệu dở dang.`;
  jobPoll = setInterval(async () => {
    try {
      const st = await loadStatus(false);
      const j = (st.background_jobs || {})[kind];
      if (!j) return;
      if (j.running) {
        const secs = Math.round((Date.now() - started) / 1000);
        $("#job-status").textContent = `Đang chạy tác vụ “${kind}” (${secs}s)… xem logs/app.log nếu cần chi tiết.`;
        return;
      }
      clearInterval(jobPoll); jobPoll = null;
      setJobButtonsDisabled(false);
      const last = j.last || {};
      if (last.status === "success") {
        toast(kind === "prepare" ? "Đã nạp dữ liệu và huấn luyện xong. Dự báo đã sẵn sàng." : kind === "retrain" ? "Huấn luyện lại hoàn tất. Đã tải lại dự báo mới." : "Cập nhật dữ liệu hoàn tất.");
        if (kind === "retrain" || kind === "prepare") { state.loadedTabs.delete("models"); state.loadedTabs.delete("history"); state.loadedTabs.delete("explain"); state.performance = state.backtest = state.explain = null; }
        await loadForecast();
        await loadStatus(true);
        const active = document.querySelector(".tab.active").dataset.tab;
        if (["models", "history", "explain"].includes(active)) lazyLoad(active);
      } else {
        toast(`Tác vụ ${kind} thất bại${last.error ? ": " + last.error : ""}. Dữ liệu/mô hình tốt gần nhất vẫn được giữ.`, true);
      }
    } catch {
      clearInterval(jobPoll); jobPoll = null;
      setJobButtonsDisabled(false);
    }
  }, 3000);
}

const PREF_KEY = "cri_prefs_v1";
function savePrefs() {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify({
      symbol: state.symbol, tf: state.tf, method: state.method, position: state.position,
      tab: (document.querySelector(".tab.active") || {}).dataset?.tab || "risk",
    }));
  } catch {}
}
function restorePrefs() {
  let p = {};
  try { p = JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); } catch {}
  if (["BTCUSDT", "ETHUSDT"].includes(p.symbol)) state.symbol = p.symbol;
  if (["1m", "5m", "15m", "30m", "1h", "4h", "1d"].includes(p.tf)) state.tf = p.tf;
  if (["forecast_based", "historical_simulation", "parametric_student_t"].includes(p.method)) state.method = p.method;
  if (isFinite(+p.position) && +p.position > 0) state.position = +p.position;
  document.querySelectorAll(".top-actions .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.symbol === state.symbol));
  document.querySelectorAll("#tf-seg button").forEach((b) => b.classList.toggle("active", b.dataset.tf === state.tf));
  document.querySelectorAll("#method-seg button").forEach((b) => b.classList.toggle("active", b.dataset.method === state.method));
  $("#position-input").value = state.position;
  $("#chart-title").textContent = state.symbol.replace("USDT", "/USDT");
  if (["risk", "models", "history", "explain", "data"].includes(p.tab) && p.tab !== "risk") {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === p.tab));
    document.querySelectorAll(".tab-panel").forEach((x) => x.classList.toggle("hidden", x.id !== "tab-" + p.tab));
  }
}

/* ---------------- Events ---------------- */
function switchSymbol(sym) {
  if (state.symbol === sym) return;
  state.symbol = sym; state.loadedTabs.clear();
  state.performance = state.backtest = state.explain = null;
  document.querySelectorAll(".top-actions .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.symbol === sym));
  $("#chart-title").textContent = sym.replace("USDT", "/USDT");
  savePrefs();
  loadAll();
}
async function loadAll() {
  await loadChart(); connectWS(); await loadForecast();
  try { await loadStatus(false); } catch (e) { toast("Chưa đọc được trạng thái hệ thống: " + e.message, true); }
  const active = document.querySelector(".tab.active").dataset.tab;
  lazyLoad(active);
}
async function lazyLoad(tab) {
  if (state.loadedTabs.has(tab)) { if (tab === "models") drawPerf(); if (tab === "history") drawBacktest(); return; }
  try {
    if (tab === "models") await loadPerformance();
    else if (tab === "history") await loadBacktest();
    else if (tab === "explain") await loadExplain();
    else if (tab === "data") await loadStatus(true);
    else return;
    state.loadedTabs.add(tab);
  } catch (e) { toast("Chưa tải được mục này: " + e.message, true); }
}
document.querySelectorAll(".top-actions .seg-btn").forEach((b) => b.addEventListener("click", () => switchSymbol(b.dataset.symbol)));
document.querySelectorAll("#tf-seg button").forEach((b) => b.addEventListener("click", async () => {
  if (state.tf === b.dataset.tf) return;
  state.tf = b.dataset.tf;
  document.querySelectorAll("#tf-seg button").forEach((x) => x.classList.toggle("active", x === b));
  savePrefs();
  await loadChart(); connectWS(); // chỉ nạp lại nến, giữ nguyên trạng thái rủi ro/mô hình
}));
document.querySelectorAll("#method-seg button").forEach((b) => b.addEventListener("click", () => {
  state.method = b.dataset.method;
  document.querySelectorAll("#method-seg button").forEach((x) => x.classList.toggle("active", x === b));
  savePrefs();
  if (state.forecast) renderRisk(state.forecast);
}));
let posTimer = null;
$("#position-input").addEventListener("input", (e) => {
  const v = parseFloat(e.target.value); if (!v || v <= 0) return;
  state.position = v; savePrefs(); clearTimeout(posTimer); posTimer = setTimeout(loadForecast, 450);
});
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + t.dataset.tab));
  savePrefs();
  lazyLoad(t.dataset.tab);
}));
document.querySelectorAll(".q").forEach((b) => b.addEventListener("click", (e) => {
  e.stopPropagation(); const pop = $("#tip-pop");
  pop.textContent = TIPS[b.dataset.tip] || ""; pop.classList.remove("hidden");
  pop.style.left = Math.min(window.innerWidth - 340, e.clientX + 10) + "px";
  pop.style.top = (e.clientY + 14) + "px";
}));
document.addEventListener("click", () => $("#tip-pop").classList.add("hidden"));
async function startBrowserPrepare() {
  try {
    const r = await api(`/api/admin/prepare`, { method: "POST" });
    toast(r.message);
    // Đưa người dùng tới nơi thấy tiến độ, nhưng giữ nguyên biểu đồ phía trên.
    document.querySelector("[data-tab='data']").click();
    watchJob("prepare");
  } catch (err) { toast("Không bắt đầu được tác vụ nạp dữ liệu: " + err.message, true); }
}
const prepareBrowserBtn = $("#btn-prepare-browser");
if (prepareBrowserBtn) prepareBrowserBtn.addEventListener("click", startBrowserPrepare);
const prepareDataBtn = $("#btn-prepare-data");
if (prepareDataBtn) prepareDataBtn.addEventListener("click", startBrowserPrepare);
$("#btn-update").addEventListener("click", async () => {
  try { const r = await api(`/api/admin/update?symbol=${state.symbol}`, { method: "POST" }); toast(r.message); watchJob("update"); }
  catch (err) { toast(err.message, true); }
});
$("#btn-retrain").addEventListener("click", async () => {
  if (!confirm("Huấn luyện lại toàn bộ mô hình trên dữ liệu đã lưu? Tác vụ chạy ở nền và có thể mất vài phút; giao diện vẫn dùng được.")) return;
  try { const r = await api(`/api/admin/retrain?symbol=${state.symbol}`, { method: "POST" }); toast(r.message); watchJob("retrain"); }
  catch (err) { toast(err.message, true); }
});
$("#btn-refresh-status").addEventListener("click", () => loadStatus(true).catch((e) => toast("Chưa làm mới được trạng thái: " + e.message, true)));
$("#btn-retry-live").addEventListener("click", async () => {
  toast("Đang thử tải lại dữ liệu trực tiếp…");
  await loadChart(); connectWS();
});
$("#btn-retry-forecast").addEventListener("click", async () => {
  await loadForecast();
  try { await loadStatus(false); } catch {}
});
// Watchdog: tick không đến >45s -> coi là stale, chủ động reconnect
setInterval(() => {
  if (state.ws && state.ws.readyState === WebSocket.OPEN && state.lastTickAt && Date.now() - state.lastTickAt > 45000) {
    setConn("reconnecting", "Dữ liệu chậm · đang kết nối lại…"); try { state.ws.close(); } catch {}
  }
}, 15000);

restorePrefs();
bindChartEvents();
loadAll().catch((e) => toast("Lỗi khởi tạo: " + e.message, true));
