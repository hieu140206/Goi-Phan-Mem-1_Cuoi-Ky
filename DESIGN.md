# DESIGN.md: thiết kế, quy ước giao diện và quy tắc dữ liệu

Mô tả điều **đang đúng trong mã** (không phải mong muốn). Muốn đổi một quy ước ở đây thì hỏi sinh viên trước (xem `AGENT.md`).

## 1. Sản phẩm
Bộ lọc cổ phiếu VN30 xây trên Radar thanh khoản, dùng NEO API của VPBankS làm nguồn chính (SSI làm nguồn phụ). Người dùng: nhà đầu tư
cá nhân và người quản trị rủi ro. Mục tiêu: cho biết mã VN30 nào đang khó mua bán, khi nào spread hoặc độ sâu lệch khỏi mức thường lệ
của chính mã đó, rồi xếp hạng mã qua cổng thanh khoản theo dòng tiền nước ngoài và động lượng. Chỉ đọc dữ liệu, không giao dịch.
Mọi trang có dòng: "công cụ phân tích học thuật, không phải khuyến nghị đầu tư".

## 2. Kiến trúc và luồng dữ liệu
```
NEO API (REST chính, WebSocket đối chiếu)  ┐
SSI FastConnect (lịch ngày, sổ lệnh dự phòng) ┴→ bộ ghi → SQLite data/market.db → làm sạch → chỉ số tài chính → cảnh báo, LRS
                                                           → bộ lọc → bảng điều khiển Streamlit → người dùng
```
- **Bộ ghi và bảng điều khiển là hai phần riêng.** Bộ ghi giữ mật khẩu trong bộ nhớ và ghi dữ liệu; bảng điều khiển chỉ ĐỌC `market.db`.
- **Bộ ghi SSI chạy song song, không nằm trong `run_live.py`:** `scripts/record_ssi.py` mở ở cửa sổ riêng để có sổ lệnh dự phòng khi NEO mất kết nối
  hoặc dừng giữa phiên; ghi vào bảng `ssi_quotes`, không đụng bảng của NEO. `run_live.py` không có cờ `--ssi` (quyết định 24/11).
- `src/neo_api/`: auth (JWT), client REST (4.1 đến 4.9), giới hạn tần suất, stream WebSocket (nhị phân Avro).
- `src/data/`: `ssi.py` (SSI v3, nguồn phụ chỉ đọc; bảng `ssi_daily`, `ssi_index_daily`; sổ lệnh theo phút từ `ssi_quotes`; nến OHLC `fetch_ohlc` chỉ để hiển thị, không lưu), `candles.py` (nến ngày NEO dự phòng từ bảng `board`), `schema.py` (cột chuẩn,
  làm sạch), `storage.py` (SQLite), `rest_recorder.py`, `ws_recorder.py` và `ssi_recorder.py` (bộ ghi), `market_board.py` (bảng giá nhiều sàn, phái sinh),
  `overview.py` (hàm dữ liệu trang Tổng quan), `backfill.py`, `market_day.py`, `simulator.py`.
- `src/finance/`: `liquidity.py` (spread, độ sâu, mất cân bằng, điểm xếp hạng, điểm cửa sổ trượt 30 lần chụp), `absorption.py`, `factors.py` (yếu tố nước ngoài, động lượng),
  `sessions.py` (lọc phiên khớp lệnh liên tục), `quality.py` (dòng không hợp lệ cho spread, khoảng trống, dữ liệu cũ, kiểm đơn vị giá).
- `src/analytics/validation.py` (kiểm chứng cảnh báo: chữ U, event study, độ nhạy ngưỡng; chỉ đọc, không đổi số ứng dụng) chạy bởi `scripts/validate_alerts.py`, kết quả ở `report/kiem-chung/`.
  Cách tách train/test theo thời gian và nhóm đối chứng không nhìn tương lai là quy ước của phần này: đổi ngưỡng ở `config.toml` thì chạy lại script.
- `src/model_config.py` đọc `config.toml`: nơi DUY NHẤT chứa hằng số và ngưỡng của phần phân tích; `src/status.py` chứa chuỗi trạng thái "Đủ dữ liệu" / "Chưa đủ dữ liệu";
  `src/data/special_days.py` đọc `data/special_days.csv` (ngày đặc biệt); `src/app/limits.py` dựng khối "Giới hạn cần nói thật" (số phiên đếm từ dữ liệu).
