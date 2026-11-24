"""Bộ ghi sổ lệnh SSI qua WebSocket (nguồn PHỤ, chạy song song với bộ ghi NEO, không thay thế REST của NEO).

Ghi ba thứ, tất cả ở nơi riêng nên không đụng dữ liệu NEO:
  1. bảng `ssi_quotes` trong market.db: sổ lệnh 3 mức của từng mã VN30 cứ mỗi `interval` giây (mặc định 5), kèm n_msgs
     (số tin trong khoảng đó; 0 nghĩa là giữ lại trạng thái cũ), age_ms (tin cuối cách mốc bao lâu) và src_ts (giờ trong tin);
  2. data/raw/<ngày>/ssi.jsonl.gz: MỌI tin thô kèm giờ nhận, để phát lại và sửa lỗi sau này (đã cần với NEO);
  3. data/raw/<ngày>/ssi_stats.json: thống kê chất lượng (số tin, độ trễ so với giờ trong tin, khoảng im lặng dài nhất,
     số lần kết nối lại, thời gian sống của từng kết nối).

Định dạng tin đã thấy thật ngày 10/11/2026 (sau 09:18, VCB và 30 mã VN30 qua chủ đề quote.VN30@*):
  {"channel":"DATA","topic":"quote.VCB","data":{"s":"VCB","t":"2026/11/10 09:18:20",
   "bids":[["54100","75400"],["54000","16400"],["53900","12000"],["0","0"],...],"asks":[...]}}
  - Mỗi tin là sổ lệnh ĐẦY ĐỦ của mã (thay thế trạng thái cũ), 10 mức mỗi bên nhưng HOSE chỉ có 3 mức thật, các mức còn
    lại là ["0","0"] nên bị bỏ. Giá đơn vị đồng, khối lượng đơn vị cổ phiếu (giống NEO).
  - "t" là giờ sàn, độ chính xác tới giây, giờ Việt Nam. Một mã có thể có vài tin trong cùng một giây.
  - Tài liệu SSI nói bản sau có thể chỉ gửi giá trị thay đổi: stats["levels_seen"] đếm số mức có giá của từng tin để
    phát hiện sớm nếu định dạng đổi.
Thời điểm của thanh là mốc làm tròn xuống của GIỜ NHẬN trên máy bạn (như bộ ghi WebSocket NEO), tin nhận sau mốc thuộc thanh sau.

Kết nối: wss://stream.ssi.com.vn/ws/v3, token trong header Authorization (không để lên địa chỉ), token sống 15 phút và
chỉ cần hợp lệ lúc kết nối (SDK chính thức cũng làm mới trước khi nối lại). Mất kết nối, hoặc không có tin quá 60 giây
trong giờ khớp lệnh, thì nối lại bằng token mới và đăng ký lại. Chỉ ĐỌC dữ liệu, không gửi lệnh, không dùng Private Key.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import json
import logging
import threading
from collections import Counter
from pathlib import Path
from typing import Callable

import pandas as pd
import websockets

from neo_api.config import TZ

from .snapshot import in_trading_hours
from .ssi import STREAM_URL, SSI_QUOTE_COLUMNS, SsiClient, SsiError
from .storage import save_ssi_quotes

log = logging.getLogger(__name__)

END_TIME = dt.time(15, 2)
LUNCH_START, LUNCH_END = dt.time(11, 30), dt.time(13, 0)   # nghỉ trưa: không ghi thanh (tin thô vẫn lưu đủ)
WATCHDOG_END = dt.time(14, 45)                             # sau ATC không còn tin sổ lệnh đều đặn
STALE_SECONDS = 900          # mã quá 15 phút không có tin thì không ghi tiếp trạng thái cũ
WATCHDOG_STEP = 5.0          # giây mỗi lần chờ tin (để còn kiểm tra lệnh dừng)
WATCHDOG_SECONDS = 60.0      # trong giờ khớp lệnh, im lặng quá lâu = kết nối chết
LEVELS = 3                   # HOSE chỉ có 3 mức giá


def _px(v: object) -> object:
    """Giá một mức: chữ ATO/ATC giữ nguyên (bước làm sạch khi đọc sẽ loại), số <= 0 hoặc rỗng là mức trống (NaN)."""
    if isinstance(v, str) and v.strip().isalpha():
        return v.strip().upper()
    x = pd.to_numeric(v, errors="coerce")
    return float("nan") if pd.isna(x) or x <= 0 else float(x)


def _qty(v: object) -> float:
    x = pd.to_numeric(v, errors="coerce")
    return float("nan") if pd.isna(x) or x < 0 else float(x)


def parse_levels(levels: object) -> list[tuple[object, float]]:
    """[[giá, khối lượng], ...] -> đúng LEVELS mức đầu; mức thiếu hoặc ["0","0"] thành (NaN, NaN), không đoán."""
    out: list[tuple[object, float]] = []
    for i in range(LEVELS):
        lv = levels[i] if isinstance(levels, list) and i < len(levels) else None
        px = _px(lv[0]) if isinstance(lv, (list, tuple)) and len(lv) >= 2 else float("nan")
        qty = _qty(lv[1]) if isinstance(lv, (list, tuple)) and len(lv) >= 2 else float("nan")
        empty = pd.isna(px) if not isinstance(px, str) else False
        out.append((float("nan"), float("nan")) if empty else (px, qty))
    return out


def parse_src_time(t: object) -> pd.Timestamp | None:
    try:
        return pd.to_datetime(str(t), format="%Y/%m/%d %H:%M:%S").tz_localize(TZ)
    except (ValueError, TypeError):
        return None


class SsiBarRecorder:
    def __init__(self, db_path: Path, data_dir: Path, interval: int = 5,
                 now_fn: Callable[[], pd.Timestamp] | None = None) -> None:
        self.db_path, self.data_dir, self.interval = Path(db_path), Path(data_dir), max(int(interval), 1)
        self.now = now_fn or (lambda: pd.Timestamp.now(tz=TZ))
        # mã -> (giờ nhận tin cuối, dòng sổ lệnh đầy đủ, giờ trong tin dạng chuỗi ISO); chỉ thay cả bản ghi, không sửa tại chỗ
        self.state: dict[str, tuple[pd.Timestamp, dict, str | None]] = {}
        self.n_msgs: Counter = Counter()
        self.raw_buffer: list[str] = []
        self.last_slot: pd.Timestamp | None = None
        # Như WsBarRecorder: tin đầu tiên sau mốc mới (tick chưa kịp chạy) chụp lại trạng thái NGAY TRƯỚC mốc.
        self.frozen: tuple[pd.Timestamp, dict, Counter] | None = None
        self.last_msg_time: pd.Timestamp | None = None
        self.longest_gap = 0.0
        self.reconnects = 0
        self.conn_seconds: list[float] = []
        self.stats: dict = {"messages": 0, "quotes": 0, "other": Counter(), "parse_errors": 0, "watchdog": 0,
                            "per_symbol": Counter(), "levels_seen": Counter(), "lag_sum": 0.0, "lag_n": 0,
                            "lag_max": None, "lag_min": None}

    # ---------- nhận tin ----------
    def on_raw(self, raw: str | bytes, now: pd.Timestamp | None = None) -> str | None:
        """Xử lý một tin. Trả về tin cần gửi lại máy chủ (PONG khi máy chủ PING), hoặc None."""
        now = now or self.now()
        self._freeze_at_slot(now)
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        self.raw_buffer.append(json.dumps({"t": now.isoformat(), "m": text}, ensure_ascii=False, separators=(",", ":")))
        self.stats["messages"] += 1
        if self.last_msg_time is not None:
            self.longest_gap = max(self.longest_gap, (now - self.last_msg_time).total_seconds())
        self.last_msg_time = now
        try:
            msg = json.loads(text)
        except ValueError:
            self.stats["parse_errors"] += 1
            return None
        if not isinstance(msg, dict):
            self.stats["parse_errors"] += 1
            return None
        if msg.get("method") == "PING":
            self.stats["other"]["PING"] += 1
            return json.dumps({"method": "PONG", "channel": "HEARTBEAT", "time": msg.get("time")})
        data = msg.get("data")
        if msg.get("channel") == "DATA" and isinstance(data, dict) and "bids" in data:
            self._update_quote(data, now)
            return None
        kind = msg.get("method") or ("error:%s" % msg.get("code") if "code" in msg else msg.get("channel") or "khác")
        self.stats["other"][f"{kind}:{msg.get('status')}" if "status" in msg else str(kind)] += 1
        if "code" in msg and "msg" in msg:
            log.warning("SSI báo lỗi: %s %s", msg.get("code"), str(msg.get("msg"))[:100])
        return None

    def _update_quote(self, data: dict, now: pd.Timestamp) -> None:
        sym = str(data.get("s") or "").strip().upper()
        if not sym:
            self.stats["parse_errors"] += 1
            return
        bids, asks = parse_levels(data.get("bids")), parse_levels(data.get("asks"))
        row: dict = {}
        for i, ((bp, bq), (ap, aq)) in enumerate(zip(bids, asks), 1):
            row.update({f"bid_px{i}": bp, f"bid_qty{i}": bq, f"ask_px{i}": ap, f"ask_qty{i}": aq})
        src = parse_src_time(data.get("t"))
        if src is not None:
            lag = (now - src).total_seconds()
            s = self.stats
            s["lag_sum"] += lag
            s["lag_n"] += 1
            s["lag_max"] = lag if s["lag_max"] is None else max(s["lag_max"], lag)
            s["lag_min"] = lag if s["lag_min"] is None else min(s["lag_min"], lag)
        n_bid = sum(1 for p, _ in bids if not (isinstance(p, float) and pd.isna(p)))
        n_ask = sum(1 for p, _ in asks if not (isinstance(p, float) and pd.isna(p)))
        self.stats["levels_seen"][f"{n_bid}/{n_ask}"] += 1
        self.state[sym] = (now, row, src.isoformat() if src is not None else None)
        self.n_msgs[sym] += 1
        self.stats["quotes"] += 1
        self.stats["per_symbol"][sym] += 1

    # ---------- chụp theo mốc ----------
    def slot(self, now: pd.Timestamp) -> pd.Timestamp:
        return now.floor(f"{self.interval}s")

    def _freeze_at_slot(self, now: pd.Timestamp) -> None:
        s = self.slot(now)
        if (self.last_slot is None or s > self.last_slot) and (self.frozen is None or self.frozen[0] != s):
            self.frozen = (s, dict(self.state), Counter(self.n_msgs))

    @staticmethod
    def expects_data(now: pd.Timestamp) -> bool:
        """Đang trong giờ khớp lệnh liên tục, lúc này im lặng lâu nghĩa là kết nối có vấn đề."""
        t = now.time()
        return in_trading_hours(now) and not (LUNCH_START <= t < LUNCH_END) and t < WATCHDOG_END

    def tick(self, now: pd.Timestamp | None = None) -> int:
        """Gọi thường xuyên. Sang mốc mới thì ghi một thanh cho mỗi mã đã có trạng thái. Trả về số dòng ghi."""
        now = now or self.now()
        slot = self.slot(now)
        if self.last_slot is not None and slot <= self.last_slot:
            return 0
        self.last_slot = slot
        if self.frozen is not None and self.frozen[0] == slot:
            _, state, counts = self.frozen
            self.n_msgs = self.n_msgs - counts
        else:
            state, counts = self.state, self.n_msgs
            self.n_msgs = Counter()
        self.frozen = None
        self.flush_raw(now)
        if not in_trading_hours(now) or LUNCH_START <= slot.time() < LUNCH_END:
            return 0
        rows = []
        for sym, (seen, row, src) in state.items():
            age = (slot - seen).total_seconds()
            if age > STALE_SECONDS:
                continue
            rows.append({**row, "symbol": sym, "ts": slot, "n_msgs": counts.get(sym, 0),
                         "age_ms": max(age, 0) * 1000, "src_ts": src})
        if not rows:
            return 0
        n = save_ssi_quotes(pd.DataFrame(rows, columns=SSI_QUOTE_COLUMNS), self.db_path)
        if slot.second == 0:
            self.write_stats(now)
        return n

    # ---------- tệp ----------
    def day_dir(self, now: pd.Timestamp) -> Path:
        d = self.data_dir / "raw" / now.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def flush_raw(self, now: pd.Timestamp) -> None:
        if not self.raw_buffer:
            return
        with gzip.open(self.day_dir(now) / "ssi.jsonl.gz", "at", encoding="utf-8") as fh:
            fh.write("\n".join(self.raw_buffer) + "\n")
        self.raw_buffer.clear()

    def write_stats(self, now: pd.Timestamp) -> None:
        s = self.stats
        out = {"updated_at": now.isoformat(), "messages": s["messages"], "quotes": s["quotes"],
               "other": dict(s["other"]), "parse_errors": s["parse_errors"], "watchdog": s["watchdog"],
               "symbols_seen": len(s["per_symbol"]), "per_symbol": dict(s["per_symbol"]),
               "levels_seen": dict(s["levels_seen"]), "longest_gap_seconds": round(self.longest_gap, 1),
               "reconnects": self.reconnects, "connection_seconds": [round(x) for x in self.conn_seconds[-20:]],
               "lag_seconds_avg": round(s["lag_sum"] / s["lag_n"], 2) if s["lag_n"] else None,
               "lag_seconds_min": s["lag_min"], "lag_seconds_max": s["lag_max"], "interval_seconds": self.interval}
        (self.day_dir(now) / "ssi_stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    def close(self) -> None:
        now = self.last_slot or self.last_msg_time or self.now()
        self.flush_raw(now)
        self.write_stats(now)


# ---------------------------------------------------------------- kết nối
def _connect(token: str):
    """Mở kết nối luồng dữ liệu SSI; token nằm trong header, không để lên địa chỉ."""
    return websockets.connect(STREAM_URL, additional_headers={"Authorization": f"Bearer {token}"},
                              ping_interval=20, open_timeout=15)


def _status_of(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


async def stream_forever(rec: SsiBarRecorder, client: SsiClient, topics: list[str],
                         stop: threading.Event | None = None, sleep=asyncio.sleep) -> None:
    """Nối, đăng ký, nhận tin; mất kết nối hoặc im lặng quá lâu thì nối lại bằng token mới, chờ tăng dần."""
    backoff = 1.0
    while not (stop and stop.is_set()) and rec.now().time() < END_TIME:
        started = None
        try:
            token = await asyncio.to_thread(client.token)
            async with _connect(token) as ws:
                await ws.send(json.dumps({"method": "SUBSCRIBE", "channel": "DATA", "topics": topics}))
                log.info("SSI: đã nối và đăng ký %s", ", ".join(topics))
                started, silent = rec.now(), 0.0
                backoff = 1.0
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=WATCHDOG_STEP)
                    except asyncio.TimeoutError:
                        if stop and stop.is_set():
                            return
                        silent += WATCHDOG_STEP
                        if silent >= WATCHDOG_SECONDS and rec.expects_data(rec.now()):
                            rec.stats["watchdog"] += 1
                            raise ConnectionError("không có tin quá %.0f giây" % silent)
                        continue
                    silent = 0.0
                    reply = rec.on_raw(raw)
                    if reply:
                        await ws.send(reply)
                    if stop and stop.is_set():
                        return
        except SsiError as exc:
            rec.reconnects += 1
            log.warning("SSI: lỗi đăng nhập (%s), thử lại sau %.0f giây", exc, backoff)
        except Exception as exc:  # noqa: BLE001 - mất mạng, bị đóng kết nối, 429, ...
            rec.reconnects += 1
            status = _status_of(exc)
            if status in (401, 403):
                client.invalidate()           # token bị từ chối: lần sau làm mới hoặc đăng nhập lại
            if status == 429:
                backoff = max(backoff, 30.0)  # theo SDK chính thức: chờ ít nhất 30 giây
            log.warning("SSI mất kết nối (%s%s), thử lại sau %.0f giây", type(exc).__name__,
                        f" HTTP {status}" if status else "", backoff)
        else:
            rec.reconnects += 1
            log.warning("SSI bị đóng, thử lại sau %.0f giây", backoff)
        if started is not None:
            rec.conn_seconds.append((rec.now() - started).total_seconds())
        await sleep(backoff)
        backoff = min(backoff * 2, 60.0)


async def ssi_main(rec: SsiBarRecorder, client: SsiClient, topics: list[str], stop: threading.Event | None = None) -> None:
    async def ticker() -> None:
        while not (stop and stop.is_set()) and rec.now().time() < END_TIME:
            await asyncio.sleep(0.5)
            try:
                n = rec.tick()
                if n and rec.last_slot is not None and rec.last_slot.second == 0:
                    log.info("SSI %s: %d mã, %d tin sổ lệnh, %d lần nối lại", rec.last_slot.strftime("%H:%M:%S"), n,
                             rec.stats["quotes"], rec.reconnects)
            except Exception as exc:  # noqa: BLE001
                log.warning("SSI: lỗi khi ghi thanh (%s): %s", type(exc).__name__, str(exc)[:100])

    reader = asyncio.ensure_future(stream_forever(rec, client, topics, stop))
    tick = asyncio.ensure_future(ticker())
    try:
        await asyncio.wait({reader, tick}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (reader, tick):
            t.cancel()
        rec.close()


def start_ssi_thread(db_path: Path, data_dir: Path, topics: list[str], interval: int = 5,
                     client: SsiClient | None = None) -> tuple[threading.Thread, threading.Event]:
    """Chạy bộ ghi SSI trong luồng nền cùng bộ ghi NEO. Lỗi ở đây chỉ ghi log, không làm hỏng bộ ghi NEO."""
    stop = threading.Event()
    rec = SsiBarRecorder(db_path, data_dir, interval)
    cl = client or SsiClient()

    def runner() -> None:
        try:
            asyncio.run(ssi_main(rec, cl, topics, stop))
        except Exception as exc:  # noqa: BLE001
            log.warning("Bộ ghi SSI dừng vì lỗi (%s): %s. Bộ ghi NEO vẫn chạy.", type(exc).__name__, str(exc)[:120])

    th = threading.Thread(target=runner, name="ssi-recorder", daemon=True)
    th.start()
    return th, stop
