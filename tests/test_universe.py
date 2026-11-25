"""Bộ lọc toàn HOSE (analytics/universe.py): cổng thanh khoản, nước ngoài, động lượng 6-1. Dữ liệu dựng sẵn, không đọc market.db."""
import numpy as np
import pandas as pd
import pytest

from analytics import universe as u

T = 5e9          # ngưỡng thử (khớp mặc định 250 triệu / 5%)
DAYS = [f"2026-11-{d:02d}" for d in range(2, 14)]     # 12 ngày thử


def rows(**per_symbol):
    """per_symbol: mã -> danh sách giá trị khớp từng ngày trong DAYS (None = mã không có dòng ngày đó)."""
    out = []
    for sym, vals in per_symbol.items():
        for d, v in zip(DAYS, vals):
            if v is not None:
                out.append({"day": d, "symbol": sym, "total_value": v})
    return pd.DataFrame(out)


def gate(**per_symbol):
    return u.liquidity_gate(rows(**per_symbol), DAYS, threshold=T, min_days_ratio=0.8, near_factor=1.25).set_index("symbol")


# ---- cổng thanh khoản
def test_threshold_comes_from_position_and_participation():
    assert u.liquidity_threshold(250e6, 0.05) == pytest.approx(5e9)
    assert u.liquidity_threshold(500e6, 0.05) == pytest.approx(10e9)      # đổi một trong hai số đầu vào thì ngưỡng đổi
    with pytest.raises(ValueError):
        u.liquidity_threshold(0, 0.05)
    with pytest.raises(ValueError):
        u.liquidity_threshold(250e6, 0)


def test_median_exactly_at_threshold_passes_and_just_below_fails():
    g = gate(AAA=[T] * 12, BBB=[T - 1] * 12)
    assert g.loc["AAA", "gate"] == u.PASS and g.loc["BBB", "gate"] == u.FAIL


def test_near_flag_is_inside_t_to_1_25_t_only():
    g = gate(AAA=[T] * 12, BBB=[1.25 * T - 1] * 12, CCC=[1.25 * T] * 12)
    assert g.loc["AAA", "near"] and g.loc["BBB", "near"] and not g.loc["CCC", "near"]
    assert (g["gate"] == u.PASS).all()                  # sát ngưỡng là cờ, không đổi nhãn Đạt


def test_zero_days_stay_in_the_sample():
    # 8 ngày giao dịch lớn + 4 ngày 0: trung vị vẫn lớn nhưng chỉ 8/12 ngày có giao dịch -> Ít giao dịch
    g = gate(AAA=[100e9] * 8 + [0] * 4)
    assert g.loc["AAA", "gate"] == u.FEW and g.loc["AAA", "trade_days"] == 8
    # 5 ngày lớn + 7 ngày 0: ngày 0 nằm trong mẫu nên trung vị = 0, không thể trông thanh khoản nhờ vài ngày khớp lớn
    g = gate(AAA=[100e9] * 5 + [0] * 7)
    assert g.loc["AAA", "median_value"] == 0 and g.loc["AAA", "gate"] == u.FEW


def test_trade_days_boundary_nine_vs_ten_of_twelve():
    nine = [10e9] * 9 + [0] * 3
    ten = [10e9] * 10 + [0] * 2
    g = gate(AAA=nine, BBB=ten)
    assert g.loc["AAA", "gate"] == u.FEW and g.loc["BBB", "gate"] == u.PASS


def test_trade_days_boundary_scales_with_ratio_for_ten_days():
    days = DAYS[:10]
    r = pd.DataFrame([{"day": d, "symbol": s, "total_value": v} for s, vals in
                      {"AAA": [10e9] * 7 + [0] * 3, "BBB": [10e9] * 8 + [0] * 2}.items() for d, v in zip(days, vals)])
    g = u.liquidity_gate(r, days, threshold=T, min_days_ratio=0.8).set_index("symbol")
    assert g.loc["AAA", "gate"] == u.FEW and g.loc["BBB", "gate"] == u.PASS     # 7/10 thiếu, 8/10 đủ


