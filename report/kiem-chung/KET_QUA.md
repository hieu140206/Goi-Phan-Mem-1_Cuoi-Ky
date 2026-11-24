# Kết quả kiểm chứng cảnh báo thanh khoản

Sinh bởi `python scripts/validate_alerts.py` (logic ở `src/analytics/validation.py`, có 14 test). Số liệu: 97.902 lần chụp NEO, 30 mã VN30, 16 phiên
(28/10 đến 20/11/2026). Biểu đồ ở `kiem_chung.html` (cần mạng để tải thư viện vẽ), bảng số ở các tệp `.csv` cùng thư mục.
Đây là bằng chứng **sơ bộ**: chỉ có 11 phiên đủ mốc nền, xem mục Giới hạn.

## 1. Dạng chữ U trong ngày: có ở độ sâu (dạng khác), gần như không có ở spread

Câu hỏi: chỉ số có đúng hình dạng trong ngày như các nghiên cứu khác đã thấy (spread cao ở đầu và cuối phiên, thấp ở giữa) không?

| Biến | Kết quả | Độ lớn |
| --- | --- | --- |
| **Spread (bps)** | **Chữ U rất yếu.** Hồi quy bậc hai cong dương có ý nghĩa thống kê (cong +0,13, khoảng tin cậy 95% từ +0,04 đến +0,22; 81% số ngày cong lên), nhưng **trung vị tỷ lệ spread gần như phẳng (1,000 đến 1,002) ở mọi khung 15 phút**. Hai đầu phiên chỉ cao hơn giữa phiên khoảng **3%** (đường khớp), và trong kiểm định dấu hai đầu chỉ cao hơn giữa ở 56% trong 450 cặp (mã, ngày), tỷ lệ trung vị 1,004. | Không đáng kể |
| **Độ sâu 3 mức** | **Không phải chữ U mà là tăng dần.** Độ sâu (so với trung vị trong ngày của chính mã) là **0,48 lúc 9:15**, 0,87 lúc 10:00, 1,00 lúc 10:30, tăng đến 1,18 lúc 14:00. Hai đầu thấp hơn giữa (đường khớp 0,70 lần); chỉ 34% số cặp có hai đầu cao hơn giữa (p < 1e-11). | Rất rõ |

Ý nghĩa:
- **Độ sâu thấp lúc mở cửa** xác nhận lý do bạn so cùng khung giờ: so 9:15 với 14:00 sẽ luôn báo "độ sâu mỏng" lúc mở cửa. Đây là bằng chứng ủng hộ việc tách khung 9:15-9:30.
- **Spread gần như phẳng vì 85% lần chụp đúng 1 bước giá**: spread bị bước giá "kẹp", nên nó không thay đổi nhiều theo giờ. Đừng viết trong báo cáo rằng spread có dạng chữ U. Dạng rõ nằm ở độ sâu.
- Phiên khớp lệnh liên tục không có ATO và ATC, nên có thể không thấy đoạn tăng ở đóng cửa mà các nghiên cứu khác thấy.

## 2. Event study: cảnh báo có thật sự đi cùng thanh khoản xấu kéo dài không?

Cách làm: với mỗi đợt cảnh báo, lấy các lần chụp **sau đó** (1, 5, 10, 15, 30 phút) của chính mã, so với 5 lần chụp đối chứng cùng mã, cùng khung giờ, không có cờ ở lần chụp đó
và 10 lần chụp trước nó. Hiệu = giá trị sau cảnh báo trừ trung bình đối chứng. Khoảng tin cậy bootstrap theo **ngày** (các mã cùng ngày không độc lập).
Có 452 đợt (321 spread, 131 độ sâu); không đợt nào thiếu đối chứng.

**Lưu ý vòng tròn:** cảnh báo được định nghĩa bằng chính spread và độ sâu, nên ở lần chụp 0 và trước đó chúng xấu là hiển nhiên (hiệu +2,31 ở h = 0). Chỉ các lần chụp **sau** có thông tin.

**Cảnh báo độ sâu mỏng: bằng chứng mạnh, xấu kéo dài.** Độ sâu (so với trung vị mốc) sau cảnh báo, đối chứng khoảng 1,10:

| Sau | 1 phút | 5 phút | 10 phút | 30 phút |
| --- | --- | --- | --- | --- |
| Độ sâu sau cảnh báo | 0,38 | 0,51 | 0,57 | 0,68 |
| Hiệu so đối chứng | −0,72 | −0,59 | −0,53 | −0,45 |
| Khoảng tin cậy 95% | −0,82 đến −0,63 | −0,70 đến −0,45 | −0,66 đến −0,34 | −0,57 đến −0,27 |
| Tỷ lệ sự kiện thấp hơn đối chứng | 98% | 93% | 90% | 87% |

Độ sâu vẫn mỏng 30 phút sau cảnh báo. Cần nhớ: độ sâu vốn tự tương quan mạnh (mỏng bây giờ thì phút sau cũng mỏng), nên đây chủ yếu cho thấy cảnh báo **không phải nhiễu một phút**, chưa chứng minh nó dự báo điều gì mới.

**Cảnh báo spread mở rộng: có tin nhưng yếu và chủ yếu thoáng qua.** Spread / trung vị mốc, đối chứng khoảng 1,2:

| Sau | 1 phút | 5 phút | 10 phút | 30 phút |
| --- | --- | --- | --- | --- |
| Hiệu trung bình | +1,43 | +0,68 | +0,44 | +0,25 |
| Khoảng tin cậy 95% | 1,08 đến 1,78 | 0,42 đến 0,97 | 0,15 đến 0,80 | 0,09 đến 0,47 |
| **Hiệu trung vị** | **+1,0** | **0,0** | **0,0** | **0,0** |
| Tỷ lệ sự kiện cao hơn đối chứng | 63% | 42% | 31% | 26% |

