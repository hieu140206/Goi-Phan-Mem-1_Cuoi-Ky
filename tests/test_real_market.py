"""Kiểm tra trên phản hồi THẬT của NEO 4.2/4.3/4.4 lấy lúc 22:47 ngày 27/10/2026."""
import datetime as dt
import json
from pathlib import Path

from data.market import breadth_table, index_intraday_frame, phase_of

DATA = json.loads((Path(__file__).parent / "fixtures" / "neo_market_20261027.json").read_text(encoding="utf-8"))


def test_vn30_intraday_has_full_day_minute_series():
    df = index_intraday_frame(DATA["4.2 intradayMarketIndex"], "2026-10-27")
    assert len(df) > 300 and df["ts"].is_monotonic_increasing
    assert str(df["ts"].iloc[0].time()) == "09:00:55" and str(df["ts"].iloc[-1].time()) == "15:05:05"
    # khối lượng lũy kế không giảm, và volume là phần tăng thêm
    assert df["total_volume"].is_monotonic_increasing
    assert (df["total_volume"].diff().dropna() == df["volume"].iloc[1:].values).all()
    # nghỉ trưa: chỉ số đứng yên, không có khớp lệnh
    lunch = df[df["phase"] == "Nghỉ trưa"]
    assert len(lunch) > 60 and lunch["index_value"].nunique() == 1 and lunch["volume"].sum() == 0


def test_phase_boundaries():
    assert phase_of(dt.time(9, 10)) == "ATO"
    assert phase_of(dt.time(10, 0)) == "Liên tục (sáng)"
    assert phase_of(dt.time(12, 0)) == "Nghỉ trưa"
    assert phase_of(dt.time(14, 40)) == "ATC"
    assert phase_of(dt.time(11, 30, 55)) == "Liên tục (sáng)" and phase_of(dt.time(14, 30, 55)) == "Liên tục (chiều)"
    assert phase_of(dt.time(15, 5, 5)) == "Sau giờ / thỏa thuận"


def test_breadth_drops_fu_and_vn30_sums_to_30():
    b = breadth_table(DATA["4.3 marketIndexDetail"]).set_index("indexCode")
    assert "FU" not in b.index
    vn30 = b.loc["VN30"]
    assert vn30["advances"] + vn30["declines"] + vn30["noChange"] == 30
