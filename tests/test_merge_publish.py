"""Gộp dữ liệu từ thư mục ghi vào dữ liệu chính (data/merge.py), đẩy riêng data/web (data/publish.py), và chạy thử cả quy trình
(scripts/gop_va_day.py). Tệp và kho git tạm, không đụng data/market.db, không gọi mạng."""
import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest

from data import merge, publish
from data.storage import _connect

ROOT = Path(__file__).resolve().parents[1]
D1, D2 = "2026-11-20", "2026-11-26"


def put(db, table, **row):
    conn = _connect(db)
    with conn:
        conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    conn.close()


def rows(db, sql):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture
def dbs(tmp_path):
    src, dst = tmp_path / "ghi" / "market.db", tmp_path / "chinh" / "market.db"
    for db in (src, dst):                       # ngày cũ có ở cả hai nơi
        put(db, "quotes", ts=f"{D1}T09:15:00+07:00", symbol="FPT", bid_px1=1.0)
    put(src, "quotes", ts=f"{D2}T09:15:00+07:00", symbol="FPT", bid_px1=2.0)
    put(src, "quotes", ts=f"{D2}T09:16:00+07:00", symbol="FPT", bid_px1=3.0)
    put(src, "board", day=D2, grp="VN30", ts=f"{D2}T15:02:00+07:00", symbol="FPT", last_px=50.0)
    put(src, "ws_trades", day=D2, symbol="FPT", seq=1, ts=f"{D2}T09:15:01+07:00")
    put(src, "ssi_quotes", ts=f"{D2}T09:15:00+07:00", symbol="FPT")
    return src, dst


def test_new_days_lists_only_days_where_the_source_has_more_rows(dbs):
    src, dst = dbs
    assert merge.new_days(src, dst) == [D2]


def test_merge_adds_only_the_chosen_days_and_running_twice_adds_nothing(dbs):
    src, dst = dbs
    put(src, "quotes", ts="2026-11-27T09:15:00+07:00", symbol="FPT")
    added = merge.merge_days(src, dst, [D2])
    assert added["quotes"] == 2 and added["board"] == 1 and added["ws_trades"] == 1 and added["ssi_quotes"] == 1
    assert rows(dst, "SELECT COUNT(*) FROM quotes") == [(3,)]                    # ngày 27/11 không được chọn nên không vào
    again = merge.merge_days(src, dst, [D2])
    assert all(n == 0 for n in again.values())
    assert merge.new_days(src, dst) == ["2026-11-27"]


def test_merge_never_overwrites_an_existing_snapshot_row(dbs):
    src, dst = dbs
    put(dst, "quotes", ts=f"{D2}T09:15:00+07:00", symbol="FPT", bid_px1=999.0)
    merge.merge_days(src, dst, [D2])
    assert rows(dst, f"SELECT bid_px1 FROM quotes WHERE ts='{D2}T09:15:00+07:00'") == [(999.0,)]


@pytest.mark.parametrize("dst_time,expected", [("11:00:00", 50.0), ("15:02:30", 77.0)])
def test_merge_board_keeps_the_newest_snapshot(dbs, dst_time, expected):
    src, dst = dbs
    put(dst, "board", day=D2, grp="VN30", ts=f"{D2}T{dst_time}+07:00", symbol="FPT", last_px=77.0)
    merge.merge_days(src, dst, [D2])
    assert rows(dst, "SELECT last_px FROM board") == [(expected,)]


def test_merge_stops_without_changes_when_the_target_lacks_a_column(dbs):
    src, dst = dbs
    conn = sqlite3.connect(src)
    with conn:
        conn.execute("ALTER TABLE ssi_quotes ADD COLUMN cot_moi REAL")
    conn.close()
    with pytest.raises(merge.MergeError):
        merge.merge_days(src, dst, [D2])
    assert rows(dst, "SELECT COUNT(*) FROM quotes") == [(1,)]                    # giao dịch bị hủy toàn bộ


def test_merge_refuses_same_file(dbs):
    src, _ = dbs
    with pytest.raises(merge.MergeError):
        merge.merge_days(src, src, [D2])


def test_backup_is_a_full_copy_and_is_never_overwritten(dbs, tmp_path):
    _, dst = dbs
    saved = merge.backup_db(dst, tmp_path / "sao-luu", "x1")
    assert rows(saved, "SELECT COUNT(*) FROM quotes") == [(1,)]
    with pytest.raises(merge.MergeError):
        merge.backup_db(dst, tmp_path / "sao-luu", "x1")


