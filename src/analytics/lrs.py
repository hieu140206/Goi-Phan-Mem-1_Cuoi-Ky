"""Điểm rủi ro thanh khoản (Liquidity Risk Score, LRS) theo thời gian.

  LRS = w1 * Z_spread - w2 * Z_depth + w3 * max(Z_|OBI|, 0)

  Z_spread: z-score cuốn chiếu của log spread tương đối   (spread phình to    -> rủi ro tăng)
  Z_depth : z-score cuốn chiếu của log độ sâu 3 mức giá     (độ sâu mỏng đi     -> rủi ro tăng, nên dấu trừ)
  Z_|OBI| : z-score cuốn chiếu của |mất cân bằng sổ lệnh|   (lệch về một phía   -> rủi ro tăng; chỉ tính phần dương)

Trọng số mặc định (0,4 / 0,4 / 0,2) là GIẢ ĐỊNH ban đầu, cho phép người dùng chỉnh trên giao diện.

Ngưỡng cảnh báo KHÔNG đặt cố định. LRS là tổng có trọng số của nhiều z-score nên không có phân phối
chuẩn tắc; nếu các thành phần độc lập, độ lệch chuẩn của LRS chỉ khoảng 0,6 và các mốc "1,5 / 2,5" sẽ hiếm hơn
nhiều so với phân vị 95% / 99%. Vì vậy ngưỡng lấy từ phân vị thực nghiệm của LRS trên chính dữ liệu thu được.
`lrs_thresholds` tính trên toàn bộ dữ liệu có sẵn nên chỉ để mô tả. Ứng dụng dùng `lrs_thresholds_past`:
tại mỗi thời điểm t, ngưỡng chỉ lấy từ các điểm LRS có trước t (gộp mọi mã), nên mức "Chú ý"/"Cao" của một lần
chụp không phụ thuộc dữ liệu đến sau nó (giống cách tính z-score cuốn chiếu).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.baseline import STATUS_NA
from model_config import section

_L = section("lrs")
DEFAULT_WEIGHTS = dict(_L["weights"])
MIN_OBS_FOR_THRESHOLD = _L["min_obs_describe"]
# Ngưỡng theo quá khứ cần ít nhất 300 điểm: với phân vị 99% còn khoảng 3 điểm nằm trên ngưỡng, ít hơn thì ngưỡng
# gần như chỉ là giá trị lớn nhất và rất dao động. 30 mã VN30 đủ 300 điểm sau khoảng 10 lần chụp có lịch sử.
MIN_OBS_PAST = _L["min_obs_past"]


def compute_lrs(df: pd.DataFrame, weights: dict[str, float] | None = None, min_periods: int = _L["min_periods"]) -> pd.Series:
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


def lrs_thresholds(lrs: pd.Series, q_watch: float = _L["q_watch"], q_high: float = _L["q_high"]) -> dict[str, float]:
    """Ngưỡng 'Chú ý' và 'Cao' = phân vị thực nghiệm của LRS. Trả NaN nếu quá ít dữ liệu."""
    s = lrs.dropna()
    if len(s) < MIN_OBS_FOR_THRESHOLD:
        return {"watch": np.nan, "high": np.nan}
    return {"watch": float(s.quantile(q_watch)), "high": float(s.quantile(q_high))}


def lrs_thresholds_past(lrs: pd.Series, ts: pd.Series, q_watch: float = _L["q_watch"], q_high: float = _L["q_high"],
                        min_obs: int = MIN_OBS_PAST, max_sessions: int | None = _L["max_sessions_past"]) -> pd.DataFrame:
    """Ngưỡng tại mỗi dòng = phân vị của mọi điểm LRS có thời điểm TRƯỚC thời điểm của dòng đó (không nhìn trước).

    Các mã chụp cùng thời điểm không dùng điểm của nhau. Chưa đủ `min_obs` điểm quá khứ thì ngưỡng là NaN.
    `max_sessions`: chỉ lấy điểm của tối đa chừng này phiên gần nhất tính đến thời điểm đang xét (gồm cả phiên đó, phần
    trước thời điểm); None hoặc <= 0 là không giới hạn (cửa sổ mở rộng từ đầu dữ liệu).
    Trả DataFrame cột watch, high, cùng index với `lrs`.
    """
    out = pd.DataFrame({"watch": np.nan, "high": np.nan}, index=lrs.index)
    has_ts = ts.notna()
    key = pd.Series(np.iinfo(np.int64).min, index=ts.index, dtype="int64")
    key[has_ts] = pd.to_datetime(ts[has_ts], utc=True).astype("int64")  # nano giây UTC, so sánh nhanh
    valid = lrs.notna() & has_ts
    order = np.argsort(key[valid].to_numpy(), kind="stable")
    past_key = key[valid].to_numpy()[order]
    past_val = lrs[valid].to_numpy(dtype=float)[order]
    # Tính ngưỡng một lần cho mỗi thời điểm khác nhau, rồi gán gộp cho mọi dòng (nhanh hơn ghi từng nhóm dòng bằng .loc).
    uniq = np.unique(key[has_ts].to_numpy())
    # Nửa đêm (giờ địa phương) của ngày chứa từng thời điểm, cùng đơn vị với `key`, để cắt đúng `max_sessions` phiên gần nhất.
    mid_key = pd.to_datetime(pd.to_datetime(ts[has_ts]).dt.normalize(), utc=True).astype("int64").to_numpy()
    days_sorted = np.unique(mid_key)
    mid_by_key = pd.Series(mid_key, index=key[has_ts].to_numpy()).groupby(level=0).first()
    day_pos = np.searchsorted(days_sorted, mid_by_key.reindex(uniq).to_numpy())
    keep = len(days_sorted) if not max_sessions or max_sessions <= 0 else int(max_sessions)
    first_day = days_sorted[np.maximum(0, day_pos - (keep - 1))]
    lo_arr = np.searchsorted(past_key, first_day, side="left")      # điểm đầu tiên của phiên cũ nhất còn được dùng
    n_past_arr = np.searchsorted(past_key, uniq, side="left")       # số điểm có thời điểm < t
    watch_t = np.full(len(uniq), np.nan)
    high_t = np.full(len(uniq), np.nan)
    for i in range(len(uniq)):
        lo, n_past = int(lo_arr[i]), int(n_past_arr[i])
        if n_past - lo < min_obs:
            continue
        watch_t[i], high_t[i] = np.quantile(past_val[lo:n_past], [q_watch, q_high])
    pos = np.searchsorted(uniq, key[has_ts].to_numpy())
    out.loc[has_ts, "watch"] = watch_t[pos]
    out.loc[has_ts, "high"] = high_t[pos]
    return out


def lrs_tier(lrs: pd.Series, thresholds) -> pd.Series:
    """'Cao' / 'Chú ý' / 'Bình thường'; 'Chưa đủ dữ liệu' khi chưa có điểm LRS hoặc chưa đủ điểm quá khứ để có ngưỡng.

    `thresholds` có watch/high là số (một ngưỡng chung) hoặc Series cùng index (ngưỡng riêng từng dòng).
    """
    out = pd.Series(STATUS_NA, index=lrs.index, dtype="object")
    watch = pd.Series(thresholds["watch"], index=lrs.index, dtype=float)
    high = pd.Series(thresholds["high"], index=lrs.index, dtype=float)
    valid = lrs.notna() & watch.notna()
    out[valid] = "Bình thường"
    out[valid & (lrs >= watch)] = "Chú ý"
    out[valid & (lrs >= high)] = "Cao"
    return out
