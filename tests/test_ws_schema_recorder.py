"""Bộ ghi WebSocket giải mã bằng schema Avro thật của máy chủ NEO (lấy bằng scripts/probe_ws_schema.py ngày 2/11/2026)."""
import base64
import hashlib
import io
import json
import zlib
from pathlib import Path

import fastavro
import pandas as pd

from data.storage import load_ws_quotes, load_ws_trades
from data.ws_recorder import WsBarRecorder
from neo_api.config import TZ

FIX = Path(__file__).parent / "fixtures"
SCHEMAS = {int(k): v for k, v in json.loads((FIX / "neo_ws_schemas_20261102.json").read_text(encoding="utf-8")).items()}
PARSED = {k: fastavro.parse_schema(v) for k, v in SCHEMAS.items()}


def frame(sid: int, rec: dict) -> bytes:
    """Mã hóa một bản ghi giống máy chủ: 1 byte id schema + bản ghi Avro. Trường không cho giá trị để trống (null)."""
    full = {f["name"]: rec.get(f["name"]) for f in SCHEMAS[sid]["fields"]}
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, PARSED[sid], full)
    return bytes([sid]) + buf.getvalue()


def sync_payload() -> bytes:
    return base64.b64encode(zlib.compress(json.dumps({str(k): v for k, v in SCHEMAS.items()}).encode("utf-8")))


# Giá trị lấy theo mẫu thật 2/11/2026 (VCB lúc 14:05): mua 54.200, bán 54.300, trần 60.200, sàn 52.400.
VCB_INFO = {"symbol": "VCB", "ceilingPrice": 60200.0, "floorPrice": 52400.0, "refPrice": 56300.0,
            "bidPrice3": 54000.0, "bidVol3": 37300.0, "bidPrice2": 54100.0, "bidVol2": 7800.0,
            "bidPrice1": "54200.0", "bidVol1": 14200.0, "askPrice1": "54300.0", "askVol1": 11300.0,
            "askPrice2": 54400.0, "askVol2": 4000.0, "askPrice3": 54500.0, "askVol3": 9000.0,
            "closePrice": 54300.0, "closeVol": 100.0}
VCB_TRADE = {"symbol": "VCB", "sequenceMsg": 2066781, "matchedPrice": 54300.0, "tradingVolume": 100.0,
             "timestamp": 1793603108, "lastColor": "B"}


def T(h, m, s=0):
    return pd.Timestamp(2026, 11, 2, h, m, s, tz=TZ)


def schema_rec(tmp_path) -> WsBarRecorder:
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path, interval=5)
    payload = sync_payload()
    ack = rec.on_sync(bytes([101]) + payload)
    assert json.loads(ack) == {"type": "sync", "data": hashlib.sha1(payload).hexdigest()}
    return rec


def test_sync_switches_to_schema_decoding_and_saves_schema(tmp_path):
    rec = schema_rec(tmp_path)
    assert rec.stats["decode_mode"] == "schema" and rec.stats["schemas"] == 26
    assert rec.names[1] == "marketData" and rec.names[3] == "stockInfo"
    assert json.loads((tmp_path / "ws_schemas.json").read_text(encoding="utf-8"))["3"]["name"] == "stockInfo"


def test_sync_up_to_date_or_broken_keeps_manual_decoding(tmp_path):
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path)
    assert rec.on_sync(bytes([101, 0])) is None          # "schema đã mới nhất": không có gì để làm
    assert rec.on_sync(bytes([101]) + b"rac") is None     # schema hỏng: chỉ ghi log
    assert rec.decoder is None and rec.stats["decode_mode"] == "thủ công"


def test_stock_info_decoded_by_schema_becomes_a_bar(tmp_path):
    rec = schema_rec(tmp_path)
    rec.on_raw(frame(3, VCB_INFO), T(10, 0, 1))
    assert rec.tick(T(10, 0, 5)) == 1
    row = load_ws_quotes(tmp_path / "m.db").iloc[0]
    assert row["symbol"] == "VCB" and row["bid_px1"] == 54200 and row["ask_px1"] == 54300   # chuỗi "54200.0" -> số
    assert row["bid_qty1"] == 14200 and row["ceil_px"] == 60200 and row["floor_px"] == 52400
    assert row["n_msgs"] == 1


