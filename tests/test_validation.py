"""Kiểm chứng cảnh báo (analytics/validation.py): dữ liệu tổng hợp có đáp án biết trước, để chắc các hàm đo ĐÚNG trước khi tin vào số trên dữ liệu thật."""
import numpy as np
import pandas as pd
import pytest

from analytics.baseline import apply_alert_rules, tod_bucket
from analytics.validation import (add_path_columns, clock_label, event_study, near_flag, pick_controls, pick_on_train, run_event_study,
                                  run_setting, sensitivity, study_specs, trading_minute, u_fit, u_profile, u_sign_test)

TZ = "Asia/Ho_Chi_Minh"


# ---------------- giờ giao dịch ----------------
def test_trading_minute_skips_the_lunch_break():
    ts = pd.Series(pd.to_datetime(["2026-11-20 09:15", "2026-11-20 11:29", "2026-11-20 13:00", "2026-11-20 14:29"]).tz_localize(TZ))
    assert trading_minute(ts).tolist() == [0, 134, 135, 224]
    assert [clock_label(x) for x in (0, 134, 135, 224)] == ["09:15", "11:29", "13:00", "14:29"]


# ---------------- 1. chữ U ----------------
def make_shape(shape, days=8, symbols=("A", "B", "C"), noise=0.03, seed=0):
    """Spread = 1 x hình dạng theo giờ giao dịch. 'u': cao hai đầu, thấp giữa; 'inv': ngược lại; 'flat': phẳng."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.bdate_range("2026-11-02", periods=days):
        for s in symbols:
            for tau in range(0, 225, 3):
                m = 555 + tau if tau < 135 else 780 + (tau - 135)
                x = (tau - 112) / 112
                f = {"u": 1 + 0.8 * x * x, "inv": 2 - 0.8 * x * x, "flat": 1.0}[shape]
                ts = pd.Timestamp(d.date().isoformat(), tz=TZ) + pd.Timedelta(minutes=m)
                rows.append({"symbol": s, "ts": ts, "rel_spread_bps": 20 * f * rng.lognormal(0, noise)})
    return pd.DataFrame(rows)


def test_u_shape_is_detected_and_vertex_is_near_the_middle():
    prof, det = u_profile(make_shape("u"))
    fit = u_fit(det, n_boot=300)
    assert fit["verdict"] == "chữ U" and fit["curvature"] > 0 and fit["ci_low"] > 0 and fit["ends_over_mid_fitted"] > 1.5
    assert 0.35 * 225 < fit["vertex_minute"] < 0.65 * 225
    ends = prof.iloc[[0, -1]]["median"].mean()
    middle = prof[(prof["bin"] >= 90) & (prof["bin"] <= 120)]["median"].mean()
    assert ends > 1.3 * middle


def test_statistically_significant_but_tiny_shape_is_called_very_weak_not_u():
    # hai đầu chỉ cao hơn giữa 2%: nhiều dữ liệu nên có ý nghĩa thống kê, nhưng không được gọi là chữ U
    df = make_shape("u", noise=0.002)
    df["rel_spread_bps"] = df["rel_spread_bps"] / (1 + 0.8 * ((df["ts"].dt.hour * 60 + df["ts"].dt.minute).map(
        lambda m: ((m - 555 if m < 720 else 135 + m - 780) - 112) / 112)) ** 2) * (1 + 0.02 * ((df["ts"].dt.hour * 60 + df["ts"].dt.minute).map(
        lambda m: ((m - 555 if m < 720 else 135 + m - 780) - 112) / 112)) ** 2)
    fit = u_fit(u_profile(df)[1], n_boot=300)
    assert fit["ci_low"] > 0 and fit["ends_over_mid_fitted"] < 1.05 and fit["verdict"].startswith("chữ U rất yếu")


def test_inverted_u_and_flat_are_not_called_u():
    assert u_fit(u_profile(make_shape("inv"))[1], n_boot=300)["verdict"] == "chữ U ngược"
    flat = u_fit(u_profile(make_shape("flat"))[1], n_boot=300)
    assert flat["verdict"] == "không rõ" and flat["ci_low"] < 0 < flat["ci_high"]


def test_sign_test_counts_symbol_days_where_ends_exceed_the_middle():
    _, det = u_profile(make_shape("u"))
    r = u_sign_test(det)
    assert r["n_pairs"] == 24 and r["share"] == 1.0 and r["p_value"] < 1e-6 and r["median_ends_over_mid"] > 1.3
    _, det2 = u_profile(make_shape("flat", noise=0.2))
    r2 = u_sign_test(det2)
    assert 0.1 < r2["share"] < 0.9 and r2["p_value"] > 0.01          # không có dạng thì không "tìm thấy" dạng


# ---------------- 2. event study ----------------
DAYS = [d.date().isoformat() for d in pd.bdate_range("2026-11-02", periods=8)]


def panel(persist, symbols=("A", "B"), drop=None):
    """Mỗi mã 8 phiên x 90 lần chụp (10:00-11:29). Chỉ các phiên CHẴN (thứ 0, 2, 4, 6) có sự kiện: hai lần chụp liền ở m = 40, 41 có spread xấu
    (alert_start ở m = 41), rồi xấu kéo dài thêm `persist` lần chụp (persist = 0: chỉ thoáng qua). Các phiên lẻ sạch, làm nguồn đối chứng."""
    rows = []
    for di, day in enumerate(DAYS):
        for s in symbols:
            for m in range(90):
                ts = pd.Timestamp(f"{day} 10:00", tz=TZ) + pd.Timedelta(minutes=m)
                if drop and (s, ts) in drop:
                    continue
                hot = di % 2 == 0 and (m in (40, 41) or 42 <= m < 42 + persist)
                rows.append({"ts": ts, "symbol": s, "spread_ticks": 2.0 if hot else 1.0, "spread_ratio": 3.0 if hot else 1.0,
                             "spread_tail_share": 0.01 if hot else 0.5, "z_depth": 0.0, "depth_ratio": 1.0, "n_hist": 100.0,
                             "mid": 20_000.0 + (m % 7) * 5})
    d = pd.DataFrame(rows)
    d["bucket"] = tod_bucket(d["ts"])
    return add_path_columns(d)


def _row(res, outcome, h):
    r = res[(res["outcome"] == outcome) & (res["h"] == h)]
    return r.iloc[0]


def test_forward_values_are_looked_up_by_symbol_and_time_and_missing_snapshots_are_nan():
    t = pd.Timestamp(f"{DAYS[0]} 10:41", tz=TZ)
    d = panel(10, drop={("A", t + pd.Timedelta(minutes=5))})
    row = d[(d["symbol"] == "A") & (d["ts"] == t)].iloc[0]
    assert np.isnan(row["spread_ratio_h+5"])                                    # lần chụp t+5 bị thiếu: NaN, không điền
    assert row["spread_ratio_h+1"] == 3.0 and row["spread_ratio_h-1"] == 3.0   # t+1 và t-1 đều đang xấu
    assert row["spread_ratio_h-15"] == 1.0
    b = d[(d["symbol"] == "B") & (d["ts"] == t)].iloc[0]
    assert b["spread_ratio_h+5"] == 3.0                                          # mã khác không bị ảnh hưởng
    assert row["absret_h+1"] == abs(d[(d["symbol"] == "A") & (d["ts"] == t + pd.Timedelta(minutes=1))]["mid"].iloc[0] - row["mid"]) / row["mid"] * 1e4


def test_controls_are_same_symbol_same_bucket_and_away_from_any_flag():
    d = panel(0)
    r = apply_alert_rules(d)
    near = near_flag(r, "raw_flag", 10).to_numpy()
    ok = d["n_hist"].notna().to_numpy() & ~near & ~r["is_alert"].to_numpy()
    pos = np.flatnonzero(r["alert_start"].to_numpy())
    ctrls = pick_controls(d, pos, ok, k=3, seed=1)
    assert len(pos) == 8 and all(len(c) == 3 for c in ctrls)
    for p, c in zip(pos, ctrls):
        assert (d.loc[c, "symbol"] == d.loc[p, "symbol"]).all() and (d.loc[c, "bucket"] == d.loc[p, "bucket"]).all()
        assert not near[c].any() and not d.loc[c, "ts"].isin([d.loc[p, "ts"]]).any()
        for q in c:                                                              # không có cờ ở chính nó và ở 10 lần chụp trước nó
            same = r[(r["symbol"] == d.loc[q, "symbol"]) & (r["ts"].dt.date == d.loc[q, "ts"].date())]
            assert not same[(same["ts"] <= d.loc[q, "ts"]) & (same["ts"] >= d.loc[q, "ts"] - pd.Timedelta(minutes=10))]["raw_flag"].any()
    again = pick_controls(d, pos, ok, k=3, seed=1)
    assert all((a == b).all() for a, b in zip(ctrls, again))                     # cùng seed: cùng đối chứng


def test_event_study_finds_persistence_and_does_not_invent_it():
    persistent = run_event_study(panel(12), n_boot=500, window=3)["tất cả"]      # vùng loại quanh cờ chỉ 3 lần chụp để còn đối chứng
    transient = run_event_study(panel(0), n_boot=500, window=3)["tất cả"]
    for res, expect_effect in ((persistent, True), (transient, False)):
        at0 = _row(res, "spread_ratio", 0)
        assert at0["diff"] == pytest.approx(2.0, abs=0.01)                          # vòng tròn: tại t0 luôn xấu vì cảnh báo được định nghĩa bằng nó
        h5 = _row(res, "spread_ratio", 5)
        if expect_effect:
            assert h5["diff"] > 1.5 and h5["ci_low"] > 1.0 and h5["share_pos"] == 1.0   # xấu kéo dài: hiệu gần 2; thấp hơn 2 một chút vì vài đối
            # chứng nằm ngay trước vùng xấu nên tương lai của chúng cũng xấu (hành vi không điều kiện, không phải lỗi đo)
        else:
            assert abs(h5["diff"]) < 0.25                                           # thoáng qua: sau 5 lần chụp đã như đối chứng
    assert _row(persistent, "spread_ratio", 5)["n"] == 8 and _row(persistent, "spread_ratio", 5)["n_days"] == 4


def test_event_study_pre_event_path_is_flat_before_the_event():
    res = run_event_study(panel(12), n_boot=300, window=3)["tất cả"]
    assert abs(_row(res, "spread_ratio", -15)["diff"]) < 0.25
    assert abs(_row(res, "spread_ratio", -5)["diff"]) < 0.25
    assert _row(res, "spread_ratio", -1)["diff"] == pytest.approx(2.0, abs=0.01)             # lần chụp ngay trước đã là lần chụp đầu của đợt


def test_event_study_splits_by_alert_type_and_reports_events_without_controls():
    out = run_event_study(panel(3), n_boot=200, window=3)
    assert set(out) == {"tất cả", "spread", "độ sâu"}
    assert out["spread"]["n_events_total"].iloc[0] == 8 and out["độ sâu"]["n_events_total"].iloc[0] == 0
    assert out["độ sâu"]["n"].eq(0).all()                                          # không có sự kiện độ sâu: không bịa số


def test_apply_alert_rules_matches_the_detector_on_real_pipeline_columns():
    from analytics.baseline import detect_anomalies_tod
    from finance.liquidity import add_liquidity_metrics
    rng = np.random.default_rng(4)
    rows = []
    for day in DAYS[:7]:
        for t in pd.date_range(f"{day} 10:00", f"{day} 10:59", freq="1min", tz=TZ):
            q = 5000.0 * rng.lognormal(0, 0.1) * (0.05 if (day == DAYS[6] and t.minute in (30, 31)) else 1.0)
            r = {"ts": t, "symbol": "AAA"}
            for i in (1, 2, 3):
                r[f"bid_px{i}"], r[f"ask_px{i}"] = 20_000.0 - (i - 1) * 50, 20_050.0 + (i - 1) * 50
                r[f"bid_qty{i}"], r[f"ask_qty{i}"] = q, q * rng.uniform(0.8, 1.25)
            rows.append(r)
    det = detect_anomalies_tod(add_liquidity_metrics(pd.DataFrame(rows)))
    again = apply_alert_rules(det.drop(columns=["raw_flag", "is_alert", "alert_start", "alert_type", "severity"]))
    for c in ("raw_flag", "is_alert", "alert_start", "alert_type", "severity"):
        assert again[c].tolist() == det[c].tolist()
    assert det["alert_start"].sum() >= 1


# ---------------- 3. độ nhạy ngưỡng ----------------
def test_stricter_threshold_never_gives_more_alerts_and_train_test_are_separated():
    d = panel(12)
    train, test = set(pd.to_datetime(DAYS[:4]).date), set(pd.to_datetime(DAYS[4:]).date)
    loose = run_setting(d, {"min_spread_ratio": 1.5}, train, test, k=3, window=3)
    strict = run_setting(d, {"min_spread_ratio": 5.0}, train, test, k=3, window=3)           # spread_ratio của dữ liệu thử chỉ 3: không còn cảnh báo nào
    assert loose["n_events"] == 8 and strict["n_events"] == 0
    assert loose["n_events_train"] == 4 and loose["n_events_test"] == 4
    assert strict["alert_row_share"] == 0.0 and np.isnan(strict["spread_diff_test_h5"])


def test_sensitivity_table_and_pick_on_train_report_test_results_for_default_and_chosen():
    d = panel(12)
    train, test = set(pd.to_datetime(DAYS[:4]).date), set(pd.to_datetime(DAYS[4:]).date)
    table = sensitivity(d, {"min_spread_ratio": [1.5, 2.0, 5.0], "spread_tail": [0.02, 0.05], "persist": [1, 2]}, train, test, k=3, window=3)
    assert table.iloc[0]["param"] == "mặc định" and len(table) == 1 + 3 + 2 + 2
    pick = pick_on_train(table, max_alert_share=1.0, min_events_train=1, min_type_n=1)
    assert {"min_spread_ratio", "spread_tail", "persist"} <= set(pick["param"])
    row = pick[pick["param"] == "min_spread_ratio"].iloc[0]
    assert row["chọn trên train"] in (1.5, 2.0)                                      # 5,0 không có sự kiện nào nên không thể thắng
    assert row["hiệu test h10 (chọn)"] > 0.5 and row["n test (chọn)"] == 4


def test_study_specs_cover_every_horizon_and_the_independent_outcome():
    specs = study_specs()
    assert ("absret_bps", 5, "absret_h+5") in specs and ("spread_ratio", -15, "spread_ratio_h-15") in specs
    assert not any(name == "absret_bps" and h <= 0 for name, h, _ in specs)
