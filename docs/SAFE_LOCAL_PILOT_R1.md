# Safe Local Pilot R1

Mục tiêu: cho từng người thử F-Selling bằng dữ liệu giả qua một link ngrok tạm
thời. Không nhập dữ liệu cá nhân, khách hàng hoặc kinh doanh thật.

## Chuẩn bị trước mỗi người thử

1. Đóng F-Selling và cửa sổ ngrok đang chạy.
2. Chạy `reset_demo.bat`, gõ `RESET` và chờ thông báo thành công.
3. Chạy `run_ngrok.bat`; chỉ gửi link cùng tài khoản `demo` / `Demo@2026`.
4. Chờ trang `/api/health/ready` sẵn sàng; Gemini và TTS phải luôn OFF.

## Năm luồng cần thử

| # | Việc người thử làm | Đạt khi |
|---|---|---|
| 1 | Mở Đăng ký, dùng username giả duy nhất và email `@example.test`, rồi gửi form | Trang nói rõ cần xác minh email; không bị kẹt ở màn hình trắng |
| 2 | Đăng nhập `demo`, tạo một shop tạm với tên bắt đầu bằng `PILOT` | Shop mới xuất hiện và chỉ yêu cầu các trường tối thiểu |
| 3 | Trong shop tạm, thêm một sản phẩm giá `10000`, tồn kho `10` | Sản phẩm xuất hiện với đơn vị giá/số lượng rõ ràng |
| 4 | Mở POS, bán một sản phẩm và thanh toán tiền mặt | Có xác nhận hoàn tất; giỏ hàng sẵn sàng cho đơn tiếp theo |
| 5 | Hỏi Trợ lý “Hướng dẫn tôi bán hàng” và “Hôm nay bán được bao nhiêu?” | Trợ lý trả lời ngắn, mở đúng màn hình và không tự sửa dữ liệu |

Mỗi luồng chỉ ghi `PASS` hoặc `FAIL`, bước bị dừng và một ảnh chụp nếu cần.
Không ghi tên thật, số điện thoại, email thật hoặc dữ liệu cửa hàng.

## Khi có sự cố

| Trạng thái | Cách xử lý |
|---|---|
| Không thấy link ngrok | Chờ server READY; kiểm tra cửa sổ launcher và kết nối mạng |
| Link mở nhưng báo 502 | Chờ vài giây rồi tải lại; launcher chỉ mở tunnel sau health check |
| Launcher báo cổng 8000 đang được dùng | Dừng F-Selling đang chạy trên cổng đó rồi mở lại launcher |
| Reset báo database đang được dùng | Đóng mọi cửa sổ F-Selling/ngrok rồi chạy lại `reset_demo.bat` |
| Người trước để lại dữ liệu | Dừng launcher, reset demo, sau đó mới mời người tiếp theo |
| Email thử nghiệm không gửi | Chỉ ghi kết quả phần hướng dẫn xác minh; tiếp tục bốn luồng còn lại bằng tài khoản demo |

Mỗi lần reset tạo một file `*.pilot-backup-*.db` đã được kiểm chứng trước khi
thay database. Giữ backup gần nhất cho tới khi lượt thử kế tiếp hoàn tất.
