"""Chạy MỘT LỆNH: vừa ghi sổ lệnh VN30 từ NEO, vừa mở dashboard tự cập nhật (chế độ "Trực tiếp").

Chạy trong thư mục gốc dự án, đã kích hoạt .venv, khoảng 9:05 mỗi ngày giao dịch:
  python scripts/run_live.py

Việc nó làm:
  1. Đăng nhập NEO một lần (hỏi tài khoản và mật khẩu; mật khẩu không hiển thị, không lưu ra đĩa).
  2. Mở dashboard Streamlit ở chế độ "Trực tiếp" (tự đọc lại dữ liệu khi có bản ghi mới).
  3. Chạy bộ ghi (giống scripts/record_rest.py): mỗi phút lấy sổ lệnh 3 mức của rổ VN30 rồi ghi vào data/market.db.
  4. Bộ ghi tự dừng khi hết phiên (khoảng 15:02, sau khi chốt số cuối ngày). Dashboard vẫn mở để xem lại; bấm Ctrl+C để tắt hẳn.

Bộ ghi và dashboard là hai phần riêng: dashboard chỉ ĐỌC market.db, nên đóng tab trình duyệt hay dashboard lỗi
không làm mất dữ liệu phiên. Dữ liệu "trực tiếp" trễ tối đa khoảng 1 phút (bộ ghi chụp mỗi phút).
Chỉ ĐỌC dữ liệu thị trường, không đặt, sửa hay hủy lệnh.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.rest_recorder import RestRecorder  # noqa: E402
from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoClient  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

APP = ROOT / "src" / "app" / "app.py"


def dashboard_command(port: int, open_browser: bool = True) -> list[str]:
    cmd = [sys.executable, "-m", "streamlit", "run", str(APP), "--server.port", str(port),
           "--browser.gatherUsageStats", "false"]
    if not open_browser:
        cmd += ["--server.headless", "true"]
    return cmd


def start_dashboard(port: int, open_browser: bool = True) -> subprocess.Popen:
    env = {**os.environ, "NEO_LIVE": "1"}  # app.py đọc biến này để bật sẵn công tắc "Trực tiếp"
    return subprocess.Popen(dashboard_command(port, open_browser), cwd=ROOT, env=env)


def stop_process(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="VN30", help="Chỉ số lấy rổ mã (mặc định VN30)")
    ap.add_argument("--interval", type=int, help="Số giây giữa 2 lần chụp (mặc định NEO_SNAPSHOT_SECONDS=60)")
    ap.add_argument("--fast", type=int, default=5, help="Giây giữa hai lần hỏi chỉ số cho thẻ chỉ số (mặc định 5; 0 = tắt)")
    ap.add_argument("--no-boards", action="store_true", help="Không ghi bảng giá HOSE/HNX/UPCoM/ETF/CW và phái sinh")
    ap.add_argument("--ws", action="store_true",
                    help="Ghi THÊM sổ lệnh qua WebSocket (bảng ws_quotes, thanh 5 giây) để đối chiếu với REST. Thử nghiệm")
    ap.add_argument("--ws-interval", type=int, default=5, help="Giây mỗi thanh WebSocket (mặc định 5)")
    ap.add_argument("--port", type=int, default=8501, help="Cổng dashboard (mặc định 8501)")
    ap.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    settings = get_settings()
    tokens = TokenManager(settings)
    try:
        tokens.get()  # đăng nhập ở đây, trước khi mở gì, để lỗi mật khẩu hiện ngay và dừng sớm
    except LoginError as exc:
        sys.exit(f"Đăng nhập thất bại: {exc}")

    db_path = settings.db_path if Path(settings.db_path).is_absolute() else ROOT / settings.db_path
    rec = RestRecorder(NeoClient(settings, tokens), db_path=db_path, data_dir=ROOT / "data",
                       interval=args.interval or settings.snapshot_seconds, index_code=args.index,
                       symbols_file=ROOT / "data" / f"symbols_{args.index}.txt",
                       fast_index_seconds=args.fast, record_boards=not args.no_boards)

    ws_thread = ws_stop = None
    if args.ws:
        from data.ws_recorder import start_ws_thread  # noqa: PLC0415
        try:
            symbols = rec.load_symbols()
            ws_thread, ws_stop = start_ws_thread(symbols, db_path, ROOT / "data", settings, tokens.get, args.ws_interval)
            print(f"Đã bật bộ ghi WebSocket thử nghiệm ({len(symbols)} mã, thanh {args.ws_interval} giây).")
        except Exception as exc:  # noqa: BLE001 - WebSocket lỗi không được làm hỏng bộ ghi REST
            print(f"Không bật được WebSocket ({type(exc).__name__}); REST vẫn chạy bình thường.")

    dash = start_dashboard(args.port, open_browser=not args.no_browser)
    print(f"\nDashboard: http://localhost:{args.port}  (đang bật chế độ Trực tiếp)")
    print("Bộ ghi đang chạy. Bấm Ctrl+C để dừng cả hai.\n")
    try:
        stats = rec.run()
        print("\n===== Bộ ghi đã dừng =====")
        print(f"Ngày {stats.date}, {stats.started} -> {stats.finished}, lý do dừng: {stats.end_reason}")
        print(f"Số mã: {stats.symbols} | ảnh chụp phiên LO: {stats.lo_snapshots} | dòng lưu: {stats.rows_saved}"
              f" | lỗi: {stats.errors}")
        print("Đã ghi tóm tắt vào data/sessions.csv.")
        if "Ctrl+C" not in stats.end_reason:  # bộ ghi tự hết phiên: giữ dashboard mở để xem lại
            print("Dashboard vẫn mở để xem lại; bấm Ctrl+C để tắt.")
            dash.wait()
    except KeyboardInterrupt:
        print("\nĐang tắt...")
    finally:
        if ws_stop is not None:
            ws_stop.set()
            ws_thread.join(timeout=5)
        stop_process(dash)


if __name__ == "__main__":
    main()
