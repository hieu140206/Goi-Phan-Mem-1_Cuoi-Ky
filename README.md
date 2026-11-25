# Bộ lọc cổ phiếu VN30 với Radar thanh khoản

Đồ án cá nhân cuối kỳ, học phần Gói phần mềm ứng dụng cho tài chính 1 (Khoa Tài chính Ngân hàng, UEL).
Bộ lọc cổ phiếu VN30 cho nhà đầu tư cá nhân (gợi ý 2 của đề), xây trên Radar thanh khoản (gợi ý 3 và 6): Radar cho biết
mã nào đang khó mua bán và khi nào spread hoặc độ dày sổ lệnh lệch khỏi mức thường lệ của chính mã đó; bộ lọc dùng kết quả
này làm cổng, rồi xếp hạng các mã qua cổng theo dòng tiền nước ngoài và động lượng giá so với VN30.
Nguồn dữ liệu chính: NEO API của VPBankS (REST, WebSocket để đối chiếu). Nguồn phụ: SSI FastConnect API (lịch phiên và số
liệu cuối ngày để đối chiếu, và sổ lệnh dự phòng khi bộ ghi NEO không chạy đủ phiên); mọi chỗ dùng SSI đều ghi rõ nguồn trên giao diện.

## Bốn trang, nối với nhau qua "một mã"
| Trang | Nội dung |
| --- | --- |
| Tổng quan thị trường (`overview.py`) | 4 chỉ số, bảng giá nhiều sàn, độ sâu, độ rộng, giá trị giao dịch. Bấm mã trong bảng giá (mọi nhóm) để mở hộp thoại chi tiết có biểu đồ nến OHLC (nguồn SSI); mã VN30 có liên kết sang hồ sơ thanh khoản |
| Bộ lọc cổ phiếu (`screen_page.py`) | Bối cảnh thị trường; cổng thanh khoản (Đạt / Chú ý / Loại); xếp hạng theo dòng tiền ngoại và động lượng; chọn dòng để mở hồ sơ mã |
| Radar thanh khoản (`radar.py`) | Xếp hạng thanh khoản, đợt cảnh báo, chi phí theo giờ, diễn biến một mã, phát lại phiên với bản đồ nhiệt thẻ lật |
| Chi tiết mã (`stock.py`, địa chỉ `?ma=FPT`) | Giá, sổ lệnh 3 mức, thanh khoản, vị trí trong bộ lọc, dòng tiền nước ngoài theo ngày, nút theo dõi |

Danh sách theo dõi ở thanh bên (mọi trang) lưu trong `data/watchlist.json` (không commit); mã bị Loại hoặc có đợt cảnh báo
được đánh dấu. Số liệu dùng chung ở `src/app/shared.py`, nên cùng một mã luôn ra cùng một con số trên mọi trang.

> Đây là công cụ phân tích học thuật, không phải khuyến nghị đầu tư. Ứng dụng chỉ đọc dữ liệu thị trường,
> không gửi, sửa hay hủy lệnh thật.

## Trạng thái hiện tại
- Chạy trên **dữ liệu NEO thật** do bộ ghi lưu vào `data/market.db` (các phiên từ 28/10/2026; đến 13/11/2026 có 8 phiên đủ 225 lần
  chụp sổ lệnh mỗi phiên: 28/10, 29/10, 3/11, 4/11, 9/11, 10/11, 11/11, 13/11; phiên 30/10 có 221 lần; 2/11, 5/11, 6/11 dở dang).
  Phiên 12/11 bộ ghi NEO bị dừng sớm nên ứng dụng dùng sổ lệnh SSI cho ngày đó, có nhãn "SSI" (xem mục Nguồn phụ SSI).
  Giao diện chỉ dùng dữ liệu thật: NEO là nguồn chính, SSI bù các ngày NEO không ghi được (có nhãn "SSI"). Dữ liệu mô phỏng (`data_sample/`) KHÔNG còn là lựa chọn trên
  giao diện (25/11/2026), chỉ còn trong mã để kiểm thử; máy chưa có dữ liệu thật thì các trang báo rõ "Chưa có dữ liệu".
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

