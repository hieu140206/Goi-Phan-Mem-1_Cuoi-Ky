"""Ngày đặc biệt (mục B2): ngày đáo hạn phái sinh, cơ cấu ETF, review chỉ số, chốt quyền, công bố kết quả kinh doanh...

Không viết cứng ngày nào trong mã: danh sách nằm ở data/special_days.csv (cột date, type, note; date dạng YYYY-MM-DD). Riêng ngày đáo
hạn phái sinh là THỨ NĂM THỨ BA của tháng nên tính bằng code (derivative_expiry_dates) và có thể ghi sẵn vào tệp bằng
scripts/make_special_days.py; các loại khác để trống cho sinh viên tự điền. Hàm đó chưa biết ngày nghỉ lễ: nếu thứ Năm thứ ba trùng ngày
nghỉ thì ngày đáo hạn thật có thể dời, cần kiểm tra thủ công.

Ngày đặc biệt vẫn được tính chỉ số và cảnh báo như bình thường, nhưng được gắn cờ và (config.toml, special_days.exclude_from_baseline = true)
KHÔNG được dùng làm mốc so sánh nền cho các ngày khác, vì thanh khoản hôm đó khác thường.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pandas as pd

from model_config import section

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)
DAY_TYPES = ("derivative_expiry", "etf_rebalance", "index_review", "ex_rights", "earnings", "market_holiday", "other")
TYPE_VI = {"derivative_expiry": "đáo hạn phái sinh", "etf_rebalance": "cơ cấu ETF", "index_review": "review chỉ số",
           "ex_rights": "chốt quyền", "earnings": "công bố kết quả kinh doanh", "market_holiday": "ngày nghỉ giao dịch",
           "other": "khác"}
COLUMNS = ["date", "type", "note"]
EXPIRY_NOTE = "Thứ Năm thứ ba của tháng (tính bằng code); nếu trùng ngày nghỉ lễ thì ngày đáo hạn thật có thể dời, cần kiểm tra"


def special_days_path() -> Path:
    p = Path(section("special_days")["path"])
    return p if p.is_absolute() else ROOT / p


def exclude_from_baseline() -> bool:
    return bool(section("special_days")["exclude_from_baseline"])


def _empty() -> pd.DataFrame:
    return pd.DataFrame({"date": pd.Series(dtype=object), "type": pd.Series(dtype=object), "note": pd.Series(dtype=object)})


def third_thursday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(3 - first.weekday()) % 7 + 14)        # thứ Năm có weekday() = 3


def derivative_expiry_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """Các thứ Năm thứ ba của tháng nằm trong [start, end]."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        d = third_thursday(y, m)
        if start <= d <= end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def load_special_days(path: str | Path | None = None) -> pd.DataFrame:
    """Đọc tệp. Thiếu tệp hoặc tệp rỗng: bảng rỗng. Dòng sai ngày hoặc sai loại bị bỏ kèm cảnh báo (không đoán)."""
    p = Path(path) if path else special_days_path()
    if not p.exists():
        return _empty()
    try:
        raw = pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("")
    except pd.errors.EmptyDataError:
        return _empty()
    if not {"date", "type"} <= set(raw.columns):
        log.warning("%s thiếu cột date hoặc type, bỏ qua cả tệp.", p.name)
        return _empty()
    rows = []
    for i, r in raw.iterrows():
        d = pd.to_datetime(str(r["date"]).strip(), format="%Y-%m-%d", errors="coerce")
        t = str(r["type"]).strip()
        if pd.isna(d):
            log.warning("%s dòng %d: ngày '%s' không đúng dạng YYYY-MM-DD, bỏ qua.", p.name, i + 2, r["date"])
        elif t not in DAY_TYPES:
            log.warning("%s dòng %d: loại '%s' không thuộc %s, bỏ qua.", p.name, i + 2, t, ", ".join(DAY_TYPES))
        else:
            rows.append((d.date(), t, str(r["note"]) if "note" in raw.columns else ""))
    if not rows:
        return _empty()
    return pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(["date", "type"]).sort_values(["date", "type"]).reset_index(drop=True)


