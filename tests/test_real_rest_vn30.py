"""Chạy pipeline trên phản hồi THẬT của NEO 4.7 (rổ VN30, lấy lúc 22:20 ngày 27/10/2026, sau giờ giao dịch)."""
import json
from pathlib import Path

import pandas as pd

from data.schema import normalize_quotes
from finance.liquidity import add_liquidity_metrics
from neo_api.stream import map_record

FIXTURE = Path(__file__).parent / "fixtures" / "neo_rest_vn30_20261027.json"


def load():
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = pd.DataFrame([map_record(r) for r in records]).assign(ts=pd.Timestamp("2026-10-27 22:20", tz="Asia/Ho_Chi_Minh"))
    return records, raw


def test_real_basket_has_30_symbols_and_string_best_prices():
    records, _ = load()
    assert len({r["symbol"] for r in records}) == 30
    assert all(isinstance(r["bidPrice1"], str) for r in records)  # tài liệu: giá mua/bán 1 là chuỗi


def test_pipeline_keeps_all_rows_and_spreads_are_sane():
    _, raw = load()
    clean, report = normalize_quotes(raw)
    assert len(clean) == 30 and report.get("dropped_crossed", 0) == 0
    m = add_liquidity_metrics(clean)
    assert (m["spread"] > 0).all()
    assert m["rel_spread_bps"].between(1, 200).all()
    assert (m["imbalance"].abs() <= 1).all()


def test_foreign_net_value_is_computed_when_missing():
    records, raw = load()
    assert not any("foreignNetValue" in r for r in records)
    lpb = raw.set_index("symbol").loc["LPB"]
    assert lpb["foreign_net_val"] == 4104960000 - 28335360000
