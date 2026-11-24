"""Ghi sẵn ngày đáo hạn phái sinh (thứ Năm thứ ba của tháng, tính bằng code) vào data/special_days.csv:
    python scripts/make_special_days.py [--start 2026-10-01] [--end 2026-12-31]

Chỉ THÊM dòng còn thiếu, không xóa hay sửa dòng nào đang có. Các loại ngày khác (etf_rebalance, index_review, ex_rights, earnings, other)
để trống cho bạn tự điền: mở tệp, thêm dòng dạng  2026-12-21,index_review,ghi chú.
Chưa xét ngày nghỉ lễ: nếu thứ Năm thứ ba trùng ngày nghỉ thì ngày đáo hạn thật có thể dời, hãy kiểm tra.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.special_days import add_expiry_dates, special_days_path  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2026-10-01", help="Ngày bắt đầu, YYYY-MM-DD (mặc định 2026-10-01)")
    ap.add_argument("--end", default="2026-12-31", help="Ngày kết thúc, YYYY-MM-DD (mặc định 2026-12-31)")
    args = ap.parse_args()
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    path = special_days_path()
    n = add_expiry_dates(path, start, end)
    print(f"Đã thêm {n} ngày đáo hạn phái sinh vào {path}" if n else f"{path} đã đủ ngày đáo hạn trong khoảng này, không thêm gì.")


if __name__ == "__main__":
    main()
