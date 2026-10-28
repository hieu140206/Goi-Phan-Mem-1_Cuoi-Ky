"""Bộ ghi REST với client giả và đồng hồ giả (không gọi NEO, không chờ thật)."""
import gzip
import json
from pathlib import Path

import pandas as pd

from data.rest_recorder import RestRecorder, status_by_clock
from data.storage import load_quotes

REAL = json.loads((Path(__file__).parent / "fixtures" / "neo_rest_vn30_20261027.json").read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self, start):
        self.t = pd.Timestamp(start, tz="Asia/Ho_Chi_Minh")

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += pd.Timedelta(seconds=seconds)


class FakeClient:
    def __init__(self, clock, statuses):
        self.clock, self.statuses, self.calls = clock, statuses, 0

    def get_index_symbols(self, code):
        return sorted({r["symbol"] for r in REAL})

    def get_market_status(self, market):
        s = self.statuses(self.clock.now())
        if s == "ERR":
            raise ConnectionError("mất mạng")
        return [{"marketCode": "HOSE", "indexCode": "VNINDEX", "marketStatus": s}]

    def get_stocks_by_index(self, code):
        self.calls += 1
        return REAL

    def get_index_intraday(self, code):
        return {"indexCode": code, "index": []}

    def get_index_detail(self, code):
        return [{"indexCode": "VN30"}]


def by_clock_with(error_between=None):
    def f(now):
        if error_between and error_between[0] <= now.strftime("%H:%M") < error_between[1]:
            return "ERR"
        return status_by_clock(now)
    return f


def make(tmp_path, start, statuses, interval=60):
    clock = FakeClock(start)
    client = FakeClient(clock, statuses)
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=interval,
                       now_fn=clock.now, sleep_fn=clock.sleep, symbols_file=tmp_path / "symbols.txt")
    return rec, client


def test_status_by_clock():
    ts = lambda h, m: pd.Timestamp(f"2026-10-28 {h:02d}:{m:02d}", tz="Asia/Ho_Chi_Minh")
    assert [status_by_clock(ts(*x)) for x in [(8, 50), (9, 5), (10, 0), (12, 0), (14, 35), (14, 50)]] == \
        ["PRE", "ATO", "LO", "BREAK", "ATC", "C"]


def test_full_session_saves_only_continuous_and_stops_after_close(tmp_path):
    rec, client = make(tmp_path, "2026-10-28 09:05:00", by_clock_with(), interval=300)
    stats = rec.run()
    assert stats.end_reason == "đóng cửa (C)"
    assert stats.statuses_seen == ["ATO", "LO", "BREAK", "LO", "ATC", "C"]
    # 09:15-11:30 và 13:00-14:30, mỗi 5 phút
    assert stats.lo_snapshots == 27 + 18
    assert stats.raw_snapshots == stats.lo_snapshots + 2 + 3  # + ATO (09:05, 09:10) + ATC (14:30, 14:35, 14:40)
    q = load_quotes(tmp_path / "m.db")
    assert len(q) == 30 * stats.lo_snapshots == stats.rows_saved
    times = pd.to_datetime(q["ts"]).dt.strftime("%H:%M")
    assert times.min() == "09:15" and times.max() == "14:25" and not times.between("11:30", "12:59").any()
    with gzip.open(tmp_path / "raw" / "2026-10-28" / "stocks.jsonl.gz", "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh]
    assert len(lines) == stats.raw_snapshots and len(lines[0]["records"]) == 30
    assert (tmp_path / "raw" / "2026-10-28" / "market.json").exists()
    summary = pd.read_csv(tmp_path / "sessions.csv")
    assert summary.loc[0, "lo_snapshots"] == stats.lo_snapshots
    assert (tmp_path / "symbols.txt").read_text(encoding="utf-8").count("\n") == 31


def test_api_errors_fall_back_to_clock_and_do_not_stop(tmp_path):
    rec, _ = make(tmp_path, "2026-10-28 10:00:00", by_clock_with(("10:00", "10:05")))
    stats = rec.run(max_cycles=10)
    assert stats.status_fallbacks == 5 and stats.lo_snapshots == 10 and stats.errors == 0


def test_weekend_does_nothing(tmp_path):
    rec, client = make(tmp_path, "2026-10-31 09:30:00", by_clock_with())  # thứ 7
    stats = rec.run()
    assert stats.end_reason.startswith("cuối tuần") and client.calls == 0


def test_snapshot_failure_is_counted_not_fatal(tmp_path):
    rec, client = make(tmp_path, "2026-10-28 10:00:00", by_clock_with())
    calls = {"n": 0}
    real = client.get_stocks_by_index

    def flaky(code):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("chậm")
        return real(code)
    client.get_stocks_by_index = flaky
    stats = rec.run(max_cycles=4)
    assert stats.errors == 1 and stats.lo_snapshots == 3
