# AGENT.md: luật làm việc giữa sinh viên và trợ lý (BẮT BUỘC đọc trước khi làm bất cứ việc gì)

Tệp này là luật. Ngữ cảnh dự án ở `CLAUDE.md`, thiết kế và quy ước giao diện/dữ liệu ở `DESIGN.md`.
Khi ba tệp mâu thuẫn nhau: luật an toàn và dữ liệu ở mục 1 thắng; còn lại thì hỏi, không tự chọn.

## 1. Quy tắc bất di bất dịch
1. **Chỉ ĐỌC dữ liệu thị trường.** Không đặt, sửa, hủy lệnh thật (cần văn bản chấp thuận của giảng viên). Không cài `ssi-sdk`
   hay NeoInvestSDK (có API đặt lệnh). Không dùng và không lưu Private Key của SSI.
2. **Bảo mật:** không in, ghi, commit hay chia sẻ token JWT, mật khẩu, số tài khoản, khóa API. `.env` không commit. Mật khẩu chỉ ở
   bộ nhớ tiến trình.
3. **Dữ liệu phải đúng, hơn mọi thứ khác.** Thiếu thì để trống hoặc "–"; không đoán, không điền, không nội suy. Đổi giao diện
   hoặc cấu trúc mã không được làm đổi số: phải chứng minh bằng so sánh trước và sau khi nghi ngờ.
4. **Giới hạn NEO:** 5 yêu cầu mỗi giây, IP phải đăng ký. Không tăng tần suất gọi khi chưa đo.
5. **Dữ liệu của sinh viên là thứ không thay thế được** (NEO không có lịch sử, không ghi thì mất): không xóa, không ghi đè, không
   sửa `data/market.db`, `data/raw/`, `data/market_backup_*.db`. Cần đụng vào thì hỏi, và sao lưu trước.
6. Người dùng là **sinh viên mới học**: giải thích ngắn, tiếng Việt, tránh thuật ngữ không cần thiết.

## 2. Phạm vi sửa: chỉ sửa tệp được yêu cầu
- Chỉ chạm tệp liên quan **trực tiếp** tới việc sinh viên nhờ. Thấy tệp khác có lỗi, cũ, xấu, thừa: **ghi lại và báo**, không tự sửa.
- Muốn sửa thêm bất kỳ tệp nào ngoài yêu cầu (kể cả dọn import, đổi tên, định dạng lại, cập nhật tài liệu, sửa lỗi thấy trên đường đi)
  thì **hỏi trước** và chờ trả lời.
- Không viết lại cả tệp khi chỉ cần sửa vài dòng. Đọc tệp trước khi sửa (tránh sửa đè thay đổi của người khác). Không đổi kiểu
  xuống dòng (CRLF/LF) của tệp.
- Không xóa tệp, không đổi tên hay chuyển tệp nếu chưa được đồng ý rõ cho đúng tệp đó.
- Không thêm thư viện mới, không đổi schema cơ sở dữ liệu, không đổi cách tính một con số nếu chưa hỏi.
- Nếu thay đổi làm README, CLAUDE.md hoặc DESIGN.md lỗi thời: nêu trong báo cáo và hỏi có cập nhật không (trừ khi yêu cầu đã gồm tài liệu).

## 3. Vòng làm việc cho MỖI yêu cầu (không bỏ bước)
1. **Hiểu:** nói lại yêu cầu trong một câu nếu có thể hiểu hai cách. Mơ hồ thì hỏi (mục 5), đừng đoán.
2. **Phân loại:** việc nhỏ (làm luôn) hay việc lớn (nhận xét và hỏi trước, mục 4).
3. **Làm nhỏ, đúng phạm vi.** Hàm tính toán mới hoặc đổi thì viết hoặc cập nhật test cùng lúc.
4. **Chạy `python -m pytest` bằng `.venv` của dự án.** Phải xanh hết. Tài liệu thuần (md) cũng chạy, để chắc không vỡ gì.
   Đỏ thì **không commit**: sửa nguyên nhân (trong phạm vi) hoặc báo sinh viên, không sửa test cho khớp cái sai.
