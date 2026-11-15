"""Lưới thẻ lật: chỉ lật thẻ đổi, mã thiếu dữ liệu hiện "–", màu đúng theo mức LRS."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "app"))
import flipgrid as fg  # noqa: E402

T0 = pd.Timestamp("2026-11-13 09:16:00+07:00")
T1 = T0 + pd.Timedelta(minutes=1)


def _df():
    rows = [
        (T0, "AAA", 0.5, ""), (T0, "BBB", 2.4, "Chú ý"), (T0, "CCC", 3.9, "Cao"), (T0, "DDD", np.nan, ""),
        (T1, "AAA", 0.5, ""), (T1, "BBB", 3.9, "Cao"), (T1, "CCC", 3.9, "Cao"), (T1, "DDD", 0.1, ""),
    ]
    return pd.DataFrame(rows, columns=["ts", "symbol", "lrs", "lrs_tier"])


def test_state_colors_and_missing():
    s = fg.grid_state(_df(), ["AAA", "BBB", "CCC", "DDD", "ZZZ"], T0).set_index("symbol")
    assert s.loc["AAA", "cls"] == "ok" and s.loc["BBB", "cls"] == "md" and s.loc["CCC", "cls"] == "hi"
    assert s.loc["BBB", "text"] == "2,4"
    assert s.loc["DDD", "cls"] == "na" and s.loc["DDD", "text"] == "–"      # LRS thiếu: không điền
    assert s.loc["ZZZ", "cls"] == "na" and s.loc["ZZZ", "text"] == "–"      # mã không có dòng






def test_empty_and_none_ts():
    s = fg.grid_state(pd.DataFrame(columns=["ts", "symbol", "lrs", "lrs_tier"]), ["AAA"], None)
    assert s.loc[0, "cls"] == "na"


def test_color_scale_is_monotone_and_anchored():
    assert fg.lrs_color(0.0) == "#eef1f4"                      # trung vị: xám
    assert fg.lrs_color(-5) == fg.lrs_color(-0.9) == "#cfe0f5"  # chặn ở đầu thấp: xanh nhạt
    assert fg.lrs_color(9) == fg.lrs_color(2.3) == "#f0a09a"    # chặn ở đầu cao: đỏ
    red = [int(fg.lrs_color(v)[3:5], 16) for v in (0.0, 0.5, 1.0, 1.3, 1.8, 2.3)]   # kênh G giảm dần khi LRS tăng
    assert red == sorted(red, reverse=True)


def test_missing_has_white_bg():
    s = fg.grid_state(_df(), ["AAA", "DDD", "ZZZ"], T0).set_index("symbol")
    assert s.loc["DDD", "bg"] == "#ffffff" and s.loc["ZZZ", "bg"] == "#ffffff"


def test_treemap_areas_match_weights_and_fill_the_rectangle():
    w = {"A": 50.0, "B": 30.0, "C": 10.0, "D": 5.0, "E": 5.0}
    r = fg.treemap_layout(w, 100.0, 40.0)
    assert set(r) == set(w)
    total = sum(x[2] * x[3] for x in r.values())
    assert abs(total - 4000.0) < 1e-6                                   # lấp đầy hình chữ nhật, không chồng không hở
    for k, v in w.items():
        assert abs(r[k][2] * r[k][3] - v / 100 * 4000.0) < 1e-6          # diện tích tỷ lệ trọng số
    for k, (x, y, ww, hh) in r.items():
        assert x >= -1e-9 and y >= -1e-9 and x + ww <= 100 + 1e-9 and y + hh <= 40 + 1e-9


def test_treemap_30_tiles_stable_and_no_overlap():
    w = {f"S{i:02d}": float(1 + (i * 7) % 23) for i in range(30)}
    r1, r2 = fg.treemap_layout(w), fg.treemap_layout(dict(reversed(list(w.items()))))
    assert r1 == r2                                                      # thứ tự đầu vào không đổi bố cục
    assert abs(sum(v[2] * v[3] for v in r1.values()) - 4000.0) < 1e-6
    rects = list(r1.values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            assert not (ox > 1e-7 and oy > 1e-7)                         # không ô nào đè lên ô khác


def test_tile_weights_use_session_median_depth_and_floor_for_missing():
    ts = [pd.Timestamp("2026-11-13 10:00:00+07:00") + pd.Timedelta(minutes=i) for i in range(3)]
    df = pd.DataFrame({"ts": ts * 2, "symbol": ["AAA"] * 3 + ["BBB"] * 3, "depth_value": [10, 30, 20, 100, 100, 100]})
    w = fg.tile_weights(df, ["AAA", "BBB", "ZZZ"], ts[0].date())
    assert w["AAA"] == 20 and w["BBB"] == 100                            # trung vị cả phiên
    assert w["ZZZ"] == 10                                                # thiếu: nửa mã nhỏ nhất (vẫn hiện ô "–")


def test_payload_has_position_color_text_and_skips_unlaid_symbols():
    cur = fg.grid_state(_df(), ["AAA", "BBB", "DDD"], T0)
    pay = fg.tiles_payload(cur, {"AAA": (0, 0, 50, 46), "BBB": (50, 0, 50, 46)}, 100.0, 46.0)
    assert [t["sym"] for t in pay] == ["AAA", "BBB"]                         # DDD không có trong bố cục: bỏ
    a, b = pay
    assert a["x"] == 0 and a["w"] == 50 and a["h"] == 100 and b["x"] == 50
    assert a["text"] == "0,5" and a["bg"] == fg.lrs_color(0.5) and a["cls"] == "ok"
    assert b["cls"] == "md" and b["text"] == "2,4"                           # Chú ý: viền cam ở phía JS
    assert "LRS 0,5" in a["title"]


def test_payload_for_missing_score_is_dash_dashed_tile():
    cur = fg.grid_state(_df(), ["DDD"], T0)
    t = fg.tiles_payload(cur, {"DDD": (0, 0, 10, 10)})[0]
    assert t["text"] == "–" and t["cls"] == "na" and t["bg"] == "#ffffff" and "không có điểm" in t["title"]

