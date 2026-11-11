"""Ghi dữ liệu sổ lệnh rổ VN30 trong một phiên giao dịch, qua REST của NEO.

Chạy mỗi ngày giao dịch, khoảng 9:05 (kích hoạt .venv trước):
  python scripts/record_rest.py

Bộ ghi tự chờ tới phiên, tự bỏ qua giờ nghỉ trưa, tự dừng sau khi đóng cửa (khoảng 15:02, sau khi chốt số cuối ngày).
Dừng sớm: Ctrl+C (dữ liệu đã ghi vẫn giữ nguyên, tóm tắt phiên vẫn được lưu).
Giữ máy bật, không cho máy ngủ, dùng đúng mạng có IP đã đăng ký với NEO.

Kết quả:
  data/market.db                      sổ lệnh phiên khớp lệnh liên tục (Radar đọc file này)
  data/raw/<ngày>/stocks.jsonl.gz     phản hồi gốc của NEO mỗi phút (bằng chứng, xử lý lại được)
  data/raw/<ngày>/market.json         chuỗi VN30/VNINDEX trong ngày và độ rộng thị trường
  data/sessions.csv                   tóm tắt từng phiên (điền sheet "Dữ liệu thu thập" trong Excel)
Chỉ ĐỌC dữ liệu, không đặt lệnh. Mỗi phút 3 yêu cầu API (4.4, 4.7, 4.3).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.rest_recorder import RestRecorder  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoClient  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="VN30", help="Chỉ số lấy rổ mã (mặc định VN30)")
    ap.add_argument("--interval", type=int, help="Số giây giữa 2 lần chụp (mặc định NEO_SNAPSHOT_SECONDS=60)")
    ap.add_argument("--cycles", type=int, help="Chỉ chạy N chu kỳ rồi dừng (để chạy thử)")
    args = ap.parse_args()

    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        tokens.get()  # hỏi tài khoản/mật khẩu một lần ở đầu; giữa phiên tự đăng nhập lại nếu token hết hạn
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")

    db_path = settings.db_path if Path(settings.db_path).is_absolute() else ROOT / settings.db_path
    rec = RestRecorder(NeoClient(settings, tokens), db_path=db_path, data_dir=ROOT / "data",
                       interval=args.interval or settings.snapshot_seconds, index_code=args.index,
                       symbols_file=ROOT / "data" / f"symbols_{args.index}.txt")
    stats = rec.run(max_cycles=args.cycles)

    print("\n===== Tóm tắt phiên =====")
    print(f"Ngày {stats.date}, {stats.started} -> {stats.finished}, lý do dừng: {stats.end_reason}")
    print(f"Số mã: {stats.symbols} | ảnh chụp gốc: {stats.raw_snapshots} | ảnh chụp phiên LO: {stats.lo_snapshots}")
    print(f"Dòng lưu vào Radar: {stats.rows_saved} | dòng bị loại: {stats.rows_dropped} | lỗi: {stats.errors}"
          f" | lần phải đoán phiên theo giờ: {stats.status_fallbacks}")
    print(f"Các trạng thái đã gặp: {' -> '.join(stats.statuses_seen) or '(không có)'}")
    print("Đã ghi tóm tắt vào data/sessions.csv")


if __name__ == "__main__":
    main()
