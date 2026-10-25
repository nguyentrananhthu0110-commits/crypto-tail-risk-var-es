# Nhật ký nguồn dữ liệu

| Dữ liệu | Nguồn | Ghi chú |
|---|---|---|
| Nến 1h/1d, ticker | Binance spot REST công khai `/api/v3/klines`, `/api/v3/ticker/24hr` (không cần API key) | Retry theo `Retry-After` (429), đổi host (421), không retry 422. Lưu parquet + `data/metadata/manifest.sqlite` |
| Giá realtime trên giao diện | Binance WebSocket công khai (trình duyệt kết nối trực tiếp) | Mất kết nối → REST fallback, dữ liệu cũ gắn nhãn *stale* |
| `Data_daily_BTC_ETH_2017-2026.csv` | **Chưa ghi nguồn gốc** — cần tác giả bổ sung (nhà cung cấp, ngày tải, giá đóng cửa theo mốc UTC nào) | Đã đối chiếu độc lập (2026-10-24): trên 726 ngày trùng với Binance BTCUSDT/ETHUSDT lệch trung vị 0,04%, p99 0,18%, tối đa 0,24%; log return tái tính từ giá khớp file (sai số ~5e-9). Đủ tốt cho backtest rủi ro, nhưng giá là USD chứ không phải USDT |

## Ghi chú tái lập
- Backtest: seed cố định (42), chạy lại cho bảng y hệt (đã kiểm tra ngày 2026-10-24).
- Phụ thuộc xem `requirements.txt`; kết quả mẫu dài cần thư viện `arch` (GARCH-t).
