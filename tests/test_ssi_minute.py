"""Sổ lệnh SSI lấy mẫu mỗi phút, và quy tắc "ngày SSI không làm mốc cho ngày NEO"."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analytics.baseline import detect_anomalies_tod  # noqa: E402
from data import ssi  # noqa: E402
from finance.liquidity import add_liquidity_metrics  # noqa: E402


def _make_db(tmp_path, rows):
    db = tmp_path / "m.db"
    con = sqlite3.connect(db)
    cols = ssi.SSI_QUOTE_COLS
    con.execute("CREATE TABLE ssi_quotes (ts TEXT, symbol TEXT, " + ", ".join(f"{c} REAL" for c in cols) + ")")
    for ts, sym, bid in rows:
        vals = [bid, bid - 50, bid - 100, 1000, 2000, 3000, bid + 50, bid + 100, bid + 150, 1100, 2100, 3100]
        con.execute(f"INSERT INTO ssi_quotes VALUES (?,?,{','.join('?' * 12)})", (ts, sym, *vals))
    con.commit()
    con.close()
    return db


def test_minute_sampling_takes_latest_bar_not_after_mark_and_drops_stale(tmp_path):
    d = "2026-11-12"
    rows = [
        (f"{d}T09:15:55+07:00", "AAA", 20000), (f"{d}T09:16:00+07:00", "AAA", 20100),   # đúng phút: lấy 20100
        (f"{d}T09:16:05+07:00", "AAA", 20200),                                           # sau phút 09:16: không dùng cho 09:16
        (f"{d}T09:16:55+07:00", "AAA", 20300),                                           # phút 09:17: lấy 20300
        (f"{d}T10:00:00+07:00", "AAA", 20500),                                           # 10:00; sau đó im lặng >60 giây
    ]
    out = ssi.load_ssi_minute_quotes(_make_db(tmp_path, rows), [d]).set_index("ts")
    t = lambda hm: pd.Timestamp(f"{d} {hm}:00", tz="Asia/Ho_Chi_Minh")  # noqa: E731
    assert out.loc[t("09:16"), "bid_px1"] == 20100
    assert out.loc[t("09:17"), "bid_px1"] == 20300
    assert t("10:00") in out.index and out.loc[t("10:00"), "bid_px1"] == 20500
    assert t("10:02") not in out.index                                                    # quá 60 giây không có thanh mới: bỏ, không điền
    assert t("09:15") not in out.index                                                    # chỉ các phút có lần chụp NEO (từ 09:16)


def test_columns_without_ssi_source_are_absent():
    cols = set(ssi.SSI_QUOTE_COLS)
    assert "last_px" not in cols and "total_vol" not in cols   # SSI không có: để trống khi chuẩn hóa, không đoán


def _frame(days, depth_by_day):
    rows = []
    for d in days:
        for m in range(60):
            ts = pd.Timestamp(f"{d} 10:{m:02d}:00", tz="Asia/Ho_Chi_Minh")
            rows.append({"ts": ts, "symbol": "AAA", "bid_px1": 20000.0, "ask_px1": 20050.0,
                         "bid_px2": 19950.0, "ask_px2": 20100.0, "bid_px3": 19900.0, "ask_px3": 20150.0,
                         "bid_qty1": depth_by_day[d], "ask_qty1": depth_by_day[d], "bid_qty2": depth_by_day[d],
                         "ask_qty2": depth_by_day[d], "bid_qty3": depth_by_day[d], "ask_qty3": depth_by_day[d],
                         "last_px": 20000.0, "total_vol": float(m * 1000)})
    return add_liquidity_metrics(pd.DataFrame(rows))


def test_excluded_day_is_not_baseline_and_empty_exclusion_changes_nothing():
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]
    depth = {"2026-11-02": 1000, "2026-11-03": 2000, "2026-11-04": 9000, "2026-11-05": 1000}
    df = _frame(days, depth)
    plain = detect_anomalies_tod(df)
    same = detect_anomalies_tod(df, no_baseline_days=set())
    pd.testing.assert_frame_equal(plain, same, check_exact=True)                 # rỗng: y hệt trước đây
    excl = detect_anomalies_tod(df, no_baseline_days={pd.Timestamp("2026-11-04").date()})
    d5 = lambda x: x[x["ts"].dt.date == pd.Timestamp("2026-11-05").date()]       # noqa: E731
    assert d5(plain)["n_base_sessions"].dropna().iloc[0] == 3
    assert d5(excl)["n_base_sessions"].dropna().iloc[0] == 2                      # ngày loại không làm mốc
    assert d5(excl)["base_depth"].dropna().iloc[0] < d5(plain)["base_depth"].dropna().iloc[0]   # mốc không còn ngày 9000
    d4 = excl[excl["ts"].dt.date == pd.Timestamp("2026-11-04").date()]
    assert d4["n_base_sessions"].dropna().iloc[0] == 2                            # chính ngày loại vẫn được so với mốc
