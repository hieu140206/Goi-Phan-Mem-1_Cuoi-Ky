"""Gộp dữ liệu từ thư mục ghi riêng vào dữ liệu chính của dự án. Chỉ THÊM, không xóa, chạy lại không bị trùng.

Nguyên tắc (dữ liệu NEO không có lịch sử, mất là không lấy lại được):
- Nguồn (bộ ghi) chỉ được ĐỌC. Đích được sao lưu trước khi ghi.
- Bảng chụp theo thời điểm: dòng trùng khóa thì giữ dòng đã có ở đích. Riêng `board` (mỗi mã mỗi ngày một ảnh chụp mới nhất): chỉ thay khi
  ảnh chụp của nguồn MỚI HƠN.
- Tệp gốc trong data/raw không bao giờ bị ghi đè: trùng tên mà khác nội dung thì chép sang tên mới để người dùng tự xem.
Không import streamlit (để kiểm thử được).
"""
from __future__ import annotations

import filecmp
import shutil
import sqlite3
from pathlib import Path

# Các bảng bộ ghi tạo ra -> biểu thức lấy ngày của một dòng. Bảng theo ngày của SSI (ssi_daily...) không do bộ ghi này viết nên không gộp.
DAY_EXPR = {
    "quotes": "substr(ts, 1, 10)",
    "market_index": "substr(ts, 1, 10)",
    "board": "day",
    "depth_market": "substr(ts, 1, 10)",
    "futures": "substr(ts, 1, 10)",
    "ws_quotes": "substr(ts, 1, 10)",
    "ws_trades": "day",
    "ssi_quotes": "substr(ts, 1, 10)",
}


class MergeError(RuntimeError):
    pass


def _ro_uri(path: Path) -> str:
    return f"file:{Path(path).resolve().as_posix()}?mode=ro"


