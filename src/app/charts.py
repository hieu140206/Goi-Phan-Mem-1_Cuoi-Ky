"""Biểu đồ dùng chung giữa các trang (Radar, Chi tiết mã)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from theme import base_layout, is_dark, palette, vn


def intraday_caption(sym: str, day, one: pd.DataFrame) -> str:
    """Một câu tóm tắt phiên của một mã: spread, độ sâu trung vị và số đợt cảnh báo."""
    flagged = one[one["is_alert"]]
    n_flag = len(flagged)
    return (f"{sym}, phiên {day:%d/%m/%Y}: spread trung vị {vn(one['rel_spread_bps'].median(), 1)} bps, "
            f"độ sâu trung vị {vn(one['depth_value'].median() / 1e6, 0)} triệu đ, "
            + (f"{int(flagged['alert_start'].sum())} đợt cảnh báo ({n_flag} lần chụp)." if n_flag
               else "không bị cảnh báo lần nào."))


def intraday_figure(one: pd.DataFrame, height: int = 600) -> go.Figure:
    """Spread, độ sâu và LRS trong một phiên của một mã; mỗi đợt cảnh báo là một dải tô đỏ nhạt.

    `one`: các lần chụp của MỘT mã trong MỘT phiên, đã qua phân tích (cột rel_spread_bps, depth_value, lrs,
    lrs_watch, lrs_high, is_alert)."""
    p = palette()                                        # màu theo chủ đề sáng/tối của phiên đang vẽ
    BORDER, GRID, HUE, INK, MUTED, NEG, WARN = (p[k] for k in ("BORDER", "GRID", "HUE", "INK", "MUTED", "NEG", "WARN"))
    depth_fill = "rgba(232,234,237,0.08)" if is_dark() else "rgba(10,10,10,0.06)"
    one = one.sort_values("ts").copy()
    one["x"] = one["ts"].dt.tz_localize(None)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.36, 0.32, 0.32],
                        subplot_titles=("Spread tương đối (bps)", "Độ sâu 3 mức giá (triệu đồng)",
                                        "Điểm rủi ro thanh khoản LRS"))
    fig.add_trace(go.Scatter(x=one["x"], y=one["rel_spread_bps"], mode="lines", line=dict(color=HUE, width=2),
                             name="Spread", showlegend=False,
                             hovertemplate="%{x|%H:%M}  %{y:.1f} bps<extra></extra>"), 1, 1)
    fig.add_trace(go.Scatter(x=one["x"], y=one["depth_value"] / 1e6, mode="lines", fill="tozeroy",
                             line=dict(color=INK, width=1.5), fillcolor=depth_fill, name="Độ sâu",
                             showlegend=False, hovertemplate="%{x|%H:%M}  %{y:,.0f} triệu đ<extra></extra>"), 2, 1)
    fig.add_trace(go.Scatter(x=one["x"], y=one["lrs"], mode="lines", line=dict(color=INK, width=1.5), name="LRS",
                             showlegend=False, hovertemplate="%{x|%H:%M}  LRS %{y:.2f}<extra></extra>"), 3, 1)
    # Ngưỡng thay đổi theo thời gian vì mỗi lần chụp chỉ dùng dữ liệu trước nó, nên vẽ thành đường bậc thang.
    for col, color, label, ypos in (("lrs_watch", WARN, "Chú ý (phân vị 95%)", "bottom"),
                                    ("lrs_high", NEG, "Cao (phân vị 99%)", "top")):
        line = one[["x", col]].dropna()
        if line.empty:
            continue
        fig.add_trace(go.Scatter(x=line["x"], y=line[col], mode="lines", line=dict(color=color, width=1, dash="dash",
                                 shape="hv"), name=label, showlegend=False,
                                 hovertemplate=f"{label.split(' (')[0]} %{{y:.2f}}<extra></extra>"), 3, 1)
        fig.add_annotation(x=line["x"].iloc[-1], y=line[col].iloc[-1], text=label, showarrow=False, row=3, col=1,
                           xanchor="right", yanchor=ypos, font=dict(size=11, color=color))
    # Mỗi đợt cảnh báo là một dải tô đỏ nhạt (thay cho chấm đỏ từng phút, vốn dày đặc khi đợt kéo dài).
    runs = (one["is_alert"] != one["is_alert"].shift()).cumsum()
    for _, g in one[one["is_alert"]].groupby(runs[one["is_alert"]]):
        fig.add_vrect(x0=g["x"].iloc[0] - pd.Timedelta(seconds=30), x1=g["x"].iloc[-1] + pd.Timedelta(seconds=30),
                      fillcolor=NEG, opacity=0.12, line_width=0, layer="below", row="all", col=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=[11.5, 13], pattern="hour")], showgrid=False, tickformat="%H:%M",
                     showline=True, linecolor=BORDER, tickfont=dict(color=MUTED))
    # fixedrange: lăn chuột chỉ phóng to trục thời gian, trục dọc giữ nguyên nên không giá trị nào bị khuất.
    fig.update_yaxes(gridcolor=GRID, zeroline=False, nticks=5, tickfont=dict(color=MUTED), automargin=True, fixedrange=True,
                     ticks="", ticklabelstandoff=6)
    for a in fig.layout.annotations[:3]:
        a.update(font=dict(size=12, color=MUTED), x=0, xanchor="left")
    base_layout(fig, height)
    fig.update_layout(hovermode="x unified", margin=dict(l=48, r=8, t=28, b=4))
    return fig
