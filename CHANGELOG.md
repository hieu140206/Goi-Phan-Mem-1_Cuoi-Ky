# CHANGELOG

## 25/11/2026: đổi hai ngưỡng theo kết quả kiểm chứng

- `baseline.z_threshold` 3,0 thành **2,5** và `baseline.min_spread_ratio` 2,0 thành **2,5** (`config.toml`), theo `report/kiem-chung/KET_QUA.md`: z độ sâu thấp hơn giữ tín hiệu mà nhiều cảnh báo hơn; spread tối thiểu cao hơn cho tín hiệu mạnh hơn.
- Tác động trên dữ liệu thật (NEO): đợt cảnh báo 452 xuống 431; cảnh báo có spread giảm (321 xuống 197), cảnh báo độ sâu tăng (131 lên 234). Các số cảnh báo, điểm LRS và nhãn cổng ở mọi trang thay đổi theo.
- Căn cứ chỉ là bằng chứng sơ bộ: chọn trên 6 phiên, báo trên 5 phiên, ngưỡng chọn rất nhiễu (xem Giới hạn trong KET_QUA.md). Muốn quay lại: sửa hai số trong `config.toml`.
- Cập nhật mô tả ở Radar và README cho khớp. 342 test qua.

## 24/11/2026: nâng cấp các phần mơ hồ và trường hợp biên của Radar thanh khoản và Bộ lọc

Không đổi công thức cốt lõi (spread bps, spread theo bước giá, độ sâu 3 mức, lệch mua/bán, trọng số 40/40/20). Số test: 245 lên 328.
Mọi hằng số và ngưỡng nay nằm ở `config.toml` (đọc bằng `src/model_config.py`). Mỗi mục một commit, riêng B1 và B5 chung một commit vì dùng chung
mô-đun `finance/quality.py`.

### Từng mục

