"""Bộ ghi sổ lệnh SSI (data/ssi_recorder.py): đọc tin, chụp thanh 5 giây, ghi SQLite và tin thô. Không gọi mạng."""
import gzip
import json

import pandas as pd

from data.ssi_recorder import SsiBarRecorder, parse_levels
from data.storage import load_ssi_quotes, save_ssi_quotes
from neo_api.config import TZ


def T(h, m, s=0, ms=0):
    return pd.Timestamp(2026, 11, 24, h, m, s, ms * 1000, tz=TZ)   # thứ Ba, trong tuần giao dịch


def quote(sym="VCB", px="54100", t="2026/11/24 10:00:02"):
    return json.dumps({"channel": "DATA", "topic": f"quote.{sym}", "data": {
        "s": sym, "t": t,
        "bids": [[px, "75400"], ["54000", "16400"], ["53900", "12000"], ["0", "0"]],
        "asks": [["54200", "1000"], ["54300", "2000"], ["54400", "3000"], ["0", "0"]]}})


def test_parse_levels_empty_level_is_nan_not_zero():
    out = parse_levels([["54100", "75400"], ["0", "0"]])
    assert out[0] == (54100.0, 75400.0)
    assert pd.isna(out[1][0]) and pd.isna(out[1][1])      # mức ["0","0"] là mức trống, không đoán
    assert pd.isna(out[2][0])                              # thiếu hẳn mức 3 cũng là trống
    assert parse_levels(None)[0][0] != parse_levels(None)[0][0]   # NaN


def test_parse_levels_keeps_ato_atc_text():
    assert parse_levels([["ATO", "100"]])[0] == ("ATO", 100.0)


def test_ping_gets_pong_and_bad_json_is_counted(tmp_path):
    rec = SsiBarRecorder(tmp_path / "m.db", tmp_path)
    reply = rec.on_raw(json.dumps({"method": "PING", "time": 123}), T(10, 0, 1))
    assert json.loads(reply)["method"] == "PONG" and json.loads(reply)["time"] == 123
    assert rec.on_raw("khong phai json", T(10, 0, 1)) is None
    assert rec.stats["parse_errors"] == 1


def test_tick_writes_bar_with_prices_and_age(tmp_path):
    db = tmp_path / "m.db"
    rec = SsiBarRecorder(db, tmp_path, interval=5)
    rec.on_raw(quote(), T(10, 0, 3))
    assert rec.tick(T(10, 0, 5)) == 1
    df = load_ssi_quotes(db)
    row = df.iloc[0]
    assert row["symbol"] == "VCB" and row["ts"] == T(10, 0, 5)
    assert (row["bid_px1"], row["bid_qty1"], row["ask_px1"]) == (54100.0, 75400.0, 54200.0)
    assert pd.isna(row["bid_px4"]) if "bid_px4" in df.columns else True   # HOSE chỉ 3 mức
    assert row["n_msgs"] == 1 and row["age_ms"] == 2000.0
    assert row["src_ts"].startswith("2026-11-24T10:00:02")


def test_message_after_slot_belongs_to_next_bar(tmp_path):
    """Tin nhận sau mốc 10:00:05 không được lọt vào thanh 10:00:05 (giống bộ ghi WebSocket của NEO)."""
    db = tmp_path / "m.db"
    rec = SsiBarRecorder(db, tmp_path, interval=5)
    rec.on_raw(quote(px="54100"), T(10, 0, 3))
    rec.on_raw(quote(px="54500"), T(10, 0, 6))      # sau mốc 10:00:05, tick chưa kịp chạy
    rec.tick(T(10, 0, 6))
    row = load_ssi_quotes(db).iloc[0]
    assert row["ts"] == T(10, 0, 5) and row["bid_px1"] == 54100.0


def test_no_bar_during_lunch_but_raw_is_kept(tmp_path):
    db = tmp_path / "m.db"
    rec = SsiBarRecorder(db, tmp_path, interval=5)
    rec.on_raw(quote(), T(12, 0, 1))
    assert rec.tick(T(12, 0, 5)) == 0
    assert load_ssi_quotes(db).empty
    rec.close()
    raw = tmp_path / "raw" / "2026-11-24" / "ssi.jsonl.gz"
    with gzip.open(raw, "rt", encoding="utf-8") as fh:
        assert len(fh.readlines()) == 1             # tin thô vẫn lưu đủ


def test_stale_symbol_is_not_carried_forward(tmp_path):
    db = tmp_path / "m.db"
    rec = SsiBarRecorder(db, tmp_path, interval=5)
    rec.on_raw(quote(), T(10, 0, 1))
    rec.tick(T(10, 0, 5))
    assert rec.tick(T(10, 20, 5)) == 0              # quá 15 phút không có tin: không ghi tiếp trạng thái cũ


def test_duplicate_bar_is_ignored(tmp_path):
    db = tmp_path / "m.db"
    rec = SsiBarRecorder(db, tmp_path, interval=5)
    rec.on_raw(quote(), T(10, 0, 3))
    rec.tick(T(10, 0, 5))
    df = load_ssi_quotes(db)
    assert save_ssi_quotes(df, db) == 0             # cùng (ts, symbol): bỏ qua, không ghi đè
    assert len(load_ssi_quotes(db)) == 1
