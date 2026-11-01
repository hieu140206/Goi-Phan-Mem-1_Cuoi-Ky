"""Điền lại giá trần/sàn/KL khớp từ phản hồi gốc: đúng nguyên văn, chỉ điền ô trống, chạy lại không đổi gì."""
import gzip
import json
from pathlib import Path

import pandas as pd

from data.backfill import backfill_extra
from data.schema import normalize_quotes
from data.storage import load_quotes, save_quotes
from neo_api.stream import map_record

REST = json.loads((Path(__file__).parent / "fixtures" / "neo_rest_vn30_20261027.json").read_text(encoding="utf-8"))
TS = pd.Timestamp("2026-10-27 10:00:00", tz="Asia/Ho_Chi_Minh")


def _old_style_db(tmp_path):
    """Dữ liệu như bộ ghi cũ lưu: có sổ lệnh nhưng chưa có trần/sàn/KL khớp."""
    raw = pd.DataFrame([map_record(r) for r in REST]).assign(ts=TS)
    raw[["ceil_px", "floor_px", "last_vol"]] = None
    clean, _ = normalize_quotes(raw)
    db = tmp_path / "m.db"
    save_quotes(clean, db)
    day = tmp_path / "raw" / "2026-10-27"
    day.mkdir(parents=True)
    with gzip.open(day / "stocks.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": TS.isoformat(), "status": "LO", "records": REST}) + "\n")
    return db, tmp_path / "raw"


def test_backfill_restores_exact_values(tmp_path):
    db, raw = _old_style_db(tmp_path)
    assert load_quotes(db)["ceil_px"].isna().all()
    res = backfill_extra(db, raw)
    assert res["snapshots"] == 1 and res["updated"] == 90  # 30 mã x 3 cột
    back = load_quotes(db).set_index("symbol")
    for r in REST:
        assert back.loc[r["symbol"], "ceil_px"] == r["ceilingPrice"]
        assert back.loc[r["symbol"], "floor_px"] == r["floorPrice"]
        assert back.loc[r["symbol"], "last_vol"] == r["closeVol"]


def test_backfill_is_idempotent_and_never_overwrites(tmp_path):
    db, raw = _old_style_db(tmp_path)
    backfill_extra(db, raw)
    assert backfill_extra(db, raw)["updated"] == 0  # lần hai không còn ô trống
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE quotes SET ceil_px = 1 WHERE symbol = 'ACB'")
    backfill_extra(db, raw)
    assert load_quotes(db).set_index("symbol").loc["ACB", "ceil_px"] == 1  # số đã có không bị ghi đè


def test_backfill_without_db_or_raw(tmp_path):
    assert backfill_extra(tmp_path / "none.db", tmp_path / "raw") == {"snapshots": 0, "updated": 0}
