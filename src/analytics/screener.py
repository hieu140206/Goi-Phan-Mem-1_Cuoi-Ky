"""Bộ lọc cổ phiếu VN30: Radar thanh khoản làm cổng, rồi xếp hạng theo dòng tiền nước ngoài và động lượng.

Thuần pandas, không phụ thuộc Streamlit. Nguyên tắc dữ liệu đúng: thiếu thì NaN, không đoán, không nội suy.

Quy trình:
  1. `liquidity_gate`: mã thanh khoản yếu bị Loại; mã có đợt cảnh báo là Chú ý; còn lại Đạt.
  2. `intraday_factors` / `momentum`: yếu tố động lượng (trong phiên, nhiều phiên) và tỷ lệ NN ròng.
  3. `screen`: điểm 0-100 = trung bình thứ hạng phần trăm các yếu tố, chỉ xếp trong nhóm qua cổng.
  4. `market_context`: bối cảnh thị trường, chỉ nêu sự kiện (tăng/giảm, dấu dương/âm), không tự đặt ngưỡng.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from finance.factors import add_factors
from neo_api.config import TZ

ATC_DONE = dt.time(14, 45)          # từ giờ này giá đã qua ATC, coi là giá đóng cửa chính thức
DEFAULT_FACTORS = ["foreign_ratio", "mom_rel"]
GATE_FAIL, GATE_WATCH, GATE_PASS = "Loại", "Chú ý", "Đạt"


def _pos(s: pd.Series) -> pd.Series:
    """Ép số; <= 0 hoặc không đọc được (chữ ATO/ATC) thì NaN."""
    n = pd.to_numeric(s, errors="coerce")
    return n.where(n > 0)


def _vn_time(ts: pd.Series) -> pd.Series:
    t = pd.to_datetime(ts)
    return t.dt.tz_localize(TZ) if t.dt.tz is None else t.dt.tz_convert(TZ)


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


def _num(x: object) -> float | None:
    v = pd.to_numeric(x, errors="coerce")
    return None if pd.isna(v) else float(v)


def _fmt(x: float, digits: int = 2) -> str:
    """Kiểu Việt Nam như phần còn lại của app: dấu chấm ngăn nghìn, dấu phẩy thập phân (1.234,5)."""
    return f"{x:,.{digits}f}".replace(",", "§").replace(".", ",").replace("§", ".")


# 1. Giá đóng cửa mỗi ngày từ bảng `board`
def daily_closes_from_board(board: pd.DataFrame) -> pd.DataFrame:
    """Mỗi (mã, ngày) của nhóm VN30 một dòng: symbol, day, close, ref, total_value, foreign_net_val, ts, final.
    final = True chỉ khi ảnh chụp lúc >= 14:45 giờ VN (đã qua ATC); trước đó close chỉ là giá tạm tính."""
    cols = ["symbol", "day", "close", "ref", "total_value", "foreign_net_val", "ts", "final"]
    if board is None or board.empty:
        return pd.DataFrame(columns=cols)
    b = board[board["grp"] == "VN30"].copy()
    if b.empty:
        return pd.DataFrame(columns=cols)
    b["ts"] = _vn_time(b["ts"])
    b = b.sort_values("ts").groupby(["symbol", "day"]).tail(1)
    out = pd.DataFrame({
        "symbol": b["symbol"].to_numpy(),
        "day": _as_date(b["day"]).to_numpy(),
        "close": _pos(b["last_px"]).to_numpy(),
        "ref": _pos(b["ref_px"]).to_numpy(),
        "total_value": pd.to_numeric(b["total_value"], errors="coerce").to_numpy(),
        "foreign_net_val": pd.to_numeric(b["foreign_net_val"], errors="coerce").to_numpy(),
        "ts": b["ts"].to_numpy(),
        "final": (b["ts"].dt.time >= ATC_DONE).to_numpy(),
    })
    out["ts"] = pd.to_datetime(out["ts"], utc=True).dt.tz_convert(TZ)
    return out.sort_values(["symbol", "day"]).reset_index(drop=True)[cols]


# 2. Động lượng nhiều phiên
def momentum(closes: pd.DataFrame, n: int, index_closes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Lợi suất n phiên = close hôm nay / close cách n phiên - 1, chỉ dùng dòng final.

    "Cách n phiên" tính theo lịch phiên chung (mọi ngày có trong `closes`, kể cả ngày chưa chốt), không theo số dòng
    của từng mã. Ngày chưa chốt (final = False) vẫn giữ chỗ trong lịch nhưng giá là NaN, nên lợi suất chạm tới ngày
    đó là NaN; mã thiếu ngày cũng NaN chứ không lấy ngày gần nhất (không nội suy).
    Có `index_closes` (day, close của VN30) thì thêm index_mom_n và rel_mom_n = mom_n - index_mom_n cùng kỳ."""
    col = f"mom_{n}"
    c = closes.copy()
    c["day"] = _as_date(c["day"])
    c["close"] = _pos(c["close"])
    if "final" in c:
        c["close"] = c["close"].where(c["final"].astype(bool))
    c = c[["symbol", "day", "close"]].sort_values(["symbol", "day"]).reset_index(drop=True)
    cal = sorted(c["day"].unique())
    back = {d: (cal[i - n] if i - n >= 0 else None) for i, d in enumerate(cal)}
    c["day_back"] = c["day"].map(back)
    prev = c[["symbol", "day", "close"]].rename(columns={"day": "day_back", "close": "close_back"})
    c = c.merge(prev, on=["symbol", "day_back"], how="left")
    c[col] = c["close"] / c["close_back"] - 1
    if index_closes is not None and not index_closes.empty:
        ix = pd.Series(_pos(index_closes["close"]).to_numpy(), index=_as_date(index_closes["day"]))
        ix = ix[~ix.index.duplicated(keep="last")]
        now = c["day"].map(ix)
        then = c["day_back"].map(lambda d: ix.get(d, np.nan) if d is not None else np.nan)
        c[f"index_mom_{n}"] = now.astype(float) / then.astype(float) - 1
        c[f"rel_mom_{n}"] = c[col] - c[f"index_mom_{n}"]
    return c.drop(columns=["close_back"]).sort_values(["symbol", "day"]).reset_index(drop=True)


