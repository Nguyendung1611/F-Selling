# F&B Menu Options R2 — thiết kế tối thiểu

Ngày: 2026-09-02  
Trạng thái: đã triển khai và qua focused QA ngày 2026-09-03

## 1. Kết quả audit

- Ghi chú món đã có đủ từ API, database, phiếu Bếp/Bar đến giao diện. Nhân viên
  được sửa số lượng và ghi chú khi món còn chưa gửi; sau khi gửi dữ liệu là bất
  biến. Không xây lại chức năng này.
- Hệ thống đã có biến thể sản phẩm (`variant_group`, `variant_name`) và POS tại
  quầy đã gom biến thể vào một ô. Màn hình F&B hiện chưa tái dùng cách trình bày
  đó nên size/loại bị trải thành nhiều món rời.
- Combo đúng nghĩa cần trừ tồn từng thành phần. Tạo combo chỉ để cộng tiền nhưng
  không có định mức nguyên liệu sẽ làm sai tồn kho, nên chưa đưa vào R2.

## 2. Mục tiêu R2

Giúp nhân viên quán chọn size/loại và ghi yêu cầu món nhanh, không thay đổi
contract tiền, tồn kho hoặc Bếp/Bar đã qua exit gate R1.

## 3. Luồng được duyệt mặc định

1. Món không có biến thể: chạm một lần để thêm như hiện tại.
2. Món có nhiều biến thể: lưới chỉ hiện một ô theo `variant_group`, kèm số loại.
3. Chạm ô nhóm mở hộp chọn size/loại; mỗi lựa chọn hiện tên, giá và trạm chế biến.
4. Chạm một lựa chọn thêm đúng SKU hiện có vào bill.
5. Dòng nháp tiếp tục có ô số lượng và ghi chú hiện hữu; ví dụ: `ít đá`,
   `không cay`, `không hành`.
6. Chỉ khi bấm `Gửi món` mới khóa giá, size/loại và ghi chú như R1.

## 4. Phạm vi code

- Chỉ sửa giao diện F&B, locale và test frontend liên quan.
- Tái dùng dữ liệu từ endpoint sản phẩm hiện tại; không thêm bảng, migration,
  dependency, API hoặc cấu hình quản trị mới.
- Tìm kiếm phải khớp cả tên nhóm lẫn tên biến thể.
- Nhóm có một biến thể vẫn mở hộp chọn để tên size không bị che; sản phẩm đơn
  không có `variant_group` vẫn thêm trực tiếp.
- Hộp chọn hỗ trợ bàn phím, trả focus về ô món khi đóng, nút chạm tối thiểu 44px,
  không tràn ở 320px và có trạng thái không còn biến thể khả dụng.

## 5. Topping và combo

- Topping R2: chủ quán có thể tạo sản phẩm thường như `Thêm trứng`, `Thêm phô
  mai`; chúng được tính tiền, trừ tồn và gửi đúng trạm ngay bằng luồng hiện có.
  Chưa gắn topping vào một món cha vì chưa có nhu cầu dữ liệu bắt buộc.
- Combo: hoãn tới R2B sau khi có đặc tả định mức/BOM, quy tắc thay món và hoàn
  kho thành phần. Không dùng một SKU combo giả vì sẽ làm sai tồn.

## 6. Gate nghiệm thu

- Sản phẩm đơn thêm bằng một chạm; nhóm biến thể không thêm nhầm SKU trước khi
  người dùng chọn.
- Tìm theo tên nhóm hoặc tên size đều mở đúng nhóm.
- SKU được chọn giữ đúng giá, trạm, tồn và tên đầy đủ qua gửi món, tách bill và
  hóa đơn.
- Ghi chú tiếp tục xuất hiện đúng ở phiếu Bếp/Bar và không sửa được sau gửi.
- Node controller/UI test, focused F&B tests, syntax check và browser QA 320px
  đều pass; Gemini/TTS runtime vẫn OFF.
