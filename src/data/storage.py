"""Lưu và đọc dữ liệu sổ lệnh bằng SQLite. Dấu thời gian lưu dạng chuỗi ISO có +07:00."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from neo_api.config import TZ

from .market import INDEX_COLUMNS
from .market_board import BOARD_COLUMNS, DEPTH_COLUMNS, FUTURES_COLUMNS
from .schema import QUOTE_COLUMNS
from .ssi import SSI_DAILY_COLUMNS, SSI_DAILY_TEXT, SSI_INDEX_COLUMNS, SSI_INDEX_TEXT

WS_COLUMNS = [*QUOTE_COLUMNS, "n_msgs", "age_ms"]  # sổ lệnh từ WebSocket theo thanh 5 giây (thử nghiệm)
# Từng lần khớp từ kênh WebSocket marketData. ts = giờ sàn (timestamp của tin, chính xác tới giây), recv_ts = giờ máy nhận.
# side = lastColor nguyên văn ("B"/"S"; giả thuyết B = mua chủ động, khớp ở giá bán, CHƯA kiểm chứng đủ).
WS_TRADE_COLUMNS = ["ts", "recv_ts", "symbol", "seq", "price", "volume", "side"]
# Cột của bảng ws_trades: thêm `day` (ngày giao dịch, YYYY-MM-DD theo giờ sàn) để làm khóa cùng mã và số thứ tự.
# NEO đánh lại sequenceMsg từ đầu mỗi ngày: khóa cũ (symbol, seq) làm lần khớp hôm nay trùng số với ngày trước bị bỏ qua
# (phát hiện 10/11/2026: phiên 9/11 đọc 64.829 lần khớp nhưng chỉ lưu 64.469, thiếu đúng 360 lần trùng số với 3-6/11).
WS_TRADE_TABLE_COLUMNS = ["day", *WS_TRADE_COLUMNS]
_WS_TRADE_TEXT = ("day", "ts", "recv_ts", "symbol", "side")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cols = ", ".join(
        f"{c} TEXT" if c in ("ts", "symbol") else f"{c} REAL" for c in QUOTE_COLUMNS
    )
    conn.execute(f"CREATE TABLE IF NOT EXISTS quotes ({cols}, PRIMARY KEY (ts, symbol))")
    # DB tạo bởi bản cũ chưa có các cột mới (ví dụ ceil_px): thêm vào, dữ liệu cũ giữ nguyên và các ô mới để trống (NULL),
    # không ước lượng. Muốn điền lại từ phản hồi gốc đã lưu: python scripts/backfill_extra.py
    have = {r[1] for r in conn.execute("PRAGMA table_info(quotes)")}
    for c in QUOTE_COLUMNS:
        if c not in have:
            conn.execute(f"ALTER TABLE quotes ADD COLUMN {c} {'TEXT' if c in ('ts', 'symbol') else 'REAL'}")
    idx_cols = ", ".join(f"{c} TEXT" if c in ("ts", "index_code", "status") else f"{c} REAL" for c in INDEX_COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS market_index ({idx_cols}, PRIMARY KEY (ts, index_code))")
    _create(conn, "board", BOARD_COLUMNS, ("day", "grp", "ts", "symbol"), "day, grp, symbol")
    _create(conn, "depth_market", DEPTH_COLUMNS, ("ts", "grp"), "ts, grp")
    _create(conn, "futures", FUTURES_COLUMNS, ("ts", "symbol", "name", "maturity"), "ts, symbol")
    _create(conn, "ws_quotes", WS_COLUMNS, ("ts", "symbol"), "ts, symbol")
    _create_ws_trades(conn)
    # Dữ liệu SSI theo ngày (nguồn PHỤ, bù lịch sử cho NEO): bảng riêng, không đụng bảng của NEO.
    _create(conn, "ssi_daily", SSI_DAILY_COLUMNS, SSI_DAILY_TEXT, "day, symbol")
    _create(conn, "ssi_index_daily", SSI_INDEX_COLUMNS, SSI_INDEX_TEXT, "day, index_code")
    return conn


def _create(conn: sqlite3.Connection, table: str, columns: list[str], text_cols: tuple[str, ...], pk: str) -> None:
    """Tạo bảng nếu chưa có. Cột giá khai báo REAL nhưng SQLite vẫn giữ được chữ ATO/ATC (không ép thành số)."""
    cols = ", ".join(f"{c} TEXT" if c in text_cols else f"{c} REAL" for c in columns)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols}, PRIMARY KEY ({pk}))")


def _create_ws_trades(conn: sqlite3.Connection) -> None:
    """Bảng ws_trades với khóa (day, symbol, seq). Bảng tạo bởi bản cũ (khóa symbol, seq, chưa có cột day) được chuyển
    sang một lần: mọi dòng cũ giữ nguyên, day lấy từ 10 ký tự đầu của ts (giờ sàn, +07:00). Không dòng nào bị bỏ vì
    khóa mới rộng hơn khóa cũ."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "ws_trades" in tables and "ws_trades_old" not in tables:
        have = {r[1] for r in conn.execute("PRAGMA table_info(ws_trades)")}
        if "day" not in have:
            conn.execute("ALTER TABLE ws_trades RENAME TO ws_trades_old")
            tables.add("ws_trades_old")
    _create(conn, "ws_trades", WS_TRADE_TABLE_COLUMNS, _WS_TRADE_TEXT, "day, symbol, seq")
    if "ws_trades_old" in tables:  # cũng chạy tiếp nếu lần chuyển trước bị ngắt giữa chừng
        old = ", ".join(WS_TRADE_COLUMNS)
        conn.execute(f"INSERT OR IGNORE INTO ws_trades (day, {old}) SELECT substr(ts, 1, 10), {old} FROM ws_trades_old")
        conn.execute("DROP TABLE ws_trades_old")
        conn.commit()