def test_missing_snapshot_day_counts_as_zero_and_null_value_as_no_trade():
    g = gate(AAA=[10e9] * 9 + [None] * 3, BBB=[10e9] * 9 + [np.nan] * 3)
    assert g.loc["AAA", "trade_days"] == 9 and g.loc["AAA", "gate"] == u.FEW
    assert g.loc["BBB", "trade_days"] == 9 and g.loc["BBB", "gate"] == u.FEW


def test_symbol_with_no_row_in_full_days_is_missing_data_not_low_liquidity():
    r = rows(AAA=[10e9] * 12)
    g = u.liquidity_gate(r, DAYS, symbols=["ZZZ"], threshold=T, min_days_ratio=0.8).set_index("symbol")
    assert g.loc["ZZZ", "gate"] == u.MISSING and g.loc["AAA", "gate"] == u.PASS


def test_etf_warrants_and_odd_symbols_are_excluded_from_the_universe():
    g = gate(AAA=[10e9] * 12, E1VFVN30=[10e9] * 12, CACB2515=[10e9] * 12, A32=[10e9] * 12, AB=[10e9] * 12)
    assert set(g.index) == {"AAA", "A32"}               # mã 3 ký tự (kể cả có số) vào, dài hơn hoặc ngắn hơn thì không
    assert u.is_stock_symbol("A32") and not u.is_stock_symbol("aaa") and not u.is_stock_symbol(None)


def test_gate_ignores_days_outside_the_full_day_list():
    r = rows(AAA=[10e9] * 12)
    extra = pd.DataFrame([{"day": "2026-10-30", "symbol": "AAA", "total_value": 1.0}])
    g = u.liquidity_gate(pd.concat([r, extra]), DAYS, threshold=T).set_index("symbol")
    assert g.loc["AAA", "n_days"] == 12 and g.loc["AAA", "median_value"] == 10e9


# ---- ngày đủ
def test_full_days_need_a_snapshot_after_the_cutoff():
    b = pd.DataFrame({"day": ["a", "b", "c", "d"], "ts": ["2026-11-02T14:45:00+07:00", "2026-11-03T15:02:15+07:00",
                                                          "2026-11-05T11:22:00+07:00", "2026-10-29T22:18:25+07:00"]})
    b["day"] = ["2026-11-02", "2026-11-03", "2026-11-05", "2026-10-29"]
    assert u.full_days(b, "14:50") == ["2026-10-29", "2026-11-03"]      # 14:45:00 chưa có ATC, 11:22 dở dang; 22:18 là sau đóng cửa


# ---- nước ngoài
def foreign_rows():
    return pd.DataFrame([
        {"day": DAYS[0], "symbol": "AAA", "total_value": 100.0, "foreign_buy_val": 30.0, "foreign_sell_val": 10.0, "foreign_net_val": 20.0},
        {"day": DAYS[1], "symbol": "AAA", "total_value": 300.0, "foreign_buy_val": 0.0, "foreign_sell_val": 60.0, "foreign_net_val": -60.0},
        {"day": DAYS[0], "symbol": "BBB", "total_value": 50.0, "foreign_buy_val": 80.0, "foreign_sell_val": 0.0, "foreign_net_val": 80.0},
        {"day": DAYS[0], "symbol": "CCC", "total_value": 0.0, "foreign_buy_val": 0.0, "foreign_sell_val": 0.0, "foreign_net_val": 0.0},
    ])


def test_foreign_ratio_is_sum_over_sum_not_mean_of_daily_ratios():
    f = u.foreign_window(foreign_rows(), DAYS).set_index("symbol")
    assert f.loc["AAA", "foreign_ratio"] == pytest.approx((20 - 60) / 400)       # -0,10; trung bình tỷ lệ ngày sẽ là (0,2-0,2)/2 = 0
    assert f.loc["AAA", "foreign_net"] == -40 and f.loc["AAA", "foreign_value"] == 400


def test_foreign_over_flag_when_buy_or_sell_exceeds_total_value():
    f = u.foreign_window(foreign_rows(), DAYS).set_index("symbol")
    assert bool(f.loc["BBB", "foreign_over"]) and not bool(f.loc["AAA", "foreign_over"])
    assert f.loc["BBB", "foreign_ratio"] == pytest.approx(80 / 50)                # có thể vượt 100%, hiện đúng số và có cờ


def test_foreign_ratio_is_nan_without_traded_value():
    f = u.foreign_window(foreign_rows(), DAYS).set_index("symbol")
    assert np.isnan(f.loc["CCC", "foreign_ratio"])


