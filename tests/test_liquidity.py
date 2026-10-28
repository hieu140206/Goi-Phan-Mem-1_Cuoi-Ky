import numpy as np
import pandas as pd
import pytest

from finance.liquidity import add_liquidity_metrics, rank_symbols


def make_row(symbol="AAA", bid1=99_900, ask1=100_100, bq=(1000, 1000, 1000), aq=(1000, 1000, 1000)):
    row = {"ts": pd.Timestamp("2026-10-22 09:00", tz="Asia/Ho_Chi_Minh"), "symbol": symbol}
    for i in (1, 2, 3):
        row[f"bid_px{i}"] = bid1 - (i - 1) * 100
        row[f"ask_px{i}"] = ask1 + (i - 1) * 100
        row[f"bid_qty{i}"] = bq[i - 1]
        row[f"ask_qty{i}"] = aq[i - 1]
    return row


def test_spread_and_relative_spread():
    df = add_liquidity_metrics(pd.DataFrame([make_row()]))
    assert df.loc[0, "mid"] == 100_000
    assert df.loc[0, "spread"] == 200
    assert df.loc[0, "rel_spread_bps"] == pytest.approx(20.0)  # 200/100000*10000


def test_depth_shares_and_value():
    df = add_liquidity_metrics(pd.DataFrame([make_row()]))
    assert df.loc[0, "depth_shares"] == 6000
    expected = 1000 * (99_900 + 99_800 + 99_700 + 100_100 + 100_200 + 100_300)
    assert df.loc[0, "depth_value"] == pytest.approx(expected)


def test_imbalance_sign_and_range():
    buy_heavy = add_liquidity_metrics(pd.DataFrame([make_row(bq=(3000, 3000, 3000), aq=(1000, 1000, 1000))]))
    assert buy_heavy.loc[0, "imbalance"] == pytest.approx(0.5)  # (9000-3000)/12000
    sell_heavy = add_liquidity_metrics(pd.DataFrame([make_row(bq=(1000, 0, 0), aq=(3000, 0, 0))]))
    assert sell_heavy.loc[0, "imbalance"] == pytest.approx(-0.5)


def test_imbalance_is_nan_when_no_depth():
    df = add_liquidity_metrics(pd.DataFrame([make_row(bq=(0, 0, 0), aq=(0, 0, 0))]))
    assert np.isnan(df.loc[0, "imbalance"])


def test_ranking_puts_liquid_symbol_higher():
    liquid = [make_row("GOOD", 99_950, 100_050, bq=(9000, 9000, 9000), aq=(9000, 9000, 9000))] * 5
    illiquid = [make_row("BAD", 99_000, 101_000, bq=(100, 100, 100), aq=(900, 900, 900))] * 5
    ranked = rank_symbols(add_liquidity_metrics(pd.DataFrame(liquid + illiquid)))
    scores = ranked.set_index("symbol")["score"]
    assert scores["GOOD"] > scores["BAD"]
    assert scores["GOOD"] == 100.0 and scores["BAD"] == 0.0
    assert ranked.iloc[0]["symbol"] == "BAD"  # xếp yếu nhất lên đầu


def test_ranking_single_symbol_does_not_crash():
    ranked = rank_symbols(add_liquidity_metrics(pd.DataFrame([make_row()])))
    assert len(ranked) == 1
