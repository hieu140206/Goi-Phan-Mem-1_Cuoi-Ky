"""Khôi phục MỘT phiên đã ghi vào market.db từ dữ liệu GỐC trong data/raw/<ngày>/ (không gọi mạng, không cần đăng nhập).

Dùng khi market.db bị mất hoặc bị ghi đè nhưng thư mục raw của phiên vẫn còn. Chạy SAU 15:02 (khi bộ ghi đã dừng) và nên
sao lưu market.db trước:
  python scripts/restore_session.py 2026-11-09
  python scripts/restore_session.py 2026-11-09 --only rest      # chỉ phần REST
  python scripts/restore_session.py 2026-11-09 --only ws        # chỉ phần WebSocket
  python scripts/restore_session.py 2026-11-04 --only trades    # chỉ từng lần khớp WebSocket (lấy lại lần khớp bị sót)

Mọi số lấy NGUYÊN VĂN từ phản hồi gốc của NEO và đi qua đúng các hàm bộ ghi dùng lúc ghi trực tiếp; không ước lượng.
Chạy lại nhiều lần không sao (dòng đã có thì bỏ qua; bảng giá giữ bản mới nhất).

Khôi phục được:
  - quotes: sổ lệnh VN30 mỗi phút của phiên khớp lệnh liên tục (stocks.jsonl.gz);
  - board: bảng giá các sàn ở lần chụp gốc cuối cùng (board.jsonl.gz); bảng giá VN30 lấy từ lần chụp 4.7 cuối, rồi được
    thay bằng dòng của chính 30 mã đó trong bảng HOSE (4.6, cùng bộ trường) nếu bảng HOSE được chụp muộn hơn (sau ATC);
  - depth_market: độ sâu theo sàn, CHỈ ở các lần chụp có lưu gốc (bộ ghi lưu gốc 10 phút một lần);
  - futures: hợp đồng tương lai VN30 (futures.jsonl.gz); tên VN30F1M... lấy từ ngày gần nhất đã có trong market.db;
  - ws_quotes, ws_trades: phát lại toàn bộ tin WebSocket thô (ws.jsonl.gz) qua bộ ghi WebSocket, cần data/ws_schemas.json.
KHÔNG khôi phục được: chuỗi chỉ số 5 giây (bảng market_index), vì bộ ghi không lưu gốc phần này. Trang Tổng quan khi đó
tự dùng data/raw/<ngày>/market.json (chỉ số cuối ngày và chuỗi theo phút của NEO 4.2).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.market_board import board_frame, depth_row, futures_frame  # noqa: E402
from data.rest_recorder import ANALYSIS_STATUSES  # noqa: E402
from data.schema import normalize_quotes  # noqa: E402
from data.storage import save_board, save_depth_market, save_futures, save_quotes  # noqa: E402
from data.ws_recorder import WsBarRecorder  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402
from neo_api.stream import map_record  # noqa: E402


def read_lines(path: Path):
    """Từng dòng JSON của file .jsonl.gz; dòng hỏng thì bỏ qua (đếm ở nơi gọi không cần thiết: file do bộ ghi tự viết)."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def vn_ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text).tz_convert(TZ)


# ---------------------------------------------------------------- REST
def restore_quotes(day_dir: Path, db: Path) -> tuple[dict, list[dict], pd.Timestamp | None]:
    """Sổ lệnh VN30: làm đúng như RestRecorder.snapshot. Trả (thống kê, bản ghi của lần chụp cuối, giờ lần chụp cuối)."""
    res = {"snapshots": 0, "lo_snapshots": 0, "rows_saved": 0}
    last_records: list[dict] = []
    last_ts = None
    for snap in read_lines(day_dir / "stocks.jsonl.gz"):
        ts, records = vn_ts(snap["ts"]), snap.get("records") or []
        res["snapshots"] += 1
        if records:
            last_records, last_ts = records, ts
        if snap.get("status") not in ANALYSIS_STATUSES or not records:
            continue
        raw = pd.DataFrame([map_record(r) for r in records]).assign(ts=ts)
        clean, report = normalize_quotes(raw)
        locked = report["limit_locked"]
        res["rows_saved"] += save_quotes(pd.concat([clean, locked], ignore_index=True) if len(locked) else clean, db)
        res["lo_snapshots"] += 1
    return res, last_records, last_ts


