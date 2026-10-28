# Radar thanh khoản VN30

Đồ án cá nhân cuối kỳ, học phần Gói phần mềm ứng dụng cho tài chính 1 (Khoa Tài chính Ngân hàng, UEL).
Công cụ giúp nhà đầu tư cá nhân và chuyên viên phân tích thấy mã nào đang khó mua bán, và khi nào spread hoặc
độ dày sổ lệnh lệch khỏi mức thường lệ của chính mã đó. Nguồn dữ liệu chính: NEO API của VPBankS (WebSocket sổ lệnh 3 mức giá).

> Đây là công cụ phân tích học thuật, không phải khuyến nghị đầu tư. Ứng dụng chỉ đọc dữ liệu thị trường,
> không gửi, sửa hay hủy lệnh thật.

## Trạng thái hiện tại
- Chạy được với **dữ liệu mô phỏng** (`data_sample/`). Mọi số liệu trên giao diện khi dùng nguồn này chỉ để minh họa.
- Phần WebSocket NEO (`src/neo_api/stream.py`) đã viết theo tài liệu (xác thực bằng tin nhắn, đăng ký kênh `stockInfo`,
  tự kết nối lại và đăng ký lại), đã thử với máy chủ giả nhưng **chưa thử với NEO thật** vì chưa có token.
  Việc đầu tiên khi có token: `python scripts/record_stream.py --dump 5 VCB` để xem định dạng thật.
- Phần REST (`client.py`) đã xác nhận đăng nhập và `market/indexList` theo ví dụ chạy thật của NEO; các endpoint khác (chi tiết cổ phiếu, danh sách mã theo chỉ số) còn `TODO`.
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
4. Kiểm tra định dạng WebSocket thật: `python scripts/record_stream.py --dump 5 VCB` (chỉ in 5 thông điệp, không ghi gì). Che token và thông tin cá nhân nếu chụp lại.
5. **Ghi dữ liệu mỗi phiên giao dịch (cách chính):** khoảng 9:05 mỗi ngày giao dịch, chạy `python scripts/record_rest.py`.
   Bộ ghi gọi REST 4.4 (trạng thái phiên) và 4.7 (sổ lệnh cả rổ VN30) mỗi 60 giây, tức 2 yêu cầu/phút.
   Chỉ lần chụp trong phiên khớp lệnh liên tục (`LO`) được đưa vào `data/market.db` cho Radar; phản hồi gốc mọi lần
   chụp (ATO/LO/ATC) được lưu nén ở `data/raw/<ngày>/stocks.jsonl.gz`. Hết phiên, bộ ghi lưu chuỗi VN30/VNINDEX
   trong ngày (4.2) và độ rộng thị trường (4.3), ghi tóm tắt phiên vào `data/sessions.csv` rồi tự dừng.
   Nếu 4.4 lỗi, bộ ghi đoán phiên theo giờ; lỗi một lần chụp không làm dừng bộ ghi. Thứ 7, chủ nhật không ghi.
6. WebSocket (`record_stream.py`, `explore_channels.py`): đã kết nối được qua `wss://` (máy chủ chuyển `ws://` sang
   `wss://`, khác tài liệu). Tin trả về là nhị phân (giống Avro), không phải JSON như tài liệu; `binary_msg.py` giải mã
   được kênh `marketSession` (thứ tự trường khớp tài liệu 6.2). Các kênh còn lại cần kiểm tra thêm trong giờ giao dịch,
   nên WebSocket đang là nguồn phụ.

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
- Chưa có tự làm mới theo thời gian thực: dùng nút "Tải lại dữ liệu".

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
