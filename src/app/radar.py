"""Trang "Radar thanh khoản" của ứng dụng (nội dung của app.py cũ, không đổi giao diện).

Chạy cả ứng dụng từ thư mục gốc dự án:  streamlit run src/app/app.py
Thương hiệu, công tắc "Trực tiếp" và điều hướng nằm ở app.py; trang này chỉ vẽ phần Radar.

Giao diện: khung chữ đen trên nền xám xanh nhạt; màu xanh (#1d5fbf) chỉ dùng cho dữ liệu chính
(spread của mã đang xem), màu đỏ chỉ dùng cho cảnh báo. Màu nền, phông và bo góc đặt trong
.streamlit/config.toml; CSS bên dưới chỉ lo phần khung tự vẽ (đầu trang, dải chỉ số, ô nền trắng).
"""
from __future__ import annotations

import sys
import time
import zlib
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from analytics.anomaly import detect_anomalies  # noqa: E402
from analytics.lrs import MIN_OBS_PAST, DEFAULT_WEIGHTS, compute_lrs, lrs_thresholds_past, lrs_tier  # noqa: E402
from data.schema import limit_lock_side, normalize_quotes  # noqa: E402
from data.storage import count_rows, load_quotes  # noqa: E402
from finance.absorption import add_absorption  # noqa: E402
from finance.liquidity import add_liquidity_metrics, rank_symbols  # noqa: E402
from finance.sessions import filter_continuous  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402

SAMPLE_CSV = ROOT / "data_sample" / "sample_quotes.csv"
SRC_SAMPLE = "Dữ liệu mô phỏng (tệp mẫu)"
SRC_DB = "Dữ liệu NEO đã ghi (SQLite)"
MODE_SUMMARY = "Tổng hợp theo kỳ"
MODE_REPLAY = "Phát lại một phiên"
SCOPE_ALL, SCOPE_PICK = "Tất cả mã", "Chọn từng mã"
ALERT_SHORT = {"Spread mở rộng": "Spread rộng", "Độ sâu mỏng": "Sổ mỏng", "Spread rộng, độ sâu mỏng": "Spread rộng, sổ mỏng"}

from theme import BORDER, FAINT, FONT, GRID, HUE, INK, MUTED, NEG, WARN, base_layout, group, vn  # noqa: E402


# ---------- tiện ích ----------
def tier_style(v: str) -> str:
    """Màu chữ cho cột mức rủi ro: đỏ cho 'Cao', hổ phách cho 'Chú ý', xám cho phần còn lại."""
    if v == "Cao":
        return f"color: {NEG}; font-weight: 500"
    if v == "Chú ý":
        return f"color: {WARN}"
    return f"color: {MUTED}"


@st.cache_data(show_spinner=False)
def load_source(source: str, db_path: str, version: float) -> tuple[pd.DataFrame, dict]:
    """Đọc, làm sạch, chỉ giữ phiên khớp lệnh liên tục (loại ATO/ATC/nghỉ trưa), tính chỉ số sổ lệnh."""
    raw = pd.read_csv(SAMPLE_CSV) if source == SRC_SAMPLE else load_quotes(Path(db_path))
    clean, report = normalize_quotes(raw)
    clean, dropped = filter_continuous(clean)
    report["dropped_session"] = dropped
    locked, _ = filter_continuous(report["limit_locked"])
    report["limit_locked"] = locked.assign(side=limit_lock_side(locked))[["ts", "symbol", "side"]]
    return add_liquidity_metrics(clean), report


@st.cache_data(show_spinner=False)
def analyze(source: str, db_path: str, version: float, window: int, threshold: float,
            w_spread: float, w_depth: float, w_imb: float) -> tuple[pd.DataFrame, dict]:
    """Cảnh báo bất thường, tỷ lệ hấp thụ và điểm LRS. Tính trên toàn bộ lịch sử để đủ dữ liệu khởi động."""
    df, _ = load_source(source, db_path, version)
    out = add_absorption(detect_anomalies(df, window=window, threshold=threshold))
    out["lrs"] = compute_lrs(out, {"spread": w_spread, "depth": w_depth, "imbalance": w_imb})
    # Ngưỡng Chú ý/Cao tại mỗi thời điểm chỉ dùng điểm LRS có trước thời điểm đó (không nhìn trước).
    thr = lrs_thresholds_past(out["lrs"], out["ts"])
    out["lrs_watch"], out["lrs_high"] = thr["watch"], thr["high"]
    out["lrs_tier"] = lrs_tier(out["lrs"], thr)
    return out


