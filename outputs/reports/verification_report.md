# Báo cáo nghiệm thu — Crypto Risk Intelligence

*Thời điểm kiểm chứng: 2026-10-22 (giờ hệ thống UTC trên môi trường build). Mọi số liệu dưới đây là kết quả chạy thật với dữ liệu Binance Public, không phải số minh hoạ.*

## 1. Kết quả định lượng tại thời điểm bàn giao

Chuẩn bị dữ liệu lần đầu: BTCUSDT + ETHUSDT, 17.519 nến 1h (730 ngày) và 1.499 nến 1d mỗi symbol, **0 gaps, 0 duplicates, 0 vi phạm OHLC**. Train 2024-11-13 → 2026-05-31 (565 ngày), test out-of-sample 2026-06-02 → 2026-10-21 (142 ngày).

| Chỉ số | BTCUSDT | ETHUSDT |
|---|---|---|
| Mô hình được chọn (QLIKE OOS thấp nhất) | XGBoost (0.430) | XGBoost (0.461) |
| QLIKE: Historical / GARCH / HAR-RV | 0.572 / 0.500 / 0.459 | 0.590 / 0.662 / 0.523 |
| Volatility dự báo (năm-hoá) | 34,0% | 56,4% |
| Regime | Bình thường (~phân vị 45) | Bình thường |
| VaR95 / ES95 — 1 ngày, vị thế 10.000 USD | $255 / $401 | $385 / $649 |
| Backtest VaR95 breach | 6/142 (4,2%; kỳ vọng 5%) | 7/142 (4,9%; kỳ vọng 5%) |
| Kupiec p-value (VaR95) | 0,664 | 0,969 |
| Christoffersen p-value (VaR95) | 0,729 | (xem artifact JSON) |

Diễn giải: tần suất breach OOS tương thích thống kê với mức danh định (không bác bỏ H0) trong cửa sổ test hiện tại — đây là bằng chứng có điều kiện về cửa sổ/kỳ mẫu, không phải bảo chứng tương lai.

## 2. Kiểm thử đã chạy

- **pytest**: 24/24 passed (data validation, resample UTC, feature leakage, đáp án đã biết QLIKE/HAR/Kupiec, quy ước dấu VaR/ES, ES≥VaR, reproducibility seed, insufficient-data guards, atomic persistence, API 200/404/422, fallback stale). Thời gian ~4 giây, không gọi mạng.
- **Live smoke** (`CRI_LIVE_TEST=1`): 1/1 passed với Binance public thật.
- **E2E trình duyệt (Playwright/Chromium)**: trang tải sạch console (0 error); WebSocket báo "Trực tiếp"; giá/regime/vol/VaR hiển thị đúng artifact; đổi timeframe 1h→5m chỉ nạp nến (500 nến, nến cuối "đang hình thành"); đổi BTC→ETH đúng giá/dự báo; 5/5 tabs render đúng dữ liệu; đổi vị thế 10.000→20.000 USD: VaR95 $255→$509 (tuyến tính); đổi phương pháp HS: VaR95 $566 kèm ghi chú giả định.
- **Restart/persistence**: tắt server → khởi động lại qua đúng `scripts/launch.py` (đường đi của `run_app.cmd`) → `/api/forecast` trả kết quả ngay từ artifacts đã lưu, không huấn luyện lại.
- **Incremental**: chạy `update_data.py` lần 2 → "đã mới nhất (checkpoint…)", +0 nến ngày, không retrain (chưa đủ ngưỡng 7 ngày theo chính sách), giữ nguyên forecast cùng timestamp cũ.
- **Port bận**: `check_status.py --check-port` khi server đang chạy → exit code 3 đúng hợp đồng với `run_app.cmd`.
- **Background jobs**: `POST /api/admin/update` → accepted, hoàn tất "success" mà UI không bị chặn.
- **Lỗi API**: `symbol=DOGEUSDT` và `limit=5` (< tối thiểu 10) → HTTP 422 có cấu trúc; model chưa khởi tạo → 404 `MODEL_NOT_INITIALIZED` + empty state trên UI; ticker khi upstream chết (mock) → fallback dữ liệu cục bộ có cờ `stale=true`.

## 3. Chưa kiểm chứng được trong môi trường build (nói thẳng)

- **Các file `.cmd` chưa thể thực thi trên máy Windows thật** tại đây (môi trường build là Linux). Mọi logic bên dưới chúng (`check_status.py` theo mã thoát 0/2/3, `prepare_data.py`, `update_data.py`, `launch.py`) đã chạy thật; `.cmd` dùng `%~dp0`, quoting cho đường dẫn có dấu cách, không hardcode đường dẫn, `pause` chỉ ở nhánh lỗi và mã thoát vẫn được bảo toàn (`CRI_NO_PAUSE=1` để tắt). Cần chạy thử nghiệm thu 4 bước trên Windows của bạn theo README §2 — dự kiến điểm rủi ro duy nhất là wheel của `arch`/`xgboost` theo phiên bản Python, và cả hai đều có fallback.
- Hành vi WebSocket khi mất mạng dài hạn chỉ kiểm chứng bằng logic reconnect + watchdog 45s và fallback REST, chưa soak-test nhiều giờ.

## 4. Những gì cố ý không làm (và lý do)

