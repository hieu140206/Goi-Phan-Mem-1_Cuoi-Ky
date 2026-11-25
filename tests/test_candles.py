"""Nến OHLC cho hộp thoại chi tiết mã: đọc phản hồi SSI, nến ngày dự phòng từ NEO, vẽ biểu đồ, liên kết mở hộp thoại."""
import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "app"))

from data import ssi  # noqa: E402
from data.candles import neo_daily_candles  # noqa: E402
from test_ssi import FakeSession, Resp, login_body, make  # noqa: E402


def _row(day, o=100.0, h=110.0, l=95.0, c=105.0, v=1000.0):
    return {"symbol": "VNM", "tradingDate": day, "open": str(o), "high": str(h), "low": str(l), "close": str(c), "volume": str(v)}


# ---- đọc phản hồi SSI ----
def test_parse_ohlc_sorts_ascending_reads_both_time_formats_and_skips_bad_rows():
    rows = [_row("2026/11/23 14:45:00", c=52300), _row("2026/11/23 09:15:00"), _row("2026/11/20", c=51400),
            _row("hỏng", c=1), {**_row("2026/11/19"), "close": ""}, _row("2026/11/23 09:15:00", c=999)]       # trùng giờ: lấy dòng sau
    df = ssi.parse_ohlc(rows)
    assert df["ts"].tolist() == [pd.Timestamp("2026-11-20"), pd.Timestamp("2026-11-23 09:15"), pd.Timestamp("2026-11-23 14:45")]
    assert df["close"].tolist() == [51400.0, 999.0, 52300.0]            # dòng sai giờ và dòng thiếu giá đóng bị bỏ, không điền
    assert ssi.parse_ohlc([]).empty and list(ssi.parse_ohlc([]).columns) == ssi.OHLC_COLUMNS


def test_parse_ohlc_keeps_fractional_adjusted_prices_as_is():
    df = ssi.parse_ohlc([_row("2026/02/02", o=65686.683, h=67261.681, l=65130.802, c=67261.681)])
    assert df["open"].iloc[0] == 65686.683 and not math.isnan(df["volume"].iloc[0])


def test_fetch_ohlc_follows_pages_until_a_short_page_and_sends_time_range():
    page = lambda n, day: Resp(body={"data": [_row(day)] * n})               # noqa: E731
    s = FakeSession(posts=[Resp(body=login_body(exp=10_000))], gets=[page(2, "2026/11/23"), page(1, "2026/11/20")])
    c, _ = make(s, t=0)
    df = ssi.fetch_ohlc(c, "VNM", "2026/11/01", "2026/11/25", "5m", page_size=2)
    assert df["ts"].tolist() == [pd.Timestamp("2026-11-20"), pd.Timestamp("2026-11-23")]
    gets = [x for x in s.calls if x[0] == "GET"]
    assert [g[2]["pageIndex"] for g in gets] == [1, 2]
    assert gets[0][2]["timeFrame"] == "5m" and gets[0][2]["from"] == "2026/11/01 00:00:00" and gets[0][2]["to"] == "2026/11/25 23:59:59"


def test_fetch_ohlc_rejects_unsupported_frame_and_empty_reply_is_empty():
    c, _ = make(FakeSession(posts=[Resp(body=login_body(exp=10_000))], gets=[Resp(status=204)]), t=0)
    with pytest.raises(ValueError):
        ssi.fetch_ohlc(c, "VNM", "2026/11/01", "2026/11/25", "1w")
    assert ssi.fetch_ohlc(c, "VNM", "2026/11/01", "2026/11/25", "1d").empty


# ---- nến ngày dự phòng từ NEO ----
def _board_db(tmp_path):
    p = tmp_path / "m.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE board (day TEXT, grp TEXT, ts TEXT, symbol TEXT, open_px REAL, high_px REAL, low_px REAL, last_px REAL, total_vol REAL)")
    con.executemany("INSERT INTO board VALUES (?,?,?,?,?,?,?,?,?)", [
        ("2026-11-19", "VN30", "2026-11-19T15:02:20+07:00", "VNM", 100, 110, 95, 105, 1000),
        ("2026-11-20", "VN30", "2026-11-20T14:44:55+07:00", "VNM", 105, 108, 100, 101, 900),     # chụp trước 15:00
        ("2026-11-20", "VN30", "2026-11-20T15:02:20+07:00", "ACB", 0, 0, 0, 0, 0),              # giá 0: loại
        ("2026-11-20", "VN30", "2026-11-20T15:02:20+07:00", "FPT", None, None, None, None, None)])
    con.commit()
    con.close()
    return p


