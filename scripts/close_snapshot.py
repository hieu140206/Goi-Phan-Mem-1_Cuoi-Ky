"""Chốt số CUỐI NGÀY của phiên hôm nay vào market.db: chỉ số, bảng giá VN30, bảng giá các sàn, phái sinh (khoảng 12 yêu cầu GET, chỉ đọc).

Dùng khi bộ ghi đã dừng lúc 14:45 (bản cũ) nên thẻ chỉ số dừng ở 14:44, lệch số chính thức do giá đóng cửa ATC và giao dịch
thỏa thuận chưa vào. Chạy từ 15:00 cùng ngày (kích hoạt .venv trước):  python scripts/close_snapshot.py
Bản bộ ghi mới đã tự làm việc này tới 15:02 nên chỉ cần khi chạy bằng bản cũ.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.market_day import TooEarlyError, save_close_snapshot  # noqa: E402
from data.overview import INDEX_NAMES, MAIN_INDICES  # noqa: E402
from data.storage import load_market_index  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoClient  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402


def main() -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    now = pd.Timestamp.now(tz=TZ)
    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        tokens.get()
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")
    db = settings.db_path if Path(settings.db_path).is_absolute() else ROOT / settings.db_path
    try:
        res = save_close_snapshot(NeoClient(settings, tokens), db, ROOT / "data", now)
    except TooEarlyError as exc:
        sys.exit(str(exc))
    print(f"\nĐã lưu lúc {now:%H:%M:%S}: {res['indices']} dòng chỉ số, bảng giá VN30 {res['vn30']} mã.")
    print("Bảng giá các sàn đã có trong ngày:", res["groups"] or "(chưa có)")
    if res["errors"]:
        print("Lỗi:", res["errors"])
    frame = load_market_index(db, f"{now:%Y-%m-%d}")
    last = frame.sort_values("ts").groupby("index_code").tail(1).set_index("index_code")
    print("Số cuối ngày để đối chiếu với bảng giá chính thức:")
    for code in MAIN_INDICES:
        if code in last.index:
            r = last.loc[code]
            print(f"  {INDEX_NAMES[code]:11s} {r['index_value']:>9,.2f}  ({r['index_change']:+.2f}, {r['pct_change']:+.2f}%)"
                  f"  KL {r['sum_volume']:,.0f}  GT {r['sum_value'] / 1e9:,.2f} tỷ")


if __name__ == "__main__":
    main()
