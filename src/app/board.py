"""Bảng giá kiểu bảng điện (mã, TC, trần, sàn, 3 mức mua, khớp lệnh, 3 mức bán, tổng KL) dựng bằng HTML.

Vì sao HTML: st.dataframe không có tiêu đề nhóm "Mua | Khớp lệnh | Bán" và không tô màu từng ô theo trần/sàn/tham chiếu.
Hàm ở đây chỉ ĐỊNH DẠNG, không tính lại số liệu: giá hiển thị bằng nghìn đồng (chia 1.000), KL là số cổ phiếu nguyên,
mọi con số khác lấy nguyên từ bảng price_board.
"""
from __future__ import annotations

import html
from urllib.parse import quote

import pandas as pd

from data.overview import price_class

DASH = '<span class="na">–</span>'


def _vn(x: float, d: int = 0) -> str:
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_px(v: float) -> str:
    """Giá (đồng) -> nghìn đồng, 2 số lẻ, dấu phẩy thập phân: 21300 -> 21,30. Chữ ATO/ATC giữ nguyên."""
    if isinstance(v, str):
        return html.escape(v)
    return DASH if pd.isna(v) else _vn(v / 1000, 2)


def fmt_pt(v: float) -> str:
    """Điểm chỉ số của hợp đồng tương lai: 1892.3 -> 1.892,3 (không chia 1.000)."""
    if isinstance(v, str):
        return html.escape(v)
    return DASH if pd.isna(v) else _vn(v, 1)


def fmt_qty(v: float) -> str:
    return DASH if pd.isna(v) else _vn(v, 0)


def _arrow(sign: str) -> str:
    """Mũi tên đặt SAU con số (thẻ riêng, nên chuỗi số và lớp CSS của ô không đổi): ▲ tăng, ▼ giảm, để người không phân biệt màu vẫn đọc được."""
    return '<span class="ar">▲</span>' if sign == "up" else '<span class="ar">▼</span>' if sign == "dn" else ""


def _cell(text: str, cls: str = "") -> str:
    return f'<td class="{cls}">{text}</td>' if cls else f"<td>{text}</td>"


def _same(a: object, b: object) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return (pd.isna(a) and pd.isna(b)) or a == b


FLASH_COLUMNS = ["last_px", "last_vol", "change", "pct", *[f"{s}_{k}{i}" for s in ("bid", "ask") for k in ("px", "qty") for i in (1, 2, 3)]]


def changed_cells(board: pd.DataFrame, prev: pd.DataFrame | None) -> set[tuple[str, str]]:
    """Các ô (mã, cột) có giá trị khác lần cập nhật trước. Mã mới xuất hiện (chưa có ở lần trước) không tính là đổi."""
    if prev is None or prev.empty or board.empty:
        return set()
    old = prev.set_index("symbol")
    out: set[tuple[str, str]] = set()
    for r in board.itertuples(index=False):
        if r.symbol not in old.index:
            continue
        o = old.loc[r.symbol]
        for c in FLASH_COLUMNS:
            if c in old.columns and not _same(getattr(r, c), o[c]):
                out.add((r.symbol, c))
    return out


