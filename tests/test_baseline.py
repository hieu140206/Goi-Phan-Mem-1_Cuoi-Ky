import numpy as np
import pandas as pd

from analytics.anomaly import detect_anomalies
from analytics.baseline import bucket_label, tod_bucket
from analytics.baseline import detect_anomalies_tod as _detect
from finance.liquidity import add_liquidity_metrics

TZ = "Asia/Ho_Chi_Minh"


def detect_anomalies_tod(df, **kw):
    """4 phiên của DAYS chỉ đủ cho mốc 2 phiên, nên các test cơ chế dưới đây đặt min_sessions=2 rõ ràng
    (mặc định hiện tại là 5, xem config.toml và tests/test_baseline_status.py)."""
    kw.setdefault("min_sessions", 2)
    return _detect(df, **kw)
DAYS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]


def session_times(day):
    morning = pd.date_range(f"{day} 09:15", f"{day} 11:29", freq="1min", tz=TZ)
    afternoon = pd.date_range(f"{day} 13:00", f"{day} 14:29", freq="1min", tz=TZ)
    return morning.append(afternoon)


def build(days=DAYS, seed=0, edit=None):
    """Mã AAA giá 20.000đ (bước giá 50đ), spread 1 bước giá. Độ sâu buổi sáng chỉ bằng 1/3 buổi chiều MỖI ngày."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in days:
        for t in session_times(day):
            qty = (3000.0 if t.hour < 12 else 9000.0) * rng.lognormal(0, 0.15)
            ticks = 1
            r = {"ts": t, "symbol": "AAA", "ticks": ticks, "qty": qty}
            if edit:
                edit(r)
            rows.append(r)
    out = []
    for r in rows:
        bid = 20_000.0
        ask = bid + 50 * r["ticks"]
        row = {"ts": r["ts"], "symbol": "AAA"}
        for i in (1, 2, 3):
            row[f"bid_px{i}"] = bid - (i - 1) * 50
            row[f"ask_px{i}"] = ask + (i - 1) * 50
            row[f"bid_qty{i}"] = r["qty"]
            row[f"ask_qty{i}"] = r["qty"]
        out.append(row)
    return add_liquidity_metrics(pd.DataFrame(out))


def test_buckets_start_at_each_continuous_session():
    ts = pd.Series(pd.to_datetime(["2026-10-30 09:15", "2026-10-30 09:44", "2026-10-30 09:45", "2026-10-30 11:29",
                                   "2026-10-30 13:00", "2026-10-30 14:29"]).tz_localize(TZ))
    # Mặc định mới: 9:15-9:30 là khung riêng 15 phút, các khung sau 30 phút (9:30-10:00 ...).
    assert tod_bucket(ts).tolist() == [0, 1, 1, 4, 100, 102]
    assert bucket_label(0) == "09:15" and bucket_label(1) == "09:30" and bucket_label(101) == "13:30"
    # Cách chia cũ (khung đầu cũng 30 phút) vẫn tái hiện được bằng first_minutes=30.
    assert tod_bucket(ts, first_minutes=30).tolist() == [0, 0, 1, 4, 100, 102]
    assert bucket_label(1, first_minutes=30) == "09:45"


def test_no_baseline_until_enough_prior_sessions():
    out = detect_anomalies_tod(build())
    day = out["ts"].dt.date.astype(str)
    assert out.loc[day.isin(DAYS[:2]), "n_hist"].isna().all()        # 2 phiên đầu: chưa có mốc
    assert out.loc[day.isin(DAYS[:2]), "is_alert"].sum() == 0
    assert out.loc[day == DAYS[2], "n_base_sessions"].eq(2).all()
    assert out.loc[day == DAYS[3], "n_base_sessions"].eq(3).all()


def test_regular_intraday_pattern_is_not_an_alert():
    df = build()
    new = detect_anomalies_tod(df)
    assert new["is_alert"].sum() == 0  # sáng mỏng hơn chiều ngày nào cũng vậy: không bất thường
    # Cửa sổ trượt cũ so đầu buổi sáng với chiều hôm trước nên báo "độ sâu mỏng" lúc mở cửa.
    old = detect_anomalies(df, window=60, min_periods=20)
    assert (old["is_alert"] & (old["ts"].dt.hour == 9)).sum() > 0


def test_baseline_ignores_current_and_future_sessions():
    a = detect_anomalies_tod(build())

    def wreck_last_day(r):
        if str(r["ts"].date()) == DAYS[3]:
            r["qty"] = 1.0
    b = detect_anomalies_tod(build(edit=wreck_last_day))
    early = a["ts"].dt.date.astype(str) != DAYS[3]
    pd.testing.assert_series_equal(a.loc[early, "z_depth"], b.loc[early, "z_depth"])
    pd.testing.assert_series_equal(a.loc[early, "base_depth"], b.loc[early, "base_depth"])


def _drop_depth(times):
    def edit(r):
        if r["ts"] in times:
            r["qty"] *= 0.05
    return edit


def test_alert_needs_two_consecutive_snapshots():
    t0 = pd.Timestamp(f"{DAYS[3]} 10:00", tz=TZ)
    single = detect_anomalies_tod(build(edit=_drop_depth({t0})))
    assert single["is_alert"].sum() == 0 and single["raw_flag"].sum() == 1

    three = {t0, t0 + pd.Timedelta("1min"), t0 + pd.Timedelta("2min")}
    out = detect_anomalies_tod(build(edit=_drop_depth(three))).set_index("ts")
    assert not out.loc[t0, "is_alert"]                          # lần đầu: chưa đủ 2 lần liên tiếp
    assert out.loc[t0 + pd.Timedelta("1min"), "is_alert"]
    assert out.loc[t0 + pd.Timedelta("1min"), "alert_start"]    # mở đầu đợt
    assert out.loc[t0 + pd.Timedelta("2min"), "is_alert"] and not out.loc[t0 + pd.Timedelta("2min"), "alert_start"]
    assert out.loc[t0 + pd.Timedelta("1min"), "alert_type"] == "Độ sâu mỏng"
    assert out["alert_start"].sum() == 1


def test_spread_alert_works_when_mad_is_zero():
    t0 = pd.Timestamp(f"{DAYS[3]} 13:10", tz=TZ)

    def widen(r):
        if r["ts"] in {t0, t0 + pd.Timedelta("1min")}:
            r["ticks"] = 3
    out = detect_anomalies_tod(build(edit=widen)).set_index("ts")
    row = out.loc[t0 + pd.Timedelta("1min")]
    assert row["base_spread_ticks"] == 1 and row["spread_ratio"] == 3
    assert row["is_alert"] and row["alert_type"] == "Spread mở rộng" and row["severity"] == "Cao"


def test_spread_widening_that_is_common_in_that_slot_is_not_alerted():
    # 2 bước giá xuất hiện khoảng 20% thời gian ở khung 13:00 mọi ngày -> không hiếm -> không cảnh báo.
    # Xuất hiện thành từng cặp liên tiếp để luật "kéo dài" không phải lý do chặn cảnh báo.
    def often_two(r):
        if r["ts"].hour == 13 and r["ts"].minute < 30 and r["ts"].minute % 10 in (0, 1):
            r["ticks"] = 2
    out = detect_anomalies_tod(build(edit=often_two))
    assert out["raw_flag"].sum() == 0 and out["is_alert"].sum() == 0
    two = out[(out["spread_ticks"] == 2) & out["n_hist"].notna()]
    assert len(two) > 0 and (two["spread_tail_share"] > 0.05).all()
