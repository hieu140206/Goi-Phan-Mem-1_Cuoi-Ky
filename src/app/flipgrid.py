"""Bản đồ nhiệt thẻ lật (dạng treemap): mỗi mã VN30 một ô, màu theo điểm rủi ro thanh khoản (LRS) tại một thời điểm,
diện tích ô theo độ sâu sổ lệnh trung vị của mã trong phiên (cố định khi phát lại để các ô không nhảy chỗ).

Dùng khi "Phát lại phiên" của Radar: sang lần chụp kế tiếp, ô nào đổi điểm thì lật sang mặt mới, ô không đổi đứng yên
(việc vẽ và lật nằm ở flipgrid_component.py; file này chỉ tính dữ liệu).

Dữ liệu luôn lấy đúng từ cột `lrs` và `lrs_tier` của kết quả phân tích; mã không có lần chụp ở thời điểm đó,
hoặc chưa đủ lịch sử để tính LRS, thì hiện "–" (viền nét đứt), không đoán và không điền.

Chỉ phụ thuộc pandas (không import streamlit) để kiểm thử được; phần vẽ lên trang nằm ở flipgrid_component.py.
"""
from __future__ import annotations

import pandas as pd

DASH = "–"
TIER_CLASS = {"Cao": "hi", "Chú ý": "md", "": "ok"}


# Thang màu nền theo điểm LRS (liên tục). Các mốc lấy từ phân phối LRS của toàn bộ dữ liệu đã ghi
# (28/10-13/11/2026, 50.973 điểm): phân vị 5% = -0,9; trung vị = 0; phân vị 95% = 1,3 (mức "Chú ý"); phân vị 99% = 2,3 (mức "Cao").
# Chỉ để tô màu cho dễ nhìn; mức Chú ý/Cao vẫn do ngưỡng của Radar quyết định (viền đậm), không do thang này.
SCALE = [(-0.9, (207, 224, 245)), (0.0, (238, 241, 244)), (1.3, (251, 227, 184)), (2.3, (240, 160, 154))]


def lrs_color(v: float) -> str:
    """Màu nền (#rrggbb) cho điểm LRS: xanh nhạt = dễ giao dịch hơn thường lệ, xám = bình thường, cam rồi đỏ = khó hơn."""
    if v <= SCALE[0][0]:
        r, g, b = SCALE[0][1]
    elif v >= SCALE[-1][0]:
        r, g, b = SCALE[-1][1]
    else:
        for (x0, c0), (x1, c1) in zip(SCALE, SCALE[1:]):
            if x0 <= v <= x1:
                t = (v - x0) / (x1 - x0)
                r, g, b = (round(a + (b_ - a) * t) for a, b_ in zip(c0, c1))
                break
    return f"#{r:02x}{g:02x}{b:02x}"


def _fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def grid_state(analyzed: pd.DataFrame, symbols: list[str], ts: pd.Timestamp | None) -> pd.DataFrame:
    """Trạng thái từng mã tại ĐÚNG lần chụp `ts`. Cột: symbol, lrs, tier ('' | 'Chú ý' | 'Cao'), cls, text, bg (màu nền).
    Mã không có dòng ở `ts` hoặc LRS thiếu: cls = 'na', text = '–'."""
    rows: dict[str, tuple[float, str]] = {}
    if ts is not None and not analyzed.empty:
        at = analyzed[analyzed["ts"] == ts].drop_duplicates("symbol", keep="last").set_index("symbol")
        for s in symbols:
            if s in at.index and pd.notna(at.at[s, "lrs"]):
                rows[s] = (float(at.at[s, "lrs"]), str(at.at[s, "lrs_tier"] or ""))
    out = []
    for s in symbols:
        if s in rows:
            lrs, tier = rows[s]
            out.append((s, lrs, tier, TIER_CLASS.get(tier, "ok"), _fmt(lrs), lrs_color(lrs)))
        else:
            out.append((s, float("nan"), "", "na", DASH, "#ffffff"))
    return pd.DataFrame(out, columns=["symbol", "lrs", "tier", "cls", "text", "bg"])


