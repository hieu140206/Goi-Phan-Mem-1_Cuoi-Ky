"""Xem tin WebSocket trong giờ nghỉ trưa (11:30-13:00) là tin gì: python scripts/inspect_ws_lunch.py [YYYY-MM-DD]

Đọc data/raw/<ngày>/ws.jsonl.gz (chỉ đọc, không gọi NEO). In: số tin theo loại, và với tin stockInfo thì những trường nào
thay đổi so với trạng thái trước của mã đó (nếu có thay đổi). Không in token hay thông tin cá nhân.
"""
from __future__ import annotations

import base64
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo_api.binary_msg import decode, is_stock_info, looks_binary  # noqa: E402
from neo_api.stream import parse_message  # noqa: E402


def analyze(path: Path, start: str = "11:30:00", end: str = "13:00:00") -> dict:
    state: dict[str, dict] = {}
    types: Counter = Counter()
    changed: Counter = Counter()
    same = diff = 0
    examples: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            t = pd.Timestamp(d["t"])
            raw = base64.b64decode(d["b"])
            inside = start <= t.strftime("%H:%M:%S") < end
            if not looks_binary(raw):
                if inside:
                    types["văn bản (không phải nhị phân)"] += 1
                continue
            if is_stock_info(raw):
                try:
                    rows = parse_message(raw)
                except Exception:  # noqa: BLE001
                    rows = []
                for row in rows:
                    sym = str(row.get("symbol") or "").upper()
                    prev = state.get(sym)
                    if inside:
                        types["stockInfo"] += 1
                        if prev is not None:
                            ch = [k for k, v in row.items() if prev.get(k) != v and k != "symbol"]
                            if ch:
                                diff += 1
                                changed.update(ch)
                                if len(examples) < 8:
                                    examples.append(f"{t.strftime('%H:%M:%S')} {sym}: " + ", ".join(
                                        f"{k} {prev.get(k)}→{row.get(k)}" for k in ch[:5]))
                            else:
                                same += 1
                    state[sym] = row
            elif inside:
                try:
                    types[decode(raw).type_name] += 1
                except Exception:  # noqa: BLE001
                    types["không đọc được"] += 1
    return {"types": dict(types), "stock_same": same, "stock_changed": diff,
            "changed_fields": dict(changed.most_common()), "examples": examples}


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%Y-%m-%d")
    path = ROOT / "data" / "raw" / day / "ws.jsonl.gz"
    if not path.exists():
        sys.exit(f"Không thấy {path}")
    r = analyze(path)
    print(f"Ngày {day}, tin trong 11:30-13:00:")
    for k, v in r["types"].items():
        print(f"  {k}: {v}")
    print(f"stockInfo giống hệt trạng thái trước: {r['stock_same']} | có thay đổi: {r['stock_changed']}")
    print("Trường thay đổi (số lần):", r["changed_fields"] or "không có")
    for e in r["examples"]:
        print("  ví dụ", e)


if __name__ == "__main__":
    main()
