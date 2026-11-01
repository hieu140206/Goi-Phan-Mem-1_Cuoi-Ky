"""Chế độ Trực tiếp: công tắc trong app và các hàm phụ của scripts/run_live.py (không gọi NEO, không mở trình duyệt)."""
import importlib.util
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_run_live():
    spec = importlib.util.spec_from_file_location("run_live", ROOT / "scripts" / "run_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dashboard_command_headless_and_port():
    mod = _load_run_live()
    cmd = mod.dashboard_command(8600, open_browser=False)
    assert cmd[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert cmd[4].endswith("app.py")
    assert "8600" in cmd and "--server.headless" in cmd
    assert "--server.headless" not in mod.dashboard_command(8501, open_browser=True)


def test_dashboard_gets_live_env(monkeypatch):
    mod = _load_run_live()
    seen = {}

    def fake_popen(cmd, cwd=None, env=None):
        seen["env"], seen["cwd"] = env, cwd
        return object()

    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    mod.start_dashboard(8501)
    assert seen["env"]["NEO_LIVE"] == "1"
    assert Path(seen["cwd"]) == ROOT


def test_stop_process_terminates_and_tolerates_none():
    mod = _load_run_live()
    mod.stop_process(None)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    mod.stop_process(proc, timeout=5)
    assert proc.poll() is not None
    mod.stop_process(proc)  # đã dừng rồi thì không lỗi


def test_toggle_on_when_env_live(tmp_path, monkeypatch):
    """NEO_LIVE=1 (do run_live.py đặt) thì công tắc Trực tiếp bật sẵn, kể cả khi market.db còn trống."""
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    db = tmp_path / "market.db"
    sqlite3.connect(db).close()
    monkeypatch.setenv("NEO_DB_PATH", str(db))
    monkeypatch.setenv("NEO_LIVE", "1")
    at = AppTest.from_file(str(ROOT / "src" / "app" / "app.py"), default_timeout=60).run()
    assert not at.exception
    toggles = [t for t in at.toggle if t.key == "live"]
    assert toggles and toggles[0].value is True


def test_toggle_off_by_default(monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("NEO_LIVE", raising=False)
    at = AppTest.from_file(str(ROOT / "src" / "app" / "app.py"), default_timeout=60).run()
    assert not at.exception
    toggles = [t for t in at.toggle if t.key == "live"]
    assert toggles and toggles[0].value is False


def _seed_db(path):
    """Cơ sở dữ liệu nhỏ từ dữ liệu thật 27/10 (3 lần chụp sổ lệnh + 3 lần chụp chỉ số) để chạy thử giao diện."""
    import json

    import pandas as pd

    from data.market import index_detail_frame
    from data.schema import normalize_quotes
    from data.storage import save_market_index, save_quotes
    from neo_api.stream import map_record

    fix = ROOT / "tests" / "fixtures"
    rest = json.loads((fix / "neo_rest_vn30_20261027.json").read_text(encoding="utf-8"))
    mkt = json.loads((fix / "neo_market_20261027.json").read_text(encoding="utf-8"))
    for t in ("10:00:00", "10:01:00", "10:02:00"):
        ts = pd.Timestamp(f"2026-10-27 {t}", tz="Asia/Ho_Chi_Minh")
        clean, _ = normalize_quotes(pd.DataFrame([map_record(r) for r in rest]).assign(ts=ts))
        save_quotes(clean, path)
        save_market_index(index_detail_frame(mkt["4.3 marketIndexDetail"], ts), path)


def test_overview_and_radar_pages_render_on_real_fixtures(tmp_path, monkeypatch):
    """Trang Tổng quan (mặc định) và Radar chạy không lỗi; Tổng quan có 4 thẻ chỉ số và 4 khối nội dung."""
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    db = tmp_path / "market.db"
    _seed_db(db)
    monkeypatch.setenv("NEO_DB_PATH", str(db))
    monkeypatch.delenv("NEO_LIVE", raising=False)
    at = AppTest.from_file(str(ROOT / "src" / "app" / "app.py"), default_timeout=90).run()
    assert not at.exception
    assert [s.value for s in at.subheader] == ["Bảng giá", "Độ sâu thị trường (VN30)", "Độ rộng thị trường",
                                              "Thanh khoản thị trường"]
    html = " ".join(str(e.value) for e in at.get("html"))
    assert "Tổng Quan Thị Trường" in html
    assert "Mã CK" in html and "Giá 3" in html and "Khớp lệnh" in html  # bảng giá kiểu bảng điện
    assert all(n in html for n in ("VN-Index", "VN30", "HNX-Index", "UPCoM-Index"))
    assert "1.761,87" in html  # số thật của VNINDEX theo định dạng Việt Nam
    at.switch_page("radar.py").run()
    assert not at.exception


def test_overview_without_data_shows_guidance(tmp_path, monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("NEO_DB_PATH", str(tmp_path / "empty.db"))
    at = AppTest.from_file(str(ROOT / "src" / "app" / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert any("Chưa có dữ liệu thị trường" in i.value for i in at.info)


def _seed_boards(path):
    """Thêm bảng giá HNX/UPCoM, độ sâu theo sàn và 2 hợp đồng phái sinh (số giả lập nhỏ, đủ để thử giao diện)."""
    import pandas as pd

    from data.market_board import board_frame, depth_row, futures_frame
    from data.storage import save_board, save_depth_market, save_futures

    ts = pd.Timestamp("2026-10-27 10:02:00", tz="Asia/Ho_Chi_Minh")
    for grp, syms in (("HNX", ["SHS", "CEO", "PVS"]), ("UPCOM", ["BSR", "ACV"])):
        recs = [{"symbol": s_, "refPrice": 20000.0, "closePrice": 20500.0, "ceilingPrice": 22000.0, "floorPrice": 18000.0,
                 "bidPrice1": 20400.0, "bidVol1": 1000.0, "askPrice1": "ATO" if s_ == "CEO" else 20500.0, "askVol1": 500.0,
                 "totalTradingVolume": 123456.0} for s_ in syms]
        frame = board_frame(recs, ts, grp)
        save_board(frame, path)
        save_depth_market(depth_row(frame, ts, grp), path)
    fut = [{"symbol": "41I1GB000", "refPrice": 1893.0, "closePrice": 1892.3, "ceilingPrice": 2025.5, "floorPrice": 1760.5,
            "bidPrice1": "1892.6", "bidVol1": 1.0, "askPrice1": "1892.7", "askVol1": 2.0, "totalTradingVolume": 3057.0,
            "openInterest": 33664.0, "maturityDate": "20/11/2026"}]
    save_futures(futures_frame(fut, ts, {"41I1GB000": "VN30F1M"}), path)


@pytest.mark.parametrize("grp, expect", [("HNX", ["SHS", "CEO", "PVS"]), ("UPCOM", ["BSR"]), ("FU", ["VN30F1M", "KL mở (OI)", "Basis"]),
                                         ("ETF", None)])
def test_overview_board_groups_and_depth_scope(tmp_path, monkeypatch, grp, expect):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    db = tmp_path / "market.db"
    _seed_db(db)
    _seed_boards(db)
    monkeypatch.setenv("NEO_DB_PATH", str(db))
    monkeypatch.delenv("NEO_LIVE", raising=False)
    at = AppTest.from_file(str(ROOT / "src" / "app" / "app.py"), default_timeout=90)
    at.session_state["board_grp"] = grp
    at.session_state["depth_scope"] = "HNX"
    at.run()
    assert not at.exception
    html = " ".join(str(e.value) for e in at.get("html"))
    caps = " ".join(str(c.value) for c in at.caption)
    if expect:
        assert all(x in html for x in expect)
    else:
        assert "Chưa có bảng giá ETF" in caps  # nhóm chưa có dữ liệu: nói rõ, không vẽ số
    assert "Độ sâu thị trường (HNX)" in [s.value for s in at.subheader]
    if grp == "FU":
        import json

        mkt = json.loads((ROOT / "tests" / "fixtures" / "neo_market_20261027.json").read_text(encoding="utf-8"))
        vn30 = next(r["indexValue"] for r in mkt["4.3 marketIndexDetail"] if r["indexCode"] == "VN30")
        basis = round(1892.3 - vn30, 2)
        text = f"{basis:+,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")  # định dạng Việt Nam, có dấu
        assert f">{text}<" in html, text  # basis = giá khớp - điểm VN30 thật trong fixture
    if grp == "HNX":
        assert ">ATO<" in html  # giá bán 1 là chữ ATO được giữ nguyên chứ không đổi thành số


def test_live_board_flashes_changed_cells_after_new_snapshot(tmp_path, monkeypatch):
    """Chế độ Trực tiếp: lần mở đầu không tô; khi bộ ghi ghi bản mới, ô nào đổi được tô nền đúng màu."""
    pytest.importorskip("streamlit.testing.v1")
    import json

    import pandas as pd
    from streamlit.testing.v1 import AppTest

    from data.market_board import board_frame
    from data.storage import save_board

    db = tmp_path / "market.db"
    _seed_db(db)
    rest = json.loads((ROOT / "tests" / "fixtures" / "neo_rest_vn30_20261027.json").read_text(encoding="utf-8"))
    t1 = pd.Timestamp("2026-10-27 10:02:05", tz="Asia/Ho_Chi_Minh")
    save_board(board_frame(rest, t1, "VN30"), db)
    monkeypatch.setenv("NEO_DB_PATH", str(db))
    monkeypatch.setenv("NEO_LIVE", "1")
    at = AppTest.from_file(str(ROOT / "src" / "app" / "app.py"), default_timeout=90).run()
    assert not at.exception
    html = " ".join(str(e.value) for e in at.get("html"))
    assert "<td" in html and 'class="up f-up"' not in html and "f-dn\">" not in html  # lần đầu: chưa có gì để so

    changed = json.loads(json.dumps(rest))
    sym = changed[0]["symbol"]
    ref = float(changed[0]["refPrice"])
    changed[0]["bidVol1"] = float(changed[0]["bidVol1"]) + 12345.0
    changed[0]["bidPrice1"] = ref + 100.0   # mức mua 1 cao hơn tham chiếu -> nền xanh lá
    save_board(board_frame(changed, t1 + pd.Timedelta(seconds=5), "VN30"), db)
    at.run()
    assert not at.exception
    html = " ".join(str(e.value) for e in at.get("html"))
    assert "f-up" in html and sym in html