def test_raw_files_are_copied_and_never_overwritten(tmp_path):
    src, dst = tmp_path / "a", tmp_path / "b"
    (src / D2).mkdir(parents=True)
    (src / D2 / "stocks.jsonl.gz").write_bytes(b"moi")
    (src / D2 / "ssi.jsonl.gz").write_bytes(b"ssi")
    (dst / D2).mkdir(parents=True)
    (dst / D2 / "stocks.jsonl.gz").write_bytes(b"cu")
    copied, conflicts = merge.merge_raw(src, dst, [D2], "ghi-1")
    assert (dst / D2 / "stocks.jsonl.gz").read_bytes() == b"cu"
    assert (dst / D2 / "stocks.jsonl.gz.ghi-1").read_bytes() == b"moi" and len(conflicts) == 1
    assert (dst / D2 / "ssi.jsonl.gz").read_bytes() == b"ssi" and len(copied) == 2


def test_sessions_rows_are_appended_once(tmp_path):
    src, dst = tmp_path / "s.csv", tmp_path / "d.csv"
    src.write_text(f"date,rows\n{D1},1\n{D2},2\n", encoding="utf-8-sig")
    dst.write_text(f"date,rows\n{D1},1", encoding="utf-8-sig")                   # không có xuống dòng cuối
    assert merge.merge_sessions(src, dst, [D2]) == 1
    assert merge.merge_sessions(src, dst, [D2]) == 0
    assert dst.read_text(encoding="utf-8-sig").split() == ["date,rows", f"{D1},1", f"{D2},2"]


