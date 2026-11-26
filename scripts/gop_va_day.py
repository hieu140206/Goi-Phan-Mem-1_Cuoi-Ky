"""Gộp dữ liệu vừa ghi ở thư mục ghi riêng vào dự án chính, cập nhật nến SSI, xuất dữ liệu web, HỎI rồi mới đẩy lên GitHub.

Chạy sau khi hai bộ ghi đã dừng (khoảng 15:05):  python scripts/gop_va_day.py

Mặc định: thư mục ghi là D:\\Pycharm\\ghi-du-lieu, dự án chính là D:\\Pycharm\\du-an-neo-api (cùng cấp). Việc nó làm:
  1. Tìm ngày mà thư mục ghi có dữ liệu nhiều hơn dự án chính.
  2. Sao lưu market.db chính vào <thư mục ghi>/sao-luu/, rồi gộp (chỉ thêm, không xóa, chạy lại không trùng), chép data/raw, sessions.csv.
  3. Nạp nến SSI mới vào candles.db chính (vài phút).
  4. Xuất data/web trong thư mục ghi.
  5. In số liệu kiểm tra và hỏi "Đẩy lên GitHub?". Chỉ đẩy khi bạn gõ c. Commit đẩy lên chỉ chứa data/web.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.merge import MergeError, backup_db, day_counts, merge_days, merge_raw, merge_sessions, new_days  # noqa: E402
from data.publish import PublishError, build_data_commit, push_commit  # noqa: E402
from data.web_data import export_web_data  # noqa: E402

VN = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_RECORDER = ROOT.parent / "ghi-du-lieu"
DEFAULT_MAIN = ROOT.parent / "du-an-neo-api"
FULL_QUOTES = 6000          # phiên đủ là 225 lần chụp x 30 mã = 6.750 dòng sổ lệnh; dưới mức này coi là thiếu
CLOSE_TIME = dt.time(15, 2)  # bộ ghi tự dừng quanh giờ này


def ask(question: str) -> bool:
    try:
        return input(f"{question} (c/k): ").strip().lower() in ("c", "co", "có", "y", "yes")
    except EOFError:
        return False


def report(counts: dict, days: list[str]) -> list[str]:
    """In số dòng từng bảng của các ngày vừa gộp; trả danh sách cảnh báo."""
    warnings = []
    for day in days:
        print(f"\n  Ngày {day}:")
        for table, per in counts.items():
            if per.get(day):
                print(f"    {table:13s} {per[day]:>9,} dòng".replace(",", "."))
        q = counts.get("quotes", {}).get(day, 0)
        if q < FULL_QUOTES:
            warnings.append(f"{day}: sổ lệnh NEO chỉ {q} dòng (phiên đủ khoảng 6750). Bộ ghi NEO có thể đã dừng giữa phiên.")
        if not counts.get("ssi_quotes", {}).get(day):
            warnings.append(f"{day}: không có dữ liệu SSI.")
    return warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ghi", type=Path, default=DEFAULT_RECORDER, help="thư mục ghi riêng")
    ap.add_argument("--chinh", type=Path, default=DEFAULT_MAIN, help="thư mục dự án chính")
    ap.add_argument("--bo-qua-nen", action="store_true", help="không nạp nến SSI")
    ap.add_argument("--khong-day", action="store_true", help="chỉ gộp và xuất, không hỏi đẩy")
    args = ap.parse_args(argv)

    rec, main_dir = args.ghi.resolve(), args.chinh.resolve()
    if rec == main_dir:
        sys.exit("Thư mục ghi và dự án chính không được trùng nhau.")
    src_db, dst_db = rec / "data" / "market.db", main_dir / "data" / "market.db"
    if not src_db.exists():
        sys.exit(f"Không thấy {src_db}.")
    if not dst_db.exists():
        sys.exit(f"Không thấy {dst_db}.")

    now = dt.datetime.now(VN)
    days = new_days(src_db, dst_db)
    if not days:
        print("Không có dữ liệu mới để gộp.")
    elif now.strftime("%Y-%m-%d") in days and now.time() < CLOSE_TIME:
        print(f"Bây giờ là {now:%H:%M}, bộ ghi hôm nay có thể CHƯA dừng.")
        if not ask("Vẫn gộp phần đã ghi tới lúc này?"):
            return 0

    if days:
        print(f"Ngày cần gộp: {', '.join(days)}")
        stamp = f"{now:%Y%m%d_%H%M%S}"
        print("Sao lưu market.db chính ...")
        saved = backup_db(dst_db, rec / "sao-luu", stamp)
        print(f"  {saved}")
        print("Gộp dữ liệu ...")
        added = merge_days(src_db, dst_db, days)
        print("  " + ", ".join(f"{t}: +{n}" for t, n in added.items() if n) if any(added.values()) else "  không thêm dòng nào")
        copied, conflicts = merge_raw(rec / "data" / "raw", main_dir / "data" / "raw", days, f"ghi-{stamp}")
        print(f"  tệp gốc đã chép: {len(copied)}")
        for c in conflicts:
            print(f"  LƯU Ý, không ghi đè: {c}")
        print(f"  dòng tóm tắt phiên thêm: {merge_sessions(rec / 'data' / 'sessions.csv', main_dir / 'data' / 'sessions.csv', days)}")

    candles = main_dir / "data" / "candles.db"
    if not args.bo_qua_nen:
        print("\nNạp nến SSI mới (vài phút; lỗi thì vẫn tiếp tục) ...")
        env = {**os.environ, "NEO_DB_PATH": str(dst_db)}
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_ssi_candles.py"), "--db", str(candles)], env=env, cwd=ROOT)
        if p.returncode != 0:
            print("LƯU Ý: nạp nến SSI lỗi, dùng nến đã có.")

    print("\nXuất dữ liệu web ...")
    for name, size in export_web_data(dst_db, candles, main_dir / "data" / "raw", rec / "data" / "web").items():
        print(f"  {name}: {size / 1e6:.1f} MB")

    warnings = report(day_counts(dst_db), days)
    big = [p.name for p in (rec / "data" / "web").glob("*.gz") if p.stat().st_size > 95e6]
    if big:
        sys.exit(f"Tệp {big} vượt 95 MB, GitHub sẽ từ chối. Không đẩy.")
    for w in warnings:
        print(f"  CẢNH BÁO: {w}")

    if args.khong_day:
        return 0
    if not ask("\nĐẩy dữ liệu web lên GitHub?" + (" (đang có cảnh báo ở trên)" if warnings else "")):
        print("Chưa đẩy. Dữ liệu đã gộp vào máy; chạy lại lệnh này khi muốn đẩy.")
        return 0
    message = f"Cập nhật dữ liệu web {now:%d/%m/%Y}" + (f" (ngày ghi mới: {', '.join(days)})" if days else "")
    for attempt in (1, 2):
        built = build_data_commit(rec, message)
        if built is None:
            print("Dữ liệu web trên GitHub đã mới nhất, không có gì để đẩy.")
            return 0
        commit, files = built
        try:
            push_commit(rec, commit)
            break
        except PublishError:
            if attempt == 2:
                raise
    print(f"Đã đẩy {len(files)} tệp data/web ({commit[:7]}). Trước khi push mã ở dự án chính, chạy: git pull --rebase")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (MergeError, PublishError) as exc:
        sys.exit(f"LỖI: {exc}")
