"""Chụp trạng thái sổ lệnh theo chu kỳ cố định từ luồng thông điệp.

NEO đẩy thông điệp theo sự kiện (không đều, có thể dồn dập) và không kèm dấu thời gian. Phân tích cần các điểm
cách đều nhau, nên bộ chụp giữ trạng thái mới nhất của từng mã và cứ mỗi `interval` giây chụp một lần,
gán dấu thời gian là mốc làm tròn xuống theo giờ Việt Nam.

Giả định: mỗi thông điệp là trạng thái đầy đủ của mã (thay thế trạng thái cũ). Nếu dữ liệu thật cho thấy thông điệp
chỉ chứa trường thay đổi thì phải đổi sang gộp (merge) tại `update`.
Mã quá `stale` giây không có tin mới thì không chụp, để không ghi dữ liệu cũ khi mất kết nối hoặc nghỉ trưa.
"""
from __future__ import annotations

import pandas as pd

from neo_api.config import TZ

TRADING_START_MIN = 9 * 60       # 09:00, giữ cả ATO để kiểm tra định dạng; bước lọc phiên sẽ bỏ sau
TRADING_END_MIN = 15 * 60


def in_trading_hours(now: pd.Timestamp) -> bool:
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and TRADING_START_MIN <= minutes < TRADING_END_MIN


class Snapshotter:
    def __init__(self, interval: int = 60, stale: int = 900) -> None:
        self.interval = interval
        self.stale = stale
        self._state: dict[str, tuple[pd.Timestamp, dict]] = {}
        self._last_slot: pd.Timestamp | None = None

    def update(self, row: dict, now: pd.Timestamp | None = None) -> None:
        now = now or pd.Timestamp.now(tz=TZ)
        sym = str(row["symbol"]).strip().upper()
        self._state[sym] = (now, dict(row))

    def slot(self, now: pd.Timestamp) -> pd.Timestamp:
        return now.floor(f"{self.interval}s")

    def due(self, now: pd.Timestamp) -> bool:
        """Đã sang mốc chụp mới chưa (mỗi mốc chỉ chụp một lần)."""
        s = self.slot(now)
        return self._last_slot is None or s > self._last_slot

    def snapshot(self, now: pd.Timestamp | None = None) -> list[dict]:
        """Chụp các mã còn mới; gắn ts = mốc làm tròn xuống. Gọi một lần cho mỗi mốc."""
        now = now or pd.Timestamp.now(tz=TZ)
        slot = self.slot(now)
        self._last_slot = slot
        rows = []
        for sym, (seen, row) in self._state.items():
            if (now - seen).total_seconds() <= self.stale:
                rows.append({**row, "symbol": sym, "ts": slot})
        return rows
