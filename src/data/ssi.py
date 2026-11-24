"""Dữ liệu SSI FastConnect v3 (REST, chỉ ĐỌC): tóm tắt giao dịch theo ngày, dùng BÙ lịch sử cho NEO.

NEO REST không có lịch sử, nên giá đóng cửa, khối lượng và mua bán nước ngoài của các ngày chưa ghi lấy từ SSI. NEO vẫn
là nguồn chính; dữ liệu SSI nằm ở bảng riêng (ssi_daily, ssi_index_daily), không ghi đè bảng nào của NEO, và phải được đối
chiếu với NEO (scripts/fetch_ssi_history.py --check) trước khi dùng cho phân tích.

Chỉ dùng API KEY và API SECRET (đăng nhập bằng /api/v3/auth/token). KHÔNG dùng Private Key (chỉ để ký lệnh đặt/sửa/hủy).
Khóa lấy từ .env (SSI_API_KEY, SSI_API_SECRET) và chỉ nằm trong bộ nhớ; không in ra log hay thông báo lỗi.

Đã kiểm chứng bằng dữ liệu thật 9/11/2026 (VCB, 4 ngày): giá đóng cửa, khối lượng, room khớp NEO 4/4 ngày, đơn vị đồng và cổ phiếu.
Giới hạn: 20 lần gọi cho MỖI API (header X-RateLimit-Remaining giảm dần); chưa rõ chu kỳ làm mới nên khi còn <= 1 lần thì
nghỉ rồi gọi tiếp, và gặp HTTP 429 thì chờ >= 30 giây (theo SDK chính thức của SSI).
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from neo_api import config as _config  # noqa: F401  (nạp .env)
from neo_api.config import TZ

from .schema import ASK_PX, ASK_QTY, BID_PX, BID_QTY

log = logging.getLogger(__name__)

API = "https://api.ssi.com.vn"
STREAM_URL = "wss://stream.ssi.com.vn/ws/v3"   # luồng dữ liệu; token trong header Authorization
TOKEN_MARGIN = 60        # làm mới token khi còn dưới 60 giây (token sống 15 phút)
RATE_PAUSE = 10          # giây nghỉ khi API sắp hết lượt gọi
BACKOFF_429 = 30         # giây chờ tối thiểu khi bị 429

SSI_DAILY_COLUMNS = [
    "day", "symbol", "open", "high", "low", "close", "average", "price_change", "price_change_pct",
    "total_match", "total_match_value", "total_deal", "total_deal_value",
    "foreign_buy_vol", "foreign_buy_val", "foreign_sell_vol", "foreign_sell_val", "remain_room", "total_room",
    "fetched_at",
]
SSI_INDEX_COLUMNS = [
    "day", "index_code", "index_value", "index_change", "index_pct", "total_match", "total_match_value",
    "total_deal", "total_deal_value", "advances", "declines", "no_change", "ceilings", "floors",
    "foreign_buy_vol", "foreign_buy_val", "foreign_sell_vol", "foreign_sell_val", "foreign_net_vol", "foreign_net_val",
    "fetched_at",
]
# Sổ lệnh 3 mức theo thanh từ luồng trực tiếp (bộ ghi: ssi_recorder.py). src_ts = giờ trong tin của SSI.
SSI_QUOTE_COLUMNS = ["ts", "symbol", *BID_PX, *BID_QTY, *ASK_PX, *ASK_QTY, "n_msgs", "age_ms", "src_ts"]
SSI_QUOTE_TEXT = ("ts", "symbol", "src_ts")
SSI_DAILY_TEXT = ("day", "symbol", "fetched_at")
SSI_INDEX_TEXT = ("day", "index_code", "fetched_at")

_SUMMARY_FIELDS = {
    "open": "open", "high": "high", "low": "low", "close": "close", "average": "average",
    "priceChange": "price_change", "priceChangePercentage": "price_change_pct",
    "totalMatch": "total_match", "totalMatchValue": "total_match_value",
    "totalDeal": "total_deal", "totalDealValue": "total_deal_value",
    "totalForeignBuy": "foreign_buy_vol", "totalForeignBuyValue": "foreign_buy_val",
    "totalForeignSell": "foreign_sell_vol", "totalForeignSellValue": "foreign_sell_val",
    "remainForeignRoom": "remain_room", "totalForeignRoom": "total_room",
}
_INDEX_FIELDS = {
    "indexValue": "index_value", "indexChange": "index_change", "indexChangePercentage": "index_pct",
    "totalMatch": "total_match", "totalMatchValue": "total_match_value",
    "totalDeal": "total_deal", "totalDealValue": "total_deal_value",
    "totalAdvanceStock": "advances", "totalDeclineStock": "declines", "totalNoChangeStock": "no_change",
    "totalCeilingStock": "ceilings", "totalFloorStock": "floors",
    "totalBuyForeign": "foreign_buy_vol", "totalBuyForeignValue": "foreign_buy_val",
    "totalSellForeign": "foreign_sell_vol", "totalSellForeignValue": "foreign_sell_val",
    "netPurchasesForeignVolume": "foreign_net_vol", "netPurchasesForeignValue": "foreign_net_val",
}


class SsiError(RuntimeError):
    """Lỗi khi gọi SSI (đăng nhập, mạng, giới hạn tần suất, dữ liệu sai định dạng)."""


# ---------------------------------------------------------------- client
class SsiClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], float] = time.time) -> None:
        self._key = api_key if api_key is not None else os.getenv("SSI_API_KEY", "")
        self._secret = api_secret if api_secret is not None else os.getenv("SSI_API_SECRET", "")
        self._session, self._sleep, self._now = session or requests.Session(), sleep, now
        self._access = self._refresh_token = ""
        self._exp = self._refresh_exp = 0.0

    # --- đăng nhập và làm mới token
    def _clean(self, text: object) -> str:
        s = str(text)
        for secret in (self._key, self._secret, self._access, self._refresh_token):
            if secret:
                s = s.replace(secret, "***")
        return s

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self._session.post(f"{API}{path}", json=body, timeout=15)
        except requests.RequestException as exc:
            raise SsiError(f"Lỗi mạng khi gọi {path}: {type(exc).__name__}") from None
        if not r.ok:
            raise SsiError(f"{path} trả HTTP {r.status_code}: {self._clean(r.text[:120])}")
        try:
            return r.json()
        except ValueError:
            raise SsiError(f"{path} không trả JSON") from None

    @staticmethod
    def _to_seconds(v: object) -> float:
        v = float(v)
        return v / 1000 if v > 1e11 else v      # tài liệu SSI có chỗ ghi giây, chỗ ghi mili giây

    def _store(self, body: dict) -> None:
        if not isinstance(body, dict) or not body.get("accessToken"):
            raise SsiError("Phản hồi đăng nhập không có accessToken")
        self._access = body["accessToken"]
        self._exp = self._to_seconds(body.get("expiresAt") or 0)
        self._refresh_token = body.get("refreshToken") or self._refresh_token
        self._refresh_exp = self._to_seconds(body.get("refreshExpiresAt") or 0)

    def token(self) -> str:
        """Token còn hạn; tự làm mới bằng refreshToken, hết cách thì đăng nhập lại."""
        if self._access and self._exp - self._now() > TOKEN_MARGIN:
            return self._access
        if self._refresh_token and self._refresh_exp - self._now() > TOKEN_MARGIN:
            try:
                self._store(self._post("/api/v3/auth/refresh", {"refreshToken": self._refresh_token}))
                return self._access
            except SsiError as exc:
                log.warning("Làm mới token SSI lỗi (%s), đăng nhập lại", exc)
        if not self._key or not self._secret:
            raise SsiError("Thiếu SSI_API_KEY hoặc SSI_API_SECRET trong .env")
        self._store(self._post("/api/v3/auth/token", {"apiKey": self._key, "apiSecret": self._secret}))
        return self._access

    def invalidate(self) -> None:
        self._access, self._exp = "", 0.0

    # --- gọi API dữ liệu
    def get(self, path: str, params: dict) -> dict | list | None:
        """GET trả JSON; None khi 204 (không có dữ liệu). Tự đăng nhập lại khi 401, chờ khi 429."""
        relogged = False
        for attempt in range(1, 6):
            headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}
            try:
                r = self._session.get(f"{API}{path}", params=params, headers=headers, timeout=20)
            except requests.RequestException as exc:
                log.warning("Lỗi mạng SSI (lần %d/5): %s", attempt, type(exc).__name__)
                self._sleep(2 ** attempt)
                continue
            if r.status_code == 429:
                log.warning("SSI báo quá giới hạn (429), chờ rồi thử lại")
                self._sleep(BACKOFF_429 * attempt)
                continue
            if r.status_code == 401 and not relogged:
                self.invalidate()
                self._refresh_token = ""
                relogged = True
                continue
            if r.status_code == 204:
                return None
            if not r.ok:
                raise SsiError(f"{path} trả HTTP {r.status_code}: {self._clean(r.text[:120])}")
            remaining = r.headers.get("X-RateLimit-Remaining")
            if remaining is not None and remaining.isdigit() and int(remaining) <= 1:
                self._sleep(RATE_PAUSE)             # sắp hết lượt của API này
            try:
                return r.json()
            except ValueError:
                raise SsiError(f"{path} không trả JSON") from None
        raise SsiError(f"Gọi {path} thất bại sau 5 lần thử")


# ---------------------------------------------------------------- phân tích phản hồi
def _num(v: object) -> float:
    """Chuỗi số của SSI -> float; rỗng, thiếu hoặc không đọc được thì NaN (không đoán)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return float("nan")
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def _day(v: object) -> str | None:
    """'2026/11/09' hoặc '2026/11/09 00:00:00' -> '2026-11-09'; không đọc được thì None."""
    try:
        return datetime.strptime(str(v)[:10], "%Y/%m/%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _rows(body: object) -> list[dict]:
    if isinstance(body, dict):
        body = body.get("data")
    return [r for r in (body or []) if isinstance(r, dict)]


def _stamp() -> str:
    return pd.Timestamp.now(tz=TZ).isoformat(timespec="seconds")


def parse_summary(rows: list[dict], fetched_at: str | None = None) -> pd.DataFrame:
    out = []
    for r in rows:
        day, sym = _day(r.get("tradingDate")), str(r.get("symbol") or "").strip().upper()
        if not day or not sym:
            continue
        rec = {"day": day, "symbol": sym, "fetched_at": fetched_at or _stamp()}
        rec.update({dst: _num(r.get(src)) for src, dst in _SUMMARY_FIELDS.items()})
        out.append(rec)
    return pd.DataFrame(out, columns=SSI_DAILY_COLUMNS)


def parse_index(rows: list[dict], index_code: str, day: str, fetched_at: str | None = None) -> pd.DataFrame:
    """Một dòng/ngày. Ngày lấy từ tradingDate của phản hồi; không khớp ngày đã hỏi thì bỏ (không gán nhầm ngày)."""
    out = []
    for r in rows:
        d = _day(r.get("tradingDate"))
        if d != day:
            continue
        rec = {"day": d, "index_code": index_code.upper(), "fetched_at": fetched_at or _stamp()}
        rec.update({dst: _num(r.get(src)) for src, dst in _INDEX_FIELDS.items()})
        out.append(_blank_unavailable_breadth(rec))
    return pd.DataFrame(out, columns=SSI_INDEX_COLUMNS)


BREADTH = ["advances", "declines", "no_change", "ceilings", "floors"]


def _blank_unavailable_breadth(rec: dict) -> dict:
    """SSI trả toàn số 0 cho số mã tăng/giảm/đứng giá của chỉ số rổ như VN30 (thật tế chưa tính): để trống, không lưu số 0
    giả. Một thị trường có giao dịch không thể có tăng + giảm + đứng giá = 0."""
    if all(rec.get(c) == 0 for c in ("advances", "declines", "no_change")):
        rec.update({c: float("nan") for c in BREADTH})
    return rec


# ---------------------------------------------------------------- lấy dữ liệu
def fetch_summary(client: SsiClient, code: str, frm: str, to: str, is_index: bool = False,
                  page_size: int = 100) -> pd.DataFrame:
    """Tóm tắt giao dịch từng ngày của một mã (hoặc một chỉ số) trong [frm, to], dạng YYYY/MM/DD. Tự lật trang."""
    frames, page, stamp = [], 1, _stamp()
    while True:
        body = client.get("/api/v3/data/securitiesSummary",
                          {"index" if is_index else "symbol": code, "from": frm, "to": to,
                           "pageIndex": page, "pageSize": page_size})
        frames.append(parse_summary(_rows(body), stamp))
        pages = int(body.get("pagesCount") or 1) if isinstance(body, dict) else 1
        if page >= pages:
            break
        page += 1
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SSI_DAILY_COLUMNS)
    return df.drop_duplicates(["day", "symbol"], keep="last").reset_index(drop=True)


