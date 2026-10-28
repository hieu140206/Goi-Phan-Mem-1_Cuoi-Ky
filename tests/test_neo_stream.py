import json

import pandas as pd
import pytest

from data.schema import QUOTE_COLUMNS, normalize_quotes
from data.snapshot import Snapshotter, in_trading_hours
from neo_api.stream import (
    FIELD_MAP, build_auth_message, build_subscribe_message, extract_records, map_record, parse_message,
)

TZ = "Asia/Ho_Chi_Minh"

# Thông điệp mẫu lấy từ tài liệu NEO (giá mức 1 là chuỗi, totalBidQTTY là null).
SAMPLE = {
    "symbol": "HPG", "ceilingPrice": 31900, "floorPrice": 27800, "refPrice": 29850,
    "bidPrice1": "29750.0", "bidVol1": 293000, "bidPrice2": 29700, "bidVol2": 208800, "bidPrice3": 29650, "bidVol3": 25900,
    "askPrice1": "29800.0", "askVol1": 4000, "askPrice2": 29850, "askVol2": 342000, "askPrice3": 29900, "askVol3": 218800,
    "closePrice": 29800, "closeVol": 200, "openPrice": 30000, "highPrice": 30100, "lowPrice": 29800,
    "totalTradingVolume": 5736600, "totalTradingValue": 171836675000, "totalBidQTTY": None, "totalAskQTTY": None,
    "foreignBuyVolume": 58900, "foreignSellVolume": 679962, "foreignBuyValue": 1755220000,
    "foreignSellValue": 20262867600, "foreignNetValue": -18507647600, "foreignRemain": 2239929932,
    "foreignRoom": 3760978268, "breakEvenPoint": 0,
}


def test_auth_and_subscribe_messages_match_docs():
    assert json.loads(build_auth_message("tok")) == {"action": "auth", "data": "tok"}
    assert json.loads(build_subscribe_message(["VPB", "HPG"])) == {
        "type": "sub", "channel": "stockInfo", "listId": ["VPB", "HPG"]}


def test_field_map_targets_are_schema_columns():
    assert set(FIELD_MAP.values()) <= set(QUOTE_COLUMNS)


@pytest.mark.parametrize("wrapped", [SAMPLE, {"type": "stockInfo", "data": SAMPLE}, [SAMPLE], {"data": [SAMPLE]}])
def test_extract_records_accepts_common_envelopes(wrapped):
    recs = extract_records(wrapped)
    assert len(recs) == 1 and recs[0]["symbol"] == "HPG"


def test_non_data_messages_are_ignored():
    assert extract_records({"type": "auth", "status": "success", "data": {"username": "x"}}) == []
    assert extract_records({"type": "heartbeat"}) == []
    assert parse_message("không phải json") == []


def test_map_record_and_cleaning_of_string_prices():
    row = map_record(SAMPLE)
    assert row["bid_px1"] == "29750.0" and row["bid_qty1"] == 293000 and row["total_vol"] == 5736600
    assert row["foreign_net_val"] == -18507647600 and row["ref_px"] == 29850
    df = pd.DataFrame([{**row, "ts": "2026-10-22 10:00:00"}])
    clean, rep = normalize_quotes(df)
    assert len(clean) == 1
    assert clean.loc[0, "bid_px1"] == 29750.0 and clean.loc[0, "ask_px1"] == 29800.0


def test_auction_prices_are_dropped_and_counted():
    base = {**map_record(SAMPLE), "ts": "2026-10-22 09:05:00"}
    rows = [
        {**base, "bid_px1": "ATO"},
        {**base, "ts": "2026-10-22 09:06:00", "ask_px1": "atc"},
        {**base, "ts": "2026-10-22 10:00:00"},
    ]
    clean, rep = normalize_quotes(pd.DataFrame(rows))
    assert rep["dropped_auction"] == 2 and len(clean) == 1


def test_snapshotter_slots_and_staleness():
    snap = Snapshotter(interval=60, stale=900)
    t0 = pd.Timestamp("2026-10-22 10:00:20", tz=TZ)
    snap.update(map_record(SAMPLE), t0)
    snap.update({**map_record({**SAMPLE, "symbol": "VCB"})}, t0 - pd.Timedelta(minutes=30))  # tin đã cũ
    assert snap.due(t0)
    rows = snap.snapshot(t0 + pd.Timedelta(seconds=15))
    assert [r["symbol"] for r in rows] == ["HPG"]            # VCB quá cũ nên bị bỏ
    assert rows[0]["ts"] == pd.Timestamp("2026-10-22 10:00:00", tz=TZ)  # làm tròn xuống mốc 60 giây
    assert not snap.due(t0 + pd.Timedelta(seconds=30))       # 10:00:50, cùng mốc, không chụp lại
    assert snap.due(t0 + pd.Timedelta(seconds=45))           # sang mốc 10:01


def test_snapshot_forward_fills_unchanged_book():
    snap = Snapshotter(interval=60, stale=900)
    t0 = pd.Timestamp("2026-10-22 10:00:05", tz=TZ)
    snap.update(map_record(SAMPLE), t0)
    first = snap.snapshot(t0)
    second = snap.snapshot(t0 + pd.Timedelta(seconds=70))
    assert len(first) == len(second) == 1
    assert second[0]["ts"] - first[0]["ts"] == pd.Timedelta(minutes=1)


def test_trading_hours_window():
    assert in_trading_hours(pd.Timestamp("2026-10-23 10:00", tz=TZ))      # thứ Sáu
    assert not in_trading_hours(pd.Timestamp("2026-10-23 15:00", tz=TZ))
    assert not in_trading_hours(pd.Timestamp("2026-10-24 10:00", tz=TZ))  # thứ Bảy