# ---- động lượng 6-1
def series(symbol, start, end, start_price, end_price):
    days = pd.bdate_range(start, end)
    return pd.DataFrame({"symbol": symbol, "day": days, "close": np.linspace(start_price, end_price, len(days))})


def market(days, n=3):
    """Nền thị trường: n mã giả có nến mọi ngày để các ngày đó tính là phiên thị trường."""
    return pd.concat([pd.DataFrame({"symbol": f"M{i}", "day": days, "close": 10.0}) for i in range(n)], ignore_index=True)


KW = dict(window_months=6, skip_months=1, ref_months=3, max_gap_days=10, max_stale_sessions=3, jump_pct=0.075, min_symbols=3)


def test_momentum_uses_calendar_marks_with_one_common_reference_day():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    c = pd.concat([market(days), pd.DataFrame({"symbol": "AAA", "day": days, "close": np.arange(len(days)) + 100.0})], ignore_index=True)
    m = u.momentum_6_1(c, **KW).set_index("symbol")
    ref = pd.Timestamp("2026-11-20")
    assert m.loc["AAA", "ref_day"] == ref and m.loc["AAA", "mom_status"] == u.MOM_OK
    px = c[c.symbol == "AAA"].set_index("day")["close"]
    start, end = px[:ref - pd.DateOffset(months=6)].iloc[-1], px[:ref - pd.DateOffset(months=1)].iloc[-1]
    assert m.loc["AAA", "mom"] == pytest.approx(end / start - 1)
    assert m.loc["AAA", "mom_ref"] == pytest.approx(px[ref] / px[:ref - pd.DateOffset(months=3)].iloc[-1] - 1)


def test_two_symbols_with_different_last_candle_share_the_same_reference_day():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    a = pd.DataFrame({"symbol": "AAA", "day": days, "close": 100.0})
    b = pd.DataFrame({"symbol": "BBB", "day": days[:-2], "close": 100.0})     # nến cuối cũ 2 phiên, trong dung sai
    m = u.momentum_6_1(pd.concat([market(days), a, b], ignore_index=True), **KW).set_index("symbol")
    assert m.loc["AAA", "ref_day"] == m.loc["BBB", "ref_day"] == pd.Timestamp("2026-11-20")
    assert m.loc["BBB", "mom_status"] == u.MOM_OK and m.loc["BBB", "last_day"] == days[-3]


def test_stale_symbol_beyond_tolerance_is_not_computed():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    old = pd.DataFrame({"symbol": "OLD", "day": days[:-5], "close": 100.0})   # nến cuối cách 5 phiên > 3
    m = u.momentum_6_1(pd.concat([market(days), old], ignore_index=True), **KW).set_index("symbol")
    assert m.loc["OLD", "mom_status"] == u.STALE and np.isnan(m.loc["OLD", "mom"])


def test_price_too_far_before_the_mark_means_not_enough_history():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    s = pd.DataFrame({"symbol": "GAP", "day": list(days[:20]) + list(days[-60:]), "close": 100.0})   # nến liền sau quá xa mốc T-6 tháng
    m = u.momentum_6_1(pd.concat([market(days), s], ignore_index=True), **KW).set_index("symbol")
    assert m.loc["GAP", "mom_status"] == u.NO_HISTORY and np.isnan(m.loc["GAP", "mom"])


def test_symbol_listed_recently_has_no_history_for_six_months():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    new = pd.DataFrame({"symbol": "NEW", "day": days[-60:], "close": 100.0})
    m = u.momentum_6_1(pd.concat([market(days), new], ignore_index=True), **KW).set_index("symbol")
    assert m.loc["NEW", "mom_status"] == u.NO_HISTORY


def test_jump_flag_only_for_adjacent_market_days_inside_the_window():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    px = np.full(len(days), 100.0)
    px[100:] = 110.0                                                       # nhảy 10% giữa hai phiên liền kề, nằm trong cửa sổ
    jumpy = pd.DataFrame({"symbol": "JMP", "day": days, "close": px})
    px2 = np.full(len(days), 100.0)
    px2[-5:] = 120.0                                                       # nhảy nằm SAU mốc T-1 tháng: ngoài khoảng giá đã dùng
    late = pd.DataFrame({"symbol": "LAT", "day": days, "close": px2})
    m = u.momentum_6_1(pd.concat([market(days), jumpy, late], ignore_index=True), **KW).set_index("symbol")
    assert bool(m.loc["JMP", "jump"]) and not bool(m.loc["LAT", "jump"])


