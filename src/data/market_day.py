"""Lấy bù chuỗi chỉ số trong ngày (4.2) và độ rộng cuối ngày (4.3) của MỘT phiên đã đóng cửa, ghi vào market.json.

NEO 4.2 vẫn trả chuỗi theo phút của phiên hiện tại sau giờ đóng cửa (dữ liệu thật 27/10/2026: 09:00:55 đến 15:05:05).
Mỗi điểm chỉ có giờ (HH:MM:SS), KHÔNG có ngày, nên chỉ được gọi khi chắc chắn đang trong cùng ngày giao dịch sau 14:45;
chạy sáng hôm sau có thể lấy nhầm dữ liệu ngày khác, vì vậy hàm từ chối.
Chỉ THÊM khóa còn thiếu vào market.json, không ghi đè dữ liệu bộ ghi đã lưu.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from .overview import trading_date

CODES = ("VN30", "VNINDEX", "HNXINDEX", "UPCOMINDEX")


class TooEarlyError(RuntimeError):
    pass


def fetch_day_extras(client, data_dir: Path, now: pd.Timestamp, codes=CODES) -> dict:
    """Trả về {'added': [các khóa mới], 'kept': [các khóa đã có], 'errors': {mã: loại lỗi}}."""
    day = trading_date(now)
    if now.date() != day or now.time() < dt.time(14, 45):
        raise TooEarlyError("Chỉ chạy được từ 14:45 trong ngày giao dịch (T2-T6) để chắc chắn dữ liệu là của hôm nay.")
    day_dir = Path(data_dir) / "raw" / day.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "market.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    res: dict = {"added": [], "kept": [], "errors": {}}

    def put(key: str, getter) -> None:
        if data.get(key):
            res["kept"].append(key)
            return
        try:
            data[key] = getter()
            res["added"].append(key)
        except Exception as exc:  # noqa: BLE001 - một mã lỗi không làm mất các mã khác
            res["errors"][key] = type(exc).__name__

    for code in codes:
        put(f"intraday_{code}", lambda c=code: client.get_index_intraday(c))
    put("index_detail", lambda: client.get_index_detail("ALL"))
    data.setdefault("saved_at", now.isoformat())
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return res


def save_close_snapshot(client, db_path: Path, data_dir: Path, now: pd.Timestamp, index_code: str = "VN30") -> dict:
    """Chốt số CUỐI NGÀY của phiên hôm nay (chạy từ 15:00): chỉ số 4.3, bảng giá VN30 (4.7), rồi bảng giá các sàn và phái sinh.
    Mỗi phần lỗi riêng không làm mất phần khác. Trả về {'indices': số dòng, 'vn30': số mã, 'groups': {nhóm: số mã}, 'errors': {...}}."""
    from .market import index_detail_frame
    from .market_board import board_frame
    from .rest_recorder import RestRecorder
    from .storage import load_board, save_board, save_market_index

    day = trading_date(now)
    if now.date() != day or now.time() < dt.time(15, 0):
        raise TooEarlyError("Chỉ chạy từ 15:00 trong ngày giao dịch (T2-T6), khi mọi sàn đã đóng cửa.")
    res: dict = {"indices": 0, "vn30": 0, "groups": {}, "errors": {}}
    ts = now.floor("s")
    try:
        res["indices"] = save_market_index(index_detail_frame(client.get_index_detail("ALL"), ts), db_path)
    except Exception as exc:  # noqa: BLE001
        res["errors"]["indices"] = type(exc).__name__
    try:
        records = client.get_stocks_by_index(index_code)
        res["vn30"] = save_board(board_frame(records, ts, index_code), db_path)
    except Exception as exc:  # noqa: BLE001
        res["errors"]["vn30"] = type(exc).__name__
    rec = RestRecorder(client, db_path=db_path, data_dir=data_dir, record_boards=True)
    rec.snapshot_extras(ts, "C")  # trạng thái "C" không phải LO nên không ghi thêm độ sâu theo phút
    for grp in ("HOSE", "HNX", "UPCOM", "ETF", "CW"):
        n = len(load_board(db_path, day.strftime("%Y-%m-%d"), grp))
        if n:
            res["groups"][grp] = n
    return res
