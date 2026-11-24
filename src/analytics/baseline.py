"""Phát hiện bất thường thanh khoản so với mức thường lệ CÙNG KHUNG GIỜ của chính mã đó ở các phiên trước.

Vì sao không dùng cửa sổ trượt 60 lần chụp (analytics/anomaly.py): thanh khoản có nhịp lặp lại trong ngày
(McInish & Wood 1992; Andersen & Bollerslev 1997). Trên dữ liệu VN30 thật 28-30/10/2026, độ sâu trung vị lúc
9:15-9:30 chỉ khoảng 5 tỷ đồng so với khoảng 14 tỷ lúc 14:00, nên cửa sổ trượt (mang theo dữ liệu chiều hôm trước)
làm 49% cảnh báo dồn vào 9:15-10:00. So với cùng khung giờ thì sáng chỉ được so với sáng.

Mốc so sánh (baseline) cho một lần chụp của mã s, phiên D, khung giờ b:
  mọi lần chụp của s trong khung b ở tối đa `max_sessions` phiên giao dịch TRƯỚC D (không dùng phiên D, không
  dùng tương lai). Cần ít nhất `min_sessions` phiên trước và `min_obs` lần chụp, nếu không thì để trống.
Khung giờ tính từ đầu mỗi buổi khớp lệnh liên tục: 9:15, 9:45, ... và 13:00, 13:30, ...

Cách đo độ lệch:
  - Độ sâu (log) và |mất cân bằng|: z bền vững = (x - trung vị) / (1,4826 * MAD) (Leys và cộng sự 2013).
    Trung vị và MAD không bị chính các giá trị bất thường kéo lệch như trung bình và độ lệch chuẩn.
  - Spread: KHÔNG dùng MAD vì spread VN30 phần lớn đúng 1 bước giá (85% lần chụp; khoảng 90% nhóm mã x khung 30 phút có MAD = 0, đo 28/10 đến 11/11/2026,
    chia cho 0). Dùng spread theo bước giá và tỷ lệ lần chụp lịch sử có spread >= hiện tại (`spread_tail_share`).
    z_spread (cho điểm LRS) = phân vị hạng giữa của giá trị hiện tại trong baseline, đổi sang thang chuẩn.

Điều kiện cảnh báo (mỗi điều kiện vừa có ý nghĩa thống kê vừa có ý nghĩa kinh tế):
  - Spread mở rộng: spread >= 2 bước giá, >= `min_spread_ratio` lần trung vị baseline, và chỉ <= `spread_tail`
    (5%) lần chụp lịch sử cùng khung giờ có spread rộng bằng hoặc hơn.
  - Độ sâu mỏng: z_depth <= -threshold và độ sâu <= `max_depth_ratio` lần trung vị baseline.
  - Kéo dài: điều kiện phải đúng ở >= `persist` lần chụp liên tiếp trong cùng buổi (sáng/chiều). Cảnh báo được
    gắn từ lần chụp thứ `persist` trở đi, nên vẫn chỉ dùng dữ liệu đến thời điểm đó.
Mọi tham số là mặc định có lý do nêu trên, cần hiệu chỉnh khi có thêm phiên.
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd

from model_config import section

_B = section("baseline")
MAD_TO_SD = _B["mad_scale"]  # hệ số đổi MAD sang độ lệch chuẩn khi phân phối chuẩn (config.toml)
MORNING_START = 9 * 60 + 15
AFTERNOON_START = 13 * 60
_NORM = NormalDist()


def tod_bucket(ts: pd.Series, minutes: int = 30) -> pd.Series:
    """Số thứ tự khung giờ trong ngày: buổi sáng 0, 1, 2... tính từ 9:15; buổi chiều 100, 101... tính từ 13:00."""
    m = ts.dt.hour * 60 + ts.dt.minute
    morning = m < 12 * 60
    return pd.Series(np.where(morning, (m - MORNING_START) // minutes, 100 + (m - AFTERNOON_START) // minutes),
                     index=ts.index).astype(int)


def bucket_label(bucket: int, minutes: int = 30) -> str:
    start = (MORNING_START + bucket * minutes) if bucket < 100 else (AFTERNOON_START + (bucket - 100) * minutes)
    return f"{start // 60:02d}:{start % 60:02d}"


def _robust_z(x: np.ndarray, base: np.ndarray) -> np.ndarray:
    base = base[np.isfinite(base)]
    if len(base) == 0:
        return np.full(len(x), np.nan)
    med = np.median(base)
    mad = np.median(np.abs(base - med)) * MAD_TO_SD
    return (x - med) / mad if mad > 0 else np.full(len(x), np.nan)


def _midrank_pct(x: np.ndarray, base_sorted: np.ndarray) -> np.ndarray:
    """Phân vị hạng giữa của x trong mẫu baseline (giá trị bằng nhau tính một nửa), kẹp trong (0, 1)."""
    n = len(base_sorted)
    below = np.searchsorted(base_sorted, x, side="left")
    equal = np.searchsorted(base_sorted, x, side="right") - below
    return np.clip((below + 0.5 * equal) / n, 0.5 / n, 1 - 0.5 / n)


def detect_anomalies_tod(
    df: pd.DataFrame,
    threshold: float = _B["z_threshold"],
    bucket_minutes: int = _B["bucket_minutes"],
    max_sessions: int = _B["max_sessions"],
    min_sessions: int = _B["min_baseline_sessions"],
    min_obs: int = _B["min_obs_per_bucket"],
    min_spread_ratio: float = _B["min_spread_ratio"],
    spread_tail: float = _B["spread_tail"],
    max_depth_ratio: float = _B["max_depth_ratio"],
    persist: int = _B["persist"],
    min_spread_ticks: float = _B["min_spread_ticks"],
    high_z_extra: float = _B["z_high_extra"],
    high_spread_ratio: float = _B["high_spread_ratio"],
    no_baseline_days: frozenset | set | None = None,
) -> pd.DataFrame:
    """Thêm các cột baseline, z_spread, z_depth, z_imb, n_hist, alert_type, severity, is_alert.

    Đầu vào cần có cột từ finance.liquidity.add_liquidity_metrics (spread_ticks, depth_value, imbalance).
    Cột n_hist, z_spread, z_depth, z_imb dùng chung tên với analytics.anomaly để tính điểm LRS.
    no_baseline_days: các ngày (datetime.date) KHÔNG được dùng làm mốc cho ngày khác (ví dụ phiên lấy từ nguồn SSI);
    chính các ngày đó vẫn được so với mốc là các phiên còn lại. Rỗng thì kết quả y hệt trước đây.
    """
    excl = set(no_baseline_days or ())
    out = df.sort_values(["symbol", "ts"]).reset_index(drop=True).copy()
    out["day"] = out["ts"].dt.date
    out["bucket"] = tod_bucket(out["ts"], bucket_minutes)
    log_depth = np.log(out["depth_value"].where(out["depth_value"] > 0)).to_numpy(dtype=float)
    abs_imb = out["imbalance"].abs().to_numpy(dtype=float)
    ticks = out["spread_ticks"].to_numpy(dtype=float)
    depth = out["depth_value"].to_numpy(dtype=float)

    cols = {c: np.full(len(out), np.nan) for c in
            ("n_hist", "n_base_sessions", "base_spread_ticks", "base_depth", "spread_ratio", "spread_tail_share",
             "depth_ratio", "z_spread", "z_depth", "z_imb")}

    for _, idx in out.groupby(["symbol", "bucket"]).indices.items():
        days = out["day"].to_numpy()[idx]
        uniq = sorted(set(days))
        for k, d in enumerate(uniq):
            prior = [x for x in uniq[:k] if x not in excl][-max_sessions:]
            if len(prior) < min_sessions:
                continue
            base = idx[np.isin(days, prior)]
            cur = idx[days == d]
            b_ticks = ticks[base][np.isfinite(ticks[base])]
            if len(b_ticks) < min_obs:
                continue
            b_sorted = np.sort(b_ticks)
            med_ticks = float(np.median(b_ticks))
            med_depth = float(np.nanmedian(depth[base]))
            cols["n_hist"][cur] = len(b_ticks)
            cols["n_base_sessions"][cur] = len(prior)
            cols["base_spread_ticks"][cur] = med_ticks
            cols["base_depth"][cur] = med_depth
            cols["spread_ratio"][cur] = ticks[cur] / med_ticks
            # Tỷ lệ lần chụp lịch sử có spread rộng BẰNG hoặc HƠN hiện tại (nhỏ = hiếm).
            cols["spread_tail_share"][cur] = 1 - np.searchsorted(b_sorted, ticks[cur], side="left") / len(b_sorted)
            cols["depth_ratio"][cur] = depth[cur] / med_depth if med_depth > 0 else np.nan
            pct = _midrank_pct(ticks[cur], b_sorted)
            cols["z_spread"][cur] = [_NORM.inv_cdf(p) if np.isfinite(t) else np.nan for p, t in zip(pct, ticks[cur])]
            cols["z_depth"][cur] = _robust_z(log_depth[cur], log_depth[base])
            cols["z_imb"][cur] = _robust_z(abs_imb[cur], abs_imb[base])

    for c, v in cols.items():
        out[c] = v
    # Chỗ nào chưa có baseline thì z cũng để trống (không tính được, không phải "bình thường").
    has_base = out["n_hist"].notna()

    flag_spread = (has_base & (out["spread_ticks"] >= min_spread_ticks) & (out["spread_ratio"] >= min_spread_ratio)
                   & (out["spread_tail_share"] <= spread_tail))
    flag_depth = has_base & (out["z_depth"] <= -threshold) & (out["depth_ratio"] <= max_depth_ratio)
    raw = flag_spread | flag_depth
    out["raw_flag"] = raw

    # Đếm số lần chụp liên tiếp đang thỏa điều kiện, trong cùng mã, cùng ngày, cùng buổi.
    half = out["ts"].dt.hour < 12
    run_id = (raw != raw.groupby([out["symbol"], out["day"], half]).shift(fill_value=False)).cumsum()
    run_len = raw.groupby(run_id).cumsum().where(raw, 0)
    out["is_alert"] = run_len >= persist
    out["alert_start"] = run_len == persist  # lần chụp mở đầu một đợt cảnh báo (để đếm số đợt)

    out["alert_type"] = np.select(
        [out["is_alert"] & flag_spread & flag_depth, out["is_alert"] & flag_spread, out["is_alert"] & flag_depth],
        ["Spread rộng, độ sâu mỏng", "Spread mở rộng", "Độ sâu mỏng"], default="")
    high = (flag_depth & (out["z_depth"] <= -(threshold + high_z_extra))) | (flag_spread & (out["spread_ratio"] >= high_spread_ratio))
    out["severity"] = np.where(out["is_alert"], np.where(high, "Cao", "Chú ý"), "")
    return out.drop(columns=["day"])
