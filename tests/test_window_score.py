"""Mục A1: điểm thanh khoản theo cửa sổ trượt 30 lần chụp (không vắt qua nghỉ trưa); mã thiếu dữ liệu không chấm điểm và
không làm lệch phần trăm thứ hạng của mã khác. Điểm cả kỳ dùng cho cổng không đổi."""
import numpy as np
import pandas as pd
import pytest

from finance.liquidity import add_window_stats, window_scores

TZ = "Asia/Ho_Chi_Minh"
DAY = "2026-11-20"


def minutes(day=DAY):
    am = pd.date_range(f"{day} 09:15", f"{day} 11:29", freq="1min", tz=TZ)
    pm = pd.date_range(f"{day} 13:00", f"{day} 14:29", freq="1min", tz=TZ)
    return am.append(pm)


def frame(spec, day=DAY, drop=None):
    """spec: {mã: (spread bps, độ sâu, |lệch|)}. Giá trị đổi dần theo phút để kiểm trung bình và trung vị trên đúng cửa sổ."""
    rows = []
    for sym, (sp, dp, im) in spec.items():
        for i, t in enumerate(minutes(day)):
            if drop and (sym, t) in drop:
                continue
            rows.append({"ts": t, "symbol": sym, "rel_spread_bps": sp + 0.01 * i, "depth_value": dp + i,
                         "imbalance": im * (1 if i % 2 == 0 else -1)})
    return pd.DataFrame(rows)


SPEC = {"A": (10.0, 5e9, 0.10), "B": (20.0, 3e9, 0.20), "C": (30.0, 1e9, 0.30)}


def test_window_is_the_last_30_snapshots_of_the_same_symbol_and_session():
    df = frame(SPEC)
    out = add_window_stats(df)
    a = out[out["symbol"] == "A"].reset_index(drop=True)
    i = 60                                                          # lần chụp thứ 61 của buổi sáng
    assert a.loc[i, "win_n"] == 30
    assert a.loc[i, "win_spread_bps"] == pytest.approx(a["rel_spread_bps"].iloc[i - 29:i + 1].mean())
    assert a.loc[i, "win_depth"] == pytest.approx(a["depth_value"].iloc[i - 29:i + 1].median())
    assert a.loc[i, "win_abs_imb"] == pytest.approx(0.10)


def test_window_resets_after_the_lunch_break():
    out = add_window_stats(frame(SPEC))
    a = out[out["symbol"] == "A"].set_index("ts")
    t = pd.Timestamp(f"{DAY} 13:04", tz=TZ)                         # 5 lần chụp đầu buổi chiều
    assert a.loc[t, "win_n"] == 5                                   # không lấy 25 lần chụp cuối buổi sáng
    pm_first = a.loc[pd.Timestamp(f"{DAY} 13:00", tz=TZ), "rel_spread_bps"]
    assert a.loc[pd.Timestamp(f"{DAY} 13:00", tz=TZ), "win_spread_bps"] == pytest.approx(pm_first)
    assert a.loc[t, "win_spread_bps"] == pytest.approx(a.loc[pd.Timestamp(f"{DAY} 13:00", tz=TZ):t, "rel_spread_bps"].mean())


def test_window_does_not_cross_days():
    df = pd.concat([frame(SPEC, "2026-11-19"), frame(SPEC, DAY)], ignore_index=True)
    out = add_window_stats(df)
    first = out[(out["symbol"] == "A") & (out["ts"] == pd.Timestamp(f"{DAY} 09:15", tz=TZ))].iloc[0]
    assert first["win_n"] == 1


def test_missing_snapshots_reduce_count_instead_of_stretching_the_window():
    t_miss = {pd.Timestamp(f"{DAY} 10:{m:02d}", tz=TZ) for m in range(10, 20)}      # thiếu 10 phút liền
    df = frame({"A": SPEC["A"]}, drop={("A", t) for t in t_miss})
    out = add_window_stats(df).set_index("ts")
    assert out.loc[pd.Timestamp(f"{DAY} 10:29", tz=TZ), "win_n"] == 20            # 30 phút gần nhất có 10 phút trống


def test_no_look_ahead_future_rows_do_not_change_past_stats():
    df = frame(SPEC)
    full = add_window_stats(df)
    cut = pd.Timestamp(f"{DAY} 10:30", tz=TZ)
    wrecked = df.copy()
    wrecked.loc[wrecked["ts"] > cut, ["rel_spread_bps", "depth_value"]] = 1e9
    again = add_window_stats(wrecked)
    cols = ["win_spread_bps", "win_depth", "win_abs_imb", "win_n"]
    past = df["ts"] <= cut
    pd.testing.assert_frame_equal(again.loc[past, cols], full.loc[past, cols], check_exact=True)


def test_scores_rank_good_symbols_higher_and_stay_between_0_and_100():
    out = add_window_stats(frame(SPEC))
    last = out.sort_values("ts").groupby("symbol").tail(1)
    s = window_scores(last)
    assert (s["score_w_status"] == "Đủ dữ liệu").all()
    assert s["score_w"].between(0, 100).all() and s["score_w"].notna().all()
    assert s.loc["A", "score_w"] > s.loc["B", "score_w"] > s.loc["C", "score_w"]    # A: spread thấp, sâu, ít lệch
    assert s.loc["A", "score_w"] == 100.0 and s.loc["C", "score_w"] == 0.0


def test_symbol_with_too_few_snapshots_is_not_scored_and_does_not_shift_others():
    base = add_window_stats(frame(SPEC))
    last_ab = base[base["symbol"].isin(["A", "B"])].sort_values("ts").groupby("symbol").tail(1)
    without = window_scores(last_ab)
    # thêm mã D chỉ có 5 lần chụp trong cửa sổ, giá trị cực tốt: không được chấm điểm, không được làm đổi điểm A và B
    sparse = frame({"D": (1.0, 9e12, 0.0)}, drop={("D", t) for t in minutes()[:-5]})
    both = pd.concat([base, add_window_stats(sparse)], ignore_index=True)
    last = both.sort_values("ts").groupby("symbol").tail(1)
    last = last[last["symbol"].isin(["A", "B", "D"])]
    s = window_scores(last)
    assert s.loc["D", "score_w_status"] == "Chưa đủ dữ liệu" and np.isnan(s.loc["D", "score_w"])
    assert s.loc["A", "score_w"] == without.loc["A", "score_w"] and s.loc["B", "score_w"] == without.loc["B", "score_w"]


def test_exactly_half_of_the_window_is_enough_and_just_below_is_not():
    t = pd.Timestamp(f"{DAY} 09:29", tz=TZ)                          # 15 lần chụp từ 9:15 đến 9:29
    ok = add_window_stats(frame({"A": SPEC["A"]}))
    row = ok[ok["ts"] == t]
    assert row["win_n"].iloc[0] == 15 and window_scores(row)["score_w_status"].iloc[0] == "Đủ dữ liệu"
    t2 = pd.Timestamp(f"{DAY} 09:28", tz=TZ)                         # 14 lần chụp: dưới một nửa
    row2 = ok[ok["ts"] == t2]
    assert row2["win_n"].iloc[0] == 14 and window_scores(row2)["score_w_status"].iloc[0] == "Chưa đủ dữ liệu"


def test_empty_input_is_handled():
    out = add_window_stats(pd.DataFrame(columns=["ts", "symbol", "rel_spread_bps", "depth_value", "imbalance"]))
    assert {"win_spread_bps", "win_depth", "win_abs_imb", "win_n"} <= set(out.columns)
