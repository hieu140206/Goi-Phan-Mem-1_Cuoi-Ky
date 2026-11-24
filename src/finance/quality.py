"""Chất lượng chuỗi chụp sổ lệnh (mục B1 và B5): lần chụp không dùng được cho spread, lần chụp bị thiếu, dữ liệu cũ.

Nguyên tắc: không đoán, không điền. Dòng không hợp lệ cho spread được LOẠI khỏi khung phân tích và báo riêng; dòng đáng ngờ
(khoảng trống, dữ liệu cũ) vẫn được giữ nhưng ĐÁNH CỜ và ghi log. Chỉ xử lý ở lớp phân tích: không sửa dữ liệu đã ghi.

Dòng không hợp lệ cho spread (đều không vào xếp hạng, cảnh báo và mốc nền):
  - khóa trần/sàn: một bên sổ lệnh trống (data/schema.py, normalize_quotes);
  - giá tốt nhất chạm trần hoặc sàn khi còn đủ hai bên (`limit_touch_side`): giá bị kẹp bởi biên độ nên spread không phản ánh thanh khoản;
  - sổ lệnh chéo (bid >= ask), giá <= 0 hoặc thiếu: lỗi dữ liệu (cũng ở normalize_quotes, nay có thêm log).
Độ sâu của dòng khóa vẫn nằm trong bảng quotes và report["limit_locked"], nhưng không vào mốc nền.

Cờ đáng ngờ:
  - gap_flag: lần chụp đứng sau khoảng trống lớn hơn `max_gap_seconds` (mặc định 90 giây) so với lần chụp hợp lệ trước đó của cùng mã,
    cùng buổi (không tính khoảng nghỉ trưa); gap_s là độ dài khoảng trống;
  - stale_flag: sổ lệnh 3 mức của mã không đổi qua >= `stale_run_snapshots` lần chụp liên tiếp trong khi >= `stale_peer_share` số mã
    khác vẫn đổi ở các lần chụp đó (nghi dữ liệu đóng băng). Chỉ là nghi vấn, có thể một mã thật sự đứng yên.
Hai ngưỡng stale là lựa chọn ban đầu, chưa hiệu chỉnh (config.toml, nhóm [quality]).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from data.schema import ASK_PX, ASK_QTY, BID_PX, BID_QTY
from finance.sessions import continuous_mask
from model_config import section
from neo_api.config import TZ

_Q = section("quality")
log = logging.getLogger(__name__)
BOOK_COLS = [*BID_PX, *BID_QTY, *ASK_PX, *ASK_QTY]


def limit_touch_side(df: pd.DataFrame) -> pd.Series:
    """'trần' hoặc 'sàn' khi giá mua hoặc giá bán tốt nhất đúng bằng giá trần hoặc sàn mà còn đủ HAI bên sổ lệnh; rỗng nếu không.
    (Thiếu một bên là trường hợp khóa trần/sàn, xử lý ở data/schema.limit_lock_side.)"""
    nan = pd.Series(np.nan, index=df.index)
    ce = df["ceil_px"] if "ceil_px" in df else nan
    fl = df["floor_px"] if "floor_px" in df else nan
    bid, ask = df["bid_px1"], df["ask_px1"]
    both = (bid > 0) & (ask > 0)
    ceil_touch = both & (ce > 0) & ((bid == ce) | (ask == ce))
    floor_touch = both & (fl > 0) & ((bid == fl) | (ask == fl))
    return pd.Series(np.select([ceil_touch, floor_touch], ["trần", "sàn"], default=""), index=df.index)


def _session_key(d: pd.DataFrame) -> pd.Series:
    half = (d["ts"].dt.hour >= 12).astype(int).astype(str)
    return d["symbol"].astype(str) + "|" + d["ts"].dt.strftime("%Y-%m-%d") + "|" + half


def add_quality_flags(df: pd.DataFrame, max_gap_seconds: float = _Q["max_gap_seconds"],
                      stale_run: int = _Q["stale_run_snapshots"], peer_share: float = _Q["stale_peer_share"]) -> pd.DataFrame:
    """Thêm gap_s, gap_flag, stale_flag (xem docstring mô-đun). Không loại dòng nào, không đổi thứ tự dòng."""
    out = df.copy()
    if out.empty:
        out["gap_s"], out["gap_flag"], out["stale_flag"] = np.nan, False, False
        return out
    d = out.sort_values(["symbol", "ts"], kind="stable")
    key = _session_key(d)
    gap = d.groupby(key)["ts"].diff().dt.total_seconds()
    gap_flag = gap > max_gap_seconds

    sig = pd.Series(pd.util.hash_pandas_object(d[BOOK_COLS], index=False).to_numpy(), index=d.index)
    prev = sig.groupby(key).shift()
    has_prev = prev.notna()
    changed = (sig != prev) & has_prev
    unchanged = (sig == prev) & has_prev
    peer = changed.astype(float).groupby(d["ts"].to_numpy()).transform("mean")      # tỷ lệ mã có đổi ở cùng thời điểm
    s = (unchanged & (peer >= peer_share)).astype(int)
    run = (s != s.groupby(key).shift(fill_value=0)).cumsum()
    stale_flag = (s.groupby([key, run]).cumsum() * s) >= stale_run

    out["gap_s"] = gap.reindex(out.index)
    out["gap_flag"] = gap_flag.reindex(out.index).fillna(False).astype(bool)
    out["stale_flag"] = stale_flag.reindex(out.index).fillna(False).astype(bool)
    if out["gap_flag"].any():
        by = out.loc[out["gap_flag"], "symbol"].value_counts()
        log.warning("%d lần chụp đứng sau khoảng trống > %.0f giây ở %d mã (nhiều nhất: %s=%d); đã đánh cờ gap_flag.",
                    int(out["gap_flag"].sum()), max_gap_seconds, len(by), by.index[0], int(by.iloc[0]))
    if out["stale_flag"].any():
        by = out.loc[out["stale_flag"], "symbol"].value_counts()
        log.warning("%d lần chụp nghi dữ liệu cũ (sổ lệnh không đổi >= %d lần chụp trong khi các mã khác đổi) ở %d mã (nhiều nhất: %s=%d).",
                    int(out["stale_flag"].sum()), stale_run, len(by), by.index[0], int(by.iloc[0]))
    return out


def session_row_counts(raw: pd.DataFrame) -> pd.Series:
    """Số dòng THÔ của từng mã nằm trong phiên khớp lệnh liên tục: mẫu số để tính tỷ lệ lần chụp không hợp lệ."""
    ts = pd.to_datetime(raw["ts"], errors="coerce")
    ts = ts.dt.tz_localize(TZ) if ts.dt.tz is None else ts.dt.tz_convert(TZ)
    sym = raw["symbol"].astype("string").str.strip().str.upper()
    m = ts.notna() & sym.notna() & continuous_mask(ts)
    return sym[m].astype(str).value_counts()


def quality_table(raw: pd.DataFrame, kept: pd.DataFrame, locked: pd.DataFrame, touch: pd.DataFrame) -> pd.DataFrame:
    """Bảng theo mã: rows (dòng thô trong phiên liên tục), kept (dùng được), invalid, invalid_rate (%), locked (khóa trần/sàn),
    touch (giá tốt nhất chạm trần/sàn), other (sổ chéo, giá lỗi, trùng...), gaps, stale. locked và touch là dòng đã loại khỏi kept."""
    total = session_row_counts(raw)

    def per_symbol(frame: pd.DataFrame, col: str | None = None) -> pd.Series:
        if frame is None or frame.empty:
            return pd.Series(dtype=float)
        sel = frame if col is None else frame[frame[col].fillna(False).astype(bool)]
        return sel.groupby("symbol").size()

    syms = sorted(set(total.index) | set(kept["symbol"].astype(str).unique()))
    t = pd.DataFrame(index=pd.Index(syms, name="symbol"))
    t["rows"] = total.reindex(t.index).fillna(0).astype(int)
    t["kept"] = per_symbol(kept).reindex(t.index).fillna(0).astype(int)
    t["locked"] = per_symbol(locked).reindex(t.index).fillna(0).astype(int)
    t["touch"] = per_symbol(touch).reindex(t.index).fillna(0).astype(int)
    t["invalid"] = (t["rows"] - t["kept"]).clip(lower=0)
    t["other"] = (t["invalid"] - t["locked"] - t["touch"]).clip(lower=0)
    t["invalid_rate"] = np.where(t["rows"] > 0, t["invalid"] / t["rows"].where(t["rows"] > 0) * 100, np.nan)
    t["gaps"] = per_symbol(kept, "gap_flag").reindex(t.index).fillna(0).astype(int) if "gap_flag" in kept else 0
    t["stale"] = per_symbol(kept, "stale_flag").reindex(t.index).fillna(0).astype(int) if "stale_flag" in kept else 0
    return t.reset_index()
