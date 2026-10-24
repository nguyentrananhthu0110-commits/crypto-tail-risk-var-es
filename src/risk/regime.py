"""Volatility regime theo phân vị của realized vol trên tập TRAIN (quy tắc xác định trước,
không hardcode ngưỡng tuyệt đối tuỳ tiện)."""
from __future__ import annotations
import numpy as np

LABELS = {
    "low": {"vi": "Thấp", "desc": "Biến động thấp hơn phần lớn lịch sử tham chiếu; dao động giá thường hẹp hơn mức quen thuộc."},
    "normal": {"vi": "Bình thường", "desc": "Biến động nằm trong vùng thường gặp trong lịch sử tham chiếu."},
    "elevated": {"vi": "Cao hơn bình thường", "desc": "Biến động cao hơn mức thường gặp; khoảng dao động và độ bất định có xu hướng lớn hơn."},
    "high": {"vi": "Cao / Stress", "desc": "Biến động thuộc nhóm cao nhất lịch sử tham chiếu; mức lỗ tiềm tàng và độ bất định tăng rõ. Đây không phải bằng chứng giá nhất thiết sẽ giảm."},
}

def fit_thresholds(train_daily_vol) -> dict:
    v = np.asarray(train_daily_vol, float); v = v[np.isfinite(v)]
    return {"q25": float(np.quantile(v, .25)), "q75": float(np.quantile(v, .75)),
            "q90": float(np.quantile(v, .90)),
            "rule": "Low<q25 | Normal q25-q75 | Elevated q75-q90 | High/Stress>q90 (phân vị realized vol tập train)"}

def classify(vol_daily: float, thresholds: dict, train_daily_vol=None) -> dict:
    if vol_daily < thresholds["q25"]: key = "low"
    elif vol_daily <= thresholds["q75"]: key = "normal"
    elif vol_daily <= thresholds["q90"]: key = "elevated"
    else: key = "high"
    pct = None
    if train_daily_vol is not None:
        v = np.asarray(train_daily_vol, float); v = v[np.isfinite(v)]
        pct = float(np.mean(v <= vol_daily) * 100)
    return {"regime": key, "label_vi": LABELS[key]["vi"], "description": LABELS[key]["desc"],
            "percentile_vs_train": pct, "thresholds": thresholds}
