"""Bảng màu sáng/tối: hai bảng đủ cùng các khóa, tên màu đọc lúc dùng, ngoài lúc chạy trang thì luôn là nền sáng."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "app"))
import theme  # noqa: E402


def test_light_and_dark_palettes_define_the_same_keys():
    assert set(theme.LIGHT) == set(theme.DARK)
    assert set(theme.LIGHT["BADGE"]) == set(theme.DARK["BADGE"])
    assert theme.LIGHT["PANEL"] != theme.DARK["PANEL"] and theme.LIGHT["INK"] != theme.DARK["INK"]


def test_outside_a_running_page_the_light_palette_is_used_and_names_resolve_lazily():
    assert theme.is_dark() is False
    from theme import BORDER, HUE, INK, PANEL, POS
    assert (INK, HUE, POS, BORDER, PANEL) == (theme.LIGHT["INK"], theme.LIGHT["HUE"], theme.LIGHT["POS"], theme.LIGHT["BORDER"], "#ffffff")
    assert theme.BRAND_MARK.startswith("<img") and "data:image/svg+xml;base64," in theme.BRAND_MARK


def test_unknown_color_name_still_raises_attribute_error():
    import pytest
    with pytest.raises(AttributeError):
        theme.NOT_A_COLOR  # noqa: B018


def test_dark_palette_badges_and_board_css_use_dark_surfaces(monkeypatch):
    monkeypatch.setattr(theme, "is_dark", lambda: True)
    assert "#1b2a44" in theme.badge_style("ok") and theme.palette() is theme.DARK
    import board
    css = board.board_css("#2b313b", "#222831", "#9aa3ad", "#e8eaed", "#4cc16a", "#f2777a", theme.DARK)
    assert theme.DARK["PANEL"] in css and "#ffffff" not in css           # bảng giá không còn nền trắng ở nền tối
