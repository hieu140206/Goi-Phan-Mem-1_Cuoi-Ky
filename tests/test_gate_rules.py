"""Cổng thanh khoản, mục A4: hai cơ chế song song. Đợt cảnh báo quyết định nhãn "Chú ý"; LRS chỉ là thang mức độ đi kèm
(hiện ở cột lý do) và chỉ đổi nhãn khi bật gate.use_lrs. Dữ liệu dựng sẵn, không đọc market.db."""
import pandas as pd

from analytics.screener import liquidity_gate


def ranking(**cols):
    base = {"symbol": ["A", "B", "C", "D"], "score": [60.0, 70.0, 80.0, 90.0]}
    base.update(cols)
    return pd.DataFrame(base)


def test_lrs_alone_does_not_change_the_gate_by_default():
    r = ranking(lrs_tier=["Cao", "Chú ý", "Bình thường", "Chưa đủ dữ liệu"])
    g = liquidity_gate(r, pd.Series(dtype=float)).set_index("symbol")
    assert (g["gate"] == "Đạt").all()                               # không đợt cảnh báo nào: vẫn Đạt dù LRS Cao
    assert "LRS lần chụp cuối: Cao" in g.loc["A", "gate_reason"]    # nhưng mức LRS hiện ở cột lý do
    assert "LRS lần chụp cuối: Chú ý" in g.loc["B", "gate_reason"]
    assert "LRS" not in g.loc["C", "gate_reason"] and "LRS" not in g.loc["D", "gate_reason"]


def test_lrs_changes_the_gate_only_when_switched_on():
    r = ranking(lrs_tier=["Cao", "Chú ý", "Bình thường", "Chưa đủ dữ liệu"])
    g = liquidity_gate(r, pd.Series(dtype=float), use_lrs=True).set_index("symbol")
    assert g["gate"].tolist() == ["Chú ý", "Chú ý", "Đạt", "Đạt"]
    assert "LRS ở mức Cao" in g.loc["A", "gate_reason"]


def test_alert_period_decides_watch_whatever_the_lrs_says():
    r = ranking(lrs_tier=["Bình thường", "Bình thường", "Bình thường", "Bình thường"])
    g = liquidity_gate(r, pd.Series({"B": 2})).set_index("symbol")
    assert g.loc["B", "gate"] == "Chú ý" and "2 đợt cảnh báo" in g.loc["B", "gate_reason"]
    assert g.loc["A", "gate"] == "Đạt"


def test_low_liquidity_score_still_fails_even_with_lrs_switched_on():
    r = ranking(score=[10.0, 70.0, 80.0, 90.0], lrs_tier=["Cao", "", "", ""])
    g = liquidity_gate(r, pd.Series(dtype=float), use_lrs=True).set_index("symbol")
    assert g.loc["A", "gate"] == "Loại"


def test_without_lrs_column_behaviour_is_unchanged():
    g = liquidity_gate(ranking(), pd.Series({"A": 1}))
    assert g["gate"].tolist() == ["Chú ý", "Đạt", "Đạt", "Đạt"]
