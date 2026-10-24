# Crypto Risk Intelligence

Ứng dụng web chạy local trên Windows để **theo dõi thị trường đa tài sản (35 coin: BTC, ETH, BNB, SOL, XRP, ADA, DOGE, TRX, AVAX, LINK, DOT, POL, LTC, SHIB, UNI, ATOM, ETC, FIL, APT, ARB, OP, NEAR, SUI, PEPE, TON, INJ, STX, IMX, HBAR, TIA, RENDER, AR, GRT, AAVE, MKR) theo thời gian thực, dự báo biến động (volatility) và phân tích rủi ro đuôi (VaR/ES)**.

> Đây là công cụ **nghiên cứu định lượng và hỗ trợ quản trị rủi ro**. Sản phẩm không phải bot giao dịch, không bảo đảm lợi nhuận và không đưa ra khuyến nghị đầu tư cá nhân hoá. Dự báo volatility **không** dự báo hướng giá tăng/giảm.

---

## 1. Yêu cầu hệ thống

| Hạng mục | Yêu cầu |
|---|---|
| Hệ điều hành | Windows 10/11 (có sẵn file `.cmd`). Linux/macOS chạy được qua các lệnh Python tương đương bên dưới. |
| Python | 3.10 – 3.13 (khuyến nghị 3.11/3.12), tích **Add Python to PATH** khi cài |
| RAM / ổ đĩa | ≥ 4 GB RAM · ~300 MB cho môi trường + chỉ vài MB cho dữ liệu/mô hình |
| Mạng | Cần internet để tải dữ liệu công khai từ Binance. **Không cần API key giao dịch.** |

## Cách chạy KHÔNG cần CMD (khuyến nghị mới)

Bản ZIP đã đóng gói **sẵn dữ liệu và mô hình tham chiếu**, nên lần đầu bạn không bắt buộc phải nạp dữ liệu ngay.

1. Giải nén toàn bộ ZIP (Extract All), mở thư mục `crypto-risk-intelligence`.
2. Double-click **`START_HERE.pyw`**.
3. Bấm **“1) Cài đặt thư viện”**, chờ hoàn tất.
4. Bấm **“3) Mở ứng dụng”** — trình duyệt mở tại http://127.0.0.1:8765.
5. Khi muốn dữ liệu mới: ngay trong trình duyệt, vào tab **Dữ liệu & hệ thống** → **“Nạp dữ liệu & huấn luyện”** (hoặc “Cập nhật phần thiếu”). Không cần mở CMD/PowerShell.

Nếu double-click `.pyw` lại mở VS Code/Notepad: nhấp chuột phải → **Open with → Python**, hoặc mở PowerShell trong thư mục dự án và chạy `py .\START_HERE.pyw`.

