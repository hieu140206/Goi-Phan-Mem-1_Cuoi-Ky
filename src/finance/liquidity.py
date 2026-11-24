"""Chỉ số thanh khoản và vi cấu trúc từ sổ lệnh 3 mức giá.

Công thức (mỗi lần chụp sổ lệnh):
  mid            = (bid1 + ask1) / 2
  spread tương đối (bps) = (ask1 - bid1) / mid * 10.000     -> chi phí giao dịch khứ hồi gần đúng
  độ sâu (cổ phiếu)      = tổng khối lượng mua + bán ở 3 mức
  độ sâu (giá trị, đồng) = tổng (giá * khối lượng) ở 3 mức mua và bán
  mất cân bằng           = (khối lượng mua - khối lượng bán) / (mua + bán), nằm trong [-1, 1]
                           > 0: bên mua dày hơn; < 0: bên bán dày hơn
  spread theo bước giá   = (ask1 - bid1) / bước giá tại bid1; 1 = hẹp nhất có thể

Điểm so sánh GIỮA các mã (rank_symbols) dùng spread bps trung bình, vì đó là chi phí thật nhà đầu tư trả khi mua rồi
bán. Quyết định 3/11/2026, sau khi rà soát dữ liệu thật: chấm theo số bước giá làm điểm gần như ngược với chi phí
(VIC rẻ nhất rổ: trung vị 4 bps, trung bình 8 bps, bị xếp "Yếu"; SHB 47 bps, đắt nhất rổ, đứng đầu), vì mã giá cao có bước giá nhỏ so với
giá nên spread hay rộng 2-3 bước giá mà chi phí vẫn thấp. Mặt trái cần ghi trong báo cáo: mã giá thấp luôn có bps cao
do bước giá chiếm tỷ lệ lớn (bị "kẹp bởi bước giá", Harris 1994), nên điểm phản ánh CHI PHÍ chứ không phải độ "căng"
của sổ lệnh. Spread theo bước giá vẫn dùng cho cảnh báo (analytics/baseline.py), vì ở đó mỗi mã so với chính nó.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.schema import ASK_PX, ASK_QTY, BID_PX, BID_QTY
from model_config import section
from status import STATUS_NA, STATUS_OK

_S, _M = section("scoring"), section("market")
# Trọng số điểm thanh khoản: GIẢ ĐỊNH ban đầu (config.toml), cần giải thích/hiệu chỉnh trong báo cáo.
DEFAULT_WEIGHTS = dict(_S["weights"])


def tick_size(price: pd.Series) -> pd.Series:
    """Bước giá cổ phiếu HOSE (đồng): dưới 10.000đ là 10; 10.000-49.950đ là 50; từ 50.000đ là 100.

    Chỉ đúng cho cổ phiếu HOSE (VN30 đều là cổ phiếu HOSE); ETF, chứng quyền và sàn HNX/UPCoM có quy tắc khác.
    Giá thiếu hoặc <= 0 trả NaN.
    """
    p = pd.to_numeric(price, errors="coerce")
    b, t = _M["tick_breaks"], _M["tick_sizes"]
    tick = pd.Series(np.select([p < b[0], p < b[1]], [float(t[0]), float(t[1])], default=float(t[2])), index=p.index)
    return tick.where(p > 0)


def add_liquidity_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["mid"] = (out["bid_px1"] + out["ask_px1"]) / 2
    out["spread"] = out["ask_px1"] - out["bid_px1"]
    out["rel_spread_bps"] = out["spread"] / out["mid"] * 1e4
    # Bước giá lấy tại giá mua tốt nhất: khi bid1 = 49.950 và ask1 = 50.000 thì spread 50đ là đúng 1 bước giá.
    out["tick"] = tick_size(out["bid_px1"])
    out["spread_ticks"] = (out["spread"] / out["tick"]).round(6)
    out["bid_depth"] = out[BID_QTY].sum(axis=1, min_count=1)
    out["ask_depth"] = out[ASK_QTY].sum(axis=1, min_count=1)
    out["depth_shares"] = out["bid_depth"] + out["ask_depth"]
    # Mức không có lệnh (giá và khối lượng đều trống, ví dụ mã sát trần chỉ còn 1-2 mức bán) đóng góp 0 chứ không làm cả
    # tổng thành trống: đó là sự thật "không có lệnh ở mức này". Chỉ khi cả 6 mức đều trống thì độ sâu mới để trống.
    levels = [out[p] * out[q] for p, q in zip(BID_PX + ASK_PX, BID_QTY + ASK_QTY)]
    out["depth_value"] = pd.concat(levels, axis=1).sum(axis=1, min_count=1)
    total = out["depth_shares"].where(out["depth_shares"] > 0)
    out["imbalance"] = (out["bid_depth"] - out["ask_depth"]) / total
    return out


def _scaled_rank(s: pd.Series, ascending: bool = True) -> pd.Series:
    """Xếp hạng phần trăm về [0, 1]; ascending=True: giá trị lớn hơn -> điểm cao hơn."""
    n = s.notna().sum()
    if n <= 1:
        return pd.Series(0.5, index=s.index)
    r = s.rank(method="average", ascending=ascending)
    return (r - 1) / (n - 1)


def add_window_stats(df: pd.DataFrame, window: int = _S["window_snapshots"],
                     snapshot_seconds: int = _S["snapshot_seconds"]) -> pd.DataFrame:
    """Thêm thống kê trên cửa sổ trượt `window` lần chụp gần nhất (mặc định 30 lần = 30 phút) của CHÍNH mã đó, tính đến và
    gồm lần chụp đang xét, không bao giờ vượt ra sau nó (không nhìn trước). Cửa sổ KHÔNG vắt qua nghỉ trưa: buổi chiều bắt đầu lại.
    Cột thêm: win_spread_bps (spread bps TRUNG BÌNH, như điểm cả kỳ), win_depth (độ sâu trung vị), win_abs_imb (|lệch mua/bán|
    trung vị), win_n (số lần chụp hợp lệ trong cửa sổ, tối đa `window`). Cửa sổ tính theo thời gian (window x snapshot_seconds),
    nên lần chụp bị thiếu làm win_n nhỏ đi thay vì kéo dài cửa sổ ra xa."""
    out = df.copy()
    cols = ["win_spread_bps", "win_depth", "win_abs_imb", "win_n"]
    if out.empty:
        for c in cols:
            out[c] = np.nan
        return out
    d = out[["ts", "symbol", "rel_spread_bps", "depth_value", "imbalance"]].assign(abs_imb=out["imbalance"].abs())
    d = d.sort_values(["symbol", "ts"], kind="stable")
    half = (d["ts"].dt.hour >= 12).astype(int).astype(str)
    d["_g"] = d["symbol"].astype(str) + "|" + d["ts"].dt.strftime("%Y-%m-%d") + "|" + half   # mã, ngày, buổi: hết buổi là reset
    roll = (d.set_index("ts").groupby("_g", sort=False)[["rel_spread_bps", "depth_value", "abs_imb"]]
            .rolling(f"{int(window * snapshot_seconds)}s", closed="right"))
    res = pd.concat({"win_spread_bps": roll["rel_spread_bps"].mean(), "win_depth": roll["depth_value"].median(),
                     "win_abs_imb": roll["abs_imb"].median(), "win_n": roll["rel_spread_bps"].count()}, axis=1).reset_index()
    keyed = d[["_g", "ts"]].reset_index().merge(res, on=["_g", "ts"], how="left").set_index("index")
    for c in cols:
        out[c] = keyed[c].reindex(out.index)
    return out


def window_scores(rows: pd.DataFrame, weights: dict[str, float] | None = None, window: int = _S["window_snapshots"],
                  min_valid_share: float = _S["min_valid_share"]) -> pd.DataFrame:
    """Điểm thanh khoản 0-100 theo cửa sổ trượt, từ cột win_* ở lần chụp cuối của mỗi mã trong `rows` (add_window_stats).
    Cùng công thức và trọng số với rank_symbols (spread 40%, độ sâu 40%, lệch 20%), xếp hạng phần trăm giữa các mã CÓ ĐỦ dữ liệu.
    Mã có dưới `min_valid_share` x `window` lần chụp hợp lệ trong cửa sổ (hoặc thiếu thống kê) là "Chưa đủ dữ liệu": không chấm điểm
    và không tham gia xếp hạng, nên không làm đổi phần trăm thứ hạng của mã khác. Trả DataFrame theo mã: score_w, score_w_status."""
    w = weights or DEFAULT_WEIGHTS
    d = rows.drop_duplicates("symbol", keep="last").set_index("symbol")
    ok = (d["win_n"] >= min_valid_share * window) & d[["win_spread_bps", "win_depth", "win_abs_imb"]].notna().all(axis=1)
    out = pd.DataFrame({"score_w": np.nan, "score_w_status": np.where(ok, STATUS_OK, STATUS_NA)}, index=d.index)
    e = d[ok]
    if len(e):
        score = 100 * (w["spread"] * _scaled_rank(e["win_spread_bps"], ascending=False)
                       + w["depth"] * _scaled_rank(e["win_depth"], ascending=True)
                       + w["imbalance"] * _scaled_rank(e["win_abs_imb"], ascending=False))
        out.loc[e.index, "score_w"] = score.round(1)
    return out


def rank_symbols(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Gộp theo mã trong khoảng dữ liệu đã chọn, tính điểm thanh khoản 0-100 (cao = thanh khoản tốt).

    Điểm = 100 * (w_spread * hạng(-spread bps trung bình) + w_depth * hạng(độ sâu) + w_imb * hạng(-|mất cân bằng|)),
    trong đó hạng là xếp hạng phần trăm giữa các mã đang được so sánh. Đây là điểm TƯƠNG ĐỐI trong nhóm.

    Spread bps lấy TRUNG BÌNH (spread_bps_mean): là chi phí trung bình nếu mua bán vào một lần chụp bất kỳ, nên tính
    cả những lúc spread giãn ra. rel_spread_bps (trung vị) và spread_ticks (trung bình số bước giá) trả về để hiển thị,
    không dùng để chấm điểm.
    """
    w = weights or DEFAULT_WEIGHTS
    agg = (
        df.assign(abs_imb=df["imbalance"].abs())
        .groupby("symbol")
        .agg(
            rel_spread_bps=("rel_spread_bps", "median"),
            spread_bps_mean=("rel_spread_bps", "mean"),
            spread_ticks=("spread_ticks", "mean"),
            depth_value=("depth_value", "median"),
            abs_imbalance=("abs_imb", "median"),
            snapshots=("ts", "count"),
        )
    )
    score = 100 * (
        w["spread"] * _scaled_rank(agg["spread_bps_mean"], ascending=False)
        + w["depth"] * _scaled_rank(agg["depth_value"], ascending=True)
        + w["imbalance"] * _scaled_rank(agg["abs_imbalance"], ascending=False)
    )
    agg["score"] = score.round(1)
    agg["tier"] = pd.cut(
        agg["score"], bins=[-0.1, _S["tier_weak"], _S["tier_strong"], 100.1], labels=["Yếu", "Trung bình", "Tốt"]
    ).astype(str)
    return agg.sort_values("score").reset_index()