# 3. Yếu tố trong phiên
def intraday_factors(snap: pd.DataFrame, index_change: float | None = None) -> pd.DataFrame:
    """Ảnh chụp mới nhất của mỗi mã -> mom_intraday = last_px/ref_px - 1, foreign_ratio = NN ròng / tổng giá trị.
    `index_change` là % thay đổi VN30 đúng đơn vị NEO (cột pct_change của index_cards: 0,52 nghĩa là 0,52%);
    có thì mom_rel = mom_intraday - index_change/100, không có thì mom_rel = NaN."""
    cols = ["symbol", "ts", "last_px", "ref_px", "mom_intraday", "foreign_ratio", "mom_rel"]
    if snap is None or snap.empty:
        return pd.DataFrame(columns=cols)
    d = snap.sort_values("ts").groupby("symbol").tail(1).copy()
    for c in ("last_px", "ref_px", "open_px", "high_px", "low_px"):
        d[c] = _pos(d[c]) if c in d else np.nan
    for c in ("foreign_net_val", "total_value"):
        d[c] = pd.to_numeric(d[c], errors="coerce") if c in d else np.nan
    f = add_factors(d)
    f["mom_intraday"] = f["momentum_from_ref"]
    f["foreign_ratio"] = f["foreign_flow_ratio"]
    ok = index_change is not None and not pd.isna(index_change)
    f["mom_rel"] = f["mom_intraday"] - float(index_change) / 100 if ok else np.nan
    return f[cols].sort_values("symbol").reset_index(drop=True)


# 4. Cổng thanh khoản
def liquidity_gate(ranking: pd.DataFrame, alert_counts: pd.Series | None, min_score: float = 33.3) -> pd.DataFrame:
    """ranking: kết quả rank_symbols (symbol, score). alert_counts: số đợt cảnh báo theo mã (thiếu mã = 0 đợt).
    Loại nếu score <= min_score (hoặc không có điểm); Chú ý nếu có >= 1 đợt cảnh báo; còn lại Đạt.
    Dùng <= để khớp mốc "Yếu" của Radar (rank_symbols xếp điểm từ 33,3 trở xuống vào nhóm Yếu)."""
    out = ranking[["symbol", "score"]].copy()
    counts = alert_counts if alert_counts is not None else pd.Series(dtype=float)
    out["alerts"] = out["symbol"].map(counts).fillna(0).astype(int)
    gate, reason = [], []
    for score, n in zip(out["score"], out["alerts"]):
        if pd.isna(score):
            gate.append(GATE_FAIL); reason.append("Chưa có điểm thanh khoản")
        elif score <= min_score:
            gate.append(GATE_FAIL); reason.append(f"Điểm thanh khoản {_fmt(score, 1)} ≤ {_fmt(min_score, 1)}")
        elif n >= 1:
            gate.append(GATE_WATCH); reason.append(f"{n} đợt cảnh báo thanh khoản")
        else:
            gate.append(GATE_PASS); reason.append("Thanh khoản đạt, không có cảnh báo")
    out["gate"], out["gate_reason"] = gate, reason
    return out.reset_index(drop=True)


# 5. Xếp hạng
def _pct_rank(s: pd.Series) -> pd.Series:
    """Thứ hạng phần trăm 0-100 trong các giá trị có; lớn hơn = tốt hơn; chỉ 1 giá trị thì 50; NaN giữ NaN."""
    n = s.notna().sum()
    if n == 0:
        return pd.Series(np.nan, index=s.index)
    if n == 1:
        return pd.Series(50.0, index=s.index).where(s.notna())
    return (s.rank(method="average") - 1) / (n - 1) * 100


