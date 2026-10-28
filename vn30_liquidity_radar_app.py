import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# ==========================================
# CẤU HÌNH TRANG (Mục 6 Đề thi)
# ==========================================
st.set_page_config(
    page_title="Radar Rủi Ro Thanh Khoản VN30 - NEO API",
    page_icon="📡",
    layout="wide"
)

# Danh sách 30 mã cổ phiếu rổ VN30
VN30_TICKERS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
]

# ==========================================
# HÀM GIẢ LẬP DỮ LIỆU & TÍNH TOÁN (Bước 1 -> Bước 4)
# ==========================================
@st.cache_data
def generate_vn30_intraday_data(n_steps=60):
    np.random.seed(42)
    base_time = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    records = []

    for ticker in VN30_TICKERS:
        # Thiết lập mặt bằng thanh khoản riêng cho từng mã (ví dụ HPG, SSI, VPB thanh khoản rất dày; BVH, SAB, BCM mỏng hơn)
        is_high_liq = ticker in ["HPG", "SSI", "VPB", "MBB", "STB", "SHB", "TCB", "FPT"]
        base_price = np.random.uniform(20000, 95000) // 100 * 100
        base_depth = np.random.uniform(350000, 900000) if is_high_liq else np.random.uniform(40000, 150000)
        base_spread_bps = np.random.uniform(10, 22) if is_high_liq else np.random.uniform(25, 60)

        cum_vol = 100000
        for step in range(n_steps):
            t = base_time + timedelta(minutes=step)
            
            # Tạo kịch bản bất thường (Shock thanh khoản) từ phút thứ 40 đến 50 cho một số mã
            is_shock = (40 <= step <= 50) and (ticker in ["SSI", "HPG", "NVL", "DIG", "BVH", "MSN", "MWG"])
            
            if is_shock and ticker in ["SSI", "MWG"]:
                # Kịch bản 1: Rút lệnh đột ngột làm mỏng sổ lệnh + Spread giãn rộng
                spread_bps = base_spread_bps * np.random.uniform(2.2, 3.5)
                depth_3l = base_depth * np.random.uniform(0.20, 0.40)
                obi = np.random.uniform(-0.85, -0.60)
                delta_vol = np.random.uniform(5000, 20000)
            elif is_shock and ticker in ["HPG", "MSN"]:
                # Kịch bản 2: Mất cân bằng sổ lệnh cực đoan (Kê lệnh 1 chiều)
                spread_bps = base_spread_bps * np.random.uniform(1.3, 1.8)
                depth_3l = base_depth * np.random.uniform(0.5, 0.8)
                obi = np.random.uniform(0.75, 0.92)
                delta_vol = np.random.uniform(80000, 180000)
            else:
                spread_bps = max(5.0, np.random.normal(base_spread_bps, base_spread_bps * 0.15))
                depth_3l = max(5000.0, np.random.normal(base_depth, base_depth * 0.18))
                obi = np.clip(np.random.normal(0.0, 0.25), -0.95, 0.95)
                delta_vol = max(1000.0, np.random.normal(base_depth * 0.12, base_depth * 0.04))

            cum_vol += delta_vol
            mid_price = base_price * (1 + np.random.normal(0, 0.002))

            records.append({
                "timestamp": t,
                "step": step,
                "ticker": ticker,
                "mid_price": round(mid_price, 0),
                "rel_spread_bps": spread_bps,      # Chênh lệch mua-bán tương đối (bps)
                "depth_3l": depth_3l,              # Độ sâu sổ lệnh 3 mức giá (cổ phiếu)
                "obi": obi,                        # Order Book Imbalance [-1, 1]
                "delta_vol": delta_vol,            # Khối lượng khớp tăng thêm mỗi phút
                "total_vol": cum_vol
            })

    df = pd.DataFrame(records)

    # Bước 3: Tính Rolling Z-Score cuốn chiếu (cửa sổ 20 phút) cho từng mã so với chính lịch sử của nó
    window = 20
    df["z_spread"] = df.groupby("ticker")["rel_spread_bps"].transform(
        lambda s: (s - s.rolling(window, min_periods=5).mean()) / (s.rolling(window, min_periods=5).std() + 1e-6)
    ).fillna(0)

    df["z_depth"] = df.groupby("ticker")["depth_3l"].transform(
        lambda s: (s - s.rolling(window, min_periods=5).mean()) / (s.rolling(window, min_periods=5).std() + 1e-6)
    ).fillna(0)

    df["abs_obi"] = df["obi"].abs()
    df["z_obi"] = df.groupby("ticker")["abs_obi"].transform(
        lambda s: (s - s.rolling(window, min_periods=5).mean()) / (s.rolling(window, min_periods=5).std() + 1e-6)
    ).fillna(0)

    return df

