"""Trang "Bộ lọc cổ phiếu HOSE": cổng thanh khoản theo giá trị khớp, rồi xếp hạng động lượng 6-1 của các mã qua cổng.

Logic nằm ở analytics/universe.py (thuần pandas, có kiểm thử); số liệu dựng ở shared.hose_universe để mọi trang dùng cùng một kết quả.
Trang này chỉ chọn cách hiển thị và trình bày. Radar thanh khoản vẫn chỉ cho VN30; ở đây mã VN30 có thêm cột "Radar" để tham khảo.
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

from analytics import universe as U  # noqa: E402
from shared import analyzed_data, current_source, hose_universe, liquidity_ranking  # noqa: E402
from theme import (BORDER, CHART_CONFIG, GRID, HUE, INK, MUTED, PANEL, arrow_pct, badge_style, base_layout, sign_color,  # noqa: E402
                   how_to_read, vn)

STATUS_BADGE = {U.PASS: "ok", U.NO_HISTORY: "muted", U.STALE: "muted", U.FAIL: "faint", U.FEW: "faint", U.MISSING: "faint"}
VIEWS = ["Qua cổng thanh khoản", "Có xếp hạng", "Tất cả"]


@st.cache_data(show_spinner=False)
def _radar_tiers(source: str, version: float) -> pd.DataFrame:
    """Mức LRS lần chụp cuối của phiên NEO mới nhất cho mã VN30 (Radar chỉ có VN30); rỗng nếu chưa có sổ lệnh."""
    an = analyzed_data(source)
    an = an[an["src"] == "NEO"]
    if an.empty:
        return pd.DataFrame(columns=["symbol", "lrs_tier"])
    last = an["ts"].dt.date.max()
    ranking, _, _ = liquidity_ranking(an[an["ts"].dt.date == last])
    return ranking[["symbol", "lrs_tier"]]


st.title("Bộ lọc cổ phiếu HOSE", anchor=False)
st.caption("Dành cho nhà đầu tư cá nhân: lọc ra cổ phiếu HOSE đủ thanh khoản để vào/ra vị thế của bạn (theo giá trị khớp mỗi ngày), "
           "rồi xếp theo động lượng giá 6 tháng bỏ tháng gần nhất. Công cụ sàng lọc để so sánh, không dự báo giá.")
how_to_read(
    "**Bước 1, cổng thanh khoản:** trung vị giá trị khớp mỗi ngày (ngày không giao dịch tính là 0) phải từ ngưỡng trở lên. "
    "Nhãn: *Đạt*, *Không đạt thanh khoản*, *Ít giao dịch* (ít ngày có giao dịch), *Thiếu dữ liệu* (không có dòng nào trong các ngày đủ).",
    "**Bước 2, xếp hạng động lượng** chỉ cho mã *Đạt*: lợi suất từ 6 tháng trước đến 1 tháng trước (bỏ tháng gần nhất), thứ hạng 0-100. "
    "Mã *Đạt* mà chưa tính được thì hiện *Chưa đủ lịch sử* hoặc *Dữ liệu cũ*, vẫn nằm trong bảng nhưng không có xếp hạng.",
    "**Cờ:** *Sát ngưỡng* (mã Đạt nhưng trung vị chưa tới 1,25 lần ngưỡng, dễ rớt khi thị trường co lại); *Bước nhảy* (chuỗi giá có ngày đổi hơn 7,5% "
    "giữa hai phiên liền kề, có thể do điều chỉnh giá hoặc chuyển sàn); *NN vượt GT* (khối ngoại mua hoặc bán lớn hơn giá trị khớp, có thể gồm thỏa thuận).",
    "Cột nước ngoài chỉ để tham khảo, chưa vào xếp hạng. Bấm một dòng để mở biểu đồ nến của mã. Đây là công cụ so sánh, không phải khuyến nghị đầu tư.")

source = current_source()
if source is None:
    st.error("Chưa có dữ liệu. Ghi dữ liệu NEO bằng `python scripts/run_live.py`.", title="Chưa có dữ liệu")
    st.stop()

info = hose_universe()
r: pd.DataFrame = info["result"]
if r.empty or not info["days"]:
    st.info("Chưa có ngày nào đủ dữ liệu bảng giá HOSE (cần ảnh chụp sau phiên ATC, từ 14:50) để tính cổng thanh khoản.")
    st.stop()

days, T, ref_day = info["days"], info["threshold"], info["ref_day"]
n = r["status"].value_counts()
n_gate = int((r["gate"] == U.PASS).sum())
n_rank = int(r["mom_rank"].notna().sum())
n_near = int((r["near"] == True).sum())          # noqa: E712  (cột bool có thể là object khi có NaN)
n_no = int(n.get(U.NO_HISTORY, 0) + n.get(U.STALE, 0))
fmt_day = lambda d: pd.Timestamp(d).strftime("%d/%m")  # noqa: E731

tiers = _radar_tiers(source, 0.0)
vn30 = set(tiers["symbol"])
st.html(
    '<div class="kpis">'
    f'<div class="kpi lead"><div class="l">Qua cổng thanh khoản</div><div class="v">{n_gate}<small>/{len(r)} mã HOSE</small></div>'
    f'<div class="s">{n_rank} có xếp hạng · {n_no} chưa tính được động lượng · {n_near} sát ngưỡng</div></div>'
    f'<div class="kpi"><div class="l">Không qua cổng</div><div class="v">{len(r) - n_gate}<small>mã</small></div>'
    f'<div class="s">{n.get(U.FAIL, 0)} không đạt · {n.get(U.FEW, 0)} ít giao dịch · {n.get(U.MISSING, 0)} thiếu dữ liệu</div></div>'
    f'<div class="kpi"><div class="l">Ngưỡng thanh khoản</div><div class="v">{vn(T / 1e9, 1)}<small>tỷ đ/ngày</small></div>'
    '<div class="s">vị thế dự kiến ÷ tỷ lệ tham gia (config.toml)</div></div>'
    f'<div class="kpi"><div class="l">Mẫu giá trị khớp</div><div class="v">{len(days)}<small>ngày đủ</small></div>'
    f'<div class="s">{fmt_day(days[0])} đến {fmt_day(days[-1])}, bảng giá NEO sau ATC</div></div>'
    "</div>")
ref_txt = f"{pd.Timestamp(ref_day):%d/%m/%Y}" if ref_day is not None and not pd.isna(ref_day) else "chưa có"
st.html(f'<div class="notice"><b>Nguồn dữ liệu.</b> Giá trị khớp và nước ngoài: NEO, bảng giá cuối ngày của {len(days)} ngày đủ '
        f'(trong {info["board_days"]} ngày đã ghi, ngày chụp dở dang bị loại). Động lượng: nến ngày <b>SSI</b> (giá điều chỉnh cổ tức), '
        f'ngày tham chiếu chung {ref_txt}, {vn(info["candle_symbols"])} mã có nến.</div>')

view = st.segmented_control("Hiển thị", VIEWS, default=VIEWS[0], required=True, width="content")
shown = r
if view == VIEWS[0]:
    shown = r[r["gate"] == U.PASS]
elif view == VIEWS[1]:
    shown = r[r["mom_rank"].notna()]
shown = shown.merge(tiers, on="symbol", how="left")


def flags(row) -> str:
    out = []
    if row["near"] == True:  # noqa: E712  (so với True để NaN, nghĩa là mã không có thông tin, không bị coi là có cờ)
        out.append("Sát ngưỡng")
    if row["jump"] == True:  # noqa: E712
        out.append("Bước nhảy")
    if row["foreign_over"] == True:  # noqa: E712
        out.append("NN vượt GT")
    return " · ".join(out)


table = pd.DataFrame({
    "symbol": shown["symbol"], "status": shown["status"], "flags": shown.apply(flags, axis=1) if len(shown) else "",
    "rank": shown["mom_rank"], "mom": shown["mom"] * 100, "mom_ref": shown["mom_ref"] * 100,
    "value": shown["median_value"] / 1e9, "days": shown["trade_days"].astype(int).astype(str) + "/" + shown["n_days"].astype(int).astype(str),
    "foreign": shown["foreign_ratio"] * 100, "radar": shown["lrs_tier"].where(shown["symbol"].isin(vn30), None),
    "reason": shown["gate_reason"],
}).reset_index(drop=True)

left, right = st.columns([7, 5], gap="small")
with left, st.container(border=True, key="panel_screen"):
    st.subheader("Xếp hạng bộ lọc", anchor=False,
                 help="Xếp hạng động lượng = thứ hạng phần trăm (0-100) của lợi suất từ 6 tháng trước đến 1 tháng trước, chỉ trong nhóm Đạt. "
                      "Đơn nhân tố, chưa điều chỉnh biến động. Cột nước ngoài và Radar chỉ để tham khảo.")
    st.caption(f"{len(table)} mã đang hiện. Chọn một dòng để mở biểu đồ nến của mã. Mã có nhãn Chưa đủ lịch sử, Dữ liệu cũ và các nhãn không qua cổng nằm sau mã có xếp hạng.")
    if table.empty:
        st.info("Không có mã nào ở cách hiển thị này.")
    else:
        event = st.dataframe(
            table.style.format({"rank": "{:.0f}", "mom": arrow_pct(1), "mom_ref": arrow_pct(1), "value": lambda v: vn(v, 1),
                                "foreign": arrow_pct(1)}, decimal=",", thousands=".", na_rep="–")
                 .map(lambda g: badge_style(STATUS_BADGE.get(g, "muted")), subset=["status"])
                 .map(sign_color, subset=["mom", "mom_ref", "foreign"]),
            hide_index=True, height=438, key=f"screen_tbl_{view}", on_select="rerun", selection_mode="single-row",
            alt="Bảng xếp hạng bộ lọc cổ phiếu HOSE",
            column_config={
                "symbol": st.column_config.TextColumn("Mã", width=50, pinned=True),
                "status": st.column_config.TextColumn("Trạng thái", width=130),
                "flags": st.column_config.TextColumn("Cờ", width=170, help="Sát ngưỡng, Bước nhảy, NN vượt GT: xem mục Cách đọc trang này"),
                "rank": st.column_config.ProgressColumn("Xếp hạng ĐL", min_value=0, max_value=100, format="%.0f", width=100, color=HUE,
                                                        help="Thứ hạng phần trăm của lợi suất 6-1 trong nhóm Đạt (giá SSI điều chỉnh)"),
                "mom": st.column_config.NumberColumn("Lợi suất 6-1", width=90, help="Từ 6 tháng trước đến 1 tháng trước, tính theo mốc lịch"),
                "mom_ref": st.column_config.NumberColumn("3 tháng (tham khảo)", width=110, help="Lợi suất 3 tháng đến ngày tham chiếu; không vào xếp hạng"),
                "value": st.column_config.NumberColumn("GT khớp trung vị (tỷ)", width=130, help="Trung vị giá trị khớp mỗi ngày trong các ngày đủ, ngày không giao dịch tính 0"),
                "days": st.column_config.TextColumn("Ngày GD", width=70, help="Số ngày có giao dịch trên số ngày đủ"),
                "foreign": st.column_config.NumberColumn("NN ròng/GTGD", width=100, help="Tổng ròng nước ngoài chia tổng giá trị khớp cả cửa sổ. Chỉ tham khảo"),
                "radar": st.column_config.TextColumn("Radar (VN30)", width=100, help="Mức LRS lần chụp cuối phiên NEO mới nhất; chỉ có cho mã VN30"),
                "reason": st.column_config.TextColumn("Lý do cổng"),
            },
        )
        sel = event.selection.rows if event is not None else []
        if sel:
            st.switch_page("overview.py", query_params={"xem": str(table["symbol"].iloc[sel[0]])})

with right, st.container(border=True, key="panel_map"):
    st.subheader("Động lượng và thanh khoản", anchor=False,
                 help="Mỗi chấm là một mã Đạt có động lượng. Ngang: lợi suất 6-1. Dọc: trung vị giá trị khớp (thang log). Đường ngang là ngưỡng.")
    pts = r[r["mom_rank"].notna()]
    if pts.empty:
        st.caption("Chưa đủ dữ liệu để vẽ.")
    else:
        top = pts.nlargest(10, "mom_rank")["symbol"]
        lab = pts["symbol"].where(pts["symbol"].isin(top), "")
        fig = go.Figure(go.Scatter(
            x=pts["mom"] * 100, y=pts["median_value"] / 1e9, mode="markers+text", text=lab, textposition="top center",
            textfont=dict(size=10, color=INK), customdata=pts["symbol"],
            marker=dict(size=8, color=HUE, line=dict(color=PANEL, width=1)),
            hovertemplate="%{customdata}<br>Lợi suất 6-1 %{x:+.1f}%<br>GT khớp trung vị %{y:,.1f} tỷ<extra></extra>"))
        fig.add_hline(y=T / 1e9, line=dict(color=BORDER, width=1, dash="dot"))
        fig.add_vline(x=0, line=dict(color=BORDER, width=1))
        fig.update_xaxes(title=dict(text="Lợi suất 6-1 (%)", font=dict(size=11, color=MUTED)), gridcolor=GRID, zeroline=False, ticksuffix="%")
        fig.update_yaxes(title=dict(text="GT khớp trung vị (tỷ đồng, thang log)", font=dict(size=11, color=MUTED)), gridcolor=GRID,
                         zeroline=False, type="log")
        fig.update_xaxes(automargin=True, tickfont=dict(size=11, color=MUTED))
        fig.update_yaxes(automargin=True, tickfont=dict(size=11, color=MUTED))
        base_layout(fig, 420)
        fig.update_layout(showlegend=False, margin=dict(l=56, r=12, t=24, b=48))
        st.plotly_chart(fig, config=CHART_CONFIG, theme=None, alt="Biểu đồ phân tán lợi suất 6-1 và giá trị khớp trung vị theo mã HOSE")

with st.expander("Phương pháp và giới hạn", icon=":material/menu_book:"):
    st.markdown(
        f"""