def board_html(board: pd.DataFrame, kind: str = "stock", prev: pd.DataFrame | None = None,
               link: str | None = None, dialog: bool = False) -> str:
    """kind="stock": cổ phiếu/ETF/CW (giá nghìn đồng). kind="future": hợp đồng tương lai (giá điểm, thêm KL mở và basis).
    prev: bảng ở lần cập nhật trước; ô nào đổi giá trị được tô nền theo màu mức giá của ô (trên TC xanh, dưới TC đỏ,
    bằng TC vàng, trần tím, sàn xanh dương), như bảng điện: "vừa đổi so với lần cập nhật trước", không phải từng giao dịch.
    link: đường dẫn trang Chi tiết mã (ví dụ "ma"); có thì ô mã thành liên kết `ma?ma=<mã>` mở hồ sơ của mã đó.
    dialog: ô mã thành liên kết `?xem=<mã>` (cùng trang) để trang mở hộp thoại chi tiết mã; ưu tiên hơn link."""
    changed = changed_cells(board, prev)
    fut = kind == "future"
    px_fmt = fmt_pt if fut else fmt_px
    div = 1.0 if fut else 1000.0
    head = (
        '<thead><tr>'
        f'<th rowspan="2" class="sym">{"Hợp đồng" if fut else "Mã CK"}</th><th rowspan="2" class="g">TC</th><th rowspan="2">Trần</th>'
        '<th rowspan="2">Sàn</th>'
        '<th colspan="6" class="g c">Mua</th><th colspan="4" class="g c">Khớp lệnh</th><th colspan="6" class="g c">Bán</th>'
        '<th rowspan="2" class="g">Tổng KL</th>'
        + ('<th rowspan="2">KL mở (OI)</th><th rowspan="2">Basis (điểm)</th></tr>' if fut else
           '<th rowspan="2">Spread (bps)</th><th rowspan="2">NN ròng (tỷ đ)</th></tr>')
        + '<tr class="r2"><th class="g">Giá 3</th><th>KL 3</th><th>Giá 2</th><th>KL 2</th><th>Giá 1</th><th>KL 1</th>'
        '<th class="g">Giá</th><th>KL</th><th>+/-</th><th>%</th>'
        '<th class="g">Giá 1</th><th>KL 1</th><th>Giá 2</th><th>KL 2</th><th>Giá 3</th><th>KL 3</th></tr></thead>'
    )
    rows = []
    for r in board.itertuples(index=False):
        k = lambda px: price_class(px, r.ref, r.ceil, r.floor)  # noqa: E731
        match = k(r.last_px)
        fl = lambda col, cls: (f"{cls} f-{cls}".strip() if cls and (r.symbol, col) in changed else cls)  # noqa: E731
        sign = "up" if r.change > 0 else "dn" if r.change < 0 else "rf" if not pd.isna(r.change) else ""
        net = r.foreign_net / 1e9 if not fut and not pd.isna(r.foreign_net) else float("nan")
        net_cls = "up" if net > 0 else "dn" if net < 0 else ""
        sym_txt = html.escape(str(r.symbol))
        if dialog and not fut:
            sym_txt = f'<a href="?xem={quote(str(r.symbol))}" target="_self" title="Xem biểu đồ nến {sym_txt}">{sym_txt}</a>'
        elif link and not fut:
            sym_txt = f'<a href="{link}?ma={quote(str(r.symbol))}" target="_self" title="Mở hồ sơ {sym_txt}">{sym_txt}</a>'
        cells = [
            f'<td class="sym {match}">{sym_txt}'
            + (f' <span class="mat">{html.escape(str(r.maturity))}</span>' if fut else "") + "</td>",
            _cell(px_fmt(r.ref), "g rf"), _cell(px_fmt(r.ceil), "ce"), _cell(px_fmt(r.floor), "fl"),
        ]
        for i in (3, 2, 1):
            px, q = getattr(r, f"bid_px{i}"), getattr(r, f"bid_qty{i}")
            cells += [_cell(px_fmt(px), (fl(f"bid_px{i}", k(px)) + (" g" if i == 3 else "")).strip()),
                      _cell(fmt_qty(q), fl(f"bid_qty{i}", k(px)))]
        cells += [_cell(px_fmt(r.last_px), (fl("last_px", match) + " g").strip()), _cell(fmt_qty(r.last_vol), fl("last_vol", match)),
                  _cell(DASH if pd.isna(r.change) else ("+" if r.change > 0 else "") + _vn(r.change / div, 2 if not fut else 1) + _arrow(sign), fl("change", sign)),
                  _cell(DASH if pd.isna(r.pct) else ("+" if r.pct > 0 else "") + _vn(r.pct, 2) + "%" + _arrow(sign), fl("pct", sign))]
        for i in (1, 2, 3):
            px, q = getattr(r, f"ask_px{i}"), getattr(r, f"ask_qty{i}")
            cells += [_cell(px_fmt(px), (fl(f"ask_px{i}", k(px)) + (" g" if i == 1 else "")).strip()),
                      _cell(fmt_qty(q), fl(f"ask_qty{i}", k(px)))]
        cells.append(_cell(fmt_qty(r.total_vol), "g"))
        if fut:
            cells += [_cell(fmt_qty(r.open_interest)),
                      _cell(DASH if pd.isna(r.basis) else ("+" if r.basis > 0 else "") + _vn(r.basis, 2),
                            "" if pd.isna(r.basis) else "up" if r.basis > 0 else "dn" if r.basis < 0 else "")]
        else:
            cells += [_cell(DASH if pd.isna(r.spread_bps) else _vn(r.spread_bps, 1)),
                      _cell(DASH if pd.isna(net) else ("+" if net > 0 else "") + _vn(net, 1), net_cls)]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="board-wrap"><table class="board">{head}<tbody>{"".join(rows)}</tbody></table></div>'


def board_css(border: str, grid: str, muted: str, ink: str, up: str, dn: str) -> str:
    return f"""<style>
.board-wrap {{ overflow: auto; container-type: inline-size; max-height: calc(100vh - 230px); min-height: 420px; border: 1px solid {border}; border-radius: 8px; background: #ffffff; }}
.board {{ border-collapse: separate; border-spacing: 0; width: 100%; font-size: clamp(9.5px, calc(100cqw / 116), 13px); font-variant-numeric: tabular-nums; }}  /* chữ co theo bề ngang khung để vừa hết các cột, không cuộn ngang */
.board th {{ position: sticky; top: 0; z-index: 3; background: #f7f8fa; color: {muted}; font-weight: 600; padding: 0 0.5em;
            text-align: right; border-bottom: 1px solid {border}; height: 32px; line-height: 32px; box-sizing: border-box;
            white-space: nowrap; }}
.board th.c {{ text-align: center; color: {ink}; }}
.board tr.r2 th {{ top: 32px; }}
.board td {{ padding: 0.35em 0.5em; text-align: right; border-bottom: 1px solid {grid}; white-space: nowrap; }}
.board .g {{ border-left: 1px solid {border}; }}
.board th.sym, .board td.sym {{ text-align: left; position: sticky; left: 0; z-index: 4; font-weight: 700;
                                background: #ffffff; border-right: 1px solid {border}; border-left: none; }}
.board th.sym {{ background: #f7f8fa; z-index: 5; }}
.board td.sym a {{ color: inherit; text-decoration: none; }}
.board td.sym a:hover {{ text-decoration: underline; }}
.board tbody tr:hover td {{ background: #f7f9fc; }}
.board tbody tr:hover td.sym {{ background: #f7f9fc; }}
.board .ce {{ color: #7c3aed; }} .board .fl {{ color: #1d5fbf; }} .board .rf {{ color: #b7791f; }}
.board .f-up {{ background: #d7f0da; }} .board .f-dn {{ background: #fbdcdd; }} .board .f-rf {{ background: #fdeccb; }}
.board .f-ce {{ background: #e9ddfb; }} .board .f-fl {{ background: #d9e7fb; }}
.board .mat {{ font-weight: 400; font-size: 11px; color: {muted}; margin-left: 4px; }}
.board .up {{ color: {up}; }} .board .dn {{ color: {dn}; }} .board .na {{ color: #b5bac1; }}
.board .ar {{ font-size: 9px; margin-left: 3px; }}
</style>"""