def test_gap_between_symbol_candles_is_not_a_jump():
    days = pd.bdate_range("2026-01-01", "2026-11-20")
    keep = [d for i, d in enumerate(days) if not (100 <= i < 103)]         # mã không giao dịch 3 phiên rồi giá khác 10%
    px = np.where(np.arange(len(keep)) >= 100, 110.0, 100.0)
    s = pd.DataFrame({"symbol": "SKP", "day": keep, "close": px})
    m = u.momentum_6_1(pd.concat([market(days), s], ignore_index=True), **KW).set_index("symbol")
    assert not bool(m.loc["SKP", "jump"])                                  # hai nến không liền kề trên lịch thị trường


# ---- ghép lại
def test_screen_universe_statuses_rank_and_order():
    days_hist = pd.bdate_range("2026-01-01", "2026-11-20")
    clo = [market(days_hist, n=150)]
    for sym, end in (("AAA", 150.0), ("BBB", 80.0)):                        # AAA tăng, BBB giảm
        clo.append(pd.DataFrame({"symbol": sym, "day": days_hist, "close": np.linspace(100.0, end, len(days_hist))}))
    clo.append(pd.DataFrame({"symbol": "NEW", "day": days_hist[-30:], "close": 100.0}))          # đạt cổng nhưng thiếu lịch sử
    closes = pd.concat(clo, ignore_index=True)
    ts = "2026-11-%02dT15:02:20+07:00"
    b = []
    for i, d in enumerate(DAYS):
        for sym, v in (("AAA", 20e9), ("BBB", 30e9), ("NEW", 10e9), ("LOW", 1e9), ("FEW", 50e9 if i < 3 else 0.0)):
            b.append({"day": d, "ts": ts % (i + 2), "symbol": sym, "total_value": v, "foreign_buy_val": 0.0,
                      "foreign_sell_val": 0.0, "foreign_net_val": 0.0})
    b.append({"day": "2026-11-16", "ts": "2026-11-16T11:20:00+07:00", "symbol": "ZZZ", "total_value": 1.0,
              "foreign_buy_val": 0.0, "foreign_sell_val": 0.0, "foreign_net_val": 0.0})        # chỉ có ở ngày dở dang
    res = u.screen_universe(pd.DataFrame(b), closes).set_index("symbol")
    assert res.loc["AAA", "status"] == u.PASS and res.loc["BBB", "status"] == u.PASS
    assert res.loc["NEW", "status"] == u.NO_HISTORY and res.loc["NEW", "gate"] == u.PASS
    assert res.loc["LOW", "status"] == u.FAIL and res.loc["FEW", "status"] == u.FEW and res.loc["ZZZ", "status"] == u.MISSING
    assert res.loc["AAA", "mom_rank"] == 100.0 and res.loc["BBB", "mom_rank"] == 0.0     # chỉ hai mã được xếp hạng
    assert res[["mom_rank"]].drop(["AAA", "BBB"]).isna().all().all()
    order = list(u.screen_universe(pd.DataFrame(b), closes)["status"])
    assert order == sorted(order, key=u.STATUS_ORDER.index)                                 # Đạt, rồi lịch sử, rồi không đạt, ...
    assert u.screen_universe(pd.DataFrame(b), closes).attrs["days"] == DAYS


def test_screen_universe_without_candles_never_shows_pass_with_a_rank():
    ts = "2026-11-%02dT15:02:20+07:00"
    b = pd.DataFrame([{"day": d, "ts": ts % (i + 2), "symbol": "AAA", "total_value": 20e9, "foreign_buy_val": 0.0,
                       "foreign_sell_val": 0.0, "foreign_net_val": 0.0} for i, d in enumerate(DAYS)])
    res = u.screen_universe(b, pd.DataFrame(columns=["symbol", "day", "close"]))
    assert res.loc[0, "status"] == u.NO_HISTORY and np.isnan(res.loc[0, "mom_rank"])
