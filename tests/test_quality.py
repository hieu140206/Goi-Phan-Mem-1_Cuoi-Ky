"""Mục B1 và B5: dòng không hợp lệ cho spread, khoảng trống, dữ liệu cũ, và "liên tiếp" của đợt cảnh báo là hai lần chụp hợp lệ
kề nhau cách không quá 90 giây, không vắt qua nghỉ trưa. Dữ liệu dựng sẵn."""
import numpy as np
import pandas as pd

from analytics.baseline import detect_anomalies_tod
from finance.liquidity import add_liquidity_metrics
from finance.quality import add_quality_flags, limit_touch_side, quality_table, session_row_counts

TZ = "Asia/Ho_Chi_Minh"


def T(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz=TZ)


def book(ts, sym, bid=20_000.0, ask=20_050.0, qty=1000.0, ceil=21_400.0, floor=18_600.0):
    r = {"ts": ts, "symbol": sym, "ceil_px": ceil, "floor_px": floor}
    for i in (1, 2, 3):
        r[f"bid_px{i}"], r[f"ask_px{i}"] = bid - (i - 1) * 50, ask + (i - 1) * 50
        r[f"bid_qty{i}"] = r[f"ask_qty{i}"] = qty
    return r


# ---------------- B1 ----------------
def test_touching_the_price_limit_with_both_sides_present_is_flagged():
    df = pd.DataFrame([
        book(T("2026-11-20", "10:00"), "A"),                                   # bình thường
        book(T("2026-11-20", "10:01"), "A", bid=21_350.0, ask=21_400.0),       # bán tốt nhất = trần
        book(T("2026-11-20", "10:02"), "A", bid=18_600.0, ask=18_650.0),       # mua tốt nhất = sàn
    ])
    assert limit_touch_side(df).tolist() == ["", "trần", "sàn"]


def test_one_sided_book_is_not_called_touch_that_is_the_lock_case():
    df = pd.DataFrame([book(T("2026-11-20", "10:00"), "A", bid=21_400.0, ask=np.nan)])
    assert limit_touch_side(df).tolist() == [""]                                # khóa trần: xử lý ở normalize_quotes


def test_touch_works_without_limit_columns():
    df = pd.DataFrame([book(T("2026-11-20", "10:00"), "A")]).drop(columns=["ceil_px", "floor_px"])
    assert limit_touch_side(df).tolist() == [""]


def test_invalid_rate_table_counts_every_reason_per_symbol():
    day = "2026-11-20"
    raw = pd.DataFrame([book(T(day, f"10:{m:02d}"), "X") for m in range(10)]
                       + [book(T(day, "09:05"), "X"), book(T(day, "12:00"), "X")])     # hai dòng ngoài phiên liên tục: không tính
    kept = pd.DataFrame([book(T(day, f"10:{m:02d}"), "X") for m in range(7)])
    locked = pd.DataFrame({"ts": [T(day, "10:07"), T(day, "10:08")], "symbol": ["X", "X"], "side": ["trần", "trần"]})
    touch = pd.DataFrame({"ts": [T(day, "10:09")], "symbol": ["X"], "side": ["sàn"]})
    t = quality_table(raw, kept, locked, touch).set_index("symbol")
    assert session_row_counts(raw).to_dict() == {"X": 10}
    r = t.loc["X"]
    assert (r["rows"], r["kept"], r["invalid"], r["locked"], r["touch"], r["other"]) == (10, 7, 3, 2, 1, 0)
    assert r["invalid_rate"] == 30.0


def test_table_has_no_nan_when_a_symbol_has_no_rows():
    raw = pd.DataFrame([book(T("2026-11-20", "10:00"), "A")])
    t = quality_table(raw, pd.DataFrame(columns=raw.columns), pd.DataFrame(), pd.DataFrame())
    assert not t[["rows", "kept", "invalid", "locked", "touch", "other", "gaps", "stale"]].isna().any().any()


# ---------------- B5: cờ ----------------
def series(sym, day, minutes, **kw):
    return [book(T(day, f"{m // 60:02d}:{m % 60:02d}"), sym, **kw) for m in minutes]


def test_gap_flag_marks_the_snapshot_after_a_missing_stretch():
    day = "2026-11-20"
    mins = [m for m in range(10 * 60, 10 * 60 + 40) if not (10 * 60 + 20 <= m < 10 * 60 + 25)]     # thiếu 5 phút
    out = add_quality_flags(pd.DataFrame(series("A", day, mins)))
    flagged = out[out["gap_flag"]]
    assert len(flagged) == 1 and flagged["ts"].iloc[0] == T(day, "10:25") and flagged["gap_s"].iloc[0] == 360


def test_one_minute_cadence_and_the_lunch_break_are_not_gaps():
    day = "2026-11-20"
    mins = list(range(11 * 60 + 20, 11 * 60 + 30)) + list(range(13 * 60, 13 * 60 + 10))
    out = add_quality_flags(pd.DataFrame(series("A", day, mins)))
    assert not out["gap_flag"].any()                                            # 11:29 -> 13:00 là nghỉ trưa, khác buổi


