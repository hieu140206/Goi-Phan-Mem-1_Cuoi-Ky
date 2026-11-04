# CLAUDE.md: ngữ cảnh dự án (đọc trước khi làm bất cứ việc gì)

## Dự án là gì
Đồ án cá nhân cuối kỳ môn "Gói phần mềm ứng dụng cho tài chính 1" (UEL, FinTech), nộp **1/12/2026**. Sinh viên: Nguyễn Minh Hiếu, năm 3.
Sản phẩm: ứng dụng Python + Streamlit dùng **NEO API của VPBankS** làm nguồn dữ liệu chính, giao diện **sáng, chuyên nghiệp**, chạy local.
Chuỗi giá trị: NEO API -> thu thập -> chuẩn hóa/lưu (SQLite) -> logic tài chính -> phân tích -> dashboard -> người dùng.
Chấm 100 điểm; **trần 60 điểm nếu không chạy được, 50 nếu NEO không phải nguồn lõi**.

Định vị (2/11): **Bộ lọc cổ phiếu VN30** (gợi ý 2) xây trên **Radar thanh khoản** (gợi ý 3, 6): Radar làm cổng thanh khoản,
xếp hạng theo dòng tiền nước ngoài và động lượng so VN30; 4 trang Tổng quan, Bộ lọc, Radar, Chi tiết mã nối qua `?ma=<mã>`.
Lõi phân tích: **Radar thanh khoản VN30** (spread tương đối bps, độ sâu, mất cân bằng mua/bán, z-score trượt, cảnh báo bất thường, điểm LRS).
Trang đầu "Tổng quan thị trường" (4 chỉ số, bảng giá nhiều nhóm, độ sâu, độ rộng, thanh khoản) là phần mở rộng.

## Quy tắc bất di bất dịch
1. **Chỉ ĐỌC dữ liệu.** Không đặt, sửa, hủy lệnh thật (cần văn bản chấp thuận của giảng viên).
2. **Bảo mật:** không in/ghi/chia sẻ token JWT, mật khẩu, số tài khoản. Mật khẩu chỉ nằm trong bộ nhớ tiến trình, `.env` không commit.
3. **Dữ liệu luôn phải đúng, hơn mọi thứ khác.** Thiếu thì để trống hoặc "–", không đoán, không điền, không nội suy. Đổi giao diện không được làm đổi số.
4. Giới hạn NEO: **5 yêu cầu/giây**, IP phải đăng ký. Không tăng tần suất gọi khi chưa đo.
5. Người dùng là **sinh viên mới học**: giải thích ngắn gọn, tiếng Việt, tránh thuật ngữ không cần thiết. Việc lớn thì **nhận xét và hỏi trước** rồi mới làm; không cắt phạm vi tự ý.
6. Làm xong phải chạy `python -m pytest` (hiện **204 passed**) và xem lại giao diện trước khi báo xong.

## Kiến trúc
- `src/neo_api/`: auth (JWT), client REST (4.1 đến 4.9), stream WebSocket (nhị phân, phụ, mới giải mã được `stockInfo`).
- `src/data/`: schema + làm sạch, storage (SQLite `data/market.db`), rest_recorder (bộ ghi), market_board (bảng giá nhiều sàn, phái sinh), overview (hàm dữ liệu trang Tổng quan), backfill, market_day.
- `src/finance/`: liquidity, anomaly, factors, sessions (lọc phiên khớp lệnh liên tục).
- `src/analytics/`: baseline (cảnh báo theo khung giờ), lrs, screener (cổng thanh khoản, yếu tố, điểm bộ lọc, bối cảnh thị trường).
- `src/app/`: `app.py` (cổng vào, điều hướng, công tắc Trực tiếp, danh sách theo dõi), `overview.py` (Tổng quan), `screen_page.py` (Bộ lọc), `radar.py`, `stock.py` (Chi tiết mã), `shared.py` (tải và phân tích dùng chung, cùng số trên mọi trang), `charts.py`, `watchlist.py` (`data/watchlist.json`, không commit), `board.py` (bảng giá HTML), `theme.py`.
- `scripts/`: `run_live.py` (một lệnh: ghi + dashboard), `record_rest.py`, `probe_market.py`, `export_data.py`, `check_boards.py`, `close_snapshot.py`, `backfill_extra.py`, `fetch_day_index.py`.
- Dashboard **chỉ đọc** market.db, không giữ mật khẩu. Bộ ghi và dashboard là hai phần riêng.

## Điều đã xác nhận bằng dữ liệu thật vs chưa
- Đã xác nhận: 4.7 (30 mã VN30 một lần gọi), 4.3 (cả 4 chỉ số), 4.4, 4.9 (4 hợp đồng VN30, mã `41I1GB000`..., tên ở `otherName` VN30F1M/F2M/F1Q/F2Q), 4.5 (đếm mã), 4.6 trả số dòng ít hơn số mã xin 1 đến 2 dòng.
- **Chưa xác nhận:** nội dung 4.6 cho HNX/UPCoM/ETF/CW (đơn vị, trường), 4.3 sau 15:00 có đúng số chính thức không (so với bảng VPS), WebSocket `marketInfo`/`marketVolume` chưa giải mã. Phiên 30/10 là lần kiểm chứng đầu tiên cho bảng giá các sàn (`python scripts/check_boards.py`).
- 30/10: tổng khối lượng của app thấp hơn VPS đúng bằng khối lượng khớp ATC của từng mã (11/11 mã kiểm tra), vì các bảng giá dừng ở 14:44. Đã sửa: `finalize_close` làm mới bảng VN30, bảng các sàn và phái sinh tới 15:02 (cần chạy lại để thấy kết quả). `scripts/inspect_ws_lunch.py` xem tin WebSocket giờ nghỉ trưa.
- Trạng thái HOSE thấy thật: ATO -> LO -> L (nghỉ trưa) -> LO -> ATC -> PT. Chỉ phiên LO được lưu cho phân tích.
- Quy ước màu bảng giá: tím = trần, xanh dương = sàn, vàng = tham chiếu, xanh lá = tăng, đỏ = giảm; giá hiển thị nghìn đồng; ô vừa đổi được tô nền theo màu mức giá.