def restore_boards(day_dir: Path, db: Path, vn30_records: list[dict], vn30_ts: pd.Timestamp | None) -> dict:
    """Bảng giá các sàn và độ sâu theo sàn (như RestRecorder.snapshot_board), rồi bảng giá VN30."""
    res: dict = {"board_snapshots": 0, "depth_rows": 0, "groups": {}, "vn30": "không có"}
    hose_last: tuple[pd.Timestamp, list[dict]] | None = None
    path = day_dir / "board.jsonl.gz"
    if path.exists():
        for snap in read_lines(path):
            ts = vn_ts(snap["ts"])
            res["board_snapshots"] += 1
            for g in snap.get("groups") or []:
                grp, records = g.get("grp"), g.get("records") or []
                if not grp or not records:
                    continue
                frame = board_frame(records, ts, grp)
                save_board(frame, db)
                res["groups"][grp] = f"{len(frame)} mã lúc {ts:%H:%M:%S}"
                if snap.get("status") in ANALYSIS_STATUSES:
                    res["depth_rows"] += save_depth_market(depth_row(frame, ts, grp), db)
                if grp == "HOSE":
                    hose_last = (ts, records)
    if vn30_records and vn30_ts is not None:
        save_board(board_frame(vn30_records, vn30_ts, "VN30"), db)
        res["vn30"] = f"{len(vn30_records)} mã lúc {vn30_ts:%H:%M:%S} (4.7)"
        basket = {str(r.get("symbol", "")).strip().upper() for r in vn30_records}
        if hose_last is not None and hose_last[0] > vn30_ts:
            later = [r for r in hose_last[1] if str(r.get("symbol", "")).strip().upper() in basket]
            if later:
                save_board(board_frame(later, hose_last[0], "VN30"), db)
                res["vn30"] = (f"{len(later)}/{len(basket)} mã lúc {hose_last[0]:%H:%M:%S} (từ bảng HOSE 4.6)"
                               + ("" if len(later) == len(basket) else f"; mã còn lại giữ lần chụp {vn30_ts:%H:%M:%S}"))
    return res


def futures_names(db: Path, day: str) -> dict[str, str]:
    """Mã hợp đồng -> tên (VN30F1M...) lấy từ ngày GẦN NHẤT có trong market.db. Không có thì để nguyên mã."""
    if not db.exists():
        return {}
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT symbol, name, substr(ts, 1, 10) FROM futures WHERE name IS NOT NULL AND name != symbol "
                           "GROUP BY symbol, substr(ts, 1, 10)").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    target = pd.Timestamp(day)
    best: dict[str, tuple[float, str]] = {}
    for sym, name, d in rows:
        gap = abs((pd.Timestamp(d) - target).days)
        if sym not in best or gap < best[sym][0]:
            best[sym] = (gap, name)
    return {s: n for s, (_, n) in best.items()}


def restore_futures(day_dir: Path, db: Path, day: str) -> dict:
    path = day_dir / "futures.jsonl.gz"
    res = {"futures_snapshots": 0, "futures_rows": 0, "unnamed": []}
    if not path.exists():
        return res
    names = futures_names(db, day)
    for snap in read_lines(path):
        records = snap.get("records") or []
        if not records:
            continue
        frame = futures_frame(records, vn_ts(snap["ts"]), names)
        res["futures_rows"] += save_futures(frame, db)
        res["futures_snapshots"] += 1
        res["unnamed"] = sorted(set(res["unnamed"]) | set(frame.loc[frame["name"] == frame["symbol"], "symbol"]))
    return res


# ---------------------------------------------------------------- WebSocket
class ReplayRecorder(WsBarRecorder):
    """Bộ ghi WebSocket chạy trên tin thô đã lưu: không ghi lại file thô và không ghi đè ws_stats.json của phiên gốc."""

    hold_trades = True

    def flush_raw(self, now) -> None:  # noqa: ANN001
        self.raw_buffer.clear()

    def write_stats(self, now) -> None:  # noqa: ANN001
        return

    def flush_trades(self) -> int:
        return 0 if self.hold_trades else super().flush_trades()   # ghi một lần ở cuối cho nhanh


