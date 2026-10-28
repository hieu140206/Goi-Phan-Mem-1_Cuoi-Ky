"""Đăng nhập NEO để lấy token (JWT) và giữ token trong bộ nhớ.

Luồng (theo ví dụ trong tài liệu NEO):
  POST {auth_url}  với JSON {"username": ..., "password": ...}
  -> phản hồi có data.access_token. Token này dùng cho cả REST (header Authorization: Bearer) và WebSocket
     (tin nhắn {"action": "auth", "data": token}).

Token KHÔNG tự được lưu ở đâu cả: nó chỉ nằm trong TokenManager (bộ nhớ) và mất khi chương trình tắt.
Vì vậy mỗi lần chạy chương trình phải đăng nhập lại; bộ ghi dữ liệu chạy nhiều giờ sẽ tự đăng nhập lại khi
token hết hạn hoặc bị từ chối. Mật khẩu chỉ được giữ trong bộ nhớ của tiến trình, không ghi ra đĩa.

Chưa biết thời hạn token: nếu phản hồi có `expires_in` (giây) thì dùng để tự làm mới trước hạn, nếu không thì
chỉ làm mới khi NEO từ chối token (401 hoặc xác thực WebSocket thất bại).
"""
from __future__ import annotations

import getpass
import logging
import sys
import time
from dataclasses import dataclass, field

import requests

from .config import Settings, get_settings

log = logging.getLogger(__name__)

EXPIRY_MARGIN = 60.0  # làm mới trước hạn 60 giây


class LoginError(RuntimeError):
    """Đăng nhập thất bại. Thông báo không bao giờ chứa tên đăng nhập, mật khẩu hay token."""


@dataclass
class TokenInfo:
    access_token: str = field(repr=False)
    expires_at: float | None  # thời điểm hết hạn (time.time()), None nếu NEO không cho biết
    other_fields: list[str]   # chỉ TÊN các trường khác trong phản hồi (ví dụ refresh_token), không lấy giá trị

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or time.time()) >= self.expires_at - EXPIRY_MARGIN


def login(settings: Settings, username: str, password: str, timeout: float = 15.0) -> TokenInfo:
    try:
        resp = requests.post(settings.auth_url, json={"username": username, "password": password}, timeout=timeout)
    except requests.RequestException as exc:
        raise LoginError(f"Không kết nối được máy chủ đăng nhập ({type(exc).__name__}). Kiểm tra mạng.") from exc
    if resp.status_code in (400, 401, 403):
        raise LoginError(f"Đăng nhập bị từ chối ({resp.status_code}). Kiểm tra tài khoản, mật khẩu hoặc IP đã đăng ký.")
    if not resp.ok:
        raise LoginError(f"Máy chủ đăng nhập trả lỗi {resp.status_code}.")
    try:
        data = resp.json()["data"]
        token = data["access_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LoginError("Phản hồi đăng nhập không có data.access_token như tài liệu mô tả.") from exc
    if not isinstance(token, str) or not token:
        raise LoginError("Token nhận được rỗng hoặc sai kiểu.")
    expires_in = data.get("expires_in")
    expires_at = time.time() + float(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else None
    return TokenInfo(token, expires_at, sorted(k for k in data if k != "access_token"))


class TokenManager:
    """Cấp token cho REST và WebSocket. Thứ tự: token đang giữ -> NEO_API_TOKEN trong .env -> đăng nhập."""

    def __init__(self, settings: Settings | None = None, username: str | None = None, password: str | None = None) -> None:
        self.settings = settings or get_settings()
        self._username = username or self.settings.username
        self._password = password or self.settings.password
        self._info: TokenInfo | None = None
        self._static = self.settings.token  # token dán tay trong .env, chỉ dùng cho tới khi bị từ chối

    @property
    def info(self) -> TokenInfo | None:
        return self._info

    def get(self) -> str:
        if self._info is not None and not self._info.is_expired():
            return self._info.access_token
        if self._info is None and self._static:
            return self._static
        self._info = login(self.settings, *self._credentials())
        self._static = None
        log.info("Đăng nhập NEO thành công")
        return self._info.access_token

    def invalidate(self) -> None:
        """Gọi khi NEO từ chối token: lần get() sau sẽ đăng nhập lại."""
        self._info = None
        self._static = None

    def _credentials(self) -> tuple[str, str]:
        if not self._username or not self._password:
            if not sys.stdin.isatty():
                raise LoginError("Thiếu NEO_USERNAME/NEO_PASSWORD và không có cửa sổ dòng lệnh để hỏi. Xem .env.example.")
            if not self._username:
                self._username = input("Tài khoản NEO: ").strip()
            if not self._password:
                self._password = getpass.getpass("Mật khẩu (không hiển thị khi gõ): ")
        if not self._username or not self._password:
            raise LoginError("Chưa nhập tài khoản hoặc mật khẩu.")
        return self._username, self._password