| Mục | Đã làm | Khác mặc định đề xuất, và vì sao |
| --- | --- | --- |
| Config | `config.toml` gom ngưỡng rải ở 6 tệp; thiếu tệp hoặc thiếu nhóm thì báo lỗi, không dùng số khác. Giá trị giữ nguyên, đã so số trước sau giống hệt. | **TOML thay vì YAML**: máy chưa cài PyYAML, thêm thư viện cần bạn đồng ý; `tomllib` có sẵn từ Python 3.11. Hằng số luật sàn (giờ phiên, hệ số 1,4826) vẫn ở mã. |
| A1 | Radar thêm cột "Điểm 30 phút": cùng công thức 40/40/20, trên 30 lần chụp gần nhất của chính mã, reset sau nghỉ trưa và qua ngày. Dưới một nửa số lần chụp hợp lệ là "Chưa đủ dữ liệu", không chấm và không làm lệch hạng mã khác. | **Cổng của Bộ lọc giữ điểm cả kỳ** (bạn chọn): số trên Bộ lọc không đổi. Cửa sổ tính theo thời gian (30 x 60 giây) chứ không theo 30 hàng, để lần chụp thiếu làm số hợp lệ nhỏ đi thay vì kéo dài cửa sổ. |
| A2 | Mốc nền cần 5 phiên (trước là 2). Khung 9:15-9:30 riêng, sau đó 9:30-10:00, 10:00-10:30... Z là z bền vững (đã chứng minh cùng công thức với 0,6745 x (x - trung vị) / MAD). MAD = 0 thì chia cho độ lệch chuẩn, kẹp +-10, đánh cờ. | **Z của spread giữ phân vị hạng giữa, không dùng MAD**: khoảng 90% nhóm mã x khung giờ có MAD = 0 nên z MAD vô nghĩa với spread. Phương án dự phòng chưa lần nào được dùng trên dữ liệu thật (0 dòng). |
| A3 | Ngưỡng P95, P99 chỉ dùng điểm trước t trong tối đa 20 phiên gần nhất; cần 300 điểm; nhãn "Chưa đủ dữ liệu" thay chuỗi rỗng. Đã có test nhìn trước từ trước, nay thêm test và thử đột biến. | Trần 20 phiên chưa tác dụng: hiện chỉ 17 ngày. |
| A4 | Code đã đúng quy tắc (đợt cảnh báo quyết định Chú ý, LRS không đổi nhãn). Thêm `gate.use_lrs` (mặc định tắt) và ghi mức LRS vào cột lý do. | Không khác. |
| A5 | Mã Chú ý đã được xếp hạng cùng mã Đạt. Thêm cột dấu cảnh báo riêng và thông báo khi dưới 10 mã qua cổng (`gate.min_sample_warning`). | Dấu cảnh báo là ký tự đơn giản, không phải emoji màu, dù DESIGN.md hạn chế emoji. |
| B1 | Giá tốt nhất chạm trần/sàn còn đủ hai bên cũng bị loại như khóa trần/sàn; bảng chất lượng theo mã (tỷ lệ không hợp lệ); log sổ chéo, giá lỗi, trùng. | **Dòng không hợp lệ KHÔNG được giữ lại trong khung phân tích kèm cờ**, vẫn bị loại như cũ. Lý do: `normalize_quotes` cũng quyết định bộ ghi lưu gì vào `market.db`, đổi nó có thể làm mất dòng khi ghi. Độ sâu một phía vẫn ở bảng `quotes` và `report["limit_locked"]`, không vào mốc nền. |
| B2 | `data/special_days.csv` (không viết cứng ngày), ngày đáo hạn phái sinh tính bằng code (thứ Năm thứ ba), `scripts/make_special_days.py` chỉ thêm không xóa. Ngày đặc biệt vẫn tính, gắn cờ, không làm mốc nền (và không vào nền ngưỡng LRS). | Mẫu có 15/10, 19/11, 17/12/2026; các loại khác để trống cho bạn điền. |
| B3 | Cột `baseline_status` và `baseline_reason` (nêu số phiên hoặc số lần chụp đang có); Radar ghi rõ phiên nào Chưa đủ dữ liệu. | Không khác. |
| B4 | Tách khung 9:15-9:30; ghi log khi độ sâu lệch quá 2 lần so với khung kế. | Chỉ log, không đổi logic, đúng yêu cầu. |
| B5 | Cờ `gap_flag` (khoảng trống > 90 giây) và `stale_flag`; đợt cảnh báo cần hai lần chụp kề nhau cách không quá 90 giây, không vắt qua nghỉ trưa. | **Ngưỡng dữ liệu cũ (10 lần chụp, 50% mã khác đổi) là lựa chọn của tôi, không từ dữ liệu**; xem việc còn mở. |
| B6 | Cổng thêm nhãn "Chưa đánh giá" (sau Đạt/Chú ý, trước Loại, không có điểm, không làm lệch hạng). Điểm thanh khoản thấp vẫn Loại trước. | Không khác. |
| B7 | `src/app/limits.py`: khối "Giới hạn cần nói thật" tự đếm số phiên, có đủ các ý mới (spread chào, đặt rồi hủy, chụp mỗi phút, số phiên nền). Mô tả phương pháp ở Radar và Bộ lọc cập nhật. | Nói đúng hiện trạng: đã ghi từng lần khớp (`ws_trades`) nhưng chưa dùng cho spread hiệu dụng. |

### Tác động lên số liệu thật (đo trên 16 phiên NEO)

- 5 phiên đầu (28/10, 29/10, 30/10, 3/11, 4/11) mất cảnh báo và LRS vì chưa đủ 5 phiên nền: đợt cảnh báo NEO 706 xuống 454; các phiên còn lại gần như giữ nguyên.
- Cổng 5 phiên đầu: mọi mã không bị Loại nay là "Chưa đánh giá" (24 đến 26 mã) thay vì "Đạt" như trước.
- B1 loại 21 lần chụp chạm trần (FPT 12, SSI 5, TCX 4) trên 97.923; B5 gắn cờ 63 lần chụp sau khoảng trống (60 lần ở phiên 30/10 thiếu 4 phút, 3 lần ở 4/11); 0 lần nghi dữ liệu cũ.
- B2: chỉ 19/11 là ngày đặc biệt; chỉ 20/11 đổi nhẹ (87 xuống 85 đợt).