def restore_ws(day_dir: Path, db: Path, schemas_path: Path, interval: int = 5, bars: bool = True) -> dict:
    """Phát lại ws.jsonl.gz. Thanh mang nhãn mốc S chỉ chứa tin nhận TRƯỚC S, giống bộ ghi trực tiếp: trước khi xử lý tin
    đầu tiên của một mốc mới, gọi tick() tại đúng từng mốc đã trôi qua. bars=False: chỉ ghi từng lần khớp (ws_trades)."""
    path = day_dir / "ws.jsonl.gz"
    if not path.exists():
        return {"ws": "không có ws.jsonl.gz"}
    if not schemas_path.exists():
        return {"ws": f"thiếu {schemas_path.name} nên không giải mã được"}
    rec = ReplayRecorder(db, day_dir, interval)
    schemas = {int(k): v for k, v in json.loads(schemas_path.read_text(encoding="utf-8")).items()}
    if not rec.set_schemas(schemas):
        return {"ws": "không dùng được schema (cần cài fastavro)"}
    step = pd.Timedelta(seconds=rec.interval)
    n_bars = 0
    for msg in read_lines(path):
        now = vn_ts(msg["t"])
        if bars:
            slot = rec.slot(now)
            if rec.last_slot is None:
                n_bars += rec.tick(slot)
            else:
                while rec.last_slot < slot:
                    n_bars += rec.tick(rec.last_slot + step)
        rec.on_raw(base64.b64decode(msg["b"]), now)
    if bars and rec.last_slot is not None:
        n_bars += rec.tick(rec.last_slot + step)   # thanh cuối cùng sau tin cuối
    rec.hold_trades = False
    saved = rec.flush_trades()
    s = rec.stats
    return {"ws_messages": s["messages"], "ws_bar_rows": n_bars, "ws_trades_read": s["trades"], "ws_trades_saved": saved,
            "ws_decode_errors": s["decode_errors"]}


# ---------------------------------------------------------------- chạy
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("day", help="Ngày cần khôi phục, dạng YYYY-MM-DD (phải có thư mục data/raw/<ngày>/)")
    ap.add_argument("--only", choices=["rest", "ws", "trades"],
                    help="Chỉ khôi phục phần REST, phần WebSocket, hoặc riêng từng lần khớp WebSocket (bảng ws_trades)")
    ap.add_argument("--db", type=Path, help="Đường dẫn market.db khác (mặc định theo .env)")
    args = ap.parse_args()

    try:
        day = pd.Timestamp(args.day).strftime("%Y-%m-%d")
    except ValueError:
        sys.exit("Ngày phải có dạng YYYY-MM-DD.")
    day_dir = ROOT / "data" / "raw" / day
    if not day_dir.is_dir():
        sys.exit(f"Không có thư mục {day_dir}. Không có dữ liệu gốc thì không khôi phục được.")
    now = pd.Timestamp.now(tz=TZ)
    if day == now.strftime("%Y-%m-%d") and now.time() < pd.Timestamp("15:05").time():
        sys.exit("Đây là phiên hôm nay và bộ ghi có thể còn chạy. Chạy lại sau 15:05.")
    db = args.db or get_settings().db_path
    db = db if db.is_absolute() else ROOT / db
    print(f"Khôi phục phiên {day} vào {db}")

    if args.only not in ("ws", "trades"):
        if (day_dir / "stocks.jsonl.gz").exists():
            q, last_records, last_ts = restore_quotes(day_dir, db)
            print(f"  Sổ lệnh VN30: đọc {q['snapshots']} lần chụp gốc, {q['lo_snapshots']} lần trong phiên liên tục, "
                  f"ghi thêm {q['rows_saved']} dòng")
        else:
            last_records, last_ts = [], None
            print("  Sổ lệnh VN30: không có stocks.jsonl.gz")
        b = restore_boards(day_dir, db, last_records, last_ts)
        print(f"  Bảng giá các sàn: {b['board_snapshots']} lần chụp gốc; "
              + (" · ".join(f"{g} {v}" for g, v in b["groups"].items()) or "không có"))
        print(f"  Bảng giá VN30: {b['vn30']}")
        print(f"  Độ sâu theo sàn: ghi thêm {b['depth_rows']} dòng (gốc chỉ lưu 10 phút một lần)")
        f = restore_futures(day_dir, db, day)
        print(f"  Phái sinh: {f['futures_snapshots']} lần chụp, ghi thêm {f['futures_rows']} dòng"
              + (f"; chưa có tên cho {', '.join(f['unnamed'])} (để nguyên mã)" if f["unnamed"] else ""))
        print("  Chỉ số 5 giây: không có dữ liệu gốc nên không khôi phục; Tổng quan dùng market.json của ngày này.")
    if args.only != "rest":
        print("  WebSocket: đang phát lại tin thô (mất một hai phút)...")
        w = restore_ws(day_dir, db, ROOT / "data" / "ws_schemas.json", bars=args.only != "trades")
        if "ws" in w:
            print(f"  WebSocket: {w['ws']}")
        else:
            print(f"  WebSocket: {w['ws_messages']} tin, ghi thêm {w['ws_bar_rows']} dòng thanh 5 giây và "
                  f"{w['ws_trades_saved']}/{w['ws_trades_read']} lần khớp, {w['ws_decode_errors']} tin không giải mã được")
    print(f"Xong. Kiểm tra lại:  python scripts/compare_ws_rest.py {day}")


if __name__ == "__main__":
    main()
