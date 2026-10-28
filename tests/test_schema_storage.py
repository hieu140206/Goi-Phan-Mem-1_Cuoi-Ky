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
