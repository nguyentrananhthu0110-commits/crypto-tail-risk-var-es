"""Báo cáo PDF chuyên sâu — dựa trên artifacts đã tính & bảng backtest mở rộng."""
from __future__ import annotations
import json
import math
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from src.config import MODEL_META_DIR
from fpdf import FPDF

# Font có dấu tiếng Việt: ưu tiên font kèm theo dự án, fallback sang hệ thống
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
BUNDLED_DIR = PROJECT_ROOT / "assets" / "fonts"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
DEJA = BUNDLED_DIR / "DejaVuSans.ttf"
DEJA_B = BUNDLED_DIR / "DejaVuSans-Bold.ttf"
if not DEJA.exists():
    DEJA = FONT_DIR / "DejaVuSans.ttf"
    DEJA_B = FONT_DIR / "DejaVuSans-Bold.ttf"
FALLBACK_FONT = "helvetica"
FONT_FAMILY = "dejavu" if DEJA.exists() and DEJA_B.exists() else FALLBACK_FONT
USE_DEJAVU = FONT_FAMILY == "dejavu"

MODEL_LABELS = {
    "historical_22d": "Historical 22d",
    "garch_1_1": "GARCH(1,1)-t",
    "har_rv": "HAR-RV",
    "xgboost": "XGBoost",
    "GARCH-t (rolling)": "GARCH-t (rolling)",
    "EWMA-t (RiskMetrics)": "EWMA-t (RiskMetrics)",
    "Historical 22d-t": "Historical 22d-t",
    "GARCH-chuẩn (đối chứng đuôi mỏng)": "GARCH-chuẩn (đuôi mỏng)",
}
MODEL_THEORY = {
    "historical_22d": "Mốc so sánh đơn giản nhất (naïve benchmark): trung bình phương sai thực hiện 22 ngày. Không tham số; đại diện kỳ vọng 'biến động sẽ giống trung bình tháng qua'. Dùng để kiểm tra mô hình phức tạp có thực sự hơn trung bình đơn giản hay không.",
    "garch_1_1": "GARCH(1,1)-t (Bollerslev 1986): σ²ₜ = ω + α·ε²ₜ₋₁ + β·σ²ₜ₋₁, phần dư Student-t. Nắm bắt cụm biến động và đuôi dày. Tham số α đo phản ứng cú sốc, β đo tính bền.",
    "har_rv": "HAR-RV (Corsi 2009): RVₜ₊₁ = β₀ + βᴅ·RVₜ + βᵂ·RV̄⁵ + βᴹ·RV̄²². Mô phỏng hành vi đa chân trời; chuẩn học thuật cho realized volatility.",
    "xgboost": "XGBoost trên log(RV) kèm hiệu chỉnh Duan smearing (Chen & Guestrin 2016; Duan 1983): cây tăng cường trên lag RV, lợi suất, biên độ, khối lượng, RV chéo; đảm bảo phương sai dự báo luôn dương ổn định trên cả altcoin biên độ gắt.",
}


