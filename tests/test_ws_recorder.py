import base64
import json
import sqlite3
from pathlib import Path

import pandas as pd

from data.storage import load_ws_quotes
from data.ws_recorder import WsBarRecorder
from neo_api.config import TZ

FIX = Path(__file__).parent / "fixtures" / "neo_ws_20261028_sample.jsonl"


def _msgs():
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        out.append(base64.b64decode(d["raw_b64"]))
    return out


def T(h, m, s=0, ms=0):
    return pd.Timestamp(2026, 10, 28, h, m, s, ms * 1000, tz=TZ)


def test_records_bars_and_raw(tmp_path):
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path, interval=5)
    t = T(10, 0, 1)
    for raw in _msgs():
        rec.on_raw(raw, t)
    n = rec.tick(T(10, 0, 5))
    assert n == rec.stats["stock_info"] and n > 0 or n == len(rec.state)
    df = load_ws_quotes(tmp_path / "m.db")
    assert len(df) == n
    assert {"n_msgs", "age_ms"} <= set(df.columns)
    assert (df["n_msgs"] >= 1).all()
    assert (df["ts"] == T(10, 0, 5)).all()
    # mốc kế không có tin: giữ trạng thái cũ, n_msgs = 0
    rec.tick(T(10, 0, 10))
    df2 = load_ws_quotes(tmp_path / "m.db")
    last = df2[df2["ts"] == T(10, 0, 10)]
    assert len(last) == n and (last["n_msgs"] == 0).all() and (last["age_ms"] >= 4000).all()
    rec.close()
    raw_file = tmp_path / "raw" / "2026-10-28" / "ws.jsonl.gz"
    assert raw_file.exists()
    stats = json.loads((tmp_path / "raw" / "2026-10-28" / "ws_stats.json").read_text(encoding="utf-8"))
    assert stats["messages"] == len(_msgs()) and stats["reconnects"] == 0


def test_bar_excludes_messages_after_its_slot(tmp_path):
    # Như phiên 3/11: tin đến 10:00:05,3 nhưng tick 10:00:05,8 mới chạy -> thanh 10:00:05 chỉ chứa tin trước mốc.
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path, interval=5)
    msgs = _msgs()
    for raw in msgs:
        rec.on_raw(raw, T(10, 0, 3))
    per_sym = dict(rec.n_msgs)
    for raw in msgs:
        rec.on_raw(raw, T(10, 0, 5, 300))   # sau mốc 10:00:05
    n = rec.tick(T(10, 0, 5, 800))
    df = load_ws_quotes(tmp_path / "m.db")
    bar = df[df["ts"] == T(10, 0, 5)].set_index("symbol")
    assert len(bar) == n > 0
    assert (bar["age_ms"] == 2000).all()                     # tin cuối lúc 10:00:03, không phải 0
    assert all(bar.loc[s, "n_msgs"] == c for s, c in per_sym.items() if s in bar.index)
    # tin sau mốc thuộc thanh kế tiếp
    rec.tick(T(10, 0, 10, 100))
    nxt = load_ws_quotes(tmp_path / "m.db").query("ts == @T(10, 0, 10)").set_index("symbol")
    assert (nxt["age_ms"] == 4700).all()
    assert all(nxt.loc[s, "n_msgs"] == c for s, c in per_sym.items() if s in nxt.index)


def _book(sym, bid, ask, ceil=28_350.0, floor=24_650.0):
    row = {"symbol": sym, "last_px": bid, "total_vol": 1000, "ref_px": 26_500.0, "ceil_px": ceil, "floor_px": floor}
    for i in (1, 2, 3):
        row[f"bid_px{i}"], row[f"bid_qty{i}"] = bid - (i - 1) * 50, 1000.0
        row[f"ask_px{i}"], row[f"ask_qty{i}"] = (ask + (i - 1) * 50, 1000.0) if ask else (None, None)
    return row


def test_limit_locked_symbol_is_kept_like_rest(tmp_path, monkeypatch):
    # Như TCX chiều 4/11: tăng trần, bên bán trống. REST lưu dòng này (bên bán rỗng); WS trước đây bỏ mất.
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    import export_data as ed

    rec = WsBarRecorder(tmp_path / "m.db", tmp_path, interval=5)
    rec._update_state(_book("TCX", 28_350.0, None), T(13, 5, 2))
    rec._update_state(_book("AAA", 28_300.0, 28_350.0), T(13, 5, 2))
    assert rec.tick(T(13, 5, 5)) == 2
    df = load_ws_quotes(tmp_path / "m.db").set_index("symbol")
    assert df.loc["TCX", "bid_px1"] == 28_350.0 and pd.isna(df.loc["TCX", "ask_px1"])
    assert df.loc["TCX", "n_msgs"] == 1 and df.loc["TCX", "age_ms"] == 3000
    # khi xuất/phân tích, dòng khóa trần bị tách ra giống REST (spread không tính được)
    class S: db_path = tmp_path / "m.db"
    monkeypatch.setattr(ed, "get_settings", lambda: S())
    out = ed.load_ws_table()
    assert out["symbol"].tolist() == ["AAA"] and out["n_msgs"].tolist() == [1]


