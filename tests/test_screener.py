"""Kiểm thử bộ lọc VN30 bằng dữ liệu dựng tay, đáp án tính tay."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from analytics.screener import (daily_closes_from_board, intraday_factors, liquidity_gate, market_context,
                                momentum, screen)
from neo_api.config import TZ

D1, D2, D3, D4 = (dt.date(2026, 10, d) for d in (27, 28, 29, 30))


def _ts(day: dt.date, hh: int, mm: int) -> pd.Timestamp:
    return pd.Timestamp(dt.datetime.combine(day, dt.time(hh, mm)), tz=TZ)


def _board_row(day, hh, mm, sym, last, grp="VN30", ref=10_000.0, value=1e10, fnet=1e9):
    return {"day": day.strftime("%Y-%m-%d"), "grp": grp, "ts": _ts(day, hh, mm), "symbol": sym, "last_px": last,
            "ref_px": ref, "total_value": value, "foreign_net_val": fnet}


# 1. daily_closes_from_board
def test_daily_closes_final_flag_and_bad_price():
    board = pd.DataFrame([
        _board_row(D1, 14, 30, "AAA", 9_900.0),        # bị ghi đè bởi dòng 15:01 cùng ngày
        _board_row(D1, 15, 1, "AAA", 10_000.0),
        _board_row(D2, 14, 30, "AAA", 10_500.0),       # trước ATC -> tạm tính
        _board_row(D1, 15, 1, "BBB", 0.0),             # giá 0 -> NaN
        _board_row(D1, 15, 1, "CCC", "ATC"),           # chữ -> NaN
        _board_row(D1, 15, 1, "ZZZ", 5_000.0, grp="HOSE"),  # không thuộc VN30
    ])
    c = daily_closes_from_board(board)
    assert list(c.columns) == ["symbol", "day", "close", "ref", "total_value", "foreign_net_val", "ts", "final"]
    assert set(c["symbol"]) == {"AAA", "BBB", "CCC"}
    a1 = c[(c["symbol"] == "AAA") & (c["day"] == D1)].iloc[0]
    assert a1["close"] == 10_000.0 and bool(a1["final"]) is True
    a2 = c[(c["symbol"] == "AAA") & (c["day"] == D2)].iloc[0]
    assert a2["close"] == 10_500.0 and bool(a2["final"]) is False
    assert np.isnan(c.loc[c["symbol"] == "BBB", "close"].iloc[0])
    assert np.isnan(c.loc[c["symbol"] == "CCC", "close"].iloc[0])


def test_daily_closes_boundary_1445_is_final():
    c = daily_closes_from_board(pd.DataFrame([_board_row(D1, 14, 45, "AAA", 10_000.0),
                                              _board_row(D2, 14, 44, "AAA", 10_000.0)]))
    assert c["final"].tolist() == [True, False]


def test_daily_closes_empty():
    assert daily_closes_from_board(pd.DataFrame()).empty


# 2. momentum
def _closes():
    rows = [("AAA", D1, 100.0, True), ("AAA", D2, 110.0, True), ("AAA", D3, 121.0, True),
            ("AAA", D4, 200.0, False),                       # giá tạm tính: không dùng
            ("BBB", D1, 50.0, True), ("BBB", D3, 60.0, True)]  # BBB thiếu phiên D2
    return pd.DataFrame(rows, columns=["symbol", "day", "close", "final"])


def test_momentum_uses_only_final_rows():
    m = momentum(_closes(), 1)
    a = m[m["symbol"] == "AAA"].set_index("day")["mom_1"]
    assert np.isnan(a[D1])
    assert a[D2] == pytest.approx(0.10)
    assert a[D3] == pytest.approx(0.10)
    assert np.isnan(a[D4])                     # D4 tạm tính: không ra 200/121 - 1


def test_momentum_unfinal_day_keeps_its_slot():
    # Như dữ liệu thật 30/10: một phiên chưa chốt ở giữa. "1 phiên trước" của D3 là D2 (NaN), không phải D1.
    rows = [("AAA", D1, 100.0, True), ("AAA", D2, 105.0, False), ("AAA", D3, 110.0, True)]
    m = momentum(pd.DataFrame(rows, columns=["symbol", "day", "close", "final"]), 1).set_index("day")
    assert np.isnan(m.loc[D3, "mom_1"])
    m2 = momentum(pd.DataFrame(rows, columns=["symbol", "day", "close", "final"]), 2).set_index("day")
    assert m2.loc[D3, "mom_2"] == pytest.approx(0.10)


def test_momentum_missing_session_is_nan():
    m = momentum(_closes(), 1)
    b = m[m["symbol"] == "BBB"].set_index("day")["mom_1"]
    assert np.isnan(b[D3])                     # phiên D2 thiếu: không lấy D1 thay thế
    m2 = momentum(_closes(), 2)
    assert m2[(m2["symbol"] == "BBB") & (m2["day"] == D3)]["mom_2"].iloc[0] == pytest.approx(60 / 50 - 1)
    assert m2[(m2["symbol"] == "AAA") & (m2["day"] == D3)]["mom_2"].iloc[0] == pytest.approx(0.21)


def test_momentum_relative_to_vn30():
    ix = pd.DataFrame({"day": [D1, D2, D3], "close": [1000.0, 1050.0, 1100.0]})
    m = momentum(_closes(), 1, index_closes=ix)
    r = m[(m["symbol"] == "AAA") & (m["day"] == D3)].iloc[0]
    assert r["index_mom_1"] == pytest.approx(1100 / 1050 - 1)
    assert r["rel_mom_1"] == pytest.approx(0.10 - (1100 / 1050 - 1))
    # chỉ số thiếu phiên D2 -> tương đối NaN
    m2 = momentum(_closes(), 1, index_closes=ix[ix["day"] != D2])
    assert np.isnan(m2[(m2["symbol"] == "AAA") & (m2["day"] == D3)]["rel_mom_1"].iloc[0])


# 3. intraday_factors
def _snap():
    t0, t1 = _ts(D3, 10, 0), _ts(D3, 10, 1)
    return pd.DataFrame([
        {"ts": t0, "symbol": "AAA", "last_px": 9_000.0, "ref_px": 10_000.0, "foreign_net_val": 0.0, "total_value": 1e9},
        {"ts": t1, "symbol": "AAA", "last_px": 10_500.0, "ref_px": 10_000.0, "foreign_net_val": 2e9, "total_value": 1e10},
        {"ts": t1, "symbol": "BBB", "last_px": 20_000.0, "ref_px": 0.0, "foreign_net_val": -1e9, "total_value": 0.0},
    ])


def test_intraday_factors_latest_snapshot():
    f = intraday_factors(_snap(), index_change=1.0).set_index("symbol")
    assert f.loc["AAA", "mom_intraday"] == pytest.approx(0.05)
    assert f.loc["AAA", "foreign_ratio"] == pytest.approx(0.2)
    assert f.loc["AAA", "mom_rel"] == pytest.approx(0.04)   # 0,05 - 1%/100
    assert np.isnan(f.loc["BBB", "mom_intraday"])           # tham chiếu 0 -> NaN
    assert np.isnan(f.loc["BBB", "foreign_ratio"])          # tổng giá trị 0 -> NaN


def test_intraday_factors_without_index():
    f = intraday_factors(_snap(), index_change=None)
    assert f["mom_rel"].isna().all()


# 4. liquidity_gate
def test_liquidity_gate_three_levels():
    ranking = pd.DataFrame({"symbol": ["A", "B", "C", "D", "E"], "score": [20.0, 50.0, 80.0, np.nan, 33.3]})
    alerts = pd.Series({"A": 3, "B": 2})
    g = liquidity_gate(ranking, alerts).set_index("symbol")
    assert g.loc["A", "gate"] == "Loại"       # điểm thấp: Loại dù có cảnh báo
    assert g.loc["B", "gate"] == "Chú ý"
    assert g.loc["C", "gate"] == "Đạt"
    assert g.loc["D", "gate"] == "Loại"       # không có điểm
    assert g.loc["E", "gate"] == "Loại"       # đúng 33,3 là "Yếu" ở Radar nên cũng bị loại
    assert g.loc["C", "alerts"] == 0
    assert g["gate_reason"].str.len().gt(0).all()


# 5. screen
def _gate():
    ranking = pd.DataFrame({"symbol": ["A", "B", "C", "E", "F"], "score": [10.0, 60.0, 70.0, 90.0, 80.0]})
    return liquidity_gate(ranking, pd.Series({"B": 1}))


def _factors():
    return pd.DataFrame({
        "symbol": ["A", "B", "C", "E", "F"],
        "foreign_ratio": [0.9, 0.1, 0.3, 0.2, np.nan],
        "mom_rel": [0.9, 0.05, np.nan, 0.01, np.nan],
        "mom_intraday": [0.9, 0.02, 0.03, 0.01, np.nan],
    })


def test_screen_ranks_only_passing_symbols():
    s = screen(_factors(), _gate())
    assert s.attrs["factors"] == ["foreign_ratio", "mom_rel"]
    by = s.set_index("symbol")
    # foreign_ratio trong B, C, E: B 0, E 50, C 100. mom_rel trong B, E: B 100, E 0
    assert by.loc["B", "rank_foreign_ratio"] == 0 and by.loc["C", "rank_foreign_ratio"] == 100
    assert by.loc["E", "rank_foreign_ratio"] == 50
    assert by.loc["B", "screen_score"] == 50.0
    assert by.loc["C", "screen_score"] == 100.0     # thiếu mom_rel: trung bình trên yếu tố có
    assert by.loc["E", "screen_score"] == 25.0
    assert np.isnan(by.loc["F", "screen_score"])    # thiếu hết
    assert np.isnan(by.loc["A", "screen_score"])    # Loại: NaN dù yếu tố tốt nhất
    assert np.isnan(by.loc["A", "rank_foreign_ratio"])
    assert s["symbol"].tolist() == ["C", "B", "E", "F", "A"]


def test_screen_falls_back_to_intraday_when_no_index():
    f = _factors().assign(mom_rel=np.nan)
    s = screen(f, _gate())
    assert s.attrs["factors"] == ["foreign_ratio", "mom_intraday"]
    by = s.set_index("symbol")
    # mom_intraday trong B, C, E: E 0, B 50, C 100 -> C (100+100)/2, B (0+50)/2, E (50+0)/2
    assert by.loc["C", "screen_score"] == 100.0
    assert by.loc["B", "screen_score"] == 25.0
    assert by.loc["E", "screen_score"] == 25.0


def test_screen_symbol_missing_from_gate_is_excluded():
    f = pd.concat([_factors(), pd.DataFrame({"symbol": ["X"], "foreign_ratio": [5.0], "mom_rel": [5.0]})])
    by = screen(f, _gate()).set_index("symbol")
    assert by.loc["X", "gate"] == "Loại" and np.isnan(by.loc["X", "screen_score"])


# 6. market_context
def test_market_context_empty_inputs():
    ctx = market_context(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    for k in ("vnindex_advances", "vnindex_declines", "vn30_pct", "basis", "vn30_foreign_net"):
        assert ctx[k] is None
    assert isinstance(ctx["summary"], str) and ctx["summary"]
    assert market_context(None, None, None, None)["vn30_pct"] is None


def test_market_context_facts():
    cards = pd.DataFrame({"index_code": ["VNINDEX", "VN30"], "pct_change": [0.3, -0.52]})
    breadth = pd.DataFrame({"index_code": ["VNINDEX", "VN30"], "advances": [250, 10], "declines": [150, 18]})
    fut = pd.DataFrame({"symbol": ["VN30F1M", "VN30F2M"], "basis": [-3.2, 1.0]})
    snap = pd.DataFrame({"ts": [_ts(D3, 10, 0), _ts(D3, 10, 1), _ts(D3, 10, 1)], "symbol": ["A", "A", "B"],
                         "foreign_net_val": [9e9, 2e9, -0.5e9]})
    ctx = market_context(cards, breadth, fut, snap)
    assert ctx["vnindex_advances"] == 250 and ctx["vnindex_declines"] == 150
    assert ctx["vn30_pct"] == pytest.approx(-0.52)
    assert ctx["basis_contract"] == "VN30F1M" and ctx["basis"] == pytest.approx(-3.2)
    assert ctx["vn30_foreign_net"] == pytest.approx(1.5e9)   # 2e9 (mới nhất của A) - 0,5e9
    assert "giảm" in ctx["summary"] and "mua ròng" in ctx["summary"] and "thấp hơn" in ctx["summary"]
