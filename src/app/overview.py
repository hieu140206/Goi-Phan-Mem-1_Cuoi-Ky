"""Trang "Tổng quan thị trường": 4 chỉ số, bảng giá VN30, độ rộng, độ sâu và thanh khoản thị trường.

Dữ liệu đọc từ market.db và data/raw/<ngày>/market.json, không gọi NEO trực tiếp nên trang không giữ mật khẩu hay token.
Thẻ chỉ số cập nhật theo vòng hỏi nhanh của bộ ghi (mặc định 5 giây); sổ lệnh, bảng giá và độ sâu theo chu kỳ 1 phút.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402
import streamlit as st  # noqa: E402

from board import board_css, board_html  # noqa: E402
from data.market_board import GROUP_LABELS  # noqa: E402
from data.overview import (INDEX_NAMES, board_view, breadth_frame, day_range, futures_view, index_cards,  # noqa: E402
                           index_series, load_market_json, market_depth, market_depth_group, price_board,
                           status_label, trading_date, traded_value)
from data.schema import normalize_quotes  # noqa: E402
from data.storage import (data_days, latest_ts, load_board, load_depth_market, load_futures,  # noqa: E402
                          load_market_index, load_quotes)
from finance.liquidity import add_liquidity_metrics  # noqa: E402
from finance.sessions import filter_continuous  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402
from theme import BORDER, CHART_CONFIG, FAINT, GRID, HUE, INK, MUTED, NEG, base_layout, group, hide_lunch, naive_vn, vn  # noqa: E402

def with_gaps(df: pd.DataFrame, minutes: int = 10) -> pd.DataFrame:
    """Chèn dòng trống vào chỗ dữ liệu đứt quãng (nghỉ trưa) để biểu đồ không nối thẳng qua khoảng nghỉ."""
    if len(df) < 2:
        return df
    prev = df["ts"].shift(1)
    gap = (df["ts"] - prev) > pd.Timedelta(minutes=minutes)
    if not gap.any():
        return df
    breaks = pd.DataFrame({"ts": prev[gap] + pd.Timedelta(seconds=30)})
    return pd.concat([df, breaks]).sort_values("ts").reset_index(drop=True)


def finish(fig: go.Figure, height: int) -> None:
    base_layout(fig, height)
    fig.update_xaxes(automargin=True)
    # Nhãn trục không bị cắt ở lề trái; trục dọc cố định để lăn chuột chỉ phóng to theo thời gian, không cắt mất giá trị.
    fig.update_yaxes(automargin=True, fixedrange=True)


SORTS = {  # tên hiển thị -> (cột, tăng dần?)
    "Mã A đến Z": ("symbol", True),
    "Tổng KL giảm dần (cổ phiếu tích cực)": ("total_vol", False),
    "Giá trị giao dịch giảm dần": ("total_value", False),
    "% tăng nhiều nhất": ("pct", False),
    "% giảm nhiều nhất": ("pct", True),
    "Spread rộng nhất": ("spread_bps", False),
}
CARD_REFRESH_SECONDS = 5   # thẻ chỉ số hỏi lại cơ sở dữ liệu mỗi 5 giây ở chế độ Trực tiếp (bộ ghi hỏi 4.3 mỗi 5 giây)
BOARD_GROUPS = ["VN30", "HOSE", "HNX", "UPCOM", "ETF", "CW", "FU"]
DEPTH_SCOPES = ["VN30", "HOSE", "HNX", "UPCOM"]
MAX_BOARD_ROWS = 300       # bảng HTML quá dài thì trình duyệt chậm; tìm mã để xem mã ngoài 300 dòng đầu
POS = "#2e7d32"  # tăng; giảm dùng đỏ NEG của giao diện; đứng giá dùng xám
FLAT = "#b5bac1"

st.html(
    f"""<style>
