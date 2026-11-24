"""Trang "Bộ lọc cổ phiếu VN30": Radar thanh khoản làm cổng, rồi xếp hạng theo dòng tiền nước ngoài và động lượng.

Logic nằm ở analytics/screener.py (thuần pandas, có kiểm thử); số liệu dựng ở shared.screen_for_day để Chi tiết mã và
thanh bên dùng cùng một kết quả. Trang này chỉ chọn tham số và trình bày.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from analytics.screener import sample_warning  # noqa: E402
from data.special_days import describe  # noqa: E402
from shared import GATE_MIN_SCORE, analyzed_data, current_source, screen_for_day  # noqa: E402
from theme import (BORDER, CHART_CONFIG, GRID, HUE, INK, MUTED, WARN, arrow_pct, badge_style, base_layout, sign_color,  # noqa: E402
                   vn)

GATE_BADGE = {"Đạt": "ok", "Chú ý": "warn", "Chưa đánh giá": "muted", "Loại": "faint"}
GATE_COLOR = {"Đạt": HUE, "Chú ý": WARN, "Chưa đánh giá": MUTED, "Loại": "#b5bac1"}

source = current_source()
st.title("Bộ lọc cổ phiếu VN30", anchor=False)
st.caption("Dành cho nhà đầu tư cá nhân: lọc ra mã VN30 mua bán dễ (cổng thanh khoản lấy từ Radar), rồi xếp theo dòng tiền "
           "nước ngoài và động lượng giá so với VN30. Công cụ sàng lọc để so sánh, không dự báo giá.")
if source is None:
    st.error("Chưa có dữ liệu. Ghi dữ liệu NEO bằng `python scripts/run_live.py`.",
             title="Chưa có dữ liệu")
    st.stop()

_an = analyzed_data(source)
# Bộ lọc cần giá khớp, nước ngoài và bảng giá của NEO; ngày chỉ có sổ lệnh SSI (không có các trường này) không đưa vào.
days = sorted(_an.loc[_an["src"] == "NEO", "ts"].dt.date.unique(), reverse=True)
if not days:
    st.info("Chưa có lần chụp sổ lệnh nào trong phiên khớp lệnh liên tục.")
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    day = st.selectbox("Phiên", days, index=0, width=160, format_func=lambda d: d.strftime("%d/%m/%Y"))
    min_score = st.slider("Cổng: loại mã có điểm thanh khoản từ mức này trở xuống", 0.0, 66.7, GATE_MIN_SCORE, 0.1,
                          format="%.1f", width=320, help="Mặc định 33,3 là mốc \"Yếu\" của điểm thanh khoản ở Radar.")
    probe = screen_for_day(source, day, min_score, "intraday")
    horizon = st.segmented_control(
        "Động lượng", ["intraday", "5d"], default="intraday", required=True,
        format_func=lambda h: "Trong phiên" if h == "intraday" else "5 phiên",
        help="5 phiên cần giá đóng cửa hợp lệ (bảng giá chụp từ 14:45, đã có ATC) của phiên này và của phiên cách đó "
             "5 phiên giao dịch; lịch phiên lấy từ SSI (python scripts/fetch_ssi_history.py).")

if probe is None:
    st.info("Phiên này không có sổ lệnh theo phút trong phiên khớp lệnh liên tục.")
    st.stop()
if horizon == "5d" and not probe["mom5_ok"]:
    st.html('<div class="notice">Chưa đủ dữ liệu để tính động lượng 5 phiên: cần bảng giá chụp từ 14:45 của phiên này và của '
            "phiên cách đó 5 phiên giao dịch, cùng lịch phiên từ SSI. Đang dùng động lượng trong phiên.</div>")
    horizon = "intraday"
res = screen_for_day(source, day, min_score, horizon) if horizon != "intraday" else probe
r = res["result"]
ctx = res["context"]
_sp = _an.loc[_an["ts"].dt.date == day, "special_day"]
if len(_sp) and _sp.iloc[0]:
    st.html(f'<div class="notice">Phiên {day:%d/%m} là ngày đặc biệt ({describe(_sp.iloc[0])}): chỉ số và cảnh báo vẫn tính như thường, '
            "nhưng thanh khoản hôm đó có thể khác thường nên cần đọc kết quả thận trọng hơn.</div>")

# ---------- bối cảnh thị trường ----------
st.html(f'<div class="notice"><b>Bối cảnh thị trường.</b> {ctx["summary"]}</div>')

passed = r[r["gate"] != "Loại"]
top = passed.dropna(subset=["screen_score"]).head(1)
n_gate = r["gate"].value_counts()
mom_col = "rel_mom_5" if "rank_rel_mom_5" in r else ("mom_rel" if "rank_mom_rel" in r else "mom_intraday")
mom_label = {"rel_mom_5": "Động lượng 5 phiên so VN30", "mom_rel": "Động lượng trong phiên so VN30",
             "mom_intraday": "Động lượng trong phiên"}[mom_col]
st.html(
    '<div class="kpis">'
    f'<div class="kpi lead"><div class="l">Qua cổng thanh khoản</div><div class="v">{n_gate.get("Đạt", 0) + n_gate.get("Chú ý", 0)}'
    f'<small>/{len(r)} mã</small></div><div class="s">{n_gate.get("Đạt", 0)} Đạt · {n_gate.get("Chú ý", 0)} Chú ý · '
    f'{n_gate.get("Chưa đánh giá", 0)} Chưa đánh giá · {n_gate.get("Loại", 0)} Loại</div></div>'
    f'<div class="kpi"><div class="l">Điểm bộ lọc cao nhất</div><div class="v">'
    + (f'{top["symbol"].iloc[0]}<small>{vn(top["screen_score"].iloc[0], 0)}/100</small>' if not top.empty else "–")
    + '</div><div class="s">trong các mã qua cổng</div></div>'
    f'<div class="kpi"><div class="l">VN30 trong phiên</div><div class="v">'
    + (f'{"+" if res["vn30_pct"] > 0 else ""}{vn(res["vn30_pct"], 2)}<small>%</small>' if res["vn30_pct"] is not None else "–")
    + '</div><div class="s">mốc để đo động lượng tương đối</div></div>'
    f'<div class="kpi"><div class="l">Khối ngoại ròng rổ VN30</div><div class="v">'
    + (f'{"+" if ctx["vn30_foreign_net"] > 0 else ""}{vn(ctx["vn30_foreign_net"] / 1e9, 1)}<small>tỷ đ</small>'
       if ctx["vn30_foreign_net"] is not None else "–")
    + "</div><div class=\"s\">cộng 30 mã, lũy kế trong ngày</div></div>"
    "</div>"
)
_warn = sample_warning(r)
if _warn:
    st.html(f'<div class="notice">{_warn}</div>')
snap_note = (f"Giá và dòng tiền lấy từ bảng giá lúc {res['snap_ts']:%H:%M}"
             + ("" if res["snap_kind"] != "board" or res["snap_ts"].time() >= pd.Timestamp("14:45").time()
                else " (trước phiên ATC)")
             if res["snap_kind"] == "board" else
             f"Giá và dòng tiền lấy từ lần chụp sổ lệnh cuối lúc {res['snap_ts']:%H:%M} (chưa gồm phiên ATC)")
st.caption(snap_note + ".")

# ---------- bảng xếp hạng ----------
left, right = st.columns([7, 5], gap="small")
with left, st.container(border=True, key="panel_screen"):
    st.subheader("Xếp hạng bộ lọc", anchor=False,
                 help="Điểm = trung bình thứ hạng phần trăm (0-100) của dòng tiền nước ngoài và động lượng, chỉ xếp trong "
                      "các mã qua cổng thanh khoản. Trọng số bằng nhau.")
    st.caption("Chọn một dòng để mở hồ sơ chi tiết của mã. Mã Chưa đánh giá, rồi mã bị Loại, nằm cuối bảng, kèm lý do.")
    rank_mom = f"rank_{mom_col}"
    table = pd.DataFrame({
        "symbol": r["symbol"], "flag": r["gate"].map(lambda g: "⚠" if g == "Chú ý" else ""), "gate": r["gate"],
        "score": r["screen_score"],
        "f_rank": r.get("rank_foreign_ratio"), "f_ratio": r["foreign_ratio"] * 100,
        "m_rank": r.get(rank_mom), "m_val": r[mom_col] * 100,
        "liq": r["liq_score"], "alerts": r["alerts"], "reason": r["gate_reason"],
    })
    event = st.dataframe(
        table.style.format({"score": "{:.0f}", "f_rank": "{:.0f}", "f_ratio": arrow_pct(1), "m_rank": "{:.0f}",
                            "m_val": arrow_pct(2), "liq": "{:.0f}"}, decimal=",", thousands=".", na_rep="–")
             .map(lambda g: badge_style(GATE_BADGE.get(g, "muted")), subset=["gate"])
             .map(sign_color, subset=["f_ratio", "m_val"]),
        hide_index=True, height=438, key=f"screen_tbl_{day}_{min_score}_{horizon}", on_select="rerun",
        selection_mode="single-row", alt="Bảng xếp hạng bộ lọc cổ phiếu VN30",
        column_config={
            "symbol": st.column_config.TextColumn("Mã", width=50, pinned=True),
            "flag": st.column_config.TextColumn("", width=28, help="⚠ = có đợt cảnh báo thanh khoản (nhãn Chú ý); vẫn được xếp hạng cùng mã Đạt"),
            "gate": st.column_config.TextColumn("Cổng", width=100),
            "score": st.column_config.ProgressColumn("Điểm", min_value=0, max_value=100, format="%.0f", width=70,
                                                     color="#1d5fbf"),
            "f_rank": st.column_config.NumberColumn("Hạng NN", width=64, help="Thứ hạng phần trăm của dòng tiền nước ngoài trong nhóm qua cổng"),
            "f_ratio": st.column_config.NumberColumn("NN ròng/GTGD", width=90, help="Giá trị khối ngoại mua ròng chia tổng giá trị giao dịch của mã"),
            "m_rank": st.column_config.NumberColumn("Hạng ĐL", width=64, help="Thứ hạng phần trăm của động lượng trong nhóm qua cổng"),
            "m_val": st.column_config.NumberColumn("Động lượng", width=86, help=mom_label),
            "liq": st.column_config.NumberColumn("Thanh khoản", width=80, help="Điểm thanh khoản 0-100 (cùng số với Radar)"),
            "alerts": st.column_config.NumberColumn("Đợt CB", width=60, format="%d"),
            "reason": st.column_config.TextColumn("Lý do cổng"),
        },
    )
    sel = event.selection.rows if event is not None else []
    if sel:
        st.switch_page("stock.py", query_params={"ma": str(table["symbol"].iloc[sel[0]])})

with right, st.container(border=True, key="panel_map"):
    st.subheader("Dòng tiền ngoại và động lượng", anchor=False,
                 help="Mỗi chấm là một mã. Góc trên bên phải: khối ngoại mua ròng và giá mạnh hơn VN30.")
    pts = table.dropna(subset=["f_ratio", "m_val"])
    if pts.empty:
        st.caption("Chưa đủ dữ liệu để vẽ.")
    else:
        fig = go.Figure()
        for g in ("Loại", "Chưa đánh giá", "Chú ý", "Đạt"):
            d = pts[pts["gate"] == g]
            if d.empty:
                continue
            fig.add_trace(go.Scatter(
                x=d["m_val"], y=d["f_ratio"], mode="markers+text", text=d["symbol"], textposition="top center",
                textfont=dict(size=10, color=MUTED if g in ("Loại", "Chưa đánh giá") else INK), name=g,
                marker=dict(size=9, color=GATE_COLOR[g], line=dict(color="#ffffff", width=1)),
                hovertemplate="%{text}<br>Động lượng %{x:+.2f}%<br>NN ròng/GTGD %{y:+.1f}%<extra>" + g + "</extra>"))
        fig.add_hline(y=0, line=dict(color=BORDER, width=1))
        fig.add_vline(x=0, line=dict(color=BORDER, width=1))
        fig.update_xaxes(title=dict(text=mom_label + " (%)", font=dict(size=11, color=MUTED)), gridcolor=GRID,
                         zeroline=False, ticksuffix="%")
        fig.update_yaxes(title=dict(text="NN ròng / giá trị GD (%)", font=dict(size=11, color=MUTED)), gridcolor=GRID,
                         zeroline=False, ticksuffix="%")
        fig.update_xaxes(automargin=True, tickfont=dict(size=11, color=MUTED))
        fig.update_yaxes(automargin=True, tickfont=dict(size=11, color=MUTED))
        base_layout(fig, 420)
        fig.update_layout(legend=dict(orientation="h", y=1.1, x=0), margin=dict(l=56, r=12, t=40, b=48))
        st.plotly_chart(fig, config=CHART_CONFIG, theme=None,
                        alt="Biểu đồ phân tán động lượng và dòng tiền nước ngoài theo mã")

with st.expander("Phương pháp và giới hạn", icon=":material/menu_book:"):
    st.markdown(
        f"""
