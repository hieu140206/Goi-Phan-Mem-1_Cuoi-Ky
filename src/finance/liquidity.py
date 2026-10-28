"""Chỉ số thanh khoản và vi cấu trúc từ sổ lệnh 3 mức giá.

Công thức (mỗi lần chụp sổ lệnh):
  mid            = (bid1 + ask1) / 2
  spread tương đối (bps) = (ask1 - bid1) / mid * 10.000     -> chi phí giao dịch khứ hồi gần đúng
  độ sâu (cổ phiếu)      = tổng khối lượng mua + bán ở 3 mức
  độ sâu (giá trị, đồng) = tổng (giá * khối lượng) ở 3 mức mua và bán
  mất cân bằng           = (khối lượng mua - khối lượng bán) / (mua + bán), nằm trong [-1, 1]
                           > 0: bên mua dày hơn; < 0: bên bán dày hơn
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.schema import ASK_PX, ASK_QTY, BID_PX, BID_QTY

# Trọng số điểm thanh khoản: GIẢ ĐỊNH ban đầu, cần giải thích/hiệu chỉnh trong báo cáo.
DEFAULT_WEIGHTS = {"spread": 0.4, "depth": 0.4, "imbalance": 0.2}


def add_liquidity_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["mid"] = (out["bid_px1"] + out["ask_px1"]) / 2
    out["spread"] = out["ask_px1"] - out["bid_px1"]
    out["rel_spread_bps"] = out["spread"] / out["mid"] * 1e4
    out["bid_depth"] = out[BID_QTY].sum(axis=1, min_count=1)
    out["ask_depth"] = out[ASK_QTY].sum(axis=1, min_count=1)
    out["depth_shares"] = out["bid_depth"] + out["ask_depth"]
    value = sum(out[p] * out[q] for p, q in zip(BID_PX + ASK_PX, BID_QTY + ASK_QTY))
    out["depth_value"] = value
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


def rank_symbols(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Gộp theo mã trong khoảng dữ liệu đã chọn, tính điểm thanh khoản 0-100 (cao = thanh khoản tốt).

    Điểm = 100 * (w_spread * hạng(-spread) + w_depth * hạng(độ sâu) + w_imb * hạng(-|mất cân bằng|)),
    trong đó hạng là xếp hạng phần trăm giữa các mã đang được so sánh. Đây là điểm TƯƠNG ĐỐI trong nhóm.
    """
    w = weights or DEFAULT_WEIGHTS
    agg = (
        df.assign(abs_imb=df["imbalance"].abs())
        .groupby("symbol")
        .agg(
            rel_spread_bps=("rel_spread_bps", "median"),
            depth_value=("depth_value", "median"),
            abs_imbalance=("abs_imb", "median"),
            snapshots=("ts", "count"),
        )
    )
    score = 100 * (
        w["spread"] * _scaled_rank(agg["rel_spread_bps"], ascending=False)
        + w["depth"] * _scaled_rank(agg["depth_value"], ascending=True)
        + w["imbalance"] * _scaled_rank(agg["abs_imbalance"], ascending=False)
    )
    agg["score"] = score.round(1)
    agg["tier"] = pd.cut(
        agg["score"], bins=[-0.1, 33.3, 66.7, 100.1], labels=["Yếu", "Trung bình", "Tốt"]
    ).astype(str)
    return agg.sort_values("score").reset_index()
