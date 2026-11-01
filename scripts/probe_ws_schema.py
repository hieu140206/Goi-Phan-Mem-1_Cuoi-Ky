"""THỬ KẾT NỐI (chỉ đọc): xem máy chủ WebSocket thật của NEO có hỗ trợ bước "sync" schema và kênh marketData không.

Chạy được CẢ NGÀY NGHỈ (bước sync không cần thị trường mở):
  pip install fastavro            # một lần
  python scripts/probe_ws_schema.py              # nghe 20 giây
  python scripts/probe_ws_schema.py --seconds 60 VCB FPT HPG

Việc nó làm: đăng nhập (hỏi tài khoản và mật khẩu, không lưu), kết nối, xác thực bằng token, gửi "sync", lưu schema vào
data/ws_schemas.json (chỉ là mô tả định dạng, không chứa thông tin cá nhân), đăng ký vài mã ở các kênh
stockInfo, marketData, marketInfo, marketVolume, marketSession rồi in số tin và 2 mẫu cho từng kênh.
KHÔNG đặt lệnh, KHÔNG in token. Dán kết quả in ra cho Claude.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.avro_sync import (AvroDecoder, build_sync_message, is_sync_frame, parse_schema_payload,  # noqa: E402
                               schema_hash)
from neo_api.config import get_settings  # noqa: E402
from neo_api.stream import _authenticate, build_subscribe_message, connect_ws  # noqa: E402


async def probe(symbols: list[str], seconds: float, settings, token: str) -> None:
    counts: Counter = Counter()
    samples: dict[str, list] = {}
    async with connect_ws(settings.ws_url) as ws:
        await _authenticate(ws, token)
        await ws.send(build_sync_message(""))
        print("Đã gửi sync, chờ schema...")
        payload = None
        t0 = time.time()
        while time.time() - t0 < 15:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=15 - (time.time() - t0))
            except asyncio.TimeoutError:
                break
            if is_sync_frame(frame):
                payload = bytes(frame[1:])
                break
            counts["tin trước khi có schema"] += 1
        if payload is None:
            print("KHÔNG nhận được tin schema trong 15 giây: máy chủ này có thể không hỗ trợ sync, hoặc xác thực chưa được chấp nhận.")
            return
        schemas = parse_schema_payload(payload)
        print(f"Nhận schema: {len(schemas)} loại, id = {sorted(schemas)}")
        out = ROOT / "data" / "ws_schemas.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({str(k): v for k, v in schemas.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Đã lưu mô tả định dạng vào {out.relative_to(ROOT)}")
        for sid, sch in sorted(schemas.items()):
            fields = [f.get("name") for f in sch.get("fields", [])] if isinstance(sch, dict) else []
            print(f"  id {sid}: {sch.get('name') if isinstance(sch, dict) else '?'} | {len(fields)} trường: {', '.join(map(str, fields))[:200]}")
        dec = AvroDecoder(schemas)
        await ws.send(build_sync_message(schema_hash(payload)))  # xác nhận đã nhận schema (giống SDK)
        for ch in ("stockInfo", "marketData"):
            await ws.send(build_subscribe_message(symbols, ch))
        for ch, ids in (("marketInfo", ["VN30", "VNINDEX"]), ("marketVolume", ["VN30"]), ("marketSession", ["HOSE"])):
            await ws.send(build_subscribe_message(ids, ch))
        print(f"Đã đăng ký {symbols} và các kênh chỉ số, nghe {seconds:.0f} giây...")
        t0 = time.time()
        while time.time() - t0 < seconds:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=max(seconds - (time.time() - t0), 0.1))
            except asyncio.TimeoutError:
                break
            if not isinstance(frame, (bytes, bytearray)):
                counts["tin chữ (không phải nhị phân)"] += 1
                continue
            if is_sync_frame(frame):
                counts["tin sync"] += 1
                continue
            try:
                sid, ch, rec = dec.decode(bytes(frame))
            except Exception as exc:  # noqa: BLE001
                counts[f"không giải mã được ({type(exc).__name__})"] += 1
                continue
            name = ch or f"id{sid}"
            counts[name] += 1
            if len(samples.setdefault(name, [])) < 2:
                samples[name].append(rec)
    print("\n===== Kết quả =====")
    for k, v in counts.most_common():
        print(f"  {k}: {v}")
    for name, recs in samples.items():
        for r in recs:
            print(f"mẫu {name}: {json.dumps(r, ensure_ascii=False, default=str)[:400]}")
    if not counts.get("marketData"):
        print("Chưa thấy tin marketData (có thể do thị trường đóng cửa, hoặc kênh này chưa mở ở máy chủ thật).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="*", default=["VCB", "FPT", "HPG"])
    ap.add_argument("--seconds", type=float, default=20)
    args = ap.parse_args()
    try:
        import fastavro  # noqa: F401, PLC0415
    except ImportError:
        sys.exit("Cần cài thư viện: pip install fastavro")
    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        token = tokens.get()
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    asyncio.run(probe([s.upper() for s in args.symbols], args.seconds, settings, token))


if __name__ == "__main__":
    main()
