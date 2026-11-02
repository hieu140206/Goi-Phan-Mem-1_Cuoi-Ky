# Radar thanh khoản VN30

Đồ án cá nhân cuối kỳ, học phần Gói phần mềm ứng dụng cho tài chính 1 (Khoa Tài chính Ngân hàng, UEL).
Công cụ giúp nhà đầu tư cá nhân và chuyên viên phân tích thấy mã nào đang khó mua bán, và khi nào spread hoặc
độ dày sổ lệnh lệch khỏi mức thường lệ của chính mã đó. Nguồn dữ liệu chính: NEO API của VPBankS (WebSocket sổ lệnh 3 mức giá).

> Đây là công cụ phân tích học thuật, không phải khuyến nghị đầu tư. Ứng dụng chỉ đọc dữ liệu thị trường,
> không gửi, sửa hay hủy lệnh thật.

## Trạng thái hiện tại
- Chạy trên **dữ liệu NEO thật** do bộ ghi lưu vào `data/market.db` (các phiên từ 28/10/2026). Dữ liệu mô phỏng
  (`data_sample/`) vẫn có để chạy thử khi chưa có dữ liệu thật; giao diện ghi rõ khi đang dùng nguồn mô phỏng.
- REST đã xác nhận bằng dữ liệu thật: 4.3, 4.4, 4.5, 4.6, 4.7 (30 mã VN30 một lần gọi), 4.9. REST là nguồn chính thức.
- WebSocket đã kết nối thật qua `wss://`, nhận schema Avro bằng bước "sync" và giải mã được mọi kênh (2/11/2026).
  Bộ ghi WebSocket chạy song song để đối chiếu với REST (xem mục cuối).
- Ứng dụng chỉ đọc dữ liệu thị trường. Token của tài khoản chứng khoán có thể đặt lệnh thật, nên đừng bao giờ chia sẻ token hay mật khẩu.

## Cài đặt (Windows)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
macOS/Linux: dùng `source .venv/bin/activate` thay cho dòng `activate`.

## Chạy
```
streamlit run src/app/app.py     # mở bảng điều khiển tại http://localhost:8501
python -m pytest                 # chạy kiểm thử
python scripts/generate_sample_data.py   # tạo lại dữ liệu mô phỏng (tùy chọn)
```
Chạy mọi lệnh từ thư mục gốc dự án.

## Cấu hình khi đã có NEO API
1. Sao chép `.env.example` thành `.env` (địa chỉ NEO đã điền sẵn). **Không commit `.env`.**
   Để trống `NEO_USERNAME` và `NEO_PASSWORD` thì chương trình hỏi trên dòng lệnh (mật khẩu không hiển thị), lấy token và chỉ giữ trong bộ nhớ.
   Token không được lưu ra đĩa: mỗi lần chạy phải đăng nhập lại, và bộ ghi tự đăng nhập lại nếu NEO từ chối token giữa chừng.
   Tài liệu NEO ghi địa chỉ WebSocket `ws://` (không mã hóa) và token gửi trong tin nhắn xác thực; thử `wss://` nếu NEO hỗ trợ và tránh wifi công cộng.
2. Đăng ký IP máy chạy với NEO (NEO kiểm soát địa chỉ IP).
3. Kiểm tra đăng nhập và REST: `python scripts/check_neo.py` (không in token).
4. Kiểm tra WebSocket thật: `python scripts/probe_ws_schema.py` (lấy schema, nghe 20 giây, in mẫu từng kênh, không ghi dữ liệu).
   Che dòng tài khoản và thông tin cá nhân nếu chụp lại.
