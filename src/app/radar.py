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

from analytics.baseline import bucket_label, tod_bucket  # noqa: E402
from analytics.lrs import MIN_OBS_PAST  # noqa: E402
from charts import intraday_caption, intraday_figure  # noqa: E402
from flipgrid import grid_state, tile_weights, treemap_layout  # noqa: E402
from flipgrid_component import flip_treemap  # noqa: E402
from model_config import section  # noqa: E402
from neo_api.config import TZ, get_settings  # noqa: E402
from shared import (SRC_SAMPLE, analyzed_data, available_sources, liquidity_ranking, load_source,  # noqa: E402
                    params, source_version)

SPEEDS = {"1x": 1, "2x": 2, "4x": 4}   # số lần chụp (phút) nhảy qua mỗi nhịp phát
_BASE = section("baseline")
MIN_BASELINE = int(_BASE["min_baseline_sessions"])   # từ config.toml
MIN_OBS_BUCKET = int(_BASE["min_obs_per_bucket"])
MODE_SUMMARY = "Tổng hợp theo kỳ"
MODE_REPLAY = "Phát lại một phiên"
SCOPE_ALL, SCOPE_PICK = "Tất cả mã", "Chọn từng mã"
ALERT_SHORT = {"Spread mở rộng": "Spread rộng", "Độ sâu mỏng": "Sổ mỏng", "Spread rộng, độ sâu mỏng": "Spread rộng, sổ mỏng"}

from theme import CHART_CONFIG, INK, MUTED, NEG, WARN, base_layout, group, vn  # noqa: E402


# ---------- tiện ích ----------
def tier_style(v: str) -> str:
    """Màu chữ cho cột mức rủi ro: đỏ cho 'Cao', hổ phách cho 'Chú ý', xám cho phần còn lại."""
    if v == "Cao":
        return f"color: {NEG}; font-weight: 500"
    if v == "Chú ý":
        return f"color: {WARN}"
    return f"color: {MUTED}"


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
sources = available_sources()

with st.sidebar:
    group("Dữ liệu")
    if not sources:
        source = None
    elif len(sources) == 1:
        source = sources[0]
        st.markdown(f"Nguồn: **{'tệp mẫu mô phỏng' if source == SRC_SAMPLE else 'dữ liệu NEO đã ghi'}**")
    else:
        prev_src = st.session_state.get("source")
        source = st.radio("Nguồn dữ liệu", sources, index=sources.index(prev_src) if prev_src in sources else 0)
    st.session_state["source"] = source  # các trang khác (Bộ lọc, Chi tiết mã) dùng cùng nguồn

if source is None:
    st.title("Radar thanh khoản VN30", anchor=False)
    st.error(
        "Chưa tìm thấy dữ liệu. Chạy `python scripts/generate_sample_data.py` để tạo dữ liệu mô phỏng, "
        "hoặc ghi dữ liệu NEO bằng `python scripts/record_rest.py` (hoặc `python scripts/run_live.py`). "
        "Đang bật chế độ Trực tiếp thì trang tự hiện dữ liệu khi bộ ghi ghi xong phút đầu tiên.",
        title="Chưa có dữ liệu",
    )
    st.stop()

version = source_version(source)
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
ssi_days = set(report.get("ssi_days", []))   # ngày NEO không ghi được, lấy sổ lệnh từ SSI (xem shared.load_source)


def day_label(d) -> str:
    return d.strftime("%d/%m/%Y") + (" · SSI" if d in ssi_days else "")


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
    p0 = params()
    threshold = st.slider("Ngưỡng z-score độ sâu", 2.0, 5.0, float(p0["threshold"]), 0.5,
                          help="Độ sâu lệch bao nhiêu so với mức thường lệ của chính mã đó ở cùng khung giờ "
                               "(z bền vững tính bằng trung vị và MAD). Leys và cộng sự (2013) gợi ý 2,5; 3 thận trọng hơn.")
    max_sessions = st.slider("Số phiên trước làm mốc (tối đa)", MIN_BASELINE, 20, max(MIN_BASELINE, int(p0["max_sessions"])), 1,
                             help="Mức thường lệ của một mã ở khung 30 phút = các lần chụp cùng khung giờ trong tối đa "
                                  f"chừng này phiên gần nhất TRƯỚC phiên đang xét. Cần ít nhất {MIN_BASELINE} phiên trước mới đánh giá "
                                  "(đặt ở config.toml).")
    with st.expander("Trọng số điểm rủi ro LRS"):
        raw_w = [
            st.slider("Spread", 0.0, 1.0, float(p0["w_spread"]), 0.05),
            st.slider("Độ sâu", 0.0, 1.0, float(p0["w_depth"]), 0.05),
            st.slider("Lệch mua/bán", 0.0, 1.0, float(p0["w_imb"]), 0.05),
        ]
        total_w = sum(raw_w) or 1.0
        w_spread, w_depth, w_imb = (x / total_w for x in raw_w)
        st.caption("Tự chuẩn hóa để tổng bằng 100%. Mặc định 40/40/20 là giả định ban đầu.")
