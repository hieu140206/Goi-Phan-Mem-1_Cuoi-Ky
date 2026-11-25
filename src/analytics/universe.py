"""Bộ lọc toàn HOSE: cổng thanh khoản theo giá trị khớp, động lượng 6-1, dòng tiền nước ngoài (chỉ để tham khảo).

Không import streamlit (để kiểm thử được). Mọi ngưỡng ở config.toml, mục [universe]; hàm nhận tham số để test đổi được.
Nguồn: bảng giá `board` nhóm HOSE (NEO, ảnh chụp cuối ngày) cho giá trị khớp và nước ngoài; nến ngày SSI cho động lượng
(giá ĐIỀU CHỈNH cổ tức, nên chỉ dùng tỷ lệ giữa các ngày của chính mã, không trộn với giá NEO).

Thứ tự áp dụng: thanh khoản trước, động lượng sau. Nhãn trạng thái (mỗi mã đúng một nhãn):
  Thiếu dữ liệu < Ít giao dịch < Không đạt thanh khoản < (Chưa đủ lịch sử | Dữ liệu cũ) < Đạt.
Hai nhãn giữa chỉ gắn cho mã đã qua cổng thanh khoản nhưng chưa tính được động lượng. "Sát ngưỡng" là CỜ riêng trên mã Đạt."""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from model_config import section

TZ = "Asia/Ho_Chi_Minh"
PASS = "Đạt"
FAIL = "Không đạt thanh khoản"
FEW = "Ít giao dịch"
MISSING = "Thiếu dữ liệu"
NO_HISTORY = "Chưa đủ lịch sử"
STALE = "Dữ liệu cũ"
MOM_OK = "Đủ"
STATUS_ORDER = [PASS, NO_HISTORY, STALE, FAIL, FEW, MISSING]
STOCK_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")   # cổ phiếu HOSE: đúng 3 ký tự (ETF, chứng quyền, chứng chỉ quỹ dài hơn)
OVER_TOL = 1.0001                               # sai số cho phép khi so giá trị nước ngoài với giá trị khớp tổng


def liquidity_threshold(position_vnd: float | None = None, max_participation: float | None = None) -> float:
    """Ngưỡng T (VND) = vị thế dự kiến / tỷ lệ tham gia tối đa vào giá trị khớp một phiên."""
    cfg = section("universe")
    pos = cfg["position_vnd"] if position_vnd is None else position_vnd
    part = cfg["max_participation"] if max_participation is None else max_participation
    if pos <= 0 or not 0 < part <= 1:
        raise ValueError("position_vnd phải dương và max_participation nằm trong (0, 1]")
    return float(pos) / float(part)


def is_stock_symbol(symbol: object) -> bool:
    return isinstance(symbol, str) and bool(STOCK_RE.match(symbol))