**1. Cổng thanh khoản** (lấy từ Radar, cùng số): *Loại* nếu điểm thanh khoản trong phiên từ {vn(min_score, 1)} trở xuống
(mặc định 33,3 là mốc "Yếu" của Radar); *Chưa đánh giá* nếu mã chưa có mốc nền (chưa đủ phiên trước cùng khung giờ, xem lý do ở bảng),
xếp sau mã qua cổng và trước mã Loại, không có điểm; *Chú ý* nếu có ít nhất một đợt cảnh báo thanh khoản trong phiên (có dấu ⚠); còn lại *Đạt*.
Mã *Chú ý* VẪN được chấm điểm và xếp hạng cùng mã *Đạt*; chỉ đợt cảnh báo mới quyết định nhãn Chú ý, còn điểm LRS chỉ hiện ở cột lý do
(bật `gate.use_lrs` ở config.toml thì LRS cũng đổi nhãn). Thứ hạng phần trăm của hai yếu tố chỉ tính trong tập mã qua cổng; tập dưới
10 mã thì trang cảnh báo mẫu nhỏ.
Lý do: mã khó mua bán thì chi phí vào/ra lệnh cao, dù các yếu tố khác tốt.

**2. Yếu tố xếp hạng** (chỉ tính cho mã qua cổng):
- Dòng tiền nước ngoài = giá trị khối ngoại mua ròng / tổng giá trị giao dịch của mã trong ngày.
- Động lượng trong phiên = giá khớp / giá tham chiếu − 1, trừ đi % thay đổi của VN30 cùng thời điểm (so với thị trường,
  nên mã chỉ giảm theo thị trường không bị phạt). Động lượng 5 phiên dùng giá đóng cửa hợp lệ (bảng giá chụp từ 14:45).