def _play(n: int) -> None:
    if st.session_state.get("replay_idx", 0) >= n - 1:
        st.session_state["replay_idx"] = 0
    st.session_state["playing"] = True


def _pause() -> None:
    st.session_state["playing"] = False


def _rewind() -> None:
    st.session_state["replay_idx"] = 0
    st.session_state["playing"] = False


def _pick_from_ranking(key: str, syms: list[str]) -> None:
    """Chọn một dòng trong bảng xếp hạng thì mở diễn biến của mã đó."""
    rows = st.session_state[key].selection.rows
    if rows and rows[0] < len(syms):
        st.session_state["sym"] = syms[rows[0]]


# ---------- chọn nguồn dữ liệu ----------
settings = get_settings()
sources = []
if SAMPLE_CSV.exists():
    sources.append(SRC_SAMPLE)
if count_rows(settings.db_path) > 0:
    sources.insert(0, SRC_DB)

with st.sidebar:
    group("Dữ liệu")
    if not sources:
        source = None
    elif len(sources) == 1:
        source = sources[0]
        st.markdown(f"Nguồn: **{'tệp mẫu mô phỏng' if source == SRC_SAMPLE else 'dữ liệu NEO đã ghi'}**")
    else:
        source = st.radio("Nguồn dữ liệu", sources)

if source is None:
    st.title("Radar thanh khoản VN30", anchor=False)
    st.error(
        "Chưa tìm thấy dữ liệu. Chạy `python scripts/generate_sample_data.py` để tạo dữ liệu mô phỏng, "
        "hoặc ghi dữ liệu NEO bằng `python scripts/record_rest.py` (hoặc `python scripts/run_live.py`). "
        "Đang bật chế độ Trực tiếp thì trang tự hiện dữ liệu khi bộ ghi ghi xong phút đầu tiên.",
        title="Chưa có dữ liệu",
    )
    st.stop()

version = SAMPLE_CSV.stat().st_mtime if source == SRC_SAMPLE else settings.db_path.stat().st_mtime
db_path_str = str(settings.db_path)
try:
    all_df, report = load_source(source, db_path_str, version)
except Exception as exc:  # hiển thị lỗi rõ ràng thay vì để ứng dụng treo
    st.title("Radar thanh khoản VN30", anchor=False)
    st.error(f"Không đọc được dữ liệu: {type(exc).__name__}. Kiểm tra tệp dữ liệu và thử lại.")
    st.stop()

if all_df.empty:
    st.title("Radar thanh khoản VN30", anchor=False)
    st.warning(
        "Nguồn dữ liệu đã chọn không có lần chụp nào trong phiên khớp lệnh liên tục "
        "(09:15-11:30 và 13:00-14:30) sau khi làm sạch."
    )
    st.stop()

days = sorted(all_df["ts"].dt.date.unique())
symbols_all = sorted(all_df["symbol"].unique())

with st.sidebar:
    mode = st.segmented_control("Chế độ xem", [MODE_SUMMARY, MODE_REPLAY], default=MODE_SUMMARY, required=True,
                                format_func=lambda m: "Tổng hợp" if m == MODE_SUMMARY else "Phát lại phiên",
                                help="Phát lại cho phép tua một phiên đã ghi từng bước, dùng khi sàn đã đóng cửa.",
                                width="stretch")
    if mode == MODE_SUMMARY:
        rng = st.date_input("Khoảng phiên giao dịch", value=(days[0], days[-1]), min_value=days[0],
                            max_value=days[-1], format="DD/MM/YYYY")
        d_from, d_to = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (days[0], days[-1])
    scope = st.segmented_control("Phạm vi mã", [SCOPE_ALL, SCOPE_PICK], default=SCOPE_ALL, required=True,
                                 width="stretch")
    picked = symbols_all if scope == SCOPE_ALL else st.multiselect("Mã cổ phiếu", symbols_all,
                                                                     default=symbols_all[:5])
    group("Cảnh báo")
    threshold = st.slider("Ngưỡng z-score", 2.0, 5.0, 3.0, 0.5,
                          help="Mức lệch so với lịch sử của chính mã đó (tính bằng độ lệch chuẩn).")
    window = st.slider("Cửa sổ lịch sử (số lần chụp)", 20, 300, 60, 10,
                       help="Số lần chụp gần nhất dùng làm mức thường lệ của mỗi mã. "
                            "Bộ ghi mặc định chụp 1 phút một lần, nên 60 lần tương đương khoảng 1 giờ.")
    with st.expander("Trọng số điểm rủi ro LRS"):
        raw_w = [
            st.slider("Spread", 0.0, 1.0, DEFAULT_WEIGHTS["spread"], 0.05),
            st.slider("Độ sâu", 0.0, 1.0, DEFAULT_WEIGHTS["depth"], 0.05),
            st.slider("Lệch mua/bán", 0.0, 1.0, DEFAULT_WEIGHTS["imbalance"], 0.05),
        ]
        total_w = sum(raw_w) or 1.0
        w_spread, w_depth, w_imb = (x / total_w for x in raw_w)
        st.caption("Tự chuẩn hóa để tổng bằng 100%. Mặc định 40/40/20 là giả định ban đầu.")