def test_ninety_seconds_is_the_limit():
    day = "2026-11-20"
    rows = [book(T(day, "10:00"), "A"), book(T(day, "10:01") + pd.Timedelta(seconds=30), "A"),
            book(T(day, "10:03") + pd.Timedelta(seconds=1), "A")]
    out = add_quality_flags(pd.DataFrame(rows))
    assert out["gap_flag"].tolist() == [False, False, True]                      # 90 giây vẫn ổn; 91 giây thì không


def _market(frozen_a_from, others_move=True, minutes=30, day="2026-11-20"):
    rows = []
    for i, m in enumerate(range(10 * 60, 10 * 60 + minutes)):
        t = T(day, f"{m // 60:02d}:{m % 60:02d}")
        rows.append(book(t, "A", qty=1000.0 + (i if i < frozen_a_from else frozen_a_from)))
        for s in ("B", "C", "D"):
            rows.append(book(t, s, qty=1000.0 + (i if others_move else 0)))
    return pd.DataFrame(rows)


def test_stale_flag_when_one_symbol_freezes_while_peers_move():
    out = add_quality_flags(_market(frozen_a_from=5))
    a = out[out["symbol"] == "A"].reset_index(drop=True)
    assert not a["stale_flag"].iloc[:15].any()
    assert a["stale_flag"].iloc[15:].all()                                       # đóng băng từ lần chụp 5; cờ bật từ lần thứ 10 không đổi
    assert not out.loc[out["symbol"] != "A", "stale_flag"].any()


def test_no_stale_flag_when_the_whole_market_is_quiet():
    out = add_quality_flags(_market(frozen_a_from=5, others_move=False))
    assert not out["stale_flag"].any()                                           # cả thị trường đứng yên: không phải dữ liệu cũ


def test_flags_do_not_drop_or_reorder_rows():
    df = _market(frozen_a_from=5).sample(frac=1, random_state=0)                 # trộn thứ tự
    out = add_quality_flags(df)
    assert out.index.tolist() == df.index.tolist() and len(out) == len(df)


def test_empty_input():
    out = add_quality_flags(pd.DataFrame(columns=["ts", "symbol"]))
    assert {"gap_s", "gap_flag", "stale_flag"} <= set(out.columns)


# ---------------- B5: đợt cảnh báo cần hai lần chụp kề nhau ----------------
DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"]


def history(drop=None, deplete=()):
    """Mã AAA 7 phiên; `deplete` là các thời điểm mà độ sâu rút còn 5%; `drop` là các thời điểm bị MẤT lần chụp (không có dòng)."""
    rng = np.random.default_rng(2)
    rows = []
    for day in DAYS:
        ts = pd.date_range(f"{day} 09:15", f"{day} 11:29", freq="1min", tz=TZ).append(
            pd.date_range(f"{day} 13:00", f"{day} 14:29", freq="1min", tz=TZ))
        for t in ts:
            if drop and t in drop:
                continue
            q = 5000.0 * rng.lognormal(0, 0.1) * (0.05 if t in deplete else 1.0)
            r = {"ts": t, "symbol": "AAA"}
            skew = rng.uniform(0.8, 1.25)
            for i in (1, 2, 3):
                r[f"bid_px{i}"], r[f"ask_px{i}"] = 20_000.0 - (i - 1) * 50, 20_050.0 + (i - 1) * 50
                r[f"bid_qty{i}"], r[f"ask_qty{i}"] = q, q * skew
            rows.append(r)
    return add_liquidity_metrics(pd.DataFrame(rows))


LAST = DAYS[-1]


def test_two_adjacent_valid_snapshots_make_an_alert():
    t0 = T(LAST, "10:00")
    out = detect_anomalies_tod(history(deplete={t0, t0 + pd.Timedelta("1min")}))
    assert out["is_alert"].sum() >= 1 and out["alert_start"].sum() == 1


def test_a_missing_snapshot_between_them_breaks_the_run():
    t0 = T(LAST, "10:00")
    df = history(deplete={t0, t0 + pd.Timedelta("2min")}, drop={t0 + pd.Timedelta("1min")})   # cách nhau 120 giây
    out = detect_anomalies_tod(df)
    assert out["raw_flag"].sum() == 2 and out["is_alert"].sum() == 0


def test_without_the_gap_rule_the_same_data_would_alert():
    t0 = T(LAST, "10:00")
    df = history(deplete={t0, t0 + pd.Timedelta("2min")}, drop={t0 + pd.Timedelta("1min")})
    assert detect_anomalies_tod(df, max_gap_seconds=None)["is_alert"].sum() >= 1          # chứng minh quy tắc mới là nguyên nhân


def test_a_run_never_spans_the_lunch_break():
    out = detect_anomalies_tod(history(deplete={T(LAST, "11:29"), T(LAST, "13:00")}))
    assert out["raw_flag"].sum() == 2 and out["is_alert"].sum() == 0
