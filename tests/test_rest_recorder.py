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
    assert stats.end_reason == "hết phiên khớp lệnh (C)"
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


def test_real_status_sequence_stops_at_put_through(tmp_path):
    """Trình tự thật 28/10/2026: ATO -> LO -> L -> LO -> ATC -> PT. Phải dừng khi gặp PT, không chờ tới 15:00."""
    def real(now):
        s = status_by_clock(now)
        return {"BREAK": "L", "C": "PT"}.get(s, s)
    rec, _ = make(tmp_path, "2026-10-28 09:05:00", real, interval=300)
    stats = rec.run()
    assert stats.end_reason == "hết phiên khớp lệnh (PT)" and stats.finished == "14:45:00"
    assert stats.statuses_seen == ["ATO", "LO", "L", "LO", "ATC", "PT"] and stats.lo_snapshots == 45


def test_after_hours_run_writes_no_empty_summary(tmp_path):
    """Chạy thử sau 15:00: không chụp lần nào, không lỗi -> không thêm dòng rỗng vào sessions.csv."""
    clock = FakeClock("2026-10-28 18:49:00")  # thứ Tư
    client = FakeClient(clock, lambda t: "C")
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60,
                       now_fn=clock.now, sleep_fn=clock.sleep)
    stats = rec.run()
    assert stats.end_reason == "quá 15:00" and stats.raw_snapshots == 0
    assert not (tmp_path / "sessions.csv").exists()


MARKET = json.loads((Path(__file__).parent / "fixtures" / "neo_market_20261027.json").read_text(encoding="utf-8"))


def test_recorder_saves_index_snapshots_for_overview(tmp_path):
    """Mỗi lần chụp còn lưu 4.3 (VNINDEX, VN30, HNX, UPCOM...) vào bảng market_index; lỗi 4.3 không làm mất sổ lệnh."""
    from data.storage import load_market_index

    clock = FakeClock("2026-10-28 10:00:00")
    client = FakeClient(clock, lambda t: "LO")
    client.get_index_detail = lambda code: MARKET["4.3 marketIndexDetail"]
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60,
                       now_fn=clock.now, sleep_fn=clock.sleep)
    rec.run(max_cycles=3)
    idx = load_market_index(tmp_path / "m.db")
    assert {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"} <= set(idx["index_code"])
    assert "FU" not in set(idx["index_code"])
    assert idx["ts"].nunique() == 3
    assert str(idx["ts"].dt.tz) == "Asia/Ho_Chi_Minh"
    vn = idx[idx["index_code"] == "VNINDEX"].iloc[0]
    assert vn["index_value"] == 1761.87 and vn["advances"] == 123 and vn["declines"] == 197
    assert len(load_quotes(tmp_path / "m.db")) == 90  # sổ lệnh vẫn lưu đủ 3 lần x 30 mã


def test_index_failure_does_not_lose_order_book(tmp_path):
    clock = FakeClock("2026-10-28 10:00:00")
    client = FakeClient(clock, lambda t: "LO")  # FakeClient không có get_index_detail -> lỗi
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60,
                       now_fn=clock.now, sleep_fn=clock.sleep)
    stats = rec.run(max_cycles=2)
    assert stats.lo_snapshots == 2 and len(load_quotes(tmp_path / "m.db")) == 60


def test_recorder_stores_ceiling_floor_and_last_volume(tmp_path):
    """Bộ ghi lưu giá trần, giá sàn, KL khớp gần nhất đúng như NEO trả về (cho bảng giá)."""
    clock = FakeClock("2026-10-28 10:00:00")
    client = FakeClient(clock, lambda t: "LO")
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60,
                       now_fn=clock.now, sleep_fn=clock.sleep)
    rec.run(max_cycles=1)
    q = load_quotes(tmp_path / "m.db").set_index("symbol")
    for r in REAL:
        assert q.loc[r["symbol"], "ceil_px"] == r["ceilingPrice"]
        assert q.loc[r["symbol"], "floor_px"] == r["floorPrice"]
        assert q.loc[r["symbol"], "last_vol"] == r["closeVol"]


def test_end_of_day_saves_series_for_all_four_indices(tmp_path):
    clock = FakeClock("2026-10-28 14:40:00")
    client = FakeClient(clock, lambda t: "LO" if t.time() < pd.Timestamp("2026-10-28 14:41", tz="Asia/Ho_Chi_Minh").time() else "PT")
    asked = []
    client.get_index_intraday = lambda code: asked.append(code) or {"indexCode": code, "index": []}
    client.get_index_detail = lambda code: MARKET["4.3 marketIndexDetail"]
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60,
                       now_fn=clock.now, sleep_fn=clock.sleep)
    rec.run()
    assert asked == ["VN30", "VNINDEX", "HNXINDEX", "UPCOMINDEX"]
    saved = json.loads((tmp_path / "raw" / "2026-10-28" / "market.json").read_text(encoding="utf-8"))
    assert {"intraday_HNXINDEX", "intraday_UPCOMINDEX", "index_detail"} <= set(saved)


def test_finalize_close_keeps_refreshing_vn30_board_after_atc(tmp_path):
    """30/10: bảng dừng ở 14:44 nên tổng khối lượng thiếu đúng khối lượng khớp ATC. Sau ATC phải còn làm mới bảng tới 15:02."""
    from data.storage import load_board

    clock = FakeClock("2026-10-28 14:46:00")
    client = FakeClient(clock, lambda t: "PT")
    rec = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60,
                       now_fn=clock.now, sleep_fn=clock.sleep, record_boards=True)
    rec.finalize_close()
    assert client.calls >= 30                       # ~33 lần hỏi 4.7 trong 16 phút, mỗi 30 giây
    board = load_board(tmp_path / "m.db", "2026-10-28", "VN30")
    assert len(board) == 30 and board["ts"].max().strftime("%H:%M") >= "15:00"
