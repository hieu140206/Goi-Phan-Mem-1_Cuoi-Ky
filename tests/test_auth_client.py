import time
from unittest.mock import MagicMock, patch

import pytest

from neo_api.auth import LoginError, TokenInfo, TokenManager, login
from neo_api.client import NeoApiError, NeoClient
from neo_api.config import Settings

SETTINGS = Settings(base_url="https://x.test/neo-api", ws_url="ws://x", max_rps=1000, db_path="x.db",
                    auth_url="https://auth.test/token")


def resp(status=200, body=None, ok=None):
    r = MagicMock()
    r.status_code = status
    r.ok = (status < 400) if ok is None else ok
    r.json.return_value = body if body is not None else {}
    return r


def login_ok(token="TOK", **extra):
    return resp(200, {"data": {"access_token": token, **extra}})


@patch("neo_api.auth.requests.post")
def test_login_returns_token_and_only_field_names(post):
    post.return_value = login_ok("secret-token", refresh_token="r", expires_in=3600)
    info = login(SETTINGS, "u", "p")
    assert info.access_token == "secret-token"
    assert info.other_fields == ["expires_in", "refresh_token"]   # chỉ tên, không có giá trị
    assert info.expires_at and info.expires_at > time.time() + 3500
    assert post.call_args.kwargs["json"] == {"username": "u", "password": "p"}


@pytest.mark.parametrize("status", [400, 401, 403])
@patch("neo_api.auth.requests.post")
def test_login_rejected_message_never_contains_credentials(post, status):
    post.return_value = resp(status)
    with pytest.raises(LoginError) as e:
        login(SETTINGS, "my-user", "my-secret-pass")
    assert "my-user" not in str(e.value) and "my-secret-pass" not in str(e.value)


@patch("neo_api.auth.requests.post")
def test_login_bad_shape(post):
    post.return_value = resp(200, {"data": {}})
    with pytest.raises(LoginError):
        login(SETTINGS, "u", "p")


def test_token_info_expiry_with_margin():
    t = TokenInfo("x", time.time() + 30, [])
    assert t.is_expired()                       # còn 30 giây, nhỏ hơn mốc làm mới 60 giây
    assert not TokenInfo("x", None, []).is_expired()


@patch("neo_api.auth.requests.post")
def test_manager_caches_and_relogs_after_invalidate(post):
    post.return_value = login_ok("A")
    m = TokenManager(SETTINGS, "u", "p")
    assert m.get() == "A" and m.get() == "A"
    assert post.call_count == 1                 # token giữ trong bộ nhớ, không đăng nhập lại
    post.return_value = login_ok("B")
    m.invalidate()
    assert m.get() == "B" and post.call_count == 2


@patch("neo_api.auth.requests.post")
def test_manager_uses_static_token_until_rejected(post):
    s = Settings(**{**SETTINGS.__dict__, "token": "STATIC"})
    m = TokenManager(s, "u", "p")
    assert m.get() == "STATIC" and post.call_count == 0
    post.return_value = login_ok("FRESH")
    m.invalidate()
    assert m.get() == "FRESH"


@patch("neo_api.auth.sys.stdin")
def test_manager_without_credentials_and_no_terminal_raises(stdin):
    stdin.isatty.return_value = False
    with pytest.raises(LoginError):
        TokenManager(SETTINGS).get()


def test_settings_repr_hides_secrets():
    s = Settings(**{**SETTINGS.__dict__, "token": "SECRETTOKEN", "username": "uu", "password": "SECRETPASS"})
    text = repr(s)
    assert "SECRETTOKEN" not in text and "SECRETPASS" not in text


def make_client(token_values):
    tokens = MagicMock()
    tokens.get.side_effect = token_values
    return NeoClient(SETTINGS, tokens), tokens


ENVELOPE = {"status": 1, "code": "NEOINP000000", "message": "ok", "data": {"content": [{"indexCode": "VN30"}], "last": True, "totalPages": 1}}


def test_get_sends_required_headers_and_unwraps_data():
    client, _ = make_client(["T1"])
    with patch.object(client._session, "get", return_value=resp(200, ENVELOPE)) as g:
        data = client.get("market/indexList", {"exchangeCode": "ALL"})
    h = g.call_args.kwargs["headers"]
    assert h["Authorization"] == "Bearer T1" and h["x-device"] and h["x-devicetype"]
    assert g.call_args.args[0] == "https://x.test/neo-api/market/indexList"
    assert data["content"][0]["indexCode"] == "VN30"


def test_401_triggers_one_relogin_then_succeeds():
    client, tokens = make_client(["OLD", "NEW"])
    with patch.object(client._session, "get", side_effect=[resp(401), resp(200, ENVELOPE)]):
        assert client.get("market/indexList")["content"]
    tokens.invalidate.assert_called_once()


def test_repeated_401_raises_clear_error():
    client, _ = make_client(["A", "B", "C"])
    with patch.object(client._session, "get", return_value=resp(401)):
        with pytest.raises(NeoApiError, match="Xác thực thất bại"):
            client.get("market/indexList")


