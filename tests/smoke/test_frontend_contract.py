"""Mục 10/11/15D (kiểm tra hợp đồng tĩnh, không cần trình duyệt):
- Mọi id mà app.js truy cập đều tồn tại trong index.html.
- Tầng Advanced dùng <details> đóng mặc định; thuật ngữ có tooltip '?'.
- Có retry/tiến độ tác vụ nền/ghi nhớ bộ lọc; dữ liệu stale có banner riêng.
Kiểm tra trình duyệt thật (Playwright) được ghi trong verification_report."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/style.css").read_text(encoding="utf-8")

def test_every_js_id_exists_in_html():
    ids = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', JS))
    missing = [i for i in sorted(ids) if f'id="{i}"' not in HTML and f"id='{i}'" not in HTML]
    # canvas ids trong setupCanvas dùng tham số, không nằm trong tập này
    assert missing == [], f"Thiếu element cho id: {missing}"

def test_advanced_details_collapsed_by_default_and_tips_present():
    assert '<details open>' not in HTML
    assert "Chi tiết nâng cao" in HTML
    for tip in ("vol", "fvol", "var", "es", "qlike", "breach", "rv", "oos"):
        assert f'data-tip="{tip}"' in HTML, f"thiếu tooltip cho {tip}"
        assert f"{tip}:" in JS or f'"{tip}"' in JS

def test_retry_progress_and_persisted_filters():
    assert 'id="btn-retry-live"' in HTML and 'id="btn-retry-forecast"' in HTML
    assert "watchJob(" in JS and "localStorage" in JS and "savePrefs" in JS
    assert "prefers-reduced-motion" in CSS

def test_no_fake_live_wording_for_stale_data():
    assert "stale" in JS and "không phải giá trực tiếp" in JS
    # Không dùng ngôn ngữ khẳng định hướng giá trên giao diện chính
    for banned in ("giá sẽ giảm", "giá sẽ tăng", "sắp sập", "an toàn tuyệt đối", "chắc chắn giảm"):
        assert banned not in HTML

def test_extended_backtest_table_renders_es_vs_actual_loss_and_pdf_button():
    assert "ES_dự_báo_trung_bình_%_ngày_vi_phạm" in JS
    assert "lỗ_thực_tế_trung_bình_%_ngày_vi_phạm" in JS
    assert "ES dự báo / Lỗ thực TB" in JS
    assert "ngày_vi_phạm" in JS
    assert 'id="btn-pdf-backtest"' in HTML and "#btn-pdf-backtest" in JS
