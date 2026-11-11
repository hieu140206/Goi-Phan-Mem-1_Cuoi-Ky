"""Tỷ lệ hấp thụ của sổ lệnh: so khối lượng thực sự khớp với độ dày sổ lệnh đang chờ.

  delta_vol  = tổng khối lượng khớp lũy kế (trong ngày) tại t  -  tại lần chụp trước, cùng mã, cùng ngày
  absorption = delta_vol / độ sâu 3 mức (cổ phiếu)

Dùng trường `total_vol` (tổng khối lượng khớp lũy kế trong ngày). Cần xác nhận NEO có trường tương đương
và nó lũy kế thật; nếu giảm giữa hai lần chụp (đặt lại hoặc lỗi dữ liệu) thì coi là thiếu.

Cờ `thin_no_trade`: độ sâu rút mỏng mạnh (<= 40% trung vị lịch sử) trong khi gần như không có giao dịch
(delta_vol <= 10% mức trung vị lịch sử). Đây chỉ là dấu hiệu thanh khoản "mỏng mà không khớp",
KHÔNG đủ để kết luận có ai hủy lệnh ảo hay thao túng: nhà đầu tư thường cũng rút lệnh vì nhiều lý do.

Trung vị lịch sử: nếu dữ liệu có cột `bucket` (khung giờ 30 phút, do analytics.baseline tạo) thì so với các lần chụp CÙNG
mã, CÙNG khung giờ ở tối đa `max_sessions` phiên trước (như cảnh báo ở Radar). Không có `bucket` thì dùng cửa sổ trượt
`window` lần chụp gần nhất. Cửa sổ trượt xuyên ngày làm đầu phiên luôn bị so với chiều hôm trước (sổ lệnh đầu phiên vốn
mỏng và ít khớp): đo trên dữ liệu 28/10 đến 11/11/2026, cờ này rơi 4,1% ở 9:00-9:30 so với khoảng 0,1% các giờ còn lại.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _tod_median(df: pd.DataFrame, col: str, max_sessions: int, min_sessions: int, min_obs: int) -> pd.Series:
    """Trung vị của `col` ở cùng mã, cùng khung giờ (`bucket`), tối đa `max_sessions` phiên TRƯỚC phiên của dòng đó.
    Trống nếu có ít hơn `min_sessions` phiên trước hoặc ít hơn `min_obs` giá trị (không dùng phiên hiện tại hay tương lai)."""
    out = np.full(len(df), np.nan)
    vals = df[col].to_numpy(dtype=float)
    days = df["ts"].dt.date.to_numpy()
    for _, idx in df.groupby(["symbol", "bucket"]).indices.items():
        d_here = days[idx]
        uniq = sorted(set(d_here))
        for k, d in enumerate(uniq):
            prior = uniq[max(0, k - max_sessions):k]
            if len(prior) < min_sessions:
                continue
            base = vals[idx[np.isin(d_here, prior)]]
            base = base[np.isfinite(base)]
            if len(base) < min_obs:
                continue
            out[idx[d_here == d]] = np.median(base)
    return pd.Series(out, index=df.index)


def add_absorption(
    df: pd.DataFrame,
    window: int = 60,
    min_periods: int = 20,
    depth_ratio_max: float = 0.4,
    quiet_ratio: float = 0.1,
    max_sessions: int = 10,
    min_sessions: int = 2,
) -> pd.DataFrame:
    out = df.sort_values(["symbol", "ts"]).reset_index(drop=True).copy()
    day = out["ts"].dt.date
    out["delta_vol"] = out.groupby([out["symbol"], day])["total_vol"].diff()
    out.loc[out["delta_vol"] < 0, "delta_vol"] = np.nan
    out["absorption"] = out["delta_vol"] / out["depth_shares"].where(out["depth_shares"] > 0)

    if "bucket" in out.columns:
        med_dv = _tod_median(out, "delta_vol", max_sessions, min_sessions, min_periods)
        med_depth = _tod_median(out, "depth_shares", max_sessions, min_sessions, min_periods)
    else:
        g = out.groupby("symbol")
        med_dv = g["delta_vol"].transform(lambda s: s.shift(1).rolling(window, min_periods=min_periods).median())
        med_depth = g["depth_shares"].transform(lambda s: s.shift(1).rolling(window, min_periods=min_periods).median())
    thin = out["depth_shares"] <= depth_ratio_max * med_depth
    quiet = (med_dv > 0) & (out["delta_vol"] <= quiet_ratio * med_dv)
    out["thin_no_trade"] = (thin & quiet).fillna(False)
    return out