Trung bình dương nhưng **trung vị bằng 0 từ phút thứ 5**: đa số cảnh báo spread trở về bình thường trong vài phút; hiệu trung bình do một thiểu số kéo dài. Spread cũng đã rộng hơn từ trước cảnh báo (hiệu +0,74 ở 5 phút trước).

**Biên độ giá sau cảnh báo (biến độc lập với định nghĩa cảnh báo):** trong 5 phút sau cảnh báo, giá dịch chuyển tuyệt đối trung bình **18,4 bps so với 12,3 bps** ở đối chứng (hiệu +6,1; khoảng tin cậy 4,3 đến 7,4; trung vị chỉ +2,2).
Hiệu dương ở mọi độ trễ (đến 30 phút: +8,3, khoảng 1,4 đến 13,9). Với riêng cảnh báo độ sâu, khoảng tin cậy chứa 0 (ít sự kiện hơn). Chưa biết chiều nhân quả: biến động cao có thể vừa làm thanh khoản mỏng vừa làm giá dịch chuyển.

## 3. Hiệu chỉnh ngưỡng: chọn trên phiên đầu, báo trên phiên sau

Tách theo thời gian: **train** = 5/11 đến 13/11 (6 phiên), **test** = 16/11 đến 20/11 (5 phiên). Đổi từng ngưỡng một. Tiêu chí chọn: độ lớn hiệu cao nhất ở train, với điều kiện còn ít nhất 100 đợt ở train,
ít nhất 30 sự kiện đo được cho loại cảnh báo đó, và không quá 5% lần chụp đang cảnh báo. Mặc định: 452 đợt, 2,0% lần chụp.
**Thành thật về quy trình:** lần chạy đầu tôi chọn theo thống kê t, và nó luôn chọn ngưỡng lỏng nhất (t tăng theo số sự kiện, không theo chất lượng). Tôi đổi sang độ lớn hiệu
sau lần chạy đó, và lần chạy đầu đã in cả cột test, nên đây KHÔNG phải một thí nghiệm "mù" hoàn toàn: kết quả test chỉ đáng tin ở mức gợi ý.

| Ngưỡng | Chọn trên train | Hiệu test (h = 10) của giá trị chọn | Hiệu test (h = 10) của mặc định | Đọc |
| --- | --- | --- | --- | --- |
| z độ sâu (mặc định 3) | **2,0** | −0,47 (200 sự kiện) | −0,50 (82 sự kiện) | Tín hiệu **không yếu đi** mà số cảnh báo gấp 2,4 lần: có thể nới xuống 2,0 đến 2,5 |
| Spread tối thiểu (mặc định 2) | **2,5** | +0,50 (90 sự kiện) | +0,38 (149 sự kiện) | Tín hiệu mạnh hơn, ít cảnh báo hơn |
| Đuôi spread (mặc định 5%) | giữ **5%** | +0,38 | +0,38 | Không giá trị nào thắng mặc định theo tiêu chí |
| Số lần chụp liên tiếp (mặc định 2) | giữ **2** | +0,38 | +0,38 | Không giá trị nào thắng mặc định theo tiêu chí |

Nhận xét thêm, **không do tiêu chí chọn mà từ bảng độ nhạy** (`nguong_do_nhay.csv`): ngưỡng chặt hơn gần như luôn cho hiệu lớn hơn nhưng ít cảnh báo hơn (đuôi 1% đến 2%, hoặc 3 đến 4 lần chụp liên tiếp: hiệu test ở 5 phút từ 1,04 đến 1,17 so với 0,62 của mặc định, với 91 đến 173 đợt ở test thay vì 267).
Đây là đánh đổi giữa **chất lượng** và **số lượng** cảnh báo mà dữ liệu không tự quyết được; chọn mức nào là quyết định của bạn.

## Giới hạn phải ghi trong báo cáo

- **Ít phiên:** 11 phiên đủ mốc nền (5/11 đến 20/11, trong đó 5/11 và 6/11 chỉ ghi dở); 5 phiên đầu không có cảnh báo vì chưa đủ mốc nền. Khoảng tin cậy theo ngày vì vậy rộng, và tập test chỉ 5 ngày.
- **Các mã cùng ngày tương quan** (cùng bị ảnh hưởng bởi thị trường); đã bootstrap theo ngày nhưng chỉ còn 10 đến 11 cụm.
- **Nhiều phép so sánh một lúc** (3 biến x 5 độ trễ x 3 nhóm): vài khoảng tin cậy "loại 0" có thể do may mắn; kết quả nhất quán qua nhiều độ trễ đáng tin hơn một ô lẻ.
- **Phần lớn hiệu bị kéo bởi một thiểu số** (trung vị thường gần 0): cảnh báo trung bình chưa nói lên cảnh báo điển hình.
- **Chọn ngưỡng trên 6 phiên rất nhiễu**; chỉ nên coi là gợi ý, không phải ngưỡng tối ưu.
- Chưa kiểm chứng ngoài mẫu (giai đoạn khác, thị trường khác) và **chưa dự báo giá hay lợi nhuận**; chỉ nói về thanh khoản và biến động ngắn hạn.

## Chưa làm, chờ bạn quyết

Các ngưỡng trong `config.toml` **chưa bị đổi**; đổi ngưỡng làm đổi số cảnh báo trên mọi trang. Hai gợi ý có bằng chứng ở trên: z độ sâu 2,5 (hoặc 2,0) và spread tối thiểu 2,5.
