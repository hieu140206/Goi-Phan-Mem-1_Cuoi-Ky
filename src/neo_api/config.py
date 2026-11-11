"""Đọc cấu hình từ biến môi trường (.env). Không bao giờ in token hay mật khẩu ra màn hình hay nhật ký."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

TZ = "Asia/Ho_Chi_Minh"  # UTC+7, dùng thống nhất cho mọi dấu thời gian

DEFAULT_AUTH_URL = "https://external.vpbanks.com.vn/auth/token"
DEFAULT_BASE_URL = "https://neoapi.vpbanks.com.vn/neo-api"
DEFAULT_WS_URL = "ws://neoapi.vpbanks.com.vn/stock-stream/broker"


@dataclass(frozen=True)
class Settings:
    base_url: str
    ws_url: str
    max_rps: int
    db_path: Path
    auth_url: str = DEFAULT_AUTH_URL
    device: str = "my-app"        # header x-device mà NEO yêu cầu (giá trị theo ví dụ trong tài liệu)
    device_type: str = "chrome"   # header x-devicetype
    snapshot_seconds: int = 60    # khoảng cách giữa hai lần chụp sổ lệnh khi ghi dữ liệu
    stale_seconds: int = 900      # quá lâu không có tin mới thì không chụp tiếp (tránh ghi dữ liệu cũ)
    # Các trường bí mật: repr=False để không lộ khi in đối tượng.
    token: str | None = field(default=None, repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    @property
    def has_token(self) -> bool:
        return bool(self.token)


def get_settings() -> Settings:
    db_path = Path(os.getenv("NEO_DB_PATH", "data/market.db"))
    if not db_path.is_absolute():  # luôn tính từ thư mục dự án, dù chạy lệnh ở đâu
        db_path = PROJECT_ROOT / db_path
    return Settings(
        base_url=(os.getenv("NEO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        ws_url=(os.getenv("NEO_WS_URL") or DEFAULT_WS_URL).strip(),
        max_rps=int(os.getenv("NEO_MAX_RPS", "5")),
        db_path=db_path,
        auth_url=os.getenv("NEO_AUTH_URL") or DEFAULT_AUTH_URL,
        device=os.getenv("NEO_DEVICE", "my-app"),
        device_type=os.getenv("NEO_DEVICE_TYPE", "chrome"),
        snapshot_seconds=max(int(os.getenv("NEO_SNAPSHOT_SECONDS", "60")), 1),
        stale_seconds=max(int(os.getenv("NEO_STALE_SECONDS", "900")), 1),
        token=os.getenv("NEO_API_TOKEN") or None,
        username=os.getenv("NEO_USERNAME") or None,
        password=os.getenv("NEO_PASSWORD") or None,
    )