# Lưu tham số vào khóa thường để Bộ lọc và Chi tiết mã tính cùng một cách (cùng số với Radar).
st.session_state["params"] = {"threshold": threshold, "max_sessions": max_sessions,
                              "w_spread": w_spread, "w_depth": w_depth, "w_imb": w_imb}

if not picked:
    st.title("Radar thanh khoản VN30", anchor=False)
    st.info("Chọn ít nhất một mã ở thanh bên để xem kết quả.")
    st.stop()

analyzed = analyzed_data(source)

# ---------- chế độ phát lại ----------
replay_day = cut_ts = None
if mode == MODE_REPLAY:
    with st.sidebar:
        group("Phát lại")
        replay_day = st.selectbox("Phiên", sorted(days, reverse=True), format_func=day_label)
        day_ts = (analyzed.loc[analyzed["ts"].dt.date == replay_day, "ts"].drop_duplicates().sort_values().tolist())
        n_steps = len(day_ts)
        if st.session_state.get("replay_day") != replay_day:  # đổi phiên: về cuối phiên, dừng phát
            st.session_state["replay_day"] = replay_day
            st.session_state["replay_idx"] = n_steps - 1
            st.session_state["playing"] = False
        idx = min(max(int(st.session_state.get("replay_idx", n_steps - 1)), 0), n_steps - 1)
        if st.session_state.get("playing"):
            if idx < n_steps - 1:
                idx = min(idx + SPEEDS[st.session_state.get("speed", "1x")], n_steps - 1)   # 2x, 4x: nhảy 2, 4 lần chụp mỗi nhịp
            else:
                st.session_state["playing"] = False
        st.session_state["replay_idx"] = idx
        if n_steps > 1:
            st.select_slider("Thời điểm", options=list(range(n_steps)), key="replay_idx",
                             format_func=lambda i: day_ts[i].strftime("%H:%M"))
        st.segmented_control("Tốc độ phát", list(SPEEDS), default="1x", required=True, key="speed", width="stretch",
                             help="1x: mỗi nhịp sang 1 lần chụp (1 phút); 2x: sang 2 lần chụp; 4x: sang 4 lần chụp. "
                                  "Bản đồ nhiệt chỉ hiện các bước dừng lại; bảng và biểu đồ khác vẫn tính đủ mọi lần chụp từ đầu phiên đến thời điểm đang xem.")
        st.toggle("Hiệu ứng lật", value=True, key="flip_on", help="Tắt thì ô đổi màu ngay, không lật.")
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

ranking, alerts, alert_counts = liquidity_ranking(view)

# Các con số dùng ở nhiều chỗ được tính một lần ở đây.
n_alerts = len(alerts)
n_events = int(alerts["alert_start"].sum())
n_alert_syms = alerts["symbol"].nunique()
weakest = ranking.iloc[0]
top_alert_sym = alert_counts.idxmax() if len(alert_counts) else None
top_alert_n = int(alert_counts.max()) if len(alert_counts) else 0
# Chỉ lấy các lần chụp cảnh báo DO SPREAD: cảnh báo độ sâu mỏng có spread_ratio bình thường (~1) nên không nói được "spread gấp mấy lần".
top_alert_ratio = (alerts.loc[(alerts["symbol"] == top_alert_sym) & alerts["alert_type"].str.contains("Spread"),
                              "spread_ratio"].max() if n_alerts else np.nan)

# ---------- đầu trang ----------
is_sim = source == SRC_SAMPLE
last_ts = cut_ts if cut_ts is not None else all_df["ts"].max()

