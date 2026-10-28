import numpy as np
import pandas as pd
import pytest

from analytics.anomaly import detect_anomalies
from analytics.lrs import DEFAULT_WEIGHTS, compute_lrs, lrs_thresholds, lrs_tier
from finance.absorption import add_absorption
from finance.liquidity import add_liquidity_metrics
from test_anomaly import build


def test_lrs_formula_signs_and_weights():
    df = pd.DataFrame({"z_spread": [2.0], "z_depth": [-1.0], "z_imb": [1.0], "n_hist": [30]})
    # 0,4*2 - 0,4*(-1) + 0,2*1 = 0,8 + 0,4 + 0,2
    assert compute_lrs(df).iloc[0] == pytest.approx(1.4)


def test_lrs_imbalance_only_adds_risk():
    df = pd.DataFrame({"z_spread": [0.0], "z_depth": [0.0], "z_imb": [-3.0], "n_hist": [30]})
    assert compute_lrs(df).iloc[0] == 0.0  # sổ lệnh cân bằng hơn thường lệ không làm giảm rủi ro


def test_lrs_nan_during_warmup_and_nan_z_treated_as_zero():
    df = pd.DataFrame({"z_spread": [np.nan, np.nan], "z_depth": [np.nan, np.nan], "z_imb": [np.nan, np.nan],
                       "n_hist": [5, 30]})
    out = compute_lrs(df)
    assert np.isnan(out.iloc[0]) and out.iloc[1] == 0.0


def test_lrs_custom_weights():
    df = pd.DataFrame({"z_spread": [1.0], "z_depth": [0.0], "z_imb": [0.0], "n_hist": [30]})
    assert compute_lrs(df, {"spread": 1.0, "depth": 0.0, "imbalance": 0.0}).iloc[0] == 1.0


def test_thresholds_are_empirical_quantiles():
    s = pd.Series(np.arange(1000, dtype=float))
    thr = lrs_thresholds(s)
    assert thr["watch"] == pytest.approx(s.quantile(0.95))
    assert thr["high"] == pytest.approx(s.quantile(0.99))


def test_thresholds_nan_when_too_little_data():
    thr = lrs_thresholds(pd.Series([1.0, 2.0, 3.0]))
    assert np.isnan(thr["watch"])
    assert (lrs_tier(pd.Series([1.0, 2.0]), thr) == "").all()


def test_tier_assignment():
    thr = {"watch": 1.0, "high": 2.0}
    tiers = lrs_tier(pd.Series([0.5, 1.0, 2.5, np.nan]), thr)
    assert tiers.tolist() == ["Bình thường", "Chú ý", "Cao", ""]


def test_lrs_flags_spike_end_to_end():
    an = detect_anomalies(build(spike_at=90))
    an["lrs"] = compute_lrs(an)
    assert an["lrs"].idxmax() == 90
    assert an.loc[90, "lrs"] > 3 * an["lrs"].drop(90).abs().max()


def make_flow(n=100, depth_drop_at=None, trade_at_drop=False, seed=3):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-10-22 09:15", periods=n, freq="1min", tz="Asia/Ho_Chi_Minh")
    rows, cum = [], 0.0
    for i, t in enumerate(ts):
        q = 5000.0 * rng.lognormal(0, 0.05)
        dv = 800.0 * rng.lognormal(0, 0.2)
        if i == depth_drop_at:
            q *= 0.1
            dv = 800.0 if trade_at_drop else 0.0
        cum += dv
        r = {"ts": t, "symbol": "AAA", "total_vol": cum}
        for k in (1, 2, 3):
            r[f"bid_px{k}"] = 99_900 - (k - 1) * 100
            r[f"ask_px{k}"] = 100_100 + (k - 1) * 100
            r[f"bid_qty{k}"] = q
            r[f"ask_qty{k}"] = q
        rows.append(r)
    return add_liquidity_metrics(pd.DataFrame(rows))


def test_absorption_value():
    out = add_absorption(make_flow())
    row = out.iloc[50]
    assert row["absorption"] == pytest.approx(row["delta_vol"] / row["depth_shares"])


def test_thin_book_without_trades_is_flagged():
    out = add_absorption(make_flow(depth_drop_at=80))
    assert out.loc[80, "thin_no_trade"]
    assert out["thin_no_trade"].sum() == 1


def test_thin_book_with_trades_is_not_flagged():
    out = add_absorption(make_flow(depth_drop_at=80, trade_at_drop=True))
    assert not out["thin_no_trade"].any()


def test_cumulative_reset_is_treated_as_missing():
    df = make_flow()
    df.loc[60:, "total_vol"] -= df.loc[60, "total_vol"] - 10  # tổng lũy kế bất ngờ giảm
    out = add_absorption(df)
    assert np.isnan(out.loc[60, "delta_vol"])


def test_new_day_does_not_diff_across_days():
    a = make_flow(n=30)
    b = make_flow(n=30)
    b["ts"] = b["ts"] + pd.Timedelta(days=1)
    out = add_absorption(pd.concat([a, b], ignore_index=True))
    first_of_day2 = out[out["ts"] == b["ts"].iloc[0]].iloc[0]
    assert np.isnan(first_of_day2["delta_vol"])
