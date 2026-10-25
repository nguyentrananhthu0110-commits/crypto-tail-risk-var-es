# Từ điển dữ liệu

Mọi thời điểm theo **UTC**. Lợi suất: `log_return = ln(C_t/C_{t-1})`, `simple_return = C_t/C_{t-1} − 1`.

## `data/raw/<SYMBOL>_1h.parquet`, `<SYMBOL>_1d.parquet` (nến Binance spot, `/api/v3/klines`)
| Cột | Ý nghĩa |
|---|---|
| timestamp | Mở nến (ms epoch UTC) |
| open, high, low, close | Giá (USDT) |
| volume / quote_volume | Khối lượng coin / USDT |
| close_time | Đóng nến (ms epoch UTC) |
| trades | Số lệnh khớp |

Phạm vi hiện có (BTCUSDT): 1h 2024-10-22 → 2026-10-22 (17.521 nến); 1d 2022-09-14 → 2026-10-21 (1.499 nến).

## `data/processed/<SYMBOL>_daily.parquet` (gộp từ nến 1h theo ngày UTC)
| Cột | Ý nghĩa |
|---|---|
| date | Ngày UTC |
| open, high, low, close, volume, quote_volume | Gộp từ 24 nến 1h |
| n_hours | Số nến 1h có trong ngày (24 = đủ) |
| rv | Σ (log-return 1h)² trong ngày (phương sai thực hiện) |
| log_return, simple_return | Lợi suất ngày |
| realized_vol | √rv |

BTCUSDT: 729 ngày, 2024-10-23 → 2026-10-21.

## `data/features/<SYMBOL>_features.parquet` (27 cột)
Feature tại ngày *t* **chỉ dùng thông tin ≤ t**; nhãn là biến động ngày *t+1*.
`rv_lag1/2/3` (RV trễ), `rv_w` (TB 5 ngày), `rv_m` (TB 22 ngày), `ret_lag1`, `abs_ret_lag1`, `ret_sq_lag1`, `range_lag1`, `log_volume_lag1`, `volume_chg_lag1`, `cross_rv_lag1` (RV của tài sản còn lại), nhãn `target_rv`, `target_vol`, `target_date`.

## `data/raw/Data_daily_BTC_ETH_2017-2026.csv` (dùng cho backtest mẫu dài)
| Cột | Ý nghĩa |
|---|---|
| date_utc | Ngày, định dạng `m/d/yyyy` |
| btc_close_usd, eth_close_usd | Giá đóng cửa USD |
| btc_log_return, eth_log_return | Log return **tính bằng %** |

3.578 dòng, 2017-01-01 → 2026-10-18, không thiếu giá trị. Dòng đầu không có giá hôm trước nên bị bỏ khi backtest.

## `outputs/tables/` (sinh bởi `python -m src.backtest.run_backtest`)
| File | Nội dung |
|---|---|
| backtest_summary.csv | Tập test ngắn: vi phạm, Kupiec, Christoffersen, pinball, ES-Z2, Basel — mỗi (symbol, mô hình, mức) |
| backtest_daily.csv | VaR/ES/vi phạm/pinball từng ngày |
| backtest_dm_pinball.csv | Diebold–Mariano vs Historical 22d (tập ngắn) |
| backtest_nu.csv | ν Student-t: train-only (dùng) và toàn mẫu (chỉ để đối chiếu rò rỉ) |
| *(cột mới 2026-10-24)* `christoffersen_cc_note` | `ok` hoặc `không đủ dữ liệu (k vi phạm < 5)` — phân biệt rõ "đã kiểm định" với "không kiểm định được" |
| *(cột mới 2026-10-24)* `sức_mạnh_kiểm_định` | Cảnh báo theo cỡ mẫu: `YẾU` khi kỳ vọng < 5 vi phạm, `TRUNG BÌNH` khi < 10, `ok` khi ≥ 10 |
| *(cột mới 2026-10-24)* `ngày_vi_phạm` | Danh sách ngày xảy ra vi phạm VaR (tối đa 8 ngày đầu + số ngày còn lại) |
| backtest_long_summary.csv / _daily.csv / _dm_pinball.csv | Mẫu dài rolling cho đủ 35 coin: ~2.577 ngày OOS (BTC/ETH từ CSV 2017–2026) và 267–1.498 ngày OOS (33 altcoin từ `<SYMBOL>_1d.parquet`) |

`models/metadata/<SYMBOL>_{forecast,performance,backtest,explain}.json` là artifact của pipeline huấn luyện; toàn bộ hệ thống (`forecast.json`, `backtest.json` và `run_backtest.py`) dùng thống nhất `t_df_train_only` (ν ước lượng chỉ trên giai đoạn train trước kỳ test).

**Quy ước ν & cửa sổ dữ liệu (thống nhất 2026-10-24).** Hệ thống thống nhất dùng một giá trị `risk.t_df_train_only` (ước lượng trên dữ liệu **trước** ngày test đầu tiên) cho cả dự báo VaR/ES (`risk.forecast_based`, `risk.parametric_student_t`) lẫn mọi bảng kiểm định ngoài mẫu (`backtest.json` và `outputs/tables/backtest_*.csv`), loại bỏ hoàn toàn rò rỉ dữ liệu kiểm định; `t_df_live` toàn mẫu chỉ lưu trong `backtest_nu.csv` để đối chiếu.
