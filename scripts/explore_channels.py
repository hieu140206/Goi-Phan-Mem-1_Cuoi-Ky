"""Khám phá các kênh WebSocket của NEO: đăng ký nhiều kênh, in và lưu tin thật để xem cấu trúc.

Chạy (kích hoạt .venv trước):
  python scripts/explore_channels.py                 # 4 kênh mặc định, tối đa 60 giây
  python scripts/explore_channels.py --seconds 120 --per-channel 5

Kênh mặc định theo code mẫu của NEO:
  marketInfo    : VNINDEX, VN30          (dữ liệu chỉ số)
  marketSession : HOSE, HNX              (trạng thái phiên)
  marketVolume  : VNINDEX, VN30, HNX30   (khối lượng chỉ số)
  stockInfo     : VCB, FPT, HPG          (dữ liệu cổ phiếu)

Kết quả lưu ở data/raw_samples/<thời điểm>.jsonl (mỗi dòng một tin: giờ nhận, byte gốc dạng base64,
và các trường đã giải mã nếu là tin nhị phân). Tin của NEO không chứa token,
nhưng hãy mở xem trước khi chia sẻ. Chỉ ĐỌC dữ liệu, không đăng ký kênh lệnh của tài khoản.
Ngoài giờ giao dịch NEO có thể không gửi tin nào; khi đó script dừng sau --seconds giây.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import websockets  # noqa: E402

from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.binary_msg import DecodeError, decode, looks_binary, to_bytes, to_dict  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402
from neo_api.stream import AuthError, build_auth_message, build_subscribe_message, connect_ws  # noqa: E402

DEFAULT_SUBS = {
    "marketInfo": ["VNINDEX", "VN30"],
    "marketSession": ["HOSE", "HNX"],
    "marketVolume": ["VNINDEX", "VN30", "HNX30"],
    "stockInfo": ["VCB", "FPT", "HPG"],
}


def guess_channel(msg: object) -> str:
    """Đoán tin thuộc kênh nào (chưa biết NEO ghi tên kênh ở trường nào nên thử vài tên thường gặp)."""
    if isinstance(msg, dict):
        for key in ("channel", "type", "event", "topic"):
            if isinstance(msg.get(key), str):
                return msg[key]
        if isinstance(msg.get("data"), dict):
            return guess_channel(msg["data"])
    return "không rõ"


def describe(msg: object, depth: int = 0) -> str:
    """Tóm tắt cấu trúc: tên trường và kiểu dữ liệu (không in giá trị dài)."""
    pad = "  " * depth
    if isinstance(msg, dict):
        lines = []
        for k, v in msg.items():
            if isinstance(v, (dict, list)) and depth < 2:
                lines.append(f"{pad}{k}: {type(v).__name__}")
                lines.append(describe(v, depth + 1))
            else:
                sample = repr(v)
                lines.append(f"{pad}{k}: {type(v).__name__} = {sample[:40]}")
        return "\n".join(lines)
    if isinstance(msg, list):
        return f"{pad}[danh sách {len(msg)} phần tử]" + ("\n" + describe(msg[0], depth + 1) if msg else "")
    return f"{pad}{type(msg).__name__} = {repr(msg)[:40]}"


JWT_LIKE = re.compile(r"eyJ[\w-]{10,}\.[\w-]+\.[\w-]+")


def mask(text: str) -> str:
    """Che mọi chuỗi trông giống token JWT trước khi in."""
    return JWT_LIKE.sub("<token đã che>", text)


async def auth_verbose(ws, token: str, timeout: float = float(os.getenv("NEO_AUTH_WAIT", "15"))) -> None:
    """Gửi xác thực và IN MỌI TIN nhận được trong lúc chờ (bản _authenticate thường bỏ qua tin lạ).
    Không có xác nhận thì vẫn đi tiếp để xem NEO có gửi dữ liệu sau khi đăng ký kênh không."""
    await ws.send(build_auth_message(token))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while (remaining := deadline - loop.time()) > 0:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        except websockets.ConnectionClosed as exc:
            raise SystemExit(f"NEO đóng kết nối khi xác thực: mã {exc.rcvd.code if exc.rcvd else '?'}, "
                             f"lý do '{exc.rcvd.reason if exc.rcvd else ''}'")
        if looks_binary(raw):
            try:
                print("  NEO gửi (nhị phân):", decode(raw))
            except DecodeError:
                print("  NEO gửi (nhị phân, hex):", to_bytes(raw)[:60].hex(" "))
            continue
        text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        print("  NEO gửi:", mask(text)[:300])
        try:
            msg = json.loads(text)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "auth":
            if msg.get("status") == "success":
                print("Xác thực WebSocket thành công.")
                return
            raise AuthError(f"Xác thực thất bại: {mask(str(msg))[:200]}")
    print("Không thấy xác nhận xác thực sau 15 giây. Vẫn thử đăng ký kênh để xem NEO có gửi dữ liệu không.")


async def explore(subs: dict[str, list[str]], seconds: float, per_channel: int, out: Path, token_provider) -> Counter:
    settings = get_settings()
    counts: Counter = Counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Bước 1: đang mở kết nối tới {settings.ws_url} ...")
    async with connect_ws(settings.ws_url) as ws:
        print("Bước 2: đã mở kết nối. Đang gửi token và chờ NEO xác nhận (tối đa 15 giây)...")
        await auth_verbose(ws, token_provider())
        for channel, ids in subs.items():
            await ws.send(build_subscribe_message(ids, channel))
            print(f"  đăng ký {channel}: {', '.join(ids)}")
        print(f"Đang nghe tối đa {seconds:.0f} giây (Ctrl+C để dừng sớm)...\n")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        with out.open("w", encoding="utf-8") as fh:
            while (remaining := deadline - loop.time()) > 0:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                record = {"received_at": pd.Timestamp.now(tz=TZ).isoformat(),
                          "frame": "binary" if isinstance(raw, bytes) else "text",
                          "raw_b64": base64.b64encode(to_bytes(raw)).decode("ascii")}  # giữ nguyên từng byte
                decoded = None
                if looks_binary(raw):
                    try:
                        decoded = decode(raw)
                        ch = decoded.type_name
                        record["type_index"], record["fields"] = decoded.type_index, decoded.fields
                    except DecodeError as exc:
                        ch = "nhị phân chưa giải mã được"
                        record["decode_error"] = str(exc)
                else:
                    text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
                    try:
                        record["msg"] = json.loads(text)
                    except ValueError:
                        record["msg"] = text
                    ch = guess_channel(record["msg"])
                counts[ch] += 1
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                if counts[ch] <= per_channel:
                    print(f"===== [{ch}] tin số {counts[ch]} =====")
                    if decoded is not None:
                        for i, (name, v) in enumerate(to_dict(decoded).items(), 1):
                            print(f"  {i:>2}. {name}: {v!r}")
                    elif "msg" in record:
                        print(describe(record["msg"]))
                    else:
                        print("  ", record["decode_error"], "| byte đầu (hex):", to_bytes(raw)[:40].hex(" "))
                    print()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=60, help="Nghe tối đa bao nhiêu giây (mặc định 60)")
    ap.add_argument("--per-channel", type=int, default=2, help="In tối đa bao nhiêu tin mỗi kênh (mặc định 2)")
    args = ap.parse_args()

    stamp = pd.Timestamp.now(tz=TZ).strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / "raw_samples" / f"{stamp}.jsonl"
    tokens = TokenManager(get_settings())
    try:
        tokens.get()
        counts = asyncio.run(explore(DEFAULT_SUBS, args.seconds, args.per_channel, out, tokens.get))
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    except AuthError as exc:
        sys.exit(f"{exc}. Kiểm tra token và IP đã đăng ký.")
    except websockets.exceptions.InvalidURI as exc:
        sys.exit(f"Địa chỉ WebSocket không hợp lệ: {exc}")
    except (OSError, websockets.WebSocketException) as exc:
        sys.exit(f"Không kết nối được WebSocket ({get_settings().ws_url}): {type(exc).__name__} {str(exc)[:120]}")
    except KeyboardInterrupt:
        print("\nĐã dừng.")
        return
    print("Tổng số tin theo kênh:", dict(counts) or "không nhận được tin nào (có thể đang ngoài giờ giao dịch)")
    print(f"Đã lưu toàn bộ tin vào {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
