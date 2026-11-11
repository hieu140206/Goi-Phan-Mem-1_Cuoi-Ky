"""Dữ liệu cho trang Tổng quan thị trường: thẻ chỉ số, bảng giá, độ rộng, độ sâu, thanh khoản.

Nguồn:
  - bảng market_index trong market.db: bộ ghi lưu NEO 4.3 mỗi chu kỳ (điểm, thay đổi, tăng/giảm, giá trị giao dịch lũy kế);
  - data/raw/<ngày>/market.json: chuỗi theo phút (4.2) và 4.3 cuối ngày, dùng cho ngày ghi trước khi có bảng market_index;
  - bảng quotes: sổ lệnh 3 mức của 30 mã VN30 (giá, khối lượng, giá trị giao dịch, nước ngoài).
Các hàm ở đây thuần pandas, không phụ thuộc Streamlit nên kiểm thử được.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from neo_api.config import TZ

from .market import index_detail_frame, index_intraday_frame
from .schema import ASK_PX, ASK_QTY, BID_PX, BID_QTY

MAIN_INDICES = ["VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"]
INDEX_NAMES = {"VNINDEX": "VN-Index", "VN30": "VN30", "HNXINDEX": "HNX-Index", "UPCOMINDEX": "UPCoM-Index",
               "HNX30": "HNX30", "VN100": "VN100"}
EXCHANGE_OF = {"VNINDEX": "HOSE", "HNXINDEX": "HNX", "UPCOMINDEX": "UPCoM"}


def load_market_json(data_dir: Path, day: dt.date) -> dict:
    """data/raw/<ngày>/market.json do bộ ghi lưu cuối phiên. Không có file thì trả dict rỗng."""
    path = Path(data_dir) / "raw" / pd.Timestamp(day).strftime("%Y-%m-%d") / "market.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _day_rows(idx: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    if idx is None or idx.empty:
        return pd.DataFrame(columns=idx.columns if idx is not None else [])
    return idx[idx["ts"].dt.date == day]


def days_available(idx: pd.DataFrame, quotes: pd.DataFrame) -> list[dt.date]:
    days: set[dt.date] = set()
    for df in (idx, quotes):
        if df is not None and not df.empty:
            days |= set(df["ts"].dt.date.unique())
    return sorted(days)


def index_cards(idx: pd.DataFrame, day: dt.date, market_json: dict | None = None) -> pd.DataFrame:
    """Dòng mới nhất của mỗi chỉ số chính trong ngày, theo thứ tự VNINDEX, VN30, HNX, UPCoM.
    Ngày chưa có bảng market_index thì lấy 4.3 cuối ngày trong market.json (nếu có)."""
    rows = _day_rows(idx, day)
    if rows.empty and market_json and market_json.get("index_detail"):
        saved = pd.Timestamp(market_json.get("saved_at") or pd.Timestamp(day, tz=TZ))
        rows = index_detail_frame(market_json["index_detail"], saved.tz_convert(TZ))
    if rows.empty:
        return rows
    last = rows.sort_values("ts").groupby("index_code").tail(1).set_index("index_code")
    order = [c for c in MAIN_INDICES if c in last.index]
    return last.loc[order].reset_index()


def index_series(idx: pd.DataFrame, day: dt.date, code: str, market_json: dict | None = None) -> pd.DataFrame:
    """Chuỗi điểm chỉ số trong ngày (ts, value). Ưu tiên bảng market_index; nếu chưa có thì dùng 4.2 (theo phút)."""
    rows = _day_rows(idx, day)
    rows = rows[rows["index_code"] == code] if not rows.empty else rows
    if not rows.empty:
        return rows[["ts", "index_value"]].rename(columns={"index_value": "value"}).sort_values("ts").reset_index(drop=True)
    payload = (market_json or {}).get(f"intraday_{code}")
    if isinstance(payload, dict) and payload.get("index"):
        f = index_intraday_frame(payload, day)
        return f[["ts", "index_value"]].rename(columns={"index_value": "value"})
    return pd.DataFrame(columns=["ts", "value"])


def price_board(quotes: pd.DataFrame, day: dt.date, until: pd.Timestamp | None = None) -> pd.DataFrame:
    """Bảng giá 30 mã tại lần chụp mới nhất (hoặc mới nhất không vượt quá `until`) của ngày, giữ NGUYÊN đơn vị NEO:
    giá bằng đồng, khối lượng bằng cổ phiếu, giá trị bằng đồng. Việc đổi sang nghìn đồng/tỷ chỉ làm ở bước hiển thị.

    Cột thay đổi (+/-) và % tính từ giá khớp và giá tham chiếu (đã đối chiếu bằng dữ liệu thật: trùng priceChange của NEO).
    Trần/sàn/KL khớp thiếu (dữ liệu ghi trước khi có cột này và chưa backfill) để trống, không ước lượng."""
    d = quotes[quotes["ts"].dt.date == day]
    if until is not None:
        d = d[d["ts"] <= until]
    if d.empty:
        return pd.DataFrame()
    d = d[d["ts"] == d["ts"].max()]
    col = lambda name: d[name].to_numpy() if name in d else np.full(len(d), np.nan)  # noqa: E731
    ref = pd.Series(col("ref_px")).where(lambda s: s > 0)
    last = pd.Series(col("last_px"))
    out = pd.DataFrame({
        "symbol": d["symbol"].to_numpy(), "ref": ref.to_numpy(), "ceil": col("ceil_px"), "floor": col("floor_px"),
        "bid_px3": col("bid_px3"), "bid_qty3": col("bid_qty3"), "bid_px2": col("bid_px2"), "bid_qty2": col("bid_qty2"),
        "bid_px1": col("bid_px1"), "bid_qty1": col("bid_qty1"),
        "last_px": last.to_numpy(), "last_vol": col("last_vol"),
        "change": (last - ref).to_numpy(), "pct": ((last / ref - 1) * 100).to_numpy(),
        "ask_px1": col("ask_px1"), "ask_qty1": col("ask_qty1"), "ask_px2": col("ask_px2"), "ask_qty2": col("ask_qty2"),
        "ask_px3": col("ask_px3"), "ask_qty3": col("ask_qty3"),
        "total_vol": col("total_vol"), "total_value": col("total_value"),
        "spread_bps": col("rel_spread_bps"), "foreign_net": col("foreign_net_val"),
    })
    return out.sort_values("symbol").reset_index(drop=True)


def price_class(px: float, ref: float, ceil: float, floor: float) -> str:
    """Quy ước màu bảng giá: ce = trần (tím), fl = sàn (xanh dương), rf = bằng tham chiếu (vàng),
    up = trên tham chiếu (xanh lá), dn = dưới tham chiếu (đỏ). Thiếu số thì không tô màu."""
    if isinstance(px, str) or pd.isna(px) or pd.isna(ref):  # chữ ATO/ATC hoặc thiếu số thì không tô màu
        return ""
    if not pd.isna(ceil) and px == ceil:
        return "ce"
    if not pd.isna(floor) and px == floor:
        return "fl"
    return "rf" if px == ref else "up" if px > ref else "dn"


def trading_date(now: pd.Timestamp) -> dt.date:
    """Ngày giao dịch hiện tại theo lịch tuần: hôm nay nếu là thứ 2 đến thứ 6, còn thứ 7 và chủ nhật thì lấy thứ 6.
    (Không biết lịch nghỉ lễ; ngày lễ app vẫn hiện ngày thường và ghi rõ "chưa có dữ liệu".)"""
    d = now.date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def market_depth(quotes: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    """Độ sâu cả rổ theo thời gian: tổng giá trị đặt mua và đặt bán ở 3 mức giá của mọi mã (tỷ đồng).
    imbalance = (mua - bán) / (mua + bán) theo giá trị, trong [-1, 1]; > 0: bên mua dày hơn."""
    d = quotes[quotes["ts"].dt.date == day]
    if d.empty:
        return pd.DataFrame(columns=["ts", "bid_value", "ask_value", "imbalance", "median_spread_bps"])
    # Mức không có lệnh tính 0 (như depth_row và add_liquidity_metrics), để một mã sát trần/sàn không làm mất cả dòng.
    work = d.assign(
        bid_value=sum((d[p] * d[q]).fillna(0) for p, q in zip(BID_PX, BID_QTY)),
        ask_value=sum((d[p] * d[q]).fillna(0) for p, q in zip(ASK_PX, ASK_QTY)),
    )
    g = work.groupby("ts").agg(bid_value=("bid_value", "sum"), ask_value=("ask_value", "sum"),
                               median_spread_bps=("rel_spread_bps", "median")).reset_index()
    g["imbalance"] = (g["bid_value"] - g["ask_value"]) / (g["bid_value"] + g["ask_value"]).where(lambda s: s > 0)
    g[["bid_value", "ask_value"]] = g[["bid_value", "ask_value"]] / 1e9
    return g


def breadth_frame(cards: pd.DataFrame) -> pd.DataFrame:
    """Độ rộng mỗi chỉ số: số mã tăng, đứng giá, giảm và tỷ lệ tăng/giảm (từ NEO 4.3)."""
    if cards.empty:
        return cards
    b = cards[["index_code", "advances", "no_change", "declines", "ceilings", "floors"]].copy()
    total = (b["advances"] + b["no_change"] + b["declines"]).where(lambda s: s > 0)
    b["adv_pct"], b["flat_pct"], b["dec_pct"] = (b["advances"] / total * 100, b["no_change"] / total * 100,
                                                  b["declines"] / total * 100)
    b["adv_dec_ratio"] = b["advances"] / b["declines"].where(b["declines"] > 0)
    return b


def traded_value(idx: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    """Giá trị giao dịch lũy kế (tỷ đồng) của từng sàn theo thời gian và phần tăng thêm mỗi lần chụp.
    Cột *_cum là lũy kế; cột *_step là giá trị giao dịch trong khoảng giữa hai lần chụp."""
    rows = _day_rows(idx, day)
    rows = rows[rows["index_code"].isin(EXCHANGE_OF)] if not rows.empty else rows
    if rows.empty:
        return pd.DataFrame()
    pv = rows.pivot_table(index="ts", columns="index_code", values="sum_value", aggfunc="last").sort_index() / 1e9
    pv = pv.rename(columns=EXCHANGE_OF)
    out = pv.add_suffix("_cum")
    steps = pv.diff().clip(lower=0).add_suffix("_step")
    out = pd.concat([out, steps], axis=1)
    out["total_cum"] = pv.sum(axis=1, min_count=1)
    out["total_step"] = pv.diff().clip(lower=0).sum(axis=1, min_count=1)
    return out.reset_index()


_STATUS_LABELS = {"ATO": "Mở cửa (ATO)", "LO": "Đang khớp lệnh", "L": "Nghỉ trưa", "ATC": "Đóng cửa (ATC)",
                  "PT": "Thỏa thuận", "PLO": "Sau giờ", "C": "Đóng cửa", "PRE": "Chờ mở cửa"}


def status_label(status: object, ts: pd.Timestamp) -> str:
    """Trạng thái phiên (NEO 4.3/4.4) -> nhãn tiếng Việt. Dữ liệu thật cho thấy sau giờ đóng cửa NEO báo "PRE"
    (chờ phiên hôm sau), nên PRE/C/rỗng từ 14:45 trở đi hiển thị là "Đóng cửa"."""
    code = str(status or "").upper()
    if code in ("", "PRE", "C") and ts is not None and ts.time() >= dt.time(14, 45):
        return "Đóng cửa"
    return _STATUS_LABELS.get(code, code or "–")


def day_range(series: pd.DataFrame) -> tuple[float, float] | None:
    """Điểm thấp nhất và cao nhất trong ngày từ chuỗi chỉ số (None nếu chưa có dữ liệu)."""
    if series is None or series.empty:
        return None
    v = pd.to_numeric(series["value"], errors="coerce").dropna()
    return (float(v.min()), float(v.max())) if len(v) else None


def _spread_bps(bid: pd.Series, ask: pd.Series) -> pd.Series:
    mid = (ask + bid) / 2
    return ((ask - bid) / mid * 1e4).where((bid > 0) & (ask > bid))


def board_view(b: pd.DataFrame) -> pd.DataFrame:
    """Bảng giá một nhóm (HOSE, HNX, UPCoM, ETF, CW) từ bảng `board` -> cột giống price_board để dùng chung board_html.
    Giữ NGUYÊN số NEO (giá đồng, KL cổ phiếu); giá mức 1 là chữ ATO/ATC thì giữ chữ. Thay đổi và % tính từ giá khớp
    và giá tham chiếu (đã đối chiếu: trùng priceChange của NEO)."""
    if b is None or b.empty:
        return pd.DataFrame()
    num = lambda c: pd.to_numeric(b[c], errors="coerce").to_numpy()  # noqa: E731
    raw = lambda c: b[c].to_numpy()  # noqa: E731
    ref = pd.Series(num("ref_px")).where(lambda x: x > 0)
    last = pd.Series(num("last_px"))
    out = pd.DataFrame({
        "symbol": raw("symbol"), "ref": ref.to_numpy(), "ceil": num("ceil_px"), "floor": num("floor_px"),
        **{f"bid_px{i}": raw(f"bid_px{i}") for i in (3, 2, 1)}, **{f"bid_qty{i}": num(f"bid_qty{i}") for i in (3, 2, 1)},
        "last_px": last.to_numpy(), "last_vol": num("last_vol"),
        "change": (last - ref).to_numpy(), "pct": ((last / ref - 1) * 100).to_numpy(),
        **{f"ask_px{i}": raw(f"ask_px{i}") for i in (1, 2, 3)}, **{f"ask_qty{i}": num(f"ask_qty{i}") for i in (1, 2, 3)},
        "total_vol": num("total_vol"), "total_value": num("total_value"),
        "spread_bps": _spread_bps(pd.Series(num("bid_px1")), pd.Series(num("ask_px1"))).to_numpy(),
        "foreign_net": num("foreign_net_val"),
    })
    return out.sort_values("symbol").reset_index(drop=True)


def futures_view(fut: pd.DataFrame, index_value: float | None = None) -> pd.DataFrame:
    """Hợp đồng tương lai VN30 ở lần chụp mới nhất. Giá là ĐIỂM chỉ số. basis = giá khớp - điểm VN30 (điểm);
    âm nghĩa là hợp đồng rẻ hơn chỉ số (chiết khấu). Chưa có giá khớp hoặc chưa có chỉ số thì để trống."""
    if fut is None or fut.empty:
        return pd.DataFrame()
    d = fut[fut["ts"] == fut["ts"].max()].copy()
    d["_mat"] = pd.to_datetime(d["maturity"], format="%d/%m/%Y", errors="coerce")
    d = d.sort_values("_mat")
    v = board_view(d.assign(symbol=d["name"].fillna(d["symbol"])))
    v["symbol"] = d["name"].fillna(d["symbol"]).to_numpy()
    v["maturity"] = d["maturity"].to_numpy()
    v["open_interest"] = pd.to_numeric(d["open_interest"], errors="coerce").to_numpy()
    last = pd.to_numeric(d["last_px"], errors="coerce").to_numpy()
    v["basis"] = last - index_value if index_value is not None and not pd.isna(index_value) else np.nan
    return v.reset_index(drop=True)


def market_depth_group(depth: pd.DataFrame, day: dt.date, grp: str) -> pd.DataFrame:
    """Độ sâu theo thời gian của một nhóm (bảng depth_market): tỷ đồng và mất cân bằng (mua - bán) / (mua + bán)."""
    d = depth[(depth["grp"] == grp) & (depth["ts"].dt.date == day)] if depth is not None and not depth.empty else depth
    if d is None or d.empty:
        return pd.DataFrame(columns=["ts", "bid_value", "ask_value", "imbalance", "median_spread_bps", "n_symbols"])
    g = d[["ts", "bid_value", "ask_value", "n_symbols"]].sort_values("ts").reset_index(drop=True)
    g["imbalance"] = (g["bid_value"] - g["ask_value"]) / (g["bid_value"] + g["ask_value"]).where(lambda s: s > 0)
    g[["bid_value", "ask_value"]] = g[["bid_value", "ask_value"]] / 1e9
    g["median_spread_bps"] = np.nan
    return g