# ---- đẩy riêng data/web
def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """Máy chủ giả (bare), thư mục ghi (clone đóng băng) và một người khác đẩy mã mới lên máy chủ."""
    remote, seed, rec, dev = (tmp_path / n for n in ("remote.git", "seed", "rec", "dev"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
    (seed / "app.py").write_text("v1\n")
    (seed / ".gitignore").write_text((ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")   # đúng luật bỏ qua của dự án
    (seed / "data" / "web").mkdir(parents=True)
    (seed / "data" / "web" / "market_web.db.gz").write_bytes(b"data-cu")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "dau")
    git(seed, "push", "-q", str(remote), "main")
    for target in (rec, dev):
        subprocess.run(["git", "clone", "-q", str(remote), str(target)], check=True, capture_output=True)
    return remote, rec, dev


def test_publish_pushes_only_data_web_and_keeps_newer_code_on_the_server(repos):
    remote, rec, dev = repos
    (dev / "app.py").write_text("v2\n")                      # mã mới được đẩy từ dự án chính trong lúc đang ghi
    git(dev, "commit", "-qam", "ma moi")
    git(dev, "push", "-q", "origin", "main")
    (rec / "app.py").write_text("sua do, khong duoc day\n")  # thay đổi lạ trong thư mục ghi
    (rec / "data" / "web" / "market_web.db.gz").write_bytes(b"data-moi")
    (rec / "data" / "web" / ".unpacked.json").write_text("{}")
    commit, files = publish.build_data_commit(rec, "cap nhat")
    assert files == ["data/web/market_web.db.gz"]
    publish.push_commit(rec, commit)
    assert git(remote, "show", "main:app.py") == "v2" and git(remote, "show", "main:data/web/market_web.db.gz") == "data-moi"
    assert (rec / "app.py").read_text() == "sua do, khong duoc day\n"      # mã trong thư mục ghi không bị đụng tới
    assert git(rec, "rev-parse", "HEAD") != commit                          # không checkout, không pull


def test_publish_leaves_out_unpack_marker_even_without_ignore_rules(repos):
    _, rec, _ = repos
    (rec / ".gitignore").unlink()                             # thư mục ghi bản cũ chưa có luật bỏ qua
    (rec / "data" / "web" / "market_web.db.gz").write_bytes(b"data-moi")
    (rec / "data" / "web" / ".unpacked.json").write_text("{}")
    (rec / "data" / "web" / "_tmp_market.db").write_bytes(b"tam")
    _, files = publish.build_data_commit(rec, "cap nhat")
    assert files == ["data/web/market_web.db.gz"]


def test_publish_returns_none_when_nothing_changed(repos):
    _, rec, _ = repos
    assert publish.build_data_commit(rec, "x") is None


# ---- cả quy trình
def load_script():
    spec = importlib.util.spec_from_file_location("gop_va_day", ROOT / "scripts" / "gop_va_day.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def folders(tmp_path, dbs):
    src, dst = dbs
    for db, base in ((src, tmp_path / "G"), (dst, tmp_path / "M")):
        (base / "data").mkdir(parents=True)
        (base / "data" / "market.db").write_bytes(db.read_bytes())
    return tmp_path / "G", tmp_path / "M"


@pytest.mark.parametrize("answer,pushed", [("k", False), ("c", True)])
def test_end_of_day_asks_before_pushing(tmp_path, dbs, monkeypatch, answer, pushed):
    rec, main_dir = folders(tmp_path, dbs)
    mod = load_script()
    calls = []
    monkeypatch.setattr(mod, "build_data_commit", lambda repo, msg: ("abc1234", ["data/web/x"]))
    monkeypatch.setattr(mod, "push_commit", lambda repo, commit: calls.append(commit))
    monkeypatch.setattr(mod.dt, "datetime", type("T", (mod.dt.datetime,), {"now": classmethod(lambda cls, tz=None: mod.dt.datetime(2026, 11, 26, 15, 10, tzinfo=tz))}))
    monkeypatch.setattr("builtins.input", lambda q: answer)
    assert mod.main(["--ghi", str(rec), "--chinh", str(main_dir), "--bo-qua-nen"]) == 0
    assert bool(calls) is pushed
    assert rows(main_dir / "data" / "market.db", f"SELECT COUNT(*) FROM quotes WHERE ts LIKE '{D2}%'") == [(2,)]   # gộp dù có đẩy hay không
    assert list((rec / "sao-luu").glob("market_*.db")) and (rec / "data" / "web" / "market_web.db.gz").exists()


# ---- bước nạp số SSI cho ngày NEO không ghi được
SSI_DAY = "2026-11-27"


def put_index(db, day, codes=("VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX")):
    for code in codes:
        put(db, "ssi_index_daily", day=day, index_code=code, index_value=1.0)


def test_ssi_days_to_load_are_only_new_days_neo_missed_and_not_yet_loaded(dbs):
    mod = load_script()
    _, db = dbs                                                      # D1 có sổ lệnh NEO
    for day in (D1, "2026-11-25", D2, SSI_DAY):
        put(db, "ssi_quotes", ts=f"{day}T14:59:55+07:00", symbol="FPT")
    put_index(db, D2)                                                # D2 đã nạp đủ chỉ số và mã
    put(db, "ssi_daily", day=D2, symbol="FPT", close=1.0)
    put_index(db, SSI_DAY)                                           # 27/11 mới có chỉ số, thiếu mã: nạp lại
    assert mod.ssi_days_to_load(db, [D1, D2, SSI_DAY, "2026-11-30"]) == [SSI_DAY]     # 25/11 không nằm trong đợt gộp


@pytest.mark.parametrize("loads,warned", [(True, False), (False, True)])
def test_end_of_day_loads_ssi_figures_when_neo_recorded_nothing(tmp_path, dbs, monkeypatch, capsys, loads, warned):
    src, dst = dbs
    put(src, "ssi_quotes", ts=f"{SSI_DAY}T14:59:55+07:00", symbol="FPT")
    rec, main_dir = folders(tmp_path, (src, dst))
    mod = load_script()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if loads:                                                    # giả lập scripts/fetch_ssi_overview.py ghi thành công
            db = Path(cmd[cmd.index("--db") + 1])
            put_index(db, SSI_DAY)
            put(db, "ssi_daily", day=SSI_DAY, symbol="FPT", close=1.0)
        return subprocess.CompletedProcess(cmd, 0 if loads else 1)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.dt, "datetime", type("T", (mod.dt.datetime,), {"now": classmethod(lambda cls, tz=None: mod.dt.datetime(2026, 11, 27, 15, 10, tzinfo=tz))}))
    assert mod.main(["--ghi", str(rec), "--chinh", str(main_dir), "--bo-qua-nen", "--khong-day"]) == 0
    assert len(calls) == 1 and calls[0][1].endswith("fetch_ssi_overview.py")           # chỉ ngày 27/11 (26/11 NEO đã ghi)
    assert calls[0][calls[0].index("--day") + 1] == SSI_DAY
    assert calls[0][calls[0].index("--db") + 1] == str(main_dir.resolve() / "data" / "market.db")
    assert "--khong-sao-luu" in calls[0]                                              # lần chạy này đã sao lưu trước khi gộp
    assert (f"chưa nạp đủ số SSI cho trang Tổng quan" in capsys.readouterr().out) is warned
