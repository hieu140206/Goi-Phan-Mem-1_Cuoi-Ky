"""Cột chuẩn của dữ liệu sổ lệnh và hàm làm sạch.

Tên cột chuẩn là tên NỘI BỘ của dự án; ánh xạ từ trường `stockInfo` của NEO nằm ở neo_api/stream.py (FIELD_MAP).
Giá tính bằng đồng, khối lượng tính bằng cổ phiếu. Thông điệp NEO không có dấu thời gian nên `ts` là
thời điểm chụp (giờ Việt Nam) do bộ ghi dữ liệu gán.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from neo_api.config import TZ

LEVELS = (1, 2, 3)
BID_PX = [f"bid_px{i}" for i in LEVELS]
BID_QTY = [f"bid_qty{i}" for i in LEVELS]
ASK_PX = [f"ask_px{i}" for i in LEVELS]
ASK_QTY = [f"ask_qty{i}" for i in LEVELS]
# Trường bổ sung cho yếu tố nước ngoài và động lượng (có thể trống với dữ liệu mô phỏng).
EXTRA_COLUMNS = [
    "total_value", "ref_px", "open_px", "high_px", "low_px",
    "foreign_buy_vol", "foreign_sell_vol", "foreign_buy_val", "foreign_sell_val",
    "foreign_net_val", "foreign_remain", "foreign_room",
]
QUOTE_COLUMNS = ["ts", "symbol", *BID_PX, *BID_QTY, *ASK_PX, *ASK_QTY, "last_px", "total_vol", *EXTRA_COLUMNS]
NUMERIC_COLUMNS = [c for c in QUOTE_COLUMNS if c not in ("ts", "symbol")]
AUCTION_TOKENS = {"ATO", "ATC", "ATP"}  # giá mức 1 là chữ trong các phiên khớp lệnh định kỳ


def _is_auction(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper().isin(AUCTION_TOKENS).fillna(False).astype(bool)


def normalize_quotes(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Làm sạch dữ liệu thô. Trả về (dữ liệu sạch, báo cáo số dòng bị loại theo từng lý do).

    Quy tắc:
      - Giá mức 1 là chữ ATO/ATC/ATP (phiên khớp lệnh định kỳ) thì loại, đếm riêng.
      - Dấu thời gian: không có múi giờ thì coi là giờ Việt Nam; có múi giờ thì đổi về UTC+7.
      - Ép kiểu số (giá có thể là chuỗi như "29750.0"); giá trị không đọc được thành NaN.
      - Loại dòng thiếu mã/thời gian/giá mua-bán tốt nhất, giá <= 0.
      - Loại sổ lệnh bị chéo (giá bán tốt nhất <= giá mua tốt nhất).
      - Loại bản ghi trùng (ts, symbol), giữ bản ghi sau cùng.
    """
    report = {"rows_in": len(df)}
    out = df.copy()
    for col in QUOTE_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    auction = _is_auction(out["bid_px1"]) | _is_auction(out["ask_px1"])
    report["dropped_auction"] = int(auction.sum())
    out = out[~auction].copy()

    ts = pd.to_datetime(out["ts"], errors="coerce")
    ts = ts.dt.tz_localize(TZ) if ts.dt.tz is None else ts.dt.tz_convert(TZ)
    out["ts"] = ts
    out["symbol"] = out["symbol"].astype("string").str.strip().str.upper()
    for col in NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    n = len(out)
    out = out.dropna(subset=["ts", "symbol", "bid_px1", "ask_px1"])
    report["dropped_missing"] = n - len(out)

    n = len(out)
    out = out[(out["bid_px1"] > 0) & (out["ask_px1"] > 0)]
    report["dropped_invalid_price"] = n - len(out)

    n = len(out)
    out = out[out["ask_px1"] > out["bid_px1"]]
    report["dropped_crossed_book"] = n - len(out)

    n = len(out)
    out = out.sort_values(["symbol", "ts"]).drop_duplicates(["ts", "symbol"], keep="last")
    report["dropped_duplicate"] = n - len(out)

    out = out[QUOTE_COLUMNS].reset_index(drop=True)
    report["rows_out"] = len(out)
    return out, report