**Lưu ý trên Windows:** nên dùng Python 3.12 hoặc 3.13 (bản quá mới ít người dùng nên gói như pandas có thể bị chặn). Nếu `pytest` hay
ứng dụng báo `DLL load failed ... An Application Control policy has blocked this file`, nguyên nhân là Smart App Control của Windows chặn tệp `.pyd`
chưa có chữ ký của pandas (xem nhật ký Code Integrity). Cách an toàn: tạo lại `.venv` bằng Python 3.12 hoặc 3.13; cách cuối cùng là tắt Smart App Control
(sau khi tắt không bật lại được nếu không cài lại Windows). Nếu terminal báo `No module named pytest`, kiểm tra đang dùng đúng `.venv` của dự án.

## Chạy
```
streamlit run src/app/app.py     # mở bảng điều khiển tại http://localhost:8501
python -m pytest                 # chạy kiểm thử (342 bài, khoảng 1 phút)
python scripts/run_live.py       # ngày giao dịch: ghi dữ liệu NEO (hỏi mật khẩu) và mở bảng điều khiển
python scripts/validate_alerts.py   # kiểm chứng cảnh báo (chữ U, event study, độ nhạy ngưỡng), ghi vào report/kiem-chung/ (chỉ đọc market.db)
python scripts/record_ssi.py     # (tùy chọn) cửa sổ thứ hai: ghi sổ lệnh SSI song song, dự phòng khi NEO mất kết nối
python scripts/fetch_ssi_history.py --check   # đối chiếu số cuối ngày của SSI với NEO (không gọi mạng)
python scripts/generate_sample_data.py   # tạo lại dữ liệu mô phỏng (chỉ để kiểm thử, giao diện không dùng)
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
   **Các trang của ứng dụng** (xem bảng ở đầu README): `src/app/app.py` là cổng vào (điều hướng, công tắc Trực tiếp). Trang **Tổng quan thị trường**
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

## Nguồn phụ SSI (FastConnect API v3, chỉ đọc)
- **Vì sao có SSI:** NEO không có lịch sử trong REST ("không ghi thì mất") và bộ ghi có ngày bị dừng. Đề cho phép dùng thêm SSI; ứng dụng
  luôn ghi rõ nguồn, không trộn hai nguồn thành một số mà không có nhãn.
- **Khóa:** `SSI_API_KEY` và `SSI_API_SECRET` trong `.env` (xem `.env.example`, không commit). Không dùng và không lưu Private Key (chỉ để ký lệnh
  đặt/sửa/hủy; ứng dụng chỉ đọc). Không cài `ssi-sdk` (có API đặt lệnh); `src/data/ssi.py` tự gọi bằng `requests`.
- **Dữ liệu theo ngày:** `python scripts/fetch_ssi_history.py` lấy giá đóng cửa, khối lượng, mua bán nước ngoài, room và điểm chỉ số vào bảng
  `ssi_daily`, `ssi_index_daily`. Bộ lọc dùng LỊCH phiên từ đây cho động lượng 5 phiên. `--check` đối chiếu với NEO: giá đóng cửa, khối lượng và
  room khớp gần hoàn toàn. **Giá đóng cửa SSI có dấu hiệu là giá đã điều chỉnh theo cổ tức** ở các ngày trước ngày không hưởng quyền (GVR, VNM: giá lẻ, tỷ lệ lệch cố định; chưa đối chiếu thông báo cổ tức), còn NEO là giá giao dịch
  thật; `--check` tách các dòng này ra (giá điều chỉnh có số lẻ) và cảnh báo không dùng giá SSI để tính lợi suất hay động lượng.
- **Sổ lệnh SSI (dự phòng):** bảng `ssi_quotes` (thanh 5 giây của 30 mã VN30, giá và khối lượng 3 mức mua bán) do bộ ghi luồng SSI ghi
  (`wss://stream.ssi.com.vn/ws/v3`, chủ đề `quote.<mã>`; dùng `scripts/probe_ssi.py` để thử luồng). Giá mức 1 khớp NEO REST khoảng 99,8%.
  Bộ ghi là `scripts/record_ssi.py` (mã ở `src/data/ssi_recorder.py`), chạy ở cửa sổ riêng song song với `run_live.py`; `run_live.py` không tự gọi nó
  (xem mục Bộ ghi SSI bên dưới).
