"""Lọc theo phiên giao dịch HOSE.

Chỉ giữ các lần chụp sổ lệnh trong phiên KHỚP LỆNH LIÊN TỤC:
  sáng  09:15 <= t < 11:30
  chiều 13:00 <= t < 14:30
Bị loại: ATO (09:00-09:15), nghỉ trưa (11:30-13:00), ATC (14:30-14:45) và thỏa thuận (14:45-15:00).
Lý do: trong các phiên khớp lệnh định kỳ, sổ lệnh không phản ánh thanh khoản liên tục (giá có thể
là 0 hoặc bên mua/bán chồng nhau trước khi khớp), làm méo spread và z-score cuốn chiếu.

Lưu ý: NEO biểu diễn giá ATO/ATC thế nào (số 0 hay chữ) chưa được kiểm tra, cần xem dữ liệu thật.
Bước làm sạch ở data/schema.py đã loại giá <= 0 và sổ lệnh chéo, nên đây là lớp lọc thứ hai theo giờ.
"""
from __future__ import annotations

import pandas as pd

MORNING = (9 * 60 + 15, 11 * 60 + 30)    # phút trong ngày, [bắt đầu, kết thúc)
AFTERNOON = (13 * 60, 14 * 60 + 30)


def continuous_mask(ts: pd.Series) -> pd.Series:
    """True cho các dấu thời gian (đã ở giờ Việt Nam) nằm trong phiên khớp lệnh liên tục."""
    minutes = ts.dt.hour * 60 + ts.dt.minute + ts.dt.second / 60
    morning = (minutes >= MORNING[0]) & (minutes < MORNING[1])
    afternoon = (minutes >= AFTERNOON[0]) & (minutes < AFTERNOON[1])
    return morning | afternoon


def filter_continuous(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Trả về (dữ liệu trong phiên liên tục, số dòng đã loại)."""
    if df.empty:
        return df, 0
    keep = continuous_mask(df["ts"])
    return df[keep].reset_index(drop=True), int((~keep).sum())