def test_status_not_one_is_an_error():
    client, _ = make_client(["T"])
    bad = {"status": 0, "code": "E1", "message": "boom", "data": None}
    with patch.object(client._session, "get", return_value=resp(200, bad)):
        with pytest.raises(NeoApiError, match="E1"):
            client.get("market/indexList")


def test_get_index_list_walks_all_pages():
    client, _ = make_client(["T"] * 5)
    p1 = {"status": 1, "data": {"content": [{"indexCode": "A"}], "last": False, "totalPages": 2}}
    p2 = {"status": 1, "data": {"content": [{"indexCode": "B"}], "last": True, "totalPages": 2}}
    with patch.object(client._session, "get", side_effect=[resp(200, p1), resp(200, p2)]) as g:
        items = client.get_index_list(page_size=1)
    assert [i["indexCode"] for i in items] == ["A", "B"]
    assert g.call_args_list[1].kwargs["params"]["pageNo"] == 2


# ---- 4.6 / 4.7 (theo tài liệu NEO) ----
def page_body(content, last=True, total_pages=1):
    return {"status": 1, "code": "NEOINP000000", "data": {"content": content, "last": last, "totalPages": total_pages}}


@patch("neo_api.client.requests.Session.get")
def test_stocks_by_index_walks_pages_and_sends_params(get):
    s = Settings(**{**SETTINGS.__dict__, "token": "T"})
    client = NeoClient(s, TokenManager(s))
    get.side_effect = [resp(200, page_body([{"symbol": "ACB"}, {"symbol": "vcb"}], last=False, total_pages=2)),
                       resp(200, page_body([{"symbol": "FPT"}, {"symbol": None}]))]
    assert client.get_index_symbols("VN30") == ["ACB", "FPT", "VCB"]
    first = get.call_args_list[0]
    assert first.args[0] == "https://x.test/neo-api/stock/stockDetailByIndex"
    assert first.kwargs["params"]["indexCode"] == "VN30" and first.kwargs["params"]["pageNo"] == 1
    assert get.call_args_list[1].kwargs["params"]["pageNo"] == 2
    h = first.kwargs["headers"]
    assert h["Authorization"] == "Bearer T" and h["x-device"] and h["x-devicetype"]


@patch("neo_api.client.requests.Session.get")
def test_stock_detail_joins_symbols(get):
    s = Settings(**{**SETTINGS.__dict__, "token": "T"})
    get.return_value = resp(200, page_body([{"symbol": "VPB", "bidPrice1": "ATO"}]))
    rows = NeoClient(s, TokenManager(s)).get_stock_detail(["VPB", "HPG"], market="HOSE")
    assert rows[0]["symbol"] == "VPB"
    p = get.call_args.kwargs["params"]
    assert p["symbols"] == "VPB,HPG" and p["marketCode"] == "HOSE" and p["stockType"] == "ST"


@patch("neo_api.client.requests.Session.get")
def test_status_not_one_is_error(get):
    s = Settings(**{**SETTINGS.__dict__, "token": "T"})
    get.return_value = resp(200, {"status": 0, "code": "NEOERR", "message": "bad", "data": None})
    with pytest.raises(NeoApiError):
        NeoClient(s, TokenManager(s)).get_stocks_by_index("VN30")


# ---- 4.2 / 4.3 / 4.4 và mã lỗi (theo tài liệu NEO) ----
def ok(data):
    return resp(200, {"status": 1, "code": "NEOINP000000", "data": data})


@patch("neo_api.client.requests.Session.get")
def test_index_and_status_endpoints(get):
    s = Settings(**{**SETTINGS.__dict__, "token": "T"})
    c = NeoClient(s, TokenManager(s))
    get.return_value = ok({"indexCode": "VN30", "indexValue": 1350.5, "index": [{"indexValue": 1349, "volume": 10}]})
    assert c.get_index_intraday("VN30")["index"][0]["volume"] == 10
    assert get.call_args.args[0].endswith("/market/intradayMarketIndex")
    get.return_value = ok([{"indexCode": "VN30", "advances": 12}])
    assert c.get_index_detail()[0]["advances"] == 12
    get.return_value = ok([{"marketCode": "HOSE", "indexCode": "VNINDEX", "marketStatus": "LO"}])
    assert c.get_market_status()[0]["marketStatus"] == "LO"
    assert get.call_args.kwargs["params"] == {"marketCode": "ALL"}


@patch("neo_api.client.requests.Session.get")
def test_empty_code_returns_empty_and_errors_are_explained(get):
    s = Settings(**{**SETTINGS.__dict__, "token": "T"})
    c = NeoClient(s, TokenManager(s))
    get.return_value = resp(200, {"status": 0, "code": "NEOINP000004", "message": "empty", "data": None})
    assert c.get_market_status() == []
    get.return_value = resp(200, {"status": 0, "code": "NEOINP000403", "message": "x", "data": None})
    with pytest.raises(NeoApiError, match="IP"):
        c.get_market_status()
