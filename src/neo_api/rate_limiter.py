"""Giới hạn tần suất gọi REST: tối đa N yêu cầu trong mỗi cửa sổ 1 giây (NEO: 5 yêu cầu/giây)."""
from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls: int = 5, period: float = 1.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Chặn cho tới khi được phép gọi tiếp."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                sleep_for = self.period - (now - self._calls[0])
            time.sleep(max(sleep_for, 0.001))