if n_events:
    finding = (f'<span class="neg">{n_events} đợt cảnh báo ở {n_alert_syms} mã.</span> '
               f"{top_alert_sym} bị cảnh báo nhiều nhất ({top_alert_n} đợt)")
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

# Phiên lấy từ SSI: nói rõ nguồn, vì khác NEO ở mấy điểm (xem shared.load_source).
view_ssi = sorted(d for d in view["ts"].dt.date.unique() if d in ssi_days)
if view_ssi:
    st.html('<div class="notice"><b>Nguồn SSI:</b> phiên ' + ", ".join(f"{d:%d/%m}" for d in view_ssi)
            + " không có dữ liệu NEO (bộ ghi NEO không chạy đủ phiên) nên dùng sổ lệnh 3 mức giá của SSI, lấy mẫu mỗi phút "
            "như NEO. SSI không có giá khớp và tổng khối lượng khớp nên không tính tỷ lệ hấp thụ và cờ không khớp cho phiên này. "
            "Phiên SSI không được dùng làm mốc so sánh cho các phiên NEO, nên số của các phiên NEO không đổi; bản thân "
            "phiên SSI được so với mốc là các phiên NEO trước đó. Đối chiếu ngày 11/11 (có cả hai nguồn): giá 3 mức khớp NEO 99,8%, "
            "khối lượng 3 mức khớp 96 đến 99%.</div>")

# Phiên chưa có baseline (chưa đủ phiên trước cùng khung giờ): nói rõ thay vì để người xem tưởng là "không bất thường".
no_base_days = sorted(d for d, g in view.groupby(view["ts"].dt.date) if g["n_hist"].isna().all())
if no_base_days:
    st.html('<div class="notice">Phiên ' + ", ".join(f"{d:%d/%m}" for d in no_base_days)
            + f" ở trạng thái Chưa đủ dữ liệu: cần ít nhất {MIN_BASELINE} phiên trước và {MIN_OBS_BUCKET} lần chụp hợp lệ cùng khung giờ "
            "(đặt ở config.toml), nên chưa có cảnh báo và điểm LRS. "
            "Xếp hạng thanh khoản và biểu đồ spread, độ sâu vẫn dùng được.</div>")

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

alert_sub = (f'{vn(n_alerts)} lần chụp · nhiều nhất <span class="neg">{top_alert_sym} ({top_alert_n})</span>'
             if n_events else "không có mã nào vượt ngưỡng")