def fetch_index_day(client: SsiClient, index_code: str, day: str) -> pd.DataFrame:
    """Chỉ số một ngày (điểm, thanh khoản, số mã tăng/giảm/trần/sàn, mua bán nước ngoài). day dạng YYYY-MM-DD."""
    body = client.get("/api/v3/data/indexSummary", {"index": index_code, "tradingDate": day.replace("-", "/")})
    return parse_index(_rows(body), index_code, day)


# ---------------------------------------------------------------- lưu và đọc (SQLite market.db)
def _upsert(df: pd.DataFrame, table: str, columns: list[str], db_path: Path) -> int:
    if df.empty:
        return 0
    from .storage import _connect  # noqa: PLC0415  (tránh import vòng: storage đọc danh sách cột ở đây)
    data = df[columns].astype(object)
    data = data.where(data.notna(), None)
    with _connect(Path(db_path)) as conn:
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            data.itertuples(index=False, name=None),
        )
        return conn.total_changes - before


def save_ssi_daily(df: pd.DataFrame, db_path: Path) -> int:
    """Mỗi (ngày, mã) giữ bản mới nhất. Dòng chỉ số (symbol = VNINDEX, VN30...) cũng nằm trong bảng này."""
    return _upsert(df, "ssi_daily", SSI_DAILY_COLUMNS, db_path)