- `src/analytics/`: `baseline.py` (cảnh báo theo khung giờ), `lrs.py` (điểm rủi ro), `screener.py` (cổng thanh khoản, yếu tố, điểm bộ lọc, bối cảnh thị trường), `anomaly.py` (cách cũ).
- `src/app/`: `app.py` (cổng vào, điều hướng, công tắc Trực tiếp, danh sách theo dõi), `overview.py`, `screen_page.py`, `radar.py`, `stock.py` (4 trang), `symbol_dialog.py` (hộp thoại chi tiết mã có biểu đồ nến, mở từ bảng giá Tổng quan),
  `shared.py` (tải và phân tích dùng chung), `theme.py`, `charts.py`, `board.py`, `watchlist.py`, `flipgrid.py` (dữ liệu bản đồ nhiệt), `flipgrid_component.py` (vẽ).
- `scripts/`: `run_live.py` (một lệnh: ghi + dashboard), `record_rest.py`, `record_ws.py`, `record_ssi.py` (bộ ghi SSI dự phòng, cửa sổ riêng), `probe_market.py`, `export_data.py`, `check_boards.py`, `close_snapshot.py`,
  `backfill_extra.py`, `fetch_day_index.py`, `fetch_ssi_history.py` (lịch sử theo ngày từ SSI; `--check` đối chiếu với NEO), `probe_ssi.py` (thử SSI: `rest`, `stream`),
  `probe_ssi_channels.py`, `probe_ws_schema.py`, `compare_ws_rest.py`, `inspect_ws_lunch.py`, `generate_sample_data.py`, `restore_session.py` (dựng lại MỘT phiên vào
  market.db từ `data/raw/<ngày>/`, không gọi mạng; `--only trades` lấy lại riêng các lần khớp WebSocket).
- **Cùng một con số trên mọi trang:** tải và phân tích đi qua `shared.py`. Trang không tự tính lại số tài chính; logic tài chính ở `finance/` và `analytics/`.
- Bảng SQLite: `quotes` (sổ lệnh VN30 mỗi phút), `market_index`, `board` (ảnh chụp mới nhất mỗi ngày), `depth_market`, `futures`, `ws_quotes`,
  `ws_trades`, `ssi_daily`, `ssi_index_daily`, `ssi_quotes`.

## 3. Quy tắc dữ liệu (không được phá)
- **Không đoán, không điền, không nội suy.** Thiếu thì để trống hoặc hiện "–". Giá và số không có thì không thay bằng số gần đúng.
- **Múi giờ:** mọi dấu thời gian lưu và hiển thị theo UTC+7 (Asia/Ho_Chi_Minh).
- **Phiên dùng để phân tích:** chỉ phiên khớp lệnh liên tục (09:15 đến 11:30 và 13:00 đến 14:30); loại ATO, ATC, nghỉ trưa. Lần chụp ở trạng thái khóa trần/sàn
  (một bên sổ lệnh trống) không tính được spread: không vào xếp hạng nhưng được đếm và báo riêng, không bỏ im lặng.
- **Đơn vị:** giá lưu bằng đồng, hiển thị bằng nghìn đồng; khối lượng bằng cổ phiếu; số kiểu Việt (dấu chấm nghìn, dấu phẩy thập phân) qua `vn()` trong `theme.py`.
- **Nguồn:** NEO là nguồn chính; SSI là phụ. Ngày NEO không có lần chụp nào trong phiên liên tục mà SSI có sổ lệnh thì dùng SSI (lấy mẫu mỗi phút,
  cùng các phút với NEO) và **dán nhãn "SSI"**. Ngày có NEO luôn dùng NEO. Không trộn hai nguồn thành một số mà không có nhãn.
- **Mốc nền cần đủ phiên:** cảnh báo, LRS và tỷ lệ hấp thụ chỉ có khi mã có ít nhất `min_baseline_sessions` (hiện 5, config.toml) phiên trước cùng khung giờ; chưa đủ thì ghi
  "Chưa đủ dữ liệu" kèm lý do (không để trống, không coi là bình thường). Ở cổng của Bộ lọc, mã chưa có mốc nền là "Chưa đánh giá" (sau Đạt/Chú ý, trước Loại, không có điểm),
  không bao giờ mặc định "Đạt". Khung đầu 9:15-9:30 tách riêng. "Hai lần chụp liên tiếp" của đợt cảnh báo là hai lần chụp hợp lệ kề nhau cách không quá 90 giây.
- **Dòng không hợp lệ cho spread bị loại khỏi khung phân tích** (khóa trần/sàn, giá tốt nhất chạm trần/sàn, sổ chéo, giá lỗi) và báo riêng; lần chụp sau khoảng trống hoặc nghi
  dữ liệu cũ chỉ bị đánh cờ. Việc này làm ở lớp phân tích (`shared.load_source`), KHÔNG đổi `normalize_quotes` vì bộ ghi dùng hàm đó để quyết định lưu gì.
