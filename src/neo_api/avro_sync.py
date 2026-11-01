"""Giải mã tin WebSocket của NEO bằng schema Avro do máy chủ gửi (bước "sync"). CHỈ ĐỌC.

Cơ chế (rút ra từ việc ĐỌC mã nguồn gói NeoInvestSDK 0.2.5, chưa kiểm chứng trên máy chủ thật của bạn):
  1. Sau khi kết nối (và xác thực), gửi chữ {"type": "sync", "data": "<sha1 của schema đã lưu, hoặc chuỗi rỗng>"}.
  2. Máy chủ trả một tin nhị phân có byte đầu = 101. Phần còn lại hoặc là b"\\x00" (schema của bạn đã mới nhất)
     hoặc là base64(zlib(JSON)) với JSON = {"<id>": <schema Avro>, ...}.
  3. Mỗi tin dữ liệu sau đó: byte đầu = id schema, phần còn lại = bản ghi Avro mã hóa theo schema đó.
  4. SDK ánh xạ id -> kênh: 1 marketData, 2 marketInfo, 3 stockInfo, 10 marketVolume, 23 fuTopNPrice, 26 marketSession.
     Khớp với dữ liệu thật của dự án: byte đầu của stockInfo = 3, marketInfo = 2, marketVolume = 10, marketSession = 26.
Kênh marketData (symbol, sequenceMsg, matchedPrice, tradingVolume, timestamp, lastColor) là từng lần khớp có số thứ tự và giờ.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zlib

SYNC_ID = 101
SYNC_OK = b"\x00"
CHANNEL_BY_ID = {1: "marketData", 2: "marketInfo", 3: "stockInfo", 10: "marketVolume",
                 23: "fuTopNPrice", 26: "marketSession"}


def build_sync_message(schema_hash: str = "") -> str:
    return json.dumps({"type": "sync", "data": schema_hash})


def schema_hash(payload: bytes) -> str:
    return hashlib.sha1(payload).hexdigest()


def is_sync_frame(frame: bytes | str) -> bool:
    return isinstance(frame, (bytes, bytearray)) and len(frame) >= 1 and frame[0] == SYNC_ID


def parse_schema_payload(payload: bytes) -> dict[int, dict]:
    """payload = phần sau byte đầu của tin sync. Trả {id: schema JSON}. Trả {} nếu là tin "đã mới nhất"."""
    if payload == SYNC_OK:
        return {}
    raw = zlib.decompress(base64.b64decode(payload))
    return {int(k): v for k, v in json.loads(raw.decode("utf-8")).items()}


class AvroDecoder:
    """Giữ schema đã biên dịch rồi giải mã tin dữ liệu. Cần thư viện fastavro (pip install fastavro)."""

    def __init__(self, schemas: dict[int, dict] | None = None) -> None:
        import fastavro  # noqa: PLC0415 - chỉ cần khi dùng đến

        self._fa = fastavro
        self.raw: dict[int, dict] = {}
        self.parsed: dict[int, object] = {}
        for sid, sch in (schemas or {}).items():
            self.add(sid, sch)

    def add(self, schema_id: int, schema: dict) -> None:
        self.raw[schema_id] = schema
        self.parsed[schema_id] = self._fa.parse_schema(schema)

    def decode(self, frame: bytes) -> tuple[int, str | None, dict]:
        """Trả (id schema, tên kênh, bản ghi). Lỗi nếu id chưa có schema."""
        sid, body = frame[0], frame[1:]
        if sid not in self.parsed:
            raise KeyError(f"chưa có schema cho id {sid}")
        rec = self._fa.schemaless_reader(io.BytesIO(body), self.parsed[sid])
        return sid, CHANNEL_BY_ID.get(sid), rec