**3. Điểm bộ lọc** = trung bình thứ hạng phần trăm (0-100) của hai yếu tố, trọng số bằng nhau; không đặt trọng số tùy ý.
Mã thiếu một yếu tố được tính trên yếu tố còn lại.

**Giới hạn**
- Chưa kiểm chứng điểm cao có đi kèm lợi suất ngày sau tốt hơn hay không: cần nhiều phiên hơn. Đây là công cụ so sánh,
  không dự báo giá, không phải khuyến nghị mua bán.
- Điểm thanh khoản là xếp hạng *tương đối* giữa 30 mã, nên luôn có mã bị Loại kể cả khi cả thị trường thanh khoản tốt
  (với ngưỡng 33,3, trên dữ liệu 28/10 đến 20/11/2026 mỗi phiên loại từ 1 đến 6 trong 30 mã, thường khoảng 4: không cố định 10 mã vì điểm là tổng có trọng số
  của ba thứ hạng). Cổng trả lời "mã nào kém nhất trong VN30", chưa phải "mã nào kém tuyệt đối".
- Nhãn *Chú ý* khá rộng: từ 5/11 trở đi thường 7 đến 19 trong 30 mã mỗi phiên có ít nhất một đợt cảnh báo, nên nhãn này chưa phân biệt mã tốt.
- Điểm thanh khoản đo chi phí chứ không đo độ "căng" của sổ lệnh, spread đo là spread chào, mốc nền còn ít phiên: xem mục Giới hạn ở trang Radar.
- Bảng giá chụp trước 14:45 chưa gồm phiên ATC; trang ghi rõ giờ chụp.
- Dòng tiền nước ngoài và giá trị giao dịch là số lũy kế NEO trả tại thời điểm chụp.
        """
    )
st.html('<p class="note">Đây là công cụ phân tích học thuật phục vụ đồ án, không phải khuyến nghị đầu tư. '
        "Ứng dụng chỉ đọc dữ liệu thị trường, không gửi, sửa hay hủy lệnh giao dịch.</p>")