**1. Cổng thanh khoản.** Ngưỡng T = vị thế dự kiến ÷ tỷ lệ tham gia tối đa vào giá trị khớp một phiên (hiện {vn(T / 1e9, 1)} tỷ đồng/ngày,
đặt ở `config.toml`, mục `[universe]`: 250 triệu đồng và 5%; đổi hai số này thì ngưỡng đổi). Mỗi mã lấy **trung vị** giá trị khớp mỗi ngày trên {len(days)} ngày đủ;
ngày mã không giao dịch và ngày mã không có trong ảnh chụp đều tính là 0 (không bỏ khỏi mẫu), nên mã khớp lai rai không trông thanh khoản hơn thực tế.
Trung vị từ T trở lên (đúng bằng T cũng được) và có giao dịch ít nhất 80% số ngày thì *Đạt*. *Sát ngưỡng* là cờ cho mã Đạt có trung vị dưới 1,25 lần T.
Mã không thuộc dạng cổ phiếu 3 ký tự (ETF, chứng quyền) bị loại khỏi tập đánh giá.

**2. Động lượng 6-1.** Lợi suất giữa giá đóng cửa cách ngày tham chiếu 6 tháng và 1 tháng, tính theo mốc lịch với một ngày tham chiếu chung cho mọi mã.
Giá lấy là giá gần nhất không muộn hơn mốc; cách mốc quá 10 ngày thì coi là không đủ lịch sử, nến cuối cách ngày tham chiếu quá 3 phiên thì *Dữ liệu cũ*.
Lọc thanh khoản trước, động lượng sau: nhãn *Chưa đủ lịch sử* chỉ gắn cho mã đã qua cổng. Xếp hạng là thứ hạng phần trăm trong nhóm Đạt.

