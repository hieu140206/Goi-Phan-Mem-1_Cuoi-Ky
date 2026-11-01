"""Nhận dữ liệu thị trường qua WebSocket của NEO (Market Stream), tự kết nối lại khi mất kết nối.

Quy trình theo tài liệu NEO:
  1. Kết nối tới Market Stream.
  2. Gửi {"action": "auth", "data": "<jwt>"} (xác thực bằng tin nhắn, không dùng header; token lấy từ
     neo_api/auth.py, mỗi lần kết nối lại sẽ hỏi lại token mới nhất) và chờ
     {"type": "auth", "status": "success"}.
  3. Gửi {"type": "sub", "channel": "stockInfo", "listId": [mã...]}.
  4. Nhận thông điệp stockInfo (giá, sổ lệnh 3 mức, OHLC, khối lượng, dữ liệu nước ngoài).

Chưa xác nhận bằng dữ liệu thật (cần kiểm tra bằng `scripts/record_stream.py --dump`):
  - thông điệp stockInfo có nằm trong lớp bọc {"data": ...} hay không (hàm extract_records xử lý cả hai);
  - mỗi thông điệp là trạng thái đầy đủ của mã hay chỉ trường thay đổi (đang giả định là đầy đủ).
Thông điệp NEO không có dấu thời gian, nên thời điểm do bộ ghi dữ liệu gán (xem data/snapshot.py).
Tài liệu chưa công bố giới hạn tần suất của WebSocket; không áp 5 RPS của REST cho kênh này.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

from .binary_msg import DecodeError, decode_stock_info, is_stock_info, looks_binary
from .config import Settings, get_settings

log = logging.getLogger(__name__)

AUTH_TIMEOUT = 5.0  # chờ tin xác nhận tối đa 5 giây (máy chủ thật không gửi)


class AuthError(RuntimeError):
    """NEO từ chối token. Không thử lại vì sẽ chỉ làm phiền máy chủ; cần lấy token mới."""


def _field_map() -> dict[str, str]:
    m = {"symbol": "symbol", "closePrice": "last_px", "totalTradingVolume": "total_vol",
         "totalTradingValue": "total_value", "refPrice": "ref_px", "openPrice": "open_px",
         "highPrice": "high_px", "lowPrice": "low_px",
         "foreignBuyVolume": "foreign_buy_vol", "foreignSellVolume": "foreign_sell_vol",
         "foreignBuyValue": "foreign_buy_val", "foreignSellValue": "foreign_sell_val",
         "foreignNetValue": "foreign_net_val", "foreignRemain": "foreign_remain", "foreignRoom": "foreign_room",
         "ceilingPrice": "ceil_px", "floorPrice": "floor_px", "closeVol": "last_vol"}
    for i in (1, 2, 3):
        m.update({f"bidPrice{i}": f"bid_px{i}", f"bidVol{i}": f"bid_qty{i}",
                  f"askPrice{i}": f"ask_px{i}", f"askVol{i}": f"ask_qty{i}"})
    return m


# Tên trường NEO (stockInfo) -> cột chuẩn của dự án.
FIELD_MAP: dict[str, str] = _field_map()


def build_auth_message(token: str) -> str:
    return json.dumps({"action": "auth", "data": token})


def build_subscribe_message(symbols: list[str], channel: str = "stockInfo") -> str:
    return json.dumps({"type": "sub", "channel": channel, "listId": list(symbols)})


def extract_records(msg: object) -> list[dict]:
    """Lấy danh sách bản ghi stockInfo từ một thông điệp đã giải mã JSON (chấp nhận vài dạng bọc)."""
    if isinstance(msg, list):
        items = msg
    elif isinstance(msg, dict):
        if msg.get("type") == "auth":
            return []
        data = msg.get("data")
        if isinstance(data, dict) and "symbol" in data:
            items = [data]
        elif isinstance(data, list):
            items = data
        elif "symbol" in msg:
            items = [msg]
        else:
            items = []
    else:
        items = []
    return [it for it in items if isinstance(it, dict) and it.get("symbol")]


def map_record(rec: dict) -> dict:
    """Đổi tên trường NEO sang cột chuẩn. Giá có thể là số, chuỗi ("29750.0") hoặc chữ (ATO/ATC): giữ nguyên
    để bước làm sạch (data/schema.py) xử lý và đếm."""
    row = {std: rec.get(src) for src, std in FIELD_MAP.items()}
    # REST 4.6/4.7 không trả foreignNetValue (kiểm tra 27/10/2026): tự tính = giá trị mua - giá trị bán.
    if row.get("foreign_net_val") is None:
        buy, sell = rec.get("foreignBuyValue"), rec.get("foreignSellValue")
        if isinstance(buy, (int, float)) and isinstance(sell, (int, float)):
            row["foreign_net_val"] = buy - sell
    return row


def parse_message(raw: str | bytes) -> list[dict]:
    """Thông điệp thô -> danh sách dòng chuẩn (chưa có ts). Trả [] cho tin không phải dữ liệu.

    Máy chủ thật (28/10/2026) gửi tin NHỊ PHÂN, không phải JSON như tài liệu: stockInfo được giải mã bằng
    binary_msg.decode_stock_info (đã đối chiếu khớp với REST 4.7). Vẫn đọc JSON nếu NEO đổi về đúng tài liệu."""
    if looks_binary(raw):
        try:
            if is_stock_info(raw):
                return [map_record(decode_stock_info(raw))]
        except DecodeError as exc:
            log.warning("Bỏ qua tin stockInfo không giải mã được: %s", exc)
        return []  # marketSession/marketInfo/marketVolume: bộ ghi sổ lệnh không dùng
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("Bỏ qua thông điệp không phải JSON")
        return []
    return [map_record(r) for r in extract_records(msg)]


def _redirect_target(exc: Exception) -> str | None:
    """Nếu máy chủ chuyển hướng ws:// sang http(s)://, websockets báo InvalidURI kèm địa chỉ đích; lấy địa chỉ đó."""
    uri = getattr(exc, "uri", "") or ""
    if uri.startswith("https://"):
        return "wss://" + uri[len("https://"):]
    if uri.startswith("http://"):
        return "ws://" + uri[len("http://"):]
    return None


