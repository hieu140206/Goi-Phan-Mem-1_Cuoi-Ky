"""Đưa dữ liệu lên bản web (Streamlit Community Cloud): xuất bản rút gọn ở máy bạn, giải nén khi web khởi động.

Bản web KHÔNG có bộ ghi (bộ ghi vẫn chạy ở laptop vì NEO yêu cầu IP đã đăng ký). Dữ liệu lên web theo đường: laptop chạy
`scripts/export_web_data.py` -> các tệp nén nằm ở data/web/ (commit và push) -> web khởi động gọi `ensure_web_data()` để giải nén.

- Bản rút gọn chỉ gồm các bảng dashboard đọc (không có ws_quotes, ws_trades) nên nhỏ hơn nhiều so với market.db.
- Chỉ ĐỌC market.db và candles.db gốc (mở chế độ chỉ đọc), chỉ ghi tệp mới trong data/web/.
- `ensure_web_data` KHÔNG BAO GIỜ ghi đè tệp dữ liệu có sẵn mà nó không tự giải nén: ở laptop (có market.db thật, không có dấu giải nén)
  nó không làm gì cả. Chỉ ở web, nơi chính nó đã giải nén lần trước (có dấu trong data/web/.unpacked.json), mới giải nén lại khi bản nén đổi.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "data" / "web"
MARKET_GZ, CANDLES_GZ, JSON_DIR, MARKER = "market_web.db.gz", "candles.db.gz", "market_json", ".unpacked.json"
# Các bảng dashboard đọc từ market.db (bảng ws_quotes, ws_trades chỉ để đối chiếu nên không đưa lên web).
WEB_TABLES = ("quotes", "market_index", "board", "depth_market", "futures", "ssi_daily", "ssi_index_daily", "ssi_quotes")


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)


def _gzip(src: Path, dst: Path) -> None:
    with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)


def export_web_data(market_db: Path, candles_db: Path | None, raw_dir: Path | None, out_dir: Path = WEB_DIR) -> dict[str, int]:
    """Tạo các tệp nén trong out_dir. Trả về {tên tệp: kích thước byte}. Không sửa market.db, candles.db, data/raw."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    made: dict[str, int] = {}
    tmp = out_dir / "_tmp_market.db"
    tmp.unlink(missing_ok=True)
    src = _ro(market_db)
    try:
        have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = [t for t in WEB_TABLES if t in have]
        ddl = [r[0] for t in tables for r in src.execute("SELECT sql FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL ORDER BY type DESC", (t,))]
    finally:
        src.close()
    dst = sqlite3.connect(f"file:{tmp.resolve().as_posix()}", uri=True)
    try:
        for s_ in ddl:
            dst.execute(s_)
        dst.execute("ATTACH DATABASE ? AS s", (f"file:{Path(market_db).resolve().as_posix()}?mode=ro",))
        for t in tables:
            dst.execute(f"INSERT INTO {t} SELECT * FROM s.{t}")
        dst.commit()
        dst.execute("DETACH DATABASE s")
        dst.execute("VACUUM")
    finally:
        dst.close()
    _gzip(tmp, out_dir / MARKET_GZ)
    tmp.unlink(missing_ok=True)
    made[MARKET_GZ] = (out_dir / MARKET_GZ).stat().st_size

    if candles_db and Path(candles_db).exists():
        tmpc = out_dir / "_tmp_candles.db"
        tmpc.unlink(missing_ok=True)
        s, d = _ro(candles_db), sqlite3.connect(tmpc)
        try:
            s.backup(d)                                    # bản sao nhất quán, kể cả khi đang có tiến trình ghi
        finally:
            d.close()
            s.close()
        _gzip(tmpc, out_dir / CANDLES_GZ)
        tmpc.unlink(missing_ok=True)
        made[CANDLES_GZ] = (out_dir / CANDLES_GZ).stat().st_size

    if raw_dir and Path(raw_dir).exists():                 # market.json từng ngày (chuỗi chỉ số theo phút, số cuối ngày) cho trang Tổng quan
        jd = out_dir / JSON_DIR
        jd.mkdir(exist_ok=True)
        for p in sorted(Path(raw_dir).glob("*/market.json")):
            shutil.copyfile(p, jd / f"{p.parent.name}.json")
        made[JSON_DIR] = sum(f.stat().st_size for f in jd.glob("*.json"))
    return made


def _sig(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unpack(gz: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    with gzip.open(gz, "rb") as f, open(part, "wb") as g:
        shutil.copyfileobj(f, g)
    os.replace(part, target)


def ensure_web_data(root: Path = ROOT, web_dir: Path | None = None) -> list[str]:
    """Giải nén dữ liệu web nếu cần. Trả về danh sách việc đã làm (rỗng nếu không làm gì).
    Không ghi đè tệp có sẵn mà chính hàm này chưa từng giải nén (bảo vệ market.db thật ở laptop)."""
    root = Path(root)
    web = Path(web_dir) if web_dir else root / "data" / "web"
    if not web.exists():
        return []
    mark_path = web / MARKER
    try:
        mark = json.loads(mark_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mark = {}
    done: list[str] = []
    for key, gz_name, target in (("market", MARKET_GZ, root / "data" / "market.db"), ("candles", CANDLES_GZ, root / "data" / "candles.db")):
        gz = web / gz_name
        if not gz.exists():
            continue
        sig = _sig(gz) if (not target.exists() or key in mark) else None
        if target.exists() and (key not in mark or mark[key] == sig):
            continue                                       # dữ liệu thật của bạn, hoặc bản đã giải nén còn mới: không đụng
        _unpack(gz, target)
        mark[key] = sig or _sig(gz)
        done.append(gz_name)
    jd = web / JSON_DIR
    if jd.exists():
        mine = set(mark.get("json", []))
        for p in sorted(jd.glob("*.json")):
            dest = root / "data" / "raw" / p.stem / "market.json"
            if dest.exists() and p.stem not in mine:
                continue                                   # tệp gốc của bộ ghi: không ghi đè
            if not dest.exists() or dest.read_bytes() != p.read_bytes():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest)
                mine.add(p.stem)
                done.append(f"{p.stem}/market.json")
        mark["json"] = sorted(mine)
    if done:
        mark_path.write_text(json.dumps(mark, ensure_ascii=False, indent=1), encoding="utf-8")
    return done
