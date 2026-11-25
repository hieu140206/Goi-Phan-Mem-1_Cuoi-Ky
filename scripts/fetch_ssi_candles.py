"""Nạp nến OHLC từ SSI vào tệp riêng data/candles.db (không đụng market.db). Chỉ ĐỌC từ SSI, không đặt lệnh. Chạy được mọi lúc.

Chạy (kích hoạt .venv trước):
  python scripts/fetch_ssi_candles.py --limit 30            # ĐO tốc độ: 30 mã đầu, in thời gian và số lần gọi, rồi ước tính cho cả danh sách
  python scripts/fetch_ssi_candles.py                       # nến ngày cho mọi cổ phiếu và ETF trong bảng giá + nến trong phiên cho VN30
  python scripts/fetch_ssi_candles.py --symbols VNM,FPT --frames 1d,5m
  python scripts/fetch_ssi_candles.py --stats               # xem tệp đang có gì (không gọi mạng)

Nến ngày nạp lại cả chuỗi mỗi lần (SSI điều chỉnh giá cũ khi chia cổ tức); nến trong phiên chỉ lấy phần mới rồi cộng dồn.
Danh sách mã lấy từ bảng board của market.db (chỉ đọc), bỏ chứng quyền và phái sinh. Cần SSI_API_KEY và SSI_API_SECRET trong .env.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.candle_store import DEFAULT_PATH, last_ts, save_candles  # noqa: E402
from data.ssi import SsiClient, SsiError, fetch_ohlc  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

DAILY_DAYS = 400                      # nến ngày: lấy về tối đa chừng này ngày lịch (SSI trả khoảng 1 năm)
INTRADAY_DAYS = 400                   # nến trong phiên lần đầu: xin rộng, SSI trả những gì còn giữ
INTRADAY_FRAMES = ("1h", "15m", "5m")


class Timed(SsiClient):
    """Đếm số lần gọi và đo thời gian từng lần (không ghi token)."""
    def __init__(self) -> None:
        super().__init__()
        self.calls, self.secs, self.slowest = 0, 0.0, 0.0

    def get(self, path, params):
        t0 = time.perf_counter()
        try:
            return super().get(path, params)
        finally:
            dt_ = time.perf_counter() - t0
            self.calls += 1
            self.secs += dt_
            self.slowest = max(self.slowest, dt_)


class Count429(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.n = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "429" in record.getMessage():
            self.n += 1


def market_db() -> Path:
    p = Path(get_settings().db_path)
    return p if p.is_absolute() else ROOT / p


def board_symbols(db: Path) -> tuple[list[str], list[str]]:
    """(mọi cổ phiếu và ETF, mã VN30) từ ngày mới nhất trong bảng board. Chỉ đọc."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        day = conn.execute("SELECT MAX(day) FROM board").fetchone()[0]
        rows = conn.execute("SELECT grp, symbol FROM board WHERE day = ? AND grp IN ('VN30','HOSE','HNX','UPCOM','ETF')", (day,)).fetchall()
    finally:
        conn.close()
    vn30 = sorted({s for g, s in rows if g == "VN30"})
    return sorted({s for _, s in rows}), vn30


def stats(path: Path) -> None:
    if not path.exists():
        print(f"Chưa có {path}")
        return
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        for r in conn.execute("SELECT frame, COUNT(DISTINCT symbol), SUM(rows), MIN(first_ts), MAX(last_ts), MAX(fetched_at) FROM candle_meta GROUP BY frame"):
            print(f"  khung {r[0]}: {r[1]} mã, {r[2]} nến, từ {r[3]} đến {r[4]}, nạp lần cuối {r[5]}")
    finally:
        conn.close()
    print(f"  dung lượng tệp: {path.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=0, help="chỉ lấy N mã đầu (để đo tốc độ)")
    ap.add_argument("--symbols", default="", help="danh sách mã cách nhau bằng dấu phẩy (thay cho danh sách từ bảng board)")
    ap.add_argument("--frames", default="1d,1h,15m,5m", help="các khung nến (mặc định: 1d cho mọi mã; 1h,15m,5m chỉ cho VN30)")
    ap.add_argument("--stats", action="store_true", help="xem nội dung tệp candles.db, không gọi mạng")
    ap.add_argument("--db", default=str(DEFAULT_PATH))
    a = ap.parse_args()
    out = Path(a.db)
    if a.stats:
        stats(out)
        return
    frames = [f.strip() for f in a.frames.split(",") if f.strip()]
    if a.symbols:
        everyone = vn30 = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    else:
        everyone, vn30 = board_symbols(market_db())
    if a.limit:
        everyone, vn30 = everyone[:a.limit], vn30[:a.limit]
    plan = [(f, everyone if f == "1d" else vn30) for f in frames]
    print("Kế hoạch: " + "; ".join(f"{f}: {len(s)} mã" for f, s in plan) + f" -> {out}")

    h = Count429()
    logging.getLogger("data.ssi").addHandler(h)
    client = Timed()
    today = dt.date.today()
    fetched_at = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").isoformat(timespec="seconds")
    saved = fails = 0
    per_frame: dict[str, tuple[int, int]] = {}      # khung -> (số lần gọi, số mã)
    t_all = time.perf_counter()
    for frame, syms in plan:
        t0, c0 = time.perf_counter(), client.calls
        for i, sym in enumerate(syms, 1):
            frm = today - dt.timedelta(days=DAILY_DAYS if frame == "1d" else INTRADAY_DAYS)
            if frame != "1d":                                           # nến trong phiên: chỉ lấy phần mới (lùi 1 ngày cho chắc)
                prev = last_ts(out, frame, sym)
                if prev is not None:
                    frm = max(frm, prev.date() - dt.timedelta(days=1))
            try:
                df = fetch_ohlc(client, sym, frm.strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d"), frame, max_pages=30)
            except (SsiError, ValueError) as exc:
                fails += 1
                print(f"  [{frame} {i}/{len(syms)}] {sym}: LỖI {type(exc).__name__}: {exc}")
                continue
            saved += save_candles(out, frame, sym, df, fetched_at, replace=(frame == "1d"))
            if i % 10 == 0 or i == len(syms):
                print(f"  [{frame} {i}/{len(syms)}] {sym}: {len(df)} nến")
        n, sec = client.calls - c0, time.perf_counter() - t0
        per_frame[frame] = (n, len(syms))
        print(f"Khung {frame}: {len(syms)} mã, {n} lần gọi, {sec:.0f} giây ({sec / max(n, 1):.2f} giây/lần gọi)")
    total = time.perf_counter() - t_all
    print(f"\nXong: {saved} nến ghi, {fails} mã lỗi, {client.calls} lần gọi trong {total:.0f} giây "
          f"({client.calls / max(total, 1) * 60:.0f} lần/phút), lần chậm nhất {client.slowest:.1f} giây, bị 429 {h.n} lần.")
    if a.limit:
        full_e, full_v = board_symbols(market_db())
        rate = client.calls / max(total, 1)                      # lần gọi mỗi giây đo được
        est = sum(n / max(m, 1) * (len(full_e) if f == "1d" else len(full_v)) for f, (n, m) in per_frame.items())
        print(f"Ước tính cho cả danh sách ({len(full_e)} mã nến ngày, {len(full_v)} mã VN30 nến trong phiên): "
              f"khoảng {est:.0f} lần gọi, {est / max(rate, 1e-9) / 60:.0f} phút nếu giữ nhịp {rate * 60:.0f} lần/phút (số lần gọi mỗi mã lấy từ lần đo này).")
    stats(out)


if __name__ == "__main__":
    main()
