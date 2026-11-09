"""Thử kết nối SSI (chỉ ĐỌC, không đặt lệnh): đăng nhập, rồi nhận sổ lệnh một mã vài giây.

Chạy (kích hoạt .venv trước):
  python scripts/probe_ssi.py rest VCB          # lịch sử theo ngày từ SSI, đối chiếu NEO (chạy được cả ngoài giờ)
  python scripts/probe_ssi.py stream VCB 20    # nghe sổ lệnh trực tiếp (trong giờ giao dịch); hoặc chủ đề: quote.VN30@*
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

import pandas as pd  # noqa: E402
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
    topic = symbol if "." in symbol else f"quote.{symbol}"   # mỗi mã một chủ đề; hoặc truyền sẵn chủ đề, ví dụ quote.VN30@*
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


def api_get(token: str, path: str, params: dict) -> object:
    r = requests.get(f"{API}{path}", params=params, timeout=20,
                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    print(f"  GET {path} {params}: HTTP {r.status_code}"
          f"  (giới hạn còn {r.headers.get('X-RATELIMIT-REMAINING', '?')}/{r.headers.get('X-RATELIMIT-LIMIT', '?')})")
    time.sleep(0.3)
    if r.status_code == 204:
        return []
    if not r.ok:
        print("   ", clean(r.text[:200]))
        return None
    return r.json()


def rows_of(body: object) -> list[dict]:
    if isinstance(body, dict):
        body = body.get("data")
    return [x for x in (body or []) if isinstance(x, dict)]


def neo_final_rows(symbol: str) -> dict[str, dict]:
    """Dòng bảng giá VN30 cuối mỗi ngày của NEO (từ market.db), chỉ lấy ảnh chụp từ 14:45 trở đi."""
    import sqlite3

    from neo_api.config import get_settings
    db = get_settings().db_path
    db = db if Path(db).is_absolute() else ROOT / db
    con = sqlite3.connect(db)
    out: dict[str, dict] = {}
    q = ("SELECT day, ts, last_px, total_vol, foreign_buy_vol, foreign_sell_vol, foreign_remain FROM board "
         "WHERE grp='VN30' AND symbol=? ORDER BY day, ts")
    for day, ts, px, vol, fb, fs, room in con.execute(q, (symbol,)):
        if ts[11:16] >= "14:45":                      # đã qua ATC; dòng sau ghi đè dòng trước
            out[day] = {"close": px, "vol": vol, "fbuy": fb, "fsell": fs, "room": room}
    return out


def rest_check(token: str, symbol: str) -> None:
    """Lấy giá đóng cửa, khối lượng, mua bán nước ngoài theo ngày từ SSI rồi đối chiếu với NEO. Chỉ đọc."""
    today = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").normalize()
    frm, to = (today - pd.Timedelta(days=21)).strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d")
    print(f"\nSSI {symbol}, từ {frm} đến {to}")
    summ = rows_of(api_get(token, "/api/v3/data/securitiesSummary",
                           {"symbol": symbol, "from": frm, "to": to, "pageSize": 50}))
    ohlc = rows_of(api_get(token, "/api/v3/data/ohlc", {"symbol": symbol, "from": frm, "to": to,
                                                        "timeFrame": "1d", "pageSize": 50}))
    if summ:
        print("  Các trường securitiesSummary:", sorted(summ[0]))
        print("  Dòng mẫu:", {k: summ[0].get(k) for k in ("tradingDate", "close", "totalMatch", "totalForeignBuy",
                                                           "totalForeignSell", "remainForeignRoom")})
    if ohlc:
        print("  Dòng mẫu ohlc:", {k: ohlc[0].get(k) for k in ("tradingDate", "open", "close", "volume", "value")})
    idx = rows_of(api_get(token, "/api/v3/data/indexSummary",
                          {"index": "VNINDEX", "tradingDate": (today - pd.Timedelta(days=4)).strftime("%Y/%m/%d")}))
    if idx:
        print("  indexSummary VNINDEX mẫu:", {k: idx[0].get(k) for k in ("tradingDate", "indexValue", "totalMatch",
                                                                        "totalAdvanceStock", "totalBuyForeign")})
    neo = neo_final_rows(symbol)
    print(f"\n  So với NEO ({len(neo)} ngày có ảnh chụp sau ATC). Giá NEO đơn vị đồng; tỷ lệ SSI/NEO cho biết đơn vị SSI.")
    print(f"  {'ngày':10s} {'đóng SSI':>10s} {'đóng NEO':>10s} {'KL SSI':>12s} {'KL NEO':>12s} "
          f"{'NN mua SSI':>12s} {'NN mua NEO':>12s} {'room SSI':>12s} {'room NEO':>12s}")
    for r in sorted(summ, key=lambda x: str(x.get("tradingDate"))):
        day = str(r.get("tradingDate", ""))[:10].replace("/", "-")
        n = neo.get(day)
        if not n:
            continue
        print(f"  {day:10s} {r.get('close')!s:>10} {n['close']!s:>10} {r.get('totalMatch')!s:>12} {n['vol']!s:>12} "
              f"{r.get('totalForeignBuy')!s:>12} {n['fbuy']!s:>12} {r.get('remainForeignRoom')!s:>12} {n['room']!s:>12}")
    sd = {str(r.get("tradingDate", ""))[:10] for r in summ}
    print(f"\n  SSI có {len(summ)} ngày (securitiesSummary), {len(ohlc)} ngày (ohlc). Ngày SSI có mà NEO chưa có: "
          f"{sorted(d.replace('/', '-') for d in sd if d.replace('/', '-') not in neo)}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = sys.argv[1:]
    mode = args.pop(0) if args and args[0] in ("rest", "stream") else "stream"
    symbol = (args[0] if args else "VCB").upper()
    body = login()
    if mode == "rest":
        rest_check(body["accessToken"], symbol)
        print("\nXong.")
        return
    seconds = float(args[1]) if len(args) > 1 else 20
    ok = asyncio.run(stream(body["accessToken"], symbol, seconds))
    print("\nXong." if ok else "\nKhông nối được luồng trực tiếp; gửi kết quả trên cho Claude.")


if __name__ == "__main__":
    main()
