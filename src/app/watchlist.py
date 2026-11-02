"""Danh sách mã theo dõi của người dùng, lưu ở data/watchlist.json để không mất khi tải lại trang.

Đây là tùy chọn hiển thị của người dùng, không phải dữ liệu thị trường (dashboard vẫn chỉ ĐỌC market.db).
File thiếu, hỏng hoặc sai kiểu thì coi như danh sách rỗng; không bao giờ làm hỏng trang.
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_SYMBOLS = 30


def _clean(symbols) -> list[str]:
    """Chuẩn hóa: chữ hoa, bỏ khoảng trắng, bỏ trùng (giữ thứ tự), bỏ mục không phải chữ."""
    out: list[str] = []
    for s in symbols if isinstance(symbols, list) else []:
        if isinstance(s, str):
            sym = s.strip().upper()
            if sym and sym.isalnum() and sym not in out:
                out.append(sym)
    return out[:MAX_SYMBOLS]


def load_watchlist(path: Path) -> list[str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return _clean(data.get("symbols") if isinstance(data, dict) else data)


def save_watchlist(path: Path, symbols: list[str]) -> list[str]:
    """Ghi danh sách (đã chuẩn hóa) và trả lại nó. Lỗi ghi file thì bỏ qua: danh sách chỉ không được lưu."""
    clean = _clean(list(symbols))
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"symbols": clean}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return clean


def toggle(path: Path, symbol: str) -> list[str]:
    """Thêm mã nếu chưa có, bỏ nếu đã có."""
    cur = load_watchlist(path)
    sym = symbol.strip().upper()
    return save_watchlist(path, [s for s in cur if s != sym] if sym in cur else cur + [sym])
