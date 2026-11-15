"""Lấy lịch sử THEO NGÀY từ SSI (giá, khối lượng, mua bán nước ngoài, room, chỉ số) vào data/market.db. Chạy được mọi lúc, kể cả ngoài giờ.

Chạy (kích hoạt .venv trước):
  python scripts/fetch_ssi_history.py              # 21 ngày gần nhất cho 30 mã VN30 + VNINDEX, VN30
  python scripts/fetch_ssi_history.py --days 45
  python scripts/fetch_ssi_history.py --check      # đối chiếu SSI với NEO (không gọi mạng)

SSI chỉ là nguồn PHỤ bù lịch sử cho NEO; dữ liệu nằm ở bảng riêng ssi_daily, ssi_index_daily. Chỉ ĐỌC, không đặt lệnh.
Cần SSI_API_KEY và SSI_API_SECRET trong .env (KHÔNG cần Private Key). Giới hạn 20 lần gọi cho mỗi API nên chạy mất vài phút.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.ssi import (  # noqa: E402
    SsiClient, SsiError, fetch_index_day, fetch_summary, load_ssi_daily, save_ssi_daily, save_ssi_index,
    stored_index_days,
)
from neo_api.config import TZ, get_settings  # noqa: E402

INDICES = ["VNINDEX", "VN30"]


def read_symbols(path: Path) -> list[str]:
    return [ln.strip().upper() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def db_path() -> Path:
    p = Path(get_settings().db_path)
    return p if p.is_absolute() else ROOT / p


def fetch(days: int, symbols: list[str]) -> None:
    db = db_path()
    today = pd.Timestamp.now(tz=TZ).normalize()
    frm, to = (today - pd.Timedelta(days=days)).strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d")
    client = SsiClient()
    print(f"SSI: {len(symbols)} mã + {len(INDICES)} chỉ số, từ {frm} đến {to}")
    calendar: set[str] = set()
    for code in INDICES:                                  # chỉ số trước: cho biết những ngày thật sự có giao dịch
        df = fetch_summary(client, code, frm, to, is_index=True)
        save_ssi_daily(df, db)
        print(f"  {code}: {len(df)} ngày")
        calendar |= set(df["day"])
    for i, sym in enumerate(symbols, 1):
        df = fetch_summary(client, sym, frm, to)
        save_ssi_daily(df, db)
        print(f"  [{i}/{len(symbols)}] {sym}: {len(df)} ngày")
    days_todo = sorted(calendar)
    for code in INDICES:                                  # số mã tăng/giảm, nước ngoài: mỗi ngày một lần gọi
        have = stored_index_days(db, code)
        todo = [d for d in days_todo if d not in have or d == today.strftime("%Y-%m-%d")]
        print(f"  Độ rộng {code}: lấy {len(todo)} ngày (đã có {len(have)})")
        for d in todo:
            save_ssi_index(fetch_index_day(client, code, d), db)
    print("Xong. Đối chiếu với NEO:  python scripts/fetch_ssi_history.py --check")


def neo_final(db: Path) -> pd.DataFrame:
    """Dòng bảng giá VN30 cuối mỗi (ngày, mã) của NEO, chỉ lấy ảnh chụp từ 14:45 (đã qua ATC)."""
    con = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT day, symbol, ts, last_px, total_vol, foreign_buy_vol, foreign_sell_vol, foreign_remain FROM board "
        "WHERE grp = 'VN30' AND substr(ts, 12, 5) >= '14:45' ORDER BY ts", con)
    return df.drop_duplicates(["day", "symbol"], keep="last")


def check() -> None:
    db = db_path()
    ssi, neo = load_ssi_daily(db), neo_final(db)
    m = neo.merge(ssi, on=["day", "symbol"], how="inner")
    if m.empty:
        sys.exit("Chưa có ngày nào có cả NEO (sau 14:45) lẫn SSI. Chạy fetch trước.")
    pairs = {"giá đóng cửa": ("last_px", "close"), "khối lượng": ("total_vol", "total_match"),
             "NN mua": ("foreign_buy_vol", "foreign_buy_vol_y"), "NN bán": ("foreign_sell_vol", "foreign_sell_vol_y"),
             "room NN": ("foreign_remain", "remain_room")}
    m = m.rename(columns={"foreign_buy_vol_x": "foreign_buy_vol", "foreign_sell_vol_x": "foreign_sell_vol"})
    print(f"Đối chiếu {len(m)} cặp (ngày, mã), {m['day'].nunique()} ngày, {m['symbol'].nunique()} mã:")
    bad = []
    for name, (a, b) in pairs.items():
        a_ = a if a in m else a + "_x"
        both = m.dropna(subset=[a_, b])
        diff = both[(both[a_] - both[b]).abs() > 0.5]
        if name == "giá đóng cửa":
            # SSI trả giá ĐÃ ĐIỀU CHỈNH cổ tức cho các ngày trước ngày giao dịch không hưởng quyền (bước giá thật
            # luôn là bội của 10 đồng, giá điều chỉnh thì lẻ, vd 31315,025). Tách riêng, không tính là lệch dữ liệu.
            adj_mask = diff[b].map(lambda v: abs(v / 10 - round(v / 10)) > 1e-6)
            adj, diff = diff[adj_mask], diff[~adj_mask]
            print(f"  {name:13s} khớp {len(both) - len(diff) - len(adj)}/{len(both)}"
                  f"  (+ {len(adj)} dòng SSI là giá điều chỉnh cổ tức, không so được)")
            if len(adj):
                ratio = (adj[b] / adj[a_]).groupby(adj["symbol"]).agg(["count", "min", "max"])
                print("    Mã có giá điều chỉnh (SSI/NEO): " + "; ".join(
                    f"{s} {r['count']:.0f} ngày, tỷ lệ {r['min']:.3f}-{r['max']:.3f}" for s, r in ratio.iterrows()))
                print("    => KHÔNG dùng giá SSI để tính lợi suất/động lượng nếu chưa xử lý điều chỉnh.")
        else:
            print(f"  {name:13s} khớp {len(both) - len(diff)}/{len(both)}")
        bad += [(name, r.day, r.symbol, getattr(r, a_), getattr(r, b)) for r in diff.itertuples()]
    for name, day, sym, n, s in bad[:25]:
        pct = (s - n) / n * 100 if n else float("nan")
        print(f"    lệch {name}: {day} {sym}  NEO {n:,.0f}  SSI {s:,.0f}  ({pct:+.1f}%)")
    if len(bad) > 25:
        print(f"    ... và {len(bad) - 25} dòng lệch nữa")
    no_neo = sorted(set(ssi["day"]) - set(neo["day"]))
    print(f"Ngày SSI có mà NEO chưa có ảnh chụp sau ATC: {no_neo}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=21, help="Lấy bao nhiêu ngày lịch gần nhất (mặc định 21)")
    ap.add_argument("--symbols", type=Path, default=ROOT / "data" / "symbols_VN30.txt")
    ap.add_argument("--check", action="store_true", help="Chỉ đối chiếu SSI với NEO trong market.db, không gọi mạng")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.check:
        check()
        return
    try:
        fetch(args.days, read_symbols(args.symbols))
    except SsiError as exc:
        sys.exit(f"Lỗi SSI: {exc}")


if __name__ == "__main__":
    main()
