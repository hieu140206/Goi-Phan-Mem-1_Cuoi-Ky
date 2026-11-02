"""So sánh sổ lệnh WebSocket với REST cùng thời điểm (chạy sau phiên): python scripts/compare_ws_rest.py [YYYY-MM-DD]

Với mỗi lần chụp REST (mỗi phút), lấy thanh WebSocket gần nhất KHÔNG SAU mốc REST (tối đa 10 giây) rồi so từng trường
giá/khối lượng. Vì REST và WebSocket được chụp lệch nhau vài trăm mili giây, vài ô lệch là bình thường; nếu lệch hàng loạt
thì có thể đơn vị hoặc cách ghép trường chưa đúng.

Phần 2 (có bảng ws_trades, từ 2/11/2026): kiểm tra MẤT TIN của kênh từng lần khớp. Với mỗi mã, tổng khối lượng các lần
khớp WebSocket trong khoảng (lần chụp REST đầu, lần chụp REST cuối] phải gần bằng phần tăng của tổng khối lượng lũy kế
REST trong cùng khoảng. Số thứ tự sequenceMsg đánh chung cho mọi mã nên không dùng nó để đếm tin mất từng mã được.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo_api.config import get_settings  # noqa: E402

COMPARE = ["bid_px1", "bid_qty1", "ask_px1", "ask_qty1", "bid_px2", "ask_px2", "last_px", "total_vol"]


def check_trades(q: pd.DataFrame, con: sqlite3.Connection, day: str) -> None:
    try:
        t = pd.read_sql_query("SELECT * FROM ws_trades WHERE substr(ts,1,10)=?", con, params=(day,))
    except Exception:  # noqa: BLE001 - DB cũ chưa có bảng
        t = pd.DataFrame()
    if t.empty:
        print("\nChưa có lần khớp WebSocket (bảng ws_trades) cho ngày này.")
        return
    t["ts"] = pd.to_datetime(t["ts"], utc=True)
    r = q[["ts", "symbol", "total_vol"]].dropna().assign(ts=lambda d: pd.to_datetime(d["ts"], utc=True))
    # Chỉ so trong khoảng bộ ghi WebSocket đang chạy (làm tròn ra phút vì REST chụp đúng mốc phút).
    r = r[(r["ts"] >= t["ts"].min().floor("min")) & (r["ts"] <= t["ts"].max().ceil("min"))]
    rows = []
    for sym, g in r.sort_values("ts").groupby("symbol"):
        if len(g) < 2:
            continue
        a, b = g.iloc[0], g.iloc[-1]
        rest = b["total_vol"] - a["total_vol"]
        ws = t.loc[(t["symbol"] == sym) & (t["ts"] > a["ts"]) & (t["ts"] <= b["ts"]), "volume"].sum()
        rows.append({"symbol": sym, "rest": rest, "ws": ws})
    if not rows:
        print("\nKhông có khoảng thời gian chung giữa lần khớp WebSocket và REST để so.")
        return
    c = pd.DataFrame(rows)
    c["ratio"] = c["ws"] / c["rest"].where(c["rest"] > 0)
    tot_rest, tot_ws = c["rest"].sum(), c["ws"].sum()
    off = c[(c["ratio"] - 1).abs() > 0.02]
    print(f"\nLần khớp WebSocket: {len(t)} lần, {t['symbol'].nunique()} mã.")
    print(f"  Tổng khối lượng: WebSocket {tot_ws:,.0f} / REST {tot_rest:,.0f} = {tot_ws / tot_rest:.1%}"
          if tot_rest else "  REST không có khối lượng tăng trong khoảng so sánh.")
    print(f"  Mã lệch quá 2%: {len(off)}/{len(c)}" + (": " + ", ".join(f"{r.symbol} {r.ratio:.1%}" for r in off.itertuples())
                                                   if len(off) else ""))
    print("  Gợi ý: gần 100% là không mất tin. Lệch nhỏ có thể do mốc chụp REST là giờ chu kỳ còn lần khớp tính theo giây.")


def main() -> None:
    settings = get_settings()
    db = Path(settings.db_path) if Path(settings.db_path).is_absolute() else ROOT / settings.db_path
    day = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").strftime("%Y-%m-%d")
    con = sqlite3.connect(db)
    q = pd.read_sql_query("SELECT * FROM quotes WHERE substr(ts,1,10)=?", con, params=(day,), parse_dates=["ts"])
    w = pd.read_sql_query("SELECT * FROM ws_quotes WHERE substr(ts,1,10)=?", con, params=(day,), parse_dates=["ts"])
    if q.empty or w.empty:
        sys.exit(f"Ngày {day}: REST {len(q)} dòng, WebSocket {len(w)} dòng. Cần cả hai để so sánh.")
    cols = [c for c in COMPARE if c in q.columns and c in w.columns]
    m = pd.merge_asof(q.sort_values("ts"), w.sort_values("ts"), on="ts", by="symbol", direction="backward",
                      tolerance=pd.Timedelta("10s"), suffixes=("", "_ws")).dropna(subset=[f"{cols[0]}_ws"])
    print(f"Ngày {day}: REST {len(q)} dòng, WebSocket {len(w)} dòng, ghép được {len(m)} cặp.")
    for c in cols:
        both = m[[c, f"{c}_ws"]].dropna()
        same = (both[c] == both[f"{c}_ws"]).mean() if len(both) else float("nan")
        print(f"  {c:10s} khớp {same:6.1%} ({len(both)} cặp)")
    print("Gợi ý: khớp >95% là WebSocket đáng tin; thấp hơn thì gửi kết quả này để kiểm tra cách ghép trường.")
    check_trades(q, con, day)


if __name__ == "__main__":
    main()
