"""Dữ liệu trang Tổng quan: thẻ chỉ số, chuỗi chỉ số, bảng giá, độ sâu, độ rộng, thanh khoản (dữ liệu thật 27/10/2026)."""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data.market import index_detail_frame
from data.overview import (breadth_frame, days_available, index_cards, index_series, load_market_json,
                           market_depth, price_board, traded_value)
from data.schema import normalize_quotes
from data.storage import load_market_index, save_market_index
from finance.liquidity import add_liquidity_metrics
from neo_api.stream import map_record

FIX = Path(__file__).parent / "fixtures"
MARKET = json.loads((FIX / "neo_market_20261027.json").read_text(encoding="utf-8"))
REST = json.loads((FIX / "neo_rest_vn30_20261027.json").read_text(encoding="utf-8"))
TZ = "Asia/Ho_Chi_Minh"
DAY = dt.date(2026, 10, 27)


def _idx(n=3):
    """n lần chụp 4.3, giá trị giao dịch lũy kế tăng dần."""
    frames = []
    for i in range(n):
        f = index_detail_frame(MARKET["4.3 marketIndexDetail"], pd.Timestamp(f"2026-10-27 10:0{i}:00", tz=TZ))
        f["sum_value"] = f["sum_value"] * (i + 1) / n
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def _quotes(times=("10:00:00", "10:01:00")):
    frames = []
    for t in times:
        raw = pd.DataFrame([map_record(r) for r in REST]).assign(ts=pd.Timestamp(f"2026-10-27 {t}", tz=TZ))
        clean, _ = normalize_quotes(raw)
        frames.append(clean)
    return add_liquidity_metrics(pd.concat(frames, ignore_index=True))


