"""Bảng giá toàn thị trường, độ sâu theo sàn, phái sinh và vòng chỉ số nhanh (client giả, đồng hồ giả)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from data.market_board import board_frame, depth_row, futures_frame
from data.rest_recorder import RestRecorder
from data.storage import board_days, load_board, load_depth_market, load_futures, load_market_index
from test_rest_recorder import REAL, FakeClient, FakeClock

TS = pd.Timestamp("2026-10-29 10:00:00", tz="Asia/Ho_Chi_Minh")


def rec(symbol, ref=10000.0, last=10100.0, bid1=10000.0, ask1=10100.0, bq=100.0, aq=200.0, **kw):
    r = {"symbol": symbol, "refPrice": ref, "closePrice": last, "ceilingPrice": ref * 1.07, "floorPrice": ref * 0.93,
         "bidPrice1": bid1, "bidVol1": bq, "askPrice1": ask1, "askVol1": aq, "totalTradingVolume": 5000.0}
    r.update(kw)
    return r


def test_board_frame_keeps_values_and_blanks_zero_prices():
    df = board_frame([rec("AAA"), rec("BBB", last=0, bid1="ATO", ask1=0)], TS, "HNX")
    assert list(df["grp"].unique()) == ["HNX"] and df["day"].iloc[0] == "2026-10-29"
    a = df[df.symbol == "AAA"].iloc[0]
    assert (a.ref_px, a.last_px, a.bid_px1, a.ask_px1, a.total_vol) == (10000.0, 10100.0, 10000.0, 10100.0, 5000.0)
    b = df[df.symbol == "BBB"].iloc[0]
    assert pd.isna(b.last_px) and b.bid_px1 == "ATO" and pd.isna(b.ask_px1)  # 0 -> trống, ATO giữ chữ


def test_board_frame_drops_duplicate_symbols_and_empty_input():
    assert len(board_frame([rec("AAA"), rec("AAA", last=10200.0)], TS, "HOSE")) == 1
    assert board_frame([], TS, "HOSE").empty


def test_depth_row_sums_value_of_three_levels():
    frame = board_frame([rec("AAA", bq=100, aq=50, bidPrice2=9900.0, bidVol2=10.0), rec("BBB", bid1="ATO", ask1="ATO")], TS, "HOSE")
    d = depth_row(frame, TS, "HOSE").iloc[0]
    assert d.bid_value == 10000 * 100 + 9900 * 10   # BBB: chữ ATO không có giá để nhân nên tính 0
    assert d.ask_value == 10100 * 50
    assert d.n_symbols == 1


def test_futures_frame_names_and_open_interest():
    raw = [rec("41I1GB000", ref=1893.0, last=1892.3, bid1="1892.6", ask1="1892.7", openInterest=33664.0, maturityDate="20/11/2026")]
    f = futures_frame(raw, TS, {"41I1GB000": "VN30F1M"}).iloc[0]
    assert (f["name"], f.maturity, f.open_interest, f.bid_px1, f.last_px) == ("VN30F1M", "20/11/2026", 33664.0, 1892.6, 1892.3)


# ---------- bộ ghi ----------
class BoardClient(FakeClient):
    def __init__(self, clock, statuses, fail_group=None, list_fails=False):
        super().__init__(clock, statuses)
        self.fail_group, self.list_fails = fail_group, list_fails
        self.index_calls, self.detail_calls = 0, []
        self.hose = [f"H{i:03d}" for i in range(450)]  # > CHUNK để thử chia nhỏ

    def get_index_detail(self, code):
        self.index_calls += 1
        return [{"indexCode": "VN30", "indexValue": 1893.0 + self.index_calls, "indexChange": 1.0, "indexPercentChange": 0.1}]

    def get_stock_list(self, market):
        if self.list_fails:
            raise ConnectionError("mất mạng")
        if market == "HOSE":
            return ([{"symbol": s, "stockType": "ST"} for s in self.hose] + [{"symbol": "E1", "stockType": "EF"},
                    {"symbol": "CW1", "stockType": "CW"}])
        if market == "HNX":
            return [{"symbol": "N1", "stockType": "ST"}, {"symbol": "N2", "stockType": "ST"}]
        if market == "UPCOM":
            return [{"symbol": "U1", "stockType": "ST"}]
        return [{"symbol": "41I1GB000", "stockType": "FUVN30", "otherName": "VN30F1M"},
                {"symbol": "41I1X0000", "stockType": "FUGB", "otherName": "GB"}]

    def get_stock_detail(self, symbols, market="ALL", stock_type="ST", page_size=1000):
        self.detail_calls.append((market, stock_type, len(symbols)))
        if self.fail_group == market and stock_type == "ST":
            raise ConnectionError("lỗi")
        return [rec(s, bid1=9900.0, ask1=10000.0) for s in symbols]

    def get_fu_detail(self, symbols=None, stock_type="FUVN30"):
        return [rec("41I1GB000", ref=1893.0, last=1892.3, bid1=1892.6, ask1=1892.7, openInterest=100.0, maturityDate="20/11/2026")]


def make(tmp_path, start, client_kw=None, **kw):
    clock = FakeClock(start)
    client = BoardClient(clock, lambda now: "LO", **(client_kw or {}))
    r = RestRecorder(client, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60, now_fn=clock.now,
                     sleep_fn=clock.sleep, symbols_file=tmp_path / "s.txt", **kw)
    return r, client


def test_recorder_saves_boards_depth_and_futures(tmp_path):
    r, c = make(tmp_path, "2026-10-29 10:00:00", record_boards=True)
    r.run(max_cycles=3)
    db = tmp_path / "m.db"
    assert board_days(db) == ["2026-10-29"]
    assert len(load_board(db, "2026-10-29", "HOSE")) == 450 and len(load_board(db, "2026-10-29", "HNX")) == 2
    assert len(load_board(db, "2026-10-29", "UPCOM")) == 1 and len(load_board(db, "2026-10-29", "CW")) == 1
    assert len(load_board(db, "2026-10-29", "ETF")) == 1
    # chia nhỏ 450 mã thành 2 lần gọi (300 + 150)
    assert [n for m, t, n in c.detail_calls if m == "HOSE" and t == "ST"][:2] == [300, 150]
    # bảng giá ghi đè: sau 3 lần chụp vẫn một dòng mỗi mã, ts là lần chụp cuối
    hose = load_board(db, "2026-10-29", "HOSE")
    assert hose["ts"].max() == pd.Timestamp("2026-10-29 10:02:00", tz="Asia/Ho_Chi_Minh")
    depth = load_depth_market(db)
    assert sorted(depth["grp"].unique()) == ["CW", "ETF", "HNX", "HOSE", "UPCOM"] and len(depth[depth.grp == "HOSE"]) == 3
    assert depth[depth.grp == "HNX"]["bid_value"].iloc[0] == 2 * 9900 * 100
    fut = load_futures(db)
    assert len(fut) == 3 and fut["name"].iloc[0] == "VN30F1M" and fut["open_interest"].iloc[0] == 100.0
    assert (tmp_path / "raw" / "2026-10-29" / "board.jsonl.gz").exists()


def test_boards_off_by_default(tmp_path):
    r, c = make(tmp_path, "2026-10-29 10:00:00")
    r.run(max_cycles=2)
    assert c.detail_calls == [] and board_days(tmp_path / "m.db") == []


def test_one_group_failing_does_not_stop_others_or_vn30(tmp_path):
    r, c = make(tmp_path, "2026-10-29 10:00:00", client_kw={"fail_group": "HNX"}, record_boards=True)
    stats = r.run(max_cycles=2)
    db = tmp_path / "m.db"
    assert len(load_board(db, "2026-10-29", "HNX")) == 0 and len(load_board(db, "2026-10-29", "HOSE")) == 450
    assert stats.lo_snapshots == 2 and stats.errors == 0  # sổ lệnh VN30 vẫn ghi đủ


def test_stock_list_failure_is_survivable(tmp_path):
    r, c = make(tmp_path, "2026-10-29 10:00:00", client_kw={"list_fails": True}, record_boards=True)
    stats = r.run(max_cycles=2)
    assert stats.lo_snapshots == 2 and c.detail_calls == []
    assert len(load_futures(tmp_path / "m.db")) == 2  # phái sinh không phụ thuộc 4.5


def test_fast_index_loop_polls_between_snapshots(tmp_path):
    r, c = make(tmp_path, "2026-10-29 10:00:00", fast_index_seconds=5)
    r.run(max_cycles=3)
    idx = load_market_index(tmp_path / "m.db")
    vn30 = idx[idx.index_code == "VN30"]
    # 3 lần chụp phút + khoảng 11 lần hỏi nhanh mỗi phút giữa hai lần chụp
    assert len(vn30) >= 3 + 2 * 10
    secs = vn30["ts"].dt.second.unique()
    assert set(secs) >= {0, 5, 10, 55}
    assert c.index_calls == len(vn30) + 1  # mỗi lần hỏi lưu đúng một dòng; +1 là lần gọi 4.3 cuối ngày (không lưu vào bảng)


def test_fast_loop_idle_when_market_not_active(tmp_path):
    clock = FakeClock("2026-10-29 11:40:00")
    c = BoardClient(clock, lambda now: "L")  # nghỉ trưa
    r = RestRecorder(c, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60, now_fn=clock.now, sleep_fn=clock.sleep,
                     fast_index_seconds=5)
    r.run(max_cycles=2)
    assert c.index_calls == 0


# ---------- hàm đọc cho chế độ Trực tiếp ----------
def test_live_stamp_changes_with_orderbook_not_with_index_ticks(tmp_path):
    from data.market import index_detail_frame
    from data.storage import latest_ts, live_stamp, save_board, save_market_index, data_days, load_market_index

    db = tmp_path / "m.db"
    assert live_stamp(db) is None and data_days(db) == [] and latest_ts(db, "2026-10-29") is None
    save_board(board_frame([rec("AAA")], TS, "HNX"), db)
    s1 = live_stamp(db)
    # chỉ số ghi thêm mỗi 5 giây: stamp KHÔNG đổi (để trang không chạy lại vô ích)
    for sec in (5, 10, 15):
        save_market_index(index_detail_frame([{"indexCode": "VN30", "indexValue": 1900.0}], TS + pd.Timedelta(seconds=sec)), db)
    assert live_stamp(db) == s1
    save_board(board_frame([rec("AAA")], TS + pd.Timedelta(minutes=1), "HNX"), db)
    assert live_stamp(db) != s1
    assert data_days(db) == ["2026-10-29"]
    assert latest_ts(db, "2026-10-29") == TS + pd.Timedelta(minutes=1)
    assert latest_ts(db, "2026-10-28") is None
    only = load_market_index(db, "2026-10-29")
    assert len(only) == 3 and len(load_market_index(db, "2026-10-28")) == 0


def test_depth_and_futures_views():
    from data.market_board import depth_row
    from data.overview import futures_view, market_depth_group

    f = board_frame([rec("AAA", bq=100, aq=50)], TS, "HNX")
    depth = pd.concat([depth_row(f, TS, "HNX"), depth_row(f, TS + pd.Timedelta(minutes=1), "HNX"), depth_row(f, TS, "HOSE")])
    g = market_depth_group(depth, TS.date(), "HNX")
    assert len(g) == 2 and g["bid_value"].iloc[0] == pytest.approx(10000 * 100 / 1e9)
    assert g["imbalance"].iloc[0] == pytest.approx((1_000_000 - 505_000) / (1_000_000 + 505_000))
    assert market_depth_group(depth, TS.date(), "UPCOM").empty

    raw = [rec("41I1GC000", last=1892.1, bid1="1890.6", ask1="1893.5", maturityDate="18/12/2026"),
           rec("41I1GB000", last=1892.3, bid1="1892.6", ask1="1892.7", maturityDate="20/11/2026")]
    v = futures_view(futures_frame(raw, TS, {"41I1GB000": "VN30F1M", "41I1GC000": "VN30F2M"}), 1893.96)
    assert list(v["symbol"]) == ["VN30F1M", "VN30F2M"]  # sắp theo ngày đáo hạn
    assert v["basis"].iloc[0] == pytest.approx(1892.3 - 1893.96)
    assert futures_view(futures_frame(raw, TS), None)["basis"].isna().all()  # chưa có chỉ số: để trống, không đoán


def test_fast_loop_refreshes_vn30_board_for_display(tmp_path):
    r, c = make(tmp_path, "2026-10-29 10:00:00", fast_index_seconds=5, record_boards=True)
    r.run(max_cycles=3)
    from data.storage import load_board, load_quotes
    b = load_board(tmp_path / "m.db", "2026-10-29", "VN30")
    assert len(b) == 30 and b["ts"].dt.second.iloc[0] in range(0, 60, 5)   # bảng giá VN30 làm mới theo nhịp 5 giây
    assert b["ts"].max() > pd.Timestamp("2026-10-29 10:01:00", tz="Asia/Ho_Chi_Minh")
    assert len(load_quotes(tmp_path / "m.db")) == 30 * 3                    # sổ lệnh phân tích vẫn chỉ mỗi phút
    # tắt bảng giá thì vòng nhanh không gọi 4.7 thêm
    r2, c2 = make(tmp_path / "x", "2026-10-29 10:00:00", fast_index_seconds=5)
    r2.run(max_cycles=3)
    assert c2.calls == 3


def test_recorder_keeps_polling_indices_until_1502_after_close(tmp_path):
    from test_rest_recorder import by_clock_with

    clock = FakeClock("2026-10-29 14:28:00")
    c = BoardClient(clock, by_clock_with())
    r = RestRecorder(c, db_path=tmp_path / "m.db", data_dir=tmp_path, interval=60, now_fn=clock.now, sleep_fn=clock.sleep,
                     symbols_file=tmp_path / "s.txt")
    stats = r.run()
    assert stats.finished.startswith("14:4")        # tóm tắt ghi giờ hết phiên khớp lệnh, không phải giờ chờ chốt số
    idx = load_market_index(tmp_path / "m.db")
    last = idx[idx.index_code == "VN30"]["ts"].max()
    assert last.strftime("%H:%M") >= "15:02"        # đã hỏi chỉ số tới 15:02 để lấy số đóng cửa chính thức
    assert (tmp_path / "raw" / "2026-10-29" / "market.json").exists()


def test_close_snapshot_saves_final_indices_vn30_board_and_groups(tmp_path):
    from data.market_day import TooEarlyError, save_close_snapshot
    from data.storage import load_board

    clock = FakeClock("2026-10-29 15:30:00")
    c = BoardClient(clock, lambda now: "C")
    res = save_close_snapshot(c, tmp_path / "m.db", tmp_path, clock.now())
    assert res["indices"] == 1 and res["vn30"] == 30 and res["errors"] == {}
    assert res["groups"] == {"HOSE": 450, "HNX": 2, "UPCOM": 1, "ETF": 1, "CW": 1}
    assert len(load_board(tmp_path / "m.db", "2026-10-29", "VN30")) == 30
    assert load_depth_market(tmp_path / "m.db").empty          # trạng thái C: không ghi độ sâu theo phút
    with pytest.raises(TooEarlyError):
        save_close_snapshot(c, tmp_path / "m.db", tmp_path, pd.Timestamp("2026-10-29 14:50", tz="Asia/Ho_Chi_Minh"))
