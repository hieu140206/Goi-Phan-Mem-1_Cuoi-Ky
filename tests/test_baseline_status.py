"""Mốc nền: cần >= 5 phiên trước (config.toml), khung 9:15-9:30 riêng, z có phương án dự phòng, trạng thái chữ có lý do."""
import logging

import numpy as np
import pandas as pd
import pytest

from analytics import baseline
from analytics.baseline import STATUS_NA, STATUS_OK, _robust_z, bucket_label, detect_anomalies_tod, tod_bucket
from finance.liquidity import add_liquidity_metrics

TZ = "Asia/Ho_Chi_Minh"
DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"]   # 7 ngày thường


def build(days=DAYS, early_factor=1.0):
    """Một mã AAA, mỗi phút một lần chụp trong phiên liên tục. early_factor nhân độ sâu của khung 9:15-9:30."""
    rng = np.random.default_rng(1)
    rows = []
    for day in days:
        ts = pd.date_range(f"{day} 09:15", f"{day} 11:29", freq="1min", tz=TZ).append(
            pd.date_range(f"{day} 13:00", f"{day} 14:29", freq="1min", tz=TZ))
        for t in ts:
            q = 5000.0 * rng.lognormal(0, 0.1) * (early_factor if (t.hour == 9 and t.minute < 30) else 1.0)
            r = {"ts": t, "symbol": "AAA"}
            skew = rng.uniform(0.8, 1.25)           # bên bán dày hơn hoặc mỏng hơn bên mua một chút, như thật
            for i in (1, 2, 3):
                r[f"bid_px{i}"], r[f"ask_px{i}"] = 20_000.0 - (i - 1) * 50, 20_050.0 + (i - 1) * 50
                r[f"bid_qty{i}"], r[f"ask_qty{i}"] = q, q * skew
            rows.append(r)
    return add_liquidity_metrics(pd.DataFrame(rows))


def test_five_prior_sessions_needed_by_default():
    out = detect_anomalies_tod(build())
    day = out["ts"].dt.date.astype(str)
    for d in DAYS[:5]:                                           # 0 đến 4 phiên trước: chưa đủ
        sel = out[day == d]
        assert (sel["baseline_status"] == STATUS_NA).all() and sel["n_hist"].isna().all()
        assert sel["is_alert"].sum() == 0
    for d, n in ((DAYS[5], 5), (DAYS[6], 6)):
        sel = out[day == d]
        assert (sel["baseline_status"] == STATUS_OK).all() and sel["n_base_sessions"].eq(n).all()


def test_status_is_text_with_a_reason_never_blank():
    out = detect_anomalies_tod(build())
    assert out["baseline_status"].isin([STATUS_OK, STATUS_NA]).all()
    na = out[out["baseline_status"] == STATUS_NA]
    assert (na["baseline_reason"].str.len() > 0).all() and na["baseline_reason"].str.contains("cần ≥5 phiên").all()
    assert (out.loc[out["baseline_status"] == STATUS_OK, "baseline_reason"] == "").all()
    one = out[(out["ts"].dt.date.astype(str) == DAYS[2])].iloc[0]
    assert "hiện có 2" in one["baseline_reason"]                  # nêu số phiên đang có


def test_min_sessions_can_be_lowered_in_config_style():
    out = detect_anomalies_tod(build(), min_sessions=2)
    assert out.loc[out["ts"].dt.date.astype(str) == DAYS[2], "baseline_status"].eq(STATUS_OK).all()


def test_too_few_observations_in_bucket_is_not_enough_data():
    # Mỗi khung 30 phút có tới 30 lần chụp/phiên; đặt ngưỡng 10.000 lần chụp để chắc chắn thiếu.
    out = detect_anomalies_tod(build(), min_obs=10_000)
    assert (out["baseline_status"] == STATUS_NA).all()
    late = out[out["ts"].dt.date.astype(str) == DAYS[6]]
    assert late["baseline_reason"].str.contains("lần chụp hợp lệ").all()


def test_first_15_minutes_is_its_own_bucket():
    ts = pd.Series(pd.to_datetime(["2026-10-30 09:15", "2026-10-30 09:29", "2026-10-30 09:30", "2026-10-30 09:59",
                                   "2026-10-30 10:00", "2026-10-30 11:29"]).tz_localize(TZ))
    assert tod_bucket(ts).tolist() == [0, 0, 1, 1, 2, 4]
    assert [bucket_label(b) for b in (0, 1, 2, 4)] == ["09:15", "09:30", "10:00", "11:00"]


def test_depth_in_first_15_minutes_is_compared_only_with_itself():
    """Độ sâu 9:15-9:30 chỉ bằng 1/3 lúc khác, mỗi ngày như vậy: không phải bất thường."""
    out = detect_anomalies_tod(build(early_factor=1 / 3))
    assert out["is_alert"].sum() == 0
    first = out[(out["bucket"] == 0) & (out["baseline_status"] == STATUS_OK)]
    assert len(first) > 0 and first["z_depth"].abs().max() < 3


def test_log_when_first_bucket_depth_differs_from_next(caplog):
    with caplog.at_level(logging.WARNING, logger=baseline.log.name):
        detect_anomalies_tod(build(early_factor=1 / 3))
    assert any("Khung 9:15-9:30" in m for m in caplog.messages)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=baseline.log.name):
        detect_anomalies_tod(build(early_factor=1.0))
    assert not any("Khung 9:15-9:30" in m for m in caplog.messages)


def test_robust_z_equals_0_6745_formula():
    base = np.array([10.0, 12, 11, 15, 9, 13, 10, 14])
    x = np.array([20.0])
    z, fb = _robust_z(x, base)
    med, mad = np.median(base), np.median(np.abs(base - np.median(base)))
    assert z[0] == pytest.approx(0.6745 * (20 - med) / mad, rel=1e-3) and not fb[0]


def test_robust_z_with_zero_mad_falls_back_to_clipped_std_and_flags():
    base = np.array([5.0] * 19 + [6.0])                           # MAD = 0 nhưng độ lệch chuẩn > 0
    z, fb = _robust_z(np.array([1000.0, 5.0]), base, "robust", 10.0)
    assert z[0] == 10.0 and fb[0] and np.isfinite(z).all()        # kẹp ở +-10, đánh cờ dự phòng
    assert z[1] == 0.0 and fb[1]


def test_robust_z_with_constant_base_is_zero_and_flagged_not_nan():
    z, fb = _robust_z(np.array([7.0, np.nan]), np.array([7.0] * 30))
    assert z[0] == 0.0 and fb[0]
    assert np.isnan(z[1]) and not fb[1]                           # giá trị đầu vào thiếu thì vẫn thiếu, không bịa


def test_std_option():
    base = np.array([1.0, 2, 3, 4, 5])
    z, fb = _robust_z(np.array([3.0 + np.std(base)]), base, "std", 10.0)
    assert z[0] == pytest.approx(1.0) and not fb[0]


def test_fallback_column_exists_and_defaults_false_on_normal_data():
    out = detect_anomalies_tod(build())
    assert "z_fallback" in out and out["z_fallback"].dtype == bool
    assert not out["z_fallback"].any()