- **LSTM/PyTorch**: baseline đã đáp ứng; LSTM là tầng mở rộng theo đúng lộ trình yêu cầu.
- **SHAP**: dùng permutation importance trên tập test (tránh phụ thuộc numba dễ gãy khi cài Windows; ghi rõ không phải nhân quả). Có thể bổ sung SHAP sau qua cùng giao diện explain.
- **CCXT**: dùng REST/WebSocket chính thức của Binance (public, không key) để tối đa hoá khả năng cài đặt thành công; adapter nằm gọn trong `src/data/binance_client.py`.
- **Funding rate / open interest / order book**: chưa có pipeline lưu trữ đáng tin cậy nên không đưa vào model.
- **Light theme**: bỏ qua để giữ độ hoàn thiện của dark theme mặc định (yêu cầu ghi là tuỳ chọn).
- **Horizon 7 ngày chính thức**: chỉ GARCH có đường cong kỳ hạn thật; mô hình khác dùng √7 và được ghi nhãn tham chiếu trong metadata/UI phụ, horizon chính cho VaR là 1 ngày.

---

## 5. Đợt bổ sung theo mục 10–18 (kiểm chứng bổ sung, cùng ngày)

**UX 2 tầng & điều hướng**
- Tooltip `?` cho đủ 8 thuật ngữ: volatility regime, forecasted vol, VaR, ES, realized volatility, out-of-sample, QLIKE, VaR breach (kiểm chứng popover QLIKE trên trình duyệt thật).
- Mọi mục "Chi tiết nâng cao" (công thức/quy ước, tham số, DM test, breach list, data quality) đều **đóng mặc định** — kiểm chứng `details.open === false`.
- Trình duyệt **ghi nhớ bộ lọc** (coin, timeframe, phương pháp VaR, vị thế, tab) bằng localStorage: E2E đặt ETH/15m/HS/25.000 USD/tab Hiệu quả → reload → giữ nguyên toàn bộ, VaR95 hiển thị $950 tương ứng.
- Tác vụ nền có **theo dõi tiến độ thật**: poll trạng thái mỗi 3 giây, hiển thị thời gian chạy, khoá nút chống chạy trùng, toast thành công/thất bại và tự nạp lại artifacts khi retrain xong; cố ý không có nút huỷ giữa chừng để tránh ghi dữ liệu dở dang (thông báo rõ trên UI).

**Độ ổn định (mục 12)**
- Retry policy được kiểm thử bằng mock: 422 gọi đúng 1 lần; 421 chuyển host ngay; 429 chờ theo `Retry-After`; 5xx dừng ở (retries+1)×hosts; timeout và **malformed JSON** retry có giới hạn; klines malformed bị loại/từ chối đúng hợp đồng.
- Phân biệt **missing/corrupt/ok** cho cả Parquet và artifact JSON: API trả `MODEL_CORRUPTED` (500 có hướng dẫn sửa), `/api/status?include_quality=true` báo gaps/dup/OHLC từ file thật, `check_status.py --deep` load thử model XGBoost. Upstream trả rỗng → fallback cục bộ + cờ stale, hoặc 502 nếu không có gì.
- **Đường dẫn có dấu cách + tiếng Việt**: sao chép toàn bộ dự án sang `thư mục tiếng Việt có dấu cách/Crypto Risk Intelligence` → check_status --deep, 36 unit/smoke tests, launch server, forecast và index đều 200.
- Incremental thật qua UI: bấm "Cập nhật dữ liệu" trên dashboard → ETH 1h tăng 17.519 → 17.520 nến (đúng +1 nến giờ mới), trạng thái job **success**, nút được mở khoá lại.

**Tests**: reorganize thành `tests/unit|integration|smoke`, nâng từ 24 → **54 passed, 1 skipped** (live smoke vẫn tách riêng, đã chạy đạt khi bật). Bộ test mới tự bắt được 1 import bị mất trong quá trình refactor (`parquet_state`) — đã sửa và xác minh lại toàn bộ, gồm huấn luyện lại BTC end-to-end (QLIKE không đổi 0.430, chứng tỏ refactor split không đổi kết quả).

---

## 6. Phương án không cần CMD (bổ sung theo yêu cầu người dùng)

- **START_HERE.pyw**: trình khởi chạy đồ họa chỉ dùng thư viện chuẩn Python/Tkinter. Đã chạy thử cửa sổ thật dưới Xvfb: hiển thị đúng trạng thái dữ liệu/mô hình đóng gói sẵn và 5 nút Cài thư viện / Nạp dữ liệu / Mở ứng dụng / Cập nhật / Dừng. Không thể xác minh liên kết double-click `.pyw` trên Windows thật trong sandbox Linux; hướng dẫn dự phòng bằng Open with Python hoặc `py .\START_HERE.pyw` được ghi ngay trong file.
- **Nạp dữ liệu ngay trong trình duyệt**: endpoint `POST /api/admin/prepare` chạy nền cho BTC+ETH; E2E với backend thật đã bấm nút trên dashboard và job **prepare: success sau ~9 giây** (dữ liệu đã ở checkpoint gần nhất, huấn luyện lại hoàn tất, console sạch). Luồng model-chưa-khởi-tạo được kiểm chứng bằng route mock: empty state hiện nút “Nạp dữ liệu & huấn luyện ngay” và gọi đúng endpoint.
- **PowerShell/VS Code**: `setup.ps1`, `prepare_data.ps1`, `update_data.ps1`, `run_app.ps1` tự định vị thư mục, không gọi ngược `.cmd`; `.vscode/tasks.json` có 4 task tương ứng. Chưa chạy được PowerShell thật trong sandbox (không có `pwsh`/Windows) — đã kiểm tra tĩnh và dùng chung các script Python đã kiểm chứng.
- **ZIP đóng gói sẵn dữ liệu/mô hình**: sau khi cài thư viện có thể mở app ngay; dữ liệu mới được kéo bằng nút trong GUI/trình duyệt thay vì CMD.
