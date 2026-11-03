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


def test_ranking_scores_spread_by_cost_in_bps():
    # Như VIC và SHB thật: mã giá cao rộng 3 bước giá vẫn rẻ hơn (bps thấp hơn) mã giá thấp đúng 1 bước giá.
    cheap = [make_row("CHEAP", 10_600, 10_650)] * 5     # 1 bước giá = 47,1 bps
    pricey = [make_row("PRICEY", 99_900, 100_000)] * 5  # 1 bước giá = 10,0 bps
    wide = [make_row("WIDE", 99_900, 100_200)] * 5      # 3 bước giá = 30,0 bps
    df = add_liquidity_metrics(pd.DataFrame(cheap + pricey + wide))
    df["depth_value"] = 1e9  # loại ảnh hưởng của độ sâu
    df["imbalance"] = 0.0    # loại ảnh hưởng của lệch mua/bán
    ranked = rank_symbols(df).set_index("symbol")
    assert ranked.loc["CHEAP", "spread_bps_mean"] == pytest.approx(50 / 10_625 * 1e4)
    assert ranked.loc["WIDE", "spread_ticks"] == 3 and ranked.loc["CHEAP", "spread_ticks"] == 1
    # spread chiếm 40%; độ sâu và lệch bằng nhau nên mỗi mã cùng 0,5 ở hai phần đó: điểm = 100*(0,4*h + 0,3)
    assert ranked.loc["PRICEY", "score"] == 70.0    # rẻ nhất: hạng 1
    assert ranked.loc["WIDE", "score"] == 50.0      # giữa: hạng 0,5
    assert ranked.loc["CHEAP", "score"] == 30.0     # đắt nhất dù chỉ 1 bước giá


def test_ranking_uses_mean_spread_not_median():
    # Hai mã cùng trung vị 10 bps, nhưng B có 2/5 lần chụp giãn ra 3 bước giá -> B tốn hơn trung bình, điểm thấp hơn.
    a = [make_row("A", 99_900, 100_000)] * 5
    b = [make_row("B", 99_900, 100_000)] * 3 + [make_row("B", 99_900, 100_200)] * 2
    df = add_liquidity_metrics(pd.DataFrame(a + b))
    df["depth_value"], df["imbalance"] = 1e9, 0.0
    ranked = rank_symbols(df).set_index("symbol")
    assert ranked.loc["A", "rel_spread_bps"] == ranked.loc["B", "rel_spread_bps"]
    assert ranked.loc["B", "spread_bps_mean"] > ranked.loc["A", "spread_bps_mean"]
    assert ranked.loc["A", "score"] > ranked.loc["B", "score"]