5. **Ghi dữ liệu mỗi phiên giao dịch (cách chính):** khoảng 9:05 mỗi ngày giao dịch, chạy `python scripts/record_rest.py`.
   Bộ ghi gọi REST 4.4 (trạng thái phiên) và 4.7 (sổ lệnh cả rổ VN30) mỗi 60 giây, tức 2 yêu cầu/phút.
   Chỉ lần chụp trong phiên khớp lệnh liên tục (`LO`) được đưa vào `data/market.db` cho Radar; phản hồi gốc mọi lần
   chụp (ATO/LO/ATC) được lưu nén ở `data/raw/<ngày>/stocks.jsonl.gz`. Hết phiên, bộ ghi lưu chuỗi VN30/VNINDEX
   trong ngày (4.2) và độ rộng thị trường (4.3), ghi tóm tắt phiên vào `data/sessions.csv` rồi tự dừng.
   Nếu 4.4 lỗi, bộ ghi đoán phiên theo giờ; lỗi một lần chụp không làm dừng bộ ghi. Thứ 7, chủ nhật không ghi.
   **Xem trực tiếp (một lệnh):** `python scripts/run_live.py` đăng nhập một lần, chạy bộ ghi ở nền và mở dashboard với công tắc
   "Trực tiếp: tự cập nhật" đã bật. Dashboard chỉ đọc `market.db` và tự tải lại khi bộ ghi ghi thêm, nên dữ liệu trễ tối đa
   khoảng 1 phút (bộ ghi chụp mỗi phút). Bộ ghi tự dừng khi hết phiên, dashboard vẫn mở để xem lại; Ctrl+C để tắt cả hai.
   Cảnh báo trực tiếp và cảnh báo khi phát lại cùng một cách tính (chỉ dùng dữ liệu trước thời điểm đó, không nhìn trước).
   **Hai trang của ứng dụng:** `src/app/app.py` là cổng vào (điều hướng, công tắc Trực tiếp). Trang **Tổng quan thị trường**
   (`overview.py`) có 4 thẻ chỉ số VN-Index, VN30, HNX-Index, UPCoM-Index, bảng giá VN30, độ sâu, độ rộng và thanh khoản thị trường.
   Trang **Radar thanh khoản** (`radar.py`) là phần phân tích sổ lệnh và cảnh báo. Giao diện dùng chung nằm ở `theme.py`.
   Bộ ghi mỗi phút còn gọi NEO 4.3 và lưu các chỉ số vào bảng `market_index` trong `market.db` (3 yêu cầu API mỗi phút);
   ngày ghi từ bản cũ chưa có bảng này thì trang Tổng quan dùng `data/raw/<ngày>/market.json` (4.2 và 4.3 cuối ngày).
   **Bảng giá toàn thị trường (bản 29/10):** bộ ghi (run_live) mỗi phút còn gọi 4.6 cho HOSE, HNX, UPCoM, ETF và chứng quyền
   (chia 300 mã mỗi lần) và 4.9 cho 4 hợp đồng VN30. Bảng `board` chỉ giữ ảnh chụp MỚI NHẤT của mỗi ngày (cuối ngày là bảng giá lúc
   đóng cửa); bảng `depth_market` giữ tổng độ sâu theo sàn từng phút (phiên LO); bảng `futures` giữ hợp đồng từng phút để tính basis
   (giá khớp trừ điểm VN30). Mỗi 10 lần chụp, phản hồi gốc 4.6 được lưu vào `data/raw/<ngày>/board.jsonl.gz`, và 4.9 vào `futures.jsonl.gz`.
   Trang Tổng quan có các tab VN30, HOSE, HNX, UPCoM, ETF, Chứng quyền, Phái sinh và đổi phạm vi độ sâu (VN30, HOSE, HNX, UPCoM).
   **Bảng giá nhảy màu:** ở chế độ Trực tiếp, khung bảng giá tự làm mới mỗi 5 giây; bộ ghi hỏi thêm 4.7 mỗi 5 giây chỉ để HIỂN THỊ
   bảng giá VN30 (ghi đè nhóm "VN30" của bảng `board`; dữ liệu phân tích vẫn là ảnh chụp mỗi phút trong bảng `quotes`). Ô nào đổi so với
   lần cập nhật trước được tô nền theo màu mức giá: xanh lá (trên TC), đỏ (dưới TC), vàng (bằng TC), tím (trần), xanh dương (sàn).
   **Chốt số cuối ngày:** HOSE hết phiên khớp lệnh lúc 14:45 nhưng chỉ số còn đổi (giá đóng cửa ATC, HNX/UPCoM khớp tới 15:00, giao dịch
   thỏa thuận). Bộ ghi bản mới vì vậy hỏi 4.3 mỗi 30 giây tới 15:02 rồi mới dừng. Phiên ghi bằng bản cũ: chạy
   `python scripts/close_snapshot.py` từ 15:00 cùng ngày để lưu số cuối ngày (chỉ số, bảng giá VN30, các sàn, phái sinh) vào market.db (khoảng 12 yêu cầu GET).
   **Vòng chỉ số nhanh:** giữa hai lần chụp sổ lệnh, bộ ghi hỏi 4.3 mỗi 5 giây (`--fast 5`, tắt bằng `--fast 0`; `--no-boards` tắt
   bảng giá các sàn). Thẻ chỉ số của dashboard tự đọc lại mỗi 5 giây ở chế độ Trực tiếp. Ngày ghi từ bản cũ không có các bảng mới:
   giao diện nói rõ "chưa có dữ liệu" chứ không điền số.
   **Bảng giá kiểu bảng điện** (trang Tổng quan): mã, TC, trần, sàn, 3 mức mua, khớp lệnh, 3 mức bán, tổng KL. Giá trần, giá sàn
   và KL khớp gần nhất là cột mới của bộ ghi. Dữ liệu ghi trước đó (ví dụ phiên 28/10) để trống 3 cột này; điền lại đúng nguyên
   văn từ phản hồi gốc đã lưu bằng `python scripts/backfill_extra.py` (chạy một lần, không gọi NEO, không ước lượng).
   Cơ sở dữ liệu cũ tự được thêm cột khi mở lại, dòng cũ giữ nguyên.
   **Bù chuỗi chỉ số cuối ngày:** bộ ghi mới lưu chuỗi 4.2 cho VN30, VN-Index, HNX-Index, UPCoM-Index khi hết phiên. Phiên ghi bằng
   bản cũ (như 28/10) chỉ có VN30 và VN-Index; chạy `python scripts/fetch_day_index.py` SAU 14:45 CÙNG NGÀY để bù HNX và UPCoM
   (chỉ thêm phần thiếu, từ chối nếu chạy sớm hay sang ngày khác vì chuỗi 4.2 không có ngày).
