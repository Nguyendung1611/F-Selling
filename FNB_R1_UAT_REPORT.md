# F&B R1 Exit Gate / UAT

Ngày kiểm tra: 2026-09-02  
Baseline: `0cb1d67` (`Complete F&B R1 exit gate`)
Kết luận hiện tại: **PASS**

## Kết quả chính

- Không còn lỗi P0/P1 đã biết trong phạm vi F&B R1.
- Checkout F&B đã tái sử dụng đúng contract POS bán lẻ cho voucher và đổi điểm:
  giảm tay + phụ thu + voucher + điểm được phân bổ bảo toàn tổng VND; retry
  không tăng lượt voucher, trừ điểm hoặc tạo Order lần hai.
- Khi polling phục hồi sau lỗi kết nối, thông báo lỗi cũ được xóa; dữ liệu gần
  nhất vẫn được giữ trong lúc server không truy cập được.
- Gemini và TTS runtime vẫn OFF; không deploy, không bật billing/provider.

## Bằng chứng tự động

- 58 test F&B R1A-R1D và migration: PASS.
- 94 test voucher, loyalty, receipt, shift và các lỗi cuối: PASS.
- 2 Node controller harness (`fnb-r1a`, `fnb-station-r1b`): PASS.
- JavaScript syntax và `git diff --check`: PASS (chỉ có cảnh báo line ending
  LF/CRLF hiện hữu trên Windows).

Các test khóa rủi ro tiền/tồn/quyền nằm tại:

- `tests/test_fnb_r1a_setup.py`
- `tests/test_fnb_r1a_sessions.py`
- `tests/test_fnb_r1b_send.py`
- `tests/test_fnb_r1b_cancel.py`
- `tests/test_fnb_r1c_checks.py`
- `tests/test_fnb_r1c_checkout.py`
- `tests/js/fnb-r1a.test.js`
- `tests/js/fnb-station-r1b.test.js`

## Browser resilience QA

- 320px: không tràn ngang (`scrollWidth = clientWidth = 305`); dialog, form,
  voucher và điểm đều nằm trong viewport; input 16px, CTA thanh toán 44px.
- Đóng dialog trả focus về nút `Tính tiền`.
- Dừng server: giữ sơ đồ gần nhất và báo `Chưa cập nhật được`.
- Khởi động lại server: polling hội tụ, lỗi cũ được xóa, nút thử lại ẩn.
- Console: không có lỗi.
- CSS có nhánh `prefers-reduced-motion: reduce`.

## Dữ liệu demo local

- 2 khu vực, 10 bàn.
- Menu có KITCHEN, BAR và DIRECT.
- Hai tài khoản phục vụ, một Bếp, một Bar, một quản lý có PIN; tài khoản thu
  ngân demo cũ vẫn được giữ.
- Chỉ dùng dữ liệu giả. Không ghi dữ liệu khách thật.

## P2 không chặn R1

- Nếu riêng server dừng nhưng hệ điều hành vẫn báo đang online, form thanh toán
  đang mở chỉ báo lỗi sau khi người dùng bấm; request fail an toàn và không ghi
  dữ liệu. Chỉ nâng cấp khi cần chỉ báo trạng thái server riêng theo thời gian
  thực.
- In-app browser không điều khiển được mức zoom trình duyệt 200% một cách đáng
  tin cậy. Kiểm tra 320px (khắt khe hơn về chiều ngang) đã pass; nên kiểm tra
  thủ công Ctrl+`+` trước deploy.

## Manual UAT - ca hoàn chỉnh

- Dùng ca local #2 đang mở; không tạo hoặc kết ca đang được dùng.
- Bàn 02 gọi ba món đại diện KITCHEN/BAR/DIRECT, tổng 153.000đ; gửi món,
  Bếp và Bar nhận làm rồi hoàn tất; hàng đợi trở về trống.
- Tách thành Bill chính 68.000đ và `Khách 2` 85.000đ; thanh toán tiền mặt độc
  lập, tạo order #96 và #97 trạng thái `PAID`.
- Hai hóa đơn cuối giữ đúng bàn, tên bill, món và tổng tiền; Bàn 02 trở về
  `Trống`; tồn ba món giảm đúng mỗi món một đơn vị.
- Ledger ca #2 nhận đúng hai `CASH_TOPUP` tổng 153.000đ. Tiền theo sổ là
  1.208.000đ = đầu ca 1.000.000đ + đơn cũ #95 55.000đ + UAT 153.000đ.
- Console F&B, hóa đơn và POS không có warning/error.
