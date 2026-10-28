"""Giải mã tin WebSocket dạng nhị phân của NEO (chưa có tài liệu chính thức, suy ra từ tin thật ngày 27/10/2026).

Tài liệu NEO mô tả tin dạng JSON, nhưng máy chủ thật gửi tin nhị phân gọn, khớp với cách mã hóa Apache Avro:
  - số nguyên: varint dạng zigzag;
  - mở đầu mỗi tin là một số nguyên = chỉ số loại tin trong một "union" (quan sát: 13 = marketSession);
  - mỗi trường là union [null, string]: số 0 = rỗng, số 1 = có giá trị, theo sau là độ dài và chuỗi UTF-8.
Ví dụ tin thật: b"\\x1a\\x02\\x08HOSE..." -> loại 13, trường đầu tiên "HOSE".

CHƯA BIẾT (cần schema của NEO hoặc thêm tin thật trong giờ giao dịch):
  - tên của từng trường (hiện chỉ biết thứ tự);
  - có trường nào kiểu số (long/double) không. Gặp kiểu khác chuỗi, hàm sẽ báo lỗi thay vì đoán sai.
"""
from __future__ import annotations

from dataclasses import dataclass

# Loại tin đã xác nhận bằng dữ liệu thật.
KNOWN_TYPES: dict[int, str] = {13: "marketSession"}

# Tên trường theo thứ tự bảng trong tài liệu NEO 6.2 (Market Stream).
# marketSession: ĐÃ XÁC NHẬN thứ tự bằng tin thật 27/10/2026 (khớp ví dụ HOSE, HOSE, C, K, 15:00:00 của tài liệu).
# Các kênh còn lại: theo tài liệu, CHƯA xác nhận bằng tin thật (cần dữ liệu trong giờ giao dịch).
CHANNEL_FIELDS: dict[str, list[str]] = {
    "marketSession": ["marketCode", "rawMarketCode", "marketStatus", "rawMarketStatus", "time"],
    "marketVolume": ["indexCode", "indexValue", "indexTime", "totalVolume", "volume"],
    "marketInfo": ["dateString", "indexCode", "indexValue", "indexChange", "indexTime", "indexPercentChange",
                   "totalVolume", "totalValue", "marketStatus", "advances", "declines", "noChange",
                   "numberOfCe", "numberOfFl", "marketCode", "oddLotTotalVolume", "oddLotTotalValue"],
    "stockInfo": ["symbol", "ceilingPrice", "floorPrice", "refPrice",
                  "bidPrice1", "bidVol1", "bidPrice2", "bidVol2", "bidPrice3", "bidVol3",
                  "askPrice1", "askVol1", "askPrice2", "askVol2", "askPrice3", "askVol3",
                  "closePrice", "closeVol", "priceChange", "percentPriceChange",
                  "openPrice", "highPrice", "lowPrice", "averagePrice",
                  "totalTradingVolume", "totalTradingValue", "totalBidQTTY", "totalAskQTTY",
                  "foreignBuyVolume", "foreignSellVolume", "foreignBuyValue", "foreignSellValue",
                  "foreignNetValue", "foreignRemain", "foreignRoom", "breakEvenPoint"],
}

# Ý nghĩa marketStatus theo tài liệu. Chỉ phiên LO (khớp lệnh liên tục) dùng để tính spread/độ sâu.
MARKET_STATUS = {"PRE": "Trước giờ giao dịch", "ATO": "Mở cửa (ATO)", "LO": "Khớp lệnh liên tục",
                 "ATC": "Đóng cửa (ATC)", "PLO": "Sau giờ (PLO)", "PT": "Thỏa thuận", "C": "Đóng cửa"}


class DecodeError(ValueError):
    """Tin không đúng cấu trúc đã biết."""


@dataclass
class RawMessage:
    type_index: int
    fields: list[str | None]

    @property
    def type_name(self) -> str:
        return KNOWN_TYPES.get(self.type_index, f"loại {self.type_index}")


def to_bytes(raw: str | bytes) -> bytes:
    """Tin có thể đến dưới dạng bytes (khung nhị phân) hoặc str (khung văn bản chứa ký tự điều khiển)."""
    if isinstance(raw, bytes):
        return raw
    try:
        return raw.encode("latin-1")
    except UnicodeEncodeError:
        return raw.encode("utf-8")


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        if pos >= len(buf):
            raise DecodeError("Hết dữ liệu giữa chừng khi đọc số")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            break
        if shift > 63:
            raise DecodeError("Số quá dài")
    return (result >> 1) ^ -(result & 1), pos


def looks_binary(raw: str | bytes) -> bool:
    """Phân biệt tin nhị phân với JSON: JSON bắt đầu bằng { hoặc [."""
    b = to_bytes(raw).lstrip()
    return bool(b) and b[:1] not in (b"{", b"[")


def decode(raw: str | bytes) -> RawMessage:
    buf = to_bytes(raw)
    type_index, pos = _read_varint(buf, 0)
    fields: list[str | None] = []
    while pos < len(buf):
        branch, pos = _read_varint(buf, pos)
        if branch == 0:
            fields.append(None)
            continue
        if branch != 1:
            raise DecodeError(f"Trường thứ {len(fields) + 1} có nhánh union {branch}, chưa biết cách đọc")
        length, pos = _read_varint(buf, pos)
        if length < 0 or pos + length > len(buf):
            raise DecodeError(f"Độ dài chuỗi không hợp lệ ở trường thứ {len(fields) + 1}")
        try:
            fields.append(buf[pos:pos + length].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise DecodeError(f"Trường thứ {len(fields) + 1} không phải chuỗi UTF-8 (có thể là số)") from exc
        pos += length
    return RawMessage(type_index, fields)


def to_dict(msg: RawMessage, channel: str | None = None) -> dict[str, str | None]:
    """Gắn tên trường theo thứ tự tài liệu. Trường dư (nếu NEO thêm trường mới) đặt tên field_<số>."""
    channel = channel or msg.type_name
    names = list(CHANNEL_FIELDS.get(channel, []))
    names += [f"field_{i + 1}" for i in range(len(names), len(msg.fields))]
    return dict(zip(names, msg.fields))


def market_session(msg: RawMessage) -> dict[str, str | None]:
    if msg.type_index != 13:
        raise DecodeError(f"Không phải marketSession (loại {msg.type_index})")
    return to_dict(msg, "marketSession")