6. WebSocket: máy chủ chuyển `ws://` sang `wss://` (khác tài liệu) và gửi tin nhị phân Avro, không phải JSON như tài liệu.
   Từ 2/11/2026 giải mã bằng schema máy chủ gửi qua bước "sync" (`avro_sync.py`); `binary_msg.py` là cách giải mã thủ công
   cũ, dùng dự phòng. WebSocket đang là nguồn phụ để đối chiếu.

## Hướng mở rộng (gợi ý 2 của đề: bộ lọc cổ phiếu thông minh)
Sau khi bản thanh khoản chạy ổn trên dữ liệu thật, bổ sung xếp hạng đa yếu tố: giữ thanh khoản và mất cân bằng làm lõi,
thêm tối đa 2 yếu tố là dòng tiền nước ngoài và động lượng giá. Đây là công cụ sàng lọc và so sánh, không dự báo giá;
trọng số phải có lý do và kết quả phải kiểm chứng không nhìn trước tương lai. Chưa cài đặt, chỉ có trong kế hoạch.

## Cấu trúc
```
src/neo_api/    kết nối NEO: cấu hình, giới hạn tần suất, REST, WebSocket (stream.py)
src/data/       cột chuẩn và làm sạch (schema), lưu trữ SQLite, chụp snapshot (snapshot.py), bộ mô phỏng
src/finance/    chỉ số thanh khoản (spread, độ sâu, mất cân bằng, điểm xếp hạng), lọc phiên ATO/ATC, tỷ lệ hấp thụ,
                yếu tố nước ngoài và động lượng (factors.py, chưa nối vào giao diện)
src/analytics/  phát hiện bất thường bằng z-score cuốn chiếu, điểm rủi ro LRS
src/app/        bảng điều khiển Streamlit
tests/          kiểm thử cho hàm tính toán, làm sạch dữ liệu, lưu trữ
scripts/        tạo dữ liệu mô phỏng, ghi luồng WebSocket
data_sample/    dữ liệu mô phỏng (KHÔNG phải giá thị trường) và danh sách sự kiện bất thường cài sẵn
docs/, report/  tài liệu và báo cáo
```