Phương án PowerShell thuần (không qua `.cmd`):

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\run_app.ps1
# Nạp dữ liệu mới khi muốn:
powershell -ExecutionPolicy Bypass -File .\prepare_data.ps1
```

Trong VS Code: mở thư mục dự án → **Terminal → Run Task** → chọn các task `CRI: ...`.

Chi tiết rút gọn nằm ở `00_BAT_DAU_TAI_DAY.txt`. Các file `.cmd` vẫn được giữ như phương án phụ ở mục dưới.

## 2. Cài đặt & chạy lần đầu (Windows)

Giải nén xong hãy mở đúng thư mục **`crypto-risk-intelligence`** (thư mục con chứa các file `setup.cmd`, `run_app.cmd` — sau khi giải nén file zip có thể nằm trong một lớp thư mục nữa, ví dụ `crypto-risk-intelligence-windows\crypto-risk-intelligence\`). Kiểm tra nhanh bằng lệnh `dir setup.cmd`: nếu không thấy file nghĩa là bạn đang đứng sai thư mục.

Chạy theo thứ tự — double-click trong File Explorer là dễ nhất. Nếu dùng terminal:

**Trong CMD (Command Prompt):**
```bat
setup.cmd           :: 1 lần duy nhất: tạo .venv + cài thư viện (không tải dữ liệu, không huấn luyện)
prepare_data.cmd    :: 1 lần duy nhất: tải ~2 năm lịch sử BTC/ETH, huấn luyện 4 mô hình, lưu tất cả
run_app.cmd         :: mọi lần dùng sau đó: mở dashboard ngay từ dữ liệu/model đã lưu
```

**Trong PowerShell** (kể cả Terminal của VS Code) phải thêm `.\` ở đầu, vì PowerShell không tự chạy file trong thư mục hiện tại:
```powershell
.\setup.cmd
.\prepare_data.cmd
.\run_app.cmd
```
Gõ thiếu `.\` trong PowerShell sẽ gặp lỗi *"The term 'setup.cmd' is not recognized..."* dù file vẫn nằm ngay đó — đây là cơ chế bảo mật của PowerShell, không phải lỗi của dự án.

Sau khi chạy `run_app.cmd`, trình duyệt tự mở tại **http://127.0.0.1:8765**. Dừng ứng dụng bằng `Ctrl+C` trong cửa sổ CMD (server con được tắt sạch).

**Điều kiện nghiệm thu đã kiểm chứng:** chạy `prepare_data.cmd` một lần → đóng → chạy `run_app.cmd` → ứng dụng mở ngay, **không** tải lại lịch sử, **không** huấn luyện lại.

## 3. Cập nhật dữ liệu

```bat
update_data.cmd              :: chỉ tải phần thiếu kể từ checkpoint gần nhất
update_data.cmd --retrain    :: cập nhật + ép huấn luyện lại ngay
```

- Chính sách mặc định: huấn luyện lại chỉ khi có **≥ 7 ngày** dữ liệu mới (cấu hình `retrain_min_new_days`), model bị thiếu, hoặc bạn ép `--retrain`.
- Trong dashboard cũng có nút **Cập nhật dữ liệu** và **Huấn luyện lại** (tab *Dữ liệu & hệ thống*) chạy nền, không chặn giao diện. Lưu ý dự báo chỉ thay đổi theo **ngày UTC đã đóng** — tick giá trực tiếp không làm đổi forecast, và giao diện phân biệt rõ hai loại thời gian cập nhật này.
- Nếu cập nhật thất bại (mất mạng…), dataset tốt gần nhất vẫn còn nguyên (ghi file kiểu nguyên tử: ghi tạm → thay thế).

## 4. Dữ liệu & mô hình được lưu ở đâu

```
data/raw/            Nến OHLCV Parquet (BTCUSDT_1h, _1d, ETHUSDT_...) — timestamp UTC (ms)
data/processed/      Chuỗi ngày: returns, realized variance/volatility
data/features/       Feature dataset (target = RV ngày kế tiếp, chống rò rỉ)
data/metadata/       manifest.sqlite: checkpoint, số dòng, phiên bản, lịch sử job & model
models/saved/        HAR (JSON), GARCH state (JSON), XGBoost (joblib) cho từng symbol
models/metadata/     <SYMBOL>_forecast/performance/backtest/explain.json — dashboard đọc trực tiếp
logs/app.log         Log xoay vòng (tối đa ~6 MB)
config/config.json   Cấu hình: symbols, độ dài lịch sử, vị thế tham chiếu, port, chính sách retrain
```

Ba thao tác tách bạch: **first-time setup** (`prepare_data`) · **normal launch** (`run_app`, load artifacts đã lưu) · **incremental update** (`update_data`, chỉ phần thiếu + lấp gap nếu phát hiện). Nến chưa đóng không bao giờ lọt vào dữ liệu huấn luyện.

## 5. Cách đọc các chỉ số (+ giải thích ý nghĩa & hiệu ứng)

Mỗi KPI/panel có nút **“?”** và khối *“Tại sao các số lại như vậy và có hiệu ứng gì?”* giải thích ngay tại chỗ.

- **Volatility dự báo 1 ngày** (hiển thị %/năm = vol ngày × √365): quy mô dao động kỳ vọng — không nói giá tăng hay giảm. *Tại sao là con số này?* Là vol ngày (√RV dự báo cho ngày kế tiếp) được năm hóa; mô hình được chọn là mô hình có **QLIKE ngoài-mẫu thấp nhất**. *Hiệu ứng:* biến động cao → VaR/ES giãn ra → cần đệm vốn/bảo hiểm lớn hơn.
- **Trạng thái biến động** (Thấp / Bình thường / Cao / Stress): phân vị của vol dự báo so với realized vol **tập huấn luyện** (ngưỡng q25/q75/q90). *Tại sao là phân vị?* Cùng một mức vol có thể là “cao” trong thị trường yên ắng nhưng “bình thường” sau khủng hoảng — phân vị chuẩn hóa theo lịch sử. *Hiệu ứng:* phân vị cao ⇒ vùng stress ⇒ ngưỡng rủi ro co giãn lên cao hơn.
- **VaR 95% = X USD** (trên vị thế tham chiếu, mặc định 10.000 USD): xác suất đuôi vượt X ≈ 5% trong 1 ngày. **VaR không phải mức lỗ tối đa.** *Tại sao?* VaR theo dự báo = σ̂_forecast × quantile Student-t(df̂) × vị thế; VaR mô phỏng = quantile lịch sử; Student-t = quantile tham số trên toàn bộ lịch sử. *Hiệu ứng:* VaR **đóng khung ngưỡng tổn thất**, ngày kích hoạt có thể vượt xa.
- **ES 95%**: mức lỗ trung bình có điều kiện trong nhóm 5% kết quả tệ nhất — "khi xấu thì xấu cỡ nào".
- **MAE / RMSE / QLIKE (tab Phân tích mô hình)**: MAE = sai số tuyệt đối trung bình, RMSE phạt nặng sai số lớn, QLIKE = hàm mất mát phù hợp biến động (tiêu chí chọn mô hình). *Hiệu ứng:* QLIKE thấp ⇒ VaR tin cậy hơn ⇒ vị thế quản trị rủi ro ổn định hơn.
- **Kupiec / Christoffersen (tab Kiểm định)**: kiểm tra tỉ lệ vi phạm và tính cụm của vi phạm. *Hiệu ứng:* p-value nhỏ ⇒ ngưỡng thiếu/thừa rủi ro hoặc vi phạm bị cụm ⇒ không nên đặt thế vị lớn.
- **Quy ước**: LOSS = −(simple return ngày) × vị thế (số dương = lỗ). Horizon VaR/ES = **1 ngày**. Khung biểu đồ (5m, 1h…) là kích thước nến hiển thị, **không** phải kỳ dự báo.

Dashboard có 3 phương pháp để đối chiếu độ nhạy giả định: *Theo dự báo* (σ dự báo × đuôi Student-t chuẩn hoá) · *Historical Simulation* (250 ngày gần nhất) · *Tham số Student-t* (fit toàn bộ lịch sử). Tab **Giải thích & phương pháp** chứa công thức, tham số đã lưu, giới hạn mô hình và từ điển thuật ngữ.

## 6. Mô hình & đánh giá

- **Benchmark**: trung bình RV 22 ngày. **GARCH(1,1)-t** (thư viện `arch`, có fallback MLE tự cài đặt bằng scipy). **HAR-RV** (Corsi): RV ngày/tuần/tháng. **XGBoost** trên lag RV/return/range/volume + RV chéo BTC↔ETH (fallback HistGradientBoosting nếu thiếu xgboost).
- RV ngày = căn bậc hai của Σ(log-return 1 giờ)² trong ngày UTC. Feature tại ngày *t* chỉ dùng thông tin ≤ *t*; mục tiêu là RV ngày *t+1*.
- Chia train/test **theo thời gian** 80/20 (không xáo trộn ngẫu nhiên); GARCH refit theo cửa sổ mở rộng trong test, chỉ dùng quá khứ.
- Metrics: MAE, RMSE, **QLIKE** (mô hình dùng cho VaR là mô hình QLIKE ngoài-mẫu thấp nhất — hiển thị minh bạch), kiểm định **Diebold–Mariano** (hiệu chỉnh HLN).
- Backtest VaR ngoài-mẫu: số breach, **Kupiec**, **Christoffersen**, quantile loss. Thiếu dữ liệu → báo *insufficient_data*, không kết luận "đạt".
- Thời gian huấn luyện toàn bộ 2 symbol trên máy thông thường: ~15–60 giây + thời gian tải dữ liệu lần đầu.

## 7. Kiểm tra trạng thái & xử lý lỗi thường gặp

```bat
.venv\Scripts\python.exe scripts\check_status.py
.venv\Scripts\python.exe scripts\check_status.py --deep   :: load thử thật file XGBoost + quét gaps/dup/OHLC trên Parquet
```

| Triệu chứng | Cách xử lý |
|---|---|
| `run_app.cmd` báo *chưa sẵn sàng* | Chạy `prepare_data.cmd` một lần. Launcher cố ý **không** âm thầm tải lại. |
| Port 8765 bị chiếm | Ứng dụng có thể đang mở (thử http://127.0.0.1:8765) hoặc đổi cổng: `set CRI_PORT=8770 && run_app.cmd` |
| Không thấy Python / `py` | Cài Python từ python.org, tích *Add Python to PATH*, chạy lại `setup.cmd`. |
| `pip install` lỗi | Kiểm tra mạng; nếu dùng Python quá mới mà wheel chưa có, cài 3.11/3.12 rồi tạo lại `.venv`. |
| Dashboard báo *stale* / mất kết nối | Binance hoặc mạng gián đoạn — app tự kết nối lại WebSocket (backoff) và dùng REST dự phòng; dữ liệu cũ luôn gắn nhãn, không giả làm trực tiếp. Có nút **Thử lại kết nối** ngay trên banner. |
| Dashboard báo *Model: corrupted* / file dataset `corrupt` | Artifact hoặc Parquet không đọc được (hay gặp khi máy tắt đột ngột). Ứng dụng **không tự xoá**; chạy `update_data.cmd --retrain` để tạo lại model, hoặc `prepare_data.cmd --full` để tải lại dataset một cách có chủ đích. Xem trạng thái từng file ở tab *Dữ liệu & hệ thống* → “Chi tiết nâng cao” hoặc `check_status.py --deep`. |
| Thư mục cài đặt có dấu cách / tiếng Việt | Được hỗ trợ (launcher tự định vị bằng `%~dp0` và quote mọi đường dẫn; đã kiểm chứng chạy từ thư mục `thư mục tiếng Việt có dấu cách/Crypto Risk Intelligence`). |
| HTTP 422 trên UI | Tham số không hợp lệ (ví dụ vị thế ≤ 0) — app báo lỗi có cấu trúc, không crash. HTTP 429/5xx từ Binance được retry có giới hạn + tôn trọng `Retry-After`; 421 (sai host) tự chuyển host dự phòng. |
| Muốn huấn luyện lại có chủ đích | `update_data.cmd --retrain` hoặc nút **Huấn luyện lại** trong dashboard. |
| Muốn reset toàn bộ | Đóng app → xoá thư mục `data/` và `models/` → chạy `prepare_data.cmd`. (Tải lại từ đầu: `prepare_data.cmd --full`.) |

Log: cửa sổ CMD + `logs/app.log`. API không trả stack trace ra trình duyệt; lỗi trả dạng `{detail:{code,message}}`. Tài liệu API tự sinh: http://127.0.0.1:8765/api/docs

## 8. Cấu hình

Sửa `config/config.json`: `history_days_hourly` (mặc định 730), `history_days_daily` (1500), `reference_position_usd` (10000), `train_ratio` (0.8), `retrain_min_new_days` (7), `port` (8765). Ghi đè nhanh bằng biến môi trường `CRI_HOST`, `CRI_PORT`, `CRI_NO_BROWSER=1`, `CRI_NO_PAUSE=1` (xem `.env.example`).

**Coin, timeframe biểu đồ và kỳ dự báo — ba khái niệm tách bạch:**

- **Coin**: chọn bằng **dropdown tìm kiếm** trên thanh trên cùng — danh sách 35 coin chỉ hiện khi bạn gõ vào ô tìm kiếm, chọn một coin để xem dữ liệu; không còn hàng nút 35-coin luôn hiện. **Vị thế & đòn bẩy**: trong tab *Theo dõi rủi ro* chỉnh *Vị thế tham chiếu* và chọn **đòn bẩy 1×/2×/5×/10×** — VaR/ES được co giãn tuyến tính (Tổn thất có đòn bẩy = Tổn thất gốc × đòn bẩy), hiển thị đồng thời trên KPI và panel rủi ro. Thêm coin mới: thêm vào `symbols` trong `config.json` rồi chạy Nạp dữ liệu & huấn luyện cho coin đó; pipeline xử lý từng coin độc lập — một coin lỗi không chặn các coin còn lại (đã sửa các mã hết hạn MATIC→POL, RNDR→RENDER, FTM→TIA).
- **Timeframe biểu đồ** (1m–1d): chọn trên thanh công cụ của chart; đây chỉ là kích thước nến hiển thị. Lựa chọn coin/timeframe/phương pháp VaR/vị thế/tab được trình duyệt ghi nhớ (localStorage) cho lần mở sau.
- **Forecast horizon**: cố định **1 ngày** trong thiết kế model (mục tiêu huấn luyện là RV ngày kế tiếp) — không đổi được bằng cấu hình. Muốn horizon khác phải thay đổi target và huấn luyện lại ở tầng mã nguồn (`src/features/build.py` + `src/models/training.py`); con số “7 ngày” trên KPI là mở rộng quy mô có ghi nhãn, không phải một model 7 ngày riêng.

**Hai tầng nội dung**: màn hình chính chỉ có kết luận, 5 KPI và VaR/ES (tầng 1). Công thức, tham số mô hình, kỳ mẫu, metrics đầy đủ, backtest chi tiết và báo cáo chất lượng dữ liệu nằm trong các mục “Chi tiết nâng cao” đóng sẵn và tab *Giải thích & phương pháp* (tầng 2). Dấu `?` cạnh thuật ngữ mở định nghĩa ngắn.

## 9. Tests

```bat
.venv\Scripts\python.exe -m pytest tests -v
:: Smoke test mạng thật (tuỳ chọn, thủ công):
set CRI_LIVE_TEST=1 && .venv\Scripts\python.exe -m pytest tests\smoke\test_live_smoke.py -v
```

Tests tổ chức theo `tests/unit` (dữ liệu, model, risk, retry policy, incremental, tái lập), `tests/integration` (API, persistence, file hỏng, hợp đồng launcher + mã thoát), `tests/smoke` (hợp đồng frontend tĩnh + smoke mạng thật tuỳ chọn) — tổng **62 tests** tại thời điểm bàn giao (chưa tính live smoke). Bộ kiểm thử mặc định dùng dữ liệu tổng hợp/mock, không gọi API sống: tính liên tục/gap/duplicate/OHLC, tổng hợp timeframe đúng ranh giới UTC, rò rỉ thông tin feature, train/test theo thời gian, đáp án đã biết cho QLIKE/HAR/Kupiec, quy ước dấu VaR/ES, breach logic, scaling theo √horizon, save/load model, chính sách retry (422 không retry · 421 chuyển host · 429 tôn trọng Retry-After · malformed JSON), lưu/đọc nguyên tử, API 200/404/422/500-corrupted/502 và fallback stale.

## 10. Kiến trúc (tóm tắt)

```
Binance Public REST ──> src/data (ingestion + validation + incremental Parquet/SQLite manifest)
                    └─> src/features (RV ngày, lag features) ──> src/models (GARCH/HAR/XGB, QLIKE/DM)
                                                              └─> src/risk (VaR/ES 3 phương pháp, Kupiec/Christoffersen, regime)