def save_ssi_index(df: pd.DataFrame, db_path: Path) -> int:
    return _upsert(df, "ssi_index_daily", SSI_INDEX_COLUMNS, db_path)


def _read(db_path: Path, sql: str, params: tuple, columns: list[str]) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=columns)
    from .storage import _connect  # noqa: PLC0415
    with _connect(Path(db_path)) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def load_ssi_daily(db_path: Path) -> pd.DataFrame:
    return _read(db_path, "SELECT * FROM ssi_daily ORDER BY symbol, day", (), SSI_DAILY_COLUMNS)


def load_ssi_index(db_path: Path) -> pd.DataFrame:
    return _read(db_path, "SELECT * FROM ssi_index_daily ORDER BY index_code, day", (), SSI_INDEX_COLUMNS)


def stored_index_days(db_path: Path, index_code: str) -> set[str]:
    df = _read(db_path, "SELECT day FROM ssi_index_daily WHERE index_code = ?", (index_code.upper(),), ["day"])
    return set(df["day"])


# ---------- sổ lệnh SSI theo phút (dùng thay NEO cho ngày NEO không ghi được) ----------
SSI_QUOTE_COLS = ["bid_px1", "bid_px2", "bid_px3", "bid_qty1", "bid_qty2", "bid_qty3",
                  "ask_px1", "ask_px2", "ask_px3", "ask_qty1", "ask_qty2", "ask_qty3"]