- **Ngày đặc biệt** (`data/special_days.csv`) vẫn được tính nhưng gắn cờ và không làm mốc nền (và nền ngưỡng LRS) cho ngày khác (`special_days.exclude_from_baseline`).
- **Phiên SSI không làm mốc cho phiên NEO** và không vào nền tính ngưỡng LRS, nên số của các phiên NEO không đổi khi thêm phiên SSI (đã so từng số).
  Phiên SSI không có giá khớp và tổng khối lượng nên các cột đó để trống, không tính tỷ lệ hấp thụ; trang Bộ lọc không dùng ngày SSI.
- **Giá đóng cửa SSI có dấu hiệu là giá điều chỉnh cổ tức:** không dùng giá SSI để tính lợi suất hay động lượng khi chưa xử lý.
- **Không nhìn trước:** cảnh báo và ngưỡng LRS tại một thời điểm chỉ dùng dữ liệu trước thời điểm đó. Cảnh báo so mỗi mã với chính nó, cùng khung 30 phút,
  tối đa 10 phiên trước (cần ít nhất 5 phiên và 20 lần chụp; ngưỡng LRS lấy tối đa 20 phiên gần nhất). Ngưỡng không đặt tùy ý: lấy từ phân vị của dữ liệu, tài liệu, hay lý luận có nêu nguồn.
- **Đối chiếu trước khi tin:** nguồn hoặc cách giải mã mới phải được đối chiếu với nguồn đã biết (ví dụ WebSocket với REST, SSI với NEO) và ghi tỷ lệ khớp.

## 4. Giao diện
**Nguyên tắc:** sáng, chuyên nghiệp, "sổ cái không màu": chữ và khung không màu; **một màu xanh cho dữ liệu chính; đỏ và hổ phách chỉ cho trạng thái/cảnh báo**.
Không thêm màu mới ngoài bảng dưới đây khi chưa hỏi.

| Vai trò | Màu |
| --- | --- |
| Chữ chính, nút chính | `#0a0a0a`, `#141414` |
| Chữ phụ, chú thích | `#6b6b6b`, mờ `#9a9a9a` |
| Nền trang, nền ô | `#f3f5f8`, `#ffffff` |
| Viền, lưới | `#e3e6ea`, `#eceef1` |
| Dữ liệu chính, liên kết | `#1d5fbf` |
| Cảnh báo, giảm | `#c4242a` |
| Chú ý (hổ phách) | `#92400e` |

- Cấu hình chủ đề đặt ở `.streamlit/config.toml` (phông Geist, cỡ chữ gốc 15, bo góc 8px, nút 6px). CSS chỉ dành cho phần tự vẽ, nằm ở `theme.py`
  (`inject_css`); thêm CSS cho một phần tử thì đặt `key=` và nhắm lớp `st-key-<key>`, không dựa vào lớp nội bộ của Streamlit.
- Bố cục: 4 trang, điều hướng ở đầu trang (`st.navigation(position="top")`): **Tổng quan** (`/tong-quan`), **Bộ lọc** (`/bo-loc`), **Radar** (`/radar`),
  **Chi tiết mã** (`/ma?ma=<mã>`). Các trang nối nhau qua `?ma=<mã>`. Thanh bên: thương hiệu, công tắc Trực tiếp, bộ lọc của trang, danh sách theo dõi.
- Rộng tối đa 1360px; ô nền trắng là container có `key` bắt đầu bằng `panel`; dải chỉ số 4 ô (`.kpis`) chia bằng vạch mảnh.
- Chữ, nút, nhãn: tiếng Việt, viết hoa đầu câu (không Title Case); biểu tượng dùng Material Symbols (`:material/...:`), hạn chế emoji.
- Biểu đồ: Plotly với `CHART_CONFIG` và `base_layout` trong `theme.py`; ẩn giờ nghỉ trưa bằng `hide_lunch`.
- **Màu bảng giá:** tím = trần, xanh dương = sàn, vàng = tham chiếu, xanh lá = tăng, đỏ = giảm; ô vừa đổi được tô nền theo màu mức giá.
- **Trạng thái dữ liệu phải minh bạch** ở mọi trang: thời điểm dữ liệu gần nhất, trạng thái kết nối (đang nhận / không có dữ liệu mới), nguồn dữ liệu
  (NEO, SSI). Thiếu dữ liệu hoặc lỗi thì hiện thông báo rõ (`st.error`/`st.info` hoặc `.notice`), ứng dụng không được treo hay hiện số gây hiểu nhầm.
  Thông báo nguồn SSI dùng `.notice` (nền trắng, vạch xanh bên trái).
