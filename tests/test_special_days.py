"""Mục B2: ngày đặc biệt đọc từ tệp (không viết cứng), ngày đáo hạn phái sinh tính bằng code, và ngày đặc biệt không làm mốc nền."""
import datetime as dt

import numpy as np
import pandas as pd

from analytics.baseline import detect_anomalies_tod
from data.special_days import (add_expiry_dates, derivative_expiry_dates, describe, is_market_holiday, load_special_days,
                               market_holiday_dates, no_data_message, special_day_map, third_thursday)
from finance.liquidity import add_liquidity_metrics

TZ = "Asia/Ho_Chi_Minh"


def test_third_thursday_known_months():
    assert third_thursday(2026, 10) == dt.date(2026, 10, 15)       # 1/10/2026 là thứ Năm: thứ Năm thứ ba là 15
    assert third_thursday(2026, 11) == dt.date(2026, 11, 19)
    assert third_thursday(2026, 12) == dt.date(2026, 12, 17)
    assert third_thursday(2026, 1) == dt.date(2026, 1, 15)
    for y in (2025, 2026, 2027):
        for m in range(1, 13):
            d = third_thursday(y, m)
            assert d.weekday() == 3 and 15 <= d.day <= 21         # luôn là thứ Năm, ngày 15 đến 21


def test_expiry_dates_in_range_across_year_end():
    got = derivative_expiry_dates(dt.date(2026, 11, 20), dt.date(2027, 1, 31))
    assert got == [dt.date(2026, 12, 17), dt.date(2027, 1, 21)]
    assert derivative_expiry_dates(dt.date(2026, 11, 20), dt.date(2026, 11, 30)) == []       # 19/11 nằm ngoài khoảng
    assert derivative_expiry_dates(dt.date(2026, 11, 19), dt.date(2026, 11, 19)) == [dt.date(2026, 11, 19)]