if not picked:
    st.title("Radar thanh khoản VN30", anchor=False)
    st.info("Chọn ít nhất một mã ở thanh bên để xem kết quả.")
    st.stop()

analyzed = analyze(source, db_path_str, version, window, threshold, w_spread, w_depth, w_imb)

# ---------- chế độ phát lại ----------
replay_day = cut_ts = None
if mode == MODE_REPLAY:
    with st.sidebar:
        group("Phát lại")
        replay_day = st.selectbox("Phiên", sorted(days, reverse=True), format_func=lambda d: d.strftime("%d/%m/%Y"))
        day_ts = (analyzed.loc[analyzed["ts"].dt.date == replay_day, "ts"].drop_duplicates().sort_values().tolist())
        n_steps = len(day_ts)
        if st.session_state.get("replay_day") != replay_day:  # đổi phiên: về cuối phiên, dừng phát
            st.session_state["replay_day"] = replay_day
            st.session_state["replay_idx"] = n_steps - 1
            st.session_state["playing"] = False
        idx = min(max(int(st.session_state.get("replay_idx", n_steps - 1)), 0), n_steps - 1)
        if st.session_state.get("playing"):
            if idx < n_steps - 1:
                idx += 1
            else:
                st.session_state["playing"] = False
        st.session_state["replay_idx"] = idx
        if n_steps > 1:
            st.select_slider("Thời điểm", options=list(range(n_steps)), key="replay_idx",
                             format_func=lambda i: day_ts[i].strftime("%H:%M"))
        with st.container(horizontal=True, gap="small"):
            st.button("Phát", icon=":material/play_arrow:", on_click=_play, args=(n_steps,), type="primary")
            st.button("Dừng", icon=":material/pause:", on_click=_pause)
            st.button("", icon=":material/first_page:", on_click=_rewind, help="Về đầu phiên", key="rewind")
    cut_ts = day_ts[min(st.session_state["replay_idx"], n_steps - 1)]
    mask = (analyzed["ts"].dt.date == replay_day) & (analyzed["ts"] <= cut_ts) & analyzed["symbol"].isin(picked)
else:
    st.session_state["playing"] = False
    mask = (
        (analyzed["ts"].dt.date >= d_from) & (analyzed["ts"].dt.date <= d_to) & analyzed["symbol"].isin(picked)
    )

view = analyzed[mask]
if view.empty:
    st.title("Radar thanh khoản VN30", anchor=False)
    st.info("Không có dữ liệu trong khoảng phiên và mã đã chọn. Mở rộng khoảng ngày hoặc chọn thêm mã.")
    st.stop()

ranking = rank_symbols(view)
alerts = view[view["is_alert"]].sort_values("ts", ascending=False)
alert_counts = alerts.groupby("symbol").size()
ranking["alerts"] = ranking["symbol"].map(alert_counts).fillna(0).astype(int)
last_per_sym = view.sort_values("ts").groupby("symbol").tail(1).set_index("symbol")
ranking["lrs"] = ranking["symbol"].map(last_per_sym["lrs"])
ranking["lrs_tier"] = ranking["symbol"].map(last_per_sym["lrs_tier"]).fillna("")

# Các con số dùng ở nhiều chỗ được tính một lần ở đây.
n_alerts = len(alerts)
n_alert_syms = alerts["symbol"].nunique()
weakest = ranking.iloc[0]
top_alert_sym = alert_counts.idxmax() if n_alerts else None
top_alert_n = int(alert_counts.max()) if n_alerts else 0
top_alert_ratio = alerts.loc[alerts["symbol"] == top_alert_sym, "spread_ratio"].max() if n_alerts else np.nan