- Mỗi trang có dòng "công cụ phân tích học thuật, không phải khuyến nghị đầu tư"; Radar và Bộ lọc có thêm khối "Phương pháp tính và giới hạn". Giao diện không còn lựa chọn dữ liệu mô phỏng (quyết định 25/11/2026): nguồn là NEO (chính) cộng SSI (bù ngày NEO thiếu); mã mô phỏng chỉ còn để kiểm thử.
- **Trạng thái và dễ đọc (25/11/2026):** nhãn trạng thái ở bảng (cổng Đạt/Chú ý/Chưa đánh giá/Loại, mức Cao/Chú ý) dùng huy hiệu `badge_style` trong `theme.py`: chữ theo màu của bảng màu, nền là bản nhạt của chính màu đó, KHÔNG thêm màu mới. Tăng giảm có mũi tên ▲ ▼ cạnh màu để người không phân biệt màu vẫn đọc được. Số dùng `tabular-nums` toàn trang. Lần tính nặng đầu tiên có khung chờ (`show_spinner`). Mỗi trang có mục thu gọn "Cách đọc trang này" (`how_to_read`). Ghi chú dữ liệu ở Radar gom thành dòng tóm tắt cộng mục thu gọn, chỉ số chính đứng trên cùng.
- Ứng dụng không lưu mật khẩu hay token (không ghi ra tệp, không in ra log); riêng hộp thoại nến gọi SSI chỉ đọc bằng khóa trong `.env`, token chỉ nằm trong bộ nhớ. Không có nút nào gửi lệnh.
- **Hộp thoại chi tiết mã (25/11/2026):** bấm mã ở mọi nhóm bảng giá Tổng quan -> liên kết `?xem=<mã>` (trang tải lại một lần, tham số được xóa ngay để đóng hộp thoại không mở lại). Nến SSI ghi rõ nguồn và chú thích giá ngày cũ có thể điều chỉnh cổ tức; nến chỉ để xem, không dùng để tính điểm. Nến trong phiên (1 giờ, 15 phút, 5 phút) có cho mọi mã từ SSI. Ngày nghỉ giao dịch (`market_holiday` ở `data/special_days.csv`) được trang Tổng quan giải thích khi không có dữ liệu.

## 5. Bản đồ nhiệt thẻ lật (Radar, chế độ Phát lại phiên)
- Dạng treemap: mỗi mã VN30 một ô, **diện tích theo độ sâu sổ lệnh trung vị cả phiên** (cố định khi phát để ô không nhảy chỗ); chỉ để chia diện tích, không phải chỉ số.
- **Màu theo điểm LRS** (liên tục): xanh nhạt = dễ giao dịch hơn thường lệ, xám = bình thường, cam rồi đỏ = khó hơn. Mốc thang lấy từ phân phối LRS của dữ liệu đã ghi
  (phân vị 5%, 50%, 95%, 99%). Viền cam đậm = mức Chú ý, viền đỏ đậm = mức Cao (do ngưỡng của Radar quyết định, không do thang màu); viền nét đứt và "–" = chưa đủ dữ liệu.
- Ô nào đổi điểm sang bước kế tiếp thì lật (quay trục ngang, đổi mặt ở giữa, độ trễ lệch nhau vài phần mười giây); ô không đổi đứng yên. Có công tắc **Hiệu ứng lật**.
  Không tự tắt theo `prefers-reduced-motion` (Windows tắt hiệu ứng động làm mất lật).
- Vẽ bằng component v2 `flipgrid_component.py` (đăng ký MỘT lần ở mức module) để ô không bị dựng lại mỗi nhịp; `flipgrid.py` chỉ tính dữ liệu, kiểm thử được.
- **Tốc độ phát** 1x, 2x, 4x = mỗi nhịp sang 1, 2, 4 lần chụp (mỗi lần chụp là 1 phút từ NEO REST); bảng và biểu đồ khác vẫn tính đủ mọi lần chụp đến thời điểm đang xem.

## 6. Kiểm thử
- `python -m pytest` bằng `.venv` của dự án; phải xanh trước mỗi commit. Số bài hiện có ghi ở `CLAUDE.md`.
- Hàm tính toán, làm sạch và quy tắc dữ liệu mới đều có test (dữ liệu nhỏ dựng sẵn); có thêm test trên dữ liệu thật (`test_real_*`).
- Đổi cách xử lý dữ liệu: so số trước và sau cho các phiên không liên quan, kết quả phải giống hệt.
- Giao diện: mở trang thật để kiểm tra (xem `AGENT.md`, mục 3); test xanh chưa đủ.

## 7. Quy ước mã
- Chú thích và thông báo cho người dùng bằng tiếng Việt; tên hàm và biến bằng tiếng Anh, ngắn gọn.
- Trang trong `src/app/` là script thẳng (không bọc thân trang trong hàm); logic dùng chung ở `shared.py` hoặc module riêng; dữ liệu nặng dùng `st.cache_data`.
- Không logic tài chính trong trang; không import `streamlit` trong `finance/`, `analytics/` hay `flipgrid.py` (để kiểm thử được).
- Tạo mới ít nhất có thể: ưu tiên sửa chỗ có sẵn, không thêm lớp trừu tượng khi chưa cần.
