"""Nạp số SSI của MỘT ngày để trang Tổng quan hiện được ngày NEO không ghi: 4 chỉ số (tổng kết ngày và nến 1 phút) và tổng kết ngày của 30 mã VN30.

Chạy SAU 15:05 của ngày đó (hoặc ngày sau), vài phút:
  python scripts/fetch_ssi_overview.py --day 2026-11-26

Ghi vào bảng ssi_index_daily, ssi_daily (market.db, không đụng bảng NEO) và nến khung 1m trong candles.db. Trước khi ghi, sao lưu market.db vào sao-luu/.
Chỉ ĐỌC từ SSI. Cần SSI_API_KEY và SSI_API_SECRET trong .env. Sổ lệnh SSI của ngày đó phải đã được bộ ghi scripts/record_ssi.py lưu.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.candle_store import DEFAULT_PATH as CANDLE_DB, save_candles  # noqa: E402
from data.merge import backup_db  # noqa: E402
from data.ssi import (SsiClient, SsiError, fetch_index_day, fetch_ohlc, fetch_summary, save_ssi_daily,  # noqa: E402
                      save_ssi_index)
from data.ssi_overview import INDEX_FRAME, SSI_OHLC_CODES, SSI_SUMMARY_CODES  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

VN = ZoneInfo("Asia/Ho_Chi_Minh")
READY_AT = dt.time(15, 5)   # trước giờ này số tổng kết của ngày hôm nay chưa chốt


def read_symbols(path: Path) -> list[str]:
    return [ln.strip().upper() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def collect(client, day: str, symbols: list[str]) -> dict:
    """Lấy mọi thứ trước (chưa ghi gì). Trả {"index": bảng, "daily": bảng, "candles": {mã: bảng}}."""
    slash = day.replace("-", "/")
    index = []
    for code, ssi_code in SSI_SUMMARY_CODES.items():
        df = fetch_index_day(client, ssi_code, day)
        index.append(df.assign(index_code=code))
        print(f"  chỉ số {code}: {len(df)} dòng")
    candles = {}
    for code, ssi_code in SSI_OHLC_CODES.items():
        candles[code] = fetch_ohlc(client, ssi_code, slash, slash, INDEX_FRAME, max_pages=3)
        print(f"  nến 1 phút {code}: {len(candles[code])}")
    daily = []
    for i, sym in enumerate(symbols, 1):
        daily.append(fetch_summary(client, sym, slash, slash))
        print(f"  [{i}/{len(symbols)}] {sym}: {len(daily[-1])} dòng")
    return {"index": pd.concat(index, ignore_index=True), "daily": pd.concat(daily, ignore_index=True), "candles": candles}


def store(data: dict, day: str, db: Path, candle_db: Path) -> dict[str, int]:
    """Ghi vào market.db và candles.db. Chỉ giữ dòng đúng ngày đã hỏi."""
    daily = data["daily"][data["daily"]["day"] == day]
    stamp = pd.Timestamp.now(tz=VN).isoformat(timespec="seconds")
    n = {"ssi_index_daily": save_ssi_index(data["index"], db), "ssi_daily": save_ssi_daily(daily, db), "candles": 0}
    for code, df in data["candles"].items():
        n["candles"] += save_candles(candle_db, INDEX_FRAME, code, df[df["ts"].dt.strftime("%Y-%m-%d") == day], stamp)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", required=True, help="Ngày YYYY-MM-DD")
    ap.add_argument("--db", type=Path, default=None, help="market.db (mặc định theo cấu hình dự án)")
    ap.add_argument("--candles", type=Path, default=CANDLE_DB)
    ap.add_argument("--symbols", type=Path, default=ROOT / "data" / "symbols_VN30.txt")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    day = dt.date.fromisoformat(args.day)
    now = dt.datetime.now(VN)
    if day > now.date() or (day == now.date() and now.time() < READY_AT):
        sys.exit(f"Ngày {day} chưa chốt số. Chạy sau {READY_AT:%H:%M} của ngày đó.")
    db = args.db or Path(get_settings().db_path)
    db = db if db.is_absolute() else ROOT / db
    if not db.exists():
        sys.exit(f"Không thấy {db}.")
    try:
        data = collect(SsiClient(), args.day, read_symbols(args.symbols))
    except SsiError as exc:
        sys.exit(f"Lỗi SSI: {exc}")
    if data["index"].empty:
        sys.exit(f"SSI không có tổng kết chỉ số ngày {args.day} (ngày nghỉ?). Không ghi gì.")
    saved = backup_db(db, ROOT / "sao-luu", f"{now:%Y%m%d_%H%M%S}")
    print(f"Đã sao lưu: {saved}")
    print("Đã ghi: " + ", ".join(f"{k} {v}" for k, v in store(data, args.day, db, args.candles).items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
