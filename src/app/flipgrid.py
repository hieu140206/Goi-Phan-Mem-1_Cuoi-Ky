"""Lưới thẻ lật: mỗi mã VN30 một thẻ, màu theo mức rủi ro thanh khoản (LRS) tại một thời điểm.

Dùng khi "Phát lại phiên" của Radar: sang lần chụp kế tiếp, thẻ nào đổi mức hoặc đổi điểm thì lật sang mặt mới
(mặt trước = trạng thái lần chụp trước, mặt sau = lần chụp hiện tại), thẻ không đổi đứng yên.

Dữ liệu luôn lấy đúng từ cột `lrs` và `lrs_tier` của kết quả phân tích; mã không có lần chụp ở thời điểm đó,
hoặc chưa đủ lịch sử để tính LRS, thì hiện "–" (xám), không đoán và không điền.

Chỉ phụ thuộc pandas (không import streamlit) để kiểm thử được; phần vẽ lên trang nằm ở radar.py.
"""
from __future__ import annotations

import html

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


def flipped(cur: pd.DataFrame, prev: pd.DataFrame | None) -> set[str]:
    """Các mã cần lật: mức hoặc điểm hiển thị khác lần chụp trước. Không có lần trước thì không mã nào lật."""
    if prev is None or prev.empty:
        return set()
    old = prev.set_index("symbol")
    return {r.symbol for r in cur.itertuples(index=False)
            if r.symbol in old.index and (r.cls != old.at[r.symbol, "cls"] or r.text != old.at[r.symbol, "text"])}


def flip_grid_html(cur: pd.DataFrame, prev: pd.DataFrame | None, step: int, link: str | None = "ma") -> str:
    """HTML của lưới. `step` đổi tên hiệu ứng lần lượt (flipA/flipB) để hiệu ứng chạy lại ở mỗi bước phát."""
    flips = flipped(cur, prev)
    old = prev.set_index("symbol") if prev is not None and not prev.empty else None
    tiles = []
    for r in cur.itertuples(index=False):
        sym = html.escape(str(r.symbol))
        back = f'<span class="s">{sym}</span><span class="v">{r.text}</span>'
        label = f"{r.symbol}: {'không có điểm' if r.cls == 'na' else 'LRS ' + r.text}"
        if r.symbol in flips and old is not None:
            o = old.loc[r.symbol]
            front = f'<span class="s">{sym}</span><span class="v">{o["text"]}</span>'
            inner = (f'<div class="in go{step % 2}"><div class="f {o["cls"]}" style="background:{o["bg"]}">{front}</div>'
                     f'<div class="b {r.cls}" style="background:{r.bg}">{back}</div></div>')
        else:
            inner = f'<div class="in"><div class="b {r.cls}" style="background:{r.bg}">{back}</div></div>'
        tile = f'<div class="tile" title="{html.escape(label)}">{inner}</div>'
        if link:
            tile = f'<a class="tl" href="{link}?ma={html.escape(str(r.symbol))}" target="_self">{tile}</a>'
        tiles.append(tile)
    return f'<div class="flipgrid">{"".join(tiles)}</div>'


def flip_css(ink: str, muted: str, neg: str, warn: str) -> str:
    """CSS của lưới. Mặt sau (b) là trạng thái hiện tại; mặt trước (f) chỉ hiện trong lúc lật."""
    return f"""<style>
.flipgrid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(82px, 1fr)); gap: 8px; }}
.flipgrid a.tl {{ text-decoration: none; color: inherit; display: block; }}
.flipgrid .tile {{ perspective: 600px; height: 58px; }}
.flipgrid .in {{ position: relative; width: 100%; height: 100%; transform-style: preserve-3d; }}
.flipgrid .f, .flipgrid .b {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
    justify-content: center; border-radius: 8px; backface-visibility: hidden; -webkit-backface-visibility: hidden;
    border: 1px solid #e3e6ea; line-height: 1.25; }}
.flipgrid .b {{ transform: rotateX(0deg); }}
.flipgrid .in.go0 .b, .flipgrid .in.go1 .b {{ transform: rotateX(180deg); }}
.flipgrid .in.go0 {{ animation: flipA .4s ease-in-out forwards; }}
.flipgrid .in.go1 {{ animation: flipB .4s ease-in-out forwards; }}
@keyframes flipA {{ from {{ transform: rotateX(0deg); }} to {{ transform: rotateX(180deg); }} }}
@keyframes flipB {{ from {{ transform: rotateX(0deg); }} to {{ transform: rotateX(180deg); }} }}
.flipgrid .s {{ font-size: 12px; font-weight: 700; color: {ink}; }}
.flipgrid .v {{ font-size: 12px; font-variant-numeric: tabular-nums; color: {muted}; }}
.flipgrid .md {{ border: 2px solid #d99a1c; }} .flipgrid .md .v {{ color: {warn}; font-weight: 600; }}
.flipgrid .hi {{ border: 2px solid {neg}; }} .flipgrid .hi .v {{ color: {neg}; font-weight: 700; }}
.flipgrid .na {{ border-style: dashed; }} .flipgrid .na .v {{ color: #b5bac1; }}
.flipgrid .tile:hover .b, .flipgrid .tile:hover .f {{ border-color: #9aa3ad; }}
@media (prefers-reduced-motion: reduce) {{ .flipgrid .in.go0, .flipgrid .in.go1 {{ animation-duration: .01s; }} }}
</style>"""