### Sự cố đã xử lý, nói thẳng
- Commit B2 (`150edcd`) làm hỏng `src/app/screen_page.py` (dấu nháy không khớp) nên trang Bộ lọc sẽ lỗi. Không test nào nạp trang, và hôm đó tôi chỉ mở thử Radar. Phát hiện
  trước khi làm tiếp, sửa ở `32b58e9` kèm `tests/test_pages_smoke.py` (biên dịch mọi tệp và chạy từng trang thật). Không dùng `--amend` theo quy tắc nên lỗi vẫn nằm trong lịch sử.
- Thông điệp của `32b58e9` ghi "322 test qua"; số đúng lúc đó là 319 (tôi cộng nhầm 3 test chưa commit).
- Ở một bước chuỗi lệnh của tôi lỡ commit dù `pytest` báo lỗi thu thập (do một tệp test chưa commit); bản đã commit vẫn xanh (319), đã kiểm tra lại.

## Việc còn mở (mặc định đề xuất chưa kiểm chứng bằng dữ liệu thật; không tự đoán)

1. `stale_run_snapshots = 10` và `stale_peer_share = 0,5` chưa hiệu chỉnh; dữ liệu thật hiện không có ca nào, nên chưa biết ngưỡng có nhạy hay quá lỏng.
2. Ngày đáo hạn phái sinh tính bằng quy tắc thứ Năm thứ ba, chưa xét nghỉ lễ dời lịch. Các loại ngày khác (cơ cấu ETF, review chỉ số, chốt quyền, công bố KQKD) tệp đang để trống, cần bạn điền.
3. **`min_baseline_sessions = 5` làm 5 trong 16 phiên mất cảnh báo.** Phát lại các phiên đầu sẽ không còn cảnh báo. Nếu cần cho demo, hạ về 2 trong `config.toml` (phải ghi trong báo cáo là kết quả nhiễu).
4. B1: nếu bạn muốn giữ dòng không hợp lệ trong khung phân tích kèm cờ (đúng nguyên văn yêu cầu), cần sửa `normalize_quotes` và hai bộ ghi; đó là việc riêng, cần cân nhắc rủi ro mất dòng.
5. Tài liệu chưa cập nhật: `README.md`, `DESIGN.md`, `CLAUDE.md` (số test 328, `config.toml`, `finance/quality.py`, `data/special_days.py`, `app/limits.py`, ngưỡng 5 phiên, nhãn "Chưa đánh giá"). Theo AGENT.md cần bạn đồng ý.
6. `tomllib` cần Python từ 3.11; `.venv` hiện dùng 3.15 nên chạy được, README khuyên 3.12 hoặc 3.13 nên cũng ổn.
7. Chưa kiểm chứng ngoài mẫu: cảnh báo có đi trước thanh khoản xấu đi thật không (event study), dạng chữ U, hiệu chỉnh ngưỡng. Đây vẫn là việc ưu tiên số 1 của đồ án.

## Lỗi logic lớn hơn đã thấy, chỉ liệt kê, không tự sửa

- Cổng "Loại" **không luôn đúng 10/30 mã** như dự đoán: thực tế 1 đến 6 mã mỗi phiên (thường khoảng 4), vì điểm là tổng có trọng số của ba thứ hạng. Nhưng điểm vẫn là xếp hạng *tương đối*, nên luôn có mã bị Loại kể cả khi cả nhóm thanh khoản tốt.
- Nhãn **"Chú ý" quá rộng**: từ 5/11 trở đi thường 7 đến 19 trong 30 mã mỗi phiên có ít nhất một đợt cảnh báo, nên nhãn này gần như không phân biệt được mã. Có thể cần yêu cầu mức "Cao", hoặc từ 2 đợt trở lên.
- Điểm cả kỳ xếp hạng giữa các mã **đang chọn** ở Radar (thanh bên), nên cùng một mã có thể đổi điểm khi bạn chọn nhóm mã khác; cổng Bộ lọc luôn xếp giữa cả 30 mã.
- Số "Chú ý" và số mã có LRS phụ thuộc số phiên đã ghi (nền ngắn thì MAD phản ánh dao động trong phiên), nên so sánh số cảnh báo giữa các giai đoạn khác độ dài nền cần thận trọng.