def _tables(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {r[0] for r in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def day_counts(db: Path) -> dict[str, dict[str, int]]:
    """{bảng: {ngày: số dòng}} của các bảng bộ ghi tạo ra. Thiếu tệp: rỗng. Chỉ đọc."""
    if not Path(db).exists():
        return {}
    conn = sqlite3.connect(_ro_uri(db), uri=True)
    try:
        have = _tables(conn)
        return {t: dict(conn.execute(f"SELECT {e} AS d, COUNT(*) FROM {t} GROUP BY d")) for t, e in DAY_EXPR.items() if t in have}
    finally:
        conn.close()


def new_days(src_db: Path, dst_db: Path) -> list[str]:
    """Các ngày mà nguồn có NHIỀU dòng hơn đích ở ít nhất một bảng (ngày chưa gộp hoặc gộp chưa hết), tăng dần."""
    src, dst = day_counts(src_db), day_counts(dst_db)
    days = {d for t, per in src.items() for d, n in per.items() if d and n > dst.get(t, {}).get(d, 0)}
    return sorted(days)


def backup_db(db: Path, backup_dir: Path, stamp: str) -> Path:
    """Bản sao nhất quán của `db` (kể cả khi đang có tiến trình đọc) vào backup_dir. Không ghi đè bản sao đã có."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{Path(db).stem}_{stamp}.db"
    if target.exists():
        raise MergeError(f"Đã có bản sao lưu {target}, không ghi đè.")
    src, dst = sqlite3.connect(_ro_uri(db), uri=True), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def merge_days(src_db: Path, dst_db: Path, days: list[str]) -> dict[str, int]:
    """Gộp các dòng của `days` từ src_db vào dst_db trong MỘT giao dịch (lỗi giữa chừng thì không đổi gì). Trả {bảng: số dòng thêm hoặc thay}."""
    if not Path(src_db).exists() or not Path(dst_db).exists():
        raise MergeError("Thiếu tệp dữ liệu nguồn hoặc đích.")
    if Path(src_db).resolve() == Path(dst_db).resolve():
        raise MergeError("Nguồn và đích là cùng một tệp.")
    added: dict[str, int] = {}
    if not days:
        return added
    marks = ",".join("?" for _ in days)
    conn = sqlite3.connect(f"file:{Path(dst_db).resolve().as_posix()}", uri=True, timeout=60)
    try:
        conn.execute("ATTACH DATABASE ? AS s", (_ro_uri(src_db),))
        src_tables, dst_tables = _tables(conn, "s"), _tables(conn)
        with conn:
            for table, expr in DAY_EXPR.items():
                if table not in src_tables:
                    continue
                if table not in dst_tables:
                    ddl = conn.execute("SELECT sql FROM s.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
                    conn.execute(ddl)
                cols = _columns(conn, table, "s")
                missing = [c for c in cols if c not in _columns(conn, table)]
                if missing:
                    raise MergeError(f"Bảng {table} ở dữ liệu chính thiếu cột {missing}: dừng, không gộp để khỏi mất dữ liệu.")
                names = ", ".join(cols)
                picked = ", ".join(f"n.{c}" for c in cols)
                day = expr.replace("ts", "n.ts") if "ts" in expr else f"n.{expr}"
                before = conn.total_changes
                if table == "board":   # giữ ảnh chụp MỚI NHẤT của mỗi mã trong ngày
                    conn.execute(f"INSERT OR REPLACE INTO board ({names}) SELECT {picked} FROM s.board AS n WHERE {day} IN ({marks}) "
                                 "AND NOT EXISTS (SELECT 1 FROM board AS o WHERE o.day = n.day AND o.grp = n.grp AND o.symbol = n.symbol "
                                 "AND o.ts >= n.ts)", days)
                else:
                    conn.execute(f"INSERT OR IGNORE INTO {table} ({names}) SELECT {picked} FROM s.{table} AS n WHERE {day} IN ({marks})", days)
                added[table] = conn.total_changes - before
        conn.execute("DETACH DATABASE s")
    finally:
        conn.close()
    return added


def merge_raw(src_raw: Path, dst_raw: Path, days: list[str], tag: str) -> tuple[list[str], list[str]]:
    """Chép tệp gốc của `days`. Trả (đã chép, xung đột). Tệp đích khác nội dung KHÔNG bị ghi đè: bản của nguồn được chép thành `<tên>.<tag>`."""
    copied, conflicts = [], []
    for day in days:
        src_dir = Path(src_raw) / day
        if not src_dir.is_dir():
            continue
        out = Path(dst_raw) / day
        out.mkdir(parents=True, exist_ok=True)
        for f in sorted(p for p in src_dir.iterdir() if p.is_file()):
            target = out / f.name
            if target.exists():
                if filecmp.cmp(f, target, shallow=False):
                    continue
                target = out / f"{f.name}.{tag}"
                conflicts.append(f"{day}/{f.name} (bản mới lưu thành {target.name})")
                if target.exists():
                    continue
            shutil.copy2(f, target)
            copied.append(f"{day}/{target.name}")
    return copied, conflicts


def merge_sessions(src_csv: Path, dst_csv: Path, days: list[str]) -> int:
    """Thêm vào sessions.csv của đích các dòng tóm tắt phiên của `days` chưa có (so nguyên dòng). Trả số dòng thêm."""
    if not Path(src_csv).exists():
        return 0
    src = Path(src_csv).read_text(encoding="utf-8-sig").splitlines()
    if not src:
        return 0
    dst = Path(dst_csv).read_text(encoding="utf-8-sig").splitlines() if Path(dst_csv).exists() else []
    seen = set(dst)
    extra = [ln for ln in src[1:] if ln.split(",", 1)[0] in days and ln not in seen]
    if not extra:
        return 0
    if not dst:
        Path(dst_csv).write_text("\n".join([src[0], *extra]) + "\n", encoding="utf-8-sig")
    else:
        text = Path(dst_csv).read_bytes()
        with open(dst_csv, "a", encoding="utf-8", newline="") as fh:
            if text and not text.endswith(b"\n"):
                fh.write("\r\n")
            fh.write("".join(ln + "\r\n" for ln in extra))
    return len(extra)
