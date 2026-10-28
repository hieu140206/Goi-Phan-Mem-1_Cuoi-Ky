"""Lưu và đọc dữ liệu sổ lệnh bằng SQLite. Dấu thời gian lưu dạng chuỗi ISO có +07:00."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .schema import QUOTE_COLUMNS


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cols = ", ".join(
        f"{c} TEXT" if c in ("ts", "symbol") else f"{c} REAL" for c in QUOTE_COLUMNS
    )
    conn.execute(f"CREATE TABLE IF NOT EXISTS quotes ({cols}, PRIMARY KEY (ts, symbol))")
    return conn


def save_quotes(df: pd.DataFrame, db_path: Path) -> int:
    """Ghi dữ liệu đã chuẩn hóa. Bản ghi trùng (ts, symbol) được bỏ qua. Trả về số dòng thực ghi."""
    if df.empty:
        return 0
    data = df[QUOTE_COLUMNS].copy()
    data["ts"] = data["ts"].map(lambda t: t.isoformat())
    placeholders = ", ".join("?" for _ in QUOTE_COLUMNS)
    with _connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR IGNORE INTO quotes ({', '.join(QUOTE_COLUMNS)}) VALUES ({placeholders})",
            data.astype(object).where(data.notna(), None).itertuples(index=False, name=None),
        )
        return conn.total_changes - before


def load_quotes(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame(columns=QUOTE_COLUMNS)
    with _connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM quotes ORDER BY symbol, ts", conn)


def count_rows(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