def test_neo_daily_candles_flag_partial_days_and_drop_missing_prices(tmp_path):
    p = _board_db(tmp_path)
    df = neo_daily_candles(p, "VNM")
    assert df["ts"].tolist() == [pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")]
    assert df["partial"].tolist() == [False, True]                       # ngày chụp 14:44 chưa gồm ATC: đánh dấu, không im lặng
    assert neo_daily_candles(p, "ACB").empty and neo_daily_candles(p, "FPT").empty and neo_daily_candles(p, "XYZ").empty
    assert neo_daily_candles(tmp_path / "khong_co.db", "VNM").empty


def test_neo_daily_candles_does_not_modify_the_database(tmp_path):
    p = _board_db(tmp_path)
    before = p.read_bytes()
    neo_daily_candles(p, "VNM")
    assert p.read_bytes() == before


# ---- biểu đồ ----
def _candles(n=5, start="2026-11-16"):
    ts = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"ts": ts, "open": [50000.0 + i * 100 for i in range(n)], "high": [51000.0 + i * 100 for i in range(n)],
                         "low": [49000.0 + i * 100 for i in range(n)], "close": [50500.0 - i * 100 for i in range(n)],
                         "volume": [1000.0 * (i + 1) for i in range(n)]})


def test_candle_figure_shows_thousand_dong_and_colours_by_direction():
    import symbol_dialog as sd
    fig = sd.candle_figure(_candles(), intraday=False)
    candle = fig.data[0]
    assert list(candle.open)[:2] == [50.0, 50.1] and fig.data[1].marker.color[0] == sd.POS      # đóng 50,5 > mở 50 -> xanh
    assert fig.data[1].marker.color[-1] == sd.NEG                                               # đóng thấp hơn mở -> đỏ


def test_candle_figure_hides_weekends_gaps_and_lunch_only_for_intraday():
    import symbol_dialog as sd
    d = _candles(4, "2026-11-16").drop(index=2).reset_index(drop=True)        # thiếu thứ Tư 18/11
    assert sd.missing_weekdays(d["ts"]) == ["2026-11-18"]
    daily = sd.candle_figure(d, intraday=False).layout.xaxis.rangebreaks
    intra = sd.candle_figure(d, intraday=True).layout.xaxis.rangebreaks
    assert not any(b.pattern == "hour" for b in daily) and sum(b.pattern == "hour" for b in intra) == 2
    assert sd.missing_weekdays(pd.Series([], dtype="datetime64[ns]")) == []


# ---- liên kết trên bảng giá ----
def test_board_symbol_opens_dialog_link_on_same_page_for_every_group():
    import board as bd
    from test_board import _board
    html_dialog = bd.board_html(_board(), dialog=True)
    assert 'href="?xem=' in html_dialog and 'target="_self"' in html_dialog and "ma?ma=" not in html_dialog
    assert 'href="?xem=' not in bd.board_html(_board())                          # mặc định không gắn liên kết


# ---- thứ tự nguồn của hộp thoại: kho nến -> SSI trực tiếp -> NEO ----
def test_get_candles_prefers_stored_history_and_does_not_call_ssi(tmp_path, monkeypatch):
    import symbol_dialog as sd
    from data.candle_store import save_candles
    db = tmp_path / "c.db"
    save_candles(db, "1d", "VNM", pd.DataFrame({"ts": pd.to_datetime(["2026-01-05", "2026-11-23"]), "open": 1.0, "high": 2.0, "low": 0.5,
                                                "close": 1.5, "volume": 10.0}), "t", replace=True)
    monkeypatch.setattr(sd, "_load_ssi", lambda *a: (_ for _ in ()).throw(AssertionError("không được gọi SSI khi kho đã có")))
    df, source, note = sd.get_candles("VNM", "Ngày", tmp_path / "khong_co.db", candle_db=db)
    assert source == "SSI" and len(df) == 2 and "23/11/2026" in note             # giữ cả lịch sử cũ trong kho, ghi ngày mới nhất


def test_get_candles_falls_back_to_live_ssi_then_neo_when_store_is_empty(tmp_path, monkeypatch):
    import symbol_dialog as sd
    live = pd.DataFrame({"ts": pd.to_datetime(["2026-11-20"]), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0})
    monkeypatch.setattr(sd, "_load_ssi", lambda *a: live)
    df, source, _ = sd.get_candles("VNM", "Ngày", tmp_path / "khong_co.db", candle_db=tmp_path / "khong_co2.db")
    assert source == "SSI" and len(df) == 1
    monkeypatch.setattr(sd, "_load_ssi", lambda *a: (_ for _ in ()).throw(RuntimeError("mạng")))
    df, source, note = sd.get_candles("VNM", "Ngày", _board_db(tmp_path), candle_db=tmp_path / "khong_co2.db")
    assert source == "NEO" and len(df) == 2 and "RuntimeError" in note
    assert sd.get_candles("VNM", "5 phút", tmp_path / "khong_co.db", candle_db=tmp_path / "khong_co2.db")[0].empty       # khung trong phiên không có dự phòng NEO


def test_candle_figure_fits_price_axis_to_the_visible_window_not_all_history():
    import symbol_dialog as sd
    d = _candles(200, "2025-01-01")
    d.loc[:100, ["open", "high", "low", "close"]] *= 3                       # lịch sử cũ giá cao gấp 3: không được kéo trục giá của đoạn cuối
    fig = sd.candle_figure(d, intraday=False)
    lo, hi = fig.layout.yaxis.range
    tail = d.iloc[-90:]
    assert lo <= tail["low"].min() / 1000 and hi >= tail["high"].max() / 1000 and hi < d["high"].max() / 1000 / 2