def test_loader_reads_valid_rows_and_skips_bad_ones(tmp_path, caplog):
    p = tmp_path / "s.csv"
    p.write_text("date,type,note\n2026-11-19,derivative_expiry,đáo hạn\n2026-11-20,earnings,\n"
                 "2026-11-21,khong_co_loai,x\n19/11/2026,other,sai dạng ngày\n2026-11-19,derivative_expiry,trùng\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        df = load_special_days(p)
    assert df["date"].tolist() == [dt.date(2026, 11, 19), dt.date(2026, 11, 20)]
    assert df["type"].tolist() == ["derivative_expiry", "earnings"]
    assert sum("bỏ qua" in m for m in caplog.messages) == 2        # loại sai và ngày sai: nói ra, không đoán


def test_missing_empty_or_headerless_file_gives_empty_table(tmp_path):
    assert load_special_days(tmp_path / "khong_co.csv").empty
    (tmp_path / "e.csv").write_text("", encoding="utf-8")
    assert load_special_days(tmp_path / "e.csv").empty
    (tmp_path / "h.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert load_special_days(tmp_path / "h.csv").empty


def test_map_and_description():
    p = {dt.date(2026, 11, 19): "derivative_expiry,earnings"}
    df = pd.DataFrame({"date": [dt.date(2026, 11, 19)] * 2, "type": ["derivative_expiry", "earnings"], "note": ["", ""]})
    assert special_day_map(df) == p
    assert describe("derivative_expiry,earnings") == "đáo hạn phái sinh, công bố kết quả kinh doanh"
    assert special_day_map(pd.DataFrame()) == {}


def test_add_expiry_dates_creates_file_and_never_removes_user_rows(tmp_path):
    p = tmp_path / "s.csv"
    assert add_expiry_dates(p, dt.date(2026, 10, 1), dt.date(2026, 12, 31)) == 3
    assert load_special_days(p)["date"].tolist() == [dt.date(2026, 10, 15), dt.date(2026, 11, 19), dt.date(2026, 12, 17)]
    with p.open("a", encoding="utf-8") as fh:
        fh.write("2026-12-21,index_review,tự điền\n")
    assert add_expiry_dates(p, dt.date(2026, 10, 1), dt.date(2026, 12, 31)) == 0                 # đã đủ: không thêm
    assert add_expiry_dates(p, dt.date(2027, 1, 1), dt.date(2027, 1, 31)) == 1
    df = load_special_days(p)
    assert (dt.date(2026, 12, 21), "index_review") in set(zip(df["date"], df["type"]))             # dòng tự điền còn nguyên


# ---- ngày đặc biệt không làm mốc nền ----
def _history(days):
    rng = np.random.default_rng(3)
    rows = []
    for day in days:
        for t in pd.date_range(f"{day} 10:00", f"{day} 10:59", freq="1min", tz=TZ):
            q = 5000.0 * rng.lognormal(0, 0.1)
            skew = rng.uniform(0.8, 1.25)
            r = {"ts": t, "symbol": "AAA"}
            for i in (1, 2, 3):
                r[f"bid_px{i}"], r[f"ask_px{i}"] = 20_000.0 - (i - 1) * 50, 20_050.0 + (i - 1) * 50
                r[f"bid_qty{i}"], r[f"ask_qty{i}"] = q, q * skew
            rows.append(r)
    return add_liquidity_metrics(pd.DataFrame(rows))


DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"]


def test_special_day_is_not_a_baseline_but_is_still_analyzed():
    df = _history(DAYS)
    special = {dt.date(2026, 11, 4)}
    plain = detect_anomalies_tod(df, min_sessions=2)
    excl = detect_anomalies_tod(df, min_sessions=2, no_baseline_days=special)
    last = lambda x: x[x["ts"].dt.date == dt.date(2026, 11, 10)]                          # noqa: E731
    assert last(plain)["n_base_sessions"].dropna().iloc[0] == 6
    assert last(excl)["n_base_sessions"].dropna().iloc[0] == 5                             # ngày đặc biệt không còn làm mốc
    on_day = excl[excl["ts"].dt.date == dt.date(2026, 11, 4)]
    assert on_day["n_base_sessions"].dropna().iloc[0] == 2                                 # chính ngày đó vẫn được phân tích
    assert on_day["baseline_status"].eq("Đủ dữ liệu").all()


def test_excluding_the_special_day_can_push_a_later_day_below_the_session_minimum():
    df = _history(DAYS[:6])                                                                # 6 phiên: phiên cuối có 5 phiên trước
    assert detect_anomalies_tod(df)["baseline_status"].iloc[-1] == "Đủ dữ liệu"
    excl = detect_anomalies_tod(df, no_baseline_days={dt.date(2026, 11, 3)})
    assert excl["baseline_status"].iloc[-1] == "Chưa đủ dữ liệu" and "hiện có 4" in excl["baseline_reason"].iloc[-1]


# ---- ngày nghỉ giao dịch (để giao diện giải thích vì sao không có dữ liệu) ----
def test_market_holiday_is_read_from_the_file_only(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("date,type,note\n2026-11-24,market_holiday,nghỉ\n2026-11-19,derivative_expiry,\n", encoding="utf-8")
    assert is_market_holiday(dt.date(2026, 11, 24), p)
    assert not is_market_holiday(dt.date(2026, 11, 19), p)             # ngày đáo hạn không phải ngày nghỉ
    assert not is_market_holiday(dt.date(2026, 11, 25), p)             # không tự đoán: ngày không ghi thì không phải ngày nghỉ
    assert not is_market_holiday(dt.date(2026, 11, 24), tmp_path / "khong_co.csv")
    assert describe("market_holiday") == "ngày nghỉ giao dịch"


def test_market_holiday_dates_lists_only_holidays_sorted(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("date,type,note\n2026-12-01,market_holiday,\n2026-11-24,market_holiday,\n2026-11-19,derivative_expiry,\n", encoding="utf-8")
    assert market_holiday_dates(p) == [dt.date(2026, 11, 24), dt.date(2026, 12, 1)]
    assert market_holiday_dates(tmp_path / "khong_co.csv") == []


def test_real_file_lists_24_11_as_holiday_and_it_does_not_disturb_analysis_days():
    assert is_market_holiday(dt.date(2026, 11, 24))
    df = load_special_days()
    assert dt.date(2026, 11, 19) in set(df[df["type"] == "derivative_expiry"]["date"])


def test_no_data_message_explains_holiday_but_not_ordinary_missing_days(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("date,type,note\n2026-11-24,market_holiday,nghỉ\n", encoding="utf-8")
    shown, have = dt.date(2026, 11, 20), {dt.date(2026, 11, 20)}
    holiday = no_data_message(dt.date(2026, 11, 24), shown, have, p)
    assert "ngày nghỉ giao dịch" in holiday and "không nhấp nháy" in holiday and "20/11/2026" in holiday
    ordinary = no_data_message(dt.date(2026, 11, 25), shown, have, p)                 # không ghi là ngày nghỉ: không đoán
    assert "ngày nghỉ" not in ordinary and ordinary.startswith("Chưa có dữ liệu phiên 25/11/2026")
    has_data = no_data_message(dt.date(2026, 11, 20), dt.date(2026, 11, 19), have, p)
    assert has_data.startswith("Đang xem phiên 19/11/2026")