# ---------- đầu trang ----------
is_sim = source == SRC_SAMPLE
last_ts = cut_ts if cut_ts is not None else all_df["ts"].max()

if n_alerts:
    finding = (f'<span class="neg">{n_alerts} cảnh báo ở {n_alert_syms} mã.</span> '
               f"{top_alert_sym} bị cảnh báo nhiều nhất ({top_alert_n} lần)")
    finding += (f", spread có lúc gấp {vn(top_alert_ratio, 1)} lần mức thường lệ của mã." if np.isfinite(top_alert_ratio)
                else ".")
else:
    finding = "Không có cảnh báo nào trong khoảng đã chọn."
finding += f" Thanh khoản yếu nhất nhóm: {weakest['symbol']}."

if mode == MODE_REPLAY:
    stamp = f"Đang phát lại {replay_day:%d/%m/%Y}<br>đến {last_ts:%H:%M} (UTC+7)"
elif is_sim:
    stamp = f"Bản ghi cuối {last_ts:%d/%m/%Y %H:%M} (UTC+7)<br>Đọc từ tệp, không có luồng trực tiếp"
else:
    age_min = max((pd.Timestamp.now(tz=TZ) - all_df["ts"].max()).total_seconds() / 60, 0)  # lệch đồng hồ không ra số âm
    link = f"đang nhận dữ liệu, cách {age_min:.0f} phút" if age_min <= 5 else "không có dữ liệu mới"
    stamp = f"Bản ghi cuối {last_ts:%d/%m/%Y %H:%M} (UTC+7)<br>Kết nối: {link}" + (" · tự cập nhật" if st.session_state.get("live") else "")

with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    with st.container(width="stretch"):
        st.title("Radar thanh khoản VN30", anchor=False)
        st.caption("Dành cho nhà đầu tư cá nhân và người quản trị rủi ro: cho biết mã VN30 nào đang khó mua bán, "
                   "và khi nào spread hoặc độ sâu sổ lệnh lệch khỏi mức thường lệ của chính mã đó.")
        st.html(f'<p class="finding">{finding}</p>')
    with st.container(horizontal=True, width="content", vertical_alignment="center", gap="small"):
        st.html(f'<div class="stamp">{stamp}</div>', width="content")
        st.button("Tải lại", icon=":material/refresh:",
                  help="Đọc lại tệp hoặc cơ sở dữ liệu để lấy các bản ghi mới nhất.")

notes = []
if is_sim:
    notes.append("<b>Dữ liệu mô phỏng, không phải giá thị trường.</b> Mọi con số chỉ minh họa cách công cụ hoạt động.")
notes.append(f"{vn(len(view))} lần chụp sổ lệnh của {view['symbol'].nunique()} mã")
dropped_session = report.get("dropped_session", 0)
if dropped_session:
    notes.append(f"đã loại {vn(dropped_session)} lần chụp ngoài phiên khớp lệnh liên tục")
if is_sim:
    st.html(f'<div class="notice">{notes[0]} {"; ".join(notes[1:]).capitalize()}.</div>')
else:
    st.caption("; ".join(notes).capitalize() + ".")

# Khóa trần/sàn: một bên sổ lệnh trống nên không tính được spread; báo riêng thay vì bỏ im lặng.
locked = report["limit_locked"]
lk_day = locked["ts"].dt.date
if mode == MODE_REPLAY:
    locked = locked[(lk_day == replay_day) & (locked["ts"] <= cut_ts)]
else:
    locked = locked[(lk_day >= d_from) & (lk_day <= d_to)]
locked = locked[locked["symbol"].isin(picked)]
if not locked.empty:
    parts = [f"<b>{s}</b> khóa {side} {len(g)} lần ({g['ts'].min():%d/%m %H:%M}–{g['ts'].max():%H:%M})"
             for (s, side), g in locked.sort_values("ts").groupby(["symbol", "side"])]
    st.html('<div class="notice">Mã bị khóa trần/sàn (một bên sổ lệnh trống, không tính được spread nên không có '
            "trong xếp hạng và cảnh báo ở các thời điểm này): " + "; ".join(parts) + ".</div>")

alert_sub = (f'ở {n_alert_syms} mã · nhiều nhất <span class="neg">{top_alert_sym} ({top_alert_n})</span>'
             if n_alerts else "không có mã nào vượt ngưỡng")
