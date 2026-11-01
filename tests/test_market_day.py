"""Lấy bù chuỗi chỉ số cuối ngày: chỉ chạy đúng giờ, chỉ thêm phần thiếu, một mã lỗi không làm mất mã khác."""
import json
from pathlib import Path

import pandas as pd
import pytest

from data.market_day import TooEarlyError, fetch_day_extras

TZ = "Asia/Ho_Chi_Minh"
MARKET = json.loads((Path(__file__).parent / "fixtures" / "neo_market_20261027.json").read_text(encoding="utf-8"))


class Client:
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []

    def get_index_intraday(self, code):
        self.calls.append(code)
        if code in self.fail:
            raise ConnectionError("x")
        return {**MARKET["4.2 intradayMarketIndex"], "indexCode": code}

    def get_index_detail(self, code):
        self.calls.append("4.3")
        return MARKET["4.3 marketIndexDetail"]


def now(s):
    return pd.Timestamp(s, tz=TZ)


def test_refuses_before_close_and_on_weekend(tmp_path):
    for t in ("2026-10-28 10:00", "2026-10-28 14:30", "2026-10-31 16:00"):  # trong phiên, trước 14:45, thứ Bảy
        with pytest.raises(TooEarlyError):
            fetch_day_extras(Client(), tmp_path, now(t))
    assert not (tmp_path / "raw").exists()


def test_adds_missing_series_and_keeps_existing(tmp_path):
    day = tmp_path / "raw" / "2026-10-28"
    day.mkdir(parents=True)
    (day / "market.json").write_text(json.dumps({"saved_at": "x", "intraday_VN30": {"keep": True}}), encoding="utf-8")
    client = Client()
    res = fetch_day_extras(client, tmp_path, now("2026-10-28 20:00"))
    saved = json.loads((day / "market.json").read_text(encoding="utf-8"))
    assert saved["intraday_VN30"] == {"keep": True} and "intraday_VN30" in res["kept"]   # không ghi đè
    assert {"intraday_VNINDEX", "intraday_HNXINDEX", "intraday_UPCOMINDEX", "index_detail"} <= set(res["added"])
    assert "VN30" not in client.calls                                                     # không gọi lại cái đã có
    assert saved["intraday_HNXINDEX"]["indexCode"] == "HNXINDEX" and saved["intraday_HNXINDEX"]["index"]
    assert fetch_day_extras(Client(), tmp_path, now("2026-10-28 20:05"))["added"] == []   # chạy lại không đổi gì


def test_one_failing_code_does_not_lose_others(tmp_path):
    res = fetch_day_extras(Client(fail={"UPCOMINDEX"}), tmp_path, now("2026-10-28 20:00"))
    assert res["errors"] == {"intraday_UPCOMINDEX": "ConnectionError"} and "intraday_HNXINDEX" in res["added"]


def test_overview_reads_hnx_and_upcom_series_from_market_json(tmp_path):
    """Có market.json mới thì thẻ HNX/UPCoM có đường biểu đồ trong ngày."""
    from data.overview import index_series

    fetch_day_extras(Client(), tmp_path, now("2026-10-28 20:00"))
    mj = json.loads((tmp_path / "raw" / "2026-10-28" / "market.json").read_text(encoding="utf-8"))
    empty = pd.DataFrame(columns=["ts", "index_code"])
    import datetime as dt
    for code in ("HNXINDEX", "UPCOMINDEX"):
        assert len(index_series(empty, dt.date(2026, 10, 28), code, mj)) > 300