def _sanitize(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    return (s.replace("\u201c", '"').replace("\u201d", '"')
             .replace("\u2019", "'").replace("\u2018", "'"))


def _is_finite(v) -> bool:
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except Exception:
        return False


def _fmt(v, d=4):
    if not _is_finite(v):
        return "-"
    return f"{float(v):.{d}f}"


def _load(symbol: str):
    base = MODEL_META_DIR

    def load(name):
        p = base / f"{symbol}_{name}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    return load("forecast"), load("performance"), load("backtest"), load("explain")


def _load_table_rows(filename: str, symbol: str, tables_dir: Path | None = None) -> list[dict]:
    tdir = tables_dir or TABLES_DIR
    path = tdir / filename
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return []
    if "symbol" in df.columns:
        key = symbol.replace("USDT", "") if symbol not in set(df["symbol"].astype(str)) else symbol
        df = df[df["symbol"].astype(str) == key]
    if df.empty:
        return []
    rows = df.to_dict(orient="records")
    return [
        {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in r.items()}
        for r in rows
    ]


class PDF(FPDF):
    def header(self):
        self.set_font(FONT_FAMILY, "B", 8)
        self.set_text_color(100, 100, 120)
        self.cell(0, 6, "Crypto Risk Intelligence — Báo cáo phân tích & kiểm định VaR/ES chuyên sâu",
                  align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 210, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font(FONT_FAMILY, "", 7)
        self.set_text_color(130, 130, 130)
        self.cell(
            0, 10,
            f"Trang {self.page_no()}/{{nb}} — Tạo lúc {datetime.now(timezone.utc).isoformat()} — Không phải khuyến nghị đầu tư",
            align="C",
        )


def _ensure_space(pdf: FPDF, needed_mm: float = 30.0):
    if pdf.get_y() + needed_mm > 277.0:
        pdf.add_page()


def _section_bar(pdf: FPDF, title: str):
    _ensure_space(pdf, 24)
    pdf.set_font(FONT_FAMILY, "B", 10.5)
    pdf.set_text_color(20, 45, 90)
    pdf.set_fill_color(235, 240, 248)
    pdf.cell(0, 7, _sanitize(f" {title}"), fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _render_ext_backtest_table(pdf: FPDF, rows: list[dict]):
    if not rows:
        return
    _ensure_space(pdf, 12 + 5 * len(rows))
    # Tổng độ rộng = 44 + 12 + 24 + 17 + 23 + 32 + 24 + 14 = 190 mm (vừa khít khổ A4 lề 10mm)
    w = [44, 12, 24, 17, 23, 32, 24, 14]
    headers = [
        "Mô hình", "Mức", "Vi phạm/KV", "Kupiec p",
        "Christoff. p", "ES dự báo/Lỗ thực", "ES-Z2 (p)", "Basel",
    ]
    pdf.set_font(FONT_FAMILY, "B", 6.8)
    pdf.set_text_color(20, 35, 65)
    pdf.set_fill_color(243, 246, 251)
    for i, h in enumerate(headers):
        pdf.cell(w[i], 5.5, _sanitize(h), border=1, align="C", fill=True)
    pdf.ln()

    for r in rows:
        _ensure_space(pdf, 6)
        m_name = MODEL_LABELS.get(str(r.get("model")), str(r.get("model")))
        lvl = str(r.get("mức_tin_cậy", "-"))
        br_txt = f"{r.get('vi_phạm', '-')} / {_fmt(r.get('kỳ_vọng'), 1)}"
        kup_p = r.get("kupiec_p")
        cc_p = r.get("christoffersen_cc_p")
        cc_txt = _fmt(cc_p, 3) if _is_finite(cc_p) else f"<5 VP ({r.get('vi_phạm', 0)})"
        es_p = r.get("ES_dự_báo_trung_bình_%_ngày_vi_phạm")
        loss_a = r.get("lỗ_thực_tế_trung_bình_%_ngày_vi_phạm")
        if _is_finite(es_p) and _is_finite(loss_a):
            es_vs_loss = f"{float(es_p):.2f}% / {float(loss_a):.2f}%"
        elif r.get("vi_phạm") == 0:
            es_vs_loss = "0 vi phạm"
        else:
            es_vs_loss = "-"
        z2 = r.get("ES_Z2")
        z2_p = r.get("ES_Z2_p")
        z2_txt = f"{float(z2):.2f} ({float(z2_p):.3f})" if (_is_finite(z2) and _is_finite(z2_p)) else "-"
        basel = str(r.get("Basel") or "-")

        rejected = (
            (_is_finite(kup_p) and float(kup_p) < 0.05)
            or (_is_finite(cc_p) and float(cc_p) < 0.05)
            or (_is_finite(z2_p) and float(z2_p) < 0.05)
            or basel == "Đỏ"
        )
        pdf.set_font(FONT_FAMILY, "B" if rejected else "", 6.7)
        pdf.set_text_color(*(185, 35, 35) if rejected else (30, 30, 35))
        vals = [m_name, lvl, br_txt, _fmt(kup_p, 3), cc_txt, es_vs_loss, z2_txt, basel]
        for i, val in enumerate(vals):
            align = "L" if i == 0 else "C"
            pdf.cell(w[i], 5, _sanitize(f" {val}" if i == 0 else val), border=1, align=align)
        pdf.ln()
    pdf.set_text_color(30, 30, 35)


def _render_dm_table(pdf: FPDF, rows: list[dict], bench_label: str):
    if not rows:
        return
    _ensure_space(pdf, 12 + 5 * len(rows))
    # Tổng độ rộng = 40 + 14 + 21 + 21 + 94 = 190 mm
    w = [40, 14, 21, 21, 94]
    headers = ["Mô hình", "Mức", "Chỉ số DM", "Giá trị p", f"Diễn giải (so với {bench_label})"]
    pdf.set_font(FONT_FAMILY, "B", 6.8)
    pdf.set_text_color(20, 35, 65)
    pdf.set_fill_color(243, 246, 251)
    for i, h in enumerate(headers):
        pdf.cell(w[i], 5.5, _sanitize(h), border=1, align="C", fill=True)
    pdf.ln()

    for r in rows:
        _ensure_space(pdf, 6)
        dm = r.get("DM_stat")
        pv = r.get("p_value")
        if _is_finite(dm) and _is_finite(pv):
            dm_f, pv_f = float(dm), float(pv)
            if pv_f < 0.05 and dm_f < 0:
                verdict = "Tốt hơn mốc cơ sở có ý nghĩa thống kê (p < 0.05)"
                color = (20, 125, 65)
                style = "B"
            elif pv_f < 0.05 and dm_f > 0:
                verdict = "Kém hơn mốc cơ sở có ý nghĩa thống kê (p < 0.05)"
                color = (185, 35, 35)
                style = "B"
            else:
                verdict = "Chưa có ý nghĩa thống kê (ngang nhau, p >= 0.05)"
                color = (60, 65, 75)
                style = ""
        else:
            verdict = "Không đủ dữ liệu so sánh"
            color = (100, 100, 105)
            style = ""
        pdf.set_font(FONT_FAMILY, style, 6.7)
        pdf.set_text_color(*color)
        m_name = MODEL_LABELS.get(str(r.get("model")), str(r.get("model")))
        vals = [m_name, str(r.get("mức_tin_cậy", "-")), _fmt(dm, 2), _fmt(pv, 3), verdict]
        for i, val in enumerate(vals):
            align = "L" if i in (0, 4) else "C"
            pdf.cell(w[i], 5, _sanitize(f" {val}" if i in (0, 4) else val), border=1, align=align)
        pdf.ln()
    pdf.set_text_color(30, 30, 35)


def build_pdf(symbol: str, out_path: Path, tables_dir: Path | None = None, figures_dir: Path | None = None):
    symbol = symbol.upper()
    fc, perf, bt, expl = _load(symbol)
    if not fc or not perf or not bt:
        raise FileNotFoundError(f"Chưa có dữ liệu đầy đủ cho {symbol}. Hãy chạy prepare_data / train.")

    short_rows = _load_table_rows("backtest_summary.csv", symbol, tables_dir)
    short_dm = _load_table_rows("backtest_dm_pinball.csv", symbol, tables_dir)
    nu_rows = _load_table_rows("backtest_nu.csv", symbol, tables_dir)
    long_rows = _load_table_rows("backtest_long_summary.csv", symbol, tables_dir)
    long_dm = _load_table_rows("backtest_long_dm_pinball.csv", symbol, tables_dir)
    fig_dir = figures_dir or FIGURES_DIR
    fig_path = fig_dir / f"backtest_{symbol}.png"

    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    if USE_DEJAVU:
        pdf.add_font(FONT_FAMILY, "", str(DEJA))
        pdf.add_font(FONT_FAMILY, "B", str(DEJA_B))
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    def mc(text, h=4, size=8, style="", color=(30, 30, 35)):
        pdf.set_font(FONT_FAMILY, style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(w=0, h=h, text=_sanitize(text), new_x="LMARGIN", new_y="NEXT")

    # Title
    pdf.set_font(FONT_FAMILY, "B", 16)
    pdf.set_text_color(15, 30, 55)
    pdf.cell(0, 9, f"Báo cáo phân tích & Backtest VaR/ES — {symbol}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY, "", 8.5)
    pdf.set_text_color(80, 90, 105)
    risk = fc.get("risk", {})
    nu_used = risk.get("t_df_train_only") or risk.get("t_df_used")
    nu_ref = risk.get("t_df_live")
    pdf.cell(
        0, 5.5,
        f"Kỳ hạn: 1 ngày  |  Vị thế tham chiếu: {risk.get('reference_position_usd', 10000):,.0f} USD  |  ν Student-t (chỉ train): {_fmt(nu_used, 2)}  |  Tạo lúc: {fc.get('generated_at_utc', '-')}",
        align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(2)
    mc(
        "Tài liệu này tổng hợp đầy đủ dự báo biến động, ước lượng rủi ro đuôi VaR/ES và bộ kiểm định học thuật ngoài mẫu (Kupiec, Christoffersen, Basel traffic-light, Acerbi–Székely ES-Z2, Diebold–Mariano trên Pinball Loss) trên cả tập test ngắn 4 mô hình lẫn mẫu dài rolling.",
        h=3.8, size=7.8, color=(90, 100, 115),
    )
    pdf.ln(3)

    # 1. Tổng quan dự báo biến động & trạng thái rủi ro
    _section_bar(pdf, "1. Tổng quan dự báo biến động & quy ước chống rò rỉ")
    regime = fc.get("regime", {})
    mc(
        f"• Mô hình đang chọn cho dự báo trực tiếp: {MODEL_LABELS.get(fc.get('selected_model'), fc.get('selected_model'))} (QLIKE OOS thấp nhất).\n"
        f"• Biến động dự báo 1 ngày (năm hóa): {_fmt(fc.get('forecast_vol_annualized_pct'), 2)}%  |  Thực tế gần nhất: {_fmt(fc.get('current_realized_vol_annualized_pct'), 2)}%  |  Phân vị: {_fmt(regime.get('percentile_vs_train'), 1)}% — Trạng thái: {regime.get('label_vi') or regime.get('label', '-')}.\n"
        f"• Giai đoạn huấn luyện: {fc.get('train_period', {}).get('start')} -> {fc.get('train_period', {}).get('end')} (n={fc.get('train_period', {}).get('n_train')}); Tập test OOS: {fc.get('test_period', {}).get('start')} -> {fc.get('test_period', {}).get('end')} (n={fc.get('test_period', {}).get('n_test')}).\n"
        f"• Thống nhất bậc tự do Student-t trên tập train: ν_train = {_fmt(nu_used, 2)}"
        + (f" (đối chiếu ν toàn mẫu nếu rò rỉ = {_fmt(nu_ref, 2)})." if _is_finite(nu_ref) else ".")
        + " Dùng một giá trị ν_train duy nhất xuyên suốt cả dự báo VaR/ES lẫn mọi bảng backtest để loại bỏ hoàn toàn rò rỉ dữ liệu kiểm định.",
        h=4.0, size=7.8,
    )
    pdf.ln(2)
    pdf.set_font(FONT_FAMILY, "B", 7.5)
    pdf.cell(50, 5, "Mô hình", border=1)
    pdf.cell(35, 5, "Vol năm hóa (%)", border=1, align="C")
    pdf.cell(105, 5, "Đặc trưng mô hình", border=1, align="C")
    pdf.ln()
    pdf.set_font(FONT_FAMILY, "", 7.3)
    for k in ["historical_22d", "garch_1_1", "har_rv", "xgboost"]:
        v = fc.get("models_vol_annualized_pct", {}).get(k)
        mark = " <- đang dùng" if k == fc.get("selected_model") else ""
        note = {
            "historical_22d": "Mốc cơ sở trung bình trượt RV 22 ngày (không tham số)",
            "garch_1_1": "Nắm cụm biến động & phần dư đuôi dày Student-t",
            "har_rv": "Đa chân trời (ngày / tuần / tháng) cho realized volatility",
            "xgboost": "Cây tăng cường trên log(RV) + hiệu chỉnh Duan smearing",
        }[k]
        pdf.cell(50, 5, _sanitize(f" {MODEL_LABELS.get(k, k)}{mark}"), border=1)
        pdf.cell(35, 5, _fmt(v, 2), border=1, align="C")
        pdf.cell(105, 5, _sanitize(note), border=1, align="L")
        pdf.ln()
    pdf.ln(3)

    # 2. Đánh giá ngoài mẫu biến động (MAE/RMSE/QLIKE)
    _section_bar(pdf, "2. Đánh giá dự báo biến động ngoài mẫu (MAE / RMSE / QLIKE)")
    mc(
        "Ba chỉ số đo sai số dự báo biến động trên tập test theo đúng thứ tự thời gian:\n"
        "• MAE & RMSE: đo sai số tuyệt đối và căn trung bình bình phương sai số (đối xứng).\n"
        "• QLIKE (Patton 2011): hàm mất mát bất đối xứng chuẩn mực cho phương sai nhiễu — phạt nặng hơn khi dự báo thấp hơn thực tế (nguy hiểm cho quản trị rủi ro). Mô hình có QLIKE thấp nhất được chọn tự động.",
        h=3.8, size=7.8,
    )
    pdf.ln(1.5)
    w2 = [45, 25, 25, 25, 25, 45]
    headers2 = ["Mô hình", "MAE (%)", "RMSE (%)", "QLIKE", "Số ngày OOS", "Xếp hạng"]
    pdf.set_font(FONT_FAMILY, "B", 7.3)
    for i, h in enumerate(headers2):
        pdf.cell(w2[i], 5, h, border=1, align="C")
    pdf.ln()
    metrics = perf.get("metrics", {})
    for k in ["historical_22d", "garch_1_1", "har_rv", "xgboost"]:
        m = metrics.get(k, {})
        is_best = k == perf.get("selected_model")
        pdf.set_font(FONT_FAMILY, "B" if is_best else "", 7.3)
        pdf.set_text_color(*(15, 70, 160) if is_best else (30, 30, 35))
        row = [
            MODEL_LABELS.get(k, k),
            _fmt(m.get("mae_vol", 0) * 100, 2),
            _fmt(m.get("rmse_vol", 0) * 100, 2),
            _fmt(m.get("qlike"), 3),
            str(m.get("n", "-")),
            "Tốt nhất theo QLIKE" if is_best else "-",
        ]
        for i, val in enumerate(row):
            pdf.cell(w2[i], 5, _sanitize(val), border=1, align="C")
        pdf.ln()
    pdf.set_text_color(30, 30, 35)
    pdf.ln(3)

    # 3. Backtest mở rộng 4 mô hình trên tập test ngắn (~142 ngày)
    _section_bar(pdf, "3. Báo cáo Backtest VaR/ES mở rộng — 4 mô hình trên cùng tập test ngắn")
    if short_rows:
        nu_info = nu_rows[0] if nu_rows else {}
        n_short = short_rows[0].get("n", "-")
        d_start = short_rows[0].get("từ_ngày") or nu_info.get("test_start") or fc.get("test_period", {}).get("start")
        d_end = short_rows[0].get("đến_ngày") or nu_info.get("test_end") or fc.get("test_period", {}).get("end")
        nu_tr_val = nu_info.get("nu_train_only(dùng)", nu_used)
        nu_all_val = nu_info.get("nu_toàn_mẫu(live_tham_chiếu)", nu_ref)

        mc(
            f"Thiết lập thực nghiệm: So sánh đồng thời 4 mô hình (Historical 22d, GARCH(1,1)-t, HAR-RV, XGBoost) trên cùng cửa sổ test {n_short} ngày ({d_start} -> {d_end}), VaR/ES 1 ngày ở mức 95% và 99%. "
            f"Bậc tự do Student-t chỉ ước lượng trên giai đoạn train (ν = {_fmt(nu_tr_val, 2)}"
            + (f", so với toàn mẫu {_fmt(nu_all_val, 2)}" if _is_finite(nu_all_val) else "")
            + ") để đảm bảo không rò rỉ thông tin từ tập kiểm định.",
            h=3.8, size=7.7,
        )
        pdf.ln(1.5)
        _render_ext_backtest_table(pdf, short_rows)
        pdf.ln(2)

        if short_dm:
            mc("Kiểm định Diebold–Mariano trên Pinball Loss so với mốc cơ sở Historical 22d (DM < 0 là sai số thấp hơn benchmark):",
               h=3.8, size=7.6, style="B")
            pdf.ln(1)
            _render_dm_table(pdf, short_dm, "Historical 22d")
            pdf.ln(2)

        # Tổng hợp tự động 4 luận điểm cốt lõi (tương ứng Kết quả 1–4 của báo cáo học thuật)
        r95 = [r for r in short_rows if str(r.get("mức_tin_cậy")) == "95%"]
        r99 = [r for r in short_rows if str(r.get("mức_tin_cậy")) == "99%"]
        kup_vals = [float(r["kupiec_p"]) for r in short_rows if _is_finite(r.get("kupiec_p"))]
        z2_vals = [float(r["ES_Z2_p"]) for r in short_rows if _is_finite(r.get("ES_Z2_p"))]
        basels = sorted({str(r.get("Basel")) for r in r99 if r.get("Basel")})
        dates99 = []
        for r in r99:
            if r.get("ngày_vi_phạm"):
                for d_item in str(r["ngày_vi_phạm"]).split(","):
                    ds = d_item.strip()
                    if ds and ds not in dates99:
                        dates99.append(ds)
        zero99_models = [MODEL_LABELS.get(str(r["model"]), str(r["model"])) for r in r99 if r.get("vi_phạm") == 0]
        es_pairs_95 = [
            f"{MODEL_LABELS.get(str(r['model']), str(r['model']))}: ES {float(r['ES_dự_báo_trung_bình_%_ngày_vi_phạm']):.2f}% vs lỗ thực {float(r['lỗ_thực_tế_trung_bình_%_ngày_vi_phạm']):.2f}%"
            for r in r95
            if _is_finite(r.get("ES_dự_báo_trung_bình_%_ngày_vi_phạm")) and _is_finite(r.get("lỗ_thực_tế_trung_bình_%_ngày_vi_phạm"))
        ]
        sig_dm = [
            f"{MODEL_LABELS.get(str(r['model']), str(r['model']))} ({r['mức_tin_cậy']}: DM={float(r['DM_stat']):.2f}, p={float(r['p_value']):.3f})"
            for r in short_dm
            if _is_finite(r.get("p_value")) and _is_finite(r.get("DM_stat")) and float(r["p_value"]) < 0.05 and float(r["DM_stat"]) < 0
        ]

        mc(
            f"Nhận xét kết quả trên {symbol}:\n"
            f"1) Độ bao phủ & đèn Basel: Kupiec p dao động từ {_fmt(min(kup_vals) if kup_vals else None, 3)} đến {_fmt(max(kup_vals) if kup_vals else None, 3)}; vùng đèn Basel 99%: {', '.join(basels) if basels else '-'}; kiểm định ES (Z2) có p từ {_fmt(min(z2_vals) if z2_vals else None, 3)} đến {_fmt(max(z2_vals) if z2_vals else None, 3)}.\n"
            f"2) So với benchmark Historical 22d (Diebold–Mariano trên Pinball Loss): "
            + (f"Mô hình vượt trội có ý nghĩa thống kê (p < 0.05): {', '.join(sig_dm)}." if sig_dm
               else "Không mô hình nào vượt khác biệt có ý nghĩa thống kê ở mức 5% trên cửa sổ ngắn này.")
            + "\n"
            f"3) Các ngày vi phạm VaR99: "
            + (f"Rơi vào ngày {', '.join(dates99)}." if dates99 else "Không có ngày nào vượt ngưỡng VaR99 trong kỳ kiểm tra.")
            + (f" Mô hình có 0 lần vi phạm VaR99: {', '.join(zero99_models)}." if zero99_models else "")
            + "\n"
            f"4) Trả lời câu hỏi độ sát của ES khi vượt VaR: "
            + ("; ".join(es_pairs_95) + "." if es_pairs_95 else "Không có ngày vi phạm VaR95 để tính trung bình lỗ vượt ngưỡng."),
            h=3.8, size=7.5,
        )
        pdf.ln(2)

        if fig_path.exists():
            _ensure_space(pdf, 116)
            mc(f"Biểu đồ đối chiếu VaR 95% & 99% của 4 mô hình so với tổn thất thực tế ({symbol}):", h=3.8, size=7.5, style="B")
            pdf.image(str(fig_path), x=14, w=182)
            pdf.ln(2)
    else:
        # Fallback khi chưa chạy run_backtest.py
        s95 = bt.get("summary_95", {})
        s99 = bt.get("summary_99", {})
        mc(
            f"Kiểm định đơn mô hình ({symbol}, n={s95.get('n', '-')}): VaR95 vượt {s95.get('breaches', '-')} lần (Kupiec p={_fmt((s95.get('kupiec') or {}).get('p_value'), 3)}); "
            f"VaR99 vượt {s99.get('breaches', '-')} lần (Kupiec p={_fmt((s99.get('kupiec') or {}).get('p_value'), 3)}).",
            h=3.8, size=7.8,
        )
        pdf.ln(2)

    # 4. Phần phụ: Mẫu dài rolling & hạn chế / đề xuất học thuật
    _section_bar(pdf, "4. Phần phụ — Mẫu dài rolling, đối chứng đuôi dày & Hạn chế cỡ mẫu")
    if long_rows:
        l0 = long_rows[0]
        n_long = l0.get("n", "-")
        l_start = l0.get("từ_ngày", "-")
        l_end = l0.get("đến_ngày", "-")
        l_win = l0.get("cửa_sổ_train", 1000)
        l_src = l0.get("nguồn_dữ_liệu", "chuỗi lịch sử ngày")
        mc(
            f"Kiểm định mẫu dài trên {symbol}: {n_long} ngày OOS ({l_start} -> {l_end}, nguồn: {l_src}, cửa sổ trượt {l_win} ngày, chỉ dùng dữ liệu <= t-1 cho ngày t). "
            f"Đặt cạnh nhau GARCH-t rolling, EWMA-t, Historical 22d-t và đối chứng GARCH-chuẩn (đuôi mỏng):",
            h=3.8, size=7.7,
        )
        pdf.ln(1.5)
        _render_ext_backtest_table(pdf, long_rows)
        pdf.ln(2)

        if long_dm:
            mc("Diebold–Mariano trên Pinball Loss (mẫu dài) so với Historical 22d-t:", h=3.8, size=7.6, style="B")
            pdf.ln(1)
            _render_dm_table(pdf, long_dm, "Historical 22d-t")
            pdf.ln(2)

        gt95 = next((r for r in long_rows if r.get("model") == "GARCH-t (rolling)" and r.get("mức_tin_cậy") == "95%"), None)
        gt99 = next((r for r in long_rows if r.get("model") == "GARCH-t (rolling)" and r.get("mức_tin_cậy") == "99%"), None)
        gn95 = next((r for r in long_rows if r.get("model") == "GARCH-chuẩn (đối chứng đuôi mỏng)" and r.get("mức_tin_cậy") == "95%"), None)
        gn99 = next((r for r in long_rows if r.get("model") == "GARCH-chuẩn (đối chứng đuôi mỏng)" and r.get("mức_tin_cậy") == "99%"), None)
        if gt95 and gt99 and gn95 and gn99:
            mc(
                f"Đối chứng đuôi dày Student-t vs phân phối chuẩn trên {symbol} ({n_long} ngày):\n"
                f"• GARCH-t (rolling): vượt {gt95.get('vi_phạm')}/{gt99.get('vi_phạm')} lần ở 95%/99% (kỳ vọng {_fmt(gt95.get('kỳ_vọng'), 1)}/{_fmt(gt99.get('kỳ_vọng'), 1)}), "
                f"Kupiec p = {_fmt(gt95.get('kupiec_p'), 3)} / {_fmt(gt99.get('kupiec_p'), 3)}, ES99 dự báo {_fmt(gt99.get('ES_dự_báo_trung_bình_%_ngày_vi_phạm'), 2)}% so với lỗ thực {_fmt(gt99.get('lỗ_thực_tế_trung_bình_%_ngày_vi_phạm'), 2)}% (Z2 p = {_fmt(gt99.get('ES_Z2_p'), 3)}, Basel {gt99.get('Basel')}).\n"
                f"• GARCH-chuẩn (đuôi mỏng): ở VaR95 vượt {gn95.get('vi_phạm')} lần (Kupiec p = {_fmt(gn95.get('kupiec_p'), 4)}), nhưng ở đuôi cực đoan ES99 chỉ dự báo {_fmt(gn99.get('ES_dự_báo_trung_bình_%_ngày_vi_phạm'), 2)}% so với lỗ thực {_fmt(gn99.get('lỗ_thực_tế_trung_bình_%_ngày_vi_phạm'), 2)}% (Z2 = {_fmt(gn99.get('ES_Z2'), 3)}, p = {_fmt(gn99.get('ES_Z2_p'), 3)}) -> ủng hộ rõ rệt việc dùng phân phối đuôi dày Student-t.",
                h=3.8, size=7.5,
            )
            pdf.ln(1.5)

    mc(
        "Hạn chế thống kê & Thực hành chuẩn đã áp dụng:\n"
        "• Hạn chế cỡ mẫu tập ngắn (~142 ngày): ở mức VaR99 chỉ kỳ vọng ~1,4 lần vượt ngưỡng, nên kết luận 'không bác bỏ' trên 142 ngày là bằng chứng thống kê yếu; kiểm định độc lập Christoffersen buộc để trống / gắn nhãn thiếu dữ liệu khi dưới 5 lần vi phạm (tránh p-value ~ 1 giả tạo).\n"
        "• Giải pháp đã chuẩn hóa trong hệ thống: (1) Thống nhất dùng duy nhất ν ước lượng trên tập train cho mọi tab và mọi kiểm định; (2) Ghi rõ cảnh báo sức mạnh kiểm định của mẫu 142 ngày; (3) Mở rộng kiểm định mẫu dài rolling cho toàn bộ 35 tài sản để có đủ độ tin cậy ở mức 99%.",
        h=3.8, size=7.5, color=(55, 60, 70),
    )
    pdf.ln(3)

    # 5. Ba phương pháp VaR/ES cho ngày kế tiếp
    _section_bar(pdf, "5. Ba phương pháp ước lượng VaR/ES 1 ngày trên Dashboard")
    for meth, label, desc in [
        ("forecast_based", "Theo dự báo (σ̂ × Student-t trên tập train)", "phương pháp chính — biến động dự báo nhân phân vị Student-t chuẩn hóa với ν_train"),
        ("historical_simulation", "Mô phỏng lịch sử (250 ngày gần nhất)", "không áp đặt phân phối tham số, phản ánh trực tiếp các cú sốc đã xảy ra"),
        ("parametric_student_t", "Student-t tham số (ước lượng trên tập train)", "phân phối đuôi dày không điều kiện ước lượng trên tập huấn luyện"),
    ]:
        r = risk.get(meth, {})
        pdf.set_font(FONT_FAMILY, "B", 7.8)
        pdf.set_text_color(20, 45, 90)
        pdf.cell(0, 4.8, _sanitize(label), new_x="LMARGIN", new_y="NEXT")
        mc(
            f"  VaR95 = {_fmt(r.get('var_95'), 0)} USD ({_fmt(r.get('var_95_pct'), 2)}%), ES95 = {_fmt(r.get('es_95'), 0)} USD ({_fmt(r.get('es_95_pct'), 2)}%); "
            f"VaR99 = {_fmt(r.get('var_99'), 0)} USD ({_fmt(r.get('var_99_pct'), 2)}%), ES99 = {_fmt(r.get('es_99'), 0)} USD ({_fmt(r.get('es_99_pct'), 2)}%). Lý thuyết: {desc}.",
            h=3.7, size=7.6,
        )
        pdf.ln(0.8)
    pdf.ln(2)

    # 6. Biến quan trọng, giới hạn & tài liệu tham khảo
    _section_bar(pdf, "6. Biến quan trọng, giới hạn mô hình & Tài liệu tham khảo")
    fi = expl.get("feature_importance", []) if expl else []
    if fi:
        top = sorted(fi, key=lambda x: x.get("share", 0), reverse=True)[:5]
        mc("Top biến quan trọng của XGBoost (permutation importance trên tập test — không phải quan hệ nhân quả):", h=3.7, size=7.6, style="B")
        for it in top:
            mc(
                f"  • {it.get('feature')}: {_fmt(it.get('share', 0) * 100, 1)}% — {expl.get('feature_schema', {}).get(it.get('feature'), '')}",
                h=3.5, size=7.4,
            )
        pdf.ln(1)

    refs = [
        "Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. J. Econometrics.",
        "Corsi, F. (2009). A simple approximate long-memory model of realized volatility. J. Financial Econometrics.",
        "Patton, A. (2011). Volatility forecast comparison using imperfect volatility proxies. J. Econometrics.",
        "Kupiec, P. (1995). Techniques for verifying the accuracy of risk measurement models. J. Derivatives.",
        "Christoffersen, P. (1998). Evaluating interval forecasts. Int. Economic Review.",
        "Acerbi, C. & Székely, B. (2014). Backtesting Expected Shortfall. Risk Magazine.",
        "Diebold, F. X. & Mariano, R. (1995). Comparing predictive accuracy. J. Business & Economic Statistics.",
        "Duan, N. (1983). Smearing estimate: A nonparametric retransformation method. JASA.",
        "Artzner et al. (1999). Coherent measures of risk. Mathematical Finance.",
    ]
    mc("Tài liệu tham khảo chọn lọc:", h=3.7, size=7.6, style="B")
    for r_txt in refs:
        mc(f"  • {r_txt}", h=3.3, size=6.9, color=(55, 60, 70))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