st.html(
    '<div class="kpis">'
    f'<div class="kpi lead"><div class="l">Cảnh báo trong kỳ</div><div class="v">{n_alerts}</div>'
    f'<div class="s">{alert_sub}</div></div>'
    f'<div class="kpi"><div class="l">Spread tương đối trung vị</div>'
    f'<div class="v">{vn(view["rel_spread_bps"].median(), 1)}<small>bps</small></div>'
    '<div class="s">chi phí mua rồi bán ngay</div></div>'
    f'<div class="kpi"><div class="l">Độ sâu 3 mức giá trung vị</div>'
    f'<div class="v">{vn(view["depth_value"].median() / 1e6, 0)}<small>triệu đ</small></div>'
    '<div class="s">tiền chờ khớp ở 3 mức mua và bán</div></div>'
    f'<div class="kpi"><div class="l">Thanh khoản yếu nhất nhóm</div>'
    f'<div class="v">{weakest["symbol"]}<small>{vn(weakest["score"], 0)}/100</small></div>'
    f'<div class="s">điểm thấp nhất trong {len(ranking)} mã</div></div>'
    "</div>"
)

# ---------- xếp hạng + cảnh báo ----------
TABLE_H = 438
left, right = st.columns([7, 5], gap="small")
with left, st.container(border=True, key="panel_rank"):
    st.subheader("Xếp hạng thanh khoản", anchor=False,
                 help="Điểm 0-100 so sánh giữa các mã đang chọn: spread hẹp tính theo bước giá (40%), "
                      "độ sâu lớn (40%), ít lệch mua/bán (20%). LRS là điểm rủi ro ở lần chụp mới nhất của từng mã.")
    st.caption("Mã yếu nhất ở trên cùng. Chọn ô đầu dòng để xem diễn biến của mã đó bên dưới.")
    table = ranking.assign(depth_m=ranking["depth_value"] / 1e6)[
        ["symbol", "score", "spread_ticks", "rel_spread_bps", "depth_m", "lrs", "lrs_tier", "alerts"]
    ].reset_index(drop=True)
    rank_syms = table["symbol"].tolist()
    # Khóa bảng đổi theo thứ tự xếp hạng, để dấu chọn không nằm nhầm dòng khi thứ hạng thay đổi.
    rank_key = "rank_tbl_" + format(zlib.crc32("|".join(rank_syms).encode()), "x")
    st.dataframe(
        table.style.map(tier_style, subset=["lrs_tier"]).format(
            {"spread_ticks": "{:.2f}", "rel_spread_bps": "{:.1f}", "depth_m": "{:,.0f}", "lrs": "{:+.2f}"},
            decimal=",", thousands=".", na_rep="–"),
        hide_index=True,
        height=TABLE_H,
        key=rank_key,
        on_select=partial(_pick_from_ranking, rank_key, rank_syms),
        selection_mode="single-row",
        alt="Bảng xếp hạng thanh khoản các mã VN30",
        column_config={
            "symbol": st.column_config.TextColumn("Mã", width=56, pinned=True),
            "score": st.column_config.ProgressColumn("Điểm", min_value=0, max_value=100, format="%.0f",
                                                     color="#8a8a8a", width=76),
            "spread_ticks": st.column_config.NumberColumn(
                "Spread (bước)", width=96,
                help="Spread trung bình tính bằng số bước giá; 1,00 là hẹp nhất có thể. Dùng để chấm điểm."),
            "rel_spread_bps": st.column_config.NumberColumn(
                "Spread (bps)", width=96,
                help="Spread tương đối trung vị: chi phí mua rồi bán ngay. Mã giá thấp có bps cao vì bước giá "
                     "chiếm tỷ lệ lớn, nên cột này không dùng để so sánh thanh khoản giữa các mã."),
            "depth_m": st.column_config.NumberColumn("Độ sâu (tr đ)", width=96),
            "lrs": st.column_config.NumberColumn("LRS", width=60,
                                                 help="Điểm rủi ro thanh khoản ở lần chụp mới nhất. Cao hơn là rủi ro hơn."),
            "lrs_tier": st.column_config.TextColumn("Mức", width=88),
            "alerts": st.column_config.NumberColumn("Cảnh báo", format="%d"),
        },
    )