.ov-head {{ margin: 4px 0 2px; }}
.ov-head h1 {{ font-size: 28px; font-weight: 700; letter-spacing: -0.01em; margin: 0; line-height: 1.25; }}
.ov-sub {{ font-size: 15px; color: #3d3d3d; margin: 6px 0 12px; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.chip {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border: 1px solid {BORDER};
        border-radius: 999px; background: #ffffff; font-size: 12.5px; font-weight: 500; color: {INK}; }}
.chip .dot {{ width: 7px; height: 7px; border-radius: 50%; background: {POS}; display: inline-block; }}
.chip .dot.off {{ background: {FAINT}; }}
.idx-cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 14px; }}
@media (max-width: 1100px) {{ .idx-cards {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 560px) {{ .idx-cards {{ grid-template-columns: 1fr; }} }}
.idx-card {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 12px; padding: 14px 16px 14px; min-width: 0; }}
.idx-card .top {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }}
.idx-card .name {{ font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #2a2a2a; }}
.idx-card .date {{ font-size: 12px; font-weight: 600; color: {MUTED}; }}
.idx-card .val {{ font-size: 28px; font-weight: 700; letter-spacing: -0.01em; line-height: 1.2; margin-top: 6px; }}
.idx-card .chg {{ font-size: 14px; font-weight: 600; margin-top: 2px; }}
.idx-card .spark {{ display: block; width: 100%; height: 56px; margin-top: 8px; }}
.idx-card .row {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 10px; font-size: 12px; color: {MUTED};
                 margin-top: 8px; line-height: 1.5; }}
.idx-card .row b {{ color: {INK}; font-weight: 600; }}
.idx-card .row.sep {{ border-top: 1px solid {GRID}; padding-top: 8px; }}
.idx-card .up {{ color: {POS}; font-weight: 600; }}
.idx-card .dn {{ color: {NEG}; font-weight: 600; }}
.idx-card .fl {{ color: #b7791f; font-weight: 600; }}
.idx-card .ce {{ color: #7c3aed; font-weight: 500; }}
.idx-card .fo {{ color: #1d5fbf; font-weight: 500; }}
.idx-card .status {{ color: {INK}; font-weight: 600; }}
</style>"""
)

settings = get_settings()
db_path = settings.db_path


@st.cache_data(show_spinner=False)
def load_quotes_clean(path: str, version: float) -> pd.DataFrame:
    """Sổ lệnh VN30 (đã làm sạch, chỉ phiên khớp lệnh liên tục). `version` là mtime của file."""
    quotes, _ = normalize_quotes(load_quotes(Path(path)))
    quotes, _ = filter_continuous(quotes)
    return add_liquidity_metrics(quotes)


@st.cache_data(show_spinner=False)
def load_idx_day(path: str, version: float, day_str: str) -> pd.DataFrame:
    return load_market_index(Path(path), day_str)


@st.cache_data(show_spinner=False)
def load_group(path: str, version: float, day_str: str, grp: str):
    """Bảng giá một nhóm trong một ngày -> (bảng hiển thị, thời điểm chụp)."""
    raw = load_board(Path(path), day_str, grp)
    return board_view(raw), (raw["ts"].max() if not raw.empty else None)


@st.cache_data(show_spinner=False)
def load_extras(path: str, version: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_depth_market(Path(path)), load_futures(Path(path))


try:
    version = db_path.stat().st_mtime
except OSError:
    version = 0.0
quotes = load_quotes_clean(str(db_path), version)
days = [pd.Timestamp(d).date() for d in data_days(db_path)]

if not days:
    st.title("🏛️ Tổng Quan Thị Trường", anchor=False)
    st.info("Chưa có dữ liệu thị trường. Chạy `python scripts/run_live.py` trong giờ giao dịch (hoặc "
            "`python scripts/record_rest.py`) để bộ ghi lưu dữ liệu từ NEO. Bật công tắc Trực tiếp thì trang tự hiện "
            "khi bộ ghi ghi xong phút đầu tiên.")
    st.stop()

with st.sidebar:
    group("Tổng quan")
    day = st.selectbox("Ngày giao dịch", sorted(days, reverse=True), format_func=lambda d: d.strftime("%d/%m/%Y"))

idx = load_idx_day(str(db_path), version, f"{day:%Y-%m-%d}")
market_json = load_market_json(ROOT / "data", day)
cards = index_cards(idx, day, market_json)
board = price_board(quotes, day)
depth_all, fut_all = load_extras(str(db_path), version)


# ---------- đầu trang ----------
def signed(x: float, d: int = 2, suffix: str = "") -> str:
    return "–" if pd.isna(x) else f"{'+' if x > 0 else ''}{vn(x, d)}{suffix}"


def tone(x: float) -> str:
    return "up" if x > 0 else "dn" if x < 0 else ""


def _chips_html(trade_day, data_ts, live: bool, fast: bool = False) -> str:
    """Chip đầu trang tính theo ĐỒNG HỒ THẬT mỗi lần vẽ: phiên hiện tại, giờ hiện tại, giờ của bản ghi cuối, kết nối."""
    now = pd.Timestamp.now(tz=TZ)
    out = [f'<span class="chip">📅 Phiên {trade_day:%d/%m/%Y}</span>', f'<span class="chip">⏱ {now:%H:%M:%S}</span>']
    if data_ts is not None:
        when = f"{data_ts:%H:%M}" + ("" if data_ts.date() == now.date() else f" ngày {data_ts:%d/%m}")
        out.append(f'<span class="chip">Dữ liệu lúc {when}</span>')
        if data_ts.date() == now.date():
            age = max((now - data_ts).total_seconds() / 60, 0)
            if age <= 5:
                ago = f"cách {age * 60:.0f} giây" if age < 1.5 else f"cách {age:.0f} phút"
                out.append(f'<span class="chip"><span class="dot"></span>Đang nhận dữ liệu · {ago}'
                           + (" · tự cập nhật" if live else "") + "</span>")
            else:
                out.append('<span class="chip"><span class="dot off"></span>Không có dữ liệu mới</span>')
    return '<div class="chips">' + "".join(out) + "</div>"


@st.fragment(run_every=1)
def render_chips(trade_day, day, live: bool) -> None:
    """Chạy lại mỗi giây chỉ riêng khối chip để đồng hồ chạy; không vẽ lại cả trang. Giờ "Dữ liệu lúc" đọc thẳng từ
    cơ sở dữ liệu mỗi lần vẽ nên đổi theo từng bản ghi mới của bộ ghi."""
    st.html(_chips_html(trade_day, latest_ts(db_path, f"{day:%Y-%m-%d}"), live))


trade_day = trading_date(pd.Timestamp.now(tz=TZ))
with st.container(horizontal=True, vertical_alignment="top", gap="medium"):
    with st.container(width="stretch"):
        st.html('<div class="ov-head"><h1>🏛️ Tổng Quan Thị Trường</h1></div>'
                '<div class="ov-sub">Toàn cảnh chứng khoán Việt Nam: chỉ số, bảng giá, độ sâu, độ rộng và thanh khoản. '
                'Dành cho nhà đầu tư cá nhân và chuyên viên phân tích muốn nắm nhanh trạng thái thị trường trong phiên.</div>')
        render_chips(trade_day, day, bool(st.session_state.get("live")))
    st.button("Làm mới", icon=":material/refresh:", key="ov_reload", width="content",
              help="Đọc lại cơ sở dữ liệu để lấy các bản ghi mới nhất.")
    st.page_link("screen_page.py", label="Lọc cổ phiếu VN30", icon=":material/filter_alt:")
if day != trade_day:
    msg = (f"Chưa có dữ liệu phiên {trade_day:%d/%m/%Y}. Đang hiển thị phiên {day:%d/%m/%Y} đã ghi." if trade_day not in days
           else f"Đang xem phiên {day:%d/%m/%Y} đã ghi, không phải phiên hiện tại.")
    st.html(f'<div class="notice" style="margin-top:10px">{msg}</div>')


# ---------- 4 thẻ chỉ số ----------
def sparkline(values: pd.Series, color: str) -> str:
    """Đường chỉ số trong ngày có phủ màu mờ phía dưới, nhúng dạng ảnh SVG (st.html lọc thẻ <svg> trực tiếp)."""
    v = pd.to_numeric(values, errors="coerce").dropna().to_numpy()
    if len(v) < 2:
        return ""
    if len(v) > 240:  # thưa bớt để ảnh gọn
        v = v[np.linspace(0, len(v) - 1, 240).astype(int)]
    lo, hi = float(v.min()), float(v.max())
    span = (hi - lo) or 1.0
    xy = [(i / (len(v) - 1) * 100, 34 - (x - lo) / span * 30) for i, x in enumerate(v)]
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in xy)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40" preserveAspectRatio="none">'
           f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity=".28"/>'
           f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
           f'<polygon points="0,40 {line} 100,40" fill="url(#g)"/>'
           f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>')
    return f'<img class="spark" alt="" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}">'


def card_html(r: pd.Series, idx: pd.DataFrame, day, market_json: dict) -> str:
    code = r["index_code"]
    chg = r["index_change"]
    color = POS if chg > 0 else NEG if chg < 0 else MUTED
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "■"
    series = index_series(idx, day, code, market_json)
    rng = day_range(series)
    low_high = (f'<div class="row"><span>Thấp–Cao <b>{vn(rng[0], 1)} – {vn(rng[1], 1)}</b></span></div>' if rng else "")
    vol = f"{vn(r['sum_volume'])} CP" if not pd.isna(r["sum_volume"]) else "–"
    val = f"{vn(r['sum_value'] / 1e9, 2)} tỷ" if not pd.isna(r["sum_value"]) else "–"
    adv, flat, dec = (vn(r[c]) for c in ("advances", "no_change", "declines"))
    ce = f' <span class="ce">({vn(r["ceilings"])})</span>' if not pd.isna(r["ceilings"]) else ""
    fo = f' <span class="fo">({vn(r["floors"])})</span>' if not pd.isna(r["floors"]) else ""
    return (f'<div class="idx-card"><div class="top"><span class="name">{INDEX_NAMES.get(code, code)}</span>'
            f'<span class="date">{day:%d/%m/%Y}</span></div>'
            f'<div class="val">{vn(r["index_value"], 2)}</div>'
            f'<div class="chg {tone(chg)}">{arrow} {signed(chg)} ({signed(r["pct_change"], 2, "%")})</div>'
            f'{sparkline(series["value"], color)}{low_high}'
            f'<div class="row sep"><span><b>{vol}</b></span><span><b>{val}</b></span>'
            f'<span class="status">{status_label(r["status"], r["ts"])}</span></div>'
            f'<div class="row"><span class="up">▲ {adv}{ce}</span><span class="fl">● {flat}</span>'
            f'<span class="dn">▼ {dec}{fo}</span></div></div>')


def _cards_block(day, market_json: dict, live: bool) -> None:
    """4 thẻ chỉ số. Ở chế độ Trực tiếp khối này tự chạy lại mỗi 5 giây và đọc lại chỉ số của ngày từ cơ sở dữ liệu;
    phần còn lại của trang chỉ chạy lại khi bộ ghi ghi thêm sổ lệnh/bảng giá (mỗi phút)."""
    idx_now = load_market_index(db_path, f"{day:%Y-%m-%d}") if live else idx
    cards_now = index_cards(idx_now, day, market_json)
    if cards_now.empty:
        st.caption("Chưa có dữ liệu chỉ số (NEO 4.3) cho ngày này. Bộ ghi bản mới lưu chỉ số liên tục; "
                   "các ngày ghi trước đó chỉ có chỉ số cuối ngày nếu bộ ghi đã chạy tới hết phiên.")
        return
    shown = list(cards_now["index_code"])
    missing = [INDEX_NAMES[c] for c in ("VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX") if c not in shown]
    st.html('<div class="idx-cards">' + "".join(card_html(r, idx_now, day, market_json) for _, r in cards_now.iterrows()) + "</div>")
    st.caption("Trong ngoặc: số mã trần (tím) và số mã sàn (xanh). Khối lượng và giá trị là lũy kế cả sàn/rổ trong ngày, "
               "do NEO tính; thường cao hơn tổng các mã trong bảng giá vài phần trăm (có thể do giao dịch thỏa thuận, chưa xác nhận).")
    if missing:
        st.caption("Chưa có dữ liệu: " + ", ".join(missing) + ".")


_live = bool(st.session_state.get("live"))
st.fragment(run_every=CARD_REFRESH_SECONDS if _live else None)(_cards_block)(day, market_json, _live)

# ---------- bảng giá ----------
st.html(board_css(BORDER, GRID, MUTED, INK, POS, NEG))
st.html("<style>.board .mat{margin-left:6px}</style>")
st.write("")
def _board_panel(day, live: bool) -> None:
    """Khung bảng giá. Ở chế độ Trực tiếp khối này tự chạy lại mỗi 5 giây và đọc thẳng bảng board (bộ ghi làm mới VN30 mỗi
    5 giây, các sàn khác mỗi phút); ô nào đổi so với lần cập nhật trước thì tô nền theo màu mức giá."""
    with st.container(border=True, key="panel_board"):
        st.subheader("Bảng giá", anchor=False)
        grp = st.segmented_control("Nhóm bảng giá", BOARD_GROUPS, default="VN30", key="board_grp",
                                   label_visibility="collapsed", format_func=lambda g: GROUP_LABELS[g]) or "VN30"
        day_str = f"{day:%Y-%m-%d}"
        view, snap_ts, kind = pd.DataFrame(), None, "stock"
        if grp == "FU":
            kind = "future"
            fut_now = load_futures(db_path) if live else fut_all
            fut_day = fut_now[fut_now["ts"].dt.date == day] if not fut_now.empty else fut_now
            vn30_row = cards[cards["index_code"] == "VN30"] if not cards.empty else cards
            view = futures_view(fut_day, float(vn30_row["index_value"].iloc[0]) if not vn30_row.empty else None)
            snap_ts = fut_day["ts"].max() if not fut_day.empty else None
        else:
            if live:
                raw = load_board(db_path, day_str, grp)
                view, snap_ts = board_view(raw), (raw["ts"].max() if not raw.empty else None)
            else:
                view, snap_ts = load_group(str(db_path), version, day_str, grp)
            if grp == "VN30" and view.empty and not board.empty:  # ngày ghi bằng bản cũ: dùng sổ lệnh VN30 trong quotes
                view = board
                snap_ts = quotes.loc[quotes["ts"].dt.date == day, "ts"].max()

        if view.empty:
            if grp == "VN30":
                st.caption("Chưa có sổ lệnh VN30 cho ngày này.")
            else:
                st.caption(f"Chưa có bảng giá {GROUP_LABELS[grp]} cho ngày này. Bộ ghi bản mới lưu bảng giá các sàn và phái sinh; "
                           "các ngày ghi trước đó chỉ có sổ lệnh VN30.")
            return
        # So với lần cập nhật trước để tô ô vừa đổi. Lần mở trang đầu tiên chưa có gì để so nên không tô.
        key = f"bd_{day_str}_{grp}"
        state = st.session_state.get(key)
        if state is None:
            state = {"ts": snap_ts, "cur": view, "prev": None}
        elif snap_ts != state["ts"]:
            state = {"ts": snap_ts, "cur": view, "prev": state["cur"]}
        st.session_state[key] = state

        shown_board = view
        if kind == "stock":
            f1, f2, _ = st.columns([2, 2, 5], gap="small", vertical_alignment="bottom")
            query = f1.text_input("Tìm mã", placeholder="Nhập mã tìm kiếm", key=f"board_q_{grp}").strip().upper()
            order = f2.selectbox("Sắp xếp", list(SORTS), index=0 if grp == "VN30" else 2, key=f"board_sort_{grp}")
            if query:
                shown_board = shown_board[shown_board["symbol"].str.contains(query, regex=False)]
            col, asc = SORTS[order]
            shown_board = shown_board.sort_values(col, ascending=asc, na_position="last")
        total = len(shown_board)
        flash_note = (" Ô tô nền là giá trị vừa đổi so với lần cập nhật trước: xanh lá nếu giá trên TC, đỏ nếu dưới TC, "
                      "vàng nếu bằng TC.")
        if kind == "future":
            st.caption(f"Lần chụp {snap_ts:%H:%M:%S}. Giá tính bằng điểm chỉ số. Basis = giá khớp trừ điểm VN30 (âm: hợp đồng "
                       "rẻ hơn chỉ số). KL mở (OI) là số hợp đồng đang mở." + flash_note)
        else:
            st.caption(f"Lần chụp {snap_ts:%H:%M:%S}. Giá tính bằng nghìn đồng, khối lượng bằng cổ phiếu. Màu chữ: tím là giá trần, "
                       "xanh dương là giá sàn, vàng là tham chiếu, xanh lá là tăng, đỏ là giảm." + flash_note
                       + (" VN30 làm mới mỗi 5 giây ở chế độ Trực tiếp." if grp == "VN30" else
                          " Bảng giá các sàn là ảnh chụp mới nhất của ngày, cập nhật mỗi phút."))
        if shown_board.empty:
            st.caption("Không có mã nào khớp.")
        else:
            if total > MAX_BOARD_ROWS:
                st.caption(f"Hiển thị {MAX_BOARD_ROWS}/{total} mã theo thứ tự sắp xếp; gõ mã vào ô tìm kiếm để xem mã khác.")
            # Chỉ mã VN30 có hồ sơ (sổ lệnh theo phút); các sàn khác chưa có nên không gắn liên kết.
            st.html(board_html(shown_board.head(MAX_BOARD_ROWS), kind, state["prev"], link="ma" if grp == "VN30" else None))
            if grp == "VN30":
                st.caption("Bấm vào mã để mở hồ sơ chi tiết của mã đó.")


st.fragment(run_every=CARD_REFRESH_SECONDS if _live else None)(_board_panel)(day, _live)

# ---------- độ sâu và độ rộng ----------
c1, c2 = st.columns(2, gap="medium")
with c2, st.container(border=True, key="panel_breadth"):
    st.subheader("Độ rộng thị trường", anchor=False)
    b = breadth_frame(cards)
    if b.empty:
        st.caption("Chưa có dữ liệu độ rộng.")
    else:
        st.caption("Tỷ lệ số mã tăng, đứng giá, giảm của từng chỉ số (NEO 4.3).")
        names = [INDEX_NAMES.get(c, c) for c in b["index_code"]]
        fig = go.Figure()
        for col, label, color in (("adv_pct", "Tăng", POS), ("flat_pct", "Đứng giá", FLAT), ("dec_pct", "Giảm", NEG)):
            fig.add_bar(y=names, x=b[col], name=label, orientation="h", marker_color=color,
                        customdata=b[{"adv_pct": "advances", "flat_pct": "no_change", "dec_pct": "declines"}[col]],
                        hovertemplate="%{y}: %{customdata:.0f} mã (%{x:.0f}%)<extra>" + label + "</extra>")
        fig.update_layout(barmode="stack", legend=dict(orientation="h", y=1.12, x=0, traceorder="normal"))
        fig.update_xaxes(range=[0, 100], ticksuffix="%", gridcolor=GRID, zeroline=False)
        fig.update_yaxes(autorange="reversed", automargin=True)
        finish(fig, 240)
        st.plotly_chart(fig, config=CHART_CONFIG, theme=None, key="ov_breadth")
        ad = b.set_index("index_code")
        parts = []
        for code in ("VNINDEX", "HNXINDEX", "UPCOMINDEX"):
            if code in ad.index and not pd.isna(ad.loc[code, "adv_dec_ratio"]):
                parts.append(f"{INDEX_NAMES[code]}: {vn(ad.loc[code, 'adv_dec_ratio'], 2)}")
        if parts:
            st.caption("Tỷ lệ tăng/giảm (số mã tăng chia số mã giảm): " + " · ".join(parts)
                       + ". Trên 1 nghĩa là nhiều mã tăng hơn giảm.")
        if "VNINDEX" in ad.index:
            st.caption(f"VN-Index: {vn(ad.loc['VNINDEX', 'ceilings'])} mã trần, {vn(ad.loc['VNINDEX', 'floors'])} mã sàn.")

with c1, st.container(border=True, key="panel_depth"):
    scope = st.segmented_control("Phạm vi độ sâu", DEPTH_SCOPES, default="VN30", key="depth_scope",
                                 label_visibility="collapsed", format_func=lambda g: GROUP_LABELS[g]) or "VN30"
    st.subheader(f"Độ sâu thị trường ({GROUP_LABELS[scope]})", anchor=False)
    depth = market_depth(quotes, day) if scope == "VN30" else market_depth_group(depth_all, day, scope)
    if depth.empty:
        st.caption("Chưa có sổ lệnh cho ngày này." if scope == "VN30" else
                   f"Chưa có độ sâu {GROUP_LABELS[scope]} cho ngày này. Bộ ghi bản mới lưu độ sâu theo sàn mỗi phút "
                   "trong phiên khớp lệnh liên tục; các ngày ghi trước đó chỉ có VN30.")
    else:
        n = "30" if scope == "VN30" else vn(depth["n_symbols"].iloc[-1])
        st.caption(f"Tổng giá trị đang chờ khớp ở 3 mức giá tốt nhất của {n} mã, bên mua và bên bán (tỷ đồng). "
                   "Đường mua và bán càng cao thì thị trường càng sâu, một lệnh lớn càng ít làm giá chạy.")
        depth = with_gaps(depth)
        x = naive_vn(depth["ts"])
        fig = go.Figure()
        fig.add_scatter(x=x, y=depth["bid_value"], name="Bên mua", mode="lines", line=dict(color=HUE, width=1.8),
                        hovertemplate="%{x|%H:%M} · %{y:.1f} tỷ<extra>Bên mua</extra>")
        fig.add_scatter(x=x, y=depth["ask_value"], name="Bên bán", mode="lines", line=dict(color=INK, width=1.4, dash="dot"),
                        hovertemplate="%{x|%H:%M} · %{y:.1f} tỷ<extra>Bên bán</extra>")
        fig.update_layout(legend=dict(orientation="h", y=1.12, x=0))
        fig.update_xaxes(gridcolor=GRID, tickformat="%H:%M")
        fig.update_yaxes(gridcolor=GRID, ticksuffix=" tỷ", rangemode="tozero")
        hide_lunch(fig)
        finish(fig, 280)
        st.plotly_chart(fig, config=CHART_CONFIG, theme=None, key="ov_depth")
        last = depth.dropna(subset=["bid_value"]).iloc[-1]
        spread = (f"; spread tương đối trung vị {vn(last['median_spread_bps'], 1)} bps"
                  if not pd.isna(last["median_spread_bps"]) else "")
        st.caption(f"Lúc {last['ts']:%H:%M}: mua {vn(last['bid_value'], 1)} tỷ, bán {vn(last['ask_value'], 1)} tỷ, "
                   f"mất cân bằng {signed(last['imbalance'] * 100, 0, '%')} (dương: bên mua dày hơn){spread}.")

# ---------- thanh khoản ----------
with st.container(border=True, key="panel_liquidity"):
    st.subheader("Thanh khoản thị trường", anchor=False)
    tv = traded_value(idx, day)
    if not tv.empty:
        st.caption("Giá trị giao dịch lũy kế trong ngày của từng sàn (tỷ đồng, NEO 4.3). Mỗi sàn một ô với thang đo riêng, "
                   "vì HOSE lớn gấp nhiều lần HNX và UPCoM nên vẽ chung thì hai sàn nhỏ nằm sát đáy.")
        tv_plot = with_gaps(tv)
        x = naive_vn(tv_plot["ts"])
        series = [(c, lb) for c, lb in (("HOSE_cum", "HOSE"), ("HNX_cum", "HNX"), ("UPCoM_cum", "UPCoM")) if c in tv]

        def _last(col):
            v = tv[col].dropna()
            return f" · {vn(v.iloc[-1])} tỷ" if len(v) else ""
        fig = make_subplots(rows=1, cols=max(len(series), 1), horizontal_spacing=0.07,
                            subplot_titles=[f"{lb}{_last(c)}" for c, lb in series])
        for i, (col, label) in enumerate(series, start=1):
            fig.add_scatter(x=x, y=tv_plot[col], name=label, mode="lines", line=dict(color=HUE, width=1.8),
                            fill="tozeroy", fillcolor="rgba(29,95,191,0.07)", showlegend=False,
                            hovertemplate="%{x|%H:%M} · %{y:,.0f} tỷ<extra>" + label + "</extra>", row=1, col=i)
        fig.update_xaxes(gridcolor=GRID, tickformat="%H:%M", nticks=4)
        fig.update_yaxes(gridcolor=GRID, ticksuffix=" tỷ", rangemode="tozero", nticks=5)
        hide_lunch(fig)
        finish(fig, 280)
        for a in fig.layout.annotations:
            a.update(font=dict(size=12, color=INK), x=a.x, xanchor="center")
        st.plotly_chart(fig, config=CHART_CONFIG, theme=None, key="ov_liq")
        st.caption(f"Tổng ba sàn đến {tv['ts'].iloc[-1]:%H:%M}: {vn(tv['total_cum'].iloc[-1])} tỷ đồng.")
    else:
        # Ngày ghi trước khi có bảng market_index: chỉ có chuỗi theo phút của 4.2 (khối lượng lũy kế).
        vol = []
        for code, color in (("VNINDEX", HUE), ("VN30", INK)):
            s = (market_json or {}).get(f"intraday_{code}")
            if isinstance(s, dict) and s.get("index"):
                from data.market import index_intraday_frame
                f = index_intraday_frame(s, day)
                vol.append((code, color, f))
        if not vol:
            st.caption("Chưa có dữ liệu thanh khoản cho ngày này.")
        else:
            st.caption("Ngày này chưa có giá trị giao dịch theo từng sàn; hiển thị khối lượng lũy kế (triệu cổ phiếu) "
                       "từ chuỗi theo phút của NEO 4.2.")
            fig = go.Figure()
            for code, color, f in vol:
                fig.add_scatter(x=naive_vn(f["ts"]), y=f["total_volume"] / 1e6, name=INDEX_NAMES.get(code, code), mode="lines",
                                line=dict(color=color, width=1.6),
                                hovertemplate="%{x|%H:%M} · %{y:,.0f} triệu cp<extra>" + code + "</extra>")
            fig.update_layout(legend=dict(orientation="h", y=1.12, x=0))
            fig.update_xaxes(gridcolor=GRID, tickformat="%H:%M")
            fig.update_yaxes(gridcolor=GRID, ticksuffix=" tr", rangemode="tozero")
            hide_lunch(fig)
            finish(fig, 280)
            st.plotly_chart(fig, config=CHART_CONFIG, theme=None, key="ov_liq_vol")

st.html(
    '<p class="note">Dữ liệu từ NEO API (REST 4.3, 4.6, 4.7, 4.9). Chỉ số cập nhật theo vòng hỏi nhanh của bộ ghi (5 giây); '
    "bảng giá, sổ lệnh và độ sâu cập nhật mỗi phút nên chưa phải từng giây. Đây là công cụ phân tích học thuật phục vụ đồ án, không phải khuyến nghị đầu tư; "
    "ứng dụng chỉ đọc dữ liệu thị trường, không gửi, sửa hay hủy lệnh giao dịch.</p>"
)
