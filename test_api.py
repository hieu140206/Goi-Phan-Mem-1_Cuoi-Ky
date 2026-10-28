"""File độc lập: đăng nhập NEO và lấy danh sách chỉ số (VN30, VNINDEX...) từ market/indexList.

Chỉ cần: pip install requests pandas
Chạy:    python scripts/get_indices.py
         python scripts/get_indices.py --exchange HOSE --csv chi_so.csv

Tài khoản/mật khẩu: đọc biến môi trường NEO_USERNAME, NEO_PASSWORD nếu có, không thì hỏi trên dòng lệnh
(mật khẩu không hiển thị). Token chỉ nằm trong bộ nhớ, không in ra, không lưu. Chỉ ĐỌC dữ liệu.
Không biết trước phản hồi có những cột nào nên script in đúng các cột NEO trả về.
"""
import argparse
import getpass
import os
import sys

import pandas as pd
import requests

AUTH_URL = "https://external.vpbanks.com.vn/auth/token"
BASE_URL = "https://neoapi.vpbanks.com.vn/neo-api"
HEADERS_EXTRA = {"x-device": "my-app", "x-devicetype": "chrome"}


def login() -> str:
    user = os.getenv("NEO_USERNAME") or input("Tài khoản NEO: ").strip()
    pwd = os.getenv("NEO_PASSWORD") or getpass.getpass("Mật khẩu (không hiển thị): ")
    resp = requests.post(AUTH_URL, json={"username": user, "password": pwd}, timeout=15)
    if not resp.ok:
        sys.exit(f"Đăng nhập thất bại (mã {resp.status_code}). Kiểm tra tài khoản, mật khẩu, IP đã đăng ký.")
    try:
        return resp.json()["data"]["access_token"]
    except (ValueError, KeyError, TypeError):
        sys.exit("Phản hồi đăng nhập không có data.access_token.")


def get_index_list(token: str, exchange: str = "ALL", page_size: int = 50) -> list:
    headers = {"Authorization": f"Bearer {token}", **HEADERS_EXTRA}
    items, page = [], 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/market/indexList",
            params={"exchangeCode": exchange, "pageNo": page, "pageSize": page_size},
            headers=headers, timeout=10,
        )
        if not resp.ok:
            sys.exit(f"Gọi indexList lỗi (mã {resp.status_code}).")
        body = resp.json()
        if body.get("status") != 1:
            sys.exit(f"NEO báo lỗi: {body.get('code')} {str(body.get('message'))[:100]}")
        data = body["data"]
        items.extend(data.get("content", []))
        if data.get("last", True) or page >= int(data.get("totalPages", 1)):
            return items
        page += 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Lấy danh sách chỉ số từ NEO API")
    ap.add_argument("--exchange", default="ALL", help="ALL, HOSE, HNX, UPCOM (mặc định ALL)")
    ap.add_argument("--csv", help="Lưu ra file CSV (tùy chọn)")
    args = ap.parse_args()

    df = pd.DataFrame(get_index_list(login(), args.exchange))
    if df.empty:
        sys.exit("NEO không trả chỉ số nào.")
    pd.set_option("display.width", 200, "display.max_columns", None)
    print(f"Có {len(df)} chỉ số. Các cột NEO trả về: {list(df.columns)}\n")
    print(df.to_string(index=False))
    if args.csv:
        df.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\nĐã lưu {args.csv}")


if __name__ == "__main__":
    main()