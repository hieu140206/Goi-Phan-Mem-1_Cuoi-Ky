"""Bộ ghi dữ liệu sổ lệnh qua REST (NEO 4.7 stockDetailByIndex), dùng cho mỗi phiên giao dịch.

Vì sao dùng REST: định dạng 4.7 đã xác nhận bằng dữ liệu thật (JSON, 30 mã VN30 trong 1 lần gọi), còn tin
WebSocket là nhị phân chưa có schema. Mỗi chu kỳ (mặc định 60 giây) chỉ gọi 2 yêu cầu: 4.4 trạng thái phiên
và 4.7 sổ lệnh, rất xa giới hạn 5 yêu cầu/giây.

Tùy chọn (run_live bật): vòng chỉ số 5 giây (4.3), bảng giá HOSE/HNX/UPCoM/ETF/CW (4.6), độ sâu theo sàn, hợp đồng VN30 (4.9).

Mỗi chu kỳ (ngoài ra mỗi lần chụp còn gọi 4.3 để lưu các chỉ số VNINDEX/VN30/HNX/UPCOM vào bảng market_index):
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

from .market import index_detail_frame
from .market_board import CHUNK, GROUPS, board_frame, depth_row, futures_frame
from .schema import normalize_quotes
from .storage import save_board, save_depth_market, save_futures, save_market_index, save_quotes

log = logging.getLogger(__name__)

RAW_STATUSES = {"ATO", "LO", "ATC"}   # lưu phản hồi gốc
ANALYSIS_STATUSES = {"LO"}            # lưu vào SQLite cho Radar
END_STATUSES = {"C", "PT", "PLO"}     # sau ATC: thỏa thuận / sau giờ / đóng cửa -> dừng ghi
# Trạng thái HOSE thấy trong dữ liệu thật 28/10/2026: ATO -> LO -> L (nghỉ trưa) -> LO -> ATC -> PT.
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
                 sleep_fn: Callable[[float], None] = time.sleep, symbols_file: Path | None = None,
                 fast_index_seconds: int | None = None, record_boards: bool = False) -> None:
        self.client = client
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.interval = max(int(interval), 5)
        self.index_code = index_code
        self.market = market
        self.now = now_fn or (lambda: pd.Timestamp.now(tz=TZ))
        self.sleep = sleep_fn
        self.symbols_file = symbols_file
        # Vòng chỉ số nhanh: giữa hai lần chụp sổ lệnh, cứ N giây hỏi 4.3 một lần (1 yêu cầu) để thẻ chỉ số nhảy nhanh.
        self.fast_interval = max(int(fast_index_seconds), 1) if fast_index_seconds else None
        self.record_boards = record_boards      # bảng giá HOSE/HNX/UPCoM/ETF/CW, độ sâu theo sàn, hợp đồng tương lai
        self._active = False                    # đang trong phiên có dữ liệu (ATO/LO/ATC) thì vòng nhanh mới chạy
        self._universe: dict[str, list[str]] | None = None
        self._fu_names: dict[str, str] = {}
        self._universe_tried: pd.Timestamp | None = None
        self._board_cycles = 0

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
        if not self.fast_interval:
            self.sleep(max((nxt - now).total_seconds(), 0.5))
            return
        while True:  # ngủ từng bước ngắn, mỗi bước hỏi chỉ số một lần, cho tới mốc chụp sổ lệnh kế tiếp
            now = self.now()
            if (nxt - now).total_seconds() <= 0.05:
                return
            step = min(now.floor(f"{self.fast_interval}s") + pd.Timedelta(seconds=self.fast_interval), nxt)
            self.sleep(max((step - now).total_seconds(), 0.2))
            now = self.now()
            if self._active and now < nxt - pd.Timedelta(seconds=0.5):
                self.poll_fast(now.floor(f"{self.fast_interval}s"))

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
        self.snapshot_indices(slot)
        self.save_live_board(records, slot)
        if status not in ANALYSIS_STATUSES:
            return
        raw = pd.DataFrame([map_record(r) for r in records]).assign(ts=slot)
        clean, report = normalize_quotes(raw)
        saved = save_quotes(clean, self.db_path)
        stats.lo_snapshots += 1
        stats.rows_saved += saved
        stats.rows_dropped += len(raw) - len(clean)
        log.info("%s [%s] lưu %d/%d mã", slot.strftime("%H:%M:%S"), status, saved, len(raw))

    # ---------- bảng giá toàn thị trường, độ sâu theo sàn, hợp đồng tương lai ----------
    def load_universe(self, now: pd.Timestamp) -> dict[str, list[str]]:
        """Danh sách mã từng nhóm (4.5): HOSE/HNX/UPCoM cổ phiếu, ETF và chứng quyền của HOSE. Lỗi thì thử lại sau 10 phút."""
        if self._universe is not None and (self._universe or (self._universe_tried is not None
                                           and (now - self._universe_tried).total_seconds() < 600)):
            return self._universe
        self._universe_tried = now
        uni: dict[str, list[str]] = {}
        try:
            for market in ("HOSE", "HNX", "UPCOM"):
                rows = self.client.get_stock_list(market)
                for grp, (mkt, typ) in GROUPS.items():
                    if mkt == market:
                        uni[grp] = sorted({str(r["symbol"]).strip().upper() for r in rows
                                           if r.get("symbol") and str(r.get("stockType", "")).upper() == typ})
            for r in self.client.get_stock_list("FU"):
                if str(r.get("stockType", "")).upper() == "FUVN30" and r.get("symbol"):
                    self._fu_names[str(r["symbol"]).strip().upper()] = str(r.get("otherName") or r["symbol"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Không lấy được danh sách mã (4.5): %s", type(exc).__name__)
            uni = {}
        self._universe = uni
        return uni

    def snapshot_board(self, slot: pd.Timestamp, status: str) -> None:
        """4.6 cho từng nhóm. Mỗi nhóm lỗi riêng không ảnh hưởng nhóm khác. Độ sâu theo sàn chỉ tính ở phiên LO."""
        uni = self.load_universe(slot)
        parts, raw = [], []
        for grp, (mkt, typ) in GROUPS.items():
            symbols = uni.get(grp) or []
            if not symbols:
                continue
            try:
                records: list[dict] = []
                for i in range(0, len(symbols), CHUNK):
                    records += self.client.get_stock_detail(symbols[i:i + CHUNK], market=mkt, stock_type=typ)
                frame = board_frame(records, slot, grp)
                save_board(frame, self.db_path)
                if status in ANALYSIS_STATUSES:
                    save_depth_market(depth_row(frame, slot, grp), self.db_path)
                parts.append(f"{grp} {len(frame)}/{len(symbols)}")
                raw.append({"grp": grp, "asked": len(symbols), "records": records})
            except Exception as exc:  # noqa: BLE001
                log.warning("Không lưu được bảng giá %s: %s %s", grp, type(exc).__name__, str(exc)[:80])
        if raw and self._board_cycles % 10 == 0:  # bằng chứng gốc: lần đầu rồi cứ 10 lần chụp một lần (file rất lớn nếu lưu hết)
            with gzip.open(self.day_dir(slot) / "board.jsonl.gz", "at", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": slot.isoformat(), "status": status, "groups": raw}, ensure_ascii=False) + "\n")
        self._board_cycles += 1
        if parts:
            log.info("%s bảng giá: %s", slot.strftime("%H:%M:%S"), " · ".join(parts))

    def snapshot_futures(self, slot: pd.Timestamp) -> None:
        records = self.client.get_fu_detail(None, "FUVN30")
        frame = futures_frame(records, slot, self._fu_names)
        with gzip.open(self.day_dir(slot) / "futures.jsonl.gz", "at", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": slot.isoformat(), "records": records}, ensure_ascii=False) + "\n")
        save_futures(frame, self.db_path)

    def snapshot_extras(self, slot: pd.Timestamp, status: str) -> None:
        """Phần mở rộng (bảng giá các sàn, phái sinh). Lỗi ở đây chỉ ghi log, không làm hỏng việc ghi sổ lệnh VN30."""
        if not self.record_boards:
            return
        try:
            self.snapshot_board(slot, status)
        except Exception as exc:  # noqa: BLE001
            log.warning("Lỗi bảng giá các sàn: %s", type(exc).__name__)
        try:
            self.snapshot_futures(slot)
        except Exception as exc:  # noqa: BLE001
            log.warning("Không lưu được phái sinh (4.9): %s", type(exc).__name__)

    def save_live_board(self, records: list[dict], ts: pd.Timestamp) -> None:
        """Bảng giá VN30 (nhóm "VN30" của bảng board, ghi đè) cho khối bảng giá tự làm mới ở dashboard.
        Lỗi ở đây chỉ ghi log: sổ lệnh phân tích đã lưu riêng vào bảng quotes."""
        if not self.record_boards:
            return
        try:
            save_board(board_frame(records, ts, self.index_code), self.db_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Không lưu được bảng giá %s: %s", self.index_code, type(exc).__name__)

    def poll_fast(self, ts: pd.Timestamp) -> None:
        """Vòng nhanh (mặc định 5 giây): chỉ số 4.3 và, nếu bật bảng giá, sổ lệnh VN30 4.7 để bảng giá hiển thị nhảy theo.
        Phần 4.7 chỉ để HIỂN THỊ (ghi đè bảng board); dữ liệu phân tích vẫn là ảnh chụp mỗi phút trong bảng quotes."""
        self.snapshot_indices(ts)
        if self.record_boards:
            try:
                self.save_live_board(self.client.get_stocks_by_index(self.index_code), ts)
            except Exception as exc:  # noqa: BLE001
                log.warning("Không lấy được bảng giá nhanh %s: %s", self.index_code, type(exc).__name__)

    def snapshot_indices(self, slot: pd.Timestamp) -> None:
        """4.3: điểm, thay đổi, độ rộng, giá trị giao dịch lũy kế của các chỉ số, cho trang Tổng quan.
        Lỗi ở bước này không được làm mất ảnh chụp sổ lệnh nên chỉ ghi log."""
        try:
            save_market_index(index_detail_frame(self.client.get_index_detail("ALL"), slot), self.db_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Không lưu được chỉ số (4.3): %s", type(exc).__name__)

    def finalize_close(self, until: dt.time = dt.time(15, 2), step: int = 30) -> None:
        """Sau khi HOSE hết phiên khớp lệnh (14:45), chỉ số vẫn đổi: giá đóng cửa ATC được chốt, HNX/UPCoM còn khớp tới 15:00,
        giao dịch thỏa thuận cộng vào khối lượng và giá trị. Hỏi 4.3 mỗi 30 giây tới 15:02 để thẻ chỉ số cuối ngày
        khớp với các bảng giá chính thức (không có bước này, ngày 29/10 thẻ chỉ số dừng ở 14:44, lệch VN-Index 2 điểm).
        Cũng làm mới các bảng giá: ngày 30/10 bảng dừng ở 14:44 nên tổng khối lượng thiếu đúng khối lượng khớp ATC của từng mã."""
        log.info("Hết phiên khớp lệnh. Chờ giá đóng cửa chính thức và giao dịch thỏa thuận tới %s...", until.strftime("%H:%M"))
        while True:
            now = self.now()
            slot = now.floor("5s")
            self.poll_fast(slot)  # chỉ số + bảng giá VN30 (tổng khối lượng đã cộng kết quả ATC)
            self.snapshot_extras(slot, "PT")  # bảng giá HOSE/HNX/UPCoM/ETF/CW + phái sinh; không ghi độ sâu (không phải phiên LO)
            if now.time() >= until:
                return
            self.sleep(step)

    def end_of_day(self, now: pd.Timestamp) -> None:
        """Lưu chuỗi chỉ số trong ngày (4.2) và độ rộng (4.3) cho trang Tổng quan."""
        out: dict[str, object] = {"saved_at": now.isoformat()}
        for code in dict.fromkeys((self.index_code, "VNINDEX", "HNXINDEX", "UPCOMINDEX")):  # bỏ trùng, giữ thứ tự
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
                # Dữ liệu thật 28/10/2026: sau ATC, HOSE chuyển sang "PT" (thỏa thuận) chứ không phải "C" ngay.
                if status in END_STATUSES and (seen_lo or now.time() >= dt.time(14, 45)):
                    stats.end_reason = f"hết phiên khớp lệnh ({status})"
                    break
                self._active = status in RAW_STATUSES
                if status in RAW_STATUSES:
                    seen_lo = seen_lo or status == "LO"
                    try:
                        self.snapshot(self.slot(now), status, stats)
                    except Exception as exc:  # noqa: BLE001
                        stats.errors += 1
                        log.warning("Lỗi khi chụp sổ lệnh (%s): %s", type(exc).__name__, str(exc)[:120])
                    self.snapshot_extras(self.slot(now), status)
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
            if stats.end_reason.startswith("hết phiên khớp lệnh") and now.time() < dt.time(15, 2):
                try:
                    self.finalize_close()
                except KeyboardInterrupt:
                    pass
                now = self.now()
            self.end_of_day(now)
        if stats.raw_snapshots or stats.errors:  # chạy ngoài giờ (chưa chụp lần nào, không lỗi) thì không ghi dòng rỗng
            self.write_summary(stats)
        return stats
