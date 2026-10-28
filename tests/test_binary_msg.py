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