def connect_ws(url: str):
    """Trả về kết nối WebSocket (dùng với async with). Tự đổi sang wss:// nếu máy chủ chuyển hướng sang https://."""
    return _ConnectWithRedirect(url)


class _ConnectWithRedirect:
    def __init__(self, url: str) -> None:
        self.url = url
        self._cm = None

    async def __aenter__(self):
        try:
            self._cm = websockets.connect(self.url, ping_interval=20)
            return await self._cm.__aenter__()
        except websockets.exceptions.InvalidURI as exc:
            new_url = _redirect_target(exc)
            if not new_url or new_url == self.url:
                raise
            log.warning("Máy chủ chuyển hướng sang kết nối mã hóa, thử lại với %s", new_url)
            print(f"Máy chủ yêu cầu kết nối mã hóa, chuyển sang: {new_url}")
            self.url = new_url
            self._cm = websockets.connect(new_url, ping_interval=20)
            return await self._cm.__aenter__()

    async def __aexit__(self, *exc_info):
        return await self._cm.__aexit__(*exc_info)


async def _authenticate(ws, token: str) -> None:
    await ws.send(build_auth_message(token))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + AUTH_TIMEOUT
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            # Máy chủ thật (27-28/10/2026) KHÔNG gửi tin xác nhận như tài liệu, nhưng vẫn gửi dữ liệu sau khi đăng ký
            # kênh. Nên hết thời gian chờ thì đi tiếp; token sai thì máy chủ sẽ không gửi dữ liệu hoặc đóng kết nối.
            log.info("Không có tin xác nhận xác thực, tiếp tục đăng ký kênh (đúng hành vi máy chủ hiện tại)")
            return
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            continue
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(msg, dict) and msg.get("type") == "auth":
            if msg.get("status") == "success":
                return
            raise AuthError(f"Xác thực thất bại: {str(msg.get('data'))[:80]}")


async def run_stream(
    symbols: list[str],
    on_row: Callable[[dict], Awaitable[None] | None],
    settings: Settings | None = None,
    max_backoff: float = 60.0,
    token_provider: Callable[[], str] | None = None,
) -> None:
    """Chạy vô hạn. token_provider được gọi MỖI LẦN kết nối (kể cả kết nối lại) để luôn dùng token còn hạn."""
    settings = settings or get_settings()
    if not settings.ws_url:
        raise RuntimeError("Thiếu NEO_WS_URL trong .env")
    provider = token_provider or (lambda: settings.token or "")
    backoff = 1.0
    while True:
        try:
            async with connect_ws(settings.ws_url) as ws:
                log.info("Đã kết nối WebSocket, đang xác thực")
                token = provider()
                if not token:
                    raise RuntimeError("Chưa có token. Đăng nhập hoặc điền NEO_API_TOKEN (xem .env.example).")
                await _authenticate(ws, token)
                await ws.send(build_subscribe_message(symbols))
                log.info("Đã xác thực và đăng ký %d mã", len(symbols))
                backoff = 1.0
                async for raw in ws:
                    for row in parse_message(raw):
                        result = on_row(row)
                        if asyncio.iscoroutine(result):
                            await result
        except AuthError:
            raise
        except (websockets.WebSocketException, OSError, TimeoutError) as exc:
            log.warning("Mất kết nối (%s). Thử lại sau %.0f giây", type(exc).__name__, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


async def dump_messages(
    symbols: list[str], n: int, settings: Settings | None = None, token_provider: Callable[[], str] | None = None
) -> list[str]:
    """Nhận n thông điệp thô đầu tiên sau khi đăng ký để xem định dạng thật. Không ghi gì xuống đĩa."""
    settings = settings or get_settings()
    if not settings.ws_url:
        raise RuntimeError("Thiếu NEO_WS_URL trong .env")
    token = (token_provider or (lambda: settings.token or ""))()
    if not token:
        raise RuntimeError("Chưa có token. Đăng nhập hoặc điền NEO_API_TOKEN (xem .env.example).")
    out: list[str] = []
    async with connect_ws(settings.ws_url) as ws:
        await _authenticate(ws, token)
        print("Xác thực WebSocket thành công. Đã đăng ký:", ", ".join(symbols))
        print("Đang chờ dữ liệu (ngoài giờ giao dịch có thể không có tin; bấm Ctrl+C để dừng)...")
        await ws.send(build_subscribe_message(symbols))
        async for raw in ws:
            out.append(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
            if len(out) >= n:
                break
    return out
