"""Ứng dụng phân tích thị trường chứng khoán Việt Nam trên dữ liệu NEO API (VPBankS): Tổng quan và Radar thanh khoản.

Chạy từ thư mục gốc dự án:  streamlit run src/app/app.py
Hoặc cùng bộ ghi dữ liệu bằng một lệnh:  python scripts/run_live.py

File này là "cổng vào": đặt cấu hình trang, CSS, thương hiệu, công tắc Trực tiếp rồi chuyển sang trang được chọn
(overview.py hoặc radar.py). Nội dung giao diện của Radar vẫn nằm nguyên trong radar.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _drop_stale_modules() -> None:
    """Sau mỗi lần cập nhật mã, nạp lại các mô-đun của dự án (data, analytics, finance, theme, shared...).

    Chạy trên Streamlit Cloud, tiến trình sống tiếp sau khi cập nhật mã: các tệp trang (radar.py...) chạy lại bản mới nhưng mô-đun đã nạp
    (candle_store.py, theme.py...) giữ bản cũ, nên một import mới có thể báo ImportError cho tới khi khởi động lại app. Ở đây so dấu thời gian
    lớn nhất của các tệp .py trong src với lần trước; đổi thì bỏ các mô-đun của dự án khỏi bộ nhớ để lần import sau đọc bản mới (không đụng tệp nào)."""
    src = Path(__file__).resolve().parents[1]
    token = max((f.stat().st_mtime for f in src.rglob("*.py")), default=0.0)
    if getattr(sys, "_ds_src_token", None) == token:
        return
    sys._ds_src_token = token
    me = Path(__file__).resolve()
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if not f or name == "__main__":
            continue
        try:
            path = Path(f).resolve()
        except OSError:
            continue
        if src in path.parents and path != me:
            del sys.modules[name]


_drop_stale_modules()

import streamlit as st  # noqa: E402

from data.storage import live_stamp  # noqa: E402
from data.web_data import ensure_web_data  # noqa: E402
from neo_api.config import get_settings  # noqa: E402
from shared import WATCHLIST_PATH, analyzed_data, current_source, screen_for_day  # noqa: E402
from theme import BRAND_MARK, group, inject_css, is_dark  # noqa: E402
from watchlist import load_watchlist  # noqa: E402

LIVE_EVERY_SECONDS = 15  # cứ 15 giây xem bộ ghi có ghi thêm gì chưa; bộ ghi chụp mỗi phút nên dữ liệu trễ tối đa ~1 phút

# Thanh bên mặc định thu gọn để nội dung tràn hết bề ngang (bấm mũi tên >> ở góc trên bên trái để mở: công tắc Trực tiếp, danh sách theo dõi, ngày và bộ lọc của trang).
st.set_page_config(page_title="Thị trường VN · NEO API", page_icon=":material/radar:", layout="wide", initial_sidebar_state="collapsed")


@st.cache_resource(show_spinner="Đang chuẩn bị dữ liệu…")
def _prepare_web_data() -> list[str]:
    """Bản web: giải nén dữ liệu rút gọn (data/web) lần đầu. Ở laptop có market.db thật thì không làm gì (không bao giờ ghi đè)."""
    return ensure_web_data(ROOT)


_prepare_web_data()
inject_css()
# Ẩn Fork, GitHub, Share và menu ba chấm mà Streamlit Cloud thêm vào góc phải trên. Đặt ở app.py (chạy lại mỗi lần tải trang) chứ không ở theme.py:
# trên Cloud, mô-đun đã nạp như theme.py giữ bản cũ cho tới khi khởi động lại app. KHÔNG ẩn cả stToolbar vì menu điều hướng trang nằm trong đó.
st.html('<style>[data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], .stDeployButton'
        ' { display: none !important; }</style>')


@st.fragment(run_every=2)
def _theme_watch(seen_dark: bool) -> None:
    """Người xem đổi nền sáng/tối ở menu Settings: Streamlit không chạy lại trang, nên cứ 2 giây hỏi lại và chạy lại cả trang khi chủ đề đổi
    (màu của phần HTML tự vẽ chỉ đúng sau khi chạy lại)."""
    if is_dark() != seen_dark:
        st.rerun()


_theme_watch(is_dark())


# Streamlit nhớ lựa chọn nền sáng/tối của người xem trong trình duyệt (localStorage, khóa stActiveTheme-<đường dẫn>-v2) và mặc định theo hệ thống.
# Dự án muốn MỖI LẦN MỞ app (tab mới) là NỀN SÁNG: lần đầu trong một tab (sessionStorage chưa có dấu dsInit) thì đặt Light và tải lại một lần.
# Sau đó trong cùng tab, chọn nền tối bằng nút ở Tổng quan hoặc bấm F5 đều giữ nguyên lựa chọn (không còn ép lại).
_DEFAULT_LIGHT_SCRIPT = (
    "<script>try{var p=window.parent,k='stActiveTheme-'+p.location.pathname+'-v2',ss=p.sessionStorage;"
    "if(!ss.getItem('dsInit')){ss.setItem('dsInit','1');if(p.localStorage.getItem(k)!=='\"Light\"')"
    "{p.localStorage.setItem(k,'\"Light\"');p.location.reload();}}}catch(e){}</script>")

st.iframe(_DEFAULT_LIGHT_SCRIPT, height=1)
settings = get_settings()


def _db_stamp(path: Path):
    """Dấu hiệu bộ ghi vừa ghi thêm sổ lệnh/bảng giá (đổi mỗi phút). Không dùng mtime của file vì bộ ghi nhanh
    ghi chỉ số mỗi 5 giây; phần chỉ số do khối thẻ chỉ số tự cập nhật riêng."""
    return live_stamp(path)


@st.fragment(run_every=LIVE_EVERY_SECONDS)
def _live_watch(db_path: Path, seen: float | None) -> None:
    """Chế độ trực tiếp: chỉ chạy lại cả trang khi market.db thực sự có dữ liệu mới (không chạy lại vô ích)."""
    if _db_stamp(db_path) != seen:
        st.rerun()


PAGE_OVERVIEW = st.Page("overview.py", title="Tổng quan thị trường", icon=":material/dashboard:", url_path="tong-quan",
                        default=True)
PAGE_SCREEN = st.Page("screen_page.py", title="Bộ lọc cổ phiếu", icon=":material/filter_alt:", url_path="bo-loc")
PAGE_RADAR = st.Page("radar.py", title="Radar thanh khoản", icon=":material/radar:", url_path="radar")
PAGE_STOCK = st.Page("stock.py", title="Chi tiết mã", icon=":material/candlestick_chart:", url_path="ma")


def _watchlist_sidebar() -> None:
    """Danh sách theo dõi: mỗi mã là một liên kết sang Chi tiết mã; ở phiên gần nhất, mã bị cổng thanh khoản Loại hoặc
    có đợt cảnh báo được đánh dấu."""
    group("Theo dõi")
    watch = load_watchlist(WATCHLIST_PATH)
    if not watch:
        st.caption("Chưa theo dõi mã nào. Mở một mã ở Chi tiết mã rồi bấm \"Theo dõi mã này\".")
        return
    info = {}
    source = current_source()
    if source is not None:
        try:
            last_day = analyzed_data(source)["ts"].dt.date.max()
            res = screen_for_day(source, last_day)
            if res is not None:
                info = res["result"].set_index("symbol")[["gate", "alerts"]].to_dict("index")
        except Exception:  # noqa: BLE001 - thanh bên không được làm hỏng trang
            info = {}
    for sym in watch:
        i = info.get(sym, {})
        n, gate = int(i.get("alerts", 0) or 0), i.get("gate", "")
        note = " · Loại" if gate == "Loại" else (f" · {n} đợt cảnh báo" if n else "")
        st.page_link(PAGE_STOCK, label=sym + note, query_params={"ma": sym},
                     icon=":material/warning:" if note else ":material/star:")


LIVE_HELP = "Tự đọc lại dữ liệu khi có bản ghi mới. Dữ liệu được chụp mỗi phút nên trễ tối đa khoảng 1 phút."
st.session_state.setdefault("live", os.environ.get("NEO_LIVE") == "1")      # công tắc Trực tiếp dùng chung khóa "live" ở mọi trang
pages = st.navigation([PAGE_OVERVIEW, PAGE_RADAR, PAGE_SCREEN, PAGE_STOCK], position="top")
with st.sidebar:
    st.html(f'<div class="brand">{BRAND_MARK}<div><b>Thị trường VN</b>'
            '<span>Dữ liệu NEO API · VPBankS</span></div></div>')
    if pages.title not in (PAGE_OVERVIEW.title, PAGE_RADAR.title):   # Tổng quan đặt công tắc này ở thanh đầu trang, Radar ở bảng bên trái
        group("Cập nhật")
        st.toggle("Trực tiếp: tự cập nhật", key="live", help=LIVE_HELP)
if st.session_state.get("live"):
    _live_watch(settings.db_path, _db_stamp(settings.db_path))
with st.sidebar:
    _watchlist_sidebar()
pages.run()
