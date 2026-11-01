"""Kiểm tra bộ giải mã bằng 4 tin THẬT nhận từ NEO tối 27/10/2026 (marketSession, ngoài giờ giao dịch)."""
import json
from pathlib import Path

import pytest

from neo_api.binary_msg import DecodeError, decode, looks_binary, market_session

FIXTURE = Path(__file__).parent / "fixtures" / "neo_raw_20261027_marketsession.jsonl"


def real_messages():
    return [json.loads(line)["msg"] for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_decode_real_market_session():
    rows = [market_session(decode(m)) for m in real_messages()]
    assert [r["marketCode"] for r in rows] == ["UPCOM", "HNX", "FU", "HOSE"]
    hose = rows[-1]
    # khớp ví dụ trong tài liệu NEO 6.2: HOSE, HOSE, C, K, <ngày>T15:00:00
    assert hose == {"marketCode": "HOSE", "rawMarketCode": "HOSE", "marketStatus": "C",
                    "rawMarketStatus": "K", "time": "2026-10-27T15:00:00"}
    assert rows[2]["marketStatus"] == "PRE"


def test_all_real_messages_are_binary_type_13():
    for m in real_messages():
        assert looks_binary(m)
        assert decode(m).type_name == "marketSession"


def test_bytes_and_str_give_same_result():
    m = real_messages()[0]
    assert decode(m) == decode(m.encode("latin-1"))


def test_json_is_not_binary():
    assert not looks_binary('{"type":"auth","status":"success"}')


def test_null_field_and_errors():
    assert decode(b"\x1a\x00\x02\x02C").fields == [None, "C"]
    with pytest.raises(DecodeError):
        decode(b"\x1a\x04")          # nhánh union lạ
    with pytest.raises(DecodeError):
        decode(b"\x1a\x02\x10AB")    # độ dài vượt quá dữ liệu


# ---- stockInfo nhị phân (tin thật 28/10/2026, trong phiên khớp lệnh) ----
import base64

from neo_api.binary_msg import KNOWN_TYPES, decode_stock_info, is_stock_info

WS = [base64.b64decode(json.loads(x)["raw_b64"])
      for x in (Path(__file__).parent / "fixtures" / "neo_ws_20261028_sample.jsonl").read_text(encoding="utf-8").splitlines()
      if x.strip()]


def test_all_real_stock_info_messages_decode():
    stock = [m for m in WS if is_stock_info(m)]
    assert len(stock) == 40
    rows = [decode_stock_info(m) for m in stock]
    for r in rows:
        assert r["symbol"] in {"FPT", "HPG", "VCB"}
        assert r["floorPrice"] < float(r["bidPrice1"]) < float(r["askPrice1"]) < r["ceilingPrice"]
        assert r["bidPrice3"] < r["bidPrice2"] < float(r["bidPrice1"])
        assert float(r["askPrice1"]) < r["askPrice2"] < r["askPrice3"]
        assert r["totalTradingVolume"] >= 0 and r["foreignRemain"] <= r["foreignRoom"]


def test_known_fpt_values():
    fpt = decode_stock_info(next(m for m in WS if is_stock_info(m)))
    assert fpt["symbol"] == "FPT"
    assert (fpt["ceilingPrice"], fpt["floorPrice"], fpt["refPrice"]) == (59200, 51600, 55400)
    assert fpt["bidPrice1"] == "55900.0" and fpt["askPrice1"] == "56000.0"
    assert abs(fpt["foreignNetValue"] - (fpt["foreignBuyValue"] - fpt["foreignSellValue"])) < 1


def test_other_types_are_recognised():
    names = {decode(m).type_name if not is_stock_info(m) else "stockInfo" for m in WS if m[0] in (0x1a,)}
    assert names == {"marketSession"}
    assert {KNOWN_TYPES[t] for t in (-2, 1, 5, 13)} == {"stockInfo", "marketInfo", "marketVolume", "marketSession"}


def test_parse_message_turns_real_binary_into_clean_quotes():
    import pandas as pd

    from data.schema import normalize_quotes
    from neo_api.stream import parse_message

    rows = [r for m in WS for r in parse_message(m)]
    assert len(rows) == 40  # chỉ stockInfo thành dòng sổ lệnh; marketSession/Info/Volume bị bỏ qua
    clean, _ = normalize_quotes(pd.DataFrame(rows).assign(ts=pd.Timestamp("2026-10-28 09:19", tz="Asia/Ho_Chi_Minh")))
    assert len(clean) > 0 and (clean["ask_px1"] > clean["bid_px1"]).all()
