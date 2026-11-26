"""Dữ liệu SSI cho trang Tổng quan, CHỈ dùng cho ngày NEO không ghi được: 4 thẻ chỉ số, bảng giá VN30 và độ sâu VN30.

Nguồn: bảng ssi_index_daily (tổng kết ngày của chỉ số), ssi_daily (tổng kết ngày của mã), ssi_quotes (sổ lệnh 3 mức) trong market.db,
và nến 1 phút của chỉ số trong candles.db. Nạp bằng scripts/fetch_ssi_overview.py. Ngày có NEO luôn dùng NEO (quy tắc ở DESIGN.md mục 3).

Đối chiếu với NEO ngày 19 và 20/11/2026 (60 cặp ngày x mã, 30 mã VN30):
- Khớp 100%: giá khớp, tham chiếu (= giá đóng cửa - mức thay đổi của SSI), mở/cao/thấp, tổng khối lượng và giá trị khớp, khối lượng NN mua/bán.
- Sổ lệnh 3 mức: thanh SSI cuối ngày (14:59:55) trùng ảnh chụp NEO 15:02 ở 30/30 mã, cả 12 cột (ngày 13 và 16/11).
- VN-Index, VN30, HNX-Index: điểm và mức thay đổi trùng. UPCoM-Index: SSI lệch số chốt NEO 0,01 đến 0,72 điểm (8 phiên 10 đến 20/11).
- Số mã tăng/giảm của NEO gồm cả trần/sàn (= SSI tăng + trần, giảm + sàn). SSI trả toàn 0 cho VN30, HNX, UPCoM: để trống.
- Khối lượng/giá trị chỉ số của NEO gần với SSI "khớp + thỏa thuận" (lệch vài phần trăm).
- KHÔNG khớp: giá trị NN mua/bán (lệch tới 3,6%) nên cột NN ròng để trống. SSI không có giá trần/sàn: để trống, không tự tính.
Thuần pandas, không import streamlit (để kiểm thử được).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from neo_api.config import TZ

from .candle_store import load_candles
from .overview import MAIN_INDICES, board_view
from .schema import ASK_PX, ASK_QTY, BID_PX, BID_QTY
from .ssi import load_ssi_daily, load_ssi_index, ssi_quote_days

# mã trong ứng dụng -> mã SSI dùng để hỏi tổng kết ngày và nến (nến UPCoM phải hỏi bằng "HNXUpcomIndex")
SSI_SUMMARY_CODES = {"VNINDEX": "VNINDEX", "VN30": "VN30", "HNXINDEX": "HNXINDEX", "UPCOMINDEX": "UPCOMINDEX"}
SSI_OHLC_CODES = {"VNINDEX": "VNINDEX", "VN30": "VN30", "HNXINDEX": "HNXINDEX", "UPCOMINDEX": "HNXUpcomIndex"}
INDEX_FRAME = "1m"                # khung nến của đường chỉ số trong ngày trong candles.db
AFTER_CLOSE = dt.time(14, 45)     # sổ lệnh chỉ coi là cuối ngày khi thanh mới nhất từ 14:45


def ssi_overview_days(db_path: Path, neo_days: list[str]) -> list[str]:
    """Ngày hiện được bằng SSI: NEO không có dữ liệu, có sổ lệnh SSI VÀ đã nạp tổng kết của ĐỦ 4 chỉ số (ngày mới có vài chỉ số từ lần lấy
    lịch sử cũ thì không hiện, để trang không thiếu thẻ và đường trong ngày). YYYY-MM-DD, tăng dần."""
    idx = load_ssi_index(Path(db_path))
    if idx.empty:
        return []
    main = idx[idx["index_code"].isin(MAIN_INDICES)]
    have = main.groupby("day")["index_code"].nunique()
    full = set(have[have == len(MAIN_INDICES)].index)
    return sorted((set(ssi_quote_days(Path(db_path))) & full) - set(neo_days))


def load_index_minutes(candle_db: Path, day: dt.date) -> pd.DataFrame:
    """Nến 1 phút trong ngày của 4 chỉ số, cùng dạng bảng market_index tối thiểu: ts (UTC+7), index_code, index_value, low, high."""
    parts = []
    for code in MAIN_INDICES:
        c = load_candles(Path(candle_db), INDEX_FRAME, code)
        if c.empty:
            continue
        c = c[c["ts"].dt.date == day]
        if c.empty:
            continue
        parts.append(pd.DataFrame({"ts": c["ts"].dt.tz_localize(TZ), "index_code": code, "index_value": c["close"],
                                   "low": c["low"], "high": c["high"]}))
    if not parts:
        return pd.DataFrame(columns=["ts", "index_code", "index_value", "low", "high"])
    return pd.concat(parts, ignore_index=True)


def ssi_index_cards(index_daily: pd.DataFrame, minutes: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    """Một dòng mỗi chỉ số, cùng cột với index_cards (NEO) cộng thêm low, high. Số mã tăng/giảm đã gồm trần/sàn như NEO;
    SSI không có thì để trống."""
    d = index_daily[index_daily["day"] == f"{day:%Y-%m-%d}"] if not index_daily.empty else index_daily
    rows = []
    for code in MAIN_INDICES:
        r = d[d["index_code"] == code] if not d.empty else d
        if r.empty:
            continue
        # cột trống đọc từ SQLite là None: đổi sang số (NaN) trước khi cộng
        r = pd.to_numeric(r.iloc[-1].drop(["day", "index_code", "fetched_at"]), errors="coerce")
        m = minutes[minutes["index_code"] == code]
        rows.append({
            "index_code": code, "index_value": r["index_value"], "index_change": r["index_change"], "pct_change": r["index_pct"],
            # thiếu một trong hai phần thì tổng để trống (không coi phần thiếu là 0)
            "sum_volume": r["total_match"] + r["total_deal"], "sum_value": r["total_match_value"] + r["total_deal_value"],
            "advances": r["advances"] + r["ceilings"], "no_change": r["no_change"], "declines": r["declines"] + r["floors"],
            "ceilings": r["ceilings"], "floors": r["floors"], "status": "C",
            "ts": m["ts"].max() if not m.empty else pd.Timestamp(f"{day:%Y-%m-%d} 15:00", tz=TZ),
            "low": m["low"].min() if not m.empty else np.nan, "high": m["high"].max() if not m.empty else np.nan,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        num = out.columns.drop(["index_code", "status", "ts"])
        out[num] = out[num].astype(float)
    return out


def ssi_last_book(db_path: Path, day: dt.date) -> pd.DataFrame:
    """Thanh sổ lệnh MỚI NHẤT trong ngày của mỗi mã (ts, symbol, 3 mức mua bán). Chỉ đọc."""
    import sqlite3
    cols = ["ts", "symbol", *BID_PX, *BID_QTY, *ASK_PX, *ASK_QTY]
    if not Path(db_path).exists():
        return pd.DataFrame(columns=cols)
    sel = ", ".join(f"q.{c}" for c in cols)
    day_s = f"{day:%Y-%m-%d}"
    try:
        con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
        try:
            df = pd.read_sql_query(
                f"SELECT {sel} FROM ssi_quotes q JOIN (SELECT symbol, MAX(ts) AS ts FROM ssi_quotes WHERE ts >= ? AND ts < ? GROUP BY symbol) m "
                "ON q.symbol = m.symbol AND q.ts = m.ts", con, params=(day_s, day_s + "~"))
        finally:
            con.close()
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame(columns=cols)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    return df


def ssi_board(book: pd.DataFrame, daily: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    """Bảng giá VN30 của ngày: cùng cột với board_view. Danh sách mã là các mã có trong sổ lệnh. Sổ lệnh chỉ hiện khi thanh mới nhất
    từ 14:45 (bộ ghi dừng sớm hơn thì để trống, không ghép sổ lệnh giữa phiên với giá đóng cửa). Trần, sàn, KL khớp lệnh cuối, NN ròng: để trống."""
    if book.empty:
        return pd.DataFrame()
    book = book.copy()
    stale = book["ts"].dt.time < AFTER_CLOSE
    book_cols = [*BID_PX, *BID_QTY, *ASK_PX, *ASK_QTY]
    book[book_cols] = book[book_cols].apply(pd.to_numeric, errors="coerce").astype(float)
    book.loc[stale, book_cols] = np.nan
    # mức không có lệnh SSI có thể ghi giá 0: để trống thay vì hiện "0,00"
    for px, qty in zip([*BID_PX, *ASK_PX], [*BID_QTY, *ASK_QTY]):
        empty = ~(book[px] > 0)
        book.loc[empty, [px, qty]] = np.nan
    d = daily[daily["day"] == f"{day:%Y-%m-%d}"] if not daily.empty else daily
    d = d[["symbol", "close", "price_change", "total_match", "total_match_value"]]
    m = book[["symbol", *book_cols]].merge(d, on="symbol", how="left")
    for c in ("close", "price_change", "total_match", "total_match_value"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m["ref_px"] = m["close"] - m["price_change"]
    m["last_px"], m["total_vol"], m["total_value"] = m["close"], m["total_match"], m["total_match_value"]
    for c in ("ceil_px", "floor_px", "last_vol", "foreign_net_val"):
        m[c] = np.nan
    return board_view(m)


def load_ssi_overview(db_path: Path, candle_db: Path, day: dt.date) -> dict:
    """Mọi thứ trang Tổng quan cần cho một ngày SSI: cards, minutes, board, book_ts (giờ thanh sổ lệnh mới nhất)."""
    minutes = load_index_minutes(candle_db, day)
    cards = ssi_index_cards(load_ssi_index(Path(db_path)), minutes, day)
    book = ssi_last_book(db_path, day)
    return {"cards": cards, "minutes": minutes, "board": ssi_board(book, load_ssi_daily(Path(db_path)), day),
            "book_ts": book["ts"].max() if not book.empty else None}
