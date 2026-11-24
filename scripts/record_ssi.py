"""Ghi sổ lệnh SSI MỘT MÌNH, ở cửa sổ riêng (không cần tắt hay chạy lại bộ ghi NEO):  python scripts/record_ssi.py

Chạy trong thư mục gốc dự án, đã kích hoạt .venv, bất cứ lúc nào trong giờ giao dịch (tốt nhất trước 9:15). Tự dừng lúc 15:02;
bấm Ctrl+C để dừng sớm. Ghi vào bảng ssi_quotes của data/market.db (thanh 5 giây), tin thô vào data/raw/<ngày>/ssi.jsonl.gz
và thống kê vào ssi_stats.json. Cần SSI_API_KEY và SSI_API_SECRET trong .env. Chỉ ĐỌC dữ liệu, không dùng Private Key.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.ssi import SsiClient, SsiError  # noqa: E402
from data.ssi_recorder import SsiBarRecorder, ssi_main  # noqa: E402
from neo_api.config import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="VN30", help="Chỉ số lấy rổ mã (mặc định VN30)")
    ap.add_argument("--interval", type=int, default=5, help="Giây mỗi thanh (mặc định 5)")
    ap.add_argument("--db", type=Path, help="Tệp SQLite (mặc định như bộ ghi NEO: NEO_DB_PATH)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    client = SsiClient()
    try:
        client.token()                      # đăng nhập ngay để lỗi khóa hiện sớm
    except SsiError as exc:
        sys.exit(f"Đăng nhập SSI thất bại: {exc}")
    settings = get_settings()
    db = args.db or (settings.db_path if Path(settings.db_path).is_absolute() else ROOT / settings.db_path)
    rec = SsiBarRecorder(db, ROOT / "data", args.interval)
    print(f"Đang ghi sổ lệnh SSI (quote.{args.index}@*, thanh {args.interval} giây) vào {db}. Ctrl+C để dừng.")
    try:
        asyncio.run(ssi_main(rec, client, [f"quote.{args.index}@*"], threading.Event()))
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    print(f"Tổng cộng {rec.stats['quotes']} tin sổ lệnh, {len(rec.stats['per_symbol'])} mã, nối lại {rec.reconnects} lần.")


if __name__ == "__main__":
    main()
