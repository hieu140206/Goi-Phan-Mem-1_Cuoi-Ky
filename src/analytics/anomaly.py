"""Phát hiện bất thường thanh khoản bằng z-score cuốn chiếu.

Nguyên tắc chống "nhìn trước tương lai": mean/std của lần chụp t chỉ tính từ các lần chụp TRƯỚC t
(shift(1)). Mỗi mã được so với chính lịch sử của nó, nên không bị lệch bởi khác biệt giữa các mã.

Cảnh báo cần đồng thời (a) vượt ngưỡng z và (b) thay đổi đủ lớn về kinh tế so với mức thường lệ.
Điều kiện (b) tránh báo động giả ở mã có spread gần như không đổi (độ lệch chuẩn rất nhỏ làm z phình to;
cộng một hằng số epsilon vào mẫu số không giải quyết được vấn đề này, nên dùng điều kiện tỷ lệ).
Mọi ngưỡng dưới đây là THAM SỐ MẶC ĐỊNH cần hiệu chỉnh trên dữ liệu thật và giải thích trong báo cáo.

Hàm cũng trả các cột z_spread, z_depth, z_imb và n_hist làm đầu vào cho điểm LRS (analytics/lrs.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_STD = 1e-9


def rolling_zscore(s: pd.Series, window: int = 60, min_periods: int = 20) -> pd.Series:
    past = s.shift(1)
    mean = past.rolling(window, min_periods=min_periods).mean()
    std = past.rolling(window, min_periods=min_periods).std(ddof=1)
    return ((s - mean) / std).where(std > MIN_STD)


def rolling_median_past(s: pd.Series, window: int = 60, min_periods: int = 20) -> pd.Series:
    return s.shift(1).rolling(window, min_periods=min_periods).median()


def detect_anomalies(
    df: pd.DataFrame,
    window: int = 60,
    threshold: float = 3.0,
    min_periods: int = 20,
    min_spread_ratio: float = 2.5,
    max_depth_ratio: float = 0.4,
) -> pd.DataFrame:
    """Thêm cột z_spread, z_depth, z_imb, n_hist, alert_type, severity, is_alert.

    Đầu vào cần có cột từ add_liquidity_metrics.
    """
    out = df.sort_values(["symbol", "ts"]).reset_index(drop=True).copy()
    out["log_spread"] = np.log(out["rel_spread_bps"].where(out["rel_spread_bps"] > 0))
    out["log_depth"] = np.log(out["depth_value"].where(out["depth_value"] > 0))
    out["abs_imb"] = out["imbalance"].abs()

    g = out.groupby("symbol")
    out["z_spread"] = g["log_spread"].transform(lambda s: rolling_zscore(s, window, min_periods))
    out["z_depth"] = g["log_depth"].transform(lambda s: rolling_zscore(s, window, min_periods))
    out["z_imb"] = g["abs_imb"].transform(lambda s: rolling_zscore(s, window, min_periods))
    out["n_hist"] = g["log_spread"].transform(lambda s: s.shift(1).rolling(window, min_periods=1).count())
    spread_med = g["rel_spread_bps"].transform(lambda s: rolling_median_past(s, window, min_periods))
    depth_med = g["depth_value"].transform(lambda s: rolling_median_past(s, window, min_periods))
    out["spread_ratio"] = out["rel_spread_bps"] / spread_med
    out["depth_ratio"] = out["depth_value"] / depth_med

    flag_spread = (out["z_spread"] >= threshold) & (out["spread_ratio"] >= min_spread_ratio)
    flag_depth = (out["z_depth"] <= -threshold) & (out["depth_ratio"] <= max_depth_ratio)
    out["alert_type"] = np.select(
        [flag_spread & flag_depth, flag_spread, flag_depth],
        ["Spread rộng, độ sâu mỏng", "Spread mở rộng", "Độ sâu mỏng"],
        default="",
    )
    strength = pd.concat([out["z_spread"].where(flag_spread), (-out["z_depth"]).where(flag_depth)], axis=1).max(axis=1)
    out["severity"] = np.where(strength >= threshold + 1.5, "Cao", np.where(strength.notna(), "Chú ý", ""))
    out["is_alert"] = flag_spread | flag_depth
    return out
