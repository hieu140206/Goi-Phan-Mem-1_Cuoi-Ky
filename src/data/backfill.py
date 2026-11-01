"""Điền lại các cột mới (giá trần, giá sàn, KL khớp gần nhất) cho dữ liệu đã ghi từ phản hồi GỐC của NEO.

Bộ ghi luôn lưu phản hồi gốc mỗi phút ở data/raw/<ngày>/stocks.jsonl.gz, nên số liệu được lấy lại đúng nguyên văn,
không ước lượng. Chỉ điền ô đang trống, không ghi đè số đã có, chạy lại nhiều lần không sao.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

from .schema import QUOTE_COLUMNS  # noqa: F401  (bảo đảm import schema trước khi mở DB)
from .storage import _connect

BACKFILL_FIELDS = {"ceilingPrice": "ceil_px", "floorPrice": "floor_px", "closeVol": "last_vol"}


def backfill_extra(db_path: Path, raw_root: Path) -> dict[str, int]:
    """Trả về {'snapshots': số lần chụp đã đọc, 'updated': số ô được điền}."""
    done = {"snapshots": 0, "updated": 0}
    if not Path(db_path).exists():
        return done
    with _connect(Path(db_path)) as conn:
        for gz in sorted(Path(raw_root).glob("*/stocks.jsonl.gz")):
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        snap = json.loads(line)
                    except ValueError:
                        continue
                    done["snapshots"] += 1
                    for rec in snap.get("records", []):
                        for src, col in BACKFILL_FIELDS.items():
                            val = rec.get(src)
                            if isinstance(val, (int, float)):
                                cur = conn.execute(
                                    f"UPDATE quotes SET {col} = ? WHERE ts = ? AND symbol = ? AND {col} IS NULL",
                                    (float(val), snap.get("ts"), str(rec.get("symbol", "")).upper()),
                                )
                                done["updated"] += cur.rowcount
    return done
