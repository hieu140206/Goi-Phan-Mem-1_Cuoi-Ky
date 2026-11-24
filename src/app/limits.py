"""Phần "Giới hạn cần nói thật" (mục B7): một nơi duy nhất, số phiên và ngưỡng được đếm từ dữ liệu và config.toml, không gõ cứng.

Thuần Python (không import streamlit) để kiểm thử được. Giọng thẳng thắn: nói điều công cụ KHÔNG làm được.
"""
from __future__ import annotations


def limits_markdown(n_neo_sessions: int, min_baseline: int, max_baseline: int, n_early_unrated: int = 0) -> str:
    """Danh sách giới hạn dạng Markdown. n_neo_sessions: số phiên NEO hiện có (đếm động); n_early_unrated: số phiên chưa đủ mốc nền."""
    early = (f" Hiện có {n_early_unrated} trong {n_neo_sessions} phiên ở trạng thái Chưa đủ dữ liệu." if n_early_unrated else "")
    few = (" Với số phiên này, bằng chứng về độ tin cậy của cảnh báo còn mỏng." if n_neo_sessions < 20 else "")
    return f"""
- **Số phiên nền hiện có: {n_neo_sessions} phiên NEO.** Mốc nền cần ít nhất {min_baseline} phiên trước và dùng tối đa {max_baseline}; phiên nào chưa đủ thì
  ghi "Chưa đủ dữ liệu", không có cảnh báo và LRS.{early} Hạ mức tối thiểu (config.toml) xuống thấp cho kết quả nhiễu hơn: MAD chủ yếu phản ánh dao động
  *trong* phiên, chưa phản ánh dao động *giữa các* phiên.{few}
- **Trọng số 40/40/20 và mọi ngưỡng là giả định, chưa hiệu chỉnh trên dữ liệu thật** (ngưỡng z, 2 bước giá, 2 lần trung vị, đuôi 5%, 0,4 lần độ sâu,
  P95 và P99, cổng 33,3, cửa sổ 30 lần chụp). Chúng nằm ở config.toml để đổi và thử, nhưng chưa có kiểm chứng ngoài mẫu.
- **Điểm thanh khoản đo chi phí, không đo độ "căng" của sổ lệnh.** Mã giá thấp luôn có bps cao vì bước giá chiếm tỷ lệ lớn (ví dụ SHB có bps cao dù spread
  đúng 1 bước giá), nên bị chấm thấp chứ không hẳn khó giao dịch hơn. Điểm cũng là xếp hạng *tương đối* giữa các mã: luôn có mã đứng cuối dù cả nhóm thanh khoản tốt.
- **Spread đo là spread chào (quoted spread), chưa phải spread hiệu dụng.** Dự án đã ghi từng lần khớp qua WebSocket (bảng ws_trades) nhưng chưa dùng để tính
  spread hiệu dụng hay chi phí tác động lệnh, vì nghĩa của cờ mua/bán chủ động chưa được kiểm chứng.
- **Sổ lệnh 3 mức có thể bị đặt rồi hủy.** Lệch mua/bán và độ sâu chỉ phản ánh áp lực *hiển thị* ở thời điểm chụp, không chứng minh có người thật sự muốn giao dịch ở các mức đó.
- **Chụp mỗi phút bỏ lỡ mọi biến động nhanh hơn một phút.** Spread có thể giãn rồi co lại giữa hai lần chụp mà công cụ không thấy; đợt cảnh báo cần hai lần chụp
  kề nhau (không quá 90 giây) nên càng bỏ sót sự kiện ngắn.
- **Dòng không dùng được cho spread bị loại**, không đoán thay: khóa trần/sàn (một bên sổ lệnh trống), giá tốt nhất chạm trần/sàn, sổ chéo, giá lỗi. Tỷ lệ theo từng mã nằm ở
  mục "Chất lượng dữ liệu theo mã". Lần chụp đứng sau khoảng trống hoặc nghi dữ liệu cũ chỉ bị đánh cờ, vẫn dùng.
- **Ngày đặc biệt** (data/special_days.csv: đáo hạn phái sinh, cơ cấu ETF...) vẫn được tính nhưng không làm mốc nền cho ngày khác. Ngày đáo hạn tính bằng quy tắc
  thứ Năm thứ ba của tháng và chưa xét dời lịch do nghỉ lễ; các loại khác chỉ có khi sinh viên tự điền.
- **Mã chưa đủ lịch sử** (mã mới, hoặc thiếu dữ liệu) ở cổng là "Chưa đánh giá", không phải "Đạt".
- **Cảnh báo là tín hiệu để xem xét thêm**: không giải thích nguyên nhân, không dự báo giá, không phải khuyến nghị đầu tư.
""".strip("\n")
