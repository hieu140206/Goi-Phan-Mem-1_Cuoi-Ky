"""Tỷ lệ hấp thụ của sổ lệnh: so khối lượng thực sự khớp với độ dày sổ lệnh đang chờ.

  delta_vol  = tổng khối lượng khớp lũy kế (trong ngày) tại t  -  tại lần chụp trước, cùng mã, cùng ngày
  absorption = delta_vol / độ sâu 3 mức (cổ phiếu)

Dùng trường `total_vol` (tổng khối lượng khớp lũy kế trong ngày). Cần xác nhận NEO có trường tương đương
và nó lũy kế thật; nếu giảm giữa hai lần chụp (đặt lại hoặc lỗi dữ liệu) thì coi là thiếu.

Cờ `thin_no_trade`: độ sâu rút mỏng mạnh (<= 40% trung vị lịch sử) trong khi gần như không có giao dịch
(delta_vol <= 10% mức trung vị lịch sử). Đây chỉ là dấu hiệu thanh khoản "mỏng mà không khớp",
KHÔNG đủ để kết luận có ai hủy lệnh ảo hay thao túng: nhà đầu tư thường cũng rút lệnh vì nhiều lý do.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_absorption(
    df: pd.DataFrame,
    window: int = 60,
    min_periods: int = 20,
    depth_ratio_max: float = 0.4,
    quiet_ratio: float = 0.1,
) -> pd.DataFrame:
    out = df.sort_values(["symbol", "ts"]).reset_index(drop=True).copy()
    day = out["ts"].dt.date
    out["delta_vol"] = out.groupby([out["symbol"], day])["total_vol"].diff()
    out.loc[out["delta_vol"] < 0, "delta_vol"] = np.nan
    out["absorption"] = out["delta_vol"] / out["depth_shares"].where(out["depth_shares"] > 0)

    g = out.groupby("symbol")
    med_dv = g["delta_vol"].transform(lambda s: s.shift(1).rolling(window, min_periods=min_periods).median())
    med_depth = g["depth_shares"].transform(lambda s: s.shift(1).rolling(window, min_periods=min_periods).median())
    thin = out["depth_shares"] <= depth_ratio_max * med_depth
    quiet = (med_dv > 0) & (out["delta_vol"] <= quiet_ratio * med_dv)
    out["thin_no_trade"] = (thin & quiet).fillna(False)
    return out
