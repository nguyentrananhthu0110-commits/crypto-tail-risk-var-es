"""Báo cáo PDF chuyên sâu — dựa trên artifacts đã tính."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from src.config import MODEL_META_DIR
from fpdf import FPDF

# Font có dấu tiếng Việt: ưu tiên font kèm theo dự án, fallback sang hệ thống
PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
}
MODEL_THEORY = {
    "historical_22d": "Mốc so sánh đơn giản nhất (naïve benchmark): trung bình phương sai thực hiện 22 ngày. Không tham số; đại diện kỳ vọng ‘biến động sẽ giống trung bình tháng qua’. Dùng để kiểm tra mô hình phức tạp có thực sự hơn trung bình đơn giản hay không.",
    "garch_1_1": "GARCH(1,1)-t (Bollerslev 1986): σ²ₜ = ω + α·ε²ₜ₋₁ + β·σ²ₜ₋₁, phần dư Student-t. Nắm bắt cụm biến động và đuôi dày. Tham số α đo phản ứng cú sốc, β đo tính bền.",
    "har_rv": "HAR-RV (Corsi 2009): RVₜ₊₁ = β₀ + βᴅ·RVₜ + βᵂ·RV̄⁵ + βᴹ·RV̄²². Mô phỏng hành vi đa chân trời; chuẩn học thuật cho realized volatility.",
    "xgboost": "XGBoost (Chen & Guestrin 2016): cây tăng cường trên lag RV, lợi suất, biên độ, khối lượng, RV chéo. Bắt phi tuyến & tương tác; rủi ro overfit kiểm soát bằng đánh giá OOS nghiêm ngặt.",
}

def _sanitize(s: str) -> str:
    # Giữ nguyên tiếng Việt có dấu - DejaVu hỗ trợ Unicode
    if not isinstance(s, str):
        s = str(s)
    s = s.replace(""","\"").replace(""","\"").replace("’","'").replace("‘","'")
    return s

def _fmt(v, d=4):
    if v is None:
        return "-"
    try:
        return f"{float(v):.{d}f}"
    except:
        return _sanitize(str(v))

def _load(symbol: str):
    base = MODEL_META_DIR
    def load(name):
        p = base / f"{symbol}_{name}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except:
            return None
    return load("forecast"), load("performance"), load("backtest"), load("explain")

class PDF(FPDF):
    def header(self):
        self.set_font(FONT_FAMILY, "B", 8)
        self.set_text_color(100,100,120)
        self.cell(0,6,"Crypto Risk Intelligence — Báo cáo phân tích chuyên sâu", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200,210,220)
        self.line(10,self.get_y(),200,self.get_y())
        self.ln(2)
    def footer(self):
        self.set_y(-15)
        self.set_font(FONT_FAMILY,"",7)
        self.set_text_color(130,130,130)
        self.cell(0,10,f"Trang {self.page_no()}/{{nb}} — Tạo lúc {datetime.now(timezone.utc).isoformat()} — Không phải khuyến nghị đầu tư", align="C")

def build_pdf(symbol: str, out_path: Path):
    symbol = symbol.upper()
    fc, perf, bt, expl = _load(symbol)
    if not fc or not perf or not bt:
        raise FileNotFoundError(f"Chưa có dữ liệu đầy đủ cho {symbol}. Hãy chạy prepare_data / train.")
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    if USE_DEJAVU:
        pdf.add_font(FONT_FAMILY, "", str(DEJA))
        pdf.add_font(FONT_FAMILY, "B", str(DEJA_B))
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    def mc(text, h=4, size=8, style="", color=(30,30,35)):
        pdf.set_font(FONT_FAMILY, style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(w=0, h=h, text=_sanitize(text), new_x="LMARGIN", new_y="NEXT")

    # Title
    pdf.set_font(FONT_FAMILY,"B",18)
    pdf.set_text_color(15,30,55)
    pdf.cell(0,10,f"Báo cáo chuyên sâu — {symbol}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY,"",9)
    pdf.set_text_color(80,90,105)
    pdf.cell(0,6,f"Kỳ hạn dự báo: 1 ngày  |  Vị thế tham chiếu: {fc.get('risk',{}).get('reference_position_usd',10000):,.0f} USD  |  Tạo lúc: {fc.get('generated_at_utc','-')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    mc("Tài liệu này giải thích TẠI SAO các chỉ số trên dashboard lại ra như vậy và HIỆU ỨNG kinh tế/rủi ro của chúng, dựa trên lý thuyết tài chính định lượng. Các con số lấy trực tiếp từ file forecast/performance/backtest đã lưu.", h=4, size=8, color=(100,110,120))
    pdf.ln(4)

    # 1
    pdf.set_font(FONT_FAMILY,"B",11); pdf.set_text_color(20,45,90); pdf.set_fill_color(235,240,248)
    pdf.cell(0,7," 1. Tổng quan dự báo biến động & trạng thái rủi ro", fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    regime = fc.get("regime",{})
    mc(f"• Mô hình được chọn: {MODEL_LABELS.get(fc.get('selected_model'), fc.get('selected_model'))} (QLIKE OOS thấp nhất).\n• Biến động dự báo 1 ngày (năm hóa): {_fmt(fc.get('forecast_vol_annualized_pct'),2)}%  |  Thực tế gần nhất: {_fmt(fc.get('current_realized_vol_annualized_pct'),2)}%  |  Phân vị: {_fmt(regime.get('percentile_vs_train'),1)}% — Trạng thái: {regime.get('label_vi') or regime.get('label','-')}.\n• Giai đoạn huấn luyện: {fc.get('train_period',{}).get('start')} → {fc.get('train_period',{}).get('end')} (n={fc.get('train_period',{}).get('n_train')}); Test: {fc.get('test_period',{}).get('start')} → {fc.get('test_period',{}).get('end')} (n={fc.get('test_period',{}).get('n_test')}).\n• Biến động dự báo đo quy mô dao động kỳ vọng, KHÔNG dự báo hướng giá. Hiệu ứng: biến động cao ⇒ VaR/ES giãn ra ⇒ cần đệm vốn lớn hơn.", h=4.2, size=8)
    pdf.ln(2)
    pdf.set_font(FONT_FAMILY,"B",8)
    pdf.cell(45,5,"Mô hình", border=1); pdf.cell(30,5,"Vol năm hóa (%)", border=1, align="C"); pdf.cell(40,5,"Lợi ích lý thuyết", border=1, align="C"); pdf.ln()
    pdf.set_font(FONT_FAMILY,"",7.5)
    for k in ["historical_22d","garch_1_1","har_rv","xgboost"]:
        v = fc.get("models_vol_annualized_pct",{}).get(k)
        mark = " ← đang dùng" if k==fc.get("selected_model") else ""
        pdf.cell(45,5,_sanitize(f" {MODEL_LABELS.get(k,k)}{mark}"), border=1)
        pdf.cell(30,5,_fmt(v,2), border=1, align="C")
        note = {"historical_22d":"Naive MA","garch_1_1":"Cụm biến động","har_rv":"Đa chân trời","xgboost":"Phi tuyến"}[k]
        pdf.cell(40,5,note, border=1, align="C"); pdf.ln()
    pdf.ln(3)
    mc("Lý thuyết: Phân vị rủi ro xác định bằng q25/q75/q90 của realized vol trong tập huấn luyện (Andersen & Bollerslev). Cùng mức vol có thể là ‘cao’ trong thị trường yên ắng nhưng ‘bình thường’ sau khủng hoảng — phân vị chuẩn hoá theo lịch sử.", h=3.5, size=7, color=(90,90,95))
    pdf.ln(4)

    # 2
    pdf.set_font(FONT_FAMILY,"B",11); pdf.set_text_color(20,45,90); pdf.set_fill_color(235,240,248)
    pdf.cell(0,7," 2. Đánh giá ngoài mẫu — Tại sao MAE/RMSE/QLIKE lại như vậy", fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    mc("Ba chỉ số đo sai số dự báo biến động trên tập test THEO THỨ TỰ THỜI GIAN (không xáo trộn, tránh rò rỉ):\n• MAE = trung bình |dự báo − thực tế| (vol). Càng thấp càng tốt.\n• RMSE = √(trung bình bình phương sai số). Phạt nặng sai số lớn hơn MAE — dùng phát hiện mô hình lệch mạnh khi biến động đột ngột.\n• QLIKE (Patton, 2011): QLIKE = σ̂²/σ² − log(σ̂²/σ²) − 1. Robust cho biến động: bảo toàn thứ tự xếp hạng mô hình dưới realized variance nhiễu và nhạy hơn khi dự báo thấp hơn thực tế (nguy hiểm cho rủi ro). Vì vậy QLIKE thấp nhất = tiêu chí chọn mô hình chính.", h=4, size=8)
    pdf.ln(2)
    pdf.set_font(FONT_FAMILY,"B",7.5)
    w=[40,25,25,25,25,50]
    headers=["Mô hình","MAE (%)","RMSE (%)","QLIKE","Số quan sát","Ghi chú"]
    for i,h in enumerate(headers): pdf.cell(w[i],5,h, border=1, align="C")
    pdf.ln()
    metrics = perf.get("metrics",{})
    for k in ["historical_22d","garch_1_1","har_rv","xgboost"]:
        m=metrics.get(k,{})
        is_best = k==perf.get("selected_model")
        pdf.set_font(FONT_FAMILY,"B" if is_best else "",7.5)
        if is_best: pdf.set_text_color(15,70,160)
        else: pdf.set_text_color(30,30,35)
        row=[MODEL_LABELS.get(k,k), _fmt(m.get("mae_vol",0)*100,2), _fmt(m.get("rmse_vol",0)*100,2), _fmt(m.get("qlike"),3), str(m.get("n","-")), "Tốt nhất theo QLIKE" if is_best else "-"]
        for i,val in enumerate(row): pdf.cell(w[i],5,_sanitize(val), border=1, align="C")
        pdf.ln()
    pdf.set_text_color(30,30,35); pdf.ln(1)
    best = perf.get("selected_model"); best_m = metrics.get(best,{})
    mc(f"Giải thích cụ thể cho {symbol}: Mô hình {MODEL_LABELS.get(best,best)} có QLIKE = {_fmt(best_m.get('qlike'),3)} thấp nhất trong 4 ứng viên, dù MAE ({_fmt(best_m.get('mae_vol',0)*100,2)}%) và RMSE ({_fmt(best_m.get('rmse_vol',0)*100,2)}%) không phải lúc nào cũng nhỏ nhất. Điều này phù hợp lý thuyết: RMSE/MAE đối xứng, còn QLIKE bất đối xứng — phạt mạnh hơn khi dự báo thấp hơn thực tế (nguy hiểm cho rủi ro). Về kinh tế, chọn QLIKE tốt nhất ⇒ VaR/ES ít bị đánh giá thiếu hơn.\nThêm: Kiểm định Diebold–Mariano (Diebold & Mariano 1995; Harvey–Leybourne–Newbold) so sánh tổn thất bình phương giữa best vs từng mô hình còn lại. Nếu p < 0.05, khác biệt dự báo có ý nghĩa thống kê.", h=3.8, size=7.5)
    pdf.ln(2)
    pdf.set_font(FONT_FAMILY,"",7); pdf.set_text_color(80,80,85)
    for k in ["historical_22d","garch_1_1","har_rv","xgboost"]:
        mc(f"• {MODEL_LABELS.get(k,k)}: {MODEL_THEORY[k]}", h=3.3, size=7, color=(80,80,85))
        pdf.ln(1)
    pdf.ln(1)
    mc("Hiệu ứng quản trị rủi ro: Mô hình QLIKE thấp ⇒ biến động dự báo sát thực tế hơn ⇒ VaR/ES tin cậy hơn ⇒ vị thế quản trị rủi ro ổn định hơn. Ngược lại, dùng QLIKE cao để tính VaR sẽ thiếu/thừa rủi ro.", h=3.8, size=8)
    pdf.ln(4)

    # 3
    pdf.set_font(FONT_FAMILY,"B",11); pdf.set_text_color(20,45,90); pdf.set_fill_color(235,240,248)
    pdf.cell(0,7," 3. Kiểm định VaR/ES — Tại sao số vi phạm & p-value lại quan trọng", fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    mc("Khung kiểm định ngoài mẫu (rolling, 1 ngày): So sánh tổn thất thực tế Lossₜ = −rₜ × Vị_thế với VaR dự báo. Vi phạm = Lossₜ > VaR.\n• Kupiec UC (Kupiec 1995): kiểm tra tỷ lệ vi phạm có khớp kỳ vọng (5% cho VaR95, 1% cho VaR99) hay không. Thống kê LRᵤc ∼ χ²(1). p lớn ⇒ không bác bỏ ⇒ tỷ lệ đúng.\n• Christoffersen CC (1998): mở rộng Kupiec bằng kiểm tra độc lập (vi phạm có cụm hay không) + bao phủ có điều kiện. Vi phạm cụm ⇒ rủi ro hệ thống.\n• Khung Basel traffic-light: <4 vi phạm/năm (250 ngày, 99%) = xanh; 4–9 = vàng; ≥10 = đỏ.", h=4, size=8)
    pdf.ln(2)
    s95 = bt.get("summary_95",{}); s99 = bt.get("summary_99",{})
    pdf.set_font(FONT_FAMILY,"B",7.5)
    pdf.cell(50,5,"Chỉ tiêu", border=1); pdf.cell(35,5,"VaR 95% (kỳ vọng 5%)", border=1, align="C"); pdf.cell(35,5,"VaR 99% (kỳ vọng 1%)", border=1, align="C"); pdf.cell(70,5,"Diễn giải lý thuyết", border=1, align="C"); pdf.ln()
    pdf.set_font(FONT_FAMILY,"",7.5)
    rows=[
        ("Số ngày kiểm tra", str(s95.get("n","-")), str(s99.get("n","-")), "Cửa sổ OOS"),
        ("Số lần vi phạm", f"{s95.get('breaches','-')} ({_fmt(s95.get('breach_rate',0)*100,2)}%)", f"{s99.get('breaches','-')} ({_fmt(s99.get('breach_rate',0)*100,2)}%)", "So sánh thực tế vs kỳ vọng"),
        ("Kupiec p", _fmt(s95.get("kupiec",{}).get("p_value"),3), _fmt(s99.get("kupiec",{}).get("p_value"),3), "p>0.05 ⇒ không bác bỏ UC"),
        ("Christoffersen p", _fmt((s95.get("christoffersen") or {}).get("p_value_conditional_coverage") or (s95.get("christoffersen") or {}).get("p_value"),3) if isinstance(s95.get("christoffersen"),dict) else "-", _fmt((s99.get("christoffersen") or {}).get("p_value_conditional_coverage") or (s99.get("christoffersen") or {}).get("p_value"),3) if isinstance(s99.get("christoffersen"),dict) else "Không đủ dữ liệu", "p>0.05 ⇒ không cụm"),
        ("Tỷ lệ kỳ vọng", "5%", "1%", "Mức ý nghĩa Basel"),
    ]
    for a,b,c,d in rows:
        pdf.cell(50,5,_sanitize(a), border=1); pdf.cell(35,5,b, border=1, align="C"); pdf.cell(35,5,c, border=1, align="C"); pdf.cell(70,5,_sanitize(d), border=1, align="C"); pdf.ln()
    pdf.ln(2)
    n = s95.get("n"); breaches95 = s95.get("breaches"); br95 = s95.get("breach_rate",0)*100 if s95.get("breach_rate") else None
    kup95 = (s95.get("kupiec") or {}).get("p_value"); cc95 = (s95.get("christoffersen") or {}).get("p_value_conditional_coverage") or (s95.get("christoffersen") or {}).get("p_value")
    mc(f"Giải thích cụ thể cho {symbol}: Trong {n} ngày kiểm tra, VaR95 bị vượt {breaches95} lần ({_fmt(br95,2)}% so với kỳ vọng 5%). Kupiec p = {_fmt(kup95,3)} ⇒ {'không bác bỏ giả thuyết tỷ lệ đúng' if (kup95 or 0)>0.05 else 'bác bỏ UC — mô hình đánh giá thiếu/thừa rủi ro'}. Christoffersen p = {_fmt(cc95,3) if cc95 else 'không đủ dữ liệu'} ⇒ {'vi phạm không cụm' if (cc95 or 0)>0.05 else ('có dấu hiệu cụm' if cc95 else 'không đủ dữ liệu')} . VaR99: {s99.get('breaches','-')} vi phạm ({_fmt(s99.get('breach_rate',0)*100,2)}% so với 1% kỳ vọng), Kupiec p = {_fmt((s99.get('kupiec') or {}).get('p_value'),3)}.\nHiệu ứng: Nếu tỷ lệ thực tế cao hơn kỳ vọng nhiều hoặc p nhỏ, ngưỡng VaR đánh giá thiếu rủi ro ⇒ cần nắm giữ bảo vệ lớn hơn hoặc giảm vị thế. Nếu cụm, rủi ro tập trung theo cụm khủng hoảng — cần mô hình chế độ.", h=3.8, size=7.5)
    pdf.ln(2)
    mc("Chi tiết đường cong: Biểu đồ breach timeline (dashboard) vẽ Lossₜ (xám) vs VaR95 (xanh) vs VaR99 (vàng); chấm đỏ = ngày vi phạm. Cụm chấm đỏ liên tiếp ⇒ dấu hiệu cụm.", h=3.5, size=7, color=(80,80,85))
    pdf.ln(4)

    # 4
    pdf.set_font(FONT_FAMILY,"B",11); pdf.set_text_color(20,45,90); pdf.set_fill_color(235,240,248)
    pdf.cell(0,7," 4. Ba phương pháp VaR/ES — Tại sao số lại khác nhau", fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    risk = fc.get("risk",{})
    for meth, label in [("forecast_based","Theo dự báo (σ̂ × Student-t)"),("historical_simulation","Mô phỏng lịch sử (250 ngày)"),("parametric_student_t","Student-t tham số toàn lịch sử")]:
        r = risk.get(meth,{})
        pdf.set_font(FONT_FAMILY,"B",8); pdf.set_text_color(20,45,90)
        pdf.cell(0,5,_sanitize(label), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FONT_FAMILY,"",8); pdf.set_text_color(30,30,35)
        mc(f"  VaR95={_fmt(r.get('var_95'),0)} USD ({_fmt(r.get('var_95_pct'),2)}%), ES95={_fmt(r.get('es_95'),0)} USD; VaR99={_fmt(r.get('var_99'),0)} USD, ES99={_fmt(r.get('es_99'),0)} USD. Lý thuyết: { {'forecast_based':'phương pháp chính — biến động dự báo nhân quantile Student-t','historical_simulation':'không áp đặt phân phối, phản ánh khung biến thực tế','parametric_student_t':'đuôi dày hơn chuẩn, ES > VaR rõ rệt'}[meth]}.", h=3.8, size=8)
        pdf.ln(1)
    pdf.ln(1)
    mc("Quy ước: LOSS = −simple_return × vị_thế (số dương = lỗ). Chân trời = 1 ngày. VaR là ngưỡng, ES là lỗ trung bình khi vượt ngưỡng (Artzner et al. coherent measure).", h=3.8, size=7.5)
    pdf.ln(4)

    # 5
    pdf.set_font(FONT_FAMILY,"B",11); pdf.set_text_color(20,45,90); pdf.set_fill_color(235,240,248)
    pdf.cell(0,7," 5. Biến quan trọng & giới hạn mô hình", fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    fi = expl.get("feature_importance",[]) if expl else []
    if fi:
        top = sorted(fi, key=lambda x: x.get("share",0), reverse=True)[:6]
        mc("Mức độ quan trọng biến (permutation importance — tăng RMSE khi xáo trộn feature, không phải nhân quả):", h=3.8, size=8)
        for it in top:
            pdf.cell(0,4,_sanitize(f"  • {it.get('feature')}: {_fmt(it.get('share',0)*100,1)}% — {expl.get('feature_schema',{}).get(it.get('feature'),'')}" ), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    wrong = fc.get("interpretation",{}).get("what_could_be_wrong",[]); lims = fc.get("limitations",[])
    pdf.set_font(FONT_FAMILY,"B",8); pdf.set_text_color(20,45,90); pdf.cell(0,5,"Điều gì có thể làm kết quả sai?", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY,"",7.5); pdf.set_text_color(30,30,35)
    for w in wrong[:5]: mc(f"  • {w}", h=3.5, size=7.5)
    pdf.ln(1)
    pdf.set_font(FONT_FAMILY,"B",8); pdf.set_text_color(20,45,90); pdf.cell(0,5,"Giới hạn đã biết", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT_FAMILY,"",7.5); pdf.set_text_color(30,30,35)
    for l in lims[:5]: mc(f"  • {l}", h=3.5, size=7.5)
    pdf.ln(4)

    pdf.set_font(FONT_FAMILY,"B",11); pdf.set_text_color(20,45,90); pdf.set_fill_color(235,240,248)
    pdf.cell(0,7," 6. Tài liệu tham khảo (chọn lọc)", fill=True, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    pdf.set_font(FONT_FAMILY,"",7); pdf.set_text_color(40,40,45)
    refs=[
        "Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. J. Econometrics.",
        "Corsi, F. (2009). A simple approximate long-memory model of realized volatility. J. Financial Econometrics.",
        "Patton, A. (2011). Volatility forecast comparison using imperfect volatility proxies. J. Econometrics.",
        "Diebold, F. X. & Mariano, R. (1995). Comparing predictive accuracy. J. Business & Economic Statistics.",
        "Harvey, Leybourne, Newbold (1997). Testing the equality of prediction mean squared errors.",
        "Kupiec, P. (1995). Techniques for verifying the accuracy of risk measurement models. J. Derivatives.",
        "Christoffersen, P. (1998). Evaluating interval forecasts. Int. Economic Review.",
        "Artzner et al. (1999). Coherent measures of risk. Mathematical Finance.",
        "Chen & Guestrin (2016). XGBoost: A scalable tree boosting system. KDD.",
    ]
    for r in refs: mc(f"  • {r}", h=3.3, size=7)
    pdf.ln(4)
    mc("Lưu ý: Báo cáo được sinh tự động từ dữ liệu đã lưu; không phải khuyến nghị đầu tư. Để tái tạo: chạy scripts/prepare_data.py và src/models/training.py, hoặc nút ‘Nạp dữ liệu & huấn luyện’ trong dashboard.", h=3.3, size=7, color=(110,110,115))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
