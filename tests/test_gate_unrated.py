"""Mục B6: mã chưa có mốc nền thì cổng ghi "Chưa đánh giá" (không Đạt, không Loại), xếp sau mã qua cổng và trước mã Loại."""
import numpy as np
import pandas as pd

from analytics.screener import GATE_UNRATED, liquidity_gate, screen


def ranking(**cols):
    base = {"symbol": ["A", "B", "C", "D"], "score": [60.0, 70.0, 80.0, 90.0]}
    base.update(cols)
    return pd.DataFrame(base)


def _factors(syms):
    return pd.DataFrame({"symbol": syms, "foreign_ratio": [0.1, 0.5, 0.9, 0.3, 0.7][:len(syms)],
                         "mom_rel": [0.0, 0.01, 0.02, 0.03, 0.04][:len(syms)]})


def test_symbol_without_baseline_is_unrated_not_pass():
    r = ranking(baseline_ok=[True, False, True, False],
                baseline_reason=["", "cần ≥5 phiên trước cùng khung giờ (hiện có 2)", "", ""])
    g = liquidity_gate(r, pd.Series(dtype=float)).set_index("symbol")
    assert g["gate"].tolist() == ["Đạt", GATE_UNRATED, "Đạt", GATE_UNRATED]
    assert g.loc["B", "gate_reason"].startswith("Chưa đánh giá") and "cần ≥5 phiên" in g.loc["B", "gate_reason"]
    assert len(g.loc["D", "gate_reason"]) > 15                      # thiếu lý do chi tiết vẫn có lý do chung


def test_low_score_beats_unrated():
    r = ranking(score=[10.0, 70.0, 80.0, 90.0], baseline_ok=[False, False, True, True])
    g = liquidity_gate(r, pd.Series(dtype=float)).set_index("symbol")
    assert g.loc["A", "gate"] == "Loại" and g.loc["B", "gate"] == GATE_UNRATED


def test_unrated_symbol_is_not_called_pass_even_with_zero_alerts():
    r = ranking(baseline_ok=[False] * 4)
    g = liquidity_gate(r, pd.Series(dtype=float))
    assert (g["gate"] == GATE_UNRATED).all() and (g["alerts"] == 0).all()    # 0 cảnh báo ở đây là chưa đánh giá được


def test_screen_orders_pass_then_unrated_then_fail_and_unrated_have_no_score():
    r = pd.DataFrame({"symbol": ["A", "B", "C", "D", "E"], "score": [60.0, 70.0, 80.0, 10.0, 90.0],
                      "baseline_ok": [True, False, True, True, False]})
    s = screen(_factors(r["symbol"].tolist()), liquidity_gate(r, pd.Series(dtype=float)))
    assert s["gate"].tolist() == ["Đạt", "Đạt", GATE_UNRATED, GATE_UNRATED, "Loại"]
    assert s.set_index("symbol").loc[["B", "E", "D"], "screen_score"].isna().all()


def test_unrated_and_failed_symbols_do_not_change_other_symbols_ranks():
    """Phần trăm thứ hạng chỉ tính trong tập mã qua cổng: thêm hay bớt mã Chưa đánh giá / Loại không làm đổi nó."""
    passing = pd.DataFrame({"symbol": ["A", "B", "C"], "score": [60.0, 70.0, 80.0]})
    a = screen(_factors(["A", "B", "C"]), liquidity_gate(passing, pd.Series(dtype=float))).set_index("symbol")
    more = pd.DataFrame({"symbol": ["A", "B", "C", "D", "E"], "score": [60.0, 70.0, 80.0, 90.0, 10.0],
                         "baseline_ok": [True, True, True, False, True]})
    f = _factors(["A", "B", "C", "D", "E"])
    f.loc[f["symbol"] == "D", ["foreign_ratio", "mom_rel"]] = [99.0, 99.0]       # cực đoan để thấy nếu lọt vào xếp hạng
    f.loc[f["symbol"] == "E", ["foreign_ratio", "mom_rel"]] = [-99.0, -99.0]
    b = screen(f, liquidity_gate(more, pd.Series(dtype=float))).set_index("symbol")
    for s in ("A", "B", "C"):
        assert a.loc[s, "screen_score"] == b.loc[s, "screen_score"]
        assert a.loc[s, "rank_foreign_ratio"] == b.loc[s, "rank_foreign_ratio"]
    assert np.isnan(b.loc["D", "rank_foreign_ratio"]) and np.isnan(b.loc["E", "rank_foreign_ratio"])