- **Bù ngày NEO thiếu:** ngày NEO không có lần chụp nào trong phiên liên tục mà `ssi_quotes` có (hiện là 12/11) thì `shared.load_source` lấy sổ lệnh SSI,
  lấy mẫu mỗi phút (`ssi.load_ssi_minute_quotes`, cùng các phút với NEO; thanh cũ quá 60 giây thì bỏ, không điền). Ngày có NEO luôn dùng NEO. Quy tắc để số không đổi và không lẫn nguồn:
  - SSI không có giá khớp và tổng khối lượng khớp nên các cột đó để trống (giá hiện "–"), không tính tỷ lệ hấp thụ và cờ "không khớp".
  - **Ngày SSI không làm mốc so sánh cho ngày NEO** và không vào nền tính ngưỡng LRS; nên số của các phiên NEO giữ nguyên (đã so 64.473 dòng x 64 cột giống hệt
    khi bật và tắt phần bù). Bản thân ngày SSI được so với mốc là các phiên NEO trước đó, tức là một phép so chéo nguồn.
  - Nhãn "· SSI" ở danh sách phiên (Radar, Chi tiết mã) và ghi chú nguồn ở Radar và Chi tiết mã. Trang Bộ lọc không dùng ngày SSI (cần giá khớp và nước ngoài của NEO).

## Bộ lọc cổ phiếu (gợi ý 2 của đề), logic ở `src/analytics/screener.py`
1. **Cổng thanh khoản** (cùng số với Radar): Loại nếu điểm thanh khoản trong phiên ≤ 33,3 (mốc "Yếu", chỉnh được);
   Chú ý nếu có ít nhất một đợt cảnh báo; còn lại Đạt. Điểm thanh khoản là xếp hạng tương đối nên khoảng 1/3 mã luôn bị Loại.
2. **Yếu tố** (chỉ cho mã qua cổng): dòng tiền nước ngoài = mua ròng / giá trị giao dịch; động lượng = giá khớp / tham chiếu − 1
   trừ % thay đổi VN30 cùng thời điểm. Động lượng 5 phiên chỉ dùng giá đóng cửa hợp lệ (bảng giá chụp từ 14:45, đã có ATC).
3. **Điểm** = trung bình thứ hạng phần trăm hai yếu tố, trọng số bằng nhau.
4. **Bối cảnh thị trường**: số mã tăng/giảm VN-Index, % VN30, basis hợp đồng gần nhất, khối ngoại ròng VN30; chỉ nêu sự kiện.
Đây là công cụ sàng lọc và so sánh, không dự báo giá. Chưa kiểm chứng điểm cao có đi kèm lợi suất ngày sau tốt hơn: cần thêm phiên.