def tile_weights(analyzed: pd.DataFrame, symbols: list[str], day) -> dict[str, float]:
    """Trọng số diện tích mỗi ô = độ sâu 3 mức giá (depth_value) TRUNG VỊ của mã trong cả phiên `day`.
    Dùng cả phiên để bố cục đứng yên suốt lúc phát lại (chỉ để chia diện tích, không phải chỉ số phân tích).
    Mã không có độ sâu trong phiên: nhận trọng số bằng nửa mã nhỏ nhất, vẫn hiện ô "–" nhỏ, không bịa số."""
    d = analyzed[analyzed["ts"].dt.date == day] if not analyzed.empty else analyzed
    med = d.groupby("symbol")["depth_value"].median() if not d.empty else pd.Series(dtype=float)
    w = {s: float(med[s]) for s in symbols if s in med.index and pd.notna(med[s]) and med[s] > 0}
    floor = 0.5 * min(w.values()) if w else 1.0
    return {s: w.get(s, floor) for s in symbols}


def treemap_layout(weights: dict[str, float], width: float = 100.0, height: float = 40.0) -> dict[str, tuple]:
    """Treemap kiểu "squarified" (Bruls, Huizing, van Wijk 2000): chia hình chữ nhật width x height thành các ô có diện
    tích tỷ lệ với trọng số, cố giữ ô gần vuông. Trả {mã: (x, y, w, h)}. Thứ tự ổn định (trọng số giảm dần, rồi theo mã)."""
    items = sorted(((k, v) for k, v in weights.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
    if not items:
        return {}
    scale = width * height / sum(v for _, v in items)
    queue = [(k, v * scale) for k, v in items]
    rects: dict[str, tuple] = {}

    def worst(row: list, side: float) -> float:
        s = sum(a for _, a in row)
        return max(side * side * max(a for _, a in row) / (s * s), s * s / (side * side * min(a for _, a in row)))

    x, y, w, h = 0.0, 0.0, width, height
    while queue:
        side = min(w, h)
        row, rest = [queue[0]], queue[1:]
        while rest and worst(row + [rest[0]], side) <= worst(row, side):
            row.append(rest[0])
            rest = rest[1:]
        s = sum(a for _, a in row)
        if w >= h:                       # xếp thành một cột bên trái, rộng s/h
            cw, yy = s / h, y
            for k, a in row:
                rects[k] = (x, yy, cw, a / cw)
                yy += a / cw
            x, w = x + cw, w - cw
        else:                            # xếp thành một hàng phía trên, cao s/w
            rh, xx = s / w, x
            for k, a in row:
                rects[k] = (xx, y, a / rh, rh)
                xx += a / rh
            y, h = y + rh, h - rh
        queue = rest
    return rects


def _size_class(w: float, h: float, width: float, height: float) -> str:
    frac = (w * h) / (width * height)
    return "xl" if frac > 0.09 else "lg" if frac > 0.04 else "md2" if frac > 0.018 else "sm"


def tiles_payload(cur: pd.DataFrame, layout: dict[str, tuple], width: float = 100.0, height: float = 46.0) -> list[dict]:
    """Dữ liệu từng ô gửi cho component JS: mã, chữ, lớp màu, nền, vị trí (% khung), cỡ chữ và chú thích khi rê chuột.
    Mã không có trong `layout` thì bỏ qua. JS tự so với trạng thái đang hiện để quyết định ô nào lật."""
    out = []
    for r in cur.itertuples(index=False):
        if r.symbol not in layout:
            continue
        x, y, w, h = layout[r.symbol]
        out.append({
            "sym": str(r.symbol), "text": r.text, "cls": r.cls, "bg": r.bg, "size": _size_class(w, h, width, height),
            "x": round(x / width * 100, 3), "y": round(y / height * 100, 3),
            "w": round(w / width * 100, 3), "h": round(h / height * 100, 3),
            "title": f"{r.symbol}: {'không có điểm' if r.cls == 'na' else 'LRS ' + r.text}",
        })
    return out