MINUTE_GRID = [f"{h:02d}:{m:02d}:00" for h in (9, 10, 11) for m in range(60) if "09:16" <= f"{h:02d}:{m:02d}" <= "11:30"] + \
              [f"{h:02d}:{m:02d}:00" for h in (13, 14) for m in range(60) if "13:01" <= f"{h:02d}:{m:02d}" <= "14:30"]
MAX_STALE_SECONDS = 60


def ssi_quote_days(db_path: Path) -> list[str]:
    """Các ngày (YYYY-MM-DD) có thanh sổ lệnh SSI trong bảng ssi_quotes. Bảng chưa có thì rỗng."""
    import sqlite3
    if not Path(db_path).exists():
        return []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            return [r[0] for r in con.execute("SELECT DISTINCT substr(ts, 1, 10) FROM ssi_quotes ORDER BY 1")]
    except sqlite3.Error:
        return []


def load_ssi_minute_quotes(db_path: Path, days: list[str]) -> pd.DataFrame:
    """Sổ lệnh SSI lấy mẫu MỖI PHÚT, cùng các phút với lần chụp NEO (09:16-11:30 và 13:01-14:30).

    Mỗi (mã, phút) lấy thanh 5 giây MỚI NHẤT có thời điểm không sau phút đó và không cũ quá 60 giây; không có thì
    bỏ dòng (không điền, không nội suy). Chỉ giữ giá và khối lượng 3 mức mua bán (SSI không có giá khớp và tổng khối
    lượng khớp, các cột đó để trống). Trả DataFrame cột ts (UTC+7), symbol và SSI_QUOTE_COLS."""
    import sqlite3
    empty = pd.DataFrame(columns=["ts", "symbol", *SSI_QUOTE_COLS])
    if not days or not Path(db_path).exists():
        return empty
    marks = pd.DataFrame([(f"{d}T{t}+07:00",) for d in days for t in MINUTE_GRID], columns=["ts"])
    marks["ts"] = pd.to_datetime(marks["ts"]).dt.tz_convert(TZ)
    marks = marks.sort_values("ts")
    marks_utc = marks.assign(_k=marks["ts"].dt.tz_convert("UTC"))
    q = ",".join("?" for _ in days)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        raw = pd.read_sql_query(
            f"SELECT ts, symbol, {', '.join(SSI_QUOTE_COLS)} FROM ssi_quotes WHERE substr(ts, 1, 10) IN ({q})",
            con, params=tuple(days))
    if raw.empty:
        return empty
    raw["ts"] = pd.to_datetime(raw["ts"], utc=True)
    raw = raw.sort_values("ts")
    parts = []
    for sym, g in raw.groupby("symbol"):
        m = pd.merge_asof(marks_utc[["ts", "_k"]].rename(columns={"ts": "mark"}), g.rename(columns={"ts": "bar_ts"}),
                          left_on="_k", right_on="bar_ts", direction="backward",
                          tolerance=pd.Timedelta(seconds=MAX_STALE_SECONDS))
        m = m.dropna(subset=["bar_ts"])
        m["symbol"] = sym
        parts.append(m)
    out = pd.concat(parts, ignore_index=True) if parts else empty
    out = out.rename(columns={"mark": "ts"})[["ts", "symbol", *SSI_QUOTE_COLS]]
    return out.sort_values(["symbol", "ts"]).reset_index(drop=True)
