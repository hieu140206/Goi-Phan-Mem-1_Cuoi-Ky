"""Giao diện dùng chung cho các trang: màu, CSS, dấu hiệu sản phẩm và vài hàm định dạng.
Nội dung tách nguyên văn từ app.py cũ (chỉ đổi chỗ, không đổi giao diện)."""
from __future__ import annotations

import base64

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Màu: chữ và khung không màu; một màu xanh cho dữ liệu chính; đỏ/hổ phách chỉ cho trạng thái.
INK, MUTED, FAINT = "#0a0a0a", "#6b6b6b", "#9a9a9a"
BORDER, GRID = "#e3e6ea", "#eceef1"
HUE, NEG, WARN = "#1d5fbf", "#c4242a", "#92400e"
POS = "#2e7d32"   # tăng (cùng màu với bảng giá và thẻ chỉ số ở trang Tổng quan)
# Huy hiệu trạng thái: chữ theo màu của bảng màu, nền là bản nhạt của chính màu đó (không thêm màu mới).
BADGE = {"ok": (HUE, "#e8f0fb"), "warn": (WARN, "#fdf0e3"), "neg": (NEG, "#fbe9ea"), "muted": (MUTED, "#eef0f2"), "faint": (MUTED, "#f3f5f8")}
FONT = "Geist, Inter, system-ui, sans-serif"


def badge_style(kind: str) -> str:
    """CSS cho một ô bảng (Styler) dạng huy hiệu: ok, warn, neg, muted hoặc faint. Bảng của Streamlit chỉ nhận màu chữ, màu nền và độ đậm."""
    fg, bg = BADGE[kind]
    return f"color: {fg}; background-color: {bg}; font-weight: 600"


def arrow_pct(digits: int = 1):
    """Hàm định dạng ô phần trăm có mũi tên: ▲ tăng, ▼ giảm (đọc được cả khi không phân biệt màu), số kiểu Việt; 0 không có mũi tên."""
    def fmt(v: float) -> str:
        body = f"{abs(v):.{digits}f}".replace(".", ",") + "%"
        return ("▲ " if v > 0 else "▼ " if v < 0 else "") + body
    return fmt


def sign_color(v: float) -> str:
    return f"color: {POS}" if v > 0 else f"color: {NEG}" if v < 0 else ""


def how_to_read(*lines: str) -> None:
    """Mục thu gọn 'Cách đọc trang này' ở đầu trang: vài gạch đầu dòng ngắn cho người mới. Mặc định đóng để không chiếm chỗ."""
    with st.expander("Cách đọc trang này", icon=":material/help:"):
        st.markdown("\n".join(f"- {line}" for line in lines))


def inject_css() -> None:
    st.html(
        f"""
    <style>
    .stApp {{ font-variant-numeric: tabular-nums; }}
    [data-testid="stMainBlockContainer"] {{ max-width: 1360px; padding-left: 40px; padding-right: 40px; }}

    /* Ô nền trắng: mọi container có key bắt đầu bằng "panel" */
    [class*="st-key-panel"] {{ background: #ffffff; }}

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
    .notice {{ font-size: 12.5px; color: #334155; background: #ffffff; border: 1px solid {BORDER};
              border-left: 3px solid {HUE}; border-radius: 6px; padding: 8px 12px; line-height: 1.5; }}
    .notice b {{ color: {INK}; }}

    /* Dải chỉ số: một khung chia bằng vạch mảnh */
    .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); background: #ffffff;
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


# Dấu hiệu sản phẩm: sổ lệnh 3 mức hai bên, khoảng trống ở giữa là spread.
_MARK_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 30 30">
  <rect width="30" height="30" rx="7" fill="{INK}"/>
  <rect x="5"  y="8"  width="8"  height="3" rx="1" fill="#ffffff"/>
  <rect x="7"  y="13.5" width="6" height="3" rx="1" fill="#ffffff" opacity=".75"/>
  <rect x="9"  y="19" width="4"  height="3" rx="1" fill="#ffffff" opacity=".5"/>
  <rect x="17" y="8"  width="8"  height="3" rx="1" fill="#ffffff"/>
  <rect x="17" y="13.5" width="6" height="3" rx="1" fill="#ffffff" opacity=".75"/>
  <rect x="17" y="19" width="4"  height="3" rx="1" fill="#ffffff" opacity=".5"/>
</svg>"""
BRAND_MARK = ('<img alt="" width="30" height="30" src="data:image/svg+xml;base64,'
              + base64.b64encode(_MARK_SVG.encode()).decode() + '">')


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
    fig.update_layout(
        height=height, margin=dict(l=4, r=8, t=28, b=4),
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
        dragmode="pan",  # kéo chuột để dịch biểu đồ (đi cùng phóng to bằng con lăn)
        font=dict(family=FONT, color=INK, size=12),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=BORDER, font=dict(family=FONT, color=INK, size=12)),
    )
