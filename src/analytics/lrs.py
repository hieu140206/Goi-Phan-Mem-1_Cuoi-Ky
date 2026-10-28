"""Điểm rủi ro thanh khoản (Liquidity Risk Score, LRS) theo thời gian.

  LRS = w1 * Z_spread - w2 * Z_depth + w3 * max(Z_|OBI|, 0)

  Z_spread: z-score cuốn chiếu của log spread tương đối   (spread phình to    -> rủi ro tăng)
  Z_depth : z-score cuốn chiếu của log độ sâu 3 mức giá     (độ sâu mỏng đi     -> rủi ro tăng, nên dấu trừ)
  Z_|OBI| : z-score cuốn chiếu của |mất cân bằng sổ lệnh|   (lệch về một phía   -> rủi ro tăng; chỉ tính phần dương)

Trọng số mặc định (0,4 / 0,4 / 0,2) là GIẢ ĐỊNH ban đầu, cho phép người dùng chỉnh trên giao diện.

Ngưỡng cảnh báo KHÔNG đặt cố định. LRS là tổng có trọng số của nhiều z-score nên không có phân phối
chuẩn tắc; nếu các thành phần độc lập, độ lệch chuẩn của LRS chỉ khoảng 0,6 và các mốc "1,5 / 2,5" sẽ hiếm hơn
nhiều so với phân vị 95% / 99%. Vì vậy ngưỡng lấy từ phân vị thực nghiệm của LRS trên chính dữ liệu thu được.
Ngưỡng tính trên toàn bộ dữ liệu có sẵn nên chỉ mô tả, không phải kiểm định ngoài mẫu.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {"spread": 0.4, "depth": 0.4, "imbalance": 0.2}
MIN_OBS_FOR_THRESHOLD = 50


def compute_lrs(df: pd.DataFrame, weights: dict[str, float] | None = None, min_periods: int = 20) -> pd.Series:
    """Tính LRS từ các cột z_spread, z_depth, z_imb và n_hist (do detect_anomalies tạo).

    Thành phần z bị thiếu vì độ lệch chuẩn bằng 0 (mã đứng yên) coi như không lệch (0).
    Các dòng chưa đủ lịch sử (n_hist < min_periods) trả NaN, không đưa ra điểm.
    """
    w = weights or DEFAULT_WEIGHTS
    zs = df["z_spread"].fillna(0)
    zd = df["z_depth"].fillna(0)
    zi = df["z_imb"].clip(lower=0).fillna(0)
    lrs = w["spread"] * zs - w["depth"] * zd + w["imbalance"] * zi
    return lrs.where(df["n_hist"] >= min_periods)


def lrs_thresholds(lrs: pd.Series, q_watch: float = 0.95, q_high: float = 0.99) -> dict[str, float]:
    """Ngưỡng 'Chú ý' và 'Cao' = phân vị thực nghiệm của LRS. Trả NaN nếu quá ít dữ liệu."""
    s = lrs.dropna()
    if len(s) < MIN_OBS_FOR_THRESHOLD:
        return {"watch": np.nan, "high": np.nan}
    return {"watch": float(s.quantile(q_watch)), "high": float(s.quantile(q_high))}


def lrs_tier(lrs: pd.Series, thresholds: dict[str, float]) -> pd.Series:
    """'Cao' / 'Chú ý' / 'Bình thường'; chuỗi rỗng khi chưa có điểm hoặc chưa có ngưỡng."""
    out = pd.Series("", index=lrs.index, dtype="object")
    if np.isnan(thresholds["watch"]):
        return out
    valid = lrs.notna()
    out[valid] = "Bình thường"
    out[valid & (lrs >= thresholds["watch"])] = "Chú ý"
    out[valid & (lrs >= thresholds["high"])] = "Cao"
    return out