5. **Đụng giao diện thì mở trang thật** (khởi động Streamlit ở cổng riêng như 8765, không đụng bản đang chạy của sinh viên) và kiểm tra:
   không lỗi, số liệu đúng, trạng thái thiếu dữ liệu vẫn rõ. Test xanh chưa đủ để nói giao diện đúng.
6. **Commit cục bộ ngay** khi bước 4 và 5 xong: một việc một commit, thông điệp tiếng Việt nói rõ đã đổi gì và vì sao, ghi số test
   qua. Chỉ `git add` đúng các tệp của việc đó (không `git add -A`). Không `--no-verify`, không `--amend`, không `push --force`,
   không rewrite lịch sử. Repo chưa có remote nên **không push**; có remote thì hỏi sinh viên trước lần push đầu.
7. **Báo cáo ngắn:** đã đổi gì (tệp nào), kết quả test (số bài), đã xem giao diện chưa, cái gì chưa làm hoặc chưa kiểm chứng, việc
   ngoài phạm vi tôi đã thấy. Không nói "xong" khi chưa chạy test.

## 4. Việc lớn: nhận xét rồi hỏi trước
Việc lớn là một trong: chạm từ 3 tệp trở lên; đổi cách tính một con số hay ngưỡng cảnh báo; đổi schema hoặc thêm bảng; thêm thư viện;
đổi bố cục hay hành vi của một trang; đụng dữ liệu đã ghi; xóa hoặc chuyển tệp; thêm nguồn dữ liệu mới; mọi thứ khó hoàn tác.
Với việc lớn: nêu nhận xét (ưu nhược, rủi ro tới số liệu), đề xuất một phương án, hỏi, **rồi mới làm**. Không cắt hay mở rộng
phạm vi tự ý: sinh viên nói làm gì thì làm đúng cái đó.

## 5. Giao thức câu hỏi (để hai bên không vướng nhau)
Hỏi khi: yêu cầu hiểu được hai cách; có nhiều hướng khác nhau về số liệu hay giao diện; cần sửa tệp ngoài phạm vi; việc khó hoàn tác;
thiếu thông tin mà không đọc được từ mã hay dữ liệu.
Không hỏi khi: câu trả lời đọc được trong mã, README, CLAUDE.md, DESIGN.md hoặc dữ liệu; việc nhỏ trong phạm vi và có cách làm hiển nhiên.
Cách hỏi:
- Mỗi lượt tối đa 3 đến 4 câu, mỗi câu tự đứng được (không cần đọc phần trước mới hiểu).
- Mỗi câu có 2 đến 3 phương án, **ghi rõ phương án đề xuất** và hệ quả của từng cái (nhất là tới số liệu và tới tệp phải sửa).
- Sau khi sinh viên chọn thì làm theo, không hỏi lại điều đã chốt. Quyết định đã chốt ghi vào CLAUDE.md hoặc DESIGN.md khi được cho phép.
- Khi thấy hai bên đang hiểu khác nhau: dừng, nói lại điều mình hiểu bằng một câu và hỏi, đừng làm tiếp theo ý mình.

## 6. Trung thực khi báo cáo
- Phân biệt **đã xác nhận bằng dữ liệu thật**, **suy ra**, và **chưa kiểm**. Không viết suy đoán như sự thật (ví dụ giá SSI điều chỉnh cổ tức
  hiện chỉ là "có dấu hiệu").
- Test đỏ, bước bị bỏ, kiểm tra không chạy được: nói thẳng kèm kết quả thật. Không làm đẹp số liệu để báo cáo trông xong.
- Nguồn dữ liệu luôn nêu rõ (NEO hay SSI). Không trộn hai nguồn thành một số mà không có nhãn.

## 7. Môi trường
- Windows. Dùng `.venv` của dự án (`.venv\Scripts\python.exe -m pytest`). Terminal báo `No module named pytest` thường là đang dùng nhầm môi trường.
- Nếu pandas bị chặn (`Application Control policy has blocked`): đó là Smart App Control của Windows. Báo sinh viên, không tự đổi cài đặt bảo mật hệ thống.
- Chạy Streamlit để kiểm tra: cổng riêng (8765), tắt sau khi xong. Sửa tệp khi server đang chạy thì khởi động lại server.
- Đường dẫn và lệnh trong tài liệu dùng dạng sinh viên chạy được trên Windows.
