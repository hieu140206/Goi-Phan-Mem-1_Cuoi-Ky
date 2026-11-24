"""Kiểm chứng cảnh báo thanh khoản trên dữ liệu NEO đã ghi:  python scripts/validate_alerts.py [--boot 2000]

Ba phần (logic ở src/analytics/validation.py, có test):
  1. dạng chữ U của spread và độ sâu trong ngày;
  2. event study: sau khi có cảnh báo, thanh khoản có còn xấu hơn nhóm đối chứng không;
  3. độ nhạy ngưỡng, chọn trên các phiên đầu và báo kết quả trên các phiên sau.
Ghi CSV và biểu đồ vào report/kiem-chung/. Chỉ ĐỌC market.db, không sửa gì. Mất khoảng 1 đến 2 phút.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
logging.disable(logging.CRITICAL)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import plotly.io as pio  # noqa: E402

from analytics.baseline import apply_alert_rules  # noqa: E402
from analytics.validation import (HORIZONS, add_path_columns, pick_on_train, run_event_study, sensitivity,  # noqa: E402
                                  u_fit, u_profile, u_sign_test)
from app import shared  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

OUT = ROOT / "report" / "kiem-chung"
BLUE, RED, GREY = "#1d5fbf", "#c4242a", "#9a9a9a"
GRID = {"threshold": [2.0, 2.5, 3.0, 3.5, 4.0], "max_depth_ratio": [0.3, 0.4, 0.5, 0.6], "min_spread_ratio": [1.5, 2.0, 2.5, 3.0],
        "spread_tail": [0.01, 0.02, 0.05, 0.1, 0.2], "persist": [1, 2, 3, 4]}
PARAM_VI = {"threshold": "z độ sâu (ngưỡng)", "max_depth_ratio": "độ sâu tối đa (x trung vị)", "min_spread_ratio": "spread tối thiểu (x trung vị)",
            "spread_tail": "đuôi spread (tỷ lệ)", "persist": "số lần chụp liên tiếp"}


def load() -> pd.DataFrame:
    p = shared.DEFAULT_PARAMS
    db = str(get_settings().db_path)
    out = shared.analyze(shared.SRC_DB, db, shared.source_version(shared.SRC_DB), int(p["max_sessions"]), float(p["threshold"]),
                         p["w_spread"], p["w_depth"], p["w_imb"], special_version=shared.special_days_version())
    return out[out["src"] == "NEO"].reset_index(drop=True)


def layout(fig: go.Figure, title: str, h: int = 380) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=14)), height=h, template="plotly_white", margin=dict(l=56, r=16, t=48, b=48),
                      font=dict(family="Geist, Arial, sans-serif", size=12), legend=dict(orientation="h", y=-0.2))
    return fig


def part_u(neo: pd.DataFrame, n_boot: int) -> tuple[pd.DataFrame, list[go.Figure]]:
    rows, figs = [], []
    for value, label in (("rel_spread_bps", "Spread (bps)"), ("depth_value", "Độ sâu 3 mức (đ)")):
        prof, det = u_profile(neo, value)
        fit, sign = u_fit(det, n_boot=n_boot), u_sign_test(det)
        rows.append({"biến": label, **fit, **{f"dấu_{k}": v for k, v in sign.items()}})
        prof.to_csv(OUT / f"chu_u_{value}.csv", index=False, encoding="utf-8-sig")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=prof["clock"], y=prof["q75"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=prof["clock"], y=prof["q25"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(29,95,191,.15)",
                                 name="khoảng 25%-75%"))
        fig.add_trace(go.Scatter(x=prof["clock"], y=prof["median"], mode="lines+markers", line=dict(color=BLUE, width=2), name="trung vị"))
        fig.add_hline(y=1, line=dict(color=GREY, dash="dot"))
        figs.append(layout(fig, f"{label} theo giờ giao dịch, chia cho trung vị của chính mã trong ngày ({fit['verdict']}; cong {fit['curvature']:+.2f}, "
                                f"95% từ {fit['ci_low']:+.2f} đến {fit['ci_high']:+.2f})"))
    return pd.DataFrame(rows), figs


def part_event(neo: pd.DataFrame, n_boot: int) -> tuple[pd.DataFrame, list[go.Figure]]:
    d = add_path_columns(neo)
    res = run_event_study(d, rules=apply_alert_rules(d), k=5, window=10, seed=0, n_boot=n_boot)
    allres = pd.concat(res.values(), ignore_index=True)
    allres.to_csv(OUT / "event_study.csv", index=False, encoding="utf-8-sig")
    figs = []
    for name in ("spread", "độ sâu"):
        r = res[name]
        for outcome, title in (("spread_ratio", "spread / trung vị mốc"), ("depth_ratio", "độ sâu / trung vị mốc")):
            s = r[(r["outcome"] == outcome)].sort_values("h")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=s["h"], y=s["mean_control"], mode="lines+markers", line=dict(color=GREY), name="đối chứng"))
            fig.add_trace(go.Scatter(x=s["h"], y=s["mean_event"], mode="lines+markers", line=dict(color=RED), name="sau cảnh báo"))
            fig.add_vline(x=0, line=dict(color=GREY, dash="dot"))
            fig.update_xaxes(title="phút so với lần chụp mở đầu đợt cảnh báo (0 = lúc cảnh báo)")
            figs.append(layout(fig, f"Cảnh báo {name}: {title} (n = {int(s['n'].max())} đợt; h ≤ 0 là vòng tròn vì cảnh báo được định nghĩa bằng chính các đại lượng này)"))
    return allres, figs


def part_threshold(neo: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[go.Figure]]:
    d = add_path_columns(neo)
    days = sorted(d.loc[d["n_hist"].notna(), "ts"].dt.date.unique())
    half = int(np.ceil(len(days) / 2))
    train, test = set(days[:half]), set(days[half:])
    table = sensitivity(d, GRID, train, test, k=3, seed=0)
    pick = pick_on_train(table, max_alert_share=0.05)
    table.to_csv(OUT / "nguong_do_nhay.csv", index=False, encoding="utf-8-sig")
    pick.to_csv(OUT / "nguong_chon_tren_train.csv", index=False, encoding="utf-8-sig")
    pd.Series({"train": [str(x) for x in sorted(train)], "test": [str(x) for x in sorted(test)]}).to_json(OUT / "nguong_tach_phien.json", force_ascii=False, indent=1)
    figs = []
    n_days = len(days)
    for param, vals in GRID.items():
        t = table[table["param"] == param]
        default_events = table.iloc[0]["n_events"]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=[str(v) for v in t["value"]], y=t["n_events"] / n_days, marker_color=BLUE, name="đợt cảnh báo mỗi phiên"))
        fig.add_hline(y=default_events / n_days, line=dict(color=GREY, dash="dot"))
        fig.update_xaxes(title=PARAM_VI[param])
        figs.append(layout(fig, f"Số đợt cảnh báo mỗi phiên khi đổi {PARAM_VI[param]} (đường chấm: mặc định)", 300))
    return table, pick, figs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boot", type=int, default=2000, help="Số lần lấy lại mẫu bootstrap (mặc định 2000)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    neo = load()
    print(f"Dữ liệu: {len(neo):,} lần chụp NEO, {neo['ts'].dt.date.nunique()} phiên, {neo['symbol'].nunique()} mã")

    u_tab, u_figs = part_u(neo, args.boot)
    u_tab.to_csv(OUT / "chu_u_tong_hop.csv", index=False, encoding="utf-8-sig")
    print("\n=== 1. Dạng chữ U ===")
    print(u_tab[["biến", "verdict", "curvature", "ci_low", "ci_high", "ends_over_mid_fitted", "vertex_clock", "share_days_curved_up", "dấu_n_pairs",
                 "dấu_share", "dấu_p_value", "dấu_median_ends_over_mid"]].round(4).to_string(index=False))

    e_tab, e_figs = part_event(neo, args.boot)
    print("\n=== 2. Event study (hiệu = sau cảnh báo trừ đối chứng; khoảng tin cậy bootstrap theo ngày) ===")
    show = e_tab[(e_tab["h"] > 0) & e_tab["outcome"].isin(["spread_ratio", "depth_ratio", "absret_bps"])]
    print(show[["events", "outcome", "h", "n", "n_days", "mean_event", "mean_control", "diff", "median_diff", "ci_low", "ci_high", "share_pos"]].round(3).to_string(index=False))

    t_tab, pick, t_figs = part_threshold(neo)
    print("\n=== 3. Độ nhạy ngưỡng ===")
    print(t_tab[["param", "value", "n_events", "n_events_train", "n_events_test", "alert_row_share", "spread_diff_train_h5", "spread_diff_test_h5",
                 "depth_diff_train_h5", "depth_diff_test_h5"]].round(3).to_string(index=False))
    print("\nChọn trên train, báo trên test:")
    print(pick.round(3).to_string(index=False))

    html = ["<html><head><meta charset='utf-8'><title>Kiểm chứng cảnh báo</title></head><body style='font-family:Arial;max-width:1100px;margin:auto'>",
            "<h1>Kiểm chứng cảnh báo thanh khoản</h1><p>Sinh bởi scripts/validate_alerts.py. Giải thích và kết luận nằm ở KET_QUA.md.</p>"]
    for title, figs in (("1. Dạng chữ U trong ngày", u_figs), ("2. Event study", e_figs), ("3. Độ nhạy ngưỡng", t_figs)):
        html.append(f"<h2>{title}</h2>")
        html += [pio.to_html(f, full_html=False, include_plotlyjs="cdn" if len(html) == 3 else False) for f in figs]
    html.append("</body></html>")
    (OUT / "kiem_chung.html").write_text("\n".join(html), encoding="utf-8")
    print(f"\nĐã ghi CSV và kiem_chung.html vào {OUT}")


if __name__ == "__main__":
    main()
