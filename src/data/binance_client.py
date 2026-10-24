"""Binance Public Market Data (REST). Chỉ dữ liệu công khai, không API key.

Chính sách retry: chỉ retry lỗi tạm thời (timeout, kết nối, 429, 5xx) với
exponential backoff + jitter và tôn trọng Retry-After. Lỗi 4xx khác (400/422...)
không retry mù quáng vì là lỗi tham số/logic, trừ 421 (sai host) -> thử host khác.
"""
from __future__ import annotations
import random, time
import pandas as pd
import requests
from src.config import CONFIG, INTERVAL_MS
from src.utils.logging_setup import get_logger

log = get_logger("cri.binance")
KLINE_COLS = ["timestamp","open","high","low","close","volume","close_time",
              "quote_volume","trades","taker_buy_volume","taker_buy_quote_volume","ignore"]

class BinanceError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message); self.status_code = status_code

class BinanceClient:
    def __init__(self, bases: list[str] | None = None, timeout: int = 20, max_retries: int = 4):
        self.bases = bases or CONFIG["binance_rest_bases"]
        self.timeout, self.max_retries = timeout, max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CryptoRiskIntelligence/1.0"})

    def _get(self, path: str, params: dict):
        last_err = None
        for base in self.bases:
            for attempt in range(self.max_retries + 1):
                try:
                    r = self.session.get(f"{base}{path}", params=params, timeout=self.timeout)
                except (requests.Timeout, requests.ConnectionError) as e:
                    last_err = e
                    self._sleep(attempt); continue
                if r.status_code == 200:
                    try:
                        return r.json()
                    except ValueError as e:  # malformed body: lỗi tạm thời phía upstream/proxy -> retry có giới hạn
                        last_err = BinanceError(f"Phản hồi không phải JSON hợp lệ từ {base}: {e}")
                        self._sleep(attempt); continue
                if r.status_code == 421:  # request lạc host -> thử base tiếp theo, không retry cùng host
                    last_err = BinanceError(f"HTTP 421 tại {base}", 421); break
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = BinanceError(f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)
                    ra = r.headers.get("Retry-After")
                    self._sleep(attempt, float(ra) if ra and ra.isdigit() else None); continue
                raise BinanceError(f"HTTP {r.status_code}: {r.text[:300]}", r.status_code)
        raise BinanceError(f"Không gọi được Binance sau khi thử {len(self.bases)} host. Lỗi cuối: {last_err}",
                           getattr(last_err, "status_code", None))

    @staticmethod
    def _sleep(attempt: int, retry_after: float | None = None):
        delay = retry_after if retry_after else min(2 ** attempt, 20) + random.uniform(0, 0.5)
        time.sleep(delay)

    def fetch_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int | None = None,
                     include_forming: bool = False) -> pd.DataFrame:
        """Tải phân trang từ start_ms đến end_ms. Loại nến chưa đóng trừ khi include_forming."""
        if interval not in INTERVAL_MS:
            raise ValueError(f"Interval không hỗ trợ: {interval}")
        symbol = symbol.upper(); step = INTERVAL_MS[interval]
        now_ms = int(time.time() * 1000)
        end_ms = end_ms or now_ms
        rows, cursor = [], int(start_ms)
        while cursor <= end_ms:
            batch = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval,
                              "startTime": cursor, "endTime": end_ms, "limit": 1000})
            if not batch:
                break
            rows.extend(batch)
            nxt = int(batch[-1][0]) + step
            if nxt <= cursor or len(batch) < 1000:
                break
            cursor = nxt
        if not rows:
            return empty_candles()
        df = parse_klines(rows)
        if not include_forming:  # nến chưa đóng không được dùng làm dữ liệu đã hoàn tất
            df = df[df["close_time"] < now_ms].reset_index(drop=True)
        return df

    def fetch_recent(self, symbol: str, interval: str, limit: int = 500, include_forming: bool = True) -> pd.DataFrame:
        batch = self._get("/api/v3/klines", {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)})
        if not batch:
            return empty_candles()
        df = parse_klines(batch)
        if not include_forming:
            df = df[df["close_time"] < int(time.time()*1000)].reset_index(drop=True)
        return df

    def fetch_ticker_24h(self, symbol: str) -> dict:
        d = self._get("/api/v3/ticker/24hr", {"symbol": symbol.upper()})
        return {"symbol": d["symbol"], "price": float(d["lastPrice"]),
                "change_pct_24h": float(d["priceChangePercent"]),
                "high_24h": float(d["highPrice"]), "low_24h": float(d["lowPrice"]),
                "volume_24h": float(d["volume"]), "quote_volume_24h": float(d["quoteVolume"]),
                "open_24h": float(d["openPrice"]), "source": "binance_rest"}

def empty_candles() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp","open","high","low","close","volume","close_time","quote_volume","trades"])

def parse_klines(rows: list) -> pd.DataFrame:
    if not isinstance(rows, list):
        raise BinanceError(f"Klines malformed: mong đợi list, nhận {type(rows).__name__}")
    rows = [r for r in rows if isinstance(r, (list, tuple)) and len(r) >= 11]
    if not rows:
        return empty_candles()
    df = pd.DataFrame(rows, columns=KLINE_COLS).drop(columns=["ignore","taker_buy_volume","taker_buy_quote_volume"])
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = df["timestamp"].astype("int64"); df["close_time"] = df["close_time"].astype("int64")
    df = df.dropna(subset=["open","high","low","close","volume"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df
