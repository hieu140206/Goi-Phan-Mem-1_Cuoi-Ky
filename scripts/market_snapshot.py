"""Thử 3 endpoint thị trường: 4.4 trạng thái phiên, 4.3 chỉ số trong phiên, 4.2 chỉ số intraday.

Chạy (kích hoạt .venv trước):
  python scripts/market_snapshot.py               # chuỗi intraday của VN30
  python scripts/market_snapshot.py --index VNINDEX

In tóm tắt và lưu phản hồi gốc vào data/raw_samples/market_<thời điểm>.json để đối chiếu với tài liệu.
Chỉ ĐỌC dữ liệu, 3 lần gọi API.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoApiError, NeoClient  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="VN30", help="Chỉ số lấy chuỗi intraday (mặc định VN30)")
    args = ap.parse_args()

    settings = get_settings()
    client = NeoClient(settings, TokenManager(settings))
    saved: dict[str, object] = {}
    pd.set_option("display.width", 200)

    try:
        status = client.get_market_status()
        saved["4.4 marketStatus"] = status
        print("== 4.4 Trạng thái phiên ==")
        print(pd.DataFrame(status).to_string(index=False) if status else "(rỗng)")

        detail = client.get_index_detail("ALL")
        saved["4.3 marketIndexDetail"] = detail
        print("\n== 4.3 Chỉ số trong phiên ==")
        if detail:
            df = pd.DataFrame(detail)
            cols = [c for c in ["indexCode", "indexValue", "indexChange", "indexPercentChange", "advances",
                                "declines", "noChange", "sumValue", "marketStatus", "indexTime"] if c in df.columns]
            print(df[cols].to_string(index=False))
            print("Các cột NEO trả về:", list(df.columns))
        else:
            print("(rỗng)")

        intraday = client.get_index_intraday(args.index)
        saved["4.2 intradayMarketIndex"] = intraday
        points = intraday.get("index") or [] if isinstance(intraday, dict) else []
        print(f"\n== 4.2 {args.index} intraday ==")
        print("Điểm:", intraday.get("indexValue"), "| thay đổi:", intraday.get("indexChange"),
              "| phiên:", intraday.get("marketStatus"), "| số điểm dữ liệu trong ngày:", len(points))
        if points:
            pts = pd.DataFrame(points)
            print("Cột của index[]:", list(pts.columns))
            print("3 điểm đầu:\n", pts.head(3).to_string(index=False))
            print("3 điểm cuối:\n", pts.tail(3).to_string(index=False))
    except (LoginError, NeoApiError) as exc:
        print(f"\nLỗi: {exc}")
    finally:
        if saved:
            out = ROOT / "data" / "raw_samples" / f"market_{pd.Timestamp.now(tz=TZ):%Y%m%d_%H%M%S}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\nĐã lưu phản hồi gốc vào {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
