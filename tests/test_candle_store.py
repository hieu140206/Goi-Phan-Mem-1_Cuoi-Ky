"""Kho nến riêng data/candles.db: ghi, nạp lại, cộng dồn, và không bao giờ xóa dữ liệu khi nhận bảng rỗng."""
import pandas as pd

from data.candle_store import last_ts, load_candles, load_daily_closes, save_candles


def _df(days, base=100.0):
    return pd.DataFrame({"ts": pd.to_datetime(days), "open": base, "high": base + 5, "low": base - 5, "close": base + 1, "volume": 1000.0})


def test_save_and_load_roundtrip_in_time_order(tmp_path):
    db = tmp_path / "c.db"
    assert save_candles(db, "1d", "VNM", _df(["2026-11-20", "2026-11-19"]), "t1") == 2
    df = load_candles(db, "1d", "VNM")
    assert df["ts"].tolist() == [pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")] and df["close"].iloc[0] == 101.0
    assert load_candles(db, "1d", "FPT").empty and load_candles(db, "5m", "VNM").empty          # khung và mã khác không lẫn
    assert last_ts(db, "1d", "VNM") == pd.Timestamp("2026-11-20") and last_ts(db, "1d", "FPT") is None


def test_missing_file_gives_empty_and_none(tmp_path):
    assert load_candles(tmp_path / "khong_co.db", "1d", "VNM").empty
    assert last_ts(tmp_path / "khong_co.db", "1d", "VNM") is None
    assert not (tmp_path / "khong_co.db").exists()                    # đọc không tự tạo tệp


def test_replace_swaps_whole_series_because_ssi_adjusts_old_prices(tmp_path):
    db = tmp_path / "c.db"
    save_candles(db, "1d", "VNM", _df(["2026-11-18", "2026-11-19"], 100.0), "t1", replace=True)
    save_candles(db, "1d", "VNM", _df(["2026-11-19", "2026-11-20"], 90.0), "t2", replace=True)       # chuỗi mới đã điều chỉnh
    df = load_candles(db, "1d", "VNM")
    assert df["ts"].tolist() == [pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")] and set(df["open"]) == {90.0}


def test_append_mode_keeps_older_intraday_bars_and_overwrites_same_time(tmp_path):
    db = tmp_path / "c.db"
    save_candles(db, "5m", "VNM", _df(["2026-11-18 09:15:00", "2026-11-18 09:20:00"], 100.0), "t1")
    save_candles(db, "5m", "VNM", _df(["2026-11-18 09:20:00", "2026-11-19 09:15:00"], 120.0), "t2")
    df = load_candles(db, "5m", "VNM")
    assert len(df) == 3 and df["open"].tolist() == [100.0, 120.0, 120.0]          # 09:15 cũ còn, 09:20 bị ghi đè
    assert last_ts(db, "5m", "VNM") == pd.Timestamp("2026-11-19 09:15:00")


def test_empty_frame_never_deletes_stored_data_even_with_replace(tmp_path):
    db = tmp_path / "c.db"
    save_candles(db, "1d", "VNM", _df(["2026-11-19"]), "t1", replace=True)
    assert save_candles(db, "1d", "VNM", pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"]), "t2", replace=True) == 0
    assert len(load_candles(db, "1d", "VNM")) == 1                  # SSI trả rỗng hoặc lỗi mạng: giữ nguyên cái đã có


def test_load_daily_closes_reads_every_symbol_of_one_frame_in_one_go(tmp_path):
    db = tmp_path / "c.db"
    save_candles(db, "1d", "VNM", _df(["2026-11-19", "2026-11-20"], 100.0), "t1", replace=True)
    save_candles(db, "1d", "FPT", _df(["2026-11-20"], 200.0), "t1", replace=True)
    save_candles(db, "5m", "VNM", _df(["2026-11-20 09:15"], 50.0), "t1")                    # khung khác không lẫn vào
    df = load_daily_closes(db)
    assert sorted(zip(df["symbol"], df["day"].dt.strftime("%Y-%m-%d"), df["close"])) == [
        ("FPT", "2026-11-20", 201.0), ("VNM", "2026-11-19", 101.0), ("VNM", "2026-11-20", 101.0)]
    assert load_daily_closes(tmp_path / "khong_co.db").empty and not (tmp_path / "khong_co.db").exists()
