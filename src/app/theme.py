"""Giao diện dùng chung cho các trang: màu, CSS, dấu hiệu sản phẩm và vài hàm định dạng.
Nội dung tách nguyên văn từ app.py cũ (chỉ đổi chỗ, không đổi giao diện)."""
from __future__ import annotations

import base64

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Màu: chữ và khung không màu; một màu xanh cho dữ liệu chính; đỏ/hổ phách chỉ cho trạng thái.
# Hai bảng màu: SÁNG (mặc định, "sổ cái không màu") và TỐI (người xem chọn ở menu Settings của Streamlit, xem .streamlit/config.toml).
# INK, MUTED, BORDER... là tên màu đọc LÚC DÙNG theo chủ đề của phiên đang chạy (hàm __getattr__ cuối tệp), nên
# `from theme import INK` ở đầu mỗi trang luôn ra màu đúng chủ đề. Mô-đun nạp một lần (ví dụ charts.py) vẫn giữ màu của lần nạp đầu.
LIGHT = {
    "INK": "#0a0a0a", "MUTED": "#6b6b6b", "FAINT": "#9a9a9a", "BORDER": "#e3e6ea", "GRID": "#eceef1",
    "HUE": "#1d5fbf", "NEG": "#c4242a", "WARN": "#92400e", "POS": "#2e7d32", "FLAT": "#b5bac1",
    "PANEL": "#ffffff", "HEAD": "#f7f8fa", "HOVER": "#f7f9fc", "NOTICE": "#334155", "ON_INK": "#ffffff",
    "CE": "#7c3aed", "FLR": "#1d5fbf", "REF": "#b7791f",                       # trần, sàn, tham chiếu của bảng giá
    "F_UP": "#d7f0da", "F_DN": "#fbdcdd", "F_RF": "#fdeccb", "F_CE": "#e9ddfb", "F_FL": "#d9e7fb",   # nền ô vừa đổi
    "SPARK": "rgba(29,95,191,0.07)",
    "BADGE": {"ok": "#e8f0fb", "warn": "#fdf0e3", "neg": "#fbe9ea", "muted": "#eef0f2", "faint": "#f3f5f8"},
}
DARK = {
    "INK": "#e8eaed", "MUTED": "#9aa3ad", "FAINT": "#6b7480", "BORDER": "#2b313b", "GRID": "#222831",
    "HUE": "#6ea8fe", "NEG": "#f2777a", "WARN": "#e0a15a", "POS": "#4cc16a", "FLAT": "#6b7480",
    "PANEL": "#171b22", "HEAD": "#1d222b", "HOVER": "#1f252e", "NOTICE": "#c3cad3", "ON_INK": "#0f1217",
    "CE": "#b794f6", "FLR": "#6ea8fe", "REF": "#e0b35a",
    "F_UP": "#1f4d2c", "F_DN": "#5a2327", "F_RF": "#58451b", "F_CE": "#40306a", "F_FL": "#1f3a66",
    "SPARK": "rgba(110,168,254,0.10)",
    "BADGE": {"ok": "#1b2a44", "warn": "#3a2c18", "neg": "#3d1f22", "muted": "#222831", "faint": "#1d222a"},
}
FONT = "Geist, Inter, system-ui, sans-serif"


def is_dark() -> bool:
    """Phiên hiện tại đang dùng chủ đề tối? Đọc từ Streamlit; ngoài lúc chạy trang (kiểm thử) hoặc lỗi thì coi là sáng."""
    try:
        return st.context.theme.type == "dark"
    except Exception:  # noqa: BLE001
        return False


def palette() -> dict:
    return DARK if is_dark() else LIGHT


def badge_style(kind: str) -> str:
    """CSS cho một ô bảng (Styler) dạng huy hiệu: ok, warn, neg, muted hoặc faint. Bảng của Streamlit chỉ nhận màu chữ, màu nền và độ đậm."""
    p = palette()
    fg = {"ok": p["HUE"], "warn": p["WARN"], "neg": p["NEG"], "muted": p["MUTED"], "faint": p["MUTED"]}[kind]
    bg = p["BADGE"][kind]
    return f"color: {fg}; background-color: {bg}; font-weight: 600"


