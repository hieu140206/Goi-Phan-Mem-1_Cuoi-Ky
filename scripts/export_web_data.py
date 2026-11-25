"""Xuất dữ liệu rút gọn cho bản web vào data/web/ (chạy ở laptop, sau giờ giao dịch). Chỉ ĐỌC market.db, candles.db, data/raw.

Chạy (kích hoạt .venv trước):
  python scripts/export_web_data.py
Rồi: git add data/web && git commit -m "Cập nhật dữ liệu web" && git push   (web tự dựng lại và giải nén dữ liệu mới)

Không đưa ws_quotes, ws_trades lên web (chỉ để đối chiếu, rất lớn). Tệp nén cỡ vài chục MB; mỗi lần đẩy thêm chừng đó vào lịch sử repo,
nên chỉ xuất khi có dữ liệu mới đáng kể (ví dụ cuối mỗi ngày giao dịch).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.candle_store import DEFAULT_PATH as CANDLES_DB  # noqa: E402
from data.web_data import WEB_DIR, export_web_data  # noqa: E402
from neo_api.config import get_settings  # noqa: E402


def main() -> None:
    market = Path(get_settings().db_path)
    if not market.exists():
        sys.exit(f"Không thấy {market}: chạy script này ở máy có dữ liệu thật.")
    made = export_web_data(market, CANDLES_DB, ROOT / "data" / "raw", WEB_DIR)
    for name, size in made.items():
        print(f"  {name}: {size / 1e6:.1f} MB")
    print(f"Xong. Các tệp ở {WEB_DIR}. Bước tiếp: git add data/web, commit, push.")


if __name__ == "__main__":
    main()
