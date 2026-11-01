import base64
import io
import json
import zlib

import fastavro

from neo_api.avro_sync import (AvroDecoder, CHANNEL_BY_ID, build_sync_message, is_sync_frame, parse_schema_payload,
                               schema_hash)

MD = {"type": "record", "name": "MarketData", "fields": [
    {"name": "symbol", "type": ["null", "string"]}, {"name": "sequenceMsg", "type": ["null", "long"]},
    {"name": "matchedPrice", "type": ["null", "double"]}, {"name": "tradingVolume", "type": ["null", "double"]},
    {"name": "timestamp", "type": ["null", "long"]}, {"name": "lastColor", "type": ["null", "string"]}]}


def _payload(schemas):
    return base64.b64encode(zlib.compress(json.dumps({str(k): v for k, v in schemas.items()}).encode()))


def test_sync_message_and_hash():
    assert json.loads(build_sync_message("")) == {"type": "sync", "data": ""}
    assert len(schema_hash(b"abc")) == 40


def test_sync_frame_detection_and_already_synced():
    assert is_sync_frame(bytes([101]) + b"\x00") and not is_sync_frame(bytes([3, 1]))
    assert not is_sync_frame("chữ")
    assert parse_schema_payload(b"\x00") == {}


def test_decode_market_data_roundtrip():
    schemas = parse_schema_payload(_payload({1: MD}))
    assert list(schemas) == [1]
    rec = {"symbol": "VCB", "sequenceMsg": 42, "matchedPrice": 61900.0, "tradingVolume": 300.0,
           "timestamp": 1761790800123, "lastColor": "green"}
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, fastavro.parse_schema(MD), rec)
    sid, channel, out = AvroDecoder(schemas).decode(bytes([1]) + buf.getvalue())
    assert (sid, channel) == (1, "marketData") and out == rec


def test_unknown_schema_id_raises():
    import pytest
    with pytest.raises(KeyError):
        AvroDecoder({1: MD}).decode(bytes([99]) + b"\x00")


def test_channel_ids_match_observed_first_bytes():
    # byte đầu thật trong dữ liệu dự án: stockInfo 3, marketInfo 2, marketVolume 10, marketSession 26
    assert CHANNEL_BY_ID[3] == "stockInfo" and CHANNEL_BY_ID[2] == "marketInfo"
    assert CHANNEL_BY_ID[10] == "marketVolume" and CHANNEL_BY_ID[26] == "marketSession"