def _write(df: pd.DataFrame, columns: list[str], table: str, db_path: Path, replace: bool) -> int:
    if df.empty:
        return 0
    data = df[columns].copy()
    data["ts"] = data["ts"].map(lambda t: t.isoformat())
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    with _connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            data.astype(object).where(data.notna(), None).itertuples(index=False, name=None),
        )
        return conn.total_changes - before


def save_board(df: pd.DataFrame, db_path: Path) -> int:
    """Bảng giá một nhóm: mỗi (ngày, nhóm, mã) giữ bản MỚI NHẤT (ghi đè), nên cuối ngày là bảng giá lúc đóng cửa."""
    return _write(df, BOARD_COLUMNS, "board", db_path, replace=True)


def save_depth_market(df: pd.DataFrame, db_path: Path) -> int:
    return _write(df, DEPTH_COLUMNS, "depth_market", db_path, replace=False)


def save_ws_quotes(df: pd.DataFrame, db_path: Path) -> int:
    return _write(df, WS_COLUMNS, "ws_quotes", db_path, replace=False)


def load_ws_quotes(db_path: Path) -> pd.DataFrame:
    return _read(db_path, "SELECT * FROM ws_quotes ORDER BY symbol, ts", (), WS_COLUMNS)


def save_ws_trades(df: pd.DataFrame, db_path: Path) -> int:
    """Lần khớp trùng (cùng NGÀY, cùng mã, cùng số thứ tự, ví dụ nhận lại sau khi kết nối lại) bị bỏ qua.
    day = ngày của giờ sàn (ts), đúng 10 ký tự đầu của ts khi lưu."""
    if df.empty:
        return 0
    data = df.assign(day=df["ts"].map(lambda t: t.isoformat()[:10]))
    return _write(data, WS_TRADE_TABLE_COLUMNS, "ws_trades", db_path, replace=False)


def load_ws_trades(db_path: Path, day: str | None = None) -> pd.DataFrame:
    sql, params = "SELECT * FROM ws_trades", ()
    if day:
        sql, params = sql + " WHERE day = ?", (day,)
    return _read(db_path, sql + " ORDER BY day, symbol, seq", params, WS_TRADE_TABLE_COLUMNS)


def save_futures(df: pd.DataFrame, db_path: Path) -> int:
    return _write(df, FUTURES_COLUMNS, "futures", db_path, replace=False)


def _read(db_path: Path, sql: str, params: tuple, columns: list[str]) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=columns)
    with _connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if "ts" in df and not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    return df


def load_board(db_path: Path, day: str, grp: str) -> pd.DataFrame:
    return _read(db_path, "SELECT * FROM board WHERE day = ? AND grp = ? ORDER BY symbol", (day, grp), BOARD_COLUMNS)


def load_depth_market(db_path: Path) -> pd.DataFrame:
    return _read(db_path, "SELECT * FROM depth_market ORDER BY grp, ts", (), DEPTH_COLUMNS)


def load_futures(db_path: Path) -> pd.DataFrame:
    return _read(db_path, "SELECT * FROM futures ORDER BY ts, symbol", (), FUTURES_COLUMNS)