def arrow_pct(digits: int = 1):
    """Hàm định dạng ô phần trăm có mũi tên: ▲ tăng, ▼ giảm (đọc được cả khi không phân biệt màu), số kiểu Việt; 0 không có mũi tên."""
    def fmt(v: float) -> str:
        body = f"{abs(v):.{digits}f}".replace(".", ",") + "%"
        return ("▲ " if v > 0 else "▼ " if v < 0 else "") + body
    return fmt


def sign_color(v: float) -> str:
    p = palette()
    return f"color: {p['POS']}" if v > 0 else f"color: {p['NEG']}" if v < 0 else ""


def how_to_read(*lines: str) -> None:
    """Mục thu gọn 'Cách đọc trang này' ở đầu trang: vài gạch đầu dòng ngắn cho người mới. Mặc định đóng để không chiếm chỗ."""
    with st.expander("Cách đọc trang này", icon=":material/help:"):
        st.markdown("\n".join(f"- {line}" for line in lines))


def inject_css() -> None:
    p = palette()
    INK, MUTED, BORDER, HUE, NEG, PANEL = p["INK"], p["MUTED"], p["BORDER"], p["HUE"], p["NEG"], p["PANEL"]
    st.html(
        f"""
    <style>
    .stApp {{ font-variant-numeric: tabular-nums; }}
    [data-testid="stMainBlockContainer"] {{ max-width: 1360px; padding-left: 40px; padding-right: 40px; }}

    /* Ô nền trắng: mọi container có key bắt đầu bằng "panel" */
    [class*="st-key-panel"] {{ background: {PANEL}; }}

    /* Thương hiệu ở đầu thanh bên */
    .brand {{ display: flex; align-items: center; gap: 10px; margin: 0 0 4px 0; }}
    .brand img {{ flex: none; display: block; }}
    .brand b {{ font-size: 15px; font-weight: 600; letter-spacing: -0.01em; display: block; line-height: 1.2; }}
    .brand span {{ font-size: 12px; color: {MUTED}; display: block; line-height: 1.4; }}
    .grp {{ font-size: 12px; color: {MUTED}; margin: 18px 0 2px 0; }}

    /* Đầu trang */
    .finding {{ font-size: 15px; line-height: 1.5; color: {INK}; margin: 2px 0 0 0; max-width: 78ch; }}
    .finding .neg {{ color: {NEG}; font-weight: 500; }}
    .stamp {{ font-size: 12px; color: {MUTED}; text-align: right; line-height: 1.5; }}
    /* Thông báo trạng thái dữ liệu: nền trắng trung tính, vạch xanh bên trái (không dùng nền vàng/be). */
    .notice {{ font-size: 12.5px; color: {p["NOTICE"]}; background: {PANEL}; border: 1px solid {BORDER};
              border-left: 3px solid {HUE}; border-radius: 6px; padding: 8px 12px; line-height: 1.5; }}
    .notice b {{ color: {INK}; }}

    /* Dải chỉ số: một khung chia bằng vạch mảnh */
    .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); background: {PANEL};
            border: 1px solid {BORDER}; border-radius: 8px; }}
    .kpi {{ padding: 16px 20px 18px; border-left: 1px solid {BORDER}; min-width: 0; }}
    .kpi:first-child {{ border-left: none; }}
    .kpi .l {{ font-size: 13px; color: {MUTED}; line-height: 1.4; }}
    .kpi .v {{ font-size: 24px; font-weight: 500; letter-spacing: -0.01em; line-height: 1.25; margin-top: 6px;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .kpi.lead .v {{ font-size: 30px; font-weight: 600; }}
    .kpi .v small {{ font-size: 14px; font-weight: 400; color: {MUTED}; margin-left: 3px; }}
    .kpi .s {{ font-size: 12px; color: {MUTED}; margin-top: 2px; }}
    .kpi .s .neg {{ color: {NEG}; }}
    @media (max-width: 900px) {{
      .kpis {{ grid-template-columns: repeat(2, 1fr); }}
      .kpi:nth-child(3) {{ border-left: none; }}
      .kpi:nth-child(n+3) {{ border-top: 1px solid {BORDER}; }}
      .kpi.lead .v {{ font-size: 26px; }}
    }}

    /* Thanh bên đủ rộng để ô khoảng ngày không bị cắt chữ (Streamlit đặt width trực tiếp nên cần !important). */
    [data-testid="stSidebar"][data-collapsed="false"] {{ width: 316px !important; min-width: 316px !important; }}
    @media (max-width: 900px) {{
      [data-testid="stMainBlockContainer"] {{ padding-left: 20px; padding-right: 20px; }}
    }}
    .note {{ color: {MUTED}; font-size: 12px; line-height: 1.6; max-width: 100ch; }}
    </style>
    """
    )