st.html(
    '<div class="kpis">'
    f'<div class="kpi lead"><div class="l">Đợt cảnh báo trong kỳ</div><div class="v">{n_events}</div>'
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

# ---------- bản đồ nhiệt thẻ lật (chỉ khi phát lại một phiên) ----------
if mode == MODE_REPLAY:
    i_now = st.session_state["replay_idx"]
    flip_syms = sorted(picked)
    cur_state = grid_state(analyzed, flip_syms, cut_ts)
    GRID_W, GRID_H = 100.0, 46.0   # tỷ lệ khung bản đồ nhiệt (rộng : cao)
    layout = treemap_layout(tile_weights(analyzed, flip_syms, replay_day), GRID_W, GRID_H)
    with st.container(border=True, key="panel_flipgrid"):
        st.subheader(f"Bản đồ nhiệt thẻ lật · {cut_ts:%H:%M}", anchor=False)
        st.caption("Mỗi ô là một mã, hiện điểm rủi ro thanh khoản LRS tại lần chụp đang xem. Diện tích ô theo độ sâu sổ lệnh "
                   "trung vị của mã trong cả phiên (cố định khi phát). Nền: xanh nhạt = dễ giao dịch hơn thường lệ, xám = bình "
                   "thường, cam rồi đỏ = khó hơn (LRS càng cao càng rủi ro). Viền cam đậm = mức Chú ý, viền đỏ đậm = mức Cao "
                   "(theo ngưỡng của Radar). Viền nét đứt = chưa đủ dữ liệu so với các phiên trước. Sang lần chụp kế tiếp, "
                   "ô nào đổi điểm sẽ lật. Bấm vào ô để mở hồ sơ mã.")
        # Component giữ nguyên các ô giữa các nhịp; JS so với trạng thái đang hiện và chỉ lật ô nào đổi.
        flip_treemap(cur_state, layout, reset_key=f"{replay_day}|{','.join(flip_syms)}", step=i_now,
                     width=GRID_W, height=GRID_H, flip_ms=450, link="ma", animate=st.session_state.get("flip_on", True))

# ---------- xếp hạng + cảnh báo ----------
TABLE_H = 438
left, right = st.columns([7, 5], gap="small")
with left, st.container(border=True, key="panel_rank"):
    st.subheader("Xếp hạng thanh khoản", anchor=False,
                 help="Điểm 0-100 so sánh giữa các mã đang chọn: spread trung bình thấp tính bằng bps (40%), "
                      "độ sâu lớn (40%), ít lệch mua/bán (20%). LRS là điểm rủi ro ở lần chụp mới nhất của từng mã.")
    st.caption("Mã yếu nhất ở trên cùng. Chọn ô đầu dòng để xem diễn biến của mã đó bên dưới.")
    table = ranking.assign(depth_m=ranking["depth_value"] / 1e6)[
        ["symbol", "score", "spread_bps_mean", "spread_ticks", "depth_m", "lrs", "lrs_tier", "alerts"]
    ].reset_index(drop=True)
    rank_syms = table["symbol"].tolist()
    # Khóa bảng đổi theo thứ tự xếp hạng, để dấu chọn không nằm nhầm dòng khi thứ hạng thay đổi.
    rank_key = "rank_tbl_" + format(zlib.crc32("|".join(rank_syms).encode()), "x")
    st.dataframe(
        table.style.map(tier_style, subset=["lrs_tier"]).format(
            {"spread_ticks": "{:.2f}", "spread_bps_mean": "{:.1f}", "depth_m": "{:,.0f}", "lrs": "{:+.2f}"},
            decimal=",", thousands=".", na_rep="–"),
        hide_index=True,
        height=TABLE_H,
        key=rank_key,
        on_select=partial(_pick_from_ranking, rank_key, rank_syms),
        selection_mode="single-row",
        alt="Bảng xếp hạng thanh khoản các mã VN30",
        column_config={
            "symbol": st.column_config.TextColumn("Mã", width=50, pinned=True),
            "score": st.column_config.ProgressColumn("Điểm", min_value=0, max_value=100, format="%.0f",
                                                     color="#8a8a8a", width=64),
            "spread_bps_mean": st.column_config.NumberColumn(
                "Spread bps", width=76,
                help="Spread tương đối trung bình: chi phí mua rồi bán ngay (1 bps = 0,01%). Dùng để chấm điểm. "
                     "Mã giá thấp thường có bps cao vì bước giá chiếm tỷ lệ lớn trong giá."),
            "spread_ticks": st.column_config.NumberColumn(
                "Bước giá", width=70,
                help="Spread trung bình tính bằng số bước giá; 1,00 là hẹp nhất có thể. Chỉ để tham khảo."),
            "depth_m": st.column_config.NumberColumn("Độ sâu (tr)", width=80,
                                                     help="Độ sâu 3 mức giá trung vị, triệu đồng"),
            "lrs": st.column_config.NumberColumn("LRS", width=54,
                                                 help="Điểm rủi ro thanh khoản ở lần chụp mới nhất. Cao hơn là rủi ro hơn."),
            "lrs_tier": st.column_config.TextColumn("Mức", width=112),
            "alerts": st.column_config.NumberColumn("Đợt CB", format="%d", width=60, help="Số đợt cảnh báo trong kỳ"),
        },
    )
with right, st.container(border=True, key="panel_alerts"):
    st.subheader("Cảnh báo gần nhất", anchor=False,
                 help="Spread mở rộng hoặc độ sâu mỏng bất thường so với lịch sử của chính mã.")
    shown_n = min(40, n_alerts)
    if alerts.empty:
        st.caption("Không có cảnh báo trong khoảng đã chọn. Thử hạ ngưỡng z-score ở thanh bên.")
    else:
        st.caption(f"{n_events} đợt cảnh báo ({vn(n_alerts)} lần chụp) trong kỳ, hiện {shown_n} lần chụp gần nhất.")
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
                                                              help="Spread (theo bước giá) so với trung vị của mã ở cùng khung giờ các phiên trước"),
                "alert_type": st.column_config.TextColumn(
                    "Loại", help="Spread rộng: chênh lệch mua-bán giãn ra. Sổ mỏng: độ sâu 3 mức rút đi. "
                                 "'không khớp': độ sâu rút mỏng mà gần như không có giao dịch khớp."),
            },
        )

