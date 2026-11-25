"""Dữ liệu cho bản web: xuất bản rút gọn và giải nén khi khởi động, nhưng không bao giờ ghi đè dữ liệu thật của sinh viên."""
import gzip
import json
import sqlite3

from data.web_data import CANDLES_GZ, JSON_DIR, MARKET_GZ, MARKER, ensure_web_data, export_web_data


def _market(path, extra_rows=0):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE quotes (ts TEXT, symbol TEXT, PRIMARY KEY (ts, symbol))")
    con.execute("CREATE TABLE ws_quotes (ts TEXT, symbol TEXT)")                   # bảng lớn chỉ để đối chiếu: không đưa lên web
    con.executemany("INSERT INTO quotes VALUES (?,?)", [(f"2026-11-20 09:{i:02d}", "VNM") for i in range(3 + extra_rows)])
    con.execute("INSERT INTO ws_quotes VALUES ('x','VNM')")
    con.commit()
    con.close()


def _candles(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE candles (frame TEXT, symbol TEXT, ts TEXT)")
    con.execute("INSERT INTO candles VALUES ('1d','VNM','2026-11-20')")
    con.commit()
    con.close()


def _tables(db):
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _setup_source(tmp_path):
    m, c, raw = tmp_path / "src" / "market.db", tmp_path / "src" / "candles.db", tmp_path / "src" / "raw"
    m.parent.mkdir()
    _market(m)
    _candles(c)
    (raw / "2026-11-20").mkdir(parents=True)
    (raw / "2026-11-20" / "market.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    return m, c, raw


def test_export_keeps_only_dashboard_tables_and_never_touches_sources(tmp_path):
    m, c, raw = _setup_source(tmp_path)
    before = (m.read_bytes(), c.read_bytes())
    out = tmp_path / "web"
    made = export_web_data(m, c, raw, out)
    assert set(made) == {MARKET_GZ, CANDLES_GZ, JSON_DIR}
    assert (m.read_bytes(), c.read_bytes()) == before                              # nguồn nguyên vẹn
    unz = tmp_path / "check.db"
    unz.write_bytes(gzip.decompress((out / MARKET_GZ).read_bytes()))
    assert _tables(unz) == {"quotes"}                                              # ws_quotes không lên web
    assert (out / JSON_DIR / "2026-11-20.json").exists() and not list(out.glob("_tmp*"))


def test_ensure_unpacks_on_a_fresh_machine_and_is_idempotent(tmp_path):
    m, c, raw = _setup_source(tmp_path)
    export_web_data(m, c, raw, tmp_path / "repo" / "data" / "web")
    root = tmp_path / "repo"
    done = ensure_web_data(root)
    assert (root / "data" / "market.db").exists() and (root / "data" / "candles.db").exists()
    assert (root / "data" / "raw" / "2026-11-20" / "market.json").exists() and MARKET_GZ in done
    assert ensure_web_data(root) == []                                             # lần sau không làm lại


def test_ensure_never_overwrites_real_data_without_our_marker(tmp_path):
    m, c, raw = _setup_source(tmp_path)
    export_web_data(m, c, raw, tmp_path / "repo" / "data" / "web")
    root = tmp_path / "repo"
    real = root / "data" / "market.db"
    _market(real, extra_rows=5)                                                    # dữ liệu thật ở laptop (nhiều dòng hơn bản web)
    (root / "data" / "raw" / "2026-11-20").mkdir(parents=True)
    own_json = root / "data" / "raw" / "2026-11-20" / "market.json"
    own_json.write_text("{\"goc\": true}", encoding="utf-8")
    before = (real.read_bytes(), own_json.read_bytes())
    assert MARKET_GZ not in ensure_web_data(root)
    assert (real.read_bytes(), own_json.read_bytes()) == before                    # không đụng market.db thật và market.json gốc
    assert not (root / "data" / "web" / MARKER).exists() or "market" not in json.loads((root / "data" / "web" / MARKER).read_text())


def test_ensure_refreshes_only_what_it_unpacked_when_the_bundle_changes(tmp_path):
    m, c, raw = _setup_source(tmp_path)
    web = tmp_path / "repo" / "data" / "web"
    export_web_data(m, c, raw, web)
    root = tmp_path / "repo"
    ensure_web_data(root)
    m.unlink()
    _market(m, extra_rows=7)                                                       # dữ liệu mới hơn, xuất lại và đẩy lên
    export_web_data(m, c, raw, web)
    assert MARKET_GZ in ensure_web_data(root)
    con = sqlite3.connect(root / "data" / "market.db")
    assert con.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 10
    con.close()


def test_ensure_without_web_folder_does_nothing(tmp_path):
    assert ensure_web_data(tmp_path) == [] and not (tmp_path / "data").exists()