def test_index_detail_frame_drops_fu_and_types():
    f = index_detail_frame(MARKET["4.3 marketIndexDetail"], pd.Timestamp("2026-10-27 10:00", tz=TZ))
    assert "FU" not in set(f["index_code"]) and {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"} <= set(f["index_code"])
    assert f["advances"].dtype.kind == "f" and f.loc[f["index_code"] == "VNINDEX", "declines"].iloc[0] == 197


def test_save_and_load_market_index_roundtrip(tmp_path):
    f = _idx(2)
    assert save_market_index(f, tmp_path / "m.db") == len(f)
    assert save_market_index(f, tmp_path / "m.db") == 0  # chạy lại không nhân đôi
    back = load_market_index(tmp_path / "m.db")
    assert len(back) == len(f) and str(back["ts"].dt.tz) == TZ


def test_cards_order_and_values():
    cards = index_cards(_idx(), DAY)
    assert list(cards["index_code"]) == ["VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"]
    assert cards.loc[0, "index_value"] == 1761.87 and cards.loc[2, "index_value"] == 259.5
    assert cards["ts"].nunique() == 1  # lấy lần chụp mới nhất


def test_cards_fall_back_to_market_json_for_old_days():
    mj = {"saved_at": "2026-10-27T15:05:00+07:00", "index_detail": MARKET["4.3 marketIndexDetail"]}
    cards = index_cards(pd.DataFrame(columns=["ts"]), DAY, mj)
    assert set(cards["index_code"]) == {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"}


def test_index_series_from_db_and_from_4_2_json():
    s = index_series(_idx(), DAY, "VNINDEX")
    assert len(s) == 3 and s["ts"].is_monotonic_increasing
    mj = {"intraday_VN30": MARKET["4.2 intradayMarketIndex"]}
    s2 = index_series(pd.DataFrame(columns=["ts", "index_code"]), DAY, "VN30", mj)
    assert len(s2) > 300 and s2["value"].between(1800, 1950).all()
    assert index_series(pd.DataFrame(columns=["ts", "index_code"]), DAY, "HNXINDEX", mj).empty


def test_price_board_every_cell_matches_neo_response():
    """Dữ liệu phải đúng: từng ô của bảng giá khớp từng trường trong phản hồi NEO 4.7 (không đổi đơn vị, không làm tròn)."""
    q = _quotes()
    b = price_board(q, DAY)
    assert len(b) == 30 and b["symbol"].is_unique
    by = b.set_index("symbol")
    for r in REST:
        row = by.loc[r["symbol"]]
        assert row["ref"] == r["refPrice"] and row["ceil"] == r["ceilingPrice"] and row["floor"] == r["floorPrice"]
        for i in (1, 2, 3):
            assert row[f"bid_px{i}"] == float(r[f"bidPrice{i}"]) and row[f"bid_qty{i}"] == r[f"bidVol{i}"]
            assert row[f"ask_px{i}"] == float(r[f"askPrice{i}"]) and row[f"ask_qty{i}"] == r[f"askVol{i}"]
        assert row["last_px"] == r["closePrice"] and row["last_vol"] == r["closeVol"]
        assert row["total_vol"] == r["totalTradingVolume"] and row["total_value"] == r["totalTradingValue"]
        assert row["change"] == pytest.approx(r["priceChange"])                    # trùng giá trị NEO tự tính
        assert row["pct"] == pytest.approx(r["percentPriceChange"], abs=0.01)      # NEO làm tròn 2 số lẻ
    early = price_board(q, DAY, until=pd.Timestamp("2026-10-27 10:00:30", tz=TZ))
    assert len(early) == 30
    assert price_board(q, dt.date(2026, 1, 1)).empty


def test_price_board_missing_ceiling_is_blank_not_guessed():
    q = _quotes().drop(columns=["ceil_px", "floor_px", "last_vol"])
    b = price_board(q, DAY)
    assert b["ceil"].isna().all() and b["floor"].isna().all() and b["last_vol"].isna().all()
    assert b["ref"].notna().all()


def test_price_class_and_trading_date():
    from data.overview import price_class, trading_date

    assert price_class(22750, 21300, 22750, 19850) == "ce" and price_class(19850, 21300, 22750, 19850) == "fl"
    assert price_class(21300, 21300, 22750, 19850) == "rf"
    assert price_class(21500, 21300, 22750, 19850) == "up" and price_class(21000, 21300, 22750, 19850) == "dn"
    assert price_class(21500, 21300, float("nan"), float("nan")) == "up"   # thiếu trần/sàn vẫn tô theo tham chiếu
    assert price_class(float("nan"), 21300, 22750, 19850) == ""
    ts = lambda s: pd.Timestamp(s, tz=TZ)  # noqa: E731
    assert trading_date(ts("2026-10-29 08:00")) == dt.date(2026, 10, 29)          # thứ Tư
    assert trading_date(ts("2026-10-31 10:00")) == dt.date(2026, 10, 30)          # thứ Bảy -> thứ Sáu
    assert trading_date(ts("2026-11-01 10:00")) == dt.date(2026, 10, 30)          # Chủ nhật -> thứ Sáu


def test_market_depth_in_billions_and_bounded_imbalance():
    d = market_depth(_quotes(), DAY)
    assert len(d) == 2 and (d["bid_value"] > 0).all() and (d["ask_value"] > 0).all()
    assert d["imbalance"].between(-1, 1).all()
    assert d["bid_value"].iloc[0] < 1e5  # tỷ đồng, không phải đồng


def test_breadth_percentages_sum_to_100():
    b = breadth_frame(index_cards(_idx(), DAY))
    assert np.allclose(b[["adv_pct", "flat_pct", "dec_pct"]].sum(axis=1), 100)
    assert b.loc[b["index_code"] == "VNINDEX", "adv_dec_ratio"].iloc[0] == pytest.approx(123 / 197)


def test_traded_value_cumulative_and_steps():
    tv = traded_value(_idx(3), DAY)
    assert {"HOSE_cum", "HNX_cum", "UPCoM_cum", "total_cum", "total_step"} <= set(tv.columns)
    assert tv["total_cum"].is_monotonic_increasing
    assert tv["total_step"].iloc[1:].gt(0).all()
    assert tv["HOSE_cum"].iloc[-1] == pytest.approx(13922.25, rel=1e-3)  # tỷ đồng


def test_days_available_and_missing_market_json(tmp_path):
    assert days_available(_idx(1), _quotes()) == [DAY]
    assert load_market_json(tmp_path, DAY) == {}


def test_status_label_after_close_and_during_session():
    from data.overview import status_label

    ts = lambda hhmm: pd.Timestamp(f"2026-10-27 {hhmm}:00", tz=TZ)  # noqa: E731
    assert status_label("PRE", ts("15:05")) == "Đóng cửa"      # dữ liệu thật: sau giờ NEO báo PRE
    assert status_label("PRE", ts("08:30")) == "Chờ mở cửa"
    assert status_label("LO", ts("10:00")) == "Đang khớp lệnh"
    assert status_label("L", ts("12:00")) == "Nghỉ trưa"
    assert status_label(None, ts("16:00")) == "Đóng cửa"
    assert status_label("XYZ", ts("10:00")) == "XYZ"


def test_day_range():
    from data.overview import day_range

    s = pd.DataFrame({"ts": pd.date_range("2026-10-27 09:00", periods=3, freq="min", tz=TZ), "value": [10.0, 12.5, 11.0]})
    assert day_range(s) == (10.0, 12.5)
    assert day_range(pd.DataFrame(columns=["ts", "value"])) is None


def test_market_depth_keeps_symbols_with_an_empty_book_level():
    q = _quotes()
    q.loc[q.index[0], ["ask_px2", "ask_qty2", "ask_px3", "ask_qty3"]] = np.nan   # một mã chỉ còn 1 mức bán
    full = market_depth(_quotes(), DAY)
    part = market_depth(q, DAY)
    assert len(part) == len(full) == 2
    lost = q.loc[q.index[0], "ask_px1"] * 0  # không thể mất cả dòng: bên bán chỉ giảm đúng phần của mức 2, 3 đã bỏ
    assert part["ask_value"].iloc[0] < full["ask_value"].iloc[0] and part["ask_value"].iloc[0] > 0
    assert part["bid_value"].iloc[0] == pytest.approx(full["bid_value"].iloc[0])
