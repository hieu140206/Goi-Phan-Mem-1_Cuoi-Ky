"""Client REST cho NEO API (chỉ ĐỌC dữ liệu thị trường; không có hàm đặt/sửa/hủy lệnh).

Địa chỉ gốc và header theo ví dụ trong tài liệu NEO:
  GET https://neoapi.vpbanks.com.vn/neo-api/market/indexList
  headers: Authorization: Bearer <token>, x-device, x-devicetype
Phản hồi bọc trong {"status": 1, "code": ..., "message": ..., "data": ...}; status khác 1 là lỗi.

Các endpoint 4.6 và 4.7 trả cùng bộ trường giá/sổ lệnh như kênh stockInfo (bidPrice1, askVol1...), nên dùng chung
bước làm sạch với dữ liệu WebSocket. bidPrice1/askPrice1 có thể là chữ ATO/ATC.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .auth import TokenManager
from .config import Settings, get_settings
from .rate_limiter import RateLimiter

log = logging.getLogger(__name__)

ENDPOINTS: dict[str, str] = {
    "index_list": "market/indexList",              # 4.1, đã chạy thật 27/10/2026
    "stock_detail": "stock/stockDetail",           # 4.6, theo tài liệu
    "stock_by_index": "stock/stockDetailByIndex",  # 4.7, đã chạy thật 27/10/2026 (30 mã VN30)
    "index_intraday": "market/intradayMarketIndex",  # 4.2, theo tài liệu: điểm hiện tại + chuỗi index[] trong ngày
    "index_detail": "market/marketIndexDetail",      # 4.3, theo tài liệu: điểm, tăng/giảm, số mã tăng/giảm
    "market_status": "market/marketStatus",          # 4.4, theo tài liệu: PRE, ATO, LO, ATC, PLO, C
    "stock_list": "stock/stockList",                 # 4.5, theo tài liệu: danh sách mã theo sàn (HOSE/HNX/UPCOM/FU/ALL)
    "fu_detail": "stock/fuStockDetail",              # 4.9, theo tài liệu: chi tiết hợp đồng tương lai (FUVN30)
}

# Mã lỗi NEO (tài liệu 7.2) hay gặp khi đọc dữ liệu.
ERROR_CODES: dict[str, str] = {
    "NEOINP000400": "Yêu cầu không hợp lệ", "NEOINP000401": "Chưa xác thực (token hết hạn?)",
    "NEOINP000403": "Bị từ chối truy cập (IP chưa đăng ký?)", "NEOINP000404": "Không tìm thấy dữ liệu",
    "NEOINP000500": "Lỗi máy chủ NEO", "NEOINP000501": "Đã xảy ra lỗi", "NEOINP000111": "Hết thời gian chờ",
    "NEOINP000003": "Lỗi kiểm tra dữ liệu", "NEOINP000004": "Không có bản ghi", "NEOINP000033": "Tham số sai định dạng",
}


class NeoApiError(RuntimeError):
    """Lỗi khi gọi NEO API (mạng, xác thực, giới hạn tần suất, dữ liệu sai định dạng)."""


class NeoClient:
    def __init__(self, settings: Settings | None = None, tokens: TokenManager | None = None) -> None:
        self.settings = settings or get_settings()
        self.tokens = tokens or TokenManager(self.settings)
        self._limiter = RateLimiter(max_calls=self.settings.max_rps, period=1.0)
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens.get()}",
            "x-device": self.settings.device,
            "x-devicetype": self.settings.device_type,
        }

    def get(self, path: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any:
        """Gọi GET và trả về phần `data` của phản hồi. Tự đăng nhập lại một lần nếu token bị từ chối (401)."""
        if not path:
            raise NeoApiError("Đường dẫn endpoint đang để trống. Điền trong ENDPOINTS (client.py).")
        url = f"{self.settings.base_url}/{path.lstrip('/')}"
        relogged = False
        for attempt in range(1, retries + 1):
            self._limiter.wait()
            try:
                resp = self._session.get(url, params=params, headers=self._headers(), timeout=10)
            except requests.RequestException as exc:
                log.warning("Lỗi mạng (lần %d/%d): %s", attempt, retries, type(exc).__name__)
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 429:  # quá giới hạn tần suất
                log.warning("Bị giới hạn tần suất (429), chờ rồi thử lại")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 401 and not relogged:
                log.warning("Token bị từ chối (401), đăng nhập lại một lần")
                self.tokens.invalidate()
                relogged = True
                continue
            if resp.status_code in (401, 403):
                raise NeoApiError(f"Xác thực thất bại ({resp.status_code}). Kiểm tra tài khoản và IP đã đăng ký.")
            if not resp.ok:
                raise NeoApiError(f"API trả lỗi {resp.status_code} tại {path}")
            return self._unwrap(resp, path)
        raise NeoApiError(f"Gọi {path} thất bại sau {retries} lần thử")

    @staticmethod
    def _unwrap(resp: requests.Response, path: str) -> Any:
        try:
            body = resp.json()
        except ValueError as exc:
            raise NeoApiError("Phản hồi không phải JSON hợp lệ") from exc
        if not isinstance(body, dict) or "data" not in body:
            raise NeoApiError(f"Phản hồi tại {path} không có trường data như tài liệu mô tả")
        if body.get("status") != 1:
            code = str(body.get("code"))
            if code == "NEOINP000004":  # "Không có bản ghi": không phải lỗi, chỉ là rỗng
                return []
            hint = ERROR_CODES.get(code, "")
            raise NeoApiError(f"NEO báo lỗi tại {path}: {code} {hint} {str(body.get('message'))[:100]}".strip())
        return body["data"]

    def _get_all_pages(self, path: str, params: dict[str, Any], page_size: int) -> list[dict]:
        """Duyệt hết các trang của phản hồi dạng {"content": [...], "last"/"totalPages": ...}."""
        items: list[dict] = []
        page = 1
        while True:
            data = self.get(path, {**params, "pageNo": page, "pageSize": page_size})
            if isinstance(data, list):  # phòng khi NEO trả thẳng danh sách
                return items + data
            content = data.get("content") or []
            items.extend(content)
            total_pages = int(data.get("totalPages") or 1)
            if data.get("last", True) or page >= total_pages or not content:
                return items
            page += 1

    def get_index_list(self, exchange: str = "ALL", page_size: int = 50) -> list[dict]:
        """4.1: danh sách chỉ số (chỉ có mã và tên, không có điểm)."""
        return self._get_all_pages(ENDPOINTS["index_list"], {"exchangeCode": exchange}, page_size)

    def get_stocks_by_index(self, index_code: str = "VN30", page_size: int = 1000) -> list[dict]:
        """4.7: chi tiết mọi cổ phiếu thuộc một chỉ số (giá, sổ lệnh 3 mức, khối ngoại...). VN30 -> 30 mã."""
        return self._get_all_pages(ENDPOINTS["stock_by_index"], {"indexCode": index_code}, page_size)

    def get_index_symbols(self, index_code: str = "VN30") -> list[str]:
        """Danh sách mã thành phần của chỉ số, lấy từ 4.7 (rổ thay đổi theo kỳ nên không gõ tay)."""
        return sorted({str(r["symbol"]).upper() for r in self.get_stocks_by_index(index_code) if r.get("symbol")})

    def get_stock_detail(self, symbols: list[str] | str, market: str = "ALL", stock_type: str = "ST",
                         page_size: int = 1000) -> list[dict]:
        """4.6: chi tiết các mã chỉ định (nhiều mã cách nhau bằng dấu phẩy)."""
        sym = symbols if isinstance(symbols, str) else ",".join(symbols)
        params = {"marketCode": market, "symbols": sym, "stockType": stock_type}
        return self._get_all_pages(ENDPOINTS["stock_detail"], params, page_size)

    def get_stock_list(self, market: str = "ALL", page_size: int = 1000) -> list[dict]:
        """4.5: danh sách mã (symbol, stockName, exchangeCode, stockType ST/CW/EF/BO/OF/MF...). Không có giá."""
        return self._get_all_pages(ENDPOINTS["stock_list"], {"marketCode": market}, page_size)

    def get_fu_detail(self, symbols: list[str] | str | None = None, stock_type: str = "FUVN30") -> list[dict]:
        """4.9: chi tiết hợp đồng tương lai (giá, sổ lệnh 3 mức, khối lượng mở, ngày đáo hạn...)."""
        params: dict[str, Any] = {"stockType": stock_type}
        if symbols:
            params["symbols"] = symbols if isinstance(symbols, str) else ",".join(symbols)
        return self._get_all_pages(ENDPOINTS["fu_detail"], params, 1000)

    def get_index_intraday(self, index_code: str = "VN30") -> dict:
        """4.2: chi tiết một chỉ số, kèm index[] = chuỗi điểm/khối lượng theo thời điểm trong ngày."""
        data = self.get(ENDPOINTS["index_intraday"], {"indexCode": index_code})
        return data[0] if isinstance(data, list) and data else (data or {})

    def get_index_detail(self, index_code: str = "ALL") -> list[dict]:
        """4.3: điểm hiện tại, thay đổi, số mã tăng/giảm/trần/sàn của các chỉ số."""
        data = self.get(ENDPOINTS["index_detail"], {"indexCode": index_code})
        return data if isinstance(data, list) else [data] if data else []

    def get_market_status(self, market: str = "ALL") -> list[dict]:
        """4.4: phiên hiện tại của từng sàn (marketStatus: PRE, ATO, LO, ATC, PLO, C)."""
        data = self.get(ENDPOINTS["market_status"], {"marketCode": market})
        return data if isinstance(data, list) else [data] if data else []
