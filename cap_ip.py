import requests

username = input("Tài khoản: ")
password = input("Mật khẩu: ")

resp = requests.post(
    "https://external.vpbanks.com.vn/auth/token",
    json={
        "username": username,
        "password": password,
    },
)

resp.raise_for_status()
token = resp.json()["data"]["access_token"]
print("Đăng nhập thành công")

import websocket
import json

def on_open(ws):
  # Step 1: Authenticate
  ws.send(json.dumps({"action": "auth", "data": "<jwt_token>"}))

def on_message(ws, message):
  data = json.loads(message)
  if data.get("type") == "auth" and data.get("status") == "success":
      print("Authenticated!")
      # Step 2: Subscribe to channels
      ws.send(json.dumps({
          "type": "sub",
          "channel": "stockInfo",
          "listId": ["VPB", "HPG"]
      }))
  else:
      print("Data:", data)

def on_error(ws, error):
  print(f"Error: {error}")

ws = websocket.WebSocketApp(
  "ws://neoapi.vpbanks.com.vn/stock-stream/broker",
  on_open=on_open,
  on_message=on_message,
  on_error=on_error,
)
ws.run_forever()
