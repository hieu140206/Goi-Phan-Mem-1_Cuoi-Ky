"""Chụp nhanh rổ VN30 qua REST 4.7 (stockDetailByIndex): danh sách mã, giá, spread, độ sâu.

Chạy (kích hoạt .venv trước):
  python scripts/vn30_snapshot.py               # rổ VN30
  python scripts/vn30_snapshot.py --index VN100

Lưu 2 file vào data/raw_samples/: phản hồi gốc (.json) và bảng đã làm sạch (.csv), cộng file symbols_<chỉ số>.txt
để bộ ghi dữ liệu dùng làm danh sách mã. Chỉ ĐỌC dữ liệu, 1 lần gọi API.
Ngoài giờ giao dịch: sổ lệnh có thể rỗng hoặc là giá ATO/ATC, khi đó bảng làm sạch sẽ ít dòng hơn (bình thường).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.schema import normalize_quotes  # noqa: E402
from finance.liquidity import add_liquidity_metrics  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoApiError, NeoClient  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402
from neo_api.stream import map_record  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="VN30", help="Mã chỉ số (mặc định VN30)")
    args = ap.parse_args()

    settings = get_settings()
    client = NeoClient(settings, TokenManager(settings))
    now = pd.Timestamp.now(tz=TZ)
    try:
        records = client.get_stocks_by_index(args.index)
    except (LoginError, NeoApiError) as exc:
        sys.exit(f"Lỗi: {exc}")
    if not records:
        sys.exit(f"NEO không trả mã nào cho {args.index}.")

    out_dir = ROOT / "data" / "raw_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    (out_dir / f"{args.index}_{stamp}.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    symbols = sorted({str(r["symbol"]).upper() for r in records if r.get("symbol")})
    (out_dir / f"symbols_{args.index}.txt").write_text(
        f"# Rổ {args.index} lấy từ NEO 4.7 lúc {now:%Y-%m-%d %H:%M}\n" + "\n".join(symbols) + "\n", encoding="utf-8")
    print(f"Rổ {args.index}: {len(symbols)} mã -> {' '.join(symbols)}\n")

    raw = pd.DataFrame([map_record(r) for r in records]).assign(ts=now)
    clean, report = normalize_quotes(raw)
    dropped = {k: v for k, v in report.items() if k.startswith("dropped") and v}
    if dropped:
        print("Dòng bị loại khi làm sạch:", dropped, "(ngoài giờ hoặc phiên ATO/ATC thì bình thường)\n")
    if clean.empty:
        print("Không còn dòng hợp lệ để tính spread (thường do đang ngoài giờ giao dịch).")
    else:
        m = add_liquidity_metrics(clean)
        cols = [c for c in ["symbol", "ref_px", "last_px", "bid_px1", "ask_px1", "rel_spread_bps", "depth_value", "imbalance"]
                if c in m.columns]
        pd.set_option("display.width", 200)
        print(m[cols].sort_values("rel_spread_bps", ascending=False)
              .to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        m.to_csv(out_dir / f"{args.index}_{stamp}.csv", index=False, encoding="utf-8-sig")
    print(f"\nĐã lưu vào {out_dir.relative_to(ROOT)} (file {args.index}_{stamp}.*, symbols_{args.index}.txt)")


if __name__ == "__main__":
    main()
