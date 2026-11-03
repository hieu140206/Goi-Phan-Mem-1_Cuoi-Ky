"""Bộ ghi WebSocket THỬ NGHIỆM, chạy song song với bộ ghi REST để đối chiếu (không thay thế REST).

Ghi ba thứ, tất cả ở nơi riêng nên không đụng dữ liệu REST:
  1. bảng `ws_quotes` trong market.db: trạng thái sổ lệnh của từng mã VN30 cứ mỗi `interval` giây (mặc định 5), kèm
     n_msgs (số tin nhận được trong khoảng đó; 0 nghĩa là giữ lại trạng thái cũ) và age_ms (tin cuối cách mốc bao lâu);
  2. data/raw/<ngày>/ws.jsonl.gz: MỌI tin thô (base64) kèm giờ nhận, kể cả kênh chưa giải mã (marketInfo, marketVolume,
     marketSession) để sau này giải mã và kiểm tra lại;
  3. data/raw/<ngày>/ws_stats.json: thống kê chất lượng (số tin, số trường có giá trị mỗi tin, khoảng im lặng dài nhất,
     số lần kết nối lại) để biết mỗi tin là trạng thái ĐẦY ĐỦ hay chỉ phần thay đổi.

  4. bảng `ws_trades`: TỪNG LẦN KHỚP của kênh marketData (giá, khối lượng, số thứ tự, giờ sàn, lastColor B/S).

Giải mã (từ 2/11/2026): mỗi lần kết nối, bộ ghi gửi "sync" và máy chủ trả schema Avro của mọi kênh (đã chạy thật
2/11 bằng scripts/probe_ws_schema.py: 26 schema, giải mã đúng stockInfo, marketData, marketInfo, marketSession).
Có schema thì mọi tin được giải mã bằng schema (neo_api/avro_sync.py); chưa có (máy chủ không trả, hoặc thiếu
fastavro) thì quay về cách giải mã thủ công cũ cho stockInfo, nên không mất dữ liệu sổ lệnh.

Giả định đã có bằng chứng: tin stockInfo là trạng thái đầy đủ của mã (40/40 tin mẫu ngày 28/10 đều đủ 34/36 trường;
máy chủ còn có kênh riêng stockInfoOnlyChange cho phần thay đổi). Thời điểm của thanh sổ lệnh là GIỜ NHẬN của máy bạn
(stockInfo không kèm giờ); lần khớp marketData có giờ sàn chính xác tới giây. Chỉ ĐỌC dữ liệu, không gửi lệnh.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import gzip
import json
import logging
import threading
from collections import Counter
from pathlib import Path
from typing import Callable

import pandas as pd

from neo_api.avro_sync import build_sync_message, is_sync_frame, parse_schema_payload, schema_hash
from neo_api.binary_msg import is_stock_info, looks_binary, to_bytes
from neo_api.config import TZ
from neo_api.stream import AuthError, _authenticate, build_subscribe_message, connect_ws, map_record, parse_message

from .schema import QUOTE_COLUMNS, normalize_quotes
from .snapshot import in_trading_hours
from .storage import WS_TRADE_COLUMNS, save_ws_quotes, save_ws_trades

log = logging.getLogger(__name__)

END_TIME = dt.time(15, 2)
LUNCH_START, LUNCH_END = dt.time(11, 30), dt.time(13, 0)  # nghỉ trưa: không ghi thanh (tin thô vẫn lưu đủ)
INDEX_CODES = ["VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"]
MARKETS = ["HOSE", "HNX", "UPCOM", "FU"]
STALE_SECONDS = 900  # mã quá 15 phút không có tin thì không ghi tiếp trạng thái cũ


class WsBarRecorder:
    def __init__(self, db_path: Path, data_dir: Path, interval: int = 5,
                 now_fn: Callable[[], pd.Timestamp] | None = None) -> None:
        self.db_path, self.data_dir, self.interval = Path(db_path), Path(data_dir), max(int(interval), 1)
        self.now = now_fn or (lambda: pd.Timestamp.now(tz=TZ))
        self.state: dict[str, tuple[pd.Timestamp, dict]] = {}   # mã -> (giờ nhận tin cuối, trạng thái đầy đủ)
        self.n_msgs: Counter = Counter()                        # số tin trong mốc hiện tại, theo mã
        self.raw_buffer: list[str] = []
        self.last_slot: pd.Timestamp | None = None
        # Trạng thái đúng tại mốc: tin đầu tiên sau mốc mới (khi tick chưa kịp chạy) chụp lại state trước khi cập nhật,
        # để thanh mốc đó không lẫn tin đến sau mốc vài trăm mili giây (phát hiện khi đối chiếu REST phiên 3/11/2026).
        self.frozen: tuple[pd.Timestamp, dict, Counter] | None = None
        self.last_msg_time: pd.Timestamp | None = None
        self.longest_gap = 0.0
        self.reconnects = 0
        self.decoder = None                                      # AvroDecoder khi đã nhận schema từ máy chủ
        self.names: dict[int, str | None] = {}
        self.trades: list[dict] = []                             # lần khớp chờ ghi vào ws_trades
        self.stats: dict = {"messages": 0, "stock_info": 0, "other_by_type": Counter(), "decode_errors": 0,
                            "per_symbol": Counter(), "fields_filled_sum": 0, "fields_filled_min": None,
                            "fields_total": 0, "decode_mode": "thủ công", "schemas": 0,
                            "trades": 0, "trades_saved": 0, "trades_skipped": 0, "trades_per_symbol": Counter()}

    # ---------- schema ----------
    def on_sync(self, frame: bytes) -> str | None:
        """Xử lý tin sync (byte đầu 101). Trả tin xác nhận cần gửi lại máy chủ, hoặc None.

        Có schema thì chuyển sang giải mã bằng schema và lưu mô tả định dạng vào data/ws_schemas.json.
        Lỗi (thiếu fastavro, schema hỏng) chỉ ghi log: bộ ghi giữ cách giải mã thủ công."""
        payload = bytes(frame[1:])
        try:
            schemas = parse_schema_payload(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("WebSocket: không đọc được schema (%s), giữ cách giải mã thủ công", type(exc).__name__)
            return None
        if not schemas:
            return None  # máy chủ báo schema đang giữ đã mới nhất
        if not self.set_schemas(schemas):
            return None
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "ws_schemas.json").write_text(
                json.dumps({str(k): v for k, v in schemas.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        return build_sync_message(schema_hash(payload))

    def set_schemas(self, schemas: dict[int, dict]) -> bool:
        try:
            from neo_api.avro_sync import AvroDecoder  # noqa: PLC0415 - cần fastavro
            self.decoder = AvroDecoder(schemas)
        except Exception as exc:  # noqa: BLE001
            log.warning("WebSocket: không dùng được schema (%s). Cài: pip install fastavro", type(exc).__name__)
            return False
        self.names = {sid: (sch.get("name") if isinstance(sch, dict) else None) for sid, sch in schemas.items()}
        self.stats["decode_mode"], self.stats["schemas"] = "schema", len(schemas)
        log.info("WebSocket: đã nhận %d schema, giải mã mọi kênh bằng schema", len(schemas))
        return True

    # ---------- nhận tin ----------
    def on_raw(self, raw: str | bytes, now: pd.Timestamp | None = None) -> None:
        now = now or self.now()
        self._freeze_at_slot(now)
        b = to_bytes(raw)
        self.raw_buffer.append(json.dumps({"t": now.isoformat(), "b": base64.b64encode(b).decode()}))
        self.stats["messages"] += 1
        if self.last_msg_time is not None:
            self.longest_gap = max(self.longest_gap, (now - self.last_msg_time).total_seconds())
        self.last_msg_time = now
        if self.decoder is not None and b and b[0] in self.decoder.parsed:
            self._on_decoded(b, now)
            return
        if not (looks_binary(raw) and is_stock_info(raw)):
            from neo_api.binary_msg import decode
            try:
                self.stats["other_by_type"][decode(raw).type_name] += 1
            except Exception:  # noqa: BLE001
                self.stats["other_by_type"]["không đọc được"] += 1
            return
        try:
            rows = parse_message(raw)
        except Exception:  # noqa: BLE001
            self.stats["decode_errors"] += 1
            return
        for row in rows:
            self._update_state(row, now)

    def _update_state(self, row: dict, now: pd.Timestamp) -> None:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            return
        filled = sum(1 for v in row.values() if v is not None)
        s = self.stats
        s["stock_info"] += 1
        s["per_symbol"][sym] += 1
        s["fields_filled_sum"] += filled
        s["fields_total"] = len(row)
        s["fields_filled_min"] = filled if s["fields_filled_min"] is None else min(s["fields_filled_min"], filled)
        self.state[sym] = (now, dict(row))   # trạng thái đầy đủ: thay thế hoàn toàn
        self.n_msgs[sym] += 1

    def _on_decoded(self, b: bytes, now: pd.Timestamp) -> None:
        try:
            sid, _, rec = self.decoder.decode(bytes(b))
        except Exception:  # noqa: BLE001 - tin hỏng: đếm, không làm dừng bộ ghi
            self.stats["decode_errors"] += 1
            return
        name = self.names.get(sid) or f"id{sid}"
        if name == "stockInfo":
            self._update_state(map_record(rec), now)
        elif name == "marketData":
            self._add_trade(rec, now)
        else:
            self.stats["other_by_type"][name] += 1

    def _add_trade(self, rec: dict, now: pd.Timestamp) -> None:
        sym = str(rec.get("symbol") or "").strip().upper()
        try:
            seq = int(rec.get("sequenceMsg"))
            # Giây UTC: 2/11/2026 tin 1793603108 = 14:05:08 giờ VN, khớp indexTime 14:05:10 của marketInfo.
            ts = pd.Timestamp(int(rec.get("timestamp")), unit="s", tz="UTC").tz_convert(TZ)
        except (TypeError, ValueError):
            self.stats["trades_skipped"] += 1   # thiếu số thứ tự hoặc giờ: không ghi, không đoán
            return
        if not sym:
            self.stats["trades_skipped"] += 1
            return
        self.trades.append({"ts": ts, "recv_ts": now.isoformat(), "symbol": sym, "seq": seq,
                            "price": pd.to_numeric(rec.get("matchedPrice"), errors="coerce"),
                            "volume": pd.to_numeric(rec.get("tradingVolume"), errors="coerce"),
                            "side": rec.get("lastColor")})
        self.stats["trades"] += 1
        self.stats["trades_per_symbol"][sym] += 1

    def flush_trades(self) -> int:
        if not self.trades:
            return 0
        n = save_ws_trades(pd.DataFrame(self.trades, columns=WS_TRADE_COLUMNS), self.db_path)
        self.stats["trades_saved"] += n
        self.trades.clear()
        return n

    # ---------- chụp theo mốc ----------
    def slot(self, now: pd.Timestamp) -> pd.Timestamp:
        return now.floor(f"{self.interval}s")

    def _freeze_at_slot(self, now: pd.Timestamp) -> None:
        """Tin này thuộc mốc mới mà tick chưa ghi mốc đó: giữ bản sao trạng thái NGAY TRƯỚC mốc (một lần mỗi mốc)."""
        s = self.slot(now)
        if (self.last_slot is None or s > self.last_slot) and (self.frozen is None or self.frozen[0] != s):
            self.frozen = (s, dict(self.state), Counter(self.n_msgs))

    def tick(self, now: pd.Timestamp | None = None) -> int:
        """Gọi thường xuyên (mỗi giây). Sang mốc mới thì ghi một thanh cho mỗi mã đã có trạng thái. Trả về số dòng ghi.

        Thanh mang nhãn mốc `slot` chỉ chứa tin nhận TRƯỚC mốc: tick thường chạy trễ mốc tới ~1 giây, tin đến trong
        khoảng trễ đó thuộc thanh sau (dùng bản sao `frozen`)."""
        now = now or self.now()
        slot = self.slot(now)
        if self.last_slot is not None and slot <= self.last_slot:
            return 0
        self.last_slot = slot
        if self.frozen is not None and self.frozen[0] == slot:
            _, state, counts = self.frozen
            self.n_msgs = self.n_msgs - counts     # tin sau mốc được đếm cho thanh kế tiếp
        else:
            state, counts = self.state, self.n_msgs
            self.n_msgs = Counter()
        self.frozen = None
        self.flush_raw(now)
        self.flush_trades()  # lần khớp ghi cả ngoài phiên liên tục (ATO/ATC cũng là khớp thật); lọc khi phân tích
        if not in_trading_hours(now) or LUNCH_START <= slot.time() < LUNCH_END:
            return 0
        rows = []
        for sym, (seen, row) in state.items():
            age = (slot - seen).total_seconds()
            if age > STALE_SECONDS:
                continue
            rows.append({**row, "symbol": sym, "ts": slot, "n_msgs": counts.get(sym, 0),
                         "age_ms": max(age, 0) * 1000})
        if not rows:
            return 0
        clean, _ = normalize_quotes(pd.DataFrame(rows))
        # normalize_quotes chỉ giữ QUOTE_COLUMNS: ghép lại n_msgs, age_ms theo (ts, symbol)
        extra = pd.DataFrame(rows)[["symbol", "n_msgs", "age_ms"]].assign(symbol=lambda d: d["symbol"].str.upper())
        clean = clean.merge(extra, on="symbol", how="left")
        n = save_ws_quotes(clean, self.db_path)
        if slot.second == 0:
            self.write_stats(now)
        return n

    def day_dir(self, now: pd.Timestamp) -> Path:
        d = self.data_dir / "raw" / now.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def flush_raw(self, now: pd.Timestamp) -> None:
        if not self.raw_buffer:
            return
        with gzip.open(self.day_dir(now) / "ws.jsonl.gz", "at", encoding="utf-8") as fh:
            fh.write("\n".join(self.raw_buffer) + "\n")
        self.raw_buffer.clear()

    def write_stats(self, now: pd.Timestamp) -> None:
        s = self.stats
        n = max(s["stock_info"], 1)
        out = {"updated_at": now.isoformat(), "messages": s["messages"], "stock_info": s["stock_info"],
               "other_by_type": dict(s["other_by_type"]), "decode_errors": s["decode_errors"],
               "symbols_seen": len(s["per_symbol"]), "per_symbol": dict(s["per_symbol"]),
               "fields_per_message_avg": round(s["fields_filled_sum"] / n, 2), "fields_per_message_min": s["fields_filled_min"],
               "fields_per_message_total": s["fields_total"], "longest_gap_seconds": round(self.longest_gap, 1),
               "reconnects": self.reconnects, "interval_seconds": self.interval,
               "decode_mode": s["decode_mode"], "schemas": s["schemas"], "trades": s["trades"],
               "trades_saved": s["trades_saved"], "trades_skipped": s["trades_skipped"],
               "trades_per_symbol": dict(s["trades_per_symbol"])}
        (self.day_dir(now) / "ws_stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    def close(self) -> None:
        now = self.last_slot or self.last_msg_time or self.now()
        self.flush_raw(now)
        self.flush_trades()
        self.write_stats(now)


async def stream_forever(symbols: list[str], rec: WsBarRecorder, settings, token_provider: Callable[[], str],
                         stop: threading.Event | None = None) -> None:
    """Kết nối, xác thực, đăng ký kênh, nhận tin thô; mất kết nối thì thử lại với thời gian chờ tăng dần."""
    backoff = 1.0
    while not (stop and stop.is_set()) and rec.now().time() < END_TIME:
        try:
            async with connect_ws(settings.ws_url) as ws:
                await _authenticate(ws, token_provider())
                await ws.send(build_sync_message(""))   # xin schema; trả lời được xử lý trong vòng nhận tin
                await ws.send(build_subscribe_message(symbols, "stockInfo"))
                await ws.send(build_subscribe_message(symbols, "marketData"))
                await ws.send(build_subscribe_message(INDEX_CODES, "marketInfo"))
                await ws.send(build_subscribe_message(INDEX_CODES, "marketVolume"))
                await ws.send(build_subscribe_message(MARKETS, "marketSession"))
                log.info("WebSocket: đã đăng ký %d mã VN30 (sổ lệnh, từng lần khớp) và các kênh chỉ số, phiên",
                         len(symbols))
                backoff = 1.0
                async for raw in ws:
                    if is_sync_frame(raw):
                        ack = rec.on_sync(raw)
                        if ack:
                            await ws.send(ack)
                        continue
                    rec.on_raw(raw)
                    if stop and stop.is_set():
                        return
            # máy chủ đóng kết nối êm: cũng coi là mất kết nối, chờ rồi nối lại (tránh vòng lặp dồn dập)
            rec.reconnects += 1
            log.warning("WebSocket bị đóng, thử lại sau %.0f giây", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001 - mất mạng, đóng kết nối, ...
            rec.reconnects += 1
            log.warning("WebSocket mất kết nối (%s), thử lại sau %.0f giây", type(exc).__name__, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


async def ws_main(symbols: list[str], rec: WsBarRecorder, settings, token_provider: Callable[[], str],
                  stop: threading.Event | None = None) -> None:
    async def ticker() -> None:
        while not (stop and stop.is_set()) and rec.now().time() < END_TIME:
            await asyncio.sleep(0.5)
            try:
                n = rec.tick()
                if n and rec.last_slot is not None and rec.last_slot.second == 0:
                    log.info("WebSocket %s: %d mã, %d tin stockInfo, %d lần khớp (giải mã %s)",
                             rec.last_slot.strftime("%H:%M:%S"), n, rec.stats["stock_info"], rec.stats["trades"],
                             rec.stats["decode_mode"])
            except Exception as exc:  # noqa: BLE001
                log.warning("WebSocket: lỗi khi ghi thanh (%s): %s", type(exc).__name__, str(exc)[:100])

    reader = asyncio.ensure_future(stream_forever(symbols, rec, settings, token_provider, stop))
    tick = asyncio.ensure_future(ticker())
    try:
        await asyncio.wait({reader, tick}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (reader, tick):
            t.cancel()
        rec.close()


def start_ws_thread(symbols: list[str], db_path: Path, data_dir: Path, settings, token_provider: Callable[[], str],
                    interval: int = 5) -> tuple[threading.Thread, threading.Event]:
    """Chạy bộ ghi WebSocket trong một luồng nền để dùng chung đăng nhập với bộ ghi REST. Lỗi ở đây chỉ ghi log."""
    stop = threading.Event()
    rec = WsBarRecorder(db_path, data_dir, interval)

    def runner() -> None:
        try:
            asyncio.run(ws_main(symbols, rec, settings, token_provider, stop))
        except AuthError as exc:
            log.warning("WebSocket bị từ chối xác thực, dừng bộ ghi WebSocket (REST vẫn chạy): %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("Bộ ghi WebSocket dừng vì lỗi (%s): %s. REST vẫn chạy.", type(exc).__name__, str(exc)[:120])

    th = threading.Thread(target=runner, name="ws-recorder", daemon=True)
    th.start()
    return th, stop