# Dấu hiệu sản phẩm: sổ lệnh 3 mức hai bên, khoảng trống ở giữa là spread. Màu nền và thanh theo chủ đề (BRAND_MARK đọc lúc dùng).
def brand_mark() -> str:
    p = palette()
    bar = p["ON_INK"]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 30 30">'
           f'<rect width="30" height="30" rx="7" fill="{p["INK"]}"/>'
           f'<rect x="5" y="8" width="8" height="3" rx="1" fill="{bar}"/><rect x="7" y="13.5" width="6" height="3" rx="1" fill="{bar}" opacity=".75"/>'
           f'<rect x="9" y="19" width="4" height="3" rx="1" fill="{bar}" opacity=".5"/><rect x="17" y="8" width="8" height="3" rx="1" fill="{bar}"/>'
           f'<rect x="17" y="13.5" width="6" height="3" rx="1" fill="{bar}" opacity=".75"/><rect x="17" y="19" width="4" height="3" rx="1" fill="{bar}" opacity=".5"/></svg>')
    return '<img alt="" width="30" height="30" src="data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode() + '">'


def vn(x: float, d: int = 0) -> str:
    """Định dạng số kiểu Việt Nam: dấu chấm ngăn nghìn, dấu phẩy thập phân."""
    if pd.isna(x):
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def group(label: str) -> None:
    st.html(f'<div class="grp">{label}</div>')


# Cấu hình chung cho mọi biểu đồ Plotly: lăn chuột để phóng to/thu nhỏ, kéo để dịch, nhấp đúp để về như cũ.
# Thanh công cụ chỉ hiện khi rê chuột vào biểu đồ, bỏ các nút chọn vùng không dùng tới.
CHART_CONFIG = {
    "scrollZoom": True,
    "doubleClick": "reset",
    "displaylogo": False,
    "displayModeBar": "hover",
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines", "hoverClosestCartesian",
                               "hoverCompareCartesian"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


def hide_lunch(fig: go.Figure) -> None:
    """Ẩn khoảng nghỉ trưa 11:30-13:00 trên trục thời gian (chỉ đổi cách vẽ, không đổi số).
    Trục x phải là giờ Việt Nam KHÔNG kèm múi giờ (dùng naive_vn). Chỗ dữ liệu đứt vẫn để đứt, không nối thẳng."""
    fig.update_xaxes(rangebreaks=[dict(bounds=[11.5, 13], pattern="hour")])


def naive_vn(ts: pd.Series) -> pd.Series:
    """Giờ Việt Nam bỏ phần múi giờ, để Plotly vẽ đúng giờ địa phương và ẩn được giờ nghỉ trưa."""
    return ts.dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None) if ts.dt.tz is not None else ts


def base_layout(fig: go.Figure, height: int) -> None:
    p = palette()
    fig.update_layout(
        height=height, margin=dict(l=4, r=8, t=28, b=4),
        plot_bgcolor=p["PANEL"], paper_bgcolor=p["PANEL"],
        dragmode="pan",  # kéo chuột để dịch biểu đồ (đi cùng phóng to bằng con lăn)
        font=dict(family=FONT, color=p["INK"], size=12),
        hoverlabel=dict(bgcolor=p["PANEL"], bordercolor=p["BORDER"], font=dict(family=FONT, color=p["INK"], size=12)),
    )


def __getattr__(name: str):
    """`from theme import INK, BORDER, ...` -> màu theo chủ đề của phiên đang chạy; BRAND_MARK dựng theo chủ đề."""
    if name == "BRAND_MARK":
        return brand_mark()
    p = palette()
    if name in p and name != "BADGE":
        return p[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