def test_trades_saved_with_exchange_time_and_deduplicated(tmp_path):
    rec = schema_rec(tmp_path)
    rec.on_raw(frame(1, VCB_TRADE), T(14, 5, 9))
    rec.on_raw(frame(1, {**VCB_TRADE, "sequenceMsg": 2066790, "lastColor": "S", "matchedPrice": 54200.0}), T(14, 5, 9))
    rec.tick(T(14, 5, 10))
    rec.on_raw(frame(1, VCB_TRADE), T(14, 5, 12))   # nhận lại sau khi kết nối lại: cùng số thứ tự
    rec.close()
    tr = load_ws_trades(tmp_path / "m.db", "2026-11-02")
    assert len(tr) == 2 and rec.stats["trades"] == 3 and rec.stats["trades_saved"] == 2
    first = tr[tr["seq"] == 2066781].iloc[0]
    assert first["ts"] == T(14, 5, 8)                 # giờ sàn, không phải giờ máy nhận
    assert first["price"] == 54300 and first["volume"] == 100 and first["side"] == "B"
    assert pd.Timestamp(first["recv_ts"]) == T(14, 5, 9)


def test_trade_without_sequence_or_time_is_skipped_not_guessed(tmp_path):
    rec = schema_rec(tmp_path)
    rec.on_raw(frame(1, {**VCB_TRADE, "sequenceMsg": None}), T(14, 5, 9))
    rec.on_raw(frame(1, {**VCB_TRADE, "timestamp": None}), T(14, 5, 9))
    rec.close()
    assert rec.stats["trades_skipped"] == 2 and load_ws_trades(tmp_path / "m.db").empty


def test_other_channels_counted_by_schema_name(tmp_path):
    rec = schema_rec(tmp_path)
    rec.on_raw(frame(26, {"marketCode": "HOSE", "rawMarketCode": "HOSE", "marketStatus": "LO",
                          "rawMarketStatus": "5", "time": "2026-11-02T13:00:00"}), T(13, 0, 1))
    rec.on_raw(bytes([3, 255, 255]), T(13, 0, 1))     # tin hỏng
    assert rec.stats["other_by_type"]["marketSession"] == 1 and rec.stats["decode_errors"] == 1


def test_stream_handles_sync_then_data(tmp_path, monkeypatch):
    import asyncio
    import threading

    import data.ws_recorder as wr

    sent = []
    frames = [bytes([101]) + sync_payload(), frame(3, VCB_INFO), frame(1, VCB_TRADE)]

    class FakeWs:
        async def send(self, m): sent.append(m)
        def __aiter__(self): return self
        async def __anext__(self):
            if not frames:
                raise StopAsyncIteration
            return frames.pop(0)

    class Ctx:
        async def __aenter__(self): return FakeWs()
        async def __aexit__(self, *a): return False

    async def fake_auth(ws, token): sent.append("auth")
    monkeypatch.setattr(wr, "connect_ws", lambda url: Ctx())
    monkeypatch.setattr(wr, "_authenticate", fake_auth)
    rec = WsBarRecorder(tmp_path / "m.db", tmp_path)
    rec.now = lambda: T(10, 0, 1)
    stop = threading.Event()

    class S: ws_url = "wss://x"

    async def go():
        task = asyncio.ensure_future(wr.stream_forever(["VCB"], rec, S(), lambda: "tok", stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, 3)
    asyncio.run(go())
    acks = [m for m in sent[2:] if json.loads(m).get("type") == "sync"]
    assert len(acks) == 1 and json.loads(acks[0])["data"]          # đã xác nhận schema
    assert rec.stats["decode_mode"] == "schema"
    assert rec.stats["stock_info"] == 1 and rec.stats["trades"] == 1
    assert rec.stats["messages"] == 2                                # tin sync không tính là tin dữ liệu


def test_compare_script_detects_missing_trades(tmp_path, capsys):
    import importlib.util
    import sqlite3

    from data.schema import QUOTE_COLUMNS
    from data.storage import save_quotes, save_ws_trades

    spec = importlib.util.spec_from_file_location("cmp", Path(__file__).parents[1] / "scripts" / "compare_ws_rest.py")
    cmp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cmp)
    db = tmp_path / "m.db"
    base = {c: None for c in QUOTE_COLUMNS}
    quotes = [{**base, "ts": T(10, 0), "symbol": s, "bid_px1": 1.0, "ask_px1": 2.0, "total_vol": 1000.0} for s in ("AAA", "BBB")]
    quotes += [{**base, "ts": T(10, 1), "symbol": s, "bid_px1": 1.0, "ask_px1": 2.0, "total_vol": 1600.0} for s in ("AAA", "BBB")]
    save_quotes(pd.DataFrame(quotes), db)
    trades = [{"ts": T(10, 0, 30), "recv_ts": "x", "symbol": "AAA", "seq": i, "price": 1.0, "volume": 200.0, "side": "B"}
              for i in range(3)]                                   # AAA đủ 600
    trades += [{"ts": T(10, 0, 30), "recv_ts": "x", "symbol": "BBB", "seq": 10, "price": 1.0, "volume": 300.0, "side": "S"}]
    save_ws_trades(pd.DataFrame(trades), db)                       # BBB mất một nửa
    con = sqlite3.connect(db)
    q = pd.read_sql_query("SELECT * FROM quotes", con)
    cmp.check_trades(q, con, "2026-11-02")
    out = capsys.readouterr().out
    assert "900 / REST 1,200 = 75.0%" in out
    assert "Mã lệch quá 2%: 1/2: BBB 50.0%" in out


