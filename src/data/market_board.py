"""Bảng giá toàn thị trường (HOSE, HNX, UPCoM, ETF, chứng quyền) và hợp đồng tương lai VN30 từ NEO 4.6 và 4.9.

Khác bảng sổ lệnh VN30 (lưu từng phút để phân tích thanh khoản), bảng giá các sàn khác chỉ giữ ảnh chụp MỚI NHẤT
của mỗi ngày (ghi đè mỗi phút, nên cuối ngày còn lại bảng giá lúc đóng cửa) cộng chuỗi "độ sâu theo sàn" mỗi phút.
Lý do: 1.800 mã x 330 phút là hàng triệu dòng mà báo cáo không cần; cái cần là độ sâu theo thời gian.

Nguyên tắc dữ liệu đúng: giữ nguyên số NEO trả; giá <= 0 coi là chưa có lệnh/giao dịch (để trống chứ không điền); giá mức 1
là chữ ATO/ATC thì giữ nguyên chữ để bảng giá hiển thị như bảng điện.
"""
from __future__ import annotations

import pandas as pd

from neo_api.stream import map_record

from .schema import ASK_PX, ASK_QTY, AUCTION_TOKENS, BID_PX, BID_QTY, NUMERIC_COLUMNS, QUOTE_COLUMNS

# nhóm bảng giá -> (marketCode gửi 4.6, stockType). 4.5 cho biết mã nào thuộc nhóm nào.
GROUPS: dict[str, tuple[str, str]] = {
    "HOSE": ("HOSE", "ST"), "HNX": ("HNX", "ST"), "UPCOM": ("UPCOM", "ST"), "ETF": ("HOSE", "EF"), "CW": ("HOSE", "CW"),
}
GROUP_LABELS = {"VN30": "VN30", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCoM", "ETF": "ETF", "CW": "Chứng quyền",
                "FU": "Phái sinh"}
CHUNK = 300  # số mã mỗi lần gọi 4.6 (đã thử tới 409 mã vẫn chạy; 300 cho gọn URL)

PRICE_COLUMNS = [*BID_PX, *ASK_PX, "last_px", "ref_px", "ceil_px", "floor_px", "open_px", "high_px", "low_px"]
BOARD_COLUMNS = ["day", "grp", *QUOTE_COLUMNS]
DEPTH_COLUMNS = ["ts", "grp", "n_symbols", "bid_value", "ask_value"]
FUTURES_COLUMNS = [*QUOTE_COLUMNS, "name", "maturity", "open_interest"]


def _px(v: object) -> object:
    """Giá: giữ chữ ATO/ATC, còn lại ép số; <= 0 hoặc không đọc được thì để trống."""
    if isinstance(v, str) and v.strip().upper() in AUCTION_TOKENS:
        return v.strip().upper()
    n = pd.to_numeric(v, errors="coerce")
    return float("nan") if pd.isna(n) or n <= 0 else float(n)


def _clean(records: list[dict], ts: pd.Timestamp) -> pd.DataFrame:
    df = pd.DataFrame([map_record(r) for r in records if r.get("symbol")], columns=QUOTE_COLUMNS[1:])
    df["symbol"] = df["symbol"].astype("string").str.strip().str.upper()
    for c in NUMERIC_COLUMNS:
        df[c] = df[c].map(_px).astype(object) if c in PRICE_COLUMNS else pd.to_numeric(df[c], errors="coerce")
    df.insert(0, "ts", ts)
    return df.drop_duplicates("symbol", keep="last").reset_index(drop=True)


def board_frame(records: list[dict], ts: pd.Timestamp, grp: str) -> pd.DataFrame:
    df = _clean(records, ts)
    df.insert(0, "grp", grp)
    df.insert(0, "day", ts.strftime("%Y-%m-%d"))
    return df[BOARD_COLUMNS]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")  # chữ ATO/ATC -> NaN (không có giá để nhân)


def depth_row(board: pd.DataFrame, ts: pd.Timestamp, grp: str) -> pd.DataFrame:
    """Tổng giá trị (đồng) đặt mua / đặt bán ở 3 mức giá tốt nhất của mọi mã trong nhóm. Mã không có giá hợp lệ ở mức nào
    thì mức đó tính 0; n_symbols là số mã có ít nhất một mức mua hoặc bán."""
    bid = sum((_num(board[p]) * _num(board[q])).fillna(0) for p, q in zip(BID_PX, BID_QTY))
    ask = sum((_num(board[p]) * _num(board[q])).fillna(0) for p, q in zip(ASK_PX, ASK_QTY))
    return pd.DataFrame([{"ts": ts, "grp": grp, "n_symbols": int(((bid > 0) | (ask > 0)).sum()),
                          "bid_value": float(bid.sum()), "ask_value": float(ask.sum())}], columns=DEPTH_COLUMNS)


def futures_frame(records: list[dict], ts: pd.Timestamp, names: dict[str, str] | None = None) -> pd.DataFrame:
    """4.9 -> bảng hợp đồng. Giá là ĐIỂM chỉ số (không phải đồng). name lấy từ otherName của 4.5 (VN30F1M...)."""
    names = names or {}
    clean = _clean(records, ts)
    extra = {str(r.get("symbol", "")).strip().upper(): r for r in records}
    clean["name"] = [names.get(s) or s for s in clean["symbol"]]
    clean["maturity"] = [extra[s].get("maturityDate") for s in clean["symbol"]]
    clean["open_interest"] = pd.to_numeric([extra[s].get("openInterest") for s in clean["symbol"]], errors="coerce")
    return clean[FUTURES_COLUMNS]
