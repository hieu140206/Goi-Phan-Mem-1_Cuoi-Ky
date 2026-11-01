"""Kiểm tra nhanh sau phiên: bảng giá các sàn, độ sâu theo sàn và phái sinh đã ghi được gì trong market.db (không gọi NEO).

  python scripts/check_boards.py            # ngày mới nhất có dữ liệu
  python scripts/check_boards.py 2026-10-30
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.storage import board_days, load_board, load_depth_market, load_futures  # noqa: E402
from neo_api.config import get_settings  # noqa: E402


def main() -> None:
    db = get_settings().db_path
    days = board_days(db)
    if not days:
        sys.exit("Chưa có bảng giá các sàn trong market.db (bộ ghi bản cũ, hoặc chưa chạy phiên nào với bản mới).")
    day = sys.argv[1] if len(sys.argv) > 1 else days[-1]
    print(f"Ngày {day}. Ngày có bảng giá: {', '.join(days)}")
    for grp in ("HOSE", "HNX", "UPCOM", "ETF", "CW"):
        b = load_board(db, day, grp)
        if b.empty:
            print(f"  {grp:6s} không có dữ liệu")
            continue
        no_price = int(b["last_px"].isna().sum())
        print(f"  {grp:6s} {len(b):4d} mã | lần chụp cuối {b['ts'].max():%H:%M:%S} | chưa có giá khớp: {no_price}"
              f" | ví dụ giá TC của {b['symbol'].iloc[0]}: {b['ref_px'].iloc[0]}")
    d = load_depth_market(db)
    d = d[d["ts"].dt.strftime("%Y-%m-%d") == day]
    print("Độ sâu theo sàn (số lần chụp):", d.groupby("grp").size().to_dict())
    f = load_futures(db)
    f = f[f["ts"].dt.strftime("%Y-%m-%d") == day]
    print(f"Phái sinh: {len(f)} dòng, hợp đồng: {sorted(f['name'].unique()) if not f.empty else []}")


if __name__ == "__main__":
    main()