def special_day_map(days: pd.DataFrame) -> dict[dt.date, str]:
    """{ngày: các loại, nối bằng dấu phẩy}."""
    if days is None or days.empty:
        return {}
    return {d: ",".join(g["type"]) for d, g in days.groupby("date")}


def describe(types: str) -> str:
    """'derivative_expiry,earnings' -> 'đáo hạn phái sinh, công bố kết quả kinh doanh' (để hiện trên giao diện)."""
    return ", ".join(TYPE_VI.get(t, t) for t in str(types).split(",") if t)


def is_market_holiday(day: dt.date, path: str | Path | None = None) -> bool:
    """True nếu `day` được ghi là ngày nghỉ giao dịch (type market_holiday) trong tệp ngày đặc biệt. Chỉ dựa vào tệp do sinh viên điền,
    KHÔNG tự đoán lịch nghỉ lễ. Ngày nghỉ không có phiên nào để phân tích nên không ảnh hưởng mốc nền; chỉ dùng để giao diện giải thích vì sao không có dữ liệu."""
    days = load_special_days(path)
    return bool(((days["date"] == day) & (days["type"] == "market_holiday")).any()) if not days.empty else False


def market_holiday_dates(path: str | Path | None = None) -> list[dt.date]:
    """Các ngày ghi là ngày nghỉ giao dịch (type market_holiday) trong tệp, tăng dần. Chỉ lấy từ tệp, không tự đoán lịch nghỉ lễ."""
    days = load_special_days(path)
    return sorted(days.loc[days["type"] == "market_holiday", "date"]) if not days.empty else []


def no_data_message(trade_day: dt.date, shown_day: dt.date, days_with_data: set | list, path: str | Path | None = None) -> str:
    """Câu thông báo khi ngày đang xem khác ngày giao dịch hiện tại. Nếu ngày hiện tại chưa có dữ liệu và được ghi là ngày nghỉ giao dịch thì
    nói rõ lý do (sàn không giao dịch nên bảng giá không nhấp nháy), không thì chỉ nói chưa có dữ liệu. Không tự đoán ngày nghỉ."""
    if trade_day not in set(days_with_data):
        if is_market_holiday(trade_day, path):
            return (f"Hôm nay ({trade_day:%d/%m/%Y}) là ngày nghỉ giao dịch nên sàn không có giao dịch và không có dữ liệu mới; bảng giá vì vậy "
                    f"không nhấp nháy như mọi ngày. Đang hiển thị phiên {shown_day:%d/%m/%Y} đã ghi.")
        return f"Chưa có dữ liệu phiên {trade_day:%d/%m/%Y}. Đang hiển thị phiên {shown_day:%d/%m/%Y} đã ghi."
    return f"Đang xem phiên {shown_day:%d/%m/%Y} đã ghi, không phải phiên hiện tại."


def add_expiry_dates(path: str | Path, start: dt.date, end: dt.date) -> int:
    """Ghi thêm ngày đáo hạn phái sinh còn thiếu vào tệp (tạo tệp nếu chưa có). KHÔNG xóa hay sửa dòng nào đang có (kể cả dòng
    sinh viên tự điền). Trả về số dòng đã thêm."""
    p = Path(path)
    have = load_special_days(p) if p.exists() else _empty()
    present = {d for d, t in zip(have["date"], have["type"]) if t == "derivative_expiry"}
    new = [d for d in derivative_expiry_dates(start, end) if d not in present]
    if not new:
        return 0
    add = pd.DataFrame({"date": [d.isoformat() for d in new], "type": "derivative_expiry", "note": EXPIRY_NOTE})
    if p.exists() and p.stat().st_size > 0:
        existing = pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("")
        out = pd.concat([existing, add], ignore_index=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        out = add
    out.sort_values(["date", "type"]).to_csv(p, index=False, encoding="utf-8")
    return len(new)