## Dữ liệu và cách chạy
- Hằng ngày trong giờ giao dịch: `python scripts/run_live.py` (~9:10), tự dừng khoảng 15:02. Chỉ số hỏi mỗi 5 giây, sổ lệnh VN30 mỗi phút (bảng giá VN30 làm mới 5 giây để hiển thị), bảng giá các sàn mỗi phút.
- Không có lịch sử trong REST: **không ghi thì mất**. Đã có phiên đầy đủ 29/10 (225 lần chụp, 6.750 dòng). Mục tiêu **ít nhất 5 phiên, tốt nhất 10**. Ngày đi học mang laptop nên không ghi được.
- Windows, `.venv`; pip dùng `--break-system-packages` chỉ khi ở môi trường cloud.

## Việc còn lại (theo thứ tự ưu tiên)
1. Ghi thêm các phiên (cần >= 5) để làm kiểm chứng: event study cho cảnh báo, liquidity commonality (Chordia-Roll-Subrahmanyam), dạng chữ U trong ngày.
2. Kiểm chứng bảng giá các sàn bằng dữ liệu NEO thật (phiên 30/10), sau đó cân nhắc nâng HOSE/HNX lên 15 giây (cần đo, tránh lỗi 429).
3. Spread theo bước giá: ĐÃ LÀM 1/11 (`tick_size`, `spread_ticks` trong liquidity.py; 3/11 ĐỔI: điểm thanh khoản (rank_symbols, cũng là cổng Bộ lọc) dùng spread bps TRUNG BÌNH vì là chi phí thật; chấm theo bước giá làm điểm ngược với chi phí (VIC 4 bps bị Loại, SHB 47 bps đứng đầu); cảnh báo vẫn dùng số bước giá vì mỗi mã so với chính nó). Baseline theo khung giờ: ĐÃ LÀM 2/11 (`analytics/baseline.py`, Radar dùng thay cửa sổ trượt của anomaly.py): so cùng mã, cùng khung 30 phút, tối đa 10 phiên trước (>= 2 phiên, >= 20 lần chụp); độ sâu và |lệch| dùng z bền vững trung vị/MAD; spread dùng số bước giá + tỷ lệ đuôi <= 5% (MAD spread = 0 ở 92% nhóm); cảnh báo phải kéo dài >= 2 lần chụp, đếm theo đợt. Phiên 30/10: 67 đợt ở 20 mã, hết dồn đầu phiên. Còn lại: hiệu chỉnh ngưỡng khi có >= 5 phiên; chi phí tác động lệnh cỡ Q; kiểm chứng H1/H4.
4. WebSocket: đã có bộ ghi thử nghiệm song song (`run_live.py --ws` hoặc `scripts/record_ws.py`, bảng `ws_quotes` thanh 5 giây, `scripts/compare_ws_rest.py` đối chiếu với REST). REST vẫn là nguồn chính thức; chưa dùng WS cho phân tích cho đến khi đối chiếu khớp. 2/11: `probe_ws_schema.py` chạy thật, nhận 26 schema; bộ ghi WS đã chuyển sang giải mã bằng schema (sync mỗi lần kết nối, lui về giải mã thủ công nếu lỗi) và ghi kênh marketData vào `ws_trades` (PK symbol+seq; ts = giờ sàn, giây UTC -> UTC+7; lastColor B/S chưa kiểm chứng nghĩa). sequenceMsg đánh chung mọi mã. Cần một phiên đầy đủ với `run_live.py --ws` rồi `compare_ws_rest.py` (có phần so tổng khối lượng khớp WS với REST). 30/10 giải mã cũ: giá mức 1 khớp 98,8%. 4/11 (sau khi sửa thanh 5 giây): mọi trường khớp >95%, ws_trades 99,8% khối lượng REST, 0 lần kết nối lại; 88/91 dòng REST không ghép được là TCX khóa trần (bộ ghi WS trước đây bỏ dòng khóa trần, đã sửa: lưu như REST).
5. Báo cáo, video demo, README, cập nhật file Excel theo dõi; nộp trước 1/12/2026.

## WebSocket: phát hiện từ NeoInvestSDK (đọc mã nguồn 1/11/2026, chưa kiểm chứng trên máy chủ thật)
- Tin nhị phân = 1 byte id schema + bản ghi Avro. Id: 1 marketData, 2 marketInfo, 3 stockInfo, 10 marketVolume, 23 fuTopNPrice, 26 marketSession (khớp byte đầu thật của tin mẫu 28/10).
- Bước sync (`{"type":"sync","data":hash}`) làm máy chủ gửi schema (byte 101 + base64(zlib(JSON))) => giải mã chính xác mọi kênh. Mã: `src/neo_api/avro_sync.py`, thử bằng `scripts/probe_ws_schema.py`.
- Kênh marketData có từng lần khớp (matchedPrice, tradingVolume, timestamp, sequenceMsg, lastColor): có thể đủ để tính effective spread, khớp theo phút thật, phát hiện mất tin bằng sequenceMsg. Dự án chưa đăng ký kênh này.
- NeoInvestSDK mặc định trỏ tới máy chủ UAT và có API đặt lệnh: KHÔNG cài vào dự án (quy tắc chỉ đọc).