def test_same_slot_and_off_hours_write_nothing(tmp_path):
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path, interval=5)
    for raw in _msgs():
        rec.on_raw(raw, T(7, 0, 1))
    assert rec.tick(T(7, 0, 5)) == 0          # ngoài giờ giao dịch: không ghi
    for raw in _msgs():
        rec.on_raw(raw, T(10, 0, 1))
    assert rec.tick(T(10, 0, 5)) > 0
    assert rec.tick(T(10, 0, 6)) == 0          # cùng mốc: không ghi lại


def test_stale_symbols_dropped(tmp_path):
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path, interval=5)
    for raw in _msgs():
        rec.on_raw(raw, T(10, 0, 1))
    assert rec.tick(T(10, 20, 0)) == 0         # quá 15 phút không có tin


def test_stream_forever_with_fake_socket(tmp_path, monkeypatch):
    import asyncio
    import threading

    import data.ws_recorder as wr

    sent = []

    class FakeWs:
        def __init__(self): self.msgs = _msgs()
        async def send(self, m): sent.append(m)
        def __aiter__(self): return self
        async def __anext__(self):
            if not self.msgs:
                raise StopAsyncIteration
            return self.msgs.pop(0)

    class Ctx:
        async def __aenter__(self): return FakeWs()
        async def __aexit__(self, *a): return False

    async def fake_auth(ws, token): sent.append("auth")
    monkeypatch.setattr(wr, "connect_ws", lambda url: Ctx())
    monkeypatch.setattr(wr, "_authenticate", fake_auth)
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path)
    stop = threading.Event()
    rec.now = lambda: T(10, 0, 1)

    class S: ws_url = "wss://x"
    async def go():
        task = asyncio.ensure_future(wr.stream_forever(["VCB"], rec, S(), lambda: "tok", stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, 3)
    asyncio.run(go())
    assert rec.stats["messages"] == len(_msgs())
    assert sent[0] == "auth" and sent[1] == '{"type": "sync", "data": ""}'
    channels = [json.loads(m)["channel"] for m in sent[2:]]
    assert channels == ["stockInfo", "marketData", "marketInfo", "marketVolume", "marketSession"]


def test_inspect_lunch_script(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    import inspect_ws_lunch as il

    rec = WsBarRecorder(tmp_path / "m.db", tmp_path)
    msgs = _msgs()
    for raw in msgs:
        rec.on_raw(raw, T(11, 40, 1))
    for raw in msgs:                      # tin lặp lại y hệt: không có trường nào đổi
        rec.on_raw(raw, T(11, 41, 1))
    rec.flush_raw(T(11, 41, 1))
    r = il.analyze(tmp_path / "raw" / "2026-10-28" / "ws.jsonl.gz")
    assert r["types"].get("stockInfo", 0) > 0
    assert r["stock_changed"] + r["stock_same"] > 0
    assert r["stock_changed"] == 0 or r["changed_fields"]


def test_lunch_break_writes_no_bars_but_keeps_raw(tmp_path):
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path)
    for raw in _msgs():
        rec.on_raw(raw, T(11, 29, 58))
    assert rec.tick(T(11, 30, 0)) == 0
    for raw in _msgs():
        rec.on_raw(raw, T(12, 0, 1))
    assert rec.tick(T(12, 0, 5)) == 0
    assert rec.tick(T(12, 59, 55)) == 0
    rec.flush_raw(T(12, 59, 55))
    assert (tmp_path / "raw" / "2026-10-28" / "ws.jsonl.gz").exists()
    for raw in _msgs():
        rec.on_raw(raw, T(13, 0, 1))
    assert rec.tick(T(13, 0, 5)) > 0


def test_export_ws_to_csv_and_excel(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    import export_data as ed

    rec = WsBarRecorder(tmp_path / "m.db", tmp_path)
    for raw in _msgs():
        rec.on_raw(raw, T(10, 0, 1))
    rec.tick(T(10, 0, 5))

    class S: db_path = tmp_path / "m.db"
    monkeypatch.setattr(ed, "get_settings", lambda: S())
    monkeypatch.setattr(ed, "ROOT", tmp_path)
    ed.export_ws("2026-10-28", True)
    assert (tmp_path / "data" / "export" / "so_lenh_ws_2026-10-28.csv").exists()
    x = pd.read_excel(tmp_path / "data" / "export" / "so_lenh_ws_2026-10-28.xlsx", sheet_name=None)
    assert set(x) == {"Tổng hợp", "2026-10-28"}
    assert "Số tin WS trong 5 giây" in x["2026-10-28"].columns and len(x["2026-10-28"]) > 0