def _trade(day: str, seq: int, symbol: str = "VCB", volume: float = 100.0) -> dict:
    return {"ts": pd.Timestamp(f"{day} 10:00:00", tz=TZ), "recv_ts": "x", "symbol": symbol, "seq": seq,
            "price": 54300.0, "volume": volume, "side": "B"}


def test_same_sequence_on_another_day_is_kept(tmp_path):
    """NEO đánh lại sequenceMsg mỗi ngày: cùng mã, cùng số thứ tự nhưng KHÁC ngày là hai lần khớp khác nhau."""
    from data.storage import save_ws_trades

    db = tmp_path / "m.db"
    assert save_ws_trades(pd.DataFrame([_trade("2026-11-03", 500)]), db) == 1
    assert save_ws_trades(pd.DataFrame([_trade("2026-11-04", 500, volume=700.0)]), db) == 1   # trước đây bị bỏ qua
    assert save_ws_trades(pd.DataFrame([_trade("2026-11-04", 500)]), db) == 0                 # trùng trong ngày vẫn bỏ
    assert len(load_ws_trades(db)) == 2
    day4 = load_ws_trades(db, "2026-11-04")
    assert len(day4) == 1 and day4["volume"].iloc[0] == 700 and day4["day"].iloc[0] == "2026-11-04"


def test_old_ws_trades_table_is_migrated_without_losing_rows(tmp_path):
    """market.db ghi bằng bản cũ (khóa symbol, seq; chưa có cột day): lần mở đầu tiên chuyển sang khóa mới, giữ đủ dòng."""
    import sqlite3

    from data.storage import save_ws_trades

    db = tmp_path / "m.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ws_trades (ts TEXT, recv_ts TEXT, symbol TEXT, seq REAL, price REAL, volume REAL, side TEXT, "
                "PRIMARY KEY (symbol, seq))")
    con.executemany("INSERT INTO ws_trades VALUES (?, 'x', 'VCB', ?, 54300.0, 100.0, 'B')",
                    [("2026-11-03T10:00:00+07:00", 500), ("2026-11-03T10:00:01+07:00", 501)])
    con.commit()
    con.close()
    old = load_ws_trades(db)                                          # mở bằng bản mới: tự chuyển bảng
    assert len(old) == 2 and set(old["day"]) == {"2026-11-03"} and list(old["seq"]) == [500, 501]
    assert save_ws_trades(pd.DataFrame([_trade("2026-11-04", 500)]), db) == 1   # số thứ tự cũ, ngày mới: lưu được
    con = sqlite3.connect(db)
    assert not con.execute("SELECT name FROM sqlite_master WHERE name = 'ws_trades_old'").fetchall()
    con.close()
