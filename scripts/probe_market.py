"""Thăm dò NEO để quyết định phạm vi trang Tổng quan thị trường. Chỉ ĐỌC dữ liệu (khoảng 40-60 yêu cầu GET).

Chạy lúc sàn đang mở (9:30-14:30 để thấy giá thật), kích hoạt .venv trước:
  python scripts/probe_market.py

Trả lời 5 câu hỏi:
  1. 4.5: mỗi sàn (HOSE, HNX, UPCOM, FU) có bao nhiêu mã, loại gì? Hợp đồng VN30F tên ra sao?
  2. 4.3: những mã chỉ số nào có (VNINDEX, VN30, HNX..., UPCOM...)?
  3. 4.7: chỉ số nào cho lấy bảng giá cả rổ (bao nhiêu mã, mất bao lâu)?
  4. 4.6: một lần gọi lấy được tối đa bao nhiêu mã (để dựng bảng giá cả sàn)?
  5. 4.9: hợp đồng tương lai VN30 có giá, sổ lệnh, khối lượng mở không? Basis = giá HĐTL - chỉ số VN30.
Không in token. Lưu phản hồi gốc (chỉ dữ liệu thị trường) vào data/raw_samples/probe_<thời điểm>.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoClient  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402

saved: dict[str, object] = {}


def section(title: str) -> None:
    print(f"\n===== {title} =====")


def timed(fn, *args, **kwargs):
    t0 = time.time()
    out = fn(*args, **kwargs)
    return out, time.time() - t0


def attempt(label: str, fn):
    """Một bước lỗi (không có quyền, sai mã...) không làm dừng các bước sau."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        print(f"  [{label}] lỗi: {type(exc).__name__}: {str(exc)[:160]}")
        return None


def probe_stock_lists(client) -> dict[str, list[dict]]:
    section("1. Danh sách mã (4.5)")
    lists: dict[str, list[dict]] = {}
    for market in ("HOSE", "HNX", "UPCOM", "FU"):
        res = attempt(market, lambda m=market: timed(client.get_stock_list, m))
        if not res:
            continue
        rows, sec = res
        lists[market] = rows
        types = Counter(r.get("stockType") for r in rows)
        print(f"  {market}: {len(rows)} mã trong {sec:.1f}s | theo loại: {dict(types)}")
    saved["4.5 stockList (đếm theo sàn)"] = {m: len(r) for m, r in lists.items()}
    fu = lists.get("FU", [])
    vn30f = [r for r in fu if "VN30" in " ".join(str(r.get(k, "")) for k in ("symbol", "stockName", "otherName"))]
    print(f"  Hợp đồng liên quan VN30 trong FU: {len(vn30f)}")
    for r in (vn30f or fu)[:6]:
        print("    ", {k: r.get(k) for k in ("symbol", "stockName", "otherName", "exchangeCode")})
    saved["4.5 FU liên quan VN30"] = vn30f[:20]
    return lists


def probe_indices(client) -> tuple[list[dict], float | None]:
    section("2. Chỉ số (4.3)")
    detail = attempt("4.3", lambda: client.get_index_detail("ALL")) or []
    saved["4.3 marketIndexDetail"] = detail
    vn30_value = None
    for r in detail:
        print("  ", {k: r.get(k) for k in ("indexCode", "indexValue", "advances", "declines", "noChange", "sumValue")})
        if r.get("indexCode") == "VN30" and isinstance(r.get("indexValue"), (int, float)):
            vn30_value = float(r["indexValue"])
    return detail, vn30_value


