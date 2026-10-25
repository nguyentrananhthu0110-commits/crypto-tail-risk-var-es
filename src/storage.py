"""Lưu trữ bền vững: Parquet (atomic replace) + manifest SQLite.

Nguyên tắc: ghi file tạm trong cùng thư mục rồi os.replace -> tiến trình bị ngắt
không làm hỏng dataset tốt gần nhất. Manifest chỉ cập nhật SAU khi file ghi thành công.
"""
from __future__ import annotations
import json, os, sqlite3, tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.config import MANIFEST_DB, METADATA_DIR

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".parquet", dir=str(path.parent))
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def atomic_write_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def read_parquet(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None

def parquet_state(path: Path) -> tuple[str, "pd.DataFrame | None"]:
    """Phân biệt 3 trạng thái file: missing | corrupt | ok (kèm DataFrame nếu ok)."""
    if not path.exists():
        return "missing", None
    try:
        return "ok", pd.read_parquet(path)
    except Exception:
        return "corrupt", None

def json_state(path: Path) -> tuple[str, dict | None]:
    if not path.exists():
        return "missing", None
    try:
        return "ok", json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "corrupt", None

def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

@contextmanager
def _db():
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(MANIFEST_DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS datasets(
          symbol TEXT, interval TEXT, source TEXT, start_ms INTEGER, end_ms INTEGER,
          rows INTEGER, last_update_utc TEXT, checkpoint_ms INTEGER,
          feature_version TEXT, model_version TEXT, status TEXT,
          PRIMARY KEY(symbol, interval));
        CREATE TABLE IF NOT EXISTS models(
          symbol TEXT, model_type TEXT, trained_at_utc TEXT, train_start TEXT, train_end TEXT,
          horizon_days INTEGER, file_path TEXT, metrics_json TEXT, status TEXT,
          model_version TEXT, feature_schema_json TEXT,
          PRIMARY KEY(symbol, model_type));
        CREATE TABLE IF NOT EXISTS jobs(
          run_id INTEGER PRIMARY KEY AUTOINCREMENT, job_type TEXT, symbol TEXT,
          started_at_utc TEXT, finished_at_utc TEXT, status TEXT, detail TEXT);
        """)
        yield con
        con.commit()
    finally:
        con.close()

def upsert_dataset(symbol, interval, source, start_ms, end_ms, rows, feature_version="", model_version="", status="ready"):
    with _db() as con:
        con.execute("""INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(symbol,interval) DO UPDATE SET source=excluded.source,start_ms=excluded.start_ms,
          end_ms=excluded.end_ms,rows=excluded.rows,last_update_utc=excluded.last_update_utc,
          checkpoint_ms=excluded.checkpoint_ms,feature_version=excluded.feature_version,
          model_version=excluded.model_version,status=excluded.status""",
          (symbol, interval, source, int(start_ms), int(end_ms), int(rows), utcnow_iso(),
           int(end_ms), feature_version, model_version, status))

def upsert_model(symbol, model_type, train_start, train_end, horizon, file_path, metrics, model_version, feature_schema):
    with _db() as con:
        con.execute("""INSERT INTO models VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(symbol,model_type) DO UPDATE SET trained_at_utc=excluded.trained_at_utc,
          train_start=excluded.train_start,train_end=excluded.train_end,file_path=excluded.file_path,
          metrics_json=excluded.metrics_json,status=excluded.status,model_version=excluded.model_version,
          feature_schema_json=excluded.feature_schema_json""",
          (symbol, model_type, utcnow_iso(), str(train_start), str(train_end), int(horizon),
           str(file_path), json.dumps(metrics, default=str), "ready", model_version,
           json.dumps(feature_schema, default=str)))

def log_job(job_type, symbol, status, detail="", started=None):
    with _db() as con:
        con.execute("INSERT INTO jobs(job_type,symbol,started_at_utc,finished_at_utc,status,detail) VALUES(?,?,?,?,?,?)",
                    (job_type, symbol, started or utcnow_iso(), utcnow_iso(), status, str(detail)[:2000]))

def get_datasets() -> list[dict]:
    with _db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM datasets ORDER BY symbol, interval")]

def get_models(symbol: str | None = None) -> list[dict]:
    with _db() as con:
        q = "SELECT * FROM models" + (" WHERE symbol=?" if symbol else "") + " ORDER BY symbol, model_type"
        rows = con.execute(q, (symbol,) if symbol else ()).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("metrics_json", "feature_schema_json"):
                try: d[k.replace("_json","")] = json.loads(d.pop(k) or "{}")
                except Exception: d[k.replace("_json","")] = {}
            out.append(d)
        return out

def get_last_jobs(limit: int = 10) -> list[dict]:
    with _db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY run_id DESC LIMIT ?", (limit,))]

def delete_symbol_records(symbol: str) -> None:
    """Xóa toàn bộ bản ghi manifest SQLite của một mã đã hủy niêm yết."""
    sym = symbol.upper()
    with _db() as con:
        con.execute("DELETE FROM datasets WHERE symbol=?", (sym,))
        con.execute("DELETE FROM models WHERE symbol=?", (sym,))
        con.execute("DELETE FROM jobs WHERE symbol=?", (sym,))
