"""Số liệu dùng chung cho mọi trang (Radar, Bộ lọc, Chi tiết mã).

Mọi trang gọi CÙNG các hàm có cache ở đây với CÙNG tham số, nên cùng một mã luôn ra cùng một con số trên mọi trang
(điểm thanh khoản, số đợt cảnh báo, LRS). Tham số phân tích người dùng chỉnh ở Radar được lưu vào st.session_state["params"]
(khóa thường, không gắn widget, nên không bị Streamlit xóa khi chuyển trang).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from analytics.baseline import detect_anomalies_tod  # noqa: E402
from analytics.lrs import DEFAULT_WEIGHTS, compute_lrs, lrs_thresholds_past, lrs_tier  # noqa: E402
from data.schema import limit_lock_side, normalize_quotes
from data.special_days import (exclude_from_baseline, load_special_days, special_day_map,  # noqa: E402
                               special_days_path)
from data.ssi import load_ssi_daily, load_ssi_minute_quotes, ssi_quote_days  # noqa: E402
from analytics.screener import (ATC_DONE, daily_closes_from_board, intraday_factors, liquidity_gate,  # noqa: E402
                                market_context, momentum, screen)
from data.overview import (breadth_frame, futures_view, index_cards, load_market_json)  # noqa: E402
from data.storage import (board_days, count_rows, load_board, load_futures, load_market_index,  # noqa: E402
                          load_quotes)
from finance.absorption import add_absorption  # noqa: E402
from finance.liquidity import add_liquidity_metrics, add_window_stats, rank_symbols, window_scores  # noqa: E402
from finance.quality import add_quality_flags, limit_touch_side, price_unit_check, quality_table  # noqa: E402
from finance.sessions import filter_continuous  # noqa: E402
from model_config import section  # noqa: E402
from status import STATUS_NA, STATUS_OK  # noqa: E402
from neo_api.config import get_settings  # noqa: E402

log = logging.getLogger(__name__)
SAMPLE_CSV = ROOT / "data_sample" / "sample_quotes.csv"
SRC_SAMPLE = "Dữ liệu mô phỏng (tệp mẫu)"
SRC_DB = "Dữ liệu NEO đã ghi (SQLite)"

# Tham số mặc định của phần phân tích (giống thanh trượt ở Radar).
_BASE = section("baseline")
DEFAULT_PARAMS = {"threshold": _BASE["z_threshold"], "max_sessions": _BASE["max_sessions"], "w_spread": DEFAULT_WEIGHTS["spread"],
                  "w_depth": DEFAULT_WEIGHTS["depth"], "w_imb": DEFAULT_WEIGHTS["imbalance"]}


def available_sources() -> list[str]:
    """Nguồn dữ liệu dùng được trên giao diện: chỉ NEO đã ghi (SSI tự bù các ngày NEO thiếu, xem load_source). Tệp mô phỏng KHÔNG còn là
    lựa chọn (quyết định 25/11/2026): mã SRC_SAMPLE vẫn giữ để kiểm thử, nhưng máy không có dữ liệu thật thì trả danh sách rỗng và trang báo rõ."""
    return [SRC_DB] if count_rows(get_settings().db_path) > 0 else []


def current_source() -> str | None:
    """Nguồn đang chọn (ở Radar); chưa chọn thì nguồn đầu tiên có dữ liệu."""
    sources = available_sources()
    chosen = st.session_state.get("source")
    return chosen if chosen in sources else (sources[0] if sources else None)


def params() -> dict:
    return {**DEFAULT_PARAMS, **st.session_state.get("params", {})}


def source_version(source: str) -> float:
    """Dấu phiên bản để cache đọc lại khi dữ liệu đổi (thời điểm sửa file)."""
    path = SAMPLE_CSV if source == SRC_SAMPLE else get_settings().db_path
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner="Đang đọc và làm sạch dữ liệu đã ghi (chỉ ở lần mở đầu tiên)...")
def load_source(source: str, db_path: str, version: float, ssi_fill: bool = True) -> tuple[pd.DataFrame, dict]:
    """Đọc, làm sạch, chỉ giữ phiên khớp lệnh liên tục (loại ATO/ATC/nghỉ trưa), tính chỉ số sổ lệnh.

    Ngày NEO không có lần chụp nào trong phiên liên tục (ví dụ bộ ghi bị dừng) mà SSI có sổ lệnh thì lấy SSI thay
    (mỗi phút một lần, cùng các phút với NEO). Ngày nào có NEO thì luôn dùng NEO. Các ngày lấy từ SSI nằm ở
    report["ssi_days"]; SSI không có giá khớp và tổng khối lượng khớp nên các cột đó để trống ở những ngày này.
    ssi_fill=False tắt việc bù này (dùng để kiểm tra số liệu NEO không đổi)."""
    raw = pd.read_csv(SAMPLE_CSV) if source == SRC_SAMPLE else load_quotes(Path(db_path))
    clean, report = normalize_quotes(raw)
    clean, dropped = filter_continuous(clean)
    report["dropped_session"] = dropped
    locked, _ = filter_continuous(report["limit_locked"])
    report["limit_locked"] = locked.assign(side=limit_lock_side(locked))[["ts", "symbol", "side"]]
    # B1: giá tốt nhất chạm trần/sàn dù còn đủ hai bên cũng không phản ánh thanh khoản: bỏ khỏi khung phân tích như dòng khóa, nhưng báo riêng.
    touch_side = limit_touch_side(clean)
    hit = touch_side != ""
    report["limit_touch"] = clean[hit].assign(side=touch_side[hit])[["ts", "symbol", "side"]]
    clean = add_quality_flags(clean[~hit])   # B5: khoảng trống và dữ liệu cũ: đánh cờ và ghi log, không loại
    report["quality"] = quality_table(raw, clean, report["limit_locked"], report["limit_touch"])
    for key, label in (("dropped_crossed_book", "sổ lệnh chéo (bán tốt nhất <= mua tốt nhất)"),
                       ("dropped_invalid_price", "giá mua hoặc bán tốt nhất <= 0"), ("dropped_duplicate", "trùng (thời gian, mã)"),
                       ("dropped_missing", "thiếu thời gian, mã hoặc giá tốt nhất")):
        if report.get(key):
            log.warning("Đã loại %d dòng %s: lỗi dữ liệu.", report[key], label)
    if len(report["limit_touch"]):
        log.info("Đã loại %d lần chụp có giá tốt nhất chạm trần/sàn (còn đủ hai bên): không dùng được cho spread.", len(report["limit_touch"]))
    # Đơn vị giá phải là đồng (kiểm một lần ở lớp nạp, không tự đổi): nếu nghi là nghìn đồng thì ghi lỗi rõ và đánh dấu để giao diện báo.
    report["price_unit_ok"], _med_px = price_unit_check(clean)
    if not report["price_unit_ok"]:
        log.error("Giá mua tốt nhất trung vị chỉ %.2f: có vẻ dữ liệu đang ở nghìn đồng thay vì đồng; spread theo bước giá và độ sâu sẽ sai.", _med_px)
    report["ssi_days"] = []
    if source == SRC_DB and ssi_fill:
        neo_days = {d.strftime("%Y-%m-%d") for d in clean["ts"].dt.date.unique()} if not clean.empty else set()
        todo = [d for d in ssi_quote_days(Path(db_path)) if d not in neo_days]
        if todo:
            s_raw = load_ssi_minute_quotes(Path(db_path), todo)
            s_clean, s_rep = normalize_quotes(s_raw)
            s_clean, s_drop = filter_continuous(s_clean)
            s_clean = add_quality_flags(s_clean)
            report["ssi_days"] = sorted(s_clean["ts"].dt.date.unique()) if not s_clean.empty else []
            report["ssi_rows"] = len(s_clean)
            report["dropped_session"] += s_drop
            s_lock, _ = filter_continuous(s_rep["limit_locked"])
            report["limit_locked"] = pd.concat(
                [report["limit_locked"], s_lock.assign(side=limit_lock_side(s_lock))[["ts", "symbol", "side"]]],
                ignore_index=True)
            clean = pd.concat([clean, s_clean], ignore_index=True)
    return add_liquidity_metrics(clean), report


@st.cache_data(show_spinner="Đang tính cảnh báo và điểm thanh khoản cho mọi phiên đã ghi, lần đầu mất vài giây...")
def analyze(source: str, db_path: str, version: float, max_sessions: int, threshold: float,
            w_spread: float, w_depth: float, w_imb: float, ssi_fill: bool = True, special_version: float = 0.0) -> pd.DataFrame:
    """Cảnh báo bất thường, tỷ lệ hấp thụ và điểm LRS. Tính trên toàn bộ lịch sử để đủ dữ liệu khởi động.

    Các ngày lấy từ SSI (cột `src` = "SSI") KHÔNG được dùng làm mốc hay làm nền tính ngưỡng cho ngày NEO, nên số của
    các ngày NEO không đổi dù có thêm ngày SSI; bản thân ngày SSI được so với mốc là các phiên NEO trước đó."""
    df, report = load_source(source, db_path, version, ssi_fill)
    ssi_days = frozenset(report.get("ssi_days", []))
    # Ngày đặc biệt (data/special_days.csv): vẫn tính bình thường nhưng gắn cờ, và (config) không làm mốc nền cho ngày khác.
    # special_version (thời điểm sửa tệp) chỉ để cache đọc lại khi bạn sửa tệp ngày đặc biệt.
    sp_map = special_day_map(load_special_days())
    data_days = set(df["ts"].dt.date.unique()) if not df.empty else set()
    sp_days = frozenset(d for d in sp_map if d in data_days)
    no_base = ssi_days | sp_days if exclude_from_baseline() else ssi_days
    # Cảnh báo so với cùng khung giờ ở các phiên trước (analytics/baseline.py), không dùng cửa sổ trượt.
    out = add_absorption(detect_anomalies_tod(df, threshold=threshold, max_sessions=max_sessions,
                                              no_baseline_days=no_base),
                         no_baseline_days=no_base)
    out["special_day"] = out["ts"].dt.date.map(sp_map).fillna("")
    out["src"] = np.where(out["ts"].dt.date.isin(ssi_days), "SSI", "NEO")
    is_ssi = out["src"] == "SSI"
    out["lrs"] = compute_lrs(out, {"spread": w_spread, "depth": w_depth, "imbalance": w_imb})
    # Ngưỡng Chú ý/Cao tại mỗi thời điểm chỉ dùng điểm LRS có trước thời điểm đó (không nhìn trước), không gồm điểm SSI.
    pool_excl = is_ssi | out["ts"].dt.date.isin(sp_days) if exclude_from_baseline() else is_ssi
    thr = lrs_thresholds_past(out["lrs"].where(~pool_excl), out["ts"])
    out["lrs_watch"], out["lrs_high"] = thr["watch"], thr["high"]
    out["lrs_tier"] = lrs_tier(out["lrs"], thr)
    return add_window_stats(out)   # thống kê cửa sổ trượt 30 lần chụp cho điểm 30 phút ở Radar


def special_days_version() -> float:
    try:
        return special_days_path().stat().st_mtime
    except OSError:
        return 0.0


def analyzed_data(source: str) -> pd.DataFrame:
    """Kết quả phân tích với tham số hiện hành (cùng cache với Radar)."""
    p = params()
    return analyze(source, str(get_settings().db_path), source_version(source), int(p["max_sessions"]),
                   float(p["threshold"]), p["w_spread"], p["w_depth"], p["w_imb"], special_version=special_days_version())


WATCHLIST_PATH = ROOT / "data" / "watchlist.json"
GATE_MIN_SCORE = section("gate")["min_score"]   # trùng mốc "Yếu" của điểm thanh khoản ở Radar (config.toml)


def db_version() -> float:
    try:
        return get_settings().db_path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _board_days(db_path: str, version: float) -> list[str]:
    return board_days(Path(db_path))


@st.cache_data(show_spinner=False)
def _board(db_path: str, version: float, day: str, grp: str) -> pd.DataFrame:
    return load_board(Path(db_path), day, grp)


@st.cache_data(show_spinner=False)
def _ssi_calendar(db_path: str, version: float) -> list[str]:
    """Các ngày giao dịch thật theo SSI (ngày có dòng của chỉ số VNINDEX hoặc VN30 trong ssi_daily), YYYY-MM-DD.
    Dùng làm lịch phiên cho động lượng nhiều phiên. Chưa lấy SSI (scripts/fetch_ssi_history.py) thì rỗng."""
    df = load_ssi_daily(Path(db_path))
    if df.empty:
        return []
    return sorted(df.loc[df["symbol"].isin(["VNINDEX", "VN30"]), "day"].dropna().unique())


def board_dates() -> list[str]:
    """Các ngày có bảng giá (ảnh chụp mới nhất mỗi ngày, cuối ngày là lúc đóng cửa), dạng YYYY-MM-DD."""
    return _board_days(str(get_settings().db_path), db_version())


def board_of(day: str, grp: str = "VN30") -> pd.DataFrame:
    """Bảng giá gốc (cột NEO đã đổi tên chuẩn) của một nhóm trong một ngày; rỗng nếu không có."""
    return _board(str(get_settings().db_path), db_version(), day, grp)


@st.cache_data(show_spinner=False)
def _index_day(db_path: str, version: float, day: str) -> pd.DataFrame:
    return load_market_index(Path(db_path), day)


@st.cache_data(show_spinner=False)
def _futures(db_path: str, version: float) -> pd.DataFrame:
    return load_futures(Path(db_path))


def index_of(day: str) -> pd.DataFrame:
    """Các lần chụp chỉ số (NEO 4.3) trong một ngày."""
    return _index_day(str(get_settings().db_path), db_version(), day)


def screen_for_day(source: str, day, min_score: float = GATE_MIN_SCORE, horizon: str = "intraday") -> dict | None:
    """Kết quả bộ lọc cho một phiên: cổng thanh khoản (cùng số với Radar), yếu tố, điểm và bối cảnh thị trường.

    Ảnh chụp giá: bảng giá cuối ngày (đã có ATC nếu chụp từ 14:45) khi có, không thì lần chụp cuối trong phiên liên tục.
    % VN30 dùng để đo động lượng tương đối lấy ở lần chụp chỉ số gần nhất KHÔNG SAU ảnh chụp giá (không nhìn trước).
    horizon: "intraday" (giá khớp so với tham chiếu) hoặc "5d" (5 phiên, chỉ khi đủ giá đóng cửa hợp lệ).
    Trả None khi phiên không có sổ lệnh theo phút."""
    data = analyzed_data(source)
    view = data[data["ts"].dt.date == day]
    if view.empty:
        return None
    ranking, _, counts = liquidity_ranking(view)
    gate = liquidity_gate(ranking, counts, min_score)
    day_str = pd.Timestamp(day).strftime("%Y-%m-%d")
    use_db = source == SRC_DB
    board = board_of(day_str, "VN30") if use_db else pd.DataFrame()
    if not board.empty:
        snap, snap_kind = board, "board"
    else:
        snap, snap_kind = view.sort_values("ts").groupby("symbol").tail(1), "quotes"
    snap_ts = snap["ts"].max()
    idx = index_of(day_str) if use_db else pd.DataFrame()
    vn30 = idx[(idx["index_code"] == "VN30") & (idx["ts"] <= snap_ts)] if not idx.empty else idx
    vn30_pct = float(vn30.sort_values("ts")["pct_change"].iloc[-1]) if vn30 is not None and not vn30.empty else None
    factors = intraday_factors(snap, vn30_pct)

    # Động lượng 5 phiên từ giá đóng cửa hợp lệ (bảng giá chụp từ 14:45) của mọi ngày đã ghi.
    mom5_ok = False
    if use_db:
        closes = daily_closes_from_board(pd.concat([board_of(d, "VN30") for d in board_dates()], ignore_index=True)
                                         if board_dates() else pd.DataFrame())
        ix_rows = []
        for d in sorted({c for c in closes["day"]}) if not closes.empty else []:
            ix = index_of(pd.Timestamp(d).strftime("%Y-%m-%d"))
            ix = ix[ix["index_code"] == "VN30"] if not ix.empty else ix
            if not ix.empty:
                last = ix.sort_values("ts").iloc[-1]
                ix_rows.append({"day": d, "close": last["index_value"] if last["ts"].time() >= ATC_DONE else None})
        cal = _ssi_calendar(str(get_settings().db_path), db_version())
        if not closes.empty and cal:   # chưa có lịch phiên thật thì không tính: không đoán ngày giao dịch
            mom = momentum(closes, 5, pd.DataFrame(ix_rows) if ix_rows else None, calendar=cal)
            today = mom[mom["day"] == day]
            if "rel_mom_5" in today and today["rel_mom_5"].notna().any():
                factors = factors.merge(today[["symbol", "mom_5", "rel_mom_5"]], on="symbol", how="left")
                mom5_ok = True
    cols = ["foreign_ratio", "rel_mom_5"] if (horizon == "5d" and mom5_ok) else None
    result = screen(factors, gate, cols)

    cards = index_cards(idx, day, load_market_json(ROOT / "data", day)) if use_db else pd.DataFrame()
    fut = _futures(str(get_settings().db_path), db_version()) if use_db else pd.DataFrame()
    fut_day = fut[fut["ts"].dt.date == day] if not fut.empty else fut
    vn30_card = cards[cards["index_code"] == "VN30"] if not cards.empty else cards
    fut_v = futures_view(fut_day, float(vn30_card["index_value"].iloc[0]) if not vn30_card.empty else None)
    ctx = market_context(cards, breadth_frame(cards) if not cards.empty else None, fut_v, snap)
    return {"result": result, "factors_used": result.attrs.get("factors", []), "snap_ts": snap_ts,
            "snap_kind": snap_kind, "vn30_pct": vn30_pct, "mom5_ok": mom5_ok, "context": ctx}


def liquidity_ranking(view: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Xếp hạng thanh khoản trong khoảng dữ liệu `view`, kèm số đợt cảnh báo và LRS ở lần chụp mới nhất.

    Trả (ranking, alerts, alert_counts): ranking theo điểm tăng dần (mã yếu nhất đầu tiên); alerts là các lần chụp đang
    cảnh báo, mới nhất trước; alert_counts là số ĐỢT cảnh báo theo mã."""
    ranking = rank_symbols(view)
    alerts = view[view["is_alert"]].sort_values("ts", ascending=False)
    # Một đợt = chuỗi lần chụp liên tiếp cùng thỏa điều kiện; đếm theo đợt để một sự kiện kéo dài không thành hàng chục cảnh báo.
    alert_counts = alerts[alerts["alert_start"]].groupby("symbol").size()
    ranking["alerts"] = ranking["symbol"].map(alert_counts).fillna(0).astype(int)
    last_per_sym = view.sort_values("ts").groupby("symbol").tail(1).set_index("symbol")
    ranking["lrs"] = ranking["symbol"].map(last_per_sym["lrs"])
    ranking["lrs_tier"] = ranking["symbol"].map(last_per_sym["lrs_tier"]).fillna("")
    # Mã chưa có mốc nền ở lần chụp nào trong khoảng đang xem thì chưa đánh giá được: đó không phải "không có cảnh báo".
    has_base = view.groupby("symbol")["n_hist"].apply(lambda s: bool(s.notna().any()))
    ranking["baseline_ok"] = ranking["symbol"].map(has_base).fillna(False).astype(bool)
    ranking["baseline_reason"] = ranking["symbol"].map(last_per_sym["baseline_reason"]).fillna("")
    ranking["base_status"] = np.where(ranking["baseline_ok"], STATUS_OK, STATUS_NA)
    # Điểm theo cửa sổ trượt 30 lần chụp, tại lần chụp cuối của từng mã trong khoảng đang xem (mã thiếu dữ liệu: không chấm).
    ws = window_scores(last_per_sym.reset_index())
    ranking["score_w"] = ranking["symbol"].map(ws["score_w"])
    ranking["score_w_status"] = ranking["symbol"].map(ws["score_w_status"]).fillna(STATUS_NA)
    return ranking, alerts, alert_counts
