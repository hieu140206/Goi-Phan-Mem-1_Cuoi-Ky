"""Hộp thoại chi tiết một mã ở trang Tổng quan: giá hiện tại và biểu đồ nến OHLC kèm khối lượng.

Nguồn nến: SSI (nguồn phụ, chỉ đọc, có đến 1 năm nến ngày và nến trong phiên của MỌI mã), có nhãn "SSI" trên giao diện. Giá SSI của ngày cũ có thể
đã điều chỉnh cổ tức nên chỉ để HIỂN THỊ, không đưa vào tính điểm. Không gọi được SSI thì dùng nến ngày NEO đã ghi (bảng board) và nói rõ.
Hàm `candle_figure` không đọc dữ liệu, kiểm thử được.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from board import fmt_px, fmt_qty, _vn
from data.candles import neo_daily_candles
from data.ssi import SsiClient, fetch_ohlc
from theme import CHART_CONFIG, INK, MUTED, NEG, POS, base_layout

# nhãn hiển thị -> (khung nến SSI, số ngày lịch lấy về)
FRAMES = {"Ngày": ("1d", 365), "1 giờ": ("1h", 45), "15 phút": ("15m", 14), "5 phút": ("5m", 7)}
SSI_NOTE = ("SSI là nguồn phụ. Giá ngày cũ có thể đã điều chỉnh cổ tức nên có thể lệch bảng giá; "
            "biểu đồ chỉ để xem, không dùng để tính điểm.")


def missing_weekdays(ts: pd.Series) -> list[str]:
    """Các ngày thứ Hai đến thứ Sáu nằm giữa dữ liệu mà không có nến nào (ngày lễ, ngày nghỉ): để ẩn khỏi trục thời gian."""
    if ts.empty:
        return []
    have = set(ts.dt.normalize())
    days = pd.date_range(ts.min().normalize(), ts.max().normalize(), freq="D")
    return [d.strftime("%Y-%m-%d") for d in days if d.weekday() < 5 and d not in have]


def candle_figure(df: pd.DataFrame, intraday: bool, height: int = 460) -> go.Figure:
    """Nến OHLC (giá nghìn đồng) và cột khối lượng bên dưới. Xanh lá là đóng cửa không thấp hơn mở cửa, đỏ là thấp hơn.
    Ẩn cuối tuần, ngày không có nến, và với nến trong phiên thì ẩn cả giờ nghỉ trưa và ngoài giờ giao dịch (chỉ đổi cách vẽ, không đổi số)."""
    d = df.copy()
    for c in ("open", "high", "low", "close"):
        d[c] = d[c] / 1000.0
    up = d["close"] >= d["open"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.76, 0.24], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=d["ts"], open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="Giá",
        increasing=dict(line=dict(color=POS), fillcolor=POS), decreasing=dict(line=dict(color=NEG), fillcolor=NEG),
        showlegend=False), row=1, col=1)
    fig.add_trace(go.Bar(x=d["ts"], y=d["volume"], marker_color=[POS if u else NEG for u in up], opacity=0.55, name="Khối lượng",
                         showlegend=False, hovertemplate="KL %{y:,.0f}<extra></extra>"), row=2, col=1)
    breaks = [dict(bounds=["sat", "mon"])]
    gone = missing_weekdays(d["ts"])
    if gone:
        breaks.append(dict(values=gone, dvalue=86_400_000))
    if intraday:
        breaks += [dict(bounds=[11.5, 13], pattern="hour"), dict(bounds=[15, 9], pattern="hour")]
    fig.update_xaxes(rangebreaks=breaks, rangeslider_visible=False, showgrid=False, linecolor="#e3e6ea")
    fig.update_yaxes(gridcolor="#eceef1", zeroline=False, hoverformat=".2f")
    fig.update_yaxes(title_text="nghìn đồng", row=1, col=1)
    base_layout(fig, height)
    fig.update_layout(bargap=0.15, hovermode="x unified")
    if len(d) > 90:   # mở đầu chỉ hiện đoạn cuối cho dễ nhìn; vẫn kéo và lăn chuột để xem phần còn lại
        fig.update_xaxes(range=[d["ts"].iloc[-90], d["ts"].iloc[-1] + (d["ts"].iloc[-1] - d["ts"].iloc[-2]) * 2])
    return fig


@st.cache_data(ttl=900, show_spinner=False)
def _load_ssi(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Gọi SSI (chỉ đọc). Lỗi thì ném ra để Streamlit KHÔNG nhớ kết quả lỗi."""
    today = dt.date.today()
    return fetch_ohlc(SsiClient(), symbol, (today - dt.timedelta(days=days)).strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d"), timeframe)


def get_candles(symbol: str, label: str, db_path: Path) -> tuple[pd.DataFrame, str, str]:
    """(nến, nguồn, ghi chú). Nguồn "SSI" hoặc "NEO". Thiếu dữ liệu thì bảng rỗng kèm ghi chú lý do, không đoán."""
    tf, days = FRAMES[label]
    try:
        df = _load_ssi(symbol, tf, days)
    except Exception as exc:          # noqa: BLE001  (mạng, thiếu khóa, giới hạn tần suất: không để làm hỏng trang)
        df, reason = pd.DataFrame(), type(exc).__name__
    else:
        reason = ""
    if not df.empty:
        return df, "SSI", SSI_NOTE
    if tf != "1d":
        return df, "", f"Không lấy được nến {label} của {symbol} từ SSI" + (f" ({reason})." if reason else ".")
    neo = neo_daily_candles(db_path, symbol)
    if neo.empty:
        return neo, "", f"Không có nến ngày của {symbol} (SSI không trả dữ liệu và NEO chưa ghi mã này)."
    partial = int(neo["partial"].sum())
    note = ("Không lấy được nến từ SSI" + (f" ({reason})" if reason else "") + f", đang dùng nến ngày NEO đã ghi ({len(neo)} ngày). "
            + (f"{partial} ngày bộ ghi dừng trước 15:00 nên giá đóng cửa có thể chưa gồm phiên ATC." if partial else ""))
    return neo, "NEO", note.strip()


def _stat(label: str, value: str, cls: str = "") -> str:
    return f'<div class="sd-stat"><div class="sd-l">{label}</div><div class="sd-v {cls}">{value}</div></div>'


def _head_html(symbol: str, row: pd.Series | None, group_label: str) -> str:
    if row is None:
        return f'<div class="sd-head"><b>{html.escape(symbol)}</b></div>'
    sign = "up" if row["change"] > 0 else "dn" if row["change"] < 0 else ""
    arrow = " ▲" if sign == "up" else " ▼" if sign == "dn" else ""
    chg = "–" if pd.isna(row["change"]) else (("+" if row["change"] > 0 else "") + _vn(row["change"] / 1000, 2)
                                              + " (" + ("+" if row["pct"] > 0 else "") + _vn(row["pct"], 2) + "%)" + arrow)
    net = row["foreign_net"] / 1e9 if not pd.isna(row["foreign_net"]) else float("nan")
    net_txt = "–" if pd.isna(net) else ("+" if net > 0 else "") + _vn(net, 1) + " tỷ"
    return (
        f'<div class="sd-head"><span class="sd-sym">{html.escape(symbol)}</span><span class="sd-grp">{html.escape(group_label)}</span>'
        f'<span class="sd-px {sign}">{fmt_px(row["last_px"])}</span><span class="sd-chg {sign}">{chg}</span></div>'
        '<div class="sd-stats">' + _stat("Tham chiếu", fmt_px(row["ref"])) + _stat("Trần", fmt_px(row["ceil"])) + _stat("Sàn", fmt_px(row["floor"]))
        + _stat("Tổng KL", fmt_qty(row["total_vol"])) + _stat("Nước ngoài ròng", net_txt, "up" if net > 0 else "dn" if net < 0 else "") + "</div>")


SD_CSS = f"""<style>
.sd-head {{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }}
.sd-sym {{ font-size:22px; font-weight:700; color:{INK}; }} .sd-grp {{ font-size:12px; color:{MUTED}; }}
.sd-px {{ font-size:22px; font-weight:700; font-variant-numeric:tabular-nums; }} .sd-chg {{ font-size:14px; font-variant-numeric:tabular-nums; }}
.sd-head .up, .sd-stat .up {{ color:{POS}; }} .sd-head .dn, .sd-stat .dn {{ color:{NEG}; }}
.sd-stats {{ display:flex; gap:22px; flex-wrap:wrap; margin:10px 0 4px; }}
.sd-l {{ font-size:11.5px; color:{MUTED}; }} .sd-v {{ font-size:14px; font-weight:600; font-variant-numeric:tabular-nums; }}
</style>"""


def _body(symbol: str, row: pd.Series | None, group_label: str, db_path: Path, stock_page: str | None) -> None:
    st.html(SD_CSS + _head_html(symbol, row, group_label))
    label = st.segmented_control("Khung nến", list(FRAMES), default="Ngày", key=f"sd_frame_{symbol}", label_visibility="collapsed") or "Ngày"
    with st.spinner("Đang tải nến…"):
        df, source, note = get_candles(symbol, label, db_path)
    if df.empty:
        st.info(note)
    else:
        st.plotly_chart(candle_figure(df, intraday=FRAMES[label][0] != "1d"), config=CHART_CONFIG, width="stretch",
                        key=f"sd_chart_{symbol}_{label}")
        st.caption(f"Nguồn: {source}. {note}")
    if stock_page:
        st.html(f'<a href="{stock_page}?ma={quote(symbol)}" target="_self">Mở hồ sơ thanh khoản đầy đủ của {html.escape(symbol)}</a>')


def open_symbol_dialog(symbol: str, row: pd.Series | None, group_label: str, db_path: Path, stock_page: str | None = None) -> None:
    """Mở hộp thoại cho `symbol`. row là dòng của bảng giá (board_view) nếu tìm thấy; stock_page là đường dẫn trang Chi tiết mã (chỉ mã VN30)."""
    st.dialog(f"Chi tiết {symbol}", width="large")(_body)(symbol, row, group_label, db_path, stock_page)
