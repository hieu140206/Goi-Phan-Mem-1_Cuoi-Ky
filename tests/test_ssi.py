import math

import pandas as pd
import pytest

from data import ssi
from data.ssi import SsiClient, SsiError


class Resp:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, text
        self.ok = 200 <= status < 300

    def json(self):
        return self._body


class FakeSession:
    """Trả lần lượt các phản hồi đã dặn trước cho get/post và nhớ các lần gọi."""
    def __init__(self, gets=(), posts=()):
        self.gets, self.posts, self.calls = list(gets), list(posts), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers))
        return self.gets.pop(0)

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        return self.posts.pop(0)


def login_body(access="ACC", refresh="REF", exp=1000.0, rexp=30000.0):
    return {"tokenType": "Bearer", "accessToken": access, "expiresAt": exp, "refreshToken": refresh,
            "refreshExpiresAt": rexp}


def make(session, t=0.0, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return SsiClient("KEY123", "SECRET456", session=session, sleep=sleeps.append, now=lambda: t), sleeps


def test_login_then_reuse_token_until_near_expiry():
    s = FakeSession(posts=[Resp(body=login_body())])
    c, _ = make(s, t=0)
    assert c.token() == "ACC" and c.token() == "ACC"
    assert [x[0] for x in s.calls] == ["POST"]
    assert s.calls[0][1].endswith("/api/v3/auth/token") and s.calls[0][2] == {"apiKey": "KEY123", "apiSecret": "SECRET456"}


def test_refresh_when_access_token_expires_and_expiry_in_ms_is_understood():
    s = FakeSession(posts=[Resp(body=login_body(exp=1000.0, rexp=30000.0)),
                           Resp(body=login_body(access="ACC2", refresh="REF2", exp=1_794_213_900_000.0,
                                                rexp=1_794_241_800_000.0))])
    c, _ = make(s, t=0)
    assert c.token() == "ACC"
    c._now = lambda: 990.0                      # còn 10 giây < 60: phải làm mới
    assert c.token() == "ACC2"
    assert s.calls[1][1].endswith("/api/v3/auth/refresh") and s.calls[1][2] == {"refreshToken": "REF"}
    assert c._exp == 1_794_213_900.0            # mili giây (> 1e11) được đổi về giây


def test_refresh_failure_falls_back_to_login():
    s = FakeSession(posts=[Resp(body=login_body()), Resp(status=400, text="bad"), Resp(body=login_body(access="ACC3"))])
    c, _ = make(s, t=0)
    c.token()
    c._now = lambda: 995.0
    assert c.token() == "ACC3"
    assert s.calls[2][1].endswith("/api/v3/auth/token")


def test_missing_credentials_raise_without_network():
    s = FakeSession()
    c = SsiClient("", "", session=s)
    with pytest.raises(SsiError, match="Thiếu SSI_API_KEY"):
        c.token()
    assert s.calls == []


def test_secrets_never_appear_in_errors():
    s = FakeSession(posts=[Resp(status=401, text="invalid apiKey KEY123 secret SECRET456")])
    c, _ = make(s)
    with pytest.raises(SsiError) as e:
        c.token()
    assert "KEY123" not in str(e.value) and "SECRET456" not in str(e.value)


def test_get_pauses_when_rate_limit_almost_used_and_waits_on_429():
    s = FakeSession(posts=[Resp(body=login_body(exp=10_000))],
                    gets=[Resp(status=429), Resp(body={"data": []}, headers={"X-RateLimit-Remaining": "1"})])
    c, sleeps = make(s, t=0)
    assert c.get("/api/v3/data/x", {}) == {"data": []}
    assert sleeps == [ssi.BACKOFF_429, ssi.RATE_PAUSE]


def test_get_relogs_once_on_401_and_204_is_none():
    s = FakeSession(posts=[Resp(body=login_body(exp=10_000)), Resp(body=login_body(access="NEW", exp=10_000))],
                    gets=[Resp(status=401), Resp(status=204)])
    c, _ = make(s, t=0)
    assert c.get("/api/v3/data/x", {}) is None
    assert s.calls[-1][3]["Authorization"] == "Bearer NEW"


def test_parse_summary_numbers_dates_and_missing():
    rows = [{"symbol": "vcb", "tradingDate": "2026/11/09", "close": "53600", "totalMatch": "2985600",
             "totalForeignBuy": "", "remainForeignRoom": "845983212", "open": "abc"},
            {"symbol": "X", "tradingDate": "không phải ngày", "close": "1"},
            {"symbol": "", "tradingDate": "2026/11/09"}]
    df = ssi.parse_summary(rows, "2026-11-09T16:00:00+07:00")
    assert len(df) == 1                              # dòng sai ngày và thiếu mã bị bỏ
    r = df.iloc[0]
    assert (r.day, r.symbol, r.close, r.total_match, r.remain_room) == ("2026-11-09", "VCB", 53600.0, 2985600.0, 845983212.0)
    assert math.isnan(r.foreign_buy_vol) and math.isnan(r.open)   # rỗng và chữ -> NaN, không đoán số 0
    assert list(df.columns) == ssi.SSI_DAILY_COLUMNS


def test_parse_index_drops_rows_of_another_day():
    rows = [{"tradingDate": "2026/11/09", "indexValue": "1830.13", "totalAdvanceStock": "10", "totalBuyForeign": "5"}]
    assert len(ssi.parse_index(rows, "vn30", "2026-11-05")) == 0
    df = ssi.parse_index(rows, "vn30", "2026-11-09")
    assert df.iloc[0].index_code == "VN30" and df.iloc[0].advances == 10 and df.iloc[0].foreign_buy_vol == 5


def test_index_breadth_of_all_zeros_is_blank_not_zero():
    # SSI không tính số mã tăng/giảm cho VN30 (trả toàn "0"): để trống, còn thị trường thật vẫn giữ số.
    zero = {"tradingDate": "2026/11/09", "indexValue": "1830.13", "totalAdvanceStock": "0", "totalDeclineStock": "0",
            "totalNoChangeStock": "0", "totalCeilingStock": "0", "totalFloorStock": "0"}
    real = {**zero, "totalAdvanceStock": "163", "totalDeclineStock": "152", "totalNoChangeStock": "40",
            "totalCeilingStock": "5"}
    a = ssi.parse_index([zero], "VN30", "2026-11-09").iloc[0]
    b = ssi.parse_index([real], "VNINDEX", "2026-11-09").iloc[0]
    assert a.index_value == 1830.13 and all(math.isnan(a[c]) for c in ssi.BREADTH)
    assert (b.advances, b.declines, b.no_change, b.ceilings, b.floors) == (163, 152, 40, 5, 0)


def test_fetch_summary_follows_pages_and_dedups():
    page = lambda i, n: Resp(body={"pagesCount": 2, "pageIndex": i, "data": [
        {"symbol": "VCB", "tradingDate": f"2026/11/0{n}", "close": str(n)}]})
    s = FakeSession(posts=[Resp(body=login_body(exp=10_000))], gets=[page(1, 5), page(2, 6)])
    c, _ = make(s, t=0)
    df = ssi.fetch_summary(c, "VCB", "2026/11/01", "2026/11/09", page_size=1)
    assert df["day"].tolist() == ["2026-11-05", "2026-11-06"]
    assert [x[2]["pageIndex"] for x in s.calls if x[0] == "GET"] == [1, 2]
    assert s.calls[1][2]["symbol"] == "VCB"


def test_fetch_summary_for_index_uses_index_param_and_empty_is_ok():
    s = FakeSession(posts=[Resp(body=login_body(exp=10_000))], gets=[Resp(status=204)])
    c, _ = make(s, t=0)
    df = ssi.fetch_summary(c, "VN30", "2026/11/01", "2026/11/09", is_index=True)
    assert df.empty and s.calls[1][2]["index"] == "VN30" and "symbol" not in s.calls[1][2]


def test_save_and_load_roundtrip_is_idempotent_and_keeps_null(tmp_path):
    db = tmp_path / "m.db"
    df = ssi.parse_summary([{"symbol": "VCB", "tradingDate": "2026/11/09", "close": "53600", "totalMatch": "100"}])
    assert ssi.save_ssi_daily(df, db) == 1
    df2 = ssi.parse_summary([{"symbol": "VCB", "tradingDate": "2026/11/09", "close": "53700", "totalMatch": "100"}])
    ssi.save_ssi_daily(df2, db)                     # cùng (ngày, mã): ghi đè, không nhân đôi
    out = ssi.load_ssi_daily(db)
    assert len(out) == 1 and out.iloc[0].close == 53700
    assert pd.isna(out.iloc[0].foreign_buy_vol)     # ô thiếu giữ NULL, không thành 0


def test_index_days_already_stored(tmp_path):
    db = tmp_path / "m.db"
    rows = [{"tradingDate": "2026/11/05", "indexValue": "1740.7"}]
    ssi.save_ssi_index(ssi.parse_index(rows, "VNINDEX", "2026-11-05"), db)
    assert ssi.stored_index_days(db, "vnindex") == {"2026-11-05"}
    assert ssi.stored_index_days(tmp_path / "none.db", "VNINDEX") == set()
