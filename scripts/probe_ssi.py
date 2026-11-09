"""Thử kết nối SSI (chỉ ĐỌC, không đặt lệnh): đăng nhập, rồi nhận sổ lệnh một mã vài giây.

Chạy (kích hoạt .venv trước):  python scripts/probe_ssi.py [MÃ] [GIÂY]      ví dụ: python scripts/probe_ssi.py VCB 20
Cần SSI_API_KEY và SSI_API_SECRET trong .env. KHÔNG dùng Private Key. Script không in khóa hay token.
Mục đích: trả lời các điều tài liệu SSI v3 chưa nói rõ (token sống bao lâu, luồng trực tiếp xác thực thế nào,
HOSE có mấy mức giá, tin gửi đủ hay chỉ gửi phần đổi). Kết quả chỉ để đọc, không ghi vào market.db.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import requests  # noqa: E402
import websockets  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

API = "https://api.ssi.com.vn"
STREAM = "wss://stream.ssi.com.vn/ws/v3"
SECRETS: list[str] = []


def clean(text: object) -> str:
    """Che mọi khóa/token nếu lỡ nằm trong thông báo lỗi."""
    s = str(text)
    for secret in SECRETS:
        if secret:
            s = s.replace(secret, "***")
    return s


def login() -> dict:
    key, secret = os.getenv("SSI_API_KEY", ""), os.getenv("SSI_API_SECRET", "")
    if not key or not secret:
        sys.exit("Thiếu SSI_API_KEY hoặc SSI_API_SECRET trong .env")
    SECRETS.extend([key, secret])
    r = requests.post(f"{API}/api/v3/auth/token", json={"apiKey": key, "apiSecret": secret}, timeout=15)
    print(f"Đăng nhập: HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        sys.exit(f"Phản hồi không phải JSON: {clean(r.text[:200])}")
    if not isinstance(body, dict) or "accessToken" not in body:
        sys.exit(f"Không có accessToken. Phản hồi: {clean(json.dumps(body, ensure_ascii=False)[:300])}")
    SECRETS.append(body["accessToken"])
    if body.get("refreshToken"):
        SECRETS.append(body["refreshToken"])
    now = time.time()
    print("  Các trường:", sorted(body))
    for f in ("expiresAt", "refreshExpiresAt"):
        v = body.get(f)
        if isinstance(v, (int, float)):
            sec = v / 1000 if v > 1e11 else v      # mili giây hay giây
            print(f"  {f}: {v} ({'mili giây' if v > 1e11 else 'giây'}), còn {(sec - now) / 3600:.1f} giờ")
    print(f"  Có refreshToken: {bool(body.get('refreshToken'))}; tokenType: {body.get('tokenType')}")
    return body


async def stream(token: str, symbol: str, seconds: float) -> bool:
    """Nối luồng trực tiếp theo SDK chính thức của SSI: đường dẫn /ws/v3, token trong header (không đưa lên địa chỉ)."""
    print(f"\nNối {STREAM} (token trong header Authorization) ...")
    try:
        async with websockets.connect(STREAM, ping_interval=20, open_timeout=10,
                                      additional_headers={"Authorization": f"Bearer {token}"}) as ws:
            print("  Đã nối.")
            await run_session(ws, symbol, seconds)
            return True
    except Exception as exc:  # noqa: BLE001 - chỉ để báo cho người thử
        print(f"  Lỗi: {type(exc).__name__}: {clean(exc)[:200]}")
        return False


async def run_session(ws, symbol: str, seconds: float) -> None:
    topic = f"quote.{symbol}"          # mỗi mã một chủ đề; không gộp "VNM,FPT"
    await ws.send(json.dumps({"method": "SUBSCRIBE", "channel": "DATA", "topics": [topic]}))
    print(f"  Đã gửi SUBSCRIBE {topic}; nghe {seconds:.0f} giây ...")
    end, n, shown, levels = time.time() + seconds, 0, 0, set()
    while time.time() < end:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=max(end - time.time(), 0.1))
        except asyncio.TimeoutError:
            break
        n += 1
        text = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
        try:
            d = json.loads(text)
        except ValueError:
            d = None
        if isinstance(d, dict) and d.get("method") == "PING":      # máy chủ gửi PING: trả PONG đúng định dạng
            await ws.send(json.dumps({"method": "PONG", "channel": "HEARTBEAT", "time": d.get("time")}))
        body = d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), dict) else d
        if isinstance(body, dict) and isinstance(body.get("bids"), list):
            levels.add((len(body["bids"]), len(body.get("asks") or [])))
        if shown < 6:
            print("  tin:", clean(text)[:400])
            shown += 1
    print(f"  Nhận {n} tin. Số mức giá (mua, bán) từng tin: {sorted(levels) or 'chưa thấy tin sổ lệnh'}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "VCB").upper()
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20
    body = login()
    ok = asyncio.run(stream(body["accessToken"], symbol, seconds))
    print("\nXong." if ok else "\nKhông nối được luồng trực tiếp bằng cả hai cách; gửi kết quả trên cho Claude.")


if __name__ == "__main__":
    main()