def board_days(db_path: Path) -> list[str]:
    if not Path(db_path).exists():
        return []
    with _connect(db_path) as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT day FROM board ORDER BY day")]


def save_quotes(df: pd.DataFrame, db_path: Path) -> int:
    """Ghi dữ liệu đã chuẩn hóa. Bản ghi trùng (ts, symbol) được bỏ qua. Trả về số dòng thực ghi."""
    if df.empty:
        return 0
    data = df[QUOTE_COLUMNS].copy()
    data["ts"] = data["ts"].map(lambda t: t.isoformat())
    placeholders = ", ".join("?" for _ in QUOTE_COLUMNS)
    with _connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR IGNORE INTO quotes ({', '.join(QUOTE_COLUMNS)}) VALUES ({placeholders})",
            data.astype(object).where(data.notna(), None).itertuples(index=False, name=None),
        )
        return conn.total_changes - before


def load_quotes(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame(columns=QUOTE_COLUMNS)
    with _connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM quotes ORDER BY symbol, ts", conn)


def count_rows(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]


def save_market_index(df: pd.DataFrame, db_path: Path) -> int:
    """Ghi các chỉ số (4.3) tại một thời điểm. Trùng (ts, index_code) thì bỏ qua. Trả về số dòng thực ghi."""
    if df.empty:
        return 0
    data = df[INDEX_COLUMNS].copy()
    data["ts"] = data["ts"].map(lambda t: t.isoformat())
    placeholders = ", ".join("?" for _ in INDEX_COLUMNS)
    with _connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR IGNORE INTO market_index ({', '.join(INDEX_COLUMNS)}) VALUES ({placeholders})",
            data.astype(object).where(data.notna(), None).itertuples(index=False, name=None),
        )
        return conn.total_changes - before


def load_market_index(db_path: Path, day: str | None = None) -> pd.DataFrame:
    """Bảng chỉ số 4.3. Truyền day (YYYY-MM-DD) để chỉ đọc một ngày: bộ ghi nhanh lưu hàng chục nghìn dòng mỗi ngày."""
    if not db_path.exists():
        return pd.DataFrame(columns=INDEX_COLUMNS)
    sql, params = "SELECT * FROM market_index ORDER BY index_code, ts", ()
    if day:
        sql, params = "SELECT * FROM market_index WHERE ts >= ? AND ts < ? ORDER BY index_code, ts", (day, day + "~")
    with _connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    return df


def data_days(db_path: Path) -> list[str]:
    """Các ngày (YYYY-MM-DD) có dữ liệu chỉ số, sổ lệnh hoặc bảng giá, theo thứ tự tăng dần."""
    if not Path(db_path).exists():
        return []
    out: set[str] = set()
    with _connect(db_path) as conn:
        for table in ("market_index", "quotes", "board"):
            col = "day" if table == "board" else "substr(ts, 1, 10)"
            out |= {r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM {table}") if r[0]}
    return sorted(out)


def live_stamp(db_path: Path) -> tuple | None:
    """Dấu hiệu "bộ ghi vừa ghi thêm sổ lệnh/bảng giá" cho chế độ Trực tiếp: (ts lớn nhất của quotes, board trừ nhóm VN30, futures; bảng giá VN30 tự làm mới 5 giây riêng).
    Chỉ đọc, không tạo bảng. Bộ ghi nhanh ghi chỉ số mỗi 5 giây nên mtime của file đổi liên tục; stamp này chỉ đổi mỗi phút."""
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        vals = []
        for table, where in (("quotes", ""), ("board", " WHERE grp != 'VN30'"), ("futures", "")):
            try:
                vals.append(conn.execute(f"SELECT MAX(ts) FROM {table}{where}").fetchone()[0])
            except sqlite3.Error:
                vals.append(None)
        return tuple(vals)
    finally:
        conn.close()


def latest_ts(db_path: Path, day: str) -> pd.Timestamp | None:
    """Thời điểm bản ghi mới nhất (chỉ số, sổ lệnh VN30, bảng giá) của một ngày; None nếu chưa có."""
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        best = None
        for table in ("market_index", "quotes", "board"):
            try:
                v = conn.execute(f"SELECT MAX(ts) FROM {table} WHERE ts >= ? AND ts < ?", (day, day + "~")).fetchone()[0]
            except sqlite3.Error:
                v = None
            if v and (best is None or v > best):
                best = v
        return pd.Timestamp(best).tz_convert(TZ) if best else None
    finally:
        conn.close()
