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


def test_tick_size_hose_bands():
    from finance.liquidity import tick_size
    ticks = tick_size(pd.Series([9_990, 10_000, 49_950, 50_000, 240_000, 0, np.nan]))
    assert ticks.tolist()[:5] == [10, 50, 50, 100, 100]
    assert ticks.iloc[5:].isna().all()


def test_spread_ticks_uses_tick_at_bid():
    rows = [make_row("LOW", 10_600, 10_650), make_row("EDGE", 49_950, 50_000), make_row("HIGH", 99_900, 100_100)]
    df = add_liquidity_metrics(pd.DataFrame(rows)).set_index("symbol")
    assert df.loc["LOW", "spread_ticks"] == 1      # 50đ / 50đ
    assert df.loc["EDGE", "spread_ticks"] == 1     # 49.950 -> 50.000 là 1 bước giá 50đ
    assert df.loc["HIGH", "spread_ticks"] == 2     # 200đ / 100đ


def test_ranking_not_biased_by_share_price():
    # Cùng độ sâu, cùng 1 bước giá: mã giá thấp có bps cao hơn nhiều nhưng không được bị chấm spread kém hơn.
    cheap = [make_row("CHEAP", 10_600, 10_650)] * 5
    pricey = [make_row("PRICEY", 99_900, 100_000)] * 5
    wide = [make_row("WIDE", 99_900, 100_200)] * 5   # 3 bước giá
    df = add_liquidity_metrics(pd.DataFrame(cheap + pricey + wide))
    df["depth_value"] = 1e9  # loại ảnh hưởng của độ sâu
    ranked = rank_symbols(df).set_index("symbol")
    assert ranked.loc["CHEAP", "rel_spread_bps"] > ranked.loc["PRICEY", "rel_spread_bps"]
    assert ranked.loc["CHEAP", "score"] == ranked.loc["PRICEY", "score"]
    assert ranked.loc["WIDE", "score"] < ranked.loc["PRICEY", "score"]
