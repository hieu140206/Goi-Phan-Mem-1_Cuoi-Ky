"""So sánh sổ lệnh WebSocket với REST cùng thời điểm (chạy sau phiên): python scripts/compare_ws_rest.py [YYYY-MM-DD]

Với mỗi lần chụp REST (mỗi phút), lấy thanh WebSocket gần nhất KHÔNG SAU mốc REST (tối đa 10 giây) rồi so từng trường
giá/khối lượng. Vì REST và WebSocket được chụp lệch nhau vài trăm mili giây, vài ô lệch là bình thường; nếu lệch hàng loạt
thì có thể đơn vị hoặc cách ghép trường chưa đúng.
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


if __name__ == "__main__":
    main()
