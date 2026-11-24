"""Bảo đảm xuyên suốt của đường ống phân tích: không nhìn trước (cả ngưỡng LRS và z), không NaN ở nhãn và trạng thái, mã mới thiếu lịch sử,
đơn vị giá. Dùng dữ liệu tổng hợp nhiều mã nhiều phiên, chạy đúng các bước của shared.analyze nhưng không cần Streamlit."""
import numpy as np
import pandas as pd

from analytics.baseline import STATUS_NA, STATUS_OK, detect_anomalies_tod
from analytics.lrs import compute_lrs, lrs_thresholds_past, lrs_tier
from analytics.screener import GATE_UNRATED, liquidity_gate
from finance.absorption import add_absorption
from finance.liquidity import add_liquidity_metrics, add_window_stats, rank_symbols
from finance.quality import price_unit_check

TZ = "Asia/Ho_Chi_Minh"
QTY = [f"{side}_qty{i}" for side in ("bid", "ask") for i in (1, 2, 3)]
RAW = ["ts", "symbol", "total_vol", "last_px", *[f"{side}_px{i}" for side in ("bid", "ask") for i in (1, 2, 3)], *QTY]   # cột thô, trước khi tính chỉ số
DAYS = [d.date().isoformat() for d in pd.bdate_range("2026-10-19", periods=9)]


