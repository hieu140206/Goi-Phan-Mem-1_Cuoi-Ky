"""Mục A5: mã "Chú ý" vẫn được xếp hạng cùng mã "Đạt"; tập mã qua cổng dưới 10 thì cảnh báo mẫu nhỏ."""
import numpy as np
import pandas as pd

from analytics.screener import liquidity_gate, sample_warning, screen


def _run(n, watch=()):
    syms = [f"S{i}" for i in range(n)]
    r = pd.DataFrame({"symbol": syms, "score": [50.0 + i for i in range(n)]})
    f = pd.DataFrame({"symbol": syms, "foreign_ratio": np.arange(n, dtype=float), "mom_rel": np.arange(n, dtype=float)})
    return screen(f, liquidity_gate(r, pd.Series({s: 1 for s in watch}, dtype=float)))


def test_watch_symbols_are_ranked_together_with_pass():
    s = _run(5, watch=("S1",)).set_index("symbol")
    assert s.loc["S1", "gate"] == "Chú ý" and pd.notna(s.loc["S1", "screen_score"])
    assert s["screen_score"].notna().all()
    assert s.loc["S4", "screen_score"] == 100.0 and s.loc["S0", "screen_score"] == 0.0     # Chú ý nằm trong cùng thang hạng


def test_small_sample_warning_under_ten_passing_symbols():
    msg = sample_warning(_run(8))
    assert msg and "8 mã" in msg and "dưới 10" in msg and "kém ổn định" in msg
    assert sample_warning(_run(10)) is None and sample_warning(_run(12)) is None


def test_symbols_not_passing_the_gate_do_not_count_toward_the_sample():
    r = pd.DataFrame({"symbol": [f"S{i}" for i in range(12)], "score": [10.0] * 4 + [60.0] * 8})   # 4 mã bị Loại
    f = pd.DataFrame({"symbol": r["symbol"], "foreign_ratio": np.arange(12.0), "mom_rel": np.arange(12.0)})
    res = screen(f, liquidity_gate(r, pd.Series(dtype=float)))
    assert sample_warning(res) is not None and "8 mã" in sample_warning(res)


def test_custom_threshold():
    assert sample_warning(_run(8), min_n=5) is None