**3. Nước ngoài** (tham khảo, chưa vào xếp hạng): tổng ròng chia tổng giá trị khớp trong cả cửa sổ. Khối lượng nước ngoài trống nghĩa là bên đó không
có giao dịch (đã kiểm: mọi dòng khối lượng trống đều có giá trị bằng 0), nên chỉ dùng giá trị.

**Giới hạn**
- **Chỉ {len(days)} ngày đủ** để tính giá trị khớp (mẫu ngắn): một phiên đột biến (cơ cấu ETF, đáo hạn phái sinh) vẫn có thể ảnh hưởng, dù đã dùng trung vị. Ngày chụp bảng giá giữa phiên hoặc trước khớp ATC bị loại.
- **Giá nến SSI là giá điều chỉnh cổ tức**, chỉ dùng tỷ lệ trong cùng mã; không trộn với giá NEO. Nến chỉ cập nhật khi chạy `python scripts/fetch_ssi_candles.py`, nên động lượng có thể cũ vài ngày: trang ghi ngày tham chiếu.
- 6-1 là cửa sổ mặc định phổ biến, **chưa kiểm trên dữ liệu của dự án** (chỉ khoảng 13 tháng nến). Chưa kiểm chứng xếp hạng cao có đi kèm lợi suất sau đó tốt hơn hay không.
- Xếp hạng động lượng là **đơn nhân tố**, chưa điều chỉnh biến động và chưa phải điểm tổng hợp.
- Giá trị nước ngoài **có thể gồm cả thỏa thuận** (19 trong 4.488 dòng mã x ngày có mua hoặc bán lớn hơn giá trị khớp: suy ra, chưa xác nhận); chưa đối chiếu tổng ròng với số công bố của sàn.
- Bảng giá không có trạng thái giao dịch (cảnh báo, kiểm soát, hạn chế) nên trang không có cờ này; không có cờ "sát room" vì chưa rõ đơn vị của hai cột room.
- Mã mới niêm yết hoặc mới giao dịch lại có thể rơi vào *Ít giao dịch* hoặc *Chưa đủ lịch sử* chỉ vì mới có vài ngày.
- Cột Radar chỉ có cho mã VN30. Radar thanh khoản không còn làm cổng của trang này.
        """
    )
st.html('<p class="note">Đây là công cụ phân tích học thuật phục vụ đồ án, không phải khuyến nghị đầu tư. '
        "Ứng dụng chỉ đọc dữ liệu thị trường, không gửi, sửa hay hủy lệnh giao dịch.</p>")
