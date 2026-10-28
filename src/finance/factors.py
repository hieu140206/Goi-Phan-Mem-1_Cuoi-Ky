"""Các yếu tố bổ sung cho bộ lọc đa yếu tố: động lượng và dòng tiền nước ngoài.

Công thức trong phiên (theo tài liệu NEO, từ trường stockInfo):
  momentum_from_ref = giá khớp / giá tham chiếu - 1
  intraday_return   = giá khớp / giá mở cửa - 1
  range_position    = (giá khớp - thấp nhất) / (cao nhất - thấp nhất)     (NaN khi cao nhất = thấp nhất)
  foreign_flow_ratio = giá trị nước ngoài mua-bán ròng / tổng giá trị giao dịch    (> 0: nước ngoài mua ròng)

Động lượng nhiều phiên (5/10/20 phiên) KHÔNG lấy được từ NEO (tài liệu chưa công bố giá lịch sử nhiều ngày),
nên phải tự lưu giá đóng cửa mỗi ngày: xem `daily_closes` và `momentum_n`.

Giả định cần kiểm tra trên dữ liệu thật: foreignNetValue và totalTradingValue là số LŨY KẾ trong ngày.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.where(b != 0)


def add_factors(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["momentum_from_ref"] = _safe_div(out["last_px"], out["ref_px"]) - 1
    out["intraday_return"] = _safe_div(out["last_px"], out["open_px"]) - 1
    out["range_position"] = _safe_div(out["last_px"] - out["low_px"], out["high_px"] - out["low_px"])
    out["foreign_flow_ratio"] = _safe_div(out["foreign_net_val"], out["total_value"])
    return out


def daily_closes(df: pd.DataFrame) -> pd.DataFrame:
    """Giá khớp cuối cùng của mỗi mã trong mỗi ngày (dùng để tự xây chuỗi giá nhiều phiên)."""
    d = df.dropna(subset=["last_px"]).sort_values("ts")
    day = d["ts"].dt.date
    out = d.groupby([d["symbol"], day]).tail(1)
    return out.assign(day=out["ts"].dt.date)[["symbol", "day", "last_px"]].rename(
        columns={"last_px": "close"}).reset_index(drop=True)


def momentum_n(closes: pd.DataFrame, n: int) -> pd.DataFrame:
    """Động lượng n phiên = close hôm nay / close cách đây n phiên - 1, theo từng mã. Cần ít nhất n+1 phiên."""
    c = closes.sort_values(["symbol", "day"]).copy()
    prev = c.groupby("symbol")["close"].shift(n)
    c[f"momentum_{n}"] = np.where(prev > 0, c["close"] / prev - 1, np.nan)
    return c
