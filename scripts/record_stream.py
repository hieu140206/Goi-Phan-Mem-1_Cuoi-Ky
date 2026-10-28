"""Ghi luồng WebSocket của NEO vào SQLite (chạy mỗi phiên giao dịch).

Chạy:
  python scripts/record_stream.py --dump 5 VCB      # xem 5 thông điệp thô đầu tiên rồi thoát, KHÔNG ghi gì
  python scripts/record_stream.py VCB FPT HPG ...   # ghi dữ liệu (chụp mỗi NEO_SNAPSHOT_SECONDS giây)

Đăng nhập: script hỏi tài khoản và mật khẩu (mật khẩu không hiển thị) hoặc đọc NEO_USERNAME/NEO_PASSWORD trong .env,
lấy token và tự đăng nhập lại khi token bị từ chối. Token chỉ nằm trong bộ nhớ, không ghi ra đĩa.
Script chỉ ĐỌC dữ liệu thị trường, không gửi bất kỳ lệnh giao dịch nào.
Khi dùng --dump, kiểm tra thông điệp rồi che token/thông tin cá nhân trước khi chia sẻ hay đưa vào báo cáo.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.schema import normalize_quotes  # noqa: E402
from data.snapshot import Snapshotter, in_trading_hours  # noqa: E402
from data.storage import save_quotes  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402
from neo_api.stream import AuthError, dump_messages, run_stream  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("recorder")


async def stream_with_relogin(symbols, on_row, settings, tokens: TokenManager) -> None:
    """Chạy luồng; nếu NEO từ chối token thì đăng nhập lại (tối đa một lần mỗi 10 phút)."""
    last_relogin = 0.0
    while True:
        try:
            await run_stream(symbols, on_row, settings, token_provider=tokens.get)
        except AuthError:
            if time.time() - last_relogin < 600:
                raise
            log.warning("Token bị từ chối, đăng nhập lại")
            last_relogin = time.time()
            tokens.invalidate()


async def record(symbols: list[str], settings, tokens: TokenManager) -> None:
    snap = Snapshotter(settings.snapshot_seconds, settings.stale_seconds)

    async def ticker() -> None:
        while True:
            await asyncio.sleep(1)
            now = pd.Timestamp.now(tz=TZ)
            if not snap.due(now):
                continue
            rows = snap.snapshot(now)
            if not rows or not in_trading_hours(now):
                continue
            clean, report = normalize_quotes(pd.DataFrame(rows))
            written = save_quotes(clean, settings.db_path)
            dropped = {k: v for k, v in report.items() if k.startswith("dropped") and v}
            log.info("%s: ghi %d dòng%s", snap.slot(now).strftime("%H:%M:%S"), written, f" (loại: {dropped})" if dropped else "")

    await asyncio.gather(stream_with_relogin(symbols, snap.update, settings, tokens), ticker())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="+", help="Mã cổ phiếu, ví dụ VCB FPT HPG")
    ap.add_argument("--dump", type=int, metavar="N", help="In N thông điệp thô đầu tiên rồi thoát (không ghi dữ liệu)")
    args = ap.parse_args()
    symbols = [s.upper() for s in args.symbols]
    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        tokens.get()  # đăng nhập trước khi chạy, để hỏi mật khẩu ở dòng lệnh thay vì giữa chừng
        if args.dump:
            for i, raw in enumerate(asyncio.run(dump_messages(symbols, args.dump, settings, tokens.get)), 1):
                print(f"--- thông điệp {i} ---\n{raw}")
        else:
            asyncio.run(record(symbols, settings, tokens))
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    except AuthError as exc:
        sys.exit(f"{exc}. Kiểm tra token còn hạn, đúng địa chỉ WebSocket và IP đã đăng ký với NEO.")
    except RuntimeError as exc:
        sys.exit(f"Chưa chạy được: {exc}")
    except KeyboardInterrupt:
        log.info("Đã dừng ghi dữ liệu")


if __name__ == "__main__":
    main()
