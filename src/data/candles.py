"""Nến ngày dự phòng từ bảng `board` của NEO (giá thật NEO đã ghi mỗi ngày), dùng khi không gọi được SSI.

Chỉ ĐỌC market.db. Mỗi ngày một dòng (ảnh chụp mới nhất của ngày): giá mở, cao, thấp là của cả ngày tính đến lúc chụp,
giá đóng là giá khớp lúc chụp. Ngày bộ ghi dừng trước 15:00 chưa có giá ATC nên được đánh dấu `partial`, không bỏ im lặng.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

COLUMNS = ["ts", "open", "high", "low", "close", "volume", "partial"]
FULL_AFTER = "14:59"          # ảnh chụp từ giờ này trở đi coi là đã gồm phiên ATC


def neo_daily_candles(db_path: Path, symbol: str) -> pd.DataFrame:
    """Nến ngày của một mã từ bảng board (mọi nhóm), tăng dần theo ngày. Thiếu bảng hoặc không có mã: bảng rỗng."""
    empty = pd.DataFrame(columns=COLUMNS)
    if not Path(db_path).exists():
        return empty
    try:
        conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
        try:
            raw = pd.read_sql_query(
                "SELECT day, ts, open_px, high_px, low_px, last_px, total_vol FROM board WHERE symbol = ? ORDER BY day",
                conn, params=(symbol,))
        finally:
            conn.close()
    except (sqlite3.Error, pd.errors.DatabaseError):
        return empty
    if raw.empty:
        return empty
    num = lambda c: pd.to_numeric(raw[c], errors="coerce")  # noqa: E731
    out = pd.DataFrame({
        "ts": pd.to_datetime(raw["day"], errors="coerce"),
        "open": num("open_px"), "high": num("high_px"), "low": num("low_px"), "close": num("last_px"), "volume": num("total_vol"),
        "partial": raw["ts"].astype(str).str[11:16] < FULL_AFTER,
    })
    out = out.dropna(subset=["ts", "open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return out.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
