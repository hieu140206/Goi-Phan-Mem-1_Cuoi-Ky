"""Đọc config.toml: nơi DUY NHẤT chứa hằng số và ngưỡng của phần phân tích (Radar, Bộ lọc).

Dùng thư viện có sẵn của Python (tomllib, từ 3.11) nên không thêm phụ thuộc. Tệp mặc định là config.toml ở thư mục gốc dự án;
đặt biến môi trường NEO_MODEL_CONFIG để dùng tệp khác (ví dụ khi thử nghiệm). Thiếu tệp hoặc thiếu khóa thì báo lỗi rõ ràng,
không âm thầm dùng số khác: một con số ngưỡng bị đổi mà không ai biết là điều tệ nhất với một công cụ phân tích.
"""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config.toml"


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("NEO_MODEL_CONFIG") or DEFAULT_PATH)
    if not p.exists():
        raise FileNotFoundError(f"Không thấy tệp cấu hình {p}. Cần config.toml ở thư mục gốc dự án.")
    with p.open("rb") as fh:
        return tomllib.load(fh)


def section(name: str) -> dict:
    """Một nhóm tham số, ví dụ section("baseline")["max_sessions"]. Thiếu nhóm thì báo lỗi nêu tên nhóm."""
    cfg = load_config()
    if name not in cfg:
        raise KeyError(f"config.toml thiếu nhóm [{name}]")
    return cfg[name]