Trình duyệt <── FastAPI (app/main.py): REST + artifacts đã lưu
Trình duyệt <── Binance WebSocket công khai (kline + miniTicker): nến/giá trực tiếp, cập nhật tăng dần
```

Lý do chọn stack: **FastAPI + frontend vanilla (canvas tự vẽ)** thay vì Streamlit vì cần cập nhật nến tăng dần mà không render lại toàn trang, và thay vì CCXT bằng REST/WebSocket chính thức của Binance để giảm phụ thuộc khi cài trên Windows (API công khai, cấu trúc dữ liệu tương thích tinh thần `binance-public-data`). XGBoost/`arch` là phụ thuộc chính nhưng đều có fallback tự cài đặt để ứng dụng không chết vì một wheel bị thiếu. SHAP không bắt buộc: giải thích dùng permutation importance trên tập test (ghi rõ không phải quan hệ nhân quả). Không dùng Kafka/Kubernetes/DB server — Parquet + SQLite là đủ và đáng tin cậy cho mức dữ liệu này.

## 11. Giới hạn cần biết

- RV tính từ lợi suất 1 giờ (không phải tick data) nên có nhiễu vi cấu trúc; ngày cần ≥23 giờ mới được tính.
- Phân phối Student-t giả định đuôi đối xứng; đuôi giảm thực tế có thể nặng hơn. Cú sốc chưa từng có trong lịch sử có thể vượt xa VaR/ES.
- Thứ hạng mô hình (QLIKE) thuộc về cửa sổ kiểm tra hiện tại và có thể đổi khi dữ liệu mới đến.
- Vol 7 ngày (ngoài GARCH) dùng quy tắc √t với giả định độc lập — chỉ để tham chiếu quy mô, đã ghi nhãn trong metadata.
- Chưa dùng funding rate/open interest/order-book: chỉ đưa vào khi có pipeline dữ liệu đáng tin cậy (điểm mở rộng tương lai cùng LSTM, nếu baseline được đánh giá là chưa đủ).
- Binance là nguồn dữ liệu duy nhất hiện tại; có host dự phòng (`data-api.binance.vision`, `api.binance.com`, `api1.binance.com`) nhưng không có sàn dự phòng.

## 12. Chạy trên Linux/macOS (cho nhà phát triển)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/prepare_data.py
.venv/bin/python scripts/launch.py        # hoặc: CRI_HOST=0.0.0.0 .venv/bin/python scripts/launch.py
```
