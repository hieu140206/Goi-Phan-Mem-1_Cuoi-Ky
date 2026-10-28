"""Bộ ghi dữ liệu sổ lệnh qua REST (NEO 4.7 stockDetailByIndex), dùng cho mỗi phiên giao dịch.

Vì sao dùng REST: định dạng 4.7 đã xác nhận bằng dữ liệu thật (JSON, 30 mã VN30 trong 1 lần gọi), còn tin
WebSocket là nhị phân chưa có schema. Mỗi chu kỳ (mặc định 60 giây) chỉ gọi 2 yêu cầu: 4.4 trạng thái phiên
và 4.7 sổ lệnh, rất xa giới hạn 5 yêu cầu/giây.

Mỗi chu kỳ:
  1. Hỏi 4.4 trạng thái HOSE. Nếu 4.4 lỗi thì dựa vào giờ (09:15-11:30, 13:00-14:30).
  2. Phiên ATO/LO/ATC: gọi 4.7, lưu phản hồi GỐC vào data/raw/<ngày>/stocks.jsonl.gz (bằng chứng, xử lý lại được).
  3. Chỉ phiên LO (khớp lệnh liên tục): làm sạch rồi lưu vào SQLite để Radar phân tích.
  4. Đã qua phiên LO mà trạng thái thành C (đóng cửa), hoặc quá 15:00: lấy chuỗi chỉ số trong ngày (4.2) và độ rộng
     thị trường (4.3), ghi tóm tắt phiên vào data/sessions.csv rồi dừng.
Thời điểm (ts) của mỗi ảnh chụp là mốc chu kỳ (ví dụ 10:42:00), giờ Việt Nam.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from neo_api.config import TZ
from neo_api.stream import map_record

from .schema import normalize_quotes
from .storage import save_quotes

log = logging.getLogger(__name__)

RAW_STATUSES = {"ATO", "LO", "ATC"}   # lưu phản hồi gốc
ANALYSIS_STATUSES = {"LO"}            # lưu vào SQLite cho Radar
END_TIME = dt.time(15, 0)
START_TIME = dt.time(8, 55)


def status_by_clock(now: pd.Timestamp) -> str:
    """Dự phòng khi 4.4 lỗi: suy ra phiên HOSE từ giờ."""
    t = now.time()
    if dt.time(9, 0) <= t < dt.time(9, 15):
        return "ATO"
    if dt.time(9, 15) <= t < dt.time(11, 30) or dt.time(13, 0) <= t < dt.time(14, 30):
        return "LO"
    if dt.time(14, 30) <= t < dt.time(14, 45):
        return "ATC"
    if dt.time(11, 30) <= t < dt.time(13, 0):
        return "BREAK"
    return "C" if t >= dt.time(14, 45) else "PRE"


@dataclass
class SessionStats:
    date: str
    started: str = ""
    finished: str = ""
    symbols: int = 0
    cycles: int = 0
    raw_snapshots: int = 0
    lo_snapshots: int = 0
    rows_saved: int = 0
    rows_dropped: int = 0
    errors: int = 0
    status_fallbacks: int = 0
    end_reason: str = ""
    statuses_seen: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        row = {k: v for k, v in self.__dict__.items() if k != "statuses_seen"}
        row["statuses_seen"] = "|".join(self.statuses_seen)
        return row


class RestRecorder:
    def __init__(self, client, db_path: Path, data_dir: Path, interval: int = 60, index_code: str = "VN30",
                 market: str = "HOSE", now_fn: Callable[[], pd.Timestamp] | None = None,
                 sleep_fn: Callable[[float], None] = time.sleep, symbols_file: Path | None = None) -> None:
        self.client = client
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.interval = max(int(interval), 5)
        self.index_code = index_code
        self.market = market
        self.now = now_fn or (lambda: pd.Timestamp.now(tz=TZ))
        self.sleep = sleep_fn
        self.symbols_file = symbols_file

    # ---------- các bước nhỏ ----------
    def market_status(self, now: pd.Timestamp, stats: SessionStats) -> str:
        try:
            rows = self.client.get_market_status(self.market)
            for r in rows:
                if str(r.get("marketCode", "")).upper() == self.market and r.get("marketStatus"):
                    return str(r["marketStatus"]).upper()
            raise ValueError("4.4 không có dòng cho " + self.market)
        except Exception as exc:  # noqa: BLE001 - mất mạng hay lỗi API đều không được làm dừng bộ ghi
            stats.status_fallbacks += 1
            fallback = status_by_clock(now)
            log.warning("Không lấy được trạng thái phiên (%s), dùng giờ: %s", type(exc).__name__, fallback)
            return fallback

    def slot(self, now: pd.Timestamp) -> pd.Timestamp:
        return now.floor(f"{self.interval}s")

    def wait_next_slot(self) -> None:
        now = self.now()
        nxt = self.slot(now) + pd.Timedelta(seconds=self.interval)
        self.sleep(max((nxt - now).total_seconds(), 0.5))

    def day_dir(self, now: pd.Timestamp) -> Path:
        d = self.data_dir / "raw" / now.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_symbols(self) -> list[str]:
        try:
            symbols = self.client.get_index_symbols(self.index_code)
            if symbols:
                return symbols
        except Exception as exc:  # noqa: BLE001
            log.warning("Không lấy được rổ %s từ NEO (%s)", self.index_code, type(exc).__name__)
        if self.symbols_file and self.symbols_file.exists():
            lines = self.symbols_file.read_text(encoding="utf-8").splitlines()
            return [s.strip().upper() for s in lines if s.strip() and not s.startswith("#")]
        return []

    def snapshot(self, slot: pd.Timestamp, status: str, stats: SessionStats) -> None:
        records = self.client.get_stocks_by_index(self.index_code)
        with gzip.open(self.day_dir(slot) / "stocks.jsonl.gz", "at", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": slot.isoformat(), "status": status, "records": records}, ensure_ascii=False) + "\n")
        stats.raw_snapshots += 1
        if status not in ANALYSIS_STATUSES:
            return
        raw = pd.DataFrame([map_record(r) for r in records]).assign(ts=slot)
        clean, report = normalize_quotes(raw)
        saved = save_quotes(clean, self.db_path)
        stats.lo_snapshots += 1
        stats.rows_saved += saved
        stats.rows_dropped += len(raw) - len(clean)
        log.info("%s [%s] lưu %d/%d mã", slot.strftime("%H:%M:%S"), status, saved, len(raw))

    def end_of_day(self, now: pd.Timestamp) -> None:
        """Lưu chuỗi chỉ số trong ngày (4.2) và độ rộng (4.3) cho trang Tổng quan."""
        out: dict[str, object] = {"saved_at": now.isoformat()}
        for code in (self.index_code, "VNINDEX"):
            try:
                out[f"intraday_{code}"] = self.client.get_index_intraday(code)
            except Exception as exc:  # noqa: BLE001
                out[f"intraday_{code}_error"] = type(exc).__name__
        try:
            out["index_detail"] = self.client.get_index_detail("ALL")
        except Exception as exc:  # noqa: BLE001
            out["index_detail_error"] = type(exc).__name__
        (self.day_dir(now) / "market.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    def write_summary(self, stats: SessionStats) -> Path:
        path = self.data_dir / "sessions.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = stats.as_row()
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
        return path

    # ---------- vòng chính ----------
    def run(self, max_cycles: int | None = None) -> SessionStats:
        now = self.now()
        stats = SessionStats(date=now.strftime("%Y-%m-%d"), started=now.strftime("%H:%M:%S"))
        if now.weekday() >= 5:
            stats.end_reason = "cuối tuần, không có phiên"
            return stats
        symbols = self.load_symbols()
        stats.symbols = len(symbols)
        if symbols and self.symbols_file:
            self.symbols_file.parent.mkdir(parents=True, exist_ok=True)
            self.symbols_file.write_text(f"# Rổ {self.index_code} ngày {stats.date}\n" + "\n".join(symbols) + "\n",
                                         encoding="utf-8")
        log.info("Rổ %s: %d mã. Bắt đầu ghi mỗi %d giây.", self.index_code, len(symbols), self.interval)

        seen_lo = False
        try:
            while True:
                now = self.now()
                if now.time() >= END_TIME:
                    stats.end_reason = "quá 15:00"
                    break
                status = self.market_status(now, stats)
                if not stats.statuses_seen or stats.statuses_seen[-1] != status:
                    stats.statuses_seen.append(status)
                    log.info("Trạng thái %s: %s", self.market, status)
                if status == "C" and (seen_lo or now.time() >= dt.time(14, 45)):
                    stats.end_reason = "đóng cửa (C)"
                    break
                if status in RAW_STATUSES:
                    seen_lo = seen_lo or status == "LO"
                    try:
                        self.snapshot(self.slot(now), status, stats)
                    except Exception as exc:  # noqa: BLE001
                        stats.errors += 1
                        log.warning("Lỗi khi chụp sổ lệnh (%s): %s", type(exc).__name__, str(exc)[:120])
                stats.cycles += 1
                if max_cycles is not None and stats.cycles >= max_cycles:
                    stats.end_reason = "đủ số chu kỳ"
                    break
                self.wait_next_slot()
        except KeyboardInterrupt:
            stats.end_reason = "dừng bằng Ctrl+C"
        now = self.now()
        stats.finished = now.strftime("%H:%M:%S")
        if seen_lo:
            self.end_of_day(now)
        self.write_summary(stats)
        return stats
