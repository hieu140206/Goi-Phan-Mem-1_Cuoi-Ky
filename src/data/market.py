"""Dữ liệu chỉ số thị trường từ NEO REST 4.2 (intradayMarketIndex) và 4.3 (marketIndexDetail).

Kiểm tra bằng dữ liệu thật 27/10/2026: 4.2 trả về chuỗi index[] mỗi phút một điểm (09:00:55 -> 15:05:05), kể cả
sau giờ giao dịch, nên trang Tổng quan vẽ được cả ngày VN30 mà không cần tự ghi điểm chỉ số.
indexTime trong index[] chỉ có giờ (HH:MM:SS), ngày lấy từ tham số trade_date.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from neo_api.config import TZ

# Ranh giới phiên HOSE (giờ Việt Nam). Mỗi điểm của 4.2 có giờ hh:mm:55 và gom giao dịch của phút đó, nên
# điểm 11:30:55 và 14:30:55 vẫn thuộc phiên liên tục (dữ liệu thật: còn khớp lệnh ở hai điểm này).
# Điểm sau 14:45:05 là giao dịch thỏa thuận (PT), không phải khớp lệnh.
PHASES = [
    (dt.time(0, 0), "Trước ATO"),
    (dt.time(9, 0), "ATO"),
    (dt.time(9, 15, 1), "Liên tục (sáng)"),
    (dt.time(11, 31), "Nghỉ trưa"),
    (dt.time(13, 0, 1), "Liên tục (chiều)"),
    (dt.time(14, 31), "ATC"),
    (dt.time(14, 45, 6), "Sau giờ / thỏa thuận"),
]


def phase_of(t: dt.time) -> str:
    label = PHASES[0][1]
    for start, name in PHASES:
        if t >= start:
            label = name
    return label


def index_intraday_frame(payload: dict, trade_date: dt.date | str) -> pd.DataFrame:
    """Chuỗi index[] của 4.2 -> bảng ts, index_value, total_volume, volume, phase (giờ Việt Nam)."""
    points = (payload or {}).get("index") or []
    if not points:
        return pd.DataFrame(columns=["ts", "index_code", "index_value", "total_volume", "volume", "phase"])
    df = pd.DataFrame(points).rename(columns={"indexValue": "index_value", "totalVolume": "total_volume"})
    day = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    df["ts"] = pd.to_datetime(day + " " + df["indexTime"].astype(str)).dt.tz_localize(TZ)
    df["index_code"] = payload.get("indexCode")
    df["phase"] = df["ts"].dt.time.map(phase_of)
    for c in ("index_value", "total_volume", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["ts", "index_code", "index_value", "total_volume", "volume", "phase"]].sort_values("ts").reset_index(drop=True)


def breadth_table(detail: list[dict]) -> pd.DataFrame:
    """4.3 -> bảng độ rộng thị trường. Bỏ 'FU' vì dữ liệu thật cho thấy nó lặp lại số của VN30."""
    df = pd.DataFrame(detail or [])
    if df.empty:
        return df
    df = df[df["indexCode"] != "FU"].copy()
    for c in ("advances", "declines", "noChange", "numberOfCe", "numberOfFl"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df.reset_index(drop=True)
