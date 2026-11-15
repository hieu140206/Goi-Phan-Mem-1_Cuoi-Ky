"""Trang "Chi tiết mã": hồ sơ của MỘT mã VN30, nơi các trang khác dẫn vào (địa chỉ ?ma=FPT).

Gom về một chỗ: giá và sổ lệnh 3 mức, thanh khoản (cùng số với Radar), diễn biến trong phiên, dòng tiền nước ngoài.
Mọi số lấy từ cùng các hàm dùng chung (shared.py); trang này chỉ chọn và trình bày, không tính lại theo cách khác.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from charts import intraday_caption, intraday_figure  # noqa: E402
from data.overview import board_view, price_board  # noqa: E402
from shared import (SRC_DB, SRC_SAMPLE, WATCHLIST_PATH, analyzed_data, board_dates, board_of,  # noqa: E402
                    current_source, liquidity_ranking, screen_for_day)
from theme import BORDER, CHART_CONFIG, GRID, INK, MUTED, NEG, vn  # noqa: E402
from watchlist import load_watchlist, toggle  # noqa: E402

POS = "#2e7d32"

st.html(f"""<style>
.ob {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
.ob th {{ color: {MUTED}; font-weight: 500; text-align: right; padding: 6px 10px; border-bottom: 1px solid {BORDER}; }}
.ob td {{ text-align: right; padding: 6px 10px; border-bottom: 1px solid {GRID}; }}
.ob th:first-child, .ob td:first-child {{ text-align: left; color: {MUTED}; }}
.ob .b {{ color: {POS}; }} .ob .a {{ color: {NEG}; }}
.facts {{ display: grid; grid-template-columns: 1fr auto; gap: 6px 16px; font-size: 13.5px; }}
.facts span {{ color: {MUTED}; }} .facts b {{ font-weight: 600; text-align: right; }}
.up {{ color: {POS}; }} .dn {{ color: {NEG}; }}
</style>""")


def px(v) -> str:
    """Giá đồng -> nghìn đồng, 2 số lẻ. Thiếu -> –."""
    v = pd.to_numeric(v, errors="coerce")
    return "–" if pd.isna(v) else vn(v / 1000, 2)


def signed(v, d: int = 2, suffix: str = "") -> str:
    v = pd.to_numeric(v, errors="coerce")
    if pd.isna(v):
        return "–"
    cls = "up" if v > 0 else "dn" if v < 0 else ""
    return f'<span class="{cls}">{"+" if v > 0 else ""}{vn(v, d)}{suffix}</span>'


# ---------- nguồn dữ liệu và mã đang xem ----------
source = current_source()
if source is None:
    st.title("Chi tiết mã", anchor=False)
    st.error("Chưa có dữ liệu. Ghi dữ liệu NEO bằng `python scripts/run_live.py` hoặc tạo dữ liệu mô phỏng.",
             title="Chưa có dữ liệu")
    st.stop()

analyzed = analyzed_data(source)
symbols = sorted(analyzed["symbol"].unique())
if not symbols:
    st.title("Chi tiết mã", anchor=False)
    st.info("Chưa có lần chụp sổ lệnh nào trong phiên khớp lệnh liên tục.")
    st.stop()

watch = load_watchlist(WATCHLIST_PATH)
wanted = str(st.query_params.get("ma", "")).strip().upper()
if wanted in symbols and wanted != st.session_state.get("_ma_seen"):
    # Chỉ nhận mã từ địa chỉ khi nó MỚI (mở từ trang khác hoặc dán link). Nếu không, mỗi lần chọn mã khác,
    # địa chỉ vẫn còn mã cũ và ghi đè lại lựa chọn của người dùng.
    st.session_state["detail_sym"] = wanted
elif st.session_state.get("detail_sym") not in symbols:
    st.session_state["detail_sym"] = next((s for s in watch if s in symbols), symbols[0])

use_board = source == SRC_DB
quote_days = sorted(analyzed["ts"].dt.date.unique())
board_day_list = [pd.Timestamp(d).date() for d in board_dates()] if use_board else []
days = sorted(set(quote_days) | set(board_day_list), reverse=True)
ssi_days = set(analyzed.loc[analyzed["src"] == "SSI", "ts"].dt.date.unique()) if "src" in analyzed else set()

with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    sym = st.selectbox("Mã", symbols, key="detail_sym", width=140)
    # Mặc định: phiên gần nhất có sổ lệnh theo phút của mã (đủ cả giá lẫn thanh khoản); vẫn chọn được ngày chỉ có bảng giá.
    sym_q_days = analyzed.loc[analyzed["symbol"] == sym, "ts"].dt.date
    default_day = sym_q_days.max() if len(sym_q_days) else days[0]
    day = st.selectbox("Phiên", days, index=days.index(default_day), width=160,
                       format_func=lambda d: d.strftime("%d/%m/%Y") + (" · SSI" if d in ssi_days else ""))
st.session_state["_ma_seen"] = sym
st.query_params["ma"] = sym          # địa chỉ trang luôn trỏ đúng mã đang xem (chia sẻ hoặc tải lại vẫn đúng)
st.session_state["sym"] = sym        # Radar mở sẵn đúng mã này khi chuyển sang

# ---------- giá: ưu tiên bảng giá cuối ngày (đã có ATC), không có thì lần chụp cuối trong phiên liên tục ----------
day_str = f"{day:%Y-%m-%d}"
raw = board_of(day_str, "VN30") if use_board else pd.DataFrame()
raw = raw[raw["symbol"] == sym] if not raw.empty else raw
if not raw.empty:
    snap = board_view(raw).iloc[0]
    snap_ts = raw["ts"].iloc[0]
    snap_note = f"bảng giá lúc {snap_ts:%H:%M}" + ("" if snap_ts.time() >= pd.Timestamp('14:45').time()
                                                   else " (trước phiên ATC, chưa phải giá đóng cửa)")
    f_buy, f_sell = raw["foreign_buy_val"].iloc[0], raw["foreign_sell_val"].iloc[0]
else:
    pb = price_board(analyzed, day)
    pb = pb[pb["symbol"] == sym] if not pb.empty else pb
    snap = pb.iloc[0] if not pb.empty else None
    last_q = analyzed[(analyzed["symbol"] == sym) & (analyzed["ts"].dt.date == day)].sort_values("ts")
    snap_ts = last_q["ts"].iloc[-1] if not last_q.empty else None
    snap_note = (f"lần chụp sổ lệnh cuối trong phiên khớp lệnh liên tục ({snap_ts:%H:%M}), chưa gồm phiên ATC"
                 if snap_ts is not None else "")
    if day in ssi_days:
        snap_note = ("sổ lệnh lấy từ SSI (NEO không ghi được phiên này), mỗi phút một lần; không có giá khớp và khối lượng khớp"
                     if snap_ts is None else f"sổ lệnh lấy từ SSI lúc {snap_ts:%H:%M} (NEO không ghi được phiên này); "
                     "không có giá khớp, khối lượng khớp và nước ngoài")
    f_buy = last_q["foreign_buy_val"].iloc[-1] if not last_q.empty else float("nan")
    f_sell = last_q["foreign_sell_val"].iloc[-1] if not last_q.empty else float("nan")

in_watch = sym in watch
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    with st.container(width="stretch"):
        st.title(sym, anchor=False)
        st.caption(f"Cổ phiếu VN30 · phiên {day:%d/%m/%Y}" + (f" · {snap_note}" if snap_note else "")
                   + (" · dữ liệu mô phỏng" if source == SRC_SAMPLE else ""))
    st.button("Bỏ theo dõi" if in_watch else "Theo dõi mã này", icon=":material/star:" if in_watch else ":material/star_border:",
              on_click=toggle, args=(WATCHLIST_PATH, sym), key="watch_btn")
    st.page_link("screen_page.py", label="Bộ lọc", icon=":material/filter_alt:")
    st.page_link("radar.py", label="Radar", icon=":material/radar:")

if snap is None:
    st.info("Không có giá cho mã này trong phiên đã chọn.")
else:
    net = pd.to_numeric(snap.get("foreign_net"), errors="coerce")
    st.html(
        '<div class="kpis">'
        f'<div class="kpi lead"><div class="l">Giá (nghìn đ)</div><div class="v">{px(snap["last_px"])}</div>'
        f'<div class="s">{signed(pd.to_numeric(snap["change"], errors="coerce") / 1000)} · {signed(snap["pct"], 2, "%")}</div></div>'
        f'<div class="kpi"><div class="l">Tham chiếu · Trần · Sàn</div><div class="v" style="font-size:18px">'
        f'{px(snap["ref"])} · {px(snap["ceil"])} · {px(snap["floor"])}</div><div class="s">nghìn đồng</div></div>'
        f'<div class="kpi"><div class="l">Tổng khối lượng</div><div class="v">{vn(snap["total_vol"])}</div>'
        f'<div class="s">{vn(pd.to_numeric(snap["total_value"], errors="coerce") / 1e9, 1)} tỷ đồng</div></div>'
        f'<div class="kpi"><div class="l">Nước ngoài ròng</div><div class="v">{signed(net / 1e9, 1)}<small>tỷ đ</small></div>'
        f'<div class="s">mua {vn(pd.to_numeric(f_buy, errors="coerce") / 1e9, 1)} · bán '
        f'{vn(pd.to_numeric(f_sell, errors="coerce") / 1e9, 1)} tỷ đ</div></div>'
        "</div>"
    )

# ---------- sổ lệnh + thanh khoản ----------
view_day = analyzed[analyzed["ts"].dt.date == day]
one = view_day[view_day["symbol"] == sym]
c1, c2 = st.columns([5, 7], gap="small")
with c1, st.container(border=True, key="panel_book"):
    st.subheader("Sổ lệnh 3 mức giá", anchor=False)
    if snap is None:
        st.caption("Không có sổ lệnh.")
    else:
        rows = "".join(
            f'<tr><td>Mức {i}</td><td>{vn(pd.to_numeric(snap[f"bid_qty{i}"], errors="coerce"))}</td>'
            f'<td class="b">{px(snap[f"bid_px{i}"]) if not isinstance(snap[f"bid_px{i}"], str) else html.escape(snap[f"bid_px{i}"])}</td>'
            f'<td class="a">{px(snap[f"ask_px{i}"]) if not isinstance(snap[f"ask_px{i}"], str) else html.escape(snap[f"ask_px{i}"])}</td>'
            f'<td>{vn(pd.to_numeric(snap[f"ask_qty{i}"], errors="coerce"))}</td></tr>' for i in (1, 2, 3))
        st.html('<table class="ob"><thead><tr><th></th><th>KL mua</th><th>Giá mua</th><th>Giá bán</th><th>KL bán</th></tr>'
                f"</thead><tbody>{rows}</tbody></table>")
        st.caption("Giá nghìn đồng, khối lượng cổ phiếu. " + (snap_note[:1].upper() + snap_note[1:] + "." if snap_note else ""))

with c2, st.container(border=True, key="panel_liq"):
    st.subheader("Thanh khoản trong phiên", anchor=False,
                 help="Cùng cách tính và cùng số với trang Radar khi Radar chọn đúng phiên này.")
    if one.empty:
        st.caption("Phiên này không có sổ lệnh theo phút trong phiên khớp lệnh liên tục, nên chưa đo được thanh khoản.")
    else:
        ranking, _, _ = liquidity_ranking(view_day)
        r = ranking.set_index("symbol").loc[sym]
        pos = len(ranking) - int(ranking.index[ranking["symbol"] == sym][0])  # ranking xếp yếu nhất trước
        tier_note = {"Cao": "dn", "Chú ý": "dn"}.get(r["lrs_tier"], "")
        st.html(
            '<div class="facts">'
            f'<span>Điểm thanh khoản</span><b>{vn(r["score"], 0)}/100 · hạng {pos}/{len(ranking)} · {html.escape(r["tier"])}</b>'
            f'<span>Spread trung bình (dùng chấm điểm)</span><b>{vn(r["spread_bps_mean"], 1)} bps</b>'
            f'<span>Spread trung bình theo bước giá</span><b>{vn(r["spread_ticks"], 2)}</b>'
            f'<span>Độ sâu 3 mức trung vị</span><b>{vn(r["depth_value"] / 1e6, 0)} triệu đ</b>'
            f'<span>Điểm rủi ro LRS (lần chụp cuối)</span><b class="{tier_note}">{vn(r["lrs"], 2) if pd.notna(r["lrs"]) else "–"}'
            f'{" · " + html.escape(r["lrs_tier"]) if r["lrs_tier"] else ""}</b>'
            f'<span>Đợt cảnh báo trong phiên</span><b class="{"dn" if r["alerts"] else ""}">{int(r["alerts"])}</b>'
            "</div>"
        )
        st.caption(f"Hạng 1 là thanh khoản tốt nhất trong {len(ranking)} mã VN30 của phiên {day:%d/%m}.")
        res = screen_for_day(source, day)
        if res is not None:
            sr = res["result"].reset_index(drop=True)
            me = sr[sr["symbol"] == sym]
            if not me.empty:
                me = me.iloc[0]
                passed = sr[sr["gate"] != "Loại"].dropna(subset=["screen_score"]).reset_index(drop=True)
                place = (f"điểm {vn(me['screen_score'], 0)}/100, hạng {int(passed.index[passed['symbol'] == sym][0]) + 1}/"
                         f"{len(passed)} mã qua cổng" if pd.notna(me["screen_score"]) else "không xếp hạng")
                st.html(f'<div class="notice"><b>Bộ lọc:</b> cổng <b>{html.escape(me["gate"])}</b> '
                        f'({html.escape(me["gate_reason"])}); {place}.</div>')

if not one.empty:
    with st.container(border=True, key="panel_intraday"):
        st.subheader("Diễn biến trong phiên", anchor=False,
                     help="Spread, độ sâu và điểm rủi ro LRS; dải tô đỏ nhạt là các đợt cảnh báo.")
        st.caption(intraday_caption(sym, day, one))
        st.plotly_chart(intraday_figure(one, 520), config=CHART_CONFIG, theme=None,
                        alt=f"Diễn biến spread, độ sâu và LRS của {sym} trong phiên {day:%d/%m/%Y}")

# ---------- dòng tiền nước ngoài theo ngày ----------
with st.container(border=True, key="panel_foreign"):
    st.subheader("Dòng tiền nước ngoài theo ngày", anchor=False)
    rows = []
    for d in board_day_list:
        b = board_of(f"{d:%Y-%m-%d}", "VN30")
        b = b[b["symbol"] == sym] if not b.empty else b
        if b.empty:
            continue
        num = lambda c: pd.to_numeric(b[c].iloc[0], errors="coerce") / 1e9  # noqa: E731
        ts = b["ts"].iloc[0]
        rows.append({"day": d.strftime("%d/%m/%Y"), "buy": num("foreign_buy_val"), "sell": num("foreign_sell_val"),
                     "net": num("foreign_net_val"),
                     "ratio": num("foreign_net_val") / num("total_value") * 100 if num("total_value") else float("nan"),
                     "at": ts.strftime("%H:%M") + ("" if ts.time() >= pd.Timestamp("14:45").time() else " (trước ATC)")})
    if not rows:
        st.caption("Chưa có bảng giá cuối ngày nào cho mã này. Bộ ghi lưu bảng giá mỗi ngày khi chạy `run_live.py`.")
    else:
        fdf = pd.DataFrame(rows[::-1])
        st.dataframe(
            fdf.style.format({"buy": "{:,.1f}", "sell": "{:,.1f}", "net": "{:+,.1f}", "ratio": "{:+.1f}%"},
                             decimal=",", thousands=".", na_rep="–"),
            hide_index=True, alt=f"Dòng tiền nước ngoài của {sym} theo ngày",
            column_config={"day": st.column_config.TextColumn("Ngày"),
                           "buy": st.column_config.NumberColumn("Mua (tỷ đ)"),
                           "sell": st.column_config.NumberColumn("Bán (tỷ đ)"),
                           "net": st.column_config.NumberColumn("Ròng (tỷ đ)"),
                           "ratio": st.column_config.NumberColumn("Ròng / giá trị GD", help="Giá trị nước ngoài mua ròng chia tổng giá trị giao dịch của mã trong ngày"),
                           "at": st.column_config.TextColumn("Chụp lúc")})
        total = pd.to_numeric(fdf["net"], errors="coerce").sum(min_count=1)
        st.caption(f"Cộng dồn {len(fdf)} ngày: {vn(total, 1) if pd.notna(total) else '–'} tỷ đồng. "
                   "Số lũy kế trong ngày lấy từ bảng giá lúc chụp ghi ở cột cuối.")

st.html('<p class="note">Đây là công cụ phân tích học thuật phục vụ đồ án, không phải khuyến nghị đầu tư. '
        "Ứng dụng chỉ đọc dữ liệu thị trường, không gửi, sửa hay hủy lệnh giao dịch.</p>")
