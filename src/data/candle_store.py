"""Kho nến OHLC lấy từ SSI, nằm ở tệp RIÊNG data/candles.db (không phải market.db: không đụng dữ liệu NEO dùng để tính toán).

Chỉ phục vụ HIỂN THỊ biểu đồ nến. Không đưa vào tính điểm, cảnh báo hay xếp hạng. Giá ngày cũ của SSI có thể đã điều chỉnh cổ tức, nên nến ngày được
NẠP LẠI TOÀN BỘ chuỗi của mã mỗi lần (replace=True); nến trong phiên thì cộng dồn (replace=False) để lịch sử dài hơn thời gian SSI còn giữ.
Thời gian lưu dạng chữ 'YYYY-MM-DD HH:MM:SS' theo giờ Việt Nam (nến ngày là 00:00:00).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "candles.db"
COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
  frame TEXT NOT NULL, symbol TEXT NOT NULL, ts TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (frame, symbol, ts));
CREATE TABLE IF NOT EXISTS candle_meta (
  frame TEXT NOT NULL, symbol TEXT NOT NULL, fetched_at TEXT NOT NULL, rows INTEGER NOT NULL,
  first_ts TEXT, last_ts TEXT, PRIMARY KEY (frame, symbol));
"""


def _stamp(ts: pd.Series) -> list[str]:
    return pd.to_datetime(ts).dt.strftime("%Y-%m-%d %H:%M:%S").tolist()


def save_candles(db_path: Path, frame: str, symbol: str, df: pd.DataFrame, fetched_at: str, replace: bool = False) -> int:
    """Ghi nến của một mã. replace=True xóa nến cũ của (khung, mã) trước (dùng cho nến ngày vì SSI điều chỉnh giá cũ); False thì ghi đè theo
    từng thời điểm và giữ phần cũ. Bảng rỗng thì KHÔNG xóa gì (lỗi mạng hay SSI trả rỗng không được làm mất dữ liệu đã lưu). Trả về số dòng ghi."""
    if df is None or df.empty:
        return 0
    rows = list(zip([frame] * len(df), [symbol] * len(df), _stamp(df["ts"]), *(df[c].astype(float).tolist() for c in COLUMNS[1:])))
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        with conn:
            if replace:
                conn.execute("DELETE FROM candles WHERE frame = ? AND symbol = ?", (frame, symbol))
            conn.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", rows)
            n, lo, hi = conn.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM candles WHERE frame = ? AND symbol = ?", (frame, symbol)).fetchone()
            conn.execute("INSERT OR REPLACE INTO candle_meta VALUES (?,?,?,?,?,?)", (frame, symbol, fetched_at, n, lo, hi))
    finally:
        conn.close()
    return len(rows)


def _connect_ro(db_path: Path) -> sqlite3.Connection | None:
    p = Path(db_path)
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True) if p.exists() else None


def load_candles(db_path: Path, frame: str, symbol: str) -> pd.DataFrame:
    """Nến đã lưu của một mã, tăng dần theo thời gian (giá bằng đồng). Thiếu tệp hoặc chưa có: bảng rỗng. Chỉ đọc."""
    empty = pd.DataFrame(columns=COLUMNS)
    conn = _connect_ro(db_path)
    if conn is None:
        return empty
    try:
        df = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM candles WHERE frame = ? AND symbol = ? ORDER BY ts",
                               conn, params=(frame, symbol))
    except (sqlite3.Error, pd.errors.DatabaseError):
        return empty
    finally:
        conn.close()
    if df.empty:
        return empty
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def last_ts(db_path: Path, frame: str, symbol: str) -> pd.Timestamp | None:
    """Thời điểm nến mới nhất đã lưu (để lần sau chỉ lấy phần mới); chưa có thì None."""
    conn = _connect_ro(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT last_ts FROM candle_meta WHERE frame = ? AND symbol = ?", (frame, symbol)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return pd.Timestamp(row[0]) if row and row[0] else None
