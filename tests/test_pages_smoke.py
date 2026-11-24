"""Kiểm tra khói: mọi tệp mã biên dịch được, và từng trang Streamlit chạy hết thân trang mà không ném lỗi.

Sinh ra sau khi một lỗi dấu nháy trong screen_page.py lọt qua toàn bộ test (không có test nào nạp trang). Các trang chạy trên
data/market.db thật (như các test_real_*), bỏ qua nếu máy không có dữ liệu. Lỗi "Could not find page" là do bộ kiểm thử không có
điều hướng nhiều trang (st.switch_page, st.page_link), không phải lỗi của trang.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["overview", "screen_page", "radar", "stock"]


def test_every_source_file_compiles():
    bad = []
    for folder in ("src", "scripts", "tests"):
        for p in (ROOT / folder).rglob("*.py"):
            try:
                ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError as e:
                bad.append(f"{p.relative_to(ROOT)}:{e.lineno} {e.msg}")
    assert not bad, bad


def _has_data():
    try:
        from data.storage import count_rows
        from neo_api.config import get_settings
        return count_rows(get_settings().db_path) > 0
    except Exception:
        return False


@pytest.mark.skipif(not _has_data(), reason="không có data/market.db")
@pytest.mark.parametrize("page", PAGES)
def test_page_body_runs_without_exceptions(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "src" / "app" / f"{page}.py"), default_timeout=240)
    at.run()
    real = [e.value for e in at.exception if "Could not find page" not in e.value]
    assert not real, real