with right, st.container(border=True, key="panel_alerts"):
    st.subheader("Cảnh báo gần nhất", anchor=False,
                 help="Spread mở rộng hoặc độ sâu mỏng bất thường so với lịch sử của chính mã.")
    shown_n = min(40, n_alerts)
    if alerts.empty:
        st.caption("Không có cảnh báo trong khoảng đã chọn. Thử hạ ngưỡng z-score ở thanh bên.")
    else:
        st.caption(f"{n_alerts} cảnh báo trong kỳ, hiện {shown_n} gần nhất.")
    if not alerts.empty:
        shown = alerts.head(40).assign(
            when=lambda d: d["ts"].dt.strftime("%d/%m %H:%M"),
            alert_type=lambda d: d["alert_type"].map(ALERT_SHORT).fillna(d["alert_type"])
            + np.where(d["thin_no_trade"], " · không khớp", ""),
        )[["when", "symbol", "severity", "spread_ratio", "alert_type"]].reset_index(drop=True)
        st.dataframe(
            shown.style.map(tier_style, subset=["severity"]).format(
                {"spread_ratio": "{:.1f}"}, decimal=",", na_rep="–"),
            hide_index=True,
            height=TABLE_H,
            alt="Danh sách cảnh báo thanh khoản gần nhất",
            column_config={
                "when": st.column_config.TextColumn("Thời điểm", width=86),
                "symbol": st.column_config.TextColumn("Mã", width=52),
                "severity": st.column_config.TextColumn("Mức", width=60),
                "spread_ratio": st.column_config.NumberColumn("Spread (lần)", width=80,
                                                              help="Spread hiện tại so với trung vị lịch sử của mã"),
                "alert_type": st.column_config.TextColumn(
                    "Loại", help="Spread rộng: chênh lệch mua-bán giãn ra. Sổ mỏng: độ sâu 3 mức rút đi. "
                                 "'không khớp': độ sâu rút mỏng mà gần như không có giao dịch khớp."),
            },
        )

# ---------- bản đồ nhiệt ----------
hm = view.copy()
hm["ratio"] = hm["rel_spread_bps"] / hm.groupby("symbol")["rel_spread_bps"].transform("median")
hm["bucket"] = hm["ts"].dt.floor("30min").dt.strftime("%H:%M")
pivot = hm.pivot_table(index="symbol", columns="bucket", values="ratio", aggfunc="mean")
pivot = pivot.reindex(index=ranking["symbol"].tolist(), columns=sorted(pivot.columns))

with st.container(border=True, key="panel_heatmap"):
    st.subheader("Chi phí giao dịch theo giờ", anchor=False)
    st.caption("Spread trung bình mỗi khung 30 phút, tính bằng số lần so với mức trung vị của chính mã. "
               "Ô xám là bình thường; ô càng đỏ, mua bán càng đắt hơn thường lệ.")
    fig_hm = go.Figure(
        go.Heatmap(
            z=pivot.values, x=pivot.columns, y=pivot.index,
            zmin=0.8, zmax=2.0,
            # Dưới 1,3 lần: xám (bình thường); từ 1,3 lần trở lên mới chuyển dần sang đỏ.
            colorscale=[[0, "#f5f6f8"], [0.42, "#e6e9ee"], [0.5, "#f4cfca"], [0.75, "#e0807a"], [1, NEG]],
            xgap=2, ygap=2,
            colorbar=dict(title=dict(text="lần thường lệ", font=dict(size=11, color=MUTED)), thickness=10,
                          len=0.6, outlinewidth=0, tickfont=dict(size=11, color=MUTED),
                          tickvals=[1.0, 1.5, 2.0], ticktext=["1,0", "1,5", "≥2,0"]),
            hovertemplate="%{y} lúc %{x}<br>Spread = %{z:.2f} lần thường lệ<extra></extra>",
        )
    )
    base_layout(fig_hm, max(320, 21 * len(pivot) + 70))
    fig_hm.update_layout(
        margin=dict(l=52, r=4, t=28, b=4),
        xaxis=dict(side="top", showgrid=False, type="category", tickfont=dict(color=MUTED)),
        yaxis=dict(autorange="reversed", showgrid=False, type="category", automargin=True,
                   tickfont=dict(color=INK, size=12), ticks="", showticklabels=True),
    )
    st.plotly_chart(fig_hm, config={"displayModeBar": False}, theme=None,
                    alt="Bản đồ nhiệt spread theo mã và khung 30 phút")

