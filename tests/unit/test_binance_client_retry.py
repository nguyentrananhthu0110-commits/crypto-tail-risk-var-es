"""Mục 12: chính sách retry — chỉ lỗi tạm thời mới retry; 422 không retry;
421 chuyển host; 429 tôn trọng Retry-After; malformed JSON được xử lý có giới hạn."""
import pytest
import requests
from src.data.binance_client import BinanceClient, BinanceError, parse_klines


class Resp:
    def __init__(self, status, payload=None, json_error=False, headers=None):
        self.status_code = status; self._payload = payload; self._err = json_error
        self.text = "fake-body"; self.headers = headers or {}
    def json(self):
        if self._err: raise ValueError("bad json")
        return self._payload


class Session:
    def __init__(self, queue):
        self.queue = list(queue); self.urls = []; self.headers = {}
    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        item = self.queue.pop(0)
        if isinstance(item, Exception): raise item
        return item


def make(queue):
    c = BinanceClient(bases=["https://a", "https://b"], timeout=1, max_retries=2)
    c.session = Session(queue)
    c._sleeps = []
    c._sleep = lambda attempt, retry_after=None: c._sleeps.append((attempt, retry_after))
    return c


def test_validation_error_422_not_retried():
    c = make([Resp(422)])
    with pytest.raises(BinanceError) as ei:
        c._get("/x", {})
    assert ei.value.status_code == 422
    assert len(c.session.urls) == 1  # không retry, không nhảy host


def test_429_retry_after_then_success():
    c = make([Resp(429, headers={"Retry-After": "3"}), Resp(200, {"ok": 1})])
    assert c._get("/x", {}) == {"ok": 1}
    assert c._sleeps and c._sleeps[0][1] == 3.0


def test_421_switches_host_without_same_host_retry():
    c = make([Resp(421), Resp(200, {"ok": 2})])
    assert c._get("/x", {}) == {"ok": 2}
    assert c.session.urls[0].startswith("https://a") and c.session.urls[1].startswith("https://b")
    assert len(c.session.urls) == 2


def test_5xx_bounded_retries_across_hosts():
    c = make([Resp(503)] * 6)
    with pytest.raises(BinanceError) as ei:
        c._get("/x", {})
    assert ei.value.status_code == 503
    assert len(c.session.urls) == 6  # (2 retries + 1) * 2 host — có giới hạn, không vô hạn


def test_timeout_then_success():
    c = make([requests.Timeout("t"), Resp(200, [1])])
    assert c._get("/x", {}) == [1]


def test_malformed_json_retried_then_success():
    c = make([Resp(200, json_error=True), Resp(200, {"ok": 3})])
    assert c._get("/x", {}) == {"ok": 3}


def test_parse_klines_malformed_rows_filtered_and_dict_rejected():
    good = [1704067200000, "1", "2", "0.5", "1.5", "10", 1704070799999, "15", 3, "1", "1", "0"]
    out = parse_klines([good, ["short"], "junk", None])
    assert len(out) == 1
    with pytest.raises(BinanceError):
        parse_klines({"code": -1121, "msg": "Invalid symbol"})
    assert parse_klines([]).empty
