"""Lưu và đọc dữ liệu sổ lệnh bằng SQLite. Dấu thời gian lưu dạng chuỗi ISO có +07:00."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from neo_api.config import TZ

from .market import INDEX_COLUMNS
from .market_board import BOARD_COLUMNS, DEPTH_COLUMNS, FUTURES_COLUMNS
from .schema import QUOTE_COLUMNS

WS_COLUMNS = [*QUOTE_COLUMNS, "n_msgs", "age_ms"]  # sổ lệnh từ WebSocket theo thanh 5 giây (thử nghiệm)
# Từng lần khớp từ kênh WebSocket marketData. ts = giờ sàn (timestamp của tin, chính xác tới giây), recv_ts = giờ máy nhận.
# side = lastColor nguyên văn ("B"/"S"; giả thuyết B = mua chủ động, khớp ở giá bán, CHƯA kiểm chứng đủ).
WS_TRADE_COLUMNS = ["ts", "recv_ts", "symbol", "seq", "price", "volume", "side"]


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
    _create(conn, "ws_trades", WS_TRADE_COLUMNS, ("ts", "recv_ts", "symbol", "side"), "symbol, seq")
    return conn


def _create(conn: sqlite3.Connection, table: str, columns: list[str], text_cols: tuple[str, ...], pk: str) -> None:
    """Tạo bảng nếu chưa có. Cột giá khai báo REAL nhưng SQLite vẫn giữ được chữ ATO/ATC (không ép thành số)."""
    cols = ", ".join(f"{c} TEXT" if c in text_cols else f"{c} REAL" for c in columns)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols}, PRIMARY KEY ({pk}))")


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
    """Lần khớp trùng (cùng mã, cùng số thứ tự, ví dụ nhận lại sau khi kết nối lại) bị bỏ qua."""
    return _write(df, WS_TRADE_COLUMNS, "ws_trades", db_path, replace=False)


def load_ws_trades(db_path: Path, day: str | None = None) -> pd.DataFrame:
    sql, params = "SELECT * FROM ws_trades", ()
    if day:
        sql, params = sql + " WHERE substr(ts, 1, 10) = ?", (day,)
    return _read(db_path, sql + " ORDER BY symbol, seq", params, WS_TRADE_COLUMNS)


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
