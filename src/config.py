"""Cấu hình tập trung. Đường dẫn luôn suy ra từ vị trí project, không hardcode máy người dùng."""
from __future__ import annotations
import json, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"

def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["host"] = os.environ.get("CRI_HOST", cfg.get("host", "127.0.0.1"))
    cfg["port"] = int(os.environ.get("CRI_PORT", cfg.get("port", 8765)))
    return cfg

CONFIG = load_config()
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR, PROCESSED_DIR, FEATURES_DIR = DATA_DIR/"raw", DATA_DIR/"processed", DATA_DIR/"features"
METADATA_DIR, CACHE_DIR = DATA_DIR/"metadata", DATA_DIR/"cache"
MODELS_DIR = PROJECT_ROOT / "models"
SAVED_DIR, MODEL_META_DIR = MODELS_DIR/"saved", MODELS_DIR/"metadata"
LOGS_DIR = PROJECT_ROOT / "logs"
MANIFEST_DB = METADATA_DIR / "manifest.sqlite"

INTERVAL_MS = {"1m":60_000,"3m":180_000,"5m":300_000,"15m":900_000,"30m":1_800_000,
               "1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"1d":86_400_000,
               "1w":604_800_000}

for _d in (RAW_DIR, PROCESSED_DIR, FEATURES_DIR, METADATA_DIR, CACHE_DIR, SAVED_DIR, MODEL_META_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

def dataset_path(symbol: str, interval: str) -> Path:
    return RAW_DIR / f"{symbol.upper()}_{interval}.parquet"
