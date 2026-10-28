"""Kiểm tra nhanh kết nối NEO: đăng nhập rồi gọi danh sách chỉ số. Không in token, không gửi lệnh.

Chạy: python scripts/check_neo.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo_api.auth import LoginError, TokenManager  # noqa: E402
from neo_api.client import NeoApiError, NeoClient  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

settings = get_settings()
tokens = TokenManager(settings)
try:
    tokens.get()
    print("Đăng nhập thành công")
    if tokens.info is not None:
        exp = "không cho biết" if tokens.info.expires_at is None else "có (đã dùng để tự làm mới)"
        print(f"Thời hạn token do NEO cung cấp: {exp}")
        print("Các trường khác trong phản hồi đăng nhập (chỉ tên):", tokens.info.other_fields or "không có")
    indexes = NeoClient(settings, tokens).get_index_list()
    codes = [i.get("indexCode") for i in indexes]
    print(f"Lấy được {len(indexes)} chỉ số. Có VN30: {'VN30' in codes}")
except (LoginError, NeoApiError) as exc:
    sys.exit(f"Lỗi: {exc}")