# ---------- chi tiết một mã ----------
sym_list = ranking["symbol"].tolist()
if st.session_state.get("sym") not in sym_list:  # mở sẵn mã nhiều cảnh báo nhất
    st.session_state["sym"] = sym_list[int(ranking["alerts"].values.argmax())] if ranking["alerts"].max() > 0 else sym_list[0]

with st.container(border=True, key="panel_detail"):
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        st.subheader("Diễn biến trong phiên", anchor=False,
                     help="Spread, độ sâu và điểm rủi ro LRS của một mã; chấm đỏ là các thời điểm bị cảnh báo.")
        sym = st.selectbox("Mã", sym_list, key="sym", width=140)
        if mode == MODE_REPLAY:
            day = replay_day
        else:
            day_options = sorted(view["ts"].dt.date.unique(), reverse=True)
            sym_alert_days = alerts.loc[alerts["symbol"] == sym, "ts"].dt.date
            day_default = day_options.index(sym_alert_days.max()) if len(sym_alert_days) else 0
            day = st.selectbox("Phiên", day_options, index=day_default, width=160,
                               format_func=lambda d: d.strftime("%d/%m/%Y"))

    one = view[(view["symbol"] == sym) & (view["ts"].dt.date == day)].copy()
    if one.empty:
        st.info("Mã này không có dữ liệu trong phiên đã chọn.")
    else:
        one["x"] = one["ts"].dt.tz_localize(None)
        flagged = one[one["is_alert"]]
        n_flag = len(flagged)
        st.caption(
            f"{sym}, phiên {day:%d/%m/%Y}: spread trung vị {vn(one['rel_spread_bps'].median(), 1)} bps, "
            f"độ sâu trung vị {vn(one['depth_value'].median() / 1e6, 0)} triệu đ, "
            + (f"{n_flag} lần bị cảnh báo." if n_flag else "không bị cảnh báo lần nào.")
        )
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.36, 0.32, 0.32],
                            subplot_titles=("Spread tương đối (bps)", "Độ sâu 3 mức giá (triệu đồng)",
                                            "Điểm rủi ro thanh khoản LRS"))
        fig.add_trace(go.Scatter(x=one["x"], y=one["rel_spread_bps"], mode="lines", line=dict(color=HUE, width=2),
                                 name="Spread", showlegend=False,
                                 hovertemplate="%{x|%H:%M}  %{y:.1f} bps<extra></extra>"), 1, 1)
        fig.add_trace(go.Scatter(x=one["x"], y=one["depth_value"] / 1e6, mode="lines", fill="tozeroy",
                                 line=dict(color=INK, width=1.5), fillcolor="rgba(10,10,10,0.06)", name="Độ sâu",
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
        if not flagged.empty:
            for row_i, ycol, scale in ((1, "rel_spread_bps", 1), (2, "depth_value", 1e6), (3, "lrs", 1)):
                fig.add_trace(go.Scatter(x=flagged["x"], y=flagged[ycol] / scale, mode="markers",
                                         name="Cảnh báo", showlegend=False,
                                         marker=dict(color=NEG, size=8, line=dict(color="#ffffff", width=1.5)),
                                         hovertemplate="%{x|%H:%M}  cảnh báo<extra></extra>"), row_i, 1)
        fig.update_xaxes(rangebreaks=[dict(bounds=[11.5, 13], pattern="hour")], showgrid=False, tickformat="%H:%M",
                         showline=True, linecolor=BORDER, tickfont=dict(color=MUTED))
        fig.update_yaxes(gridcolor=GRID, zeroline=False, nticks=5, tickfont=dict(color=MUTED), automargin=True,
                         ticks="", ticklabelstandoff=6)
        for a in fig.layout.annotations[:3]:
            a.update(font=dict(size=12, color=MUTED), x=0, xanchor="left")
        base_layout(fig, 600)
        fig.update_layout(hovermode="x unified", margin=dict(l=48, r=8, t=28, b=4))
        st.plotly_chart(fig, config={"displayModeBar": False}, theme=None,
                        alt=f"Diễn biến spread, độ sâu và LRS của {sym} trong phiên {day:%d/%m/%Y}")
        if one["lrs_watch"].isna().all():
            st.caption(f"Chưa đủ dữ liệu để tính ngưỡng LRS (cần ít nhất {MIN_OBS_PAST} điểm LRS trước thời điểm xét).")

# ---------- phương pháp và giới hạn ----------
with st.expander("Phương pháp tính và giới hạn", icon=":material/menu_book:"):
    st.markdown(
        """
**Dữ liệu đầu vào.** Chỉ dùng các lần chụp trong phiên khớp lệnh liên tục (09:15-11:30 và 13:00-14:30). Các phiên
ATO, ATC và nghỉ trưa bị loại vì sổ lệnh lúc đó không phản ánh thanh khoản liên tục.

**Chỉ số từ sổ lệnh 3 mức giá**
- Spread tương đối (bps) = (giá bán tốt nhất − giá mua tốt nhất) / giá giữa × 10.000.
- Spread theo bước giá = (giá bán tốt nhất − giá mua tốt nhất) / bước giá HOSE (10đ dưới 10.000đ, 50đ từ 10.000đ
  đến 49.950đ, 100đ từ 50.000đ). 1 bước giá là hẹp nhất có thể.
- Độ sâu = tổng (giá × khối lượng) của 3 mức mua và 3 mức bán.
- Lệch mua/bán = (khối lượng mua − khối lượng bán) / tổng, từ −1 đến +1.

**Điểm thanh khoản (0-100)** là xếp hạng tương đối giữa các mã đang chọn: spread trung bình theo bước giá thấp (40%),
độ sâu lớn (40%), ít lệch mua/bán (20%). Trọng số là giả định ban đầu, chưa được hiệu chỉnh.
Điểm dùng spread theo bước giá chứ không dùng bps: phần lớn thời gian spread VN30 chỉ đúng 1 bước giá, nên bps
chủ yếu phụ thuộc giá cổ phiếu (mã giá thấp luôn có bps cao) chứ không cho biết mã nào khó mua bán hơn.

**Điểm rủi ro LRS** = w₁·Z(spread) − w₂·Z(độ sâu) + w₃·Z(|lệch mua/bán|), trong đó Z là z-score cuốn chiếu của chính mã
đó (spread và độ sâu lấy logarit). Cao hơn là rủi ro hơn. Ngưỡng "Chú ý" và "Cao" tại mỗi thời điểm là phân vị
95% và 99% của mọi điểm LRS có *trước* thời điểm đó (cần ít nhất 300 điểm), nên không dùng dữ liệu tương lai và
ngưỡng thay đổi dần theo thời gian. Vì là phân vị nên về lâu dài khoảng 1% lần chụp ở mức "Cao" dù thị trường yên;
mức này để theo dõi xu hướng, còn danh sách cảnh báo dựa trên điều kiện bên dưới.

**Cảnh báo** khi z-score của log spread ≥ ngưỡng (hoặc của log độ sâu ≤ −ngưỡng) *và* spread ≥ 2,5 lần
(độ sâu ≤ 0,4 lần) trung vị lịch sử của mã. Mean và độ lệch chuẩn chỉ dùng các lần chụp *trước* thời điểm xét,
nên không nhìn trước tương lai. Ghi chú "Mỏng, không khớp" nghĩa là độ sâu rút mỏng trong khi gần như không có
khối lượng khớp; đây chỉ là dấu hiệu, không chứng minh có hủy lệnh ảo hay thao túng.

**Phát lại** dựng lại một phiên đã ghi từng bước. Mọi phép tính, kể cả ngưỡng LRS, chỉ dùng dữ liệu đến thời
điểm đang xem.

**Giới hạn**
- Z-score kém ổn định khi spread gần như không đổi; điều kiện tỷ lệ tối thiểu được thêm để tránh báo động giả.
- Cửa sổ lịch sử chưa loại bỏ dạng chữ U của thanh khoản trong ngày (đầu và cuối phiên sôi động hơn giữa phiên).
- Ngưỡng và trọng số mặc định chưa được hiệu chỉnh trên dữ liệu thật.
- Lúc mã khóa trần hoặc sàn, một bên sổ lệnh trống nên không tính được spread: các lần chụp đó không vào xếp hạng
  và cảnh báo mà được liệt kê riêng ở đầu trang.
- Cảnh báo là tín hiệu để xem xét thêm, không giải thích nguyên nhân và không dự báo giá.
        """
    )

st.html(
    '<p class="note">Đây là công cụ phân tích học thuật phục vụ đồ án, không phải khuyến nghị đầu tư. '
    "Ứng dụng chỉ đọc dữ liệu thị trường, không gửi, sửa hay hủy lệnh giao dịch.</p>"
)

# Phát lại tự động: chờ một nhịp rồi chạy lại để sang lần chụp kế tiếp.
if st.session_state.get("playing"):
    time.sleep(0.35)
    st.rerun()
