"""Ứng dụng phân tích thị trường chứng khoán Việt Nam trên dữ liệu NEO API (VPBankS): Tổng quan và Radar thanh khoản.

Chạy từ thư mục gốc dự án:  streamlit run src/app/app.py
Hoặc cùng bộ ghi dữ liệu bằng một lệnh:  python scripts/run_live.py

File này là "cổng vào": đặt cấu hình trang, CSS, thương hiệu, công tắc Trực tiếp rồi chuyển sang trang được chọn
(overview.py hoặc radar.py). Nội dung giao diện của Radar vẫn nằm nguyên trong radar.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

from data.storage import live_stamp  # noqa: E402
from neo_api.config import get_settings  # noqa: E402
from theme import BRAND_MARK, group, inject_css  # noqa: E402

LIVE_EVERY_SECONDS = 15  # cứ 15 giây xem bộ ghi có ghi thêm gì chưa; bộ ghi chụp mỗi phút nên dữ liệu trễ tối đa ~1 phút

st.set_page_config(page_title="Thị trường VN · NEO API", page_icon=":material/radar:", layout="wide")
inject_css()
settings = get_settings()


def _db_stamp(path: Path):
    """Dấu hiệu bộ ghi vừa ghi thêm sổ lệnh/bảng giá (đổi mỗi phút). Không dùng mtime của file vì bộ ghi nhanh
    ghi chỉ số mỗi 5 giây; phần chỉ số do khối thẻ chỉ số tự cập nhật riêng."""
    return live_stamp(path)


@st.fragment(run_every=LIVE_EVERY_SECONDS)
def _live_watch(db_path: Path, seen: float | None) -> None:
    """Chế độ trực tiếp: chỉ chạy lại cả trang khi market.db thực sự có dữ liệu mới (không chạy lại vô ích)."""
    if _db_stamp(db_path) != seen:
        st.rerun()


with st.sidebar:
    st.html(f'<div class="brand">{BRAND_MARK}<div><b>Thị trường VN</b>'
            '<span>Dữ liệu NEO API · VPBankS</span></div></div>')
    group("Cập nhật")
    live = st.toggle("Trực tiếp: tự cập nhật", value=os.environ.get("NEO_LIVE") == "1", key="live",
                     help="Tự đọc lại dữ liệu khi bộ ghi (scripts/record_rest.py) ghi thêm. "
                          "Bộ ghi chụp mỗi phút nên dữ liệu trễ tối đa khoảng 1 phút. "
                          "Chạy cả hai cùng lúc bằng: python scripts/run_live.py")
    if live:
        _live_watch(settings.db_path, _db_stamp(settings.db_path))

pages = st.navigation(
    [
        st.Page("overview.py", title="Tổng quan thị trường", icon=":material/dashboard:", url_path="tong-quan", default=True),
        st.Page("radar.py", title="Radar thanh khoản", icon=":material/radar:", url_path="radar"),
    ],
    position="top",
)
pages.run()
