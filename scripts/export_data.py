"""Xuất dữ liệu sổ lệnh đã ghi (data/market.db) ra CSV hoặc Excel để mở bằng Excel.

Chạy (kích hoạt .venv trước), chạy được cả khi bộ ghi đang chạy:
  python scripts/export_data.py                       # tất cả các ngày -> data/export/so_lenh_<ngày>.csv
  python scripts/export_data.py --date 2026-10-28     # một ngày
  python scripts/export_data.py --excel               # thêm file .xlsx (mỗi ngày một sheet + sheet tổng hợp)
  python scripts/export_data.py --ws                  # xuất sổ lệnh WebSocket (bảng ws_quotes, thanh 5 giây) ra CSV
  python scripts/export_data.py --ws --excel --date 2026-10-30   # WebSocket một ngày ra Excel

Cột đã đổi sang tên tiếng Việt và có sẵn spread, độ sâu, lệch mua/bán. Giờ là giờ Việt Nam.
CSV lưu kiểu utf-8-sig để Excel đọc đúng tiếng Việt.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from data.schema import normalize_quotes  # noqa: E402
from data.storage import load_quotes, load_ws_quotes  # noqa: E402
from finance.liquidity import add_liquidity_metrics  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

NAMES = {
    "ts": "Thời điểm", "symbol": "Mã", "ref_px": "Giá tham chiếu", "last_px": "Giá khớp gần nhất",
    "bid_px1": "Giá mua 1", "bid_qty1": "KL mua 1", "bid_px2": "Giá mua 2", "bid_qty2": "KL mua 2",
    "bid_px3": "Giá mua 3", "bid_qty3": "KL mua 3", "ask_px1": "Giá bán 1", "ask_qty1": "KL bán 1",
    "ask_px2": "Giá bán 2", "ask_qty2": "KL bán 2", "ask_px3": "Giá bán 3", "ask_qty3": "KL bán 3",
    "total_vol": "Tổng KL khớp (lũy kế)", "total_value": "Tổng giá trị khớp (lũy kế)",
    "open_px": "Giá mở cửa", "high_px": "Giá cao nhất", "low_px": "Giá thấp nhất",
    "foreign_buy_vol": "KL NN mua", "foreign_sell_vol": "KL NN bán", "foreign_net_val": "Giá trị NN mua ròng",
    "foreign_remain": "Room NN còn lại",
    "n_msgs": "Số tin WS trong 5 giây", "age_ms": "Tin cuối cách mốc (mili giây)",
    "spread": "Spread (đồng)", "rel_spread_bps": "Spread (bps)", "depth_value": "Độ sâu 3 mức (đồng)",
    "imbalance": "Lệch mua/bán (-1..1)",
}


def load_table() -> pd.DataFrame:
    raw = load_quotes(get_settings().db_path)
    if raw.empty:
        return raw
    clean, _ = normalize_quotes(raw)
    df = add_liquidity_metrics(clean)
    df = df[[c for c in NAMES if c in df.columns]].copy()
    df["ts"] = df["ts"].dt.tz_localize(None)  # Excel không đọc được múi giờ; giờ đã là giờ Việt Nam
    return df


def load_ws_table() -> pd.DataFrame:
    """Sổ lệnh WebSocket đã ghi (ws_quotes). Dữ liệu đã được làm sạch lúc ghi; thêm spread, độ sâu, lệch mua/bán như REST."""
    raw = load_ws_quotes(get_settings().db_path)
    if raw.empty:
        return raw
    df = add_liquidity_metrics(raw)
    df = df[[c for c in NAMES if c in df.columns]].copy()
    df["ts"] = df["ts"].dt.tz_localize(None)
    return df


def export_ws(date: str | None, excel: bool) -> None:
    df = load_ws_table()
    if df.empty:
        sys.exit("Chưa có dữ liệu WebSocket (bảng ws_quotes). Chạy: python scripts/run_live.py --ws")
    if date:
        df = df[df["ts"].dt.strftime("%Y-%m-%d") == date]
        if df.empty:
            sys.exit(f"Không có dữ liệu WebSocket ngày {date}.")
    out_dir = ROOT / "data" / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    days = sorted(df["ts"].dt.strftime("%Y-%m-%d").unique())
    summary = []
    for day in days:
        part = df[df["ts"].dt.strftime("%Y-%m-%d") == day].sort_values(["symbol", "ts"])
        path = out_dir / f"so_lenh_ws_{day}.csv"
        part.rename(columns=NAMES).to_csv(path, index=False, encoding="utf-8-sig")
        quiet = int((part["n_msgs"] == 0).sum()) if "n_msgs" in part else 0
        summary.append({"Ngày": day, "Số dòng": len(part), "Số mã": part["symbol"].nunique(),
                        "Số thanh 5 giây": part["ts"].nunique(), "Từ": part["ts"].min().strftime("%H:%M:%S"),
                        "Đến": part["ts"].max().strftime("%H:%M:%S"), "Dòng không có tin mới": quiet,
                        "File": path.name})
        print(f"{day}: {len(part):,} dòng WebSocket, {part['ts'].nunique()} thanh -> {path.relative_to(ROOT)}")
    if excel:
        xlsx = out_dir / (f"so_lenh_ws_{date}.xlsx" if date else "so_lenh_ws_tat_ca.xlsx")
        with pd.ExcelWriter(xlsx) as w:
            pd.DataFrame(summary).to_excel(w, sheet_name="Tổng hợp", index=False)
            for day in days:
                part = df[df["ts"].dt.strftime("%Y-%m-%d") == day].sort_values(["symbol", "ts"])
                part.rename(columns=NAMES).to_excel(w, sheet_name=day, index=False)
        print(f"Excel: {xlsx.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="Chỉ xuất một ngày, dạng YYYY-MM-DD")
    ap.add_argument("--excel", action="store_true", help="Xuất thêm file Excel .xlsx")
    ap.add_argument("--ws", action="store_true", help="Xuất sổ lệnh WebSocket (ws_quotes) thay cho REST")
    args = ap.parse_args()
    if args.ws:
        export_ws(args.date, args.excel)
        return

    df = load_table()
    if df.empty:
        sys.exit("Chưa có dữ liệu trong data/market.db. Chạy bộ ghi trước: python scripts/record_rest.py")
    if args.date:
        df = df[df["ts"].dt.strftime("%Y-%m-%d") == args.date]
        if df.empty:
            sys.exit(f"Không có dữ liệu ngày {args.date}.")
    out_dir = ROOT / "data" / "export"
    out_dir.mkdir(parents=True, exist_ok=True)

    days = sorted(df["ts"].dt.strftime("%Y-%m-%d").unique())
    summary = []
    for day in days:
        part = df[df["ts"].dt.strftime("%Y-%m-%d") == day].sort_values(["symbol", "ts"])
        path = out_dir / f"so_lenh_{day}.csv"
        part.rename(columns=NAMES).to_csv(path, index=False, encoding="utf-8-sig")
        summary.append({"Ngày": day, "Số dòng": len(part), "Số mã": part["symbol"].nunique(),
                        "Số lần chụp": part["ts"].nunique(), "Từ": part["ts"].min().strftime("%H:%M"),
                        "Đến": part["ts"].max().strftime("%H:%M"), "File": path.name})
        print(f"{day}: {len(part):,} dòng, {part['ts'].nunique()} lần chụp -> {path.relative_to(ROOT)}")

    if args.excel:
        xlsx = out_dir / (f"so_lenh_{args.date}.xlsx" if args.date else "so_lenh_tat_ca.xlsx")
        with pd.ExcelWriter(xlsx) as w:
            pd.DataFrame(summary).to_excel(w, sheet_name="Tổng hợp", index=False)
            per_sym = (df.groupby("symbol").agg(spread_bps=("rel_spread_bps", "median"),
                                                depth=("depth_value", "median"), n=("ts", "size"))
                       .rename(columns={"spread_bps": "Spread trung vị (bps)", "depth": "Độ sâu trung vị (đồng)",
                                        "n": "Số lần chụp"}).reset_index().rename(columns={"symbol": "Mã"}))
            per_sym.to_excel(w, sheet_name="Theo mã", index=False)
            for day in days:
                part = df[df["ts"].dt.strftime("%Y-%m-%d") == day].sort_values(["symbol", "ts"])
                part.rename(columns=NAMES).to_excel(w, sheet_name=day, index=False)
        print(f"Excel: {xlsx.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