def _day(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.normalize()


# 1. Ngày đủ và cổng thanh khoản
def full_days(board: pd.DataFrame, after: str | None = None) -> list[str]:
    """Các ngày (YYYY-MM-DD) mà lần chụp bảng giá cuối ngày từ giờ `after` trở đi (đã có khớp ATC). Cột cần: day, ts.
    Ngày chụp sớm hơn (giữa phiên, hoặc 14:45:00 khi ATC chưa xong) bị loại vì khối lượng và giá trị còn thiếu."""
    after = after or section("universe")["full_day_after"]
    if board is None or board.empty:
        return []
    ts = pd.to_datetime(board["ts"], utc=True).dt.tz_convert(TZ)
    last = ts.groupby(board["day"].astype(str)).max()
    cut = pd.Timestamp(f"2000-01-01 {after}").time()
    return sorted(d for d, t in last.items() if t.time() >= cut)


def liquidity_gate(rows: pd.DataFrame, days: list[str], symbols: list[str] | None = None, threshold: float | None = None,
                   min_days_ratio: float | None = None, near_factor: float | None = None) -> pd.DataFrame:
    """Cổng thanh khoản của Bộ lọc toàn HOSE. rows: day, symbol, total_value (giá trị khớp cả ngày, đồng) của các ngày đủ.

    Mỗi mã: trung vị giá trị khớp mỗi ngày trên TOÀN BỘ `days`. Ngày mã không giao dịch (giá trị trống hoặc 0) và ngày mã không có
    trong ảnh chụp đều tính 0 (không bỏ khỏi mẫu, cũng là cách thận trọng: chỉ làm mã khó qua cổng hơn). Cổng THẬT là T:
    trung vị >= T thì Đạt (đúng bằng T cũng Đạt). near = Đạt nhưng trung vị < near_factor x T (cờ "Sát ngưỡng").
    Số ngày có giao dịch phải >= min_days_ratio x số ngày, không thì "Ít giao dịch". Mã không có dòng nào trong các ngày đủ:
    "Thiếu dữ liệu". `symbols` thêm mã cần xét (ví dụ mã chỉ có ở ngày chụp dở dang); chỉ giữ mã dạng cổ phiếu."""
    cfg = section("universe")
    T = liquidity_threshold() if threshold is None else float(threshold)
    ratio = cfg["min_days_ratio"] if min_days_ratio is None else min_days_ratio
    near_f = cfg["near_factor"] if near_factor is None else near_factor
    cols = ["symbol", "median_value", "trade_days", "n_days", "gate", "near", "gate_reason"]
    n = len(days)
    r = rows[rows["day"].astype(str).isin([str(d) for d in days])] if rows is not None and not rows.empty else pd.DataFrame(
        columns=["day", "symbol", "total_value"])
    names = sorted({s for s in (set(r["symbol"]) | set(symbols or [])) if is_stock_symbol(s)})
    if n == 0 or not names:
        return pd.DataFrame(columns=cols)
    v = pd.to_numeric(r["total_value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    piv = (pd.DataFrame({"day": r["day"].astype(str), "symbol": r["symbol"], "v": v})
           .pivot_table(index="symbol", columns="day", values="v", aggfunc="sum")
           .reindex(index=names, columns=[str(d) for d in days]))
    present = piv.notna().any(axis=1)
    piv = piv.fillna(0.0)
    need = math.ceil(round(ratio * n, 9))
    out = []
    for sym in names:
        vals = piv.loc[sym].to_numpy()
        med, td = float(np.median(vals)), int((vals > 0).sum())
        if not present[sym]:
            gate, why = MISSING, "Không có dòng nào trong các ngày đủ"
        elif td < need:
            gate, why = FEW, f"Chỉ {td}/{n} ngày có giao dịch (cần ít nhất {need})"
        elif med < T:
            gate, why = FAIL, f"Giá trị khớp trung vị {med / 1e9:.2f} tỷ/ngày < {T / 1e9:.2f} tỷ"
        else:
            gate, why = PASS, f"Giá trị khớp trung vị {med / 1e9:.2f} tỷ/ngày ≥ {T / 1e9:.2f} tỷ"
        out.append({"symbol": sym, "median_value": med, "trade_days": td, "n_days": n, "gate": gate,
                    "near": gate == PASS and med < near_f * T, "gate_reason": why})
    return pd.DataFrame(out)[cols]


# 2. Nước ngoài (tham khảo)
def foreign_window(rows: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    """Nước ngoài trên cả cửa sổ `days`: foreign_ratio = tổng ròng / tổng giá trị khớp (tổng chia tổng, không trung bình tỷ lệ
    từng ngày vì ngày giao dịch mỏng làm tỷ lệ nhảy mạnh). foreign_over = có ít nhất một ngày mà mua hoặc bán nước ngoài vượt giá trị
    khớp tổng: dấu hiệu giá trị nước ngoài có cả giao dịch thỏa thuận (suy ra, chưa xác nhận). Mã không có giá trị khớp: tỷ lệ NaN.
    Cột cần: day, symbol, total_value, foreign_buy_val, foreign_sell_val, foreign_net_val. Khối lượng nước ngoài trống nghĩa là bên
    đó không có giao dịch, nên chỉ dùng cột giá trị."""
    cols = ["symbol", "foreign_net", "foreign_value", "foreign_ratio", "foreign_over"]
    if rows is None or rows.empty:
        return pd.DataFrame(columns=cols)
    r = rows[rows["day"].astype(str).isin([str(d) for d in days])].copy()
    if r.empty:
        return pd.DataFrame(columns=cols)
    for c in ("total_value", "foreign_buy_val", "foreign_sell_val", "foreign_net_val"):
        r[c] = pd.to_numeric(r[c], errors="coerce")
    tv = r["total_value"].fillna(0.0)
    r["over"] = ((r["foreign_buy_val"].fillna(0) > tv * OVER_TOL) | (r["foreign_sell_val"].fillna(0) > tv * OVER_TOL))
    g = r.groupby("symbol").agg(foreign_net=("foreign_net_val", "sum"), foreign_value=("total_value", "sum"),
                                foreign_over=("over", "any")).reset_index()
    g["foreign_ratio"] = np.where(g["foreign_value"] > 0, g["foreign_net"] / g["foreign_value"].where(g["foreign_value"] > 0), np.nan)
    return g[cols]


# 3. Động lượng 6-1 từ nến ngày
def market_days(closes: pd.DataFrame, min_symbols: int | None = None) -> list[pd.Timestamp]:
    """Phiên thị trường = ngày có nến của ít nhất `min_symbols` mã (để một ngày lẻ tẻ không làm lệch lịch)."""
    n = section("universe")["market_day_min_symbols"] if min_symbols is None else min_symbols
    if closes is None or closes.empty:
        return []
    cnt = closes.assign(day=_day(closes["day"])).groupby("day")["symbol"].nunique()
    return sorted(cnt[cnt >= n].index)


def _price_at(days: np.ndarray, closes: np.ndarray, point: pd.Timestamp, max_gap_days: int) -> tuple[float, pd.Timestamp] | None:
    """Giá gần nhất KHÔNG muộn hơn `point`; None nếu không có hoặc cách quá max_gap_days (mã ngừng giao dịch lâu không mượn giá xa)."""
    i = int(np.searchsorted(days, np.datetime64(point), side="right")) - 1
    if i < 0:
        return None
    d = pd.Timestamp(days[i])
    if (point - d).days > max_gap_days or not (closes[i] > 0):
        return None
    return float(closes[i]), d


def momentum_6_1(closes: pd.DataFrame, window_months: int | None = None, skip_months: int | None = None,
                 ref_months: int | None = None, max_gap_days: int | None = None, max_stale_sessions: int | None = None,
                 jump_pct: float | None = None, min_symbols: int | None = None) -> pd.DataFrame:
    """Động lượng 6-1 theo MỐC LỊCH với MỘT ngày tham chiếu chung (ngày nến mới nhất của thị trường) cho mọi mã.

    mom = giá(T - skip) / giá(T - window) - 1; T là ngày tham chiếu chung, không phải ngày nến cuối của từng mã. Giá lấy là giá gần
    nhất không muộn hơn mốc nhưng không cách mốc quá max_gap_days. mom_ref = giá(T) / giá(T - ref_months) - 1 (tham khảo, không xếp hạng).
    Nến cuối của mã cách T quá max_stale_sessions phiên thị trường: "Dữ liệu cũ" (không tính). Thiếu giá ở một mốc: "Chưa đủ lịch sử".
    jump = trong khoảng giá đã dùng có |lợi suất 1 ngày| > jump_pct giữa hai phiên thị trường LIỀN KỀ (chuỗi bị đứt hoặc điều chỉnh dở).
    closes: symbol, day, close (giá nến ngày SSI, đã điều chỉnh; chỉ lấy tỷ lệ trong cùng mã, cùng một lần nạp chuỗi)."""
    cfg = section("universe")
    w = cfg["momentum_window_months"] if window_months is None else window_months
    s = cfg["momentum_skip_months"] if skip_months is None else skip_months
    rf = cfg["momentum_ref_months"] if ref_months is None else ref_months
    gap = cfg["max_gap_days"] if max_gap_days is None else max_gap_days
    stale = cfg["max_stale_sessions"] if max_stale_sessions is None else max_stale_sessions
    jp = cfg["jump_pct"] if jump_pct is None else jump_pct
    cols = ["symbol", "mom", "mom_ref", "mom_status", "jump", "ref_day", "last_day", "start_day", "end_day"]
    mdays = market_days(closes, min_symbols)
    if not mdays:
        return pd.DataFrame(columns=cols)
    ref = mdays[-1]
    midx = {d: i for i, d in enumerate(mdays)}
    c = closes.assign(day=_day(closes["day"]), close=pd.to_numeric(closes["close"], errors="coerce"))
    c = c[c["day"] <= ref].dropna(subset=["close"]).sort_values(["symbol", "day"])
    t_start, t_end, t_ref = ref - pd.DateOffset(months=w), ref - pd.DateOffset(months=s), ref - pd.DateOffset(months=rf)
    out = []
    for sym, g in c.groupby("symbol"):
        days, px = g["day"].to_numpy(dtype="datetime64[ns]"), g["close"].to_numpy(dtype=float)
        last = pd.Timestamp(days[-1])
        row = {"symbol": sym, "mom": np.nan, "mom_ref": np.nan, "mom_status": MOM_OK, "jump": False, "ref_day": ref,
               "last_day": last, "start_day": pd.NaT, "end_day": pd.NaT}
        late = sum(1 for d in mdays if d > last)
        if late > stale:
            row["mom_status"] = STALE
            out.append(row)
            continue
        a, b = _price_at(days, px, t_start, gap), _price_at(days, px, t_end, gap)
        if a is None or b is None:
            row["mom_status"] = NO_HISTORY
            out.append(row)
            continue
        row["mom"], row["start_day"], row["end_day"] = b[0] / a[0] - 1, a[1], b[1]
        now, past = _price_at(days, px, ref, gap), _price_at(days, px, t_ref, gap)
        if now is not None and past is not None:
            row["mom_ref"] = now[0] / past[0] - 1
        seg = (days >= np.datetime64(a[1])) & (days <= np.datetime64(b[1]))
        sd, sp = days[seg], px[seg]
        for k in range(1, len(sd)):
            i0, i1 = midx.get(pd.Timestamp(sd[k - 1])), midx.get(pd.Timestamp(sd[k]))
            if i0 is not None and i1 is not None and i1 - i0 == 1 and abs(sp[k] / sp[k - 1] - 1) > jp:
                row["jump"] = True
                break
        out.append(row)
    return pd.DataFrame(out)[cols]


def _pct_rank(s: pd.Series) -> pd.Series:
    """Thứ hạng phần trăm 0-100 trong các giá trị có; lớn hơn = tốt hơn; chỉ 1 giá trị thì 50; NaN giữ NaN."""
    n = s.notna().sum()
    if n == 0:
        return pd.Series(np.nan, index=s.index)
    if n == 1:
        return pd.Series(50.0, index=s.index).where(s.notna())
    return (s.rank(method="average") - 1) / (n - 1) * 100


# 4. Ghép lại
def screen_universe(board: pd.DataFrame, closes: pd.DataFrame, after: str | None = None) -> pd.DataFrame:
    """Bộ lọc toàn HOSE. board: các dòng bảng giá nhóm HOSE của MỌI ngày đã ghi (day, ts, symbol, total_value, foreign_*).
    closes: nến ngày SSI (symbol, day, close). Trả mỗi mã một dòng, đã sắp thứ tự; thuộc tính: days (ngày đủ), threshold, ref_day.

    status = nhãn thanh khoản; riêng mã Đạt mà chưa tính được động lượng thì status là "Chưa đủ lịch sử" hoặc "Dữ liệu cũ" (mã vẫn
    hiện, không có xếp hạng). mom_rank = xếp hạng động lượng 0-100 (đơn nhân tố, chưa điều chỉnh biến động) CHỈ trong nhóm Đạt có động lượng.
    Cột nước ngoài chỉ để tham khảo, không vào xếp hạng ở v1."""
    days = full_days(board, after)
    stocks = board[board["symbol"].map(is_stock_symbol)] if board is not None and not board.empty else board
    gate = liquidity_gate(stocks if stocks is not None else pd.DataFrame(), days,
                          symbols=sorted(set(stocks["symbol"])) if stocks is not None and not stocks.empty else [])
    fx = foreign_window(stocks if stocks is not None else pd.DataFrame(), days)
    mom = momentum_6_1(closes)
    df = gate.merge(fx, on="symbol", how="left").merge(mom, on="symbol", how="left")
    df["mom_status"] = df["mom_status"].fillna(NO_HISTORY)
    passed = df["gate"] == PASS
    df["status"] = df["gate"]
    df.loc[passed & (df["mom_status"] != MOM_OK), "status"] = df.loc[passed & (df["mom_status"] != MOM_OK), "mom_status"]
    ranked = passed & (df["mom_status"] == MOM_OK) & df["mom"].notna()
    df["mom_rank"] = np.nan
    df.loc[ranked, "mom_rank"] = _pct_rank(df.loc[ranked, "mom"]).round(1)
    df["_o"] = df["status"].map({s: i for i, s in enumerate(STATUS_ORDER)})
    df = df.sort_values(["_o", "mom_rank", "median_value", "symbol"], ascending=[True, False, False, True], na_position="last")
    out = df.drop(columns="_o").reset_index(drop=True)
    out.attrs.update(days=days, threshold=liquidity_threshold(), ref_day=mom["ref_day"].iloc[0] if not mom.empty else pd.NaT)
    return out
