import pandas as pd

from data.schema import QUOTE_COLUMNS, normalize_quotes
from data.storage import count_rows, load_quotes, save_quotes


def raw(**over):
    base = {c: 100 for c in QUOTE_COLUMNS}
    base.update({"ts": "2026-10-22 09:00:00", "symbol": " vcb ", "bid_px1": 99, "ask_px1": 101})
    base.update(over)
    return base


def test_normalize_handles_dirty_rows():
    df = pd.DataFrame([
        raw(),
        raw(),                                   # trùng
        raw(ts="2026-10-22 09:05:00", ask_px1=98),   # sổ lệnh chéo
        raw(ts="2026-10-22 09:10:00", bid_px1="abc"),  # lỗi kiểu dữ liệu
        raw(ts="không phải ngày"),               # thời gian hỏng
        raw(ts="2026-10-22 09:15:00", bid_px1=-1),   # giá âm
    ])
    clean, rep = normalize_quotes(df)
    assert len(clean) == 1
    assert clean.loc[0, "symbol"] == "VCB"
    assert str(clean["ts"].dt.tz) == "Asia/Ho_Chi_Minh"
    assert rep["rows_in"] == 6 and rep["rows_out"] == 1
    assert rep["dropped_crossed_book"] == 1


def test_timezone_converted_to_vietnam():
    clean, _ = normalize_quotes(pd.DataFrame([raw(ts="2026-10-22T02:00:00+00:00")]))
    assert clean.loc[0, "ts"].hour == 9  # 02:00 UTC = 09:00 UTC+7


def test_storage_roundtrip_and_dedupe(tmp_path):
    clean, _ = normalize_quotes(pd.DataFrame([raw()]))
    db = tmp_path / "t.db"
    assert save_quotes(clean, db) == 1
    assert save_quotes(clean, db) == 0  # ghi lại không tạo bản trùng
    assert count_rows(db) == 1
    back, _ = normalize_quotes(load_quotes(db))
    assert back.loc[0, "symbol"] == "VCB" and back.loc[0, "ts"].hour == 9


def test_old_database_is_migrated_without_losing_rows(tmp_path):
    """DB tạo bởi bản cũ (thiếu cột ceil_px/floor_px/last_vol): mở lại thì thêm cột, giữ nguyên dòng cũ, ghi tiếp được."""
    import sqlite3

    import pandas as pd

    from data.storage import load_quotes, save_quotes

    db = tmp_path / "old.db"
    old_cols = [c for c in QUOTE_COLUMNS if c not in ("ceil_px", "floor_px", "last_vol")]
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE quotes (" + ", ".join(f"{c} TEXT" if c in ("ts", "symbol") else f"{c} REAL"
                                                         for c in old_cols) + ", PRIMARY KEY (ts, symbol))")
        row = {c: 1.0 for c in old_cols}
        row.update(ts="2026-10-28T10:00:00+07:00", symbol="ACB")
        conn.execute(f"INSERT INTO quotes ({', '.join(old_cols)}) VALUES ({', '.join('?' for _ in old_cols)})",
                     [row[c] for c in old_cols])
    back = load_quotes(db)
    assert len(back) == 1 and {"ceil_px", "floor_px", "last_vol"} <= set(back.columns)
    assert pd.isna(back.loc[0, "ceil_px"])  # không ước lượng: ô mới để trống
    new = pd.DataFrame([{**{c: 2.0 for c in QUOTE_COLUMNS}, "ts": pd.Timestamp("2026-10-28 10:01", tz="Asia/Ho_Chi_Minh"),
                         "symbol": "BID", "ceil_px": 36100.0}])
    assert save_quotes(new, db) == 1
    assert len(load_quotes(db)) == 2


def test_limit_lock_is_reported_not_silently_dropped(tmp_path):
    df = pd.DataFrame([
        raw(ceil_px=107, floor_px=93),                                                   # bình thường
        raw(symbol="HPG", bid_px1=107, ask_px1=None, ask_qty1=None, ceil_px=107, floor_px=93),  # khóa trần, bên bán trống
        raw(symbol="SSI", bid_px1=0, ask_px1=93, ceil_px=107, floor_px=93),             # khóa sàn, bên mua = 0
        raw(symbol="FPT", bid_px1=None, ask_px1=101, ceil_px=107, floor_px=93),         # thiếu dữ liệu, không phải khóa
    ])
    clean, rep = normalize_quotes(df)
    assert clean["symbol"].tolist() == ["VCB"]
    assert rep["dropped_limit_lock"] == 2 and rep["dropped_missing"] == 1
    locked = rep["limit_locked"]
    assert sorted(locked["symbol"]) == ["HPG", "SSI"]
    assert list(locked.columns) == QUOTE_COLUMNS

    from data.schema import limit_lock_side
    sides = dict(zip(locked["symbol"], limit_lock_side(locked)))
    assert sides == {"HPG": "trần", "SSI": "sàn"}

    # Lưu được (bên trống để rỗng) và đọc lại vẫn nhận ra là khóa, không lọt vào dữ liệu phân tích.
    db = tmp_path / "t.db"
    save_quotes(pd.concat([clean, locked], ignore_index=True), db)
    back, rep2 = normalize_quotes(load_quotes(db))
    assert back["symbol"].tolist() == ["VCB"] and rep2["dropped_limit_lock"] == 2