## Cấu trúc
```
src/neo_api/    kết nối NEO: cấu hình, đăng nhập (JWT), giới hạn tần suất, REST (client.py), WebSocket (stream.py, giải mã Avro)
src/data/       cột chuẩn và làm sạch (schema), lưu trữ SQLite (storage), bộ ghi REST và WebSocket, bảng giá nhiều sàn,
                hàm dữ liệu trang Tổng quan, SSI (ssi.py), bộ mô phỏng
src/finance/    chỉ số thanh khoản (spread, độ sâu, mất cân bằng, điểm xếp hạng), lọc phiên khớp lệnh liên tục,
                tỷ lệ hấp thụ, yếu tố nước ngoài và động lượng
src/analytics/  cảnh báo bất thường theo khung giờ (baseline.py), điểm rủi ro LRS, bộ lọc cổ phiếu (screener.py)
config.toml     MỌI hằng số và ngưỡng của phần phân tích (đọc bằng src/model_config.py; cần Python từ 3.11); ngày đặc biệt ở data/special_days.csv
src/app/        bảng điều khiển Streamlit: app.py (cổng vào), 4 trang, shared.py (số liệu dùng chung), flipgrid*.py (bản đồ nhiệt thẻ lật)
tests/          342 bài kiểm thử: hàm tính toán, làm sạch dữ liệu, lưu trữ, bộ ghi, SSI, bản đồ nhiệt
scripts/        ghi dữ liệu (run_live, record_rest, record_ws, record_ssi), kiểm tra và đối chiếu (check_*, compare_ws_rest, fetch_ssi_history --check),
                dựng lại phiên từ dữ liệu gốc (restore_session), xuất dữ liệu, tạo dữ liệu mô phỏng
data_sample/    dữ liệu mô phỏng (KHÔNG phải giá thị trường) và danh sách sự kiện bất thường cài sẵn
docs/, report/  tài liệu và báo cáo
```

## Luồng xử lý
NEO API (và SSI làm nguồn phụ) → thu thập (bộ ghi: `rest_recorder.py`, `ws_recorder.py`) → chuẩn hóa/lưu trữ (`schema.py`, `storage.py`, SQLite `data/market.db`)
→ chỉ số tài chính (`liquidity.py`) → cảnh báo theo khung giờ và điểm LRS (`baseline.py`, `lrs.py`) → bộ lọc (`screener.py`)
→ bảng điều khiển Streamlit (`app.py` và các trang) → người dùng. Bộ ghi và bảng điều khiển là hai phần riêng; bảng điều khiển chỉ đọc `market.db`.

## Chế độ xem trên dashboard
- **Tổng hợp theo kỳ:** xem các phiên đã chọn, lọc theo mã.
- **Phát lại một phiên:** tua từng bước (nút Phát, Dừng, Về đầu, thanh trượt thời điểm) để tái hiện một phiên đã ghi, dùng được khi sàn đã đóng cửa.
  Mỗi bước là một lần chụp sổ lệnh (1 phút, từ NEO REST). **Tốc độ phát** 1x, 2x, 4x = mỗi nhịp sang 1, 2, 4 lần chụp (bảng và biểu đồ khác vẫn tính đủ mọi lần chụp đến thời điểm đó).
  **Bản đồ nhiệt thẻ lật** (treemap): mỗi mã VN30 một ô; màu theo điểm rủi ro LRS (xanh nhạt dễ giao dịch, xám bình thường, cam rồi đỏ khó hơn; viền đậm cho mức Chú ý và Cao),
  diện tích ô theo độ sâu sổ lệnh trung vị của mã trong cả phiên (cố định khi phát để ô không nhảy chỗ). Ô nào đổi điểm sang bước kế tiếp thì lật; có công tắc "Hiệu ứng lật".
  Các mốc của thang màu lấy từ phân phối LRS trên toàn bộ dữ liệu đã ghi (phân vị 5%, 50%, 95%, 99%), chỉ để tô màu, không quyết định mức cảnh báo. Bấm vào ô để mở hồ sơ mã.
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
  Ngưỡng "Chú ý" và "Cao" là phân vị 95% và 99% của các điểm LRS CÓ TRƯỚC thời điểm xét (không nhìn trước), không đặt cố định.
