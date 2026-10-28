"""Chạy NGUYÊN VĂN code mẫu WebSocket của NEO (thư viện websocket-client) để đối chiếu.

Dùng khi scripts/explore_channels.py không kết nối được: nếu cả code mẫu của NEO cũng lỗi thì vấn đề nằm ở
địa chỉ/máy chủ/IP, không phải ở code dự án.
Cài thêm: uv pip install websocket-client
Chạy:     python scripts/neo_sample_ws.py            (thử ws://)
          python scripts/neo_sample_ws.py --wss      (thử wss://)
Token lấy bằng đăng nhập của dự án, không in ra. Tự dừng sau 30 giây.
"""
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import websocket  # thư viện websocket-client, giống code mẫu NEO

from neo_api.auth import TokenManager
from neo_api.config import get_settings

URL = "ws://neoapi.vpbanks.com.vn/stock-stream/broker"
if "--wss" in sys.argv:
    URL = URL.replace("ws://", "wss://", 1)

token = TokenManager(get_settings()).get()
count = {"n": 0}


def on_open(ws):
    print("Đã mở kết nối, gửi token...")
    ws.send(json.dumps({"action": "auth", "data": token}))


def on_message(ws, message):
    data = json.loads(message)
    if data.get("type") == "auth":
        print("Phản hồi xác thực:", {k: v for k, v in data.items() if k != "data"})
        if data.get("status") == "success":
            ws.send(json.dumps({"type": "sub", "channel": "stockInfo", "listId": ["VCB", "HPG"]}))
            print("Đã đăng ký stockInfo VCB, HPG")
        return
    count["n"] += 1
    print("Data:", str(data)[:300])
    if count["n"] >= 3:
        ws.close()


def on_error(ws, error):
    print(f"Lỗi: {type(error).__name__}: {error}")


def on_close(ws, code, msg):
    print(f"Đã đóng kết nối (mã {code})")


print("Thử kết nối:", URL)
ws = websocket.WebSocketApp(URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
threading.Timer(30, ws.close).start()
ws.run_forever()