## Luồng xử lý
NEO API → thu thập (`stream.py`) → chuẩn hóa/lưu trữ (`schema.py`, `storage.py`) → chỉ số tài chính (`liquidity.py`)
→ phát hiện bất thường (`anomaly.py`) → bảng điều khiển (`app.py`) → người dùng.

## Chế độ xem trên dashboard
- **Tổng hợp theo kỳ:** xem các phiên đã chọn, lọc theo mã.
- **Phát lại một phiên:** tua từng bước (nút Phát, Dừng, Về đầu) để tái hiện một phiên đã ghi, dùng được khi sàn đã đóng cửa.
  Dashboard đọc từ tệp mẫu hoặc SQLite nên không giữ WebSocket bên trong Streamlit; script ghi dữ liệu chạy riêng.
- **Trực tiếp:** bật công tắc "Trực tiếp: tự cập nhật" (hoặc chạy `python scripts/run_live.py`) để dashboard tự đọc lại khi
  bộ ghi ghi thêm dữ liệu; nút "Tải lại" đọc lại ngay.

## Phương pháp tóm tắt
- Chỉ dùng các lần chụp trong phiên khớp lệnh liên tục (09:15-11:30, 13:00-14:30); loại ATO, ATC, nghỉ trưa.
- Spread tương đối (bps) = (bán tốt nhất − mua tốt nhất) / giá giữa × 10.000.
- Độ sâu = tổng giá × khối lượng của 3 mức mua và 3 mức bán.
- Lệch mua/bán = (mua − bán) / (mua + bán).
- Điểm thanh khoản 0-100: xếp hạng tương đối giữa các mã (spread 40%, độ sâu 40%, lệch 20%). Trọng số là giả định ban đầu.
- Điểm rủi ro LRS = w₁·Z(spread) − w₂·Z(độ sâu) + w₃·Z(|lệch mua/bán|), trọng số mặc định 0,4/0,4/0,2 (giả định, chỉnh được).
  Ngưỡng "Chú ý" và "Cao" là phân vị 95% và 99% của LRS trên dữ liệu thu được, không đặt cố định.
- Tỷ lệ hấp thụ = khối lượng khớp giữa hai lần chụp / độ sâu sổ lệnh. Cờ "mỏng, không khớp lệnh" chỉ là dấu hiệu, không kết luận thao túng.
- Cảnh báo: z-score cuốn chiếu chỉ dùng dữ liệu trước thời điểm xét (không nhìn trước tương lai), kèm điều kiện thay đổi tối thiểu
  về kinh tế (spread ≥ 2,5 lần hoặc độ sâu ≤ 0,4 lần trung vị lịch sử).

## Giới hạn đã biết
- Ngưỡng và trọng số chưa được hiệu chỉnh trên dữ liệu thật.
- Kết quả trên dữ liệu mô phỏng (bắt đủ 12/12 sự kiện cài sẵn, không báo động giả) không chứng minh hiệu quả trên thị trường thật,
  vì dữ liệu mô phỏng được tạo đơn giản.