def screen(factors: pd.DataFrame, gate: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Điểm 0-100 = trung bình (trọng số bằng nhau) thứ hạng phần trăm các yếu tố, CHỈ xếp trong nhóm gate != Loại.
    Mặc định foreign_ratio và mom_rel; mom_rel toàn NaN (chưa có % VN30) thì dùng mom_intraday.
    Mã thiếu một yếu tố: trung bình trên các yếu tố có; thiếu hết: NaN. Mã Loại (hoặc không có trong cổng): NaN, xếp cuối.
    Cột yếu tố đã dùng nằm ở out.attrs["factors"]."""
    df = factors.merge(gate[["symbol", "score", "alerts", "gate", "gate_reason"]]
                       .rename(columns={"score": "liq_score"}), on="symbol", how="outer")
    miss = df["gate"].isna()
    df.loc[miss, "gate"] = GATE_FAIL
    df.loc[miss, "gate_reason"] = "Không có trong Radar thanh khoản"
    if columns is None:
        columns = list(DEFAULT_FACTORS)
        if "mom_rel" not in df or df["mom_rel"].isna().all():
            columns = ["foreign_ratio", "mom_intraday"]
    passed = df["gate"] != GATE_FAIL
    rank_cols = []
    for c in columns:
        rc = f"rank_{c}"
        vals = pd.to_numeric(df[c], errors="coerce") if c in df else pd.Series(np.nan, index=df.index)
        df[rc] = np.nan
        df.loc[passed, rc] = _pct_rank(vals[passed])
        rank_cols.append(rc)
    df["screen_score"] = df[rank_cols].mean(axis=1, skipna=True).round(1)
    df.loc[~passed, "screen_score"] = np.nan
    df["_order"] = np.where(passed, 0, 1)
    df = df.sort_values(["_order", "screen_score", "symbol"], ascending=[True, False, True], na_position="last")
    out = df.drop(columns="_order").reset_index(drop=True)
    out.attrs["factors"] = columns
    return out


# 6. Bối cảnh thị trường
def market_context(cards: pd.DataFrame | None, breadth: pd.DataFrame | None, fut_view: pd.DataFrame | None,
                   vn30_snap: pd.DataFrame | None) -> dict:
    """Sự kiện thị trường từ index_cards, breadth_frame, futures_view và ảnh chụp VN30; phần thiếu dữ liệu là None.
    Chỉ so với 0 (tăng/giảm, mua/bán ròng, cao/thấp hơn chỉ số); không có ngưỡng tự đặt."""
    ctx: dict = {"vnindex_advances": None, "vnindex_declines": None, "vn30_pct": None,
                 "basis_contract": None, "basis": None, "vn30_foreign_net": None}
    if breadth is not None and not breadth.empty and "index_code" in breadth:
        r = breadth[breadth["index_code"] == "VNINDEX"]
        if not r.empty:
            ctx["vnindex_advances"] = _num(r["advances"].iloc[-1])
            ctx["vnindex_declines"] = _num(r["declines"].iloc[-1])
    if cards is not None and not cards.empty and "index_code" in cards:
        r = cards[cards["index_code"] == "VN30"]
        if not r.empty:
            ctx["vn30_pct"] = _num(r["pct_change"].iloc[-1])
    if fut_view is not None and not fut_view.empty and "basis" in fut_view:
        ctx["basis_contract"] = str(fut_view["symbol"].iloc[0])   # futures_view đã xếp theo ngày đáo hạn
        ctx["basis"] = _num(fut_view["basis"].iloc[0])
    if vn30_snap is not None and not vn30_snap.empty:
        col = "foreign_net_val" if "foreign_net_val" in vn30_snap else "foreign_net" if "foreign_net" in vn30_snap else None
        if col:
            s = vn30_snap.sort_values("ts").groupby("symbol").tail(1) if "ts" in vn30_snap else vn30_snap
            ctx["vn30_foreign_net"] = _num(pd.to_numeric(s[col], errors="coerce").sum(min_count=1))

    parts = []
    a, d = ctx["vnindex_advances"], ctx["vnindex_declines"]
    if a is not None and d is not None:
        side = "nhiều mã tăng hơn" if a > d else "nhiều mã giảm hơn" if a < d else "số mã tăng bằng số mã giảm"
        parts.append(f"VN-Index có {a:.0f} mã tăng, {d:.0f} mã giảm ({side}).")
    p = ctx["vn30_pct"]
    if p is not None:
        parts.append(f"VN30 {'tăng' if p > 0 else 'giảm' if p < 0 else 'đứng'} {_fmt(abs(p))}%." if p != 0
                     else "VN30 đứng giá.")
    b = ctx["basis"]
    if b is not None:
        rel = "thấp hơn" if b < 0 else "cao hơn" if b > 0 else "bằng"
        parts.append(f"Hợp đồng {ctx['basis_contract']} {rel} chỉ số VN30"
                     + (f" {_fmt(abs(b))} điểm." if b != 0 else "."))
    f = ctx["vn30_foreign_net"]
    if f is not None:
        act = "mua ròng" if f > 0 else "bán ròng" if f < 0 else "cân bằng mua bán"
        parts.append(f"Khối ngoại {act} ở rổ VN30" + (f" {_fmt(abs(f) / 1e9, 1)} tỷ đồng." if f != 0 else "."))
    ctx["summary"] = " ".join(parts) if parts else "Chưa có dữ liệu bối cảnh thị trường."
    return ctx
