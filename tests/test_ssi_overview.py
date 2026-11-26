"""Trang Tổng quan dùng SSI cho ngày NEO không ghi được (data/ssi_overview.py, scripts/fetch_ssi_overview.py).
Số dựng sẵn, tệp tạm; không gọi mạng, không đụng data/market.db."""
import datetime as dt
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data import ssi, ssi_overview as so
from data.candle_store import save_candles
from data.overview import breadth_frame, index_series
from data.storage import _connect

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2026, 11, 26)
D = "2026-11-26"
NAN = float("nan")


def index_rows(**over) -> pd.DataFrame:
    base = {"tradingDate": "2026/11/26", "indexValue": "1629.68", "indexChange": "-57.77", "indexChangePercentage": "-3.42",
            "totalMatch": "600", "totalMatchValue": "6000", "totalDeal": "100", "totalDealValue": "1000",
            "totalAdvanceStock": "40", "totalDeclineStock": "273", "totalNoChangeStock": "34", "totalCeilingStock": "7",
            "totalFloorStock": "18"}
    return ssi.parse_index([{**base, **over}], "VNINDEX", D)


def candles(values) -> pd.DataFrame:
    ts = pd.date_range(f"{D} 09:15", periods=len(values), freq="min")
    return pd.DataFrame({"ts": ts, "open": values, "high": [v + 1 for v in values], "low": [v - 2 for v in values],
                         "close": values, "volume": 1.0})


