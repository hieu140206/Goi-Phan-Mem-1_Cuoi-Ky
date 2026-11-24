"""Ngưỡng LRS (P95, P99) theo quá khứ: không nhìn trước, tối đa 20 phiên gần nhất, đủ 300 điểm mới công bố."""
import numpy as np
import pandas as pd
import pytest

from analytics.lrs import lrs_thresholds_past, lrs_tier

TZ = "Asia/Ho_Chi_Minh"


def make(n_days, per_day=40, n_sym=5, seed=0, day_scale=None):
    """Điểm LRS tổng hợp: mỗi phiên per_day thời điểm, mỗi thời điểm n_sym mã. day_scale[d] nhân điểm của ngày d."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2026-09-01", periods=n_days)
    rows = []
    for di, d in enumerate(days):
        for m in range(per_day):
            ts = pd.Timestamp(d.date().isoformat() + " 09:20", tz=TZ) + pd.Timedelta(minutes=m)
            for s in range(n_sym):
                v = rng.normal() * (day_scale[di] if day_scale else 1.0)
                rows.append((ts, f"S{s}", v))
    df = pd.DataFrame(rows, columns=["ts", "symbol", "lrs"])
    return df["lrs"], df["ts"], df


def test_thresholds_do_not_change_when_future_data_changes():
    lrs, ts, df = make(8)
    full = lrs_thresholds_past(lrs, ts)
    cut = pd.Timestamp("2026-09-08 10:00", tz=TZ)
    past = df["ts"] <= cut
    # kết quả chỉ trên dữ liệu đến cut phải GIỐNG HỆT kết quả trên dữ liệu dài hơn ở mọi dòng <= cut
    short = lrs_thresholds_past(lrs[past].reset_index(drop=True), ts[past].reset_index(drop=True))
    pd.testing.assert_frame_equal(short, full[past].reset_index(drop=True), check_exact=True)
    # và đổi hẳn dữ liệu tương lai thành số cực lớn cũng không làm đổi ngưỡng đã tính ở quá khứ
    wrecked = lrs.copy()
    wrecked[~past] = 1e9
    again = lrs_thresholds_past(wrecked, ts)
    pd.testing.assert_frame_equal(again[past], full[past], check_exact=True)


def test_snapshots_at_same_time_do_not_use_each_other():
    lrs, ts, df = make(3)
    thr = lrs_thresholds_past(lrs, ts, min_obs=1)
    first = df["ts"] == df["ts"].min()
    assert thr.loc[first, "watch"].isna().all()                   # lần chụp đầu tiên: chưa có quá khứ nào


def test_only_most_recent_sessions_are_used():
    # 30 phiên: 10 phiên đầu có điểm cực lớn (x1000), 20 phiên sau bình thường.
    scale = [1000.0] * 10 + [1.0] * 20
    lrs, ts, df = make(30, day_scale=scale)
    capped = lrs_thresholds_past(lrs, ts, max_sessions=20)
    unlimited = lrs_thresholds_past(lrs, ts, max_sessions=None)
    last = df["ts"] == df["ts"].max()
    # Ở thời điểm cuối, phiên cũ x1000 đã ra khỏi 20 phiên gần nhất nên ngưỡng nhỏ; không giới hạn thì còn bị kéo lên rất cao.
    assert capped.loc[last, "high"].iloc[0] < 10
    assert unlimited.loc[last, "high"].iloc[0] > 100
    # Đối chiếu trực tiếp: ngưỡng cuối = phân vị của các điểm trước thời điểm cuối trong đúng 20 phiên gần nhất.
    days = sorted(df["ts"].dt.date.unique())
    keep = days[-20:]
    t_last = df["ts"].max()
    window = df[(df["ts"].dt.date.isin(keep)) & (df["ts"] < t_last)]["lrs"].to_numpy()
    assert capped.loc[last, "watch"].iloc[0] == pytest.approx(np.quantile(window, 0.95))
    assert capped.loc[last, "high"].iloc[0] == pytest.approx(np.quantile(window, 0.99))


def test_cap_has_no_effect_when_fewer_sessions_than_cap():
    lrs, ts, _ = make(12)
    pd.testing.assert_frame_equal(lrs_thresholds_past(lrs, ts, max_sessions=20),
                                  lrs_thresholds_past(lrs, ts, max_sessions=None), check_exact=True)


def test_not_published_before_300_points_and_label_says_why():
    lrs, ts, df = make(3, per_day=20, n_sym=5)                    # 100 điểm mỗi phiên
    thr = lrs_thresholds_past(lrs, ts, min_obs=300)
    n_before = df.groupby("ts").size().cumsum().shift(fill_value=0).reindex(df["ts"]).to_numpy()
    assert thr["watch"].isna().to_numpy().tolist() == (n_before < 300).tolist()
    tier = lrs_tier(lrs, thr)
    assert (tier[thr["watch"].isna()] == "Chưa đủ dữ liệu").all()
    assert tier[thr["watch"].notna()].isin(["Bình thường", "Chú ý", "Cao"]).all()


def test_tier_label_for_missing_lrs_is_text_not_blank():
    tier = lrs_tier(pd.Series([np.nan, 1.0]), {"watch": 0.5, "high": 0.9})
    assert tier.tolist() == ["Chưa đủ dữ liệu", "Cao"]