- Z-score kém ổn định khi spread gần như không đổi; đã thêm điều kiện tỷ lệ tối thiểu để giảm báo động giả.
- Tài liệu NEO cho biết giá mức 1 có thể là chữ ATO/ATC hoặc chuỗi số ("29750.0"); bộ làm sạch đã xử lý cả hai và lọc thêm theo giờ, nhưng chưa kiểm tra trên dữ liệu thật.
- Ngưỡng LRS là phân vị nên luôn có khoảng 1% lần chụp ở mức "Cao" dù thị trường yên; chỉ dùng để theo dõi xu hướng.
- Cửa sổ lịch sử chưa loại bỏ dạng chữ U của thanh khoản trong ngày. Hướng cải thiện: so với cùng khung giờ ở các phiên trước.
- Tỷ lệ hấp thụ dùng `totalTradingVolume`; cần kiểm tra trên dữ liệu thật rằng đây là số lũy kế trong ngày.
- Giả định mỗi thông điệp stockInfo là trạng thái đầy đủ của mã; nếu thật ra chỉ chứa trường thay đổi thì phải sửa `Snapshotter.update` thành gộp.
- NEO chưa công bố giới hạn tần suất, số mã tối đa hay số kết nối tối đa của WebSocket; chưa biết theo dõi 30 mã có ổn không.
- NEO không có giá nhiều phiên: động lượng 5/10/20 phiên phải tự lưu giá đóng cửa mỗi ngày (`finance/factors.py: daily_closes`).

## Bộ ghi WebSocket thử nghiệm (chạy song song với REST)
- Cách 1 (khuyên dùng, một đăng nhập): `python scripts/run_live.py --ws`
- Cách 2 (cửa sổ riêng): `python scripts/record_ws.py` cùng lúc với `python scripts/record_rest.py`
- Dữ liệu vào bảng `ws_quotes` (thanh 5 giây, có `n_msgs`, `age_ms`), tin thô ở `data/raw/<ngày>/ws.jsonl.gz`, thống kê ở `ws_stats.json`.
- Từ 2/11/2026 bộ ghi gửi "sync" để lấy schema Avro của máy chủ mỗi lần kết nối và giải mã mọi kênh bằng schema (không có schema thì quay về cách giải mã cũ cho sổ lệnh). Bộ ghi đăng ký thêm kênh `marketData`: từng lần khớp (giá, khối lượng, số thứ tự, giờ sàn tới giây, `lastColor` B/S) vào bảng `ws_trades`, bỏ qua lần khớp trùng.
- Sau phiên: `python scripts/compare_ws_rest.py` để xem WebSocket khớp REST bao nhiêu phần trăm, và tổng khối lượng các lần khớp WebSocket có bằng phần tăng khối lượng của REST không (kiểm tra mất tin). Phiên 30/10 (cách giải mã cũ): giá mức 1 khớp 98,8%, khối lượng mức 1 khớp 88-92%.
- REST vẫn là nguồn chính thức; WebSocket chỉ để đối chiếu (ghi vào bảng riêng `ws_quotes`, `ws_trades`).

## Xuất sổ lệnh WebSocket ra Excel
`python scripts/export_data.py --ws --excel --date 2026-10-30` (bỏ `--date` để xuất mọi ngày). File nằm ở `data/export/so_lenh_ws_<ngày>.csv` và `.xlsx`.

## Thử kết nối WebSocket có schema (chỉ đọc)
`pip install fastavro` rồi `python scripts/probe_ws_schema.py` (chạy được cả ngày nghỉ). Script gửi "sync" để lấy schema Avro của máy chủ,
lưu vào `data/ws_schemas.json`, đăng ký thử vài mã ở các kênh stockInfo, marketData, marketInfo, marketVolume, marketSession và in kết quả.
Cơ sở: đọc mã nguồn NeoInvestSDK 0.2.5 (chưa kiểm chứng trên máy chủ thật). Không cài SDK này vào dự án (có chức năng đặt lệnh).
