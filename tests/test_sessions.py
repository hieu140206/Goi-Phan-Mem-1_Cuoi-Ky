import pandas as pd

from finance.sessions import continuous_mask, filter_continuous

TZ = "Asia/Ho_Chi_Minh"


def ts(*hhmm):
    return pd.Series([pd.Timestamp(f"2026-10-22 {t}", tz=TZ) for t in hhmm])


def test_boundaries_of_continuous_session():
    s = ts("09:00", "09:14", "09:15", "11:29", "11:30", "12:00", "13:00", "14:29", "14:30", "14:45")
    keep = continuous_mask(s).tolist()
    assert keep == [False, False, True, True, False, False, True, True, False, False]


def test_filter_reports_dropped_count():
    df = pd.DataFrame({"ts": ts("09:05", "10:00", "12:00", "14:35"), "x": [1, 2, 3, 4]})
    out, dropped = filter_continuous(df)
    assert list(out["x"]) == [2] and dropped == 3


def test_filter_empty_frame():
    out, dropped = filter_continuous(pd.DataFrame({"ts": pd.Series([], dtype="datetime64[ns, Asia/Ho_Chi_Minh]")}))
    assert out.empty and dropped == 0