def put_quote(db, ts, symbol, bid=45000.0, ask=45100.0, **extra):
    row = {"ts": ts, "symbol": symbol, "bid_px1": bid, "bid_qty1": 100.0, "ask_px1": ask, "ask_qty1": 200.0, **extra}
    conn = _connect(db)
    with conn:
        conn.execute(f"INSERT INTO ssi_quotes ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    conn.close()


def daily(symbol="FPT", close="44500", change="-1550") -> pd.DataFrame:
    return ssi.parse_summary([{"tradingDate": "2026/11/26", "symbol": symbol, "close": close, "priceChange": change,
                               "totalMatch": "13993100", "totalMatchValue": "637401100000", "totalForeignBuyValue": "9",
                               "totalForeignSellValue": "5"}])


def test_index_cards_use_neo_meaning_for_totals_and_breadth(tmp_path):
    cdb = tmp_path / "c.db"
    save_candles(cdb, "1m", "VNINDEX", candles([1687.0, 1660.0, 1629.68]), "x")
    minutes = so.load_index_minutes(cdb, DAY)
    card = so.ssi_index_cards(index_rows(), minutes, DAY).iloc[0]
    assert (card["index_value"], card["index_change"], card["pct_change"]) == (1629.68, -57.77, -3.42)
    assert card["sum_volume"] == 700 and card["sum_value"] == 7000                 # khớp + thỏa thuận
    assert card["advances"] == 47 and card["declines"] == 291 and card["no_change"] == 34      # tăng gồm trần, giảm gồm sàn
    assert (card["low"], card["high"]) == (1627.68, 1688.0)                        # từ đáy và đỉnh nến, không phải giá đóng
    assert card["ts"].hour == 9 and card["ts"].tzinfo is not None
    series = index_series(minutes, DAY, "VNINDEX")                                 # đường chỉ số dùng chung hàm của NEO
    assert list(series["value"]) == [1687.0, 1660.0, 1629.68]


def test_index_cards_leave_unavailable_numbers_blank():
    zero = index_rows(totalAdvanceStock="0", totalDeclineStock="0", totalNoChangeStock="0", totalCeilingStock="0",
                      totalFloorStock="0", totalDealValue="")
    card = so.ssi_index_cards(zero, so.load_index_minutes(Path("khong-co.db"), DAY), DAY)
    r = card.iloc[0]
    assert pd.isna(r["advances"]) and pd.isna(r["declines"]) and pd.isna(r["ceilings"])
    assert pd.isna(r["sum_value"]) and r["sum_volume"] == 700                      # thiếu một phần thì không cộng thiếu
    assert pd.isna(r["low"]) and pd.isna(breadth_frame(card)["adv_pct"].iloc[0])


def test_board_matches_neo_columns_and_blanks_what_ssi_lacks(tmp_path):
    db = tmp_path / "m.db"
    put_quote(db, f"{D}T14:00:00+07:00", "FPT", bid=1.0, ask=2.0)
    put_quote(db, f"{D}T14:59:55+07:00", "FPT", bid_px2=0.0, bid_qty2=0.0)
    b = so.ssi_board(so.ssi_last_book(db, DAY), daily(), DAY).iloc[0]
    assert (b["bid_px1"], b["ask_px1"]) == (45000.0, 45100.0)                      # thanh mới nhất
    assert pd.isna(b["bid_px2"]) and pd.isna(b["bid_qty2"])                        # mức không có lệnh
    assert b["ref"] == 46050.0 and b["last_px"] == 44500.0 and b["change"] == -1550.0
    assert round(b["pct"], 2) == -3.37 and b["total_vol"] == 13993100 and b["total_value"] == 637401100000
    assert all(pd.isna(b[c]) for c in ("ceil", "floor", "last_vol", "foreign_net"))   # không tự tính, không lấy số chưa khớp


def test_board_hides_book_when_recorder_stopped_before_close_and_keeps_symbol_without_summary(tmp_path):
    db = tmp_path / "m.db"
    put_quote(db, f"{D}T11:00:00+07:00", "FPT")
    put_quote(db, f"{D}T14:59:55+07:00", "VCB")
    b = so.ssi_board(so.ssi_last_book(db, DAY), daily("FPT"), DAY).set_index("symbol")
    assert pd.isna(b.loc["FPT", "bid_px1"]) and b.loc["FPT", "last_px"] == 44500.0
    assert b.loc["VCB", "bid_px1"] == 45000.0 and pd.isna(b.loc["VCB", "last_px"]) and np.isnan(b.loc["VCB", "ref"])


def test_ssi_days_need_no_neo_data_and_both_quotes_and_index(tmp_path):
    db = tmp_path / "m.db"
    assert so.ssi_overview_days(db, []) == []
    for day in ("2026-11-20", D, "2026-11-27"):
        put_quote(db, f"{day}T09:15:00+07:00", "FPT")
    def save(day, codes):
        for code in codes:
            ssi.save_ssi_index(ssi.parse_index([{"tradingDate": day.replace("-", "/"), "indexValue": "1"}], code, day), db)

    save("2026-11-20", so.MAIN_INDICES)
    save(D, so.MAIN_INDICES)
    save("2026-11-27", ["VNINDEX", "VN30"])              # như ngày 12/11 thật: mới có 2 chỉ số từ lần lấy lịch sử cũ
    # 20/11 có NEO nên giữ NEO; 27/11 chưa đủ 4 chỉ số nên chưa hiện
    assert so.ssi_overview_days(db, ["2026-11-20"]) == [D]


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_ssi_overview", ROOT / "scripts" / "fetch_ssi_overview.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClient:
    def get(self, path, params):
        if path.endswith("indexSummary"):
            return {"data": [{"tradingDate": params["tradingDate"], "indexValue": "100", "indexChange": "1"}]}
        if path.endswith("ohlc"):
            return {"data": [{"tradingDate": "2026/11/26 09:15:00", "open": "1", "high": "2", "low": "1", "close": "2", "volume": "3"}]}
        return {"data": [{"tradingDate": "2026/11/26", "symbol": params["symbol"], "close": "10"}], "pagesCount": 1}


def test_fetch_stores_one_day_and_the_page_can_read_it(tmp_path):
    mod = load_script()
    db, cdb = tmp_path / "m.db", tmp_path / "c.db"
    put_quote(db, f"{D}T14:59:55+07:00", "FPT")
    added = mod.store(mod.collect(FakeClient(), D, ["FPT"]), D, db, cdb)
    assert added == {"ssi_index_daily": 4, "ssi_daily": 1, "candles": 4}
    data = so.load_ssi_overview(db, cdb, DAY)
    assert list(data["cards"]["index_code"]) == ["VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"]
    assert len(data["minutes"]) == 4 and data["board"]["last_px"].tolist() == [10.0] and data["book_ts"].hour == 14
    assert so.ssi_overview_days(db, []) == [D]
    conn = _connect(db)                       # không ghi dòng chỉ số vào ssi_daily (lịch phiên đang đọc bảng đó)
    assert [r[0] for r in conn.execute("SELECT symbol FROM ssi_daily")] == ["FPT"]
    conn.close()


def test_fetch_refuses_a_day_that_is_not_closed(tmp_path):
    mod = load_script()
    with pytest.raises(SystemExit):
        mod.main(["--day", "2999-01-01", "--db", str(tmp_path / "m.db")])


@pytest.mark.parametrize("flag,backups", [([], 1), (["--khong-sao-luu"], 0)])
def test_fetch_backs_up_unless_the_caller_already_did(tmp_path, monkeypatch, flag, backups):
    mod = load_script()
    db = tmp_path / "m.db"
    put_quote(db, f"{D}T14:59:55+07:00", "FPT")
    (tmp_path / "ma.txt").write_text("FPT\n", encoding="utf-8")
    monkeypatch.setattr(mod, "SsiClient", FakeClient)
    made = []
    monkeypatch.setattr(mod, "backup_db", lambda *a: made.append(a) or tmp_path / "bk.db")
    monkeypatch.setattr(mod.dt, "datetime", type("T", (mod.dt.datetime,), {"now": classmethod(lambda cls, tz=None: mod.dt.datetime(2026, 11, 26, 15, 10, tzinfo=tz))}))
    assert mod.main(["--day", D, "--db", str(db), "--candles", str(tmp_path / "c.db"), "--symbols", str(tmp_path / "ma.txt"), *flag]) == 0
    assert len(made) == backups