def probe_baskets(client) -> None:
    section("3. Bảng giá theo chỉ số (4.7): mã chỉ số nào dùng được")
    idx = attempt("4.1", lambda: client.get_index_list("ALL")) or []
    codes = [r.get("indexCode") or r.get("code") for r in idx]
    codes = [c for c in codes if c]
    saved["4.1 mã chỉ số"] = codes
    print(f"  Thử {len(codes)} mã chỉ số: {', '.join(codes)}")
    result = {}
    for code in codes:
        res = attempt(code, lambda c=code: timed(client.get_stocks_by_index, c))
        if res is None:
            result[code] = "lỗi"
            continue
        rows, sec = res
        result[code] = len(rows)
        print(f"  {code:<12} {len(rows):>4} mã | {sec:.1f}s")
    saved["4.7 số mã theo chỉ số"] = result


def probe_batch_limit(client, lists: dict[str, list[dict]]) -> None:
    section("4. Giới hạn số mã mỗi lần gọi (4.6)")
    syms = [r["symbol"] for r in lists.get("HOSE", []) if r.get("stockType") == "ST" and r.get("symbol")]
    if not syms:
        print("  Không có danh sách HOSE (bước 1 lỗi), bỏ qua.")
        return
    out = {}
    for n in (30, 100, 300, len(syms)):
        n = min(n, len(syms))
        if n in out:
            continue
        res = attempt(f"{n} mã", lambda n=n: timed(client.get_stock_detail, syms[:n], "HOSE"))
        if res is None:
            out[n] = "lỗi"
            continue
        rows, sec = res
        out[n] = len(rows)
        print(f"  xin {n:>3} mã -> nhận {len(rows):>3} dòng | {sec:.1f}s")
    saved["4.6 xin n mã -> nhận"] = out


def probe_futures(client, lists: dict[str, list[dict]], vn30_value: float | None) -> None:
    section("5. Hợp đồng tương lai VN30 (4.9)")
    fu = lists.get("FU", [])
    # NEO đặt mã hợp đồng kiểu 41I1GB000; tên VN30F1M nằm ở otherName, loại là FUVN30
    cands = [r["symbol"] for r in fu if str(r.get("stockType", "")).upper() == "FUVN30"]
    print(f"  Hợp đồng VN30 (stockType FUVN30) trong 4.5: {cands[:8]}")
    rows = attempt("4.9 theo mã", lambda: client.get_fu_detail(cands[:4])) if cands else None
    if not rows:
        rows = attempt("4.9 mặc định", lambda: client.get_fu_detail()) or []
        print("  (không thấy hợp đồng FUVN30 trong 4.5, đã gọi 4.9 không truyền mã)")
    saved["4.9 fuStockDetail"] = rows
    keys = ("symbol", "maturityDate", "closePrice", "bidPrice1", "askPrice1", "bidVol1", "askVol1",
            "totalTradingVolume", "openInterest", "tradingSession")
    for r in rows[:6]:
        print("  ", {k: r.get(k) for k in keys})
        px = r.get("closePrice")
        if vn30_value and isinstance(px, (int, float)) and px:
            print(f"     basis = {px:.2f} - {vn30_value:.2f} = {px - vn30_value:+.2f} điểm")
    if not rows:
        print("  Không có dòng nào.")


def main() -> None:
    settings = get_settings()
    try:
        tokens = TokenManager(settings)
        tokens.get()
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    client = NeoClient(settings, tokens)
    print("Giờ máy:", pd.Timestamp.now(tz=TZ).strftime("%d/%m/%Y %H:%M:%S"))
    status = attempt("4.4", lambda: client.get_market_status())
    saved["4.4 marketStatus"] = status
    print("Trạng thái phiên:", [(r.get("marketCode"), r.get("marketStatus")) for r in status or []])

    lists = probe_stock_lists(client)
    _, vn30_value = probe_indices(client)
    probe_baskets(client)
    probe_batch_limit(client, lists)
    probe_futures(client, lists, vn30_value)

    out = ROOT / "data" / "raw_samples" / f"probe_{pd.Timestamp.now(tz=TZ):%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(saved, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nĐã lưu phản hồi gốc vào {out.relative_to(ROOT)}. Gửi mình phần chữ in ra ở trên (không có token).")


if __name__ == "__main__":
    main()