# ---------- bản đồ nhiệt ----------
hm = view.copy()
hm["ratio"] = hm["rel_spread_bps"] / hm.groupby("symbol")["rel_spread_bps"].transform("median")
# Khung 30 phút tính từ đầu mỗi buổi khớp lệnh liên tục (9:15, 9:45, ... 13:00, ...), trùng khung của baseline cảnh báo.
hm["bucket"] = tod_bucket(hm["ts"])
pivot = hm.pivot_table(index="symbol", columns="bucket", values="ratio", aggfunc="mean")
pivot = pivot.reindex(index=ranking["symbol"].tolist(), columns=sorted(pivot.columns))
pivot.columns = [bucket_label(b) for b in pivot.columns]

with st.container(border=True, key="panel_heatmap"):
    st.subheader("Chi phí giao dịch theo giờ", anchor=False)
    st.caption("Spread trung bình mỗi khung 30 phút (ghi giờ bắt đầu khung), tính bằng số lần so với mức trung vị của chính mã. "
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
    st.plotly_chart(fig_hm, config=CHART_CONFIG, theme=None,
                    alt="Bản đồ nhiệt spread theo mã và khung 30 phút")

# ---------- chi tiết một mã ----------
sym_list = ranking["symbol"].tolist()
if st.session_state.get("sym") not in sym_list:  # mở sẵn mã nhiều cảnh báo nhất
    st.session_state["sym"] = sym_list[int(ranking["alerts"].values.argmax())] if ranking["alerts"].max() > 0 else sym_list[0]

with st.container(border=True, key="panel_detail"):
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        st.subheader("Diễn biến trong phiên", anchor=False,
                     help="Spread, độ sâu và điểm rủi ro LRS của một mã; dải tô đỏ nhạt là các đợt cảnh báo.")
        sym = st.selectbox("Mã", sym_list, key="sym", width=140)
        st.page_link("stock.py", label="Mở hồ sơ mã", icon=":material/open_in_new:", query_params={"ma": sym})
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
        st.caption(intraday_caption(sym, day, one))
        fig = intraday_figure(one)
        st.plotly_chart(fig, config=CHART_CONFIG, theme=None,
                        alt=f"Diễn biến spread, độ sâu và LRS của {sym} trong phiên {day:%d/%m/%Y}")
        if one["lrs_watch"].isna().all():
            st.caption(f"Chưa đủ dữ liệu để tính ngưỡng LRS (cần ít nhất {MIN_OBS_PAST} điểm LRS trước thời điểm xét).")

# ---------- phương pháp và giới hạn ----------
with st.expander("Phương pháp tính và giới hạn", icon=":material/menu_book:"):
    st.markdown(
        f"""
**Dữ liệu đầu vào.** Chỉ dùng các lần chụp trong phiên khớp lệnh liên tục (09:15-11:30 và 13:00-14:30). Các phiên
ATO, ATC và nghỉ trưa bị loại vì sổ lệnh lúc đó không phản ánh thanh khoản liên tục.

**Chỉ số từ sổ lệnh 3 mức giá**
- Spread tương đối (bps) = (giá bán tốt nhất − giá mua tốt nhất) / giá giữa × 10.000.
- Spread theo bước giá = (giá bán tốt nhất − giá mua tốt nhất) / bước giá HOSE (10đ dưới 10.000đ, 50đ từ 10.000đ
  đến 49.950đ, 100đ từ 50.000đ). 1 bước giá là hẹp nhất có thể.
- Độ sâu = tổng (giá × khối lượng) của 3 mức mua và 3 mức bán.
- Lệch mua/bán = (khối lượng mua − khối lượng bán) / tổng, từ −1 đến +1.

**Điểm thanh khoản (0-100)** là xếp hạng tương đối giữa các mã đang chọn: spread trung bình tính bằng bps thấp (40%),
độ sâu lớn (40%), ít lệch mua/bán (20%). Trọng số là giả định ban đầu, chưa được hiệu chỉnh.
Điểm dùng spread bps vì đó là chi phí thật khi mua rồi bán. Chấm theo số bước giá cho kết quả gần như ngược với chi phí:
mã giá cao (VIC ~240.000đ) có bước giá nhỏ so với giá (1 bước giá chỉ ~4 bps) nên dù spread trung bình khoảng 2 bước giá
vẫn chỉ tốn ~8 bps (trung vị ~4 bps), còn mã giá thấp (SHB ~10.700đ) luôn đúng 1 bước giá nhưng tốn ~47 bps (số liệu
28/10 đến 11/11/2026). Giới hạn: mã giá thấp luôn có bps cao do bước giá, nên điểm
cho biết mua bán *tốn kém* đến đâu, không cho biết sổ lệnh có "căng" hay không. Cảnh báo bên dưới vẫn dùng số bước giá
vì mỗi mã chỉ so với chính nó.

**Mức thường lệ (baseline)** của một mã ở một khung giờ (9:15-9:30 là khung riêng, rồi 9:30, 10:00, ... và 13:00, 13:30, ...
mỗi khung 30 phút) là mọi lần chụp của chính mã đó trong cùng khung giờ ở tối đa 10 phiên *trước* phiên đang xét
(cần ít nhất {MIN_BASELINE} phiên và {MIN_OBS_BUCKET} lần chụp hợp lệ, nếu không thì ghi "Chưa đủ dữ liệu"). Sáng chỉ so với
sáng, vì thanh khoản có nhịp lặp lại trong ngày: trên dữ liệu VN30 thật, độ sâu đầu phiên chỉ bằng khoảng 1/3 cuối
phiên. Phiên hiện tại và tương lai không được dùng.

**Điểm rủi ro LRS** = w₁·Z(spread) − w₂·Z(độ sâu) + w₃·Z(|lệch mua/bán|), so với baseline cùng khung giờ. Z của độ sâu
(logarit) và của |lệch mua/bán| là z bền vững = (x − trung vị) / (1,4826 × MAD) (Leys và cộng sự, 2013). Z của spread
lấy từ thứ hạng phần trăm của spread (theo bước giá) trong baseline, vì spread phần lớn đúng 1 bước giá (khoảng 85% lần
chụp) nên MAD thường bằng 0. Cao hơn là rủi ro hơn. Ngưỡng "Chú ý" và "Cao" tại mỗi thời điểm là phân vị
95% và 99% của mọi điểm LRS có *trước* thời điểm đó (cần ít nhất 300 điểm), nên không dùng dữ liệu tương lai và
ngưỡng thay đổi dần theo thời gian. Vì là phân vị nên về lâu dài khoảng 1% lần chụp ở mức "Cao" dù thị trường yên;
mức này để theo dõi xu hướng, còn danh sách cảnh báo dựa trên điều kiện bên dưới.

**Cảnh báo** khi (a) *spread mở rộng*: spread ≥ 2 bước giá, ≥ 2 lần trung vị baseline và chỉ ≤ 5% lần chụp cùng
khung giờ trước đây rộng bằng hoặc hơn; hoặc (b) *độ sâu mỏng*: z độ sâu ≤ −ngưỡng và độ sâu ≤ 0,4 lần trung vị
baseline. Điều kiện phải đúng ở ít nhất **2 lần chụp liên tiếp** trong cùng buổi mới thành một *đợt cảnh báo*;
cảnh báo được gắn từ lần chụp thứ hai nên vẫn không nhìn trước tương lai. Mức "Cao": z độ sâu ≤ −(ngưỡng + 1,5)
hoặc spread ≥ 3 lần mức thường lệ. Ghi chú "Mỏng, không khớp" nghĩa là độ sâu rút mỏng trong khi gần như không có
khối lượng khớp; đây chỉ là dấu hiệu, không chứng minh có hủy lệnh ảo hay thao túng.

**Phát lại** dựng lại một phiên đã ghi từng bước. Mọi phép tính, kể cả ngưỡng LRS, chỉ dùng dữ liệu đến thời
điểm đang xem.

**Giới hạn**
- Các phiên đầu (chưa đủ {MIN_BASELINE} phiên trước) chưa có baseline nên ghi "Chưa đủ dữ liệu", không có cảnh báo và điểm LRS. Khi mới có vài phiên, MAD chủ yếu phản ánh
  dao động *trong* phiên, chưa phản ánh dao động *giữa các* phiên, nên cảnh báo có thể nhiều hơn; sẽ ổn định dần khi
  ghi thêm phiên.
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
