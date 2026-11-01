"""Điền giá trần, giá sàn và KL khớp gần nhất cho các phiên đã ghi trước khi bộ ghi lưu các cột này.

Chạy một lần (kích hoạt .venv trước):  python scripts/backfill_extra.py
Số liệu lấy NGUYÊN VĂN từ data/raw/<ngày>/stocks.jsonl.gz (phản hồi gốc của NEO), không ước lượng.
Chỉ điền ô đang trống; chạy lại nhiều lần không sao. Không gọi NEO, không cần đăng nhập.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.backfill import backfill_extra  # noqa: E402
from neo_api.config import get_settings  # noqa: E402


def main() -> None:
    db = get_settings().db_path
    if not db.exists():
        sys.exit(f"Chưa có {db}. Hãy ghi dữ liệu trước (python scripts/run_live.py).")
    res = backfill_extra(db, ROOT / "data" / "raw")
    print(f"Đã đọc {res['snapshots']} lần chụp gốc, điền {res['updated']} ô trống trong {db.name}.")


if __name__ == "__main__":
    main()