def make(symbols=("A", "B", "C", "D"), days=DAYS, depress=(), seed=5):
    """Mỗi phiên 10:00-10:59 và 13:00-13:59 một lần chụp/phút. `depress` = {(mã, thời điểm)}: độ sâu rút còn 5% ở các thời điểm đó."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in days:
        ts = pd.date_range(f"{day} 10:00", f"{day} 10:59", freq="1min", tz=TZ).append(
            pd.date_range(f"{day} 13:00", f"{day} 13:59", freq="1min", tz=TZ))
        cum = {s: 0.0 for s in symbols}
        for t in ts:
            for k, s in enumerate(symbols):
                q = (3000.0 + 1500 * k) * rng.lognormal(0, 0.15) * (0.05 if (s, t) in depress else 1.0)
                skew = rng.uniform(0.7, 1.3)
                cum[s] += rng.uniform(0, 400)
                r = {"ts": t, "symbol": s, "total_vol": cum[s], "last_px": 20_000.0 + 1000 * k}
                tick = 1 + (rng.random() < 0.15)                       # đôi khi spread 2 bước giá
                for i in (1, 2, 3):
                    r[f"bid_px{i}"] = 20_000.0 + 1000 * k - (i - 1) * 50
                    r[f"ask_px{i}"] = 20_000.0 + 1000 * k + 50 * tick + (i - 1) * 50
                    r[f"bid_qty{i}"], r[f"ask_qty{i}"] = q, q * skew
                rows.append(r)
    return add_liquidity_metrics(pd.DataFrame(rows))


def pipeline(df):
    """Các bước của shared.analyze (không cache, không SSI)."""
    out = add_absorption(detect_anomalies_tod(df))
    out["lrs"] = compute_lrs(out)
    thr = lrs_thresholds_past(out["lrs"], out["ts"], min_obs=300)
    out["lrs_watch"], out["lrs_high"] = thr["watch"], thr["high"]
    out["lrs_tier"] = lrs_tier(out["lrs"], thr)
    return add_window_stats(out)


COLS = ["z_spread", "z_depth", "z_imb", "base_depth", "base_spread_ticks", "spread_ratio", "spread_tail_share", "depth_ratio",
        "raw_flag", "is_alert", "alert_start", "alert_type", "severity", "baseline_status", "baseline_reason", "thin_no_trade",
        "lrs", "lrs_watch", "lrs_high", "lrs_tier", "win_spread_bps", "win_depth", "win_abs_imb", "win_n"]


# ---------------- 1. không nhìn trước ----------------
def test_results_up_to_t_are_identical_when_more_data_is_added_after_t():
    t_hit = pd.Timestamp(f"{DAYS[7]} 10:30", tz=TZ)                       # sự kiện thật ở phiên 8 (trước mốc cắt)
    depress = {("A", t_hit), ("A", t_hit + pd.Timedelta("1min")), ("B", pd.Timestamp(f"{DAYS[8]} 13:40", tz=TZ))}
    full_df = make(depress=depress)
    cut = pd.Timestamp(f"{DAYS[8]} 13:20", tz=TZ)                         # giữa phiên cuối, trước sự kiện của B
    full = pipeline(full_df).set_index(["symbol", "ts"]).sort_index()
    short = pipeline(full_df[full_df["ts"] <= cut].reset_index(drop=True)).set_index(["symbol", "ts"]).sort_index()
    assert full["alert_start"].any() and full["lrs_watch"].notna().any()   # dữ liệu thử có sự kiện và có ngưỡng: so sánh có nghĩa
    same = full.loc[short.index, COLS]
    pd.testing.assert_frame_equal(same, short[COLS], check_exact=True)     # giống hệt, kể cả z, P95, P99 và cửa sổ trượt


def test_changing_future_values_does_not_change_the_past():
    base = make()
    cut = pd.Timestamp(f"{DAYS[8]} 10:30", tz=TZ)
    raw = base[RAW].copy()
    raw.loc[raw["ts"] > cut, QTY] = 1.0                                    # phá nát toàn bộ khối lượng sau mốc cắt
    wrecked = add_liquidity_metrics(raw)
    a = pipeline(base).set_index(["symbol", "ts"]).sort_index()
    b = pipeline(wrecked).set_index(["symbol", "ts"]).sort_index()
    past = a.index.get_level_values("ts") <= cut
    pd.testing.assert_frame_equal(a.loc[past, COLS], b.loc[past, COLS], check_exact=True)


# ---------------- 2. không NaN ở nhãn và trạng thái; mã mới ----------------
def test_labels_and_statuses_are_never_blank_or_nan():
    out = pipeline(make())
    for c in ("baseline_status", "baseline_reason", "lrs_tier"):
        assert out[c].notna().all(), c
    assert out["baseline_status"].isin([STATUS_OK, STATUS_NA]).all()
    assert out["lrs_tier"].isin(["Bình thường", "Chú ý", "Cao", STATUS_NA]).all()          # không còn chuỗi rỗng
    assert not np.isinf(out[["z_spread", "z_depth", "z_imb", "lrs"]].to_numpy(dtype=float)).any()   # không inf lọt vào điểm
    no_base = out["baseline_status"] == STATUS_NA
    assert (out.loc[no_base, "baseline_reason"].str.len() > 0).all()


def test_new_symbol_with_short_history_is_unrated_and_never_called_pass():
    old = make(("A", "B", "C"))
    new = make(("NEW",), days=DAYS[-3:], seed=9)                          # mã mới: chỉ 3 phiên cuối
    out = pipeline(pd.concat([old, new], ignore_index=True))
    last_day = out[out["ts"].dt.date == pd.Timestamp(DAYS[-1]).date()]
    assert (last_day.loc[last_day["symbol"] == "NEW", "baseline_status"] == STATUS_NA).all()
    assert (last_day.loc[last_day["symbol"] != "NEW", "baseline_status"] == STATUS_OK).all()
    assert last_day.loc[last_day["symbol"] == "NEW", "baseline_reason"].str.contains("cần ≥5 phiên").all()
    # cổng: dựng baseline_ok như shared.liquidity_ranking
    ranking = rank_symbols(last_day)
    has_base = last_day.groupby("symbol")["n_hist"].apply(lambda s: bool(s.notna().any()))
    ranking["baseline_ok"] = ranking["symbol"].map(has_base).astype(bool)
    gate = liquidity_gate(ranking, pd.Series(dtype=float)).set_index("symbol")
    assert gate.loc["NEW", "gate"] in (GATE_UNRATED, "Loại")              # không bao giờ "Đạt" khi chưa có mốc nền
    assert gate.loc["NEW", "gate_reason"] != ""
    assert gate.loc[["A", "B", "C"], "gate"].isin(["Đạt", "Chú ý", "Loại"]).all()


def test_the_first_sessions_have_no_alerts_but_a_clear_status():
    out = pipeline(make())
    early = out[out["ts"].dt.date <= pd.Timestamp(DAYS[4]).date()]        # 5 phiên đầu: chưa đủ 5 phiên trước
    assert (early["baseline_status"] == STATUS_NA).all() and early["is_alert"].sum() == 0
    assert early["lrs"].isna().all() and (early["lrs_tier"] == STATUS_NA).all()


# ---------------- 3. đơn vị giá ----------------
def test_price_unit_check_accepts_dong_and_flags_thousands():
    ok, med = price_unit_check(pd.DataFrame({"bid_px1": [20_000.0, 54_100.0, 9_990.0]}))
    assert ok and med == 20_000.0
    bad, med2 = price_unit_check(pd.DataFrame({"bid_px1": [20.0, 54.1, 9.99]}))        # nghìn đồng
    assert not bad and med2 == 20.0
    assert price_unit_check(pd.DataFrame({"bid_px1": []}))[0] is True                   # rỗng: không có gì để báo sai
