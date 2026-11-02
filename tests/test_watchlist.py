import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "app"))

from watchlist import load_watchlist, save_watchlist, toggle  # noqa: E402


def test_missing_or_broken_file_is_empty(tmp_path):
    assert load_watchlist(tmp_path / "khong_co.json") == []
    bad = tmp_path / "w.json"
    bad.write_text("{không phải json", encoding="utf-8")
    assert load_watchlist(bad) == []
    bad.write_text('{"symbols": "FPT"}', encoding="utf-8")   # sai kiểu
    assert load_watchlist(bad) == []


def test_save_cleans_and_round_trips(tmp_path):
    f = tmp_path / "sub" / "w.json"
    assert save_watchlist(f, [" fpt", "FPT", "vcb", "", "A-B", 5]) == ["FPT", "VCB"]
    assert load_watchlist(f) == ["FPT", "VCB"]


def test_toggle_adds_then_removes(tmp_path):
    f = tmp_path / "w.json"
    assert toggle(f, "hpg") == ["HPG"]
    assert toggle(f, "FPT") == ["HPG", "FPT"]
    assert toggle(f, "HPG") == ["FPT"]
    assert load_watchlist(f) == ["FPT"]
