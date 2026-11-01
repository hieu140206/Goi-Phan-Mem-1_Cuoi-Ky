"""Lấy bù chuỗi chỉ số trong ngày (VN30, VN-Index, HNX-Index, UPCoM-Index) và độ rộng cuối ngày của phiên HÔM NAY.

Chạy sau 14:45 cùng ngày giao dịch (kích hoạt .venv trước):  python scripts/fetch_day_index.py
Dùng khi bộ ghi chưa lưu đủ các chuỗi này (ví dụ phiên 28/10/2026 chỉ có VN30 và VN-Index).
Chỉ THÊM phần còn thiếu vào data/raw/<ngày>/market.json, không ghi đè. Chỉ ĐỌC dữ liệu, tối đa 5 yêu cầu GET.
Chạy sáng hôm sau sẽ bị từ chối vì chuỗi 4.2 chỉ có giờ, không có ngày.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.market_day import TooEarlyError, fetch_day_extras  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoClient  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        tokens.get()
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    try:
        res = fetch_day_extras(NeoClient(settings, tokens), ROOT / "data", pd.Timestamp.now(tz=TZ))
    except TooEarlyError as exc:
        sys.exit(str(exc))
    print("Đã thêm:", ", ".join(res["added"]) or "(không có gì mới)")
    print("Đã có sẵn, giữ nguyên:", ", ".join(res["kept"]) or "(không)")
    if res["errors"]:
        print("Lỗi:", res["errors"])


if __name__ == "__main__":
    main()
