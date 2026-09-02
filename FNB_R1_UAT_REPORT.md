# F&B R1 Exit Gate / UAT

Ngày kiểm tra: 2026-09-02  
Baseline: `9a9ab7a` (`Complete F&B final receipt integration R1D`)  
Kết luận hiện tại: **READY FOR FULL REPO GATE**

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

## Gate còn lại

Chạy full repo gate và chỉ commit nếu script kết thúc 100% với exit code 0:

```powershell
cd "C:\Users\nguye\OneDrive\Desktop\FSellingV2\F-Selling-main\F-Selling-main\F-Selling-master-main\python_app"
.\test-commit.ps1 "Complete F&B R1 exit gate"
```

