import numpy as np
import pandas as pd
import pytest

from finance.factors import add_factors, daily_closes, momentum_n

TZ = "Asia/Ho_Chi_Minh"


def row(**kw):
    base = dict(last_px=29800.0, ref_px=29850.0, open_px=30000.0, high_px=30100.0, low_px=29800.0,
                foreign_net_val=-18_507_647_600.0, total_value=171_836_675_000.0)
    base.update(kw)
    return base


def test_factor_formulas_with_doc_sample():
    out = add_factors(pd.DataFrame([row()])).iloc[0]
    assert out["momentum_from_ref"] == pytest.approx(29800 / 29850 - 1)
    assert out["intraday_return"] == pytest.approx(29800 / 30000 - 1)
    assert out["range_position"] == pytest.approx(0.0)  # giá khớp bằng giá thấp nhất
    assert out["foreign_flow_ratio"] == pytest.approx(-18_507_647_600 / 171_836_675_000)
    assert out["foreign_flow_ratio"] < 0                # nước ngoài bán ròng


def test_range_position_is_nan_when_high_equals_low():
    out = add_factors(pd.DataFrame([row(high_px=29800.0, low_px=29800.0)])).iloc[0]
    assert np.isnan(out["range_position"])


def test_zero_denominators_give_nan_not_error():
    out = add_factors(pd.DataFrame([row(ref_px=0.0, open_px=0.0, total_value=0.0)])).iloc[0]
    assert np.isnan(out["momentum_from_ref"]) and np.isnan(out["intraday_return"]) and np.isnan(out["foreign_flow_ratio"])


def test_daily_close_and_multi_session_momentum():
    rows = []
    for d, px in enumerate([100.0, 102.0, 101.0, 105.0, 110.0, 120.0]):
        day = pd.Timestamp("2026-10-12", tz=TZ) + pd.Timedelta(days=d)
        rows.append({"ts": day + pd.Timedelta(hours=10), "symbol": "AAA", "last_px": px - 1})   # giữa ngày
        rows.append({"ts": day + pd.Timedelta(hours=14, minutes=20), "symbol": "AAA", "last_px": px})  # cuối ngày
    closes = daily_closes(pd.DataFrame(rows))
    assert closes["close"].tolist() == [100.0, 102.0, 101.0, 105.0, 110.0, 120.0]
    m = momentum_n(closes, 5)
    assert m["momentum_5"].iloc[:5].isna().all()          # chưa đủ 5 phiên lịch sử
    assert m["momentum_5"].iloc[5] == pytest.approx(120 / 100 - 1)