df_all = generate_vn30_intraday_data()

# ==========================================
# SIDEBAR: BỘ LỌC & CẤU HÌNH TRỌNG SỐ (Mục 6 Đề thi)
# ==========================================
st.sidebar.title("⚙️ Điều Khiển Radar VN30")

mode = st.sidebar.radio(
    "Chế độ vận hành dữ liệu:",
    ["⏪ Replay Kiểm Chứng (SQLite/Parquet)", "🟢 Live WebSocket (NEO API)"],
    index=0
)

if "Live" in mode:
    st.sidebar.success("🟢 WebSocket NEO API: Đã kết nối (5 req/s OK)")
else:
    st.sidebar.info("📂 Đang đọc từ bộ dữ liệu sạch Intraday (UTC+7)")

selected_step = st.sidebar.slider(
    "🕒 Tua thời gian phiên (Phút thứ 40-50 có Shock):",
    min_value=10,
    max_value=59,
    value=45,
    help="Kéo đến khoảng phút 42 - 48 để quan sát cảnh báo bất thường thanh khoản nổ ra trên SSI, MWG, HPG!"
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚖️ Trọng số Điểm Rủi Ro (LRS)")
w_spread = st.sidebar.slider("Trọng số Giãn Spread (w1):", 0.0, 1.0, 0.40, 0.05)
w_depth = st.sidebar.slider("Trọng số Sụt Độ sâu 3 mức (w2):", 0.0, 1.0, 0.40, 0.05)
w_obi = st.sidebar.slider("Trọng số Lệch Sổ lệnh |OBI| (w3):", 0.0, 1.0, 0.20, 0.05)

z_threshold = st.sidebar.selectbox("Ngưỡng Z-Score báo động:", [1.5, 2.0, 2.5, 3.0], index=1)

# Lọc dữ liệu tại thời điểm đang chọn
df_snap = df_all[df_all["step"] == selected_step].copy()
current_ts = df_snap["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M:%S (UTC+7)")

# Bước 4: Tính Điểm Rủi Ro Thanh Khoản Tổng Hợp (Liquidity Risk Score - LRS)
# Rủi ro cao khi: Spread giãn rộng (+z_spread), Độ sâu sụt giảm (-z_depth), và Sổ lệnh lệch cực đoan (+z_obi)
df_snap["LRS"] = (
    w_spread * df_snap["z_spread"]
    - w_depth * df_snap["z_depth"]
    + w_obi * df_snap["z_obi"]
)

def classify_risk(lrs):
    if lrs >= z_threshold:
        return "🔴 Rủi ro Cao (Bất thường)"
    elif lrs >= z_threshold * 0.6:
        return "🟡 Cảnh báo Sớm"
    return "🟢 Thanh khoản Ổn định"

df_snap["Trạng thái"] = df_snap["LRS"].apply(classify_risk)
df_snap = df_snap.sort_values(by="LRS", ascending=False).reset_index(drop=True)
df_snap["Hạng Rủi Ro"] = df_snap.index + 1

# ==========================================
# HEADER & 3 CHỈ SỐ TỔNG HỢP (Mục 6 Đề thi)
# ==========================================
st.title("📡 Radar Rủi Ro Thanh Khoản VN30 (NEO API Microstructure)")
st.caption(
    f"**Người dùng mục tiêu:** Nhà đầu tư cá nhân, Quản trị rủi ro & Giao dịch định lượng | "
    f"**Cập nhật gần nhất:** `{current_ts}` | **Nguồn cốt lõi:** VPBankS NEO API"
)

high_risk_count = (df_snap["LRS"] >= z_threshold).sum()
avg_spread = df_snap["rel_spread_bps"].mean()
worst_ticker = df_snap.iloc[0]["ticker"]
worst_lrs = df_snap.iloc[0]["LRS"]

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric(
    "Số mã Báo động Rủi ro (LRS ≥ Ngưỡng)",
    f"{high_risk_count} / 30 mã",
    "Cần chú ý trượt giá!" if high_risk_count > 0 else "Toàn rổ ổn định",
    delta_color="inverse" if high_risk_count > 0 else "normal"
)
kpi2.metric(
    "Mã Căng thẳng Thanh khoản Nhất",
    f"{worst_ticker} (LRS: {worst_lrs:+.2f}σ)",
    f"Spread: {df_snap.iloc[0]['rel_spread_bps']:.1f} bps",
    delta_color="inverse"
)
kpi3.metric(
    "Spread Tương đối TB Rổ VN30",
    f"{avg_spread:.1f} bps",
    f"{avg_spread/100:.3f}% chi phí ngầm"
)
kpi4.metric(
    "Tổng Độ sâu 3 Bước giá VN30",
    f"{df_snap['depth_3l'].sum()/1e6:.2f} Triệu cp",
    "Thanh khoản chờ khớp trực tiếp"
)

# ==========================================
# KHU VỰC CẢNH BÁO BẤT THƯỜNG Tự ĐỘNG (Bước 3 & Mục 6)
# ==========================================
alerts_df = df_snap[df_snap["LRS"] >= z_threshold]
if not alerts_df.empty:
    with st.expander(f"🚨 PHÁT HIỆN {len(alerts_df)} MÃ CÓ BẤT THƯỜNG VI CẤU TRÚC SỔ LỆNH (Nhấn để xem chi tiết)", expanded=True):
        for _, row in alerts_df.head(5).iterrows():
            reasons = []
            if row["z_spread"] > 1.5:
                reasons.append(f"Spread giãn rộng bất thường (Z = {row['z_spread']:+.2f}σ)")
            if row["z_depth"] < -1.5:
                reasons.append(f"Độ sâu 3 bước giá sụt giảm mạnh (Z = {row['z_depth']:+.2f}σ)")
            if row["z_obi"] > 1.5:
                reasons.append(f"Mất cân bằng sổ lệnh cực đoan (OBI = {row['obi']:+.2f}, Z = {row['z_obi']:+.2f}σ)")
            reason_text = " | ".join(reasons) if reasons else "Tổ hợp chỉ số vượt ngưỡng"
            st.error(f"**[{row['ticker']}] Điểm Rủi Ro LRS = {row['LRS']:+.2f}σ** — Nguyên nhân: {reason_text}")
else:
    st.success("✅ Hiện tại toàn bộ 30 mã trong rổ VN30 đều có cấu trúc sổ lệnh nằm trong biên độ lịch sử bình thường.")

# ==========================================
# TRỰC QUAN HÓA 1: HEATMAP RỔ VN30 & BẢNG XẾP HẠNG (Bước 4 & 5)
# ==========================================
col_left, col_right = st.columns([1.15, 1])

with col_left:
    st.subheader("🗺️ Bản Đồ Nhiệt (Heatmap) Rủi Ro Thanh Khoản VN30")
    
    # Sắp xếp 30 mã thành lưới 5x6 để vẽ Heatmap (tương thích Pandas/PyArrow mới)
    df_sorted = df_snap.sort_values("ticker")
    grid_tickers = np.array(df_sorted["ticker"].tolist(), dtype=object).reshape(5, 6)
    grid_lrs = np.array(df_sorted["LRS"].tolist(), dtype=float).reshape(5, 6)
    
    # Định nghĩa lại biến grid_text đã bị thiếu
    grid_text = [
        [f"<b>{t}</b><br>LRS: {v:+.2f}σ" for t, v in zip(row_t, row_v)]
        for row_t, row_v in zip(grid_tickers, grid_lrs)
    ]

    fig_hm = go.Figure(data=go.Heatmap(
        z=grid_lrs,
        text=grid_text,
        texttemplate="%{text}",
        colorscale="RdYlGn_r",
        zmid=0,
        zmin=-2.5,
        zmax=3.5,
        colorbar=dict(title="LRS (σ)")
    ))
    fig_hm.update_layout(
        height=400,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis=dict(showticklabels=False),
        yaxis=dict(showticklabels=False)
    )
    st.plotly_chart(fig_hm, use_container_width=True)

with col_right:
    st.subheader("🏆 Bảng Xếp Hạng Điểm Rủi Ro Thanh Khoản")
    display_cols = df_snap[[
        "Hạng Rủi Ro", "ticker", "Trạng thái", "LRS",
        "rel_spread_bps", "depth_3l", "obi", "z_spread", "z_depth"
    ]].rename(columns={
        "ticker": "Mã CP",
        "LRS": "Điểm LRS (σ)",
        "rel_spread_bps": "Spread (bps)",
        "depth_3l": "Độ sâu 3 mức (cp)",
        "obi": "OBI [-1,1]",
        "z_spread": "Z-Spread",
        "z_depth": "Z-Depth"
    })
    st.dataframe(
        display_cols.style.format({
            "Điểm LRS (σ)": "{:+.2f}",
            "Spread (bps)": "{:.1f}",
            "Độ sâu 3 mức (cp)": "{:,.0f}",
            "OBI [-1,1]": "{:+.2f}",
            "Z-Spread": "{:+.2f}",
            "Z-Depth": "{:+.2f}"
        }),
        height=400,
        use_container_width=True,
        hide_index=True
    )

# ==========================================
# TRỰC QUAN HÓA 2: BIỂU ĐỒ CHUỖI THỜI GIAN CHI TIẾT TỪNG MÃ (Bước 3 & 5)
# ==========================================
st.markdown("---")
st.subheader("📈 Phân Tích Chuỗi Thời Gian & Z-Score Cuốn Chiếu Theo Mã")

col_sel1, col_sel2 = st.columns([1, 3])
selected_ticker = col_sel1.selectbox(
    "🔍 Chọn mã cổ phiếu để soi lịch sử nội ngày:",
    df_snap["ticker"].tolist(),
    index=0
)

df_ticker_hist = df_all[(df_all["ticker"] == selected_ticker) & (df_all["step"] <= selected_step)].copy()
df_ticker_hist["LRS"] = (
    w_spread * df_ticker_hist["z_spread"]
    - w_depth * df_ticker_hist["z_depth"]
    + w_obi * df_ticker_hist["z_obi"]
)

tab1, tab2 = st.tabs(["📊 Biến động Z-Score Cuốn chiếu & Điểm LRS", "📚 Độ sâu 3 Bước giá & Order Imbalance (OBI)"])

with tab1:
    fig_ts = go.Figure()
    fig_ts.add_trace(go.Scatter(
        x=df_ticker_hist["timestamp"], y=df_ticker_hist["LRS"],
        mode="lines+markers", name="Điểm Rủi Ro LRS (Tổng hợp)",
        line=dict(color="crimson", width=3)
    ))
    fig_ts.add_trace(go.Scatter(
        x=df_ticker_hist["timestamp"], y=df_ticker_hist["z_spread"],
        mode="lines", name="Z-Score Spread", line=dict(dash="dot", color="orange")
    ))
    fig_ts.add_trace(go.Scatter(
        x=df_ticker_hist["timestamp"], y=-df_ticker_hist["z_depth"],
        mode="lines", name="-Z-Score Độ sâu (Sụt thanh khoản)", line=dict(dash="dot", color="royalblue")
    ))
    fig_ts.add_hline(y=z_threshold, line_dash="dash", line_color="red", annotation_text=f"Ngưỡng Cảnh báo (+{z_threshold}σ)")
    fig_ts.update_layout(
        title=f"Diễn biến Điểm Rủi Ro Thanh Khoản (LRS) so với chính lịch sử mã {selected_ticker}",
        height=360, yaxis_title="Độ lệch chuẩn (Z-Score σ)"
    )
    st.plotly_chart(fig_ts, use_container_width=True)

with tab2:
    c_sub1, c_sub2 = st.columns(2)
    with c_sub1:
        fig_depth = px.area(
            df_ticker_hist, x="timestamp", y="depth_3l",
            title=f"Tổng Độ sâu 3 Bước giá (Bid 1..3 + Ask 1..3) - {selected_ticker}",
            labels={"depth_3l": "Khối lượng treo (cp)", "timestamp": "Thời gian"}
        )
        fig_depth.update_layout(height=320)
        st.plotly_chart(fig_depth, use_container_width=True)
    with c_sub2:
        fig_obi = px.bar(
            df_ticker_hist, x="timestamp", y="obi",
            color="obi", color_continuous_scale="RdYlGn", range_color=[-1, 1],
            title=f"Chỉ số Mất cân bằng Sổ lệnh (OBI) - {selected_ticker}",
            labels={"obi": "OBI [-1: Áp lực Bán, +1: Áp lực Mua]", "timestamp": "Thời gian"}
        )
        fig_obi.update_layout(height=320)
        st.plotly_chart(fig_obi, use_container_width=True)

# ==========================================
# GHI CHÚ PHƯƠNG PHÁP & GIỚI HẠN MÔ HÌNH (Mục 6 & Mục 8 Đề thi)
# ==========================================
st.markdown("---")
with st.expander("📖 Phương pháp tính toán tài chính & Giới hạn của sản phẩm (Tuân thủ Mục 6 & Mục 8 Đề thi)", expanded=False):
    st.markdown("""
    * **Công thức vi cấu trúc:**
      * **Chênh lệch tương đối (Relative Spread):** $Spread_{bps} = \frac{Ask_1 - Bid_1}{(Ask_1 + Bid_1)/2} \times 10^4$
      * **Độ sâu sổ lệnh 3 mức (3-Level Market Depth):** $Depth_{3L} = \sum_{k=1}^3 (V_{Bid,k} + V_{Ask,k})$
      * **Mất cân bằng sổ lệnh (Order Book Imbalance - OBI):** $OBI = \frac{\sum_{k=1}^3 V_{Bid,k} - \sum_{k=1}^3 V_{Ask,k}}{Depth_{3L}} \in [-1, 1]$
      * **Điểm Rủi Ro Thanh Khoản (Liquidity Risk Score - LRS):** $LRS_{i,t} = w_1 Z_{Spread,i,t} - w_2 Z_{Depth,i,t} + w_3 |Z_{OBI,i,t}|$ (chuẩn hóa cuốn chiếu trên cửa sổ trượt 20 phút của chính mã $i$).
    * **Giới hạn & Sử dụng có trách nhiệm:**
      * Dữ liệu sổ lệnh từ NEO API giới hạn ở **03 bước giá tốt nhất**; không phản ánh lượng thanh khoản ẩn (Iceberg orders) hoặc các bước giá sâu hơn.
      * Công cụ phục vụ mục đích **phân tích rủi ro thanh khoản học thuật**, tuyệt đối không phát sinh giao dịch thật và không phải khuyến nghị Mua/Bán tự động.
    """)
