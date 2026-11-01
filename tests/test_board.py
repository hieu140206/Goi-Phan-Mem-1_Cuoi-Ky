"""Bảng giá HTML: định dạng đúng, màu theo trần/sàn/tham chiếu, và hiển thị đúng số của NEO (nghìn đồng, KL nguyên)."""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "app"))
import board as bd  # noqa: E402

from data.overview import price_board  # noqa: E402
from data.schema import normalize_quotes  # noqa: E402
from finance.liquidity import add_liquidity_metrics  # noqa: E402
from neo_api.stream import map_record  # noqa: E402

REST = json.loads((Path(__file__).parent / "fixtures" / "neo_rest_vn30_20261027.json").read_text(encoding="utf-8"))
TS = pd.Timestamp("2026-10-27 10:00:00", tz="Asia/Ho_Chi_Minh")


def _board():
    raw = pd.DataFrame([map_record(r) for r in REST]).assign(ts=TS)
    clean, _ = normalize_quotes(raw)
    return price_board(add_liquidity_metrics(clean), TS.date())


def test_formatters_vietnamese_style():
    assert bd.fmt_px(21300) == "21,30" and bd.fmt_px(139900) == "139,90" and bd.fmt_px(10050) == "10,05"
    assert bd.fmt_qty(3137400) == "3.137.400" and bd.fmt_qty(0) == "0"
    assert "–" in bd.fmt_px(float("nan")) and "–" in bd.fmt_qty(float("nan"))


def test_html_has_one_row_per_symbol_and_full_columns():
    html = bd.board_html(_board())
    rows = re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>")[1], flags=re.S)
    assert len(rows) == 30
    assert all(r.count("<td") == 23 for r in rows)           # mã + TC/trần/sàn + 6 mua + 4 khớp + 6 bán + 3 cuối
    assert "Mua" in html and "Khớp lệnh" in html and "Bán" in html and "Tổng KL" in html


def test_cells_show_neo_numbers_exactly():
    html = bd.board_html(_board())
    acb = next(r for r in REST if r["symbol"] == "ACB")
    row = next(r for r in re.findall(r"<tr>(.*?)</tr>", html.split("<tbody>")[1], flags=re.S) if ">ACB<" in r)
    for expect in (bd.fmt_px(acb["refPrice"]), bd.fmt_px(acb["ceilingPrice"]), bd.fmt_px(acb["floorPrice"]),
                   bd.fmt_qty(acb["totalTradingVolume"]), bd.fmt_qty(acb["bidVol1"]), bd.fmt_qty(acb["askVol1"])):
        assert expect in row


def test_colors_follow_ceiling_floor_reference():
    base = dict(symbol="XYZ", ref=10000.0, ceil=10700.0, floor=9300.0, bid_px3=np.nan, bid_qty3=np.nan, bid_px2=np.nan,
                bid_qty2=np.nan, bid_px1=9900.0, bid_qty1=100.0, last_px=10700.0, last_vol=500.0, change=700.0, pct=7.0,
                ask_px1=10000.0, ask_qty1=200.0, ask_px2=np.nan, ask_qty2=np.nan, ask_px3=np.nan, ask_qty3=np.nan,
                total_vol=1000.0, total_value=1e7, spread_bps=10.0, foreign_net=-2e9)
    html = bd.board_html(pd.DataFrame([base]))
    assert 'class="sym ce">XYZ' in html                      # khớp giá trần: mã và giá tím
    assert re.search(r'class="dn">9,90', html)               # mua 1 dưới tham chiếu: đỏ
    assert re.search(r'class="rf">10,00', html) or re.search(r'class="rf g?">10,00', html)  # bán 1 bằng tham chiếu: vàng
    assert re.search(r'class="up">\+7,00%', html)            # tăng: xanh lá, có dấu +
    assert re.search(r'class="dn">-2,0', html)               # NN bán ròng: đỏ
    assert "nan" not in html.lower().replace("na\">", "")


def test_symbol_is_html_escaped():
    b = _board().copy()
    b.loc[0, "symbol"] = "<b>X</b>"
    assert "<b>X</b>" not in bd.board_html(b) and "&lt;b&gt;" in bd.board_html(b)


# ---------- tô ô vừa đổi ----------
def _row(sym, **kw):
    base = dict(symbol=sym, ref=10000.0, ceil=10700.0, floor=9300.0, bid_px3=9700.0, bid_qty3=10.0, bid_px2=9800.0, bid_qty2=20.0,
                bid_px1=9900.0, bid_qty1=30.0, last_px=10000.0, last_vol=100.0, change=0.0, pct=0.0, ask_px1=10100.0, ask_qty1=40.0,
                ask_px2=10200.0, ask_qty2=50.0, ask_px3=10300.0, ask_qty3=60.0, total_vol=1000.0, total_value=1e9,
                spread_bps=100.0, foreign_net=0.0)
    base.update(kw)
    return base


def test_changed_cells_and_flash_colors_follow_price_level():
    import pandas as pd

    from board import board_html, changed_cells

    prev = pd.DataFrame([_row("AAA"), _row("BBB")])
    cur = pd.DataFrame([
        _row("AAA", bid_qty1=99.0,        # KL mua mức 1 (giá 9.900 < TC) đổi  -> nền đỏ
            ask_qty1=77.0,                # KL bán mức 1 (giá 10.100 > TC) đổi -> nền xanh lá
            bid_qty2=20.0),
        _row("BBB", last_px=10000.0, last_vol=300.0),   # khớp bằng TC đổi KL -> nền vàng
        _row("CCC"),                                    # mã mới: không tính là đổi
    ])
    assert changed_cells(cur, prev) == {("AAA", "bid_qty1"), ("AAA", "ask_qty1"), ("BBB", "last_vol")}
    html = board_html(cur, prev=prev)
    assert html.count("f-dn") == 1 and html.count("f-up") == 1 and html.count("f-rf") == 1
    assert 'class="dn f-dn">99' in html and 'class="up f-up">77' in html and 'class="rf f-rf">300' in html
    assert "f-" not in board_html(cur)             # không có bảng trước thì không tô gì
    assert changed_cells(cur, pd.DataFrame()) == set()


def test_flash_ignores_nan_to_nan_and_text_prices():
    import numpy as np
    import pandas as pd

    from board import changed_cells

    a = pd.DataFrame([_row("AAA", bid_px1="ATO", ask_qty3=np.nan)])
    assert changed_cells(a, a.copy()) == set()
    b = pd.DataFrame([_row("AAA", bid_px1=9900.0, ask_qty3=np.nan)])
    assert changed_cells(b, a) == {("AAA", "bid_px1")}  # ATO -> số là đổi
