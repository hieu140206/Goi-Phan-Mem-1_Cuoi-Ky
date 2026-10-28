import numpy as np
import pandas as pd

from analytics.anomaly import detect_anomalies, rolling_zscore
from finance.liquidity import add_liquidity_metrics


def build(n=120, spike_at=None, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-10-22 09:00", periods=n, freq="5min", tz="Asia/Ho_Chi_Minh")
    spread = np.full(n, 100.0) + rng.normal(0, 3, n)
    qty = 5000.0 * rng.lognormal(0, 0.1, n)
    if spike_at is not None:
        spread[spike_at] *= 5
        qty[spike_at] *= 0.1
    rows = []
    for t, s, q in zip(ts, spread, qty):
        r = {"ts": t, "symbol": "AAA"}
        for i in (1, 2, 3):
            r[f"bid_px{i}"] = 100_000 - s / 2 - (i - 1) * 100
            r[f"ask_px{i}"] = 100_000 + s / 2 + (i - 1) * 100
            r[f"bid_qty{i}"] = q
            r[f"ask_qty{i}"] = q
        rows.append(r)
    return add_liquidity_metrics(pd.DataFrame(rows))


def test_zscore_does_not_look_ahead():
    s = pd.Series(np.random.default_rng(1).normal(10, 1, 100))
    z1 = rolling_zscore(s, window=30, min_periods=10)
    s2 = s.copy()
    s2.iloc[80:] = 1_000.0  # thay đổi tương lai
    z2 = rolling_zscore(s2, window=30, min_periods=10)
    pd.testing.assert_series_equal(z1.iloc[:80], z2.iloc[:80])


def test_constant_series_gives_nan_not_error():
    z = rolling_zscore(pd.Series([5.0] * 50), window=30, min_periods=10)
    assert z.isna().all()


def test_spike_is_detected_and_quiet_data_is_not():
    quiet = detect_anomalies(build())
    assert not quiet["is_alert"].any()
    spiky = detect_anomalies(build(spike_at=90))
    flagged = spiky.loc[spiky["is_alert"], "ts"]
    assert len(flagged) == 1
    assert flagged.iloc[0] == spiky.loc[90, "ts"]
    assert spiky.loc[90, "alert_type"] == "Spread rộng, độ sâu mỏng"


def test_warmup_period_has_no_alerts():
    out = detect_anomalies(build(spike_at=5))  # quá sớm, chưa đủ lịch sử
    assert not out.loc[:10, "is_alert"].any()