- Tỷ lệ hấp thụ = khối lượng khớp giữa hai lần chụp / độ sâu sổ lệnh. Cờ "mỏng, không khớp lệnh" chỉ là dấu hiệu, không kết luận thao túng.
- Cảnh báo (`analytics/baseline.py`): so từng mã với CHÍNH NÓ ở cùng khung giờ (9:15-9:30 riêng, rồi các khung 30 phút) trong tối đa 10 phiên trước
  (cần ít nhất 5 phiên và 20 lần chụp; chưa đủ thì ghi "Chưa đủ dữ liệu"; đổi ở config.toml),
  chỉ dùng dữ liệu trước phiên đang xét. Spread rộng: từ 2 bước giá trở lên, gấp ít nhất 2,5 lần trung vị và thuộc nhóm 5% rộng nhất của lịch sử; độ sâu mỏng:
  z bền vững (trung vị và MAD) từ -2,5 trở xuống (ngưỡng chỉnh được ở thanh bên, mặc định 2,5) và độ sâu không quá 0,4 lần trung vị. Một cảnh báo phải kéo dài ít nhất 2 lần chụp hợp lệ kề nhau (cách nhau không quá 90 giây, cùng buổi); số liệu đếm theo đợt.
  Cổng của Bộ lọc có thêm nhãn "Chưa đánh giá" cho mã chưa có mốc nền; Radar thêm điểm thanh khoản 30 phút, thống kê chất lượng dữ liệu và ngày đặc biệt.
  Mọi thay đổi và số đo của đợt nâng cấp 24/11/2026 nằm ở CHANGELOG.md. Kiểm chứng cảnh báo (chữ U, event study, độ nhạy ngưỡng) và kết luận ở
  report/kiem-chung/KET_QUA.md; từ 25/11 z độ sâu mặc định 2,5 và spread tối thiểu 2,5 lần trung vị theo kiểm chứng đó.
  Cách này thay cho cửa sổ trượt cũ (so với chiều hôm trước) để không gán nhầm dạng chữ U của thanh khoản trong ngày thành bất thường.

## Giới hạn đã biết
- Ngưỡng và trọng số chưa được hiệu chỉnh trên dữ liệu thật.
- Kết quả trên dữ liệu mô phỏng (bắt đủ 12/12 sự kiện cài sẵn, không báo động giả) không chứng minh hiệu quả trên thị trường thật,
  vì dữ liệu mô phỏng được tạo đơn giản.
- Z-score kém ổn định khi spread gần như không đổi; đã thêm điều kiện tỷ lệ tối thiểu để giảm báo động giả.
- Tài liệu NEO cho biết giá mức 1 có thể là chữ ATO/ATC hoặc chuỗi số ("29750.0"); bộ làm sạch đã xử lý cả hai và lọc thêm theo giờ, nhưng chưa kiểm tra trên dữ liệu thật.
- Ngưỡng LRS là phân vị nên luôn có khoảng 1% lần chụp ở mức "Cao" dù thị trường yên; chỉ dùng để theo dõi xu hướng.
- Cảnh báo đã so cùng khung giờ (thay cho cửa sổ trượt), nhưng chưa có kiểm chứng định lượng (event study, dạng chữ U, hiệu chỉnh ngưỡng) vì mới có khoảng 8 phiên đủ.
- Tỷ lệ hấp thụ dùng `totalTradingVolume`; cần kiểm tra trên dữ liệu thật rằng đây là số lũy kế trong ngày.
- Giả định mỗi thông điệp stockInfo là trạng thái đầy đủ của mã; nếu thật ra chỉ chứa trường thay đổi thì phải sửa `Snapshotter.update` thành gộp.
- NEO chưa công bố giới hạn tần suất, số mã tối đa hay số kết nối tối đa của WebSocket; chưa biết theo dõi 30 mã có ổn không.
- NEO không có giá nhiều phiên: động lượng 5/10/20 phiên phải tự lưu giá đóng cửa mỗi ngày (`finance/factors.py: daily_closes`).
- Phát lại theo phút (từ lần chụp REST), chưa phát theo từng thanh 5 giây của WebSocket dù đã ghi.
- Phiên SSI (12/11) không có giá khớp, khối lượng khớp và nước ngoài, nên Chi tiết mã hiện "–" ở các ô đó, Bộ lọc không có ngày này và không tính tỷ lệ hấp thụ; đây là phép so chéo nguồn, không tính vào các phiên đủ để kiểm chứng bằng NEO.
- Giá đóng cửa SSI có dấu hiệu là giá điều chỉnh cổ tức ở một số ngày (xem mục Nguồn phụ SSI); chưa dùng giá SSI để bù ngày không ghi.
- Sổ lệnh SSI thời gian thực chỉ là nguồn dự phòng: bộ ghi `record_ssi.py` phải được chạy riêng (không nằm trong `run_live.py`), và ngày nào NEO đã có đủ lần chụp thì app luôn dùng NEO.

