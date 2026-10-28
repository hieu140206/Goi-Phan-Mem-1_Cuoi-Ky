"""Bộ tạo DỮ LIỆU MÔ PHỎNG để phát triển giao diện và kiểm thử khi chưa có dữ liệu NEO.

Mọi đầu ra từ module này là dữ liệu giả. Giá gốc chỉ mang tính minh họa, không phải giá thị trường.
Khi đưa vào báo cáo phải ghi rõ "dữ liệu mô phỏng". Các sự kiện bất thường được cài sẵn và lưu lại
(ground truth) để kiểm tra bộ phát hiện bất thường có bắt được hay không.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from neo_api.config import TZ

# Giá gốc minh họa (đồng) cho nhóm mã cỡ lớn.
BASE_PRICES: dict[str, float] = {
    "ACB": 26000, "BCM": 62000, "BID": 48000, "BVH": 46000, "CTG": 36000, "FPT": 120000,
    "GAS": 72000, "GVR": 34000, "HDB": 27000, "HPG": 27000, "MBB": 25000, "MSN": 68000,
    "MWG": 62000, "PLX": 40000, "POW": 13000, "SAB": 52000, "SHB": 13000, "SSB": 20000,
    "SSI": 30000, "STB": 38000, "TCB": 24000, "TPB": 17000, "VCB": 90000, "VHM": 80000,
    "VIB": 19000, "VIC": 95000, "VJC": 105000, "VNM": 62000, "VPB": 20000, "VRE": 30000,
}
THIN_NAMES = {"BCM", "BVH", "GVR", "PLX", "POW", "SAB", "SSB"}  # mã giả định kém thanh khoản hơn


def tick_size(price: float) -> int:
    """Bước giá HOSE: <10.000đ: 10; 10.000-49.950đ: 50; từ 50.000đ: 100."""
    if price < 10_000:
        return 10
    if price < 50_000:
        return 50
    return 100


def trading_days(end: str = "2026-10-22", n: int = 10) -> list[pd.Timestamp]:
    days = pd.bdate_range(end=end, periods=n)
    return list(days)


def _intraday_times() -> list[tuple[int, int]]:
    times = [(9, m) for m in range(0, 60, 5)] + [(10, m) for m in range(0, 60, 5)]
    times += [(11, m) for m in range(0, 35, 5)]
    times += [(13, m) for m in range(0, 60, 5)] + [(14, m) for m in range(0, 35, 5)]
    return times


def simulate(seed: int = 7, n_days: int = 10, n_events: int = 12) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = trading_days(n=n_days)
    times = _intraday_times()
    n_steps = len(times)
    symbols = list(BASE_PRICES)

    # Sự kiện bất thường cài sẵn: (ngày, mã, bước bắt đầu), kéo dài 4 lần chụp.
    events = []
    for _ in range(n_events):
        events.append((int(rng.integers(3, n_days)), symbols[int(rng.integers(len(symbols)))],
                       int(rng.integers(5, n_steps - 6))))
    event_keys = {(d, s, i) for d, s, st in events for i in range(st, st + 4)}

    rows: list[dict] = []
    for sym, base in BASE_PRICES.items():
        thin = sym in THIN_NAMES
        depth_scale = (3_000 if thin else 12_000) * rng.uniform(0.7, 1.4)
        price = base
        for d_idx, day in enumerate(days):
            price *= float(np.exp(rng.normal(0, 0.012)))
            cum_vol = 0.0
            for t_idx, (hh, mm) in enumerate(times):
                price *= float(np.exp(rng.normal(0, 0.0007)))
                tick = tick_size(price)
                base_ticks = 2 if thin else (2 if rng.random() < 0.2 else 1)
                spread_ticks = base_ticks + (int(rng.integers(0, 2)) if thin else 0)
                depth_mult = 1.0
                if (d_idx, sym, t_idx) in event_keys:
                    spread_ticks *= 4
                    depth_mult = 0.2
                bid1 = np.floor(price / tick) * tick
                ask1 = bid1 + spread_ticks * tick
                row = {"ts": day.tz_localize(TZ) + pd.Timedelta(hours=hh, minutes=mm), "symbol": sym}
                for lv, mult in zip((1, 2, 3), (1.0, 1.3, 1.6)):
                    row[f"bid_px{lv}"] = bid1 - (lv - 1) * tick
                    row[f"ask_px{lv}"] = ask1 + (lv - 1) * tick
                    row[f"bid_qty{lv}"] = round(depth_scale * mult * depth_mult * rng.lognormal(0, 0.35), -1)
                    row[f"ask_qty{lv}"] = round(depth_scale * mult * depth_mult * rng.lognormal(0, 0.35), -1)
                cum_vol += depth_scale * rng.uniform(0.2, 0.9)
                row["last_px"] = bid1 if rng.random() < 0.5 else ask1
                row["total_vol"] = round(cum_vol, -1)
                rows.append(row)

    quotes = pd.DataFrame(rows).sort_values(["symbol", "ts"]).reset_index(drop=True)
    truth = pd.DataFrame(
        [{"symbol": s,
          "start_ts": days[d].tz_localize(TZ) + pd.Timedelta(hours=times[st][0], minutes=times[st][1]),
          "n_snapshots": 4} for d, s, st in events]
    ).sort_values(["symbol", "start_ts"]).reset_index(drop=True)
    return quotes, truth
