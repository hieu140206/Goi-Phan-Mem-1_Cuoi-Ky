"""Bộ ghi WebSocket ĐỘC LẬP (thử nghiệm): chỉ ghi sổ lệnh VN30 qua WebSocket, không mở dashboard, không ghi REST.

  python scripts/record_ws.py            # ghi đến 15:02 rồi tự dừng
  python scripts/record_ws.py --interval 2

Nên chạy cùng lúc với bộ ghi REST (python scripts/record_rest.py hoặc run_live.py) để đối chiếu bằng
python scripts/compare_ws_rest.py. Mỗi cửa sổ chỉ cần MỘT đăng nhập; nếu đã dùng run_live.py --ws thì không cần file này.
Dữ liệu vào bảng ws_quotes (KHÔNG đụng bảng quotes của REST). Chỉ ĐỌC, không đặt lệnh.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.rest_recorder import RestRecorder  # noqa: E402
from data.ws_recorder import WsBarRecorder, ws_main  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoClient  # noqa: E402
from neo_api.config import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="VN30")
    ap.add_argument("--interval", type=int, default=5, help="Giây mỗi thanh (mặc định 5)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        tokens.get()
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    db_path = settings.db_path if Path(settings.db_path).is_absolute() else ROOT / settings.db_path
    loader = RestRecorder(NeoClient(settings, tokens), db_path=db_path, data_dir=ROOT / "data", index_code=args.index,
                          symbols_file=ROOT / "data" / f"symbols_{args.index}.txt", record_boards=False)
    symbols = loader.load_symbols()
    print(f"Ghi WebSocket {len(symbols)} mã, thanh {args.interval} giây. Ctrl+C để dừng.")
    rec = WsBarRecorder(db_path, ROOT / "data", args.interval)
    try:
        asyncio.run(ws_main(symbols, rec, settings, tokens.get))
    except KeyboardInterrupt:
        rec.close()
    print("Đã dừng. Thống kê: data/raw/<ngày>/ws_stats.json")


if __name__ == "__main__":
    main()