## Bộ ghi WebSocket thử nghiệm (chạy song song với REST)
- Cách 1 (khuyên dùng, một đăng nhập): `python scripts/run_live.py --ws`
- Cách 2 (cửa sổ riêng): `python scripts/record_ws.py` cùng lúc với `python scripts/record_rest.py`
- Dữ liệu vào bảng `ws_quotes` (thanh 5 giây, có `n_msgs`, `age_ms`), tin thô ở `data/raw/<ngày>/ws.jsonl.gz`, thống kê ở `ws_stats.json`.
- Từ 2/11/2026 bộ ghi gửi "sync" để lấy schema Avro của máy chủ mỗi lần kết nối và giải mã mọi kênh bằng schema (không có schema thì quay về cách giải mã cũ cho sổ lệnh). Bộ ghi đăng ký thêm kênh `marketData`: từng lần khớp (giá, khối lượng, số thứ tự, giờ sàn tới giây, `lastColor` B/S) vào bảng `ws_trades`, bỏ qua lần khớp trùng.
- Sau phiên: `python scripts/compare_ws_rest.py` để xem WebSocket khớp REST bao nhiêu phần trăm, và tổng khối lượng các lần khớp WebSocket có bằng phần tăng khối lượng của REST không (kiểm tra mất tin). Phiên 30/10 (cách giải mã cũ): giá mức 1 khớp 98,8%, khối lượng mức 1 khớp 88-92%.
- REST vẫn là nguồn chính thức; WebSocket chỉ để đối chiếu (ghi vào bảng riêng `ws_quotes`, `ws_trades`).

## Bộ ghi SSI (dự phòng, chạy song song)
- Mục đích: nếu bộ ghi NEO mất kết nối hoặc dừng giữa phiên (như 12/11), vẫn còn sổ lệnh của ngày đó để app bù (ghi rõ nhãn "SSI"). Không thay thế NEO.
- Cách chạy: mở THÊM một cửa sổ terminal (trước 9:15 là tốt nhất) trong thư mục dự án, song song với `python scripts/run_live.py --ws`, không cần tắt hay chạy lại bộ ghi NEO:
  `python scripts/record_ssi.py`. Cần `SSI_API_KEY` và `SSI_API_SECRET` trong `.env`. Tự dừng lúc 15:02; Ctrl+C để dừng sớm.
- Dữ liệu vào bảng `ssi_quotes` (thanh 5 giây, 3 mức giá, kèm `n_msgs`, `age_ms`, `src_ts`), tin thô ở `data/raw/<ngày>/ssi.jsonl.gz`, thống kê ở `ssi_stats.json`.
- Chỉ ĐỌC dữ liệu, không dùng Private Key, không cài `ssi-sdk`. Hai bộ ghi dùng chung `market.db` nhưng ghi vào bảng khác nhau nên không đụng dữ liệu của nhau.

## Xuất sổ lệnh WebSocket ra Excel
`python scripts/export_data.py --ws --excel --date 2026-10-30` (bỏ `--date` để xuất mọi ngày). File nằm ở `data/export/so_lenh_ws_<ngày>.csv` và `.xlsx`.

## Thử kết nối WebSocket có schema (chỉ đọc)
`pip install fastavro` rồi `python scripts/probe_ws_schema.py` (chạy được cả ngày nghỉ). Script gửi "sync" để lấy schema Avro của máy chủ,
lưu vào `data/ws_schemas.json`, đăng ký thử vài mã ở các kênh stockInfo, marketData, marketInfo, marketVolume, marketSession và in kết quả.
Cơ sở: đọc mã nguồn NeoInvestSDK 0.2.5 (chưa kiểm chứng trên máy chủ thật). Không cài SDK này vào dự án (có chức năng đặt lệnh).
