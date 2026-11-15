"""Thử TỪNG chủ đề luồng trực tiếp của SSI v3 (chỉ ĐỌC): chủ đề nào đăng ký được, nhận tin gì, có những trường nào.

Chạy: python scripts/probe_ssi_channels.py [giây_mỗi_chủ_đề]      (mặc định 15)
Trong giờ giao dịch mới có tin trade/quote/room; ngoài giờ chỉ biết được chủ đề nào bị từ chối.
Không in khóa hay token. Không ghi vào market.db. Không dùng Private Key.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_ssi as P  # noqa: E402  (dùng lại đăng nhập và che khóa)
from dotenv import load_dotenv  # noqa: E402
import websockets  # noqa: E402

TOPICS = ["market.hose", "indexsummary.VN30", "indexsummary.VNINDEX", "trade.index.VN30", "trade.VCB",
          "trade.vn30", "quote.VCB", "room.VCB", "room.vn30", "put.VCB", "oddlot.VCB"]


async def one(token: str, topic: str, seconds: float) -> None:
    print(f"\n=== {topic}")
    try:
        async with websockets.connect(P.STREAM, ping_interval=20, open_timeout=10,
                                      additional_headers={"Authorization": f"Bearer {token}"}) as ws:
            await ws.send(json.dumps({"method": "SUBSCRIBE", "channel": "DATA", "topics": [topic]}))
            end, n, keys = time.time() + seconds, 0, set()
            while time.time() < end:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=max(end - time.time(), 0.1))
                except asyncio.TimeoutError:
                    break
                text = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
                try:
                    d = json.loads(text)
                except ValueError:
                    d = {}
                if isinstance(d, dict) and d.get("method") == "PING":
                    await ws.send(json.dumps({"method": "PONG", "channel": "HEARTBEAT", "time": d.get("time")}))
                    continue
                n += 1
                if isinstance(d, dict) and isinstance(d.get("data"), dict):
                    keys |= set(d["data"])
                if n <= 3:
                    print("  tin:", P.clean(text)[:500])
            print(f"  nhận {n} tin; các trường trong data: {sorted(keys) or '(không có)'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Lỗi: {type(exc).__name__}: {P.clean(exc)[:200]}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    token = P.login()["accessToken"]
    for t in TOPICS:
        asyncio.run(one(token, t, seconds))
    print("\nXong.")


if __name__ == "__main__":
    main()
