"""Một lệnh cho cả ngày: mở hai bộ ghi ở hai cửa sổ riêng, chờ hết phiên rồi gộp dữ liệu và hỏi đẩy lên GitHub.

Chạy khoảng 9:00, từ THƯ MỤC GHI RIÊNG (bản sao đóng băng, không phải thư mục đang sửa web):
  cd D:\\Pycharm\\ghi-du-lieu
  D:\\Pycharm\\du-an-neo-api\\.venv\\Scripts\\python.exe scripts\\ghi_hang_ngay.py

Cửa sổ NEO (REST + WebSocket, kèm dashboard ở cổng 8601): nhập tài khoản và mật khẩu NEO ở đó. Cửa sổ SSI tự chạy.
Đừng đóng ba cửa sổ này, đừng để máy ngủ. Khoảng 15:05 cửa sổ này tự chạy phần gộp (scripts/gop_va_day.py) và hỏi trước khi đẩy.
Muốn gộp sớm hoặc lỡ đóng cửa sổ này: chạy scripts/gop_va_day.py bất cứ lúc nào sau đó (bộ ghi không phụ thuộc cửa sổ này).
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gop_va_day  # noqa: E402

VN = ZoneInfo("Asia/Ho_Chi_Minh")
MERGE_AT = dt.time(15, 5)


def commands(port: int) -> list[list[str]]:
    """Hai bộ ghi: NEO (REST + WebSocket, kèm dashboard của thư mục ghi) và SSI."""
    py = sys.executable
    return [[py, str(ROOT / "scripts" / "run_live.py"), "--ws", "--port", str(port)], [py, str(ROOT / "scripts" / "record_ssi.py")]]


def open_window(cmd: list[str]) -> subprocess.Popen:
    """Mở cửa sổ PowerShell riêng chạy `cmd` và giữ cửa sổ lại sau khi chương trình dừng."""
    quoted = " ".join("'" + c.replace("'", "''") + "'" for c in cmd)
    return subprocess.Popen(["powershell", "-NoExit", "-NoProfile", "-Command", f"& {quoted}"], cwd=ROOT,
                            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8601, help="cổng dashboard của thư mục ghi (mặc định 8601)")
    args = ap.parse_args()
    if ROOT.resolve() == gop_va_day.DEFAULT_MAIN.resolve():
        sys.exit("Hãy chạy lệnh này từ thư mục ghi riêng (ví dụ D:\\Pycharm\\ghi-du-lieu), không phải thư mục dự án đang sửa.")
    for cmd in commands(args.port):
        open_window(cmd)
    print("Đã mở hai cửa sổ ghi. Nhập mật khẩu NEO ở cửa sổ NEO.")
    print(f"Cửa sổ này chờ tới {MERGE_AT:%H:%M} rồi gộp dữ liệu. Ctrl+C nếu muốn tự gộp sau.")
    try:
        while dt.datetime.now(VN).time() < MERGE_AT:
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nĐã thôi chờ. Hai cửa sổ ghi vẫn chạy.")
        return 0
    return gop_va_day.main(["--ghi", str(ROOT)])


if __name__ == "__main__":
    sys.exit(main())
