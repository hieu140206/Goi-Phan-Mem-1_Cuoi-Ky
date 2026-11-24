"""Kiểm chứng cảnh báo thanh khoản: dạng chữ U trong ngày, event study, và độ nhạy của ngưỡng (tách train và test theo thời gian).

Thuần pandas/numpy, không phụ thuộc Streamlit. Đầu vào là bảng kết quả phân tích (shared.analyze) của các phiên NEO.
KHÔNG đổi bất kỳ con số nào của ứng dụng: chỉ đọc và đo.

1. Dạng chữ U (u_profile, u_fit, u_sign_test): spread của một mã trong ngày, chuẩn hóa theo trung vị của chính mã đó trong ngày, vẽ theo giờ giao dịch
   (bỏ nghỉ trưa). Nghiên cứu thị trường khác (McInish và Wood 1992) thấy spread cao ở đầu và cuối phiên, thấp ở giữa. Hồi quy bậc hai trên log
   của tỷ lệ; khoảng tin cậy bootstrap theo NGÀY (các mã cùng ngày không độc lập). Phiên khớp lệnh liên tục chỉ có 9:15-14:30, không có ATO và ATC,
   nên dạng thấy được có thể khác dạng trong các nghiên cứu có đủ phiên mở và đóng cửa.

2. Event study (add_path_columns, pick_controls, event_study): sau khi Radar báo cảnh báo, thanh khoản có còn xấu ở các lần chụp SAU đó không?
   Lưu ý then chốt: cảnh báo được định nghĩa bằng chính spread và độ sâu, nên ở thời điểm t0 và trước đó spread cao là hiển nhiên (vòng tròn).
   Phần có thông tin là các lần chụp SAU t0 (h > 0): cảnh báo mang tin nếu thanh khoản xấu kéo dài hơn nhóm đối chứng. Nhóm đối chứng: các lần chụp
   của CHÍNH mã đó, cùng khung giờ, không có cờ ở lần chụp đó và W lần chụp TRƯỚC nó. KHÔNG loại theo tương lai của đối chứng: loại đối chứng vì sau đó
   yên ắng là chọn theo kết quả và làm hiệu bị thổi phồng. Hiệu = giá trị sau cảnh báo trừ trung bình các đối chứng; khoảng tin cậy bootstrap theo ngày.
   Thêm biến thứ ba độc lập với định nghĩa cảnh báo: biên độ giá tuyệt đối sau h phút (bps).

3. Độ nhạy ngưỡng (run_setting, sensitivity): đổi từng ngưỡng một, đếm cảnh báo và đo cùng hiệu ở h = 5, 10 phút. Chọn ngưỡng trên các phiên ĐẦU (train)
   rồi báo kết quả trên các phiên SAU (test), để tránh chọn ngưỡng vì kết quả đẹp trên chính dữ liệu dùng để chọn.

Giới hạn phải nêu khi dùng số: ít phiên, các mã cùng ngày tương quan (đã bootstrap theo ngày, vẫn ít cụm nên khoảng tin cậy rộng), nhiều phép so sánh một lúc.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from analytics.baseline import apply_alert_rules
from status import STATUS_OK

TRADING_MINUTES = 225                   # 9:15-11:30 (135 phút) và 13:00-14:30 (90 phút)
HORIZONS = (-15, -5, -1, 0, 1, 5, 10, 15, 30)


# ---------------------------------------------------------------- giờ giao dịch
def trading_minute(ts: pd.Series) -> pd.Series:
    """Số phút giao dịch tính từ 9:15, bỏ nghỉ trưa: 9:15 = 0, 11:30 = 135, 13:00 = 135, 14:30 = 225."""
    m = ts.dt.hour * 60 + ts.dt.minute + ts.dt.second / 60
    return pd.Series(np.where(m < 12 * 60, m - 555, 135 + (m - 780)), index=ts.index)


def clock_label(tau: float) -> str:
    m = 555 + tau if tau < 135 else 780 + (tau - 135)
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


# ---------------------------------------------------------------- 1. dạng chữ U
def u_profile(df: pd.DataFrame, value: str = "rel_spread_bps", bin_minutes: int = 15) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trả (hồ sơ theo khung, dữ liệu chi tiết). Hồ sơ: trung vị, tứ phân vị 25 và 75 của tỷ lệ (giá trị / trung vị của chính mã trong ngày)."""
    d = df[["symbol", "ts", value]].dropna(subset=[value]).copy()
    d = d[d[value] > 0]
    d["day"] = d["ts"].dt.date
    d["tau"] = trading_minute(d["ts"])
    d["ratio"] = d[value] / d.groupby(["symbol", "day"])[value].transform("median")
    d["bin"] = (d["tau"] // bin_minutes * bin_minutes).astype(int)
    g = d.groupby("bin")["ratio"]
    prof = pd.DataFrame({"median": g.median(), "q25": g.quantile(0.25), "q75": g.quantile(0.75), "n": g.size()}).reset_index()
    prof["clock"] = prof["bin"].map(clock_label)
    return prof, d[["symbol", "day", "tau", "ratio"]]


def _quad(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    c2, c1, c0 = np.polyfit(x, y, 2)
    return float(c2), float(c1), float(c0)


def u_fit(detail: pd.DataFrame, n_boot: int = 2000, seed: int = 0, min_effect: float = 1.05) -> dict:
    """Hồi quy bậc hai của log tỷ lệ theo giờ giao dịch (x = phút / 225). curvature > 0 là chữ U (cao ở hai đầu); < 0 là chữ U ngược.
    Khoảng tin cậy 95% bootstrap theo ngày. vertex là điểm cực tiểu (hoặc cực đại) tính theo phút giao dịch và giờ đồng hồ.
    Chỉ gọi là chữ U (hoặc ngược) khi có ý nghĩa thống kê VÀ độ lớn đủ lớn: hai đầu phiên cao hơn giữa phiên ít nhất `min_effect` lần (mặc định 5%).
    Có ý nghĩa thống kê mà độ lớn nhỏ xíu (dễ xảy ra với nhiều dữ liệu) thì ghi "rất yếu", không gọi là có dạng."""
    y_all = np.log(detail["ratio"].to_numpy())
    t = detail.assign(y=y_all, tau_i=detail["tau"].round().astype(int)).groupby(["day", "tau_i"])["y"].mean().reset_index()
    days = sorted(t["day"].unique())
    per_day = {d: (g["tau_i"].to_numpy() / TRADING_MINUTES, g["y"].to_numpy()) for d, g in t.groupby("day")}
    x_all, y_agg = t["tau_i"].to_numpy() / TRADING_MINUTES, t["y"].to_numpy()
    c2, c1, c0 = _quad(x_all, y_agg)
    rng = np.random.default_rng(seed)
    boots, verts = [], []
    for _ in range(n_boot):
        pick = rng.integers(0, len(days), len(days))
        xs = np.concatenate([per_day[days[i]][0] for i in pick])
        ys = np.concatenate([per_day[days[i]][1] for i in pick])
        b2, b1, _ = _quad(xs, ys)
        boots.append(b2)
        verts.append(-b1 / (2 * b2) if b2 != 0 else np.nan)
    boots, verts = np.array(boots), np.array(verts)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    vertex = -c1 / (2 * c2) if c2 != 0 else float("nan")
    day_c2 = np.array([_quad(*per_day[d])[0] for d in days if len(per_day[d][0]) >= 10])
    v_med = float(np.nanmedian(verts))
    f = lambda x: c0 + c1 * x + c2 * x * x                                     # noqa: E731
    ends_over_mid = float(np.exp((f(0.0) + f(1.0)) / 2 - f(0.5)))               # độ lớn: hai đầu so với giữa phiên (đường khớp)
    if lo > 0 and 0.1 <= v_med <= 0.9:
        verdict = "chữ U" if ends_over_mid >= min_effect else "chữ U rất yếu (có ý nghĩa thống kê nhưng độ lớn không đáng kể)"
    elif hi < 0 and 0.1 <= v_med <= 0.9:
        verdict = "chữ U ngược" if ends_over_mid <= 1 / min_effect else "chữ U ngược rất yếu (độ lớn không đáng kể)"
    else:
        verdict = "không rõ"
    return {"curvature": c2, "ci_low": float(lo), "ci_high": float(hi), "vertex_minute": vertex * TRADING_MINUTES,
            "vertex_clock": clock_label(vertex * TRADING_MINUTES) if np.isfinite(vertex) and 0 <= vertex <= 1 else "ngoài phiên",
            "share_days_curved_up": float((day_c2 > 0).mean()) if len(day_c2) else float("nan"), "n_days": len(days),
            "n_obs": len(detail), "ends_over_mid_fitted": ends_over_mid, "verdict": verdict}


def _binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return float("nan")
    p = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * p)


def u_sign_test(detail: pd.DataFrame, end_minutes: int = 30, mid: tuple[int, int] = (60, 165)) -> dict:
    """Với mỗi cặp (mã, ngày): trung bình tỷ lệ ở `end_minutes` phút đầu và cuối phiên có cao hơn khoảng giữa (phút giao dịch 60 đến 165) không.
    Kiểm định dấu hai phía (nhị thức) trên các cặp; các cặp cùng ngày không độc lập, nên đây chỉ là kiểm tra thô bổ sung cho hồi quy."""
    tau = detail["tau"]
    ends = detail[(tau < end_minutes) | (tau >= TRADING_MINUTES - end_minutes)].groupby(["symbol", "day"])["ratio"].mean()
    middle = detail[(tau >= mid[0]) & (tau < mid[1])].groupby(["symbol", "day"])["ratio"].mean()
    j = pd.concat([ends.rename("ends"), middle.rename("mid")], axis=1).dropna()
    n, k = len(j), int((j["ends"] > j["mid"]).sum())
    return {"n_pairs": n, "n_ends_higher": k, "share": k / n if n else float("nan"), "p_value": _binom_two_sided(k, n),
            "median_ends_over_mid": float((j["ends"] / j["mid"]).median()) if n else float("nan")}


# ---------------------------------------------------------------- 2. event study
def add_path_columns(df: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Thêm, với mỗi độ trễ h (phút, âm là trước): spread_ratio_h{h}, depth_ratio_h{h} (giá trị của CÙNG MÃ ở thời điểm t+h; NaN nếu lần chụp đó không
    có hoặc chưa có mốc nền) và absret_h{h} (|mid(t+h) - mid(t)| / mid(t), bps, chỉ cho h > 0). Trả bảng đã sắp theo (symbol, ts), chỉ số 0..n-1."""
    d = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    base = d.set_index(["symbol", "ts"])
    if not base.index.is_unique:
        raise ValueError("Có hai dòng cùng (mã, thời gian): làm sạch trước khi kiểm chứng.")
    for h in horizons:
        tgt = pd.MultiIndex.from_arrays([d["symbol"], d["ts"] + pd.Timedelta(minutes=h)])
        for col in ("spread_ratio", "depth_ratio"):
            d[f"{col}_h{h:+d}"] = base[col].reindex(tgt).to_numpy()
        if h > 0:
            mid = base["mid"].reindex(tgt).to_numpy()
            d[f"absret_h{h:+d}"] = np.abs(mid - d["mid"].to_numpy()) / d["mid"].to_numpy() * 1e4
    return d


def near_flag(d: pd.DataFrame, flag: str = "raw_flag", window: int = 10) -> pd.Series:
    """True ở dòng có cờ, hoặc có cờ trong `window` lần chụp (xấp xỉ phút) TRƯỚC nó, cùng mã, cùng ngày, cùng buổi. Chỉ nhìn về quá khứ: không
    dùng tương lai của dòng đó để quyết định có làm đối chứng hay không."""
    key = [d["symbol"], d["ts"].dt.date, d["ts"].dt.hour < 12]
    return d.groupby(key)[flag].transform(lambda s: s.astype(int).rolling(window + 1, min_periods=1).max()).astype(bool)


def pick_controls(d: pd.DataFrame, event_pos: np.ndarray, ctrl_ok: np.ndarray, k: int = 5, seed: int = 0) -> list[np.ndarray]:
    """Với mỗi sự kiện, chọn tối đa k đối chứng ngẫu nhiên (cố định seed) trong các dòng ctrl_ok CÙNG MÃ và CÙNG KHUNG GIỜ (cột bucket).
    Sự kiện không có đối chứng nào nhận mảng rỗng."""
    rng = np.random.default_rng(seed)
    sym, bucket = d["symbol"].to_numpy(), d["bucket"].to_numpy()
    pools: dict[tuple, list[int]] = {}
    for p in np.flatnonzero(ctrl_ok):
        pools.setdefault((sym[p], bucket[p]), []).append(int(p))
    out = []
    for p in event_pos:
        pool = pools.get((sym[p], bucket[p]), [])
        out.append(np.array(rng.choice(pool, size=min(k, len(pool)), replace=False), dtype=int) if pool else np.array([], dtype=int))
    return out


def event_study(d: pd.DataFrame, event_pos: np.ndarray, controls: list[np.ndarray], specs: list[tuple[str, int, str]],
                n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    """specs: danh sách (tên biến, h, tên cột). Mỗi dòng kết quả: số sự kiện dùng được, trung bình sự kiện, trung bình đối chứng, hiệu và khoảng tin cậy 95%
    (bootstrap theo NGÀY: lấy lại mẫu các ngày có thay thế), tỷ lệ sự kiện có hiệu dương."""
    rng = np.random.default_rng(seed)
    day_codes, uniq = pd.factorize(pd.Series(d["ts"].dt.date.to_numpy()[event_pos]))
    rows = []
    for name, h, col in specs:
        v = d[col].to_numpy(dtype=float)
        ye = v[event_pos]
        yc = np.array([np.nanmean(v[c]) if len(c) and np.isfinite(v[c]).any() else np.nan for c in controls]) if len(controls) else np.array([])
        ok = np.isfinite(ye) & np.isfinite(yc) if len(ye) else np.array([], dtype=bool)
        n = int(ok.sum())
        if n == 0:
            rows.append({"outcome": name, "h": h, "n": 0, "n_days": 0, "mean_event": np.nan, "mean_control": np.nan, "diff": np.nan,
                         "median_diff": np.nan, "ci_low": np.nan, "ci_high": np.nan, "share_pos": np.nan})
            continue
        diff, dc = (ye - yc)[ok], day_codes[ok]
        s = np.bincount(dc, weights=diff, minlength=len(uniq))
        c = np.bincount(dc, minlength=len(uniq))
        pick = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
        boot = s[pick].sum(axis=1) / np.maximum(c[pick].sum(axis=1), 1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        rows.append({"outcome": name, "h": h, "n": n, "n_days": int((c > 0).sum()), "mean_event": float(ye[ok].mean()),
                     "mean_control": float(yc[ok].mean()), "diff": float(diff.mean()), "median_diff": float(np.median(diff)),
                     "ci_low": float(lo), "ci_high": float(hi),
                     "share_pos": float((diff > 0).mean())})
    return pd.DataFrame(rows)


def study_specs(horizons: tuple[int, ...] = HORIZONS) -> list[tuple[str, int, str]]:
    specs = []
    for h in horizons:
        specs += [("spread_ratio", h, f"spread_ratio_h{h:+d}"), ("depth_ratio", h, f"depth_ratio_h{h:+d}")]
        if h > 0:
            specs.append(("absret_bps", h, f"absret_h{h:+d}"))
    return specs


def run_event_study(d: pd.DataFrame, rules: pd.DataFrame | None = None, k: int = 5, window: int = 10, seed: int = 0,
                    n_boot: int = 2000) -> dict[str, pd.DataFrame]:
    """Chạy event study cho: tất cả đợt cảnh báo, riêng cảnh báo spread, riêng cảnh báo độ sâu. `d` đã qua add_path_columns; `rules` là kết quả
    apply_alert_rules (mặc định tính từ cột của d). Sự kiện = lần chụp mở đầu đợt (alert_start) ở phiên có mốc nền."""
    r = rules if rules is not None else apply_alert_rules(d)
    ok_base = d["n_hist"].notna().to_numpy()
    ctrl_ok = ok_base & ~near_flag(r.assign(symbol=d["symbol"], ts=d["ts"]), "raw_flag", window).to_numpy() & ~r["is_alert"].to_numpy()
    start = r["alert_start"].to_numpy() & ok_base
    kinds = {"tất cả": start, "spread": start & r["alert_type"].str.contains("Spread").to_numpy(),
             "độ sâu": start & r["alert_type"].str.contains("Độ sâu").to_numpy()}
    out = {}
    for name, mask in kinds.items():
        pos = np.flatnonzero(mask)
        ctrls = pick_controls(d, pos, ctrl_ok, k=k, seed=seed)
        res = event_study(d, pos, ctrls, study_specs(), n_boot=n_boot, seed=seed)
        res.insert(0, "events", name)
        res["n_events_total"] = len(pos)
        res["n_events_without_control"] = int(sum(len(c) == 0 for c in ctrls))
        out[name] = res
    return out


# ---------------------------------------------------------------- 3. độ nhạy ngưỡng
def run_setting(d: pd.DataFrame, params: dict, train_days: set, test_days: set, k: int = 3, window: int = 10, seed: int = 0) -> dict:
    """Áp luật cảnh báo với `params` (ghi đè mặc định) và đo: số đợt, tỷ lệ lần chụp đang cảnh báo, và hiệu (sự kiện - đối chứng) ở h = 5 và 10 phút
    trên tập train và tập test. Cảnh báo spread đo bằng spread_ratio sau đó; cảnh báo độ sâu đo bằng depth_ratio sau đó (thấp hơn đối chứng là tốt)."""
    r = apply_alert_rules(d, **params)
    ok_base = d["n_hist"].notna().to_numpy()
    days = d["ts"].dt.date.to_numpy()
    ctrl_ok = ok_base & ~near_flag(r.assign(symbol=d["symbol"], ts=d["ts"]), "raw_flag", window).to_numpy() & ~r["is_alert"].to_numpy()
    start = r["alert_start"].to_numpy() & ok_base
    kind = {"spread": start & r["alert_type"].str.contains("Spread").to_numpy(), "depth": start & r["alert_type"].str.contains("Độ sâu").to_numpy()}
    res = {"n_events": int(start.sum()), "alert_row_share": float((r["is_alert"].to_numpy() & ok_base).sum() / max(ok_base.sum(), 1))}
    for split, dayset in (("train", train_days), ("test", test_days)):
        in_split = np.isin(days, list(dayset))
        res[f"n_events_{split}"] = int((start & in_split).sum())
        for typ, col in (("spread", "spread_ratio"), ("depth", "depth_ratio")):
            pos = np.flatnonzero(kind[typ] & in_split)
            ctrls = pick_controls(d, pos, ctrl_ok & in_split, k=k, seed=seed)
            for h in (5, 10):
                v = d[f"{col}_h{h:+d}"].to_numpy(dtype=float)
                ye = v[pos]
                yc = np.array([np.nanmean(v[c]) if len(c) and np.isfinite(v[c]).any() else np.nan for c in ctrls]) if len(pos) else np.array([])
                ok = np.isfinite(ye) & np.isfinite(yc) if len(pos) else np.array([], dtype=bool)
                diff = (ye - yc)[ok] if len(pos) else np.array([])
                res[f"{typ}_n_{split}_h{h}"] = int(len(diff))
                res[f"{typ}_diff_{split}_h{h}"] = float(diff.mean()) if len(diff) else np.nan
                res[f"{typ}_t_{split}_h{h}"] = float(diff.mean() / (diff.std(ddof=1) / math.sqrt(len(diff)))) if len(diff) > 2 and diff.std(ddof=1) > 0 else np.nan
    return res


def sensitivity(d: pd.DataFrame, grid: dict[str, list], train_days: set, test_days: set, k: int = 3, seed: int = 0,
                window: int = 10) -> pd.DataFrame:
    """Đổi MỘT ngưỡng một lần (các ngưỡng khác giữ mặc định) và gom kết quả. Có thêm dòng cho mặc định để so sánh."""
    rows = [{"param": "mặc định", "value": np.nan, **run_setting(d, {}, train_days, test_days, k=k, seed=seed, window=window)}]
    for param, values in grid.items():
        for v in values:
            rows.append({"param": param, "value": v, **run_setting(d, {param: v}, train_days, test_days, k=k, seed=seed, window=window)})
    return pd.DataFrame(rows)


def pick_on_train(table: pd.DataFrame, max_alert_share: float = 0.05, min_events_train: int = 100, min_type_n: int = 30) -> pd.DataFrame:
    """Với mỗi ngưỡng, chọn giá trị có ĐỘ LỚN hiệu (trung bình hiệu sự kiện - đối chứng, trung bình của h = 5 và 10 phút) lớn nhất trên tập TRAIN, trong các
    giá trị còn đủ nhiều: tối thiểu `min_events_train` đợt cảnh báo ở train, tối thiểu `min_type_n` sự kiện đo được cho loại cảnh báo liên quan, và tỷ lệ
    lần chụp đang cảnh báo không vượt `max_alert_share`. Không chọn theo thống kê t vì t tăng theo số sự kiện, sẽ luôn chọn ngưỡng lỏng nhất (nhiều sự kiện
    nhất) chứ không phải ngưỡng cho cảnh báo chất lượng nhất. Cảnh báo độ sâu: hiệu âm là tốt nên đổi dấu. Trả giá trị được chọn và hiệu của nó trên TEST,
    cạnh giá trị mặc định. Đánh đổi độ lớn và số lượng là lựa chọn phải nêu rõ: ngưỡng chặt hơn gần như luôn cho hiệu lớn hơn nhưng ít cảnh báo hơn."""
    rows = []
    which = {"threshold": "depth", "max_depth_ratio": "depth", "min_spread_ratio": "spread", "spread_tail": "spread", "persist": "spread"}
    default = table[table["param"] == "mặc định"].iloc[0]
    for param, typ in which.items():
        sub = table[(table["param"] == param) & (table["alert_row_share"] <= max_alert_share) & (table["n_events_train"] >= min_events_train)
                    & (table[f"{typ}_n_train_h10"] >= min_type_n)]
        if sub.empty:
            continue
        sign = -1.0 if typ == "depth" else 1.0
        score = sign * sub[[f"{typ}_diff_train_h5", f"{typ}_diff_train_h10"]].mean(axis=1)
        best = sub.loc[score.idxmax()] if score.notna().any() else None
        if best is None:
            continue
        rows.append({"param": param, "loại cảnh báo": typ, "chọn trên train": best["value"], "hiệu train (chọn)": float(score.max()), "n sự kiện train (chọn)": int(best["n_events_train"]),
                     "hiệu test h10 (chọn)": best[f"{typ}_diff_test_h10"], "n test (chọn)": int(best[f"{typ}_n_test_h10"]),
                     "hiệu test h10 (mặc định)": default[f"{typ}_diff_test_h10"], "n test (mặc định)": int(default[f"{typ}_n_test_h10"])})
    return pd.DataFrame(rows)
