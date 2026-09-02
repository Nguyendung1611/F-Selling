# F&B Table Service R1D — Hóa đơn cuối và chốt ca

## Mục tiêu

Nối bill F&B đã thanh toán vào đúng năng lực POS hiện có, không tạo hệ thống
hóa đơn hay báo cáo ca thứ hai.

## Phạm vi tối thiểu

1. Bill `PAID`/`DEBT` có nút mở hóa đơn cuối trên POS; bill chuyển khoản còn
   `PAYMENT_PENDING` chưa được xuất hóa đơn cuối.
2. POS nhận `?receipt=<order_id>` và mở bản sao hóa đơn bằng dữ liệu server.
3. Chi tiết/lịch sử đơn có tên bàn và tên bill; tìm lịch sử được theo tên bàn
   hoặc tên bill; ảnh/in hóa đơn hiện đúng ngữ cảnh này.
4. Kiểm thử chứng minh tiền mặt F&B đi vào ledger và số tiền dự kiến kết ca
   hiện có. Không thay đổi công thức sổ ca.

## Không làm

- Không thêm bảng/migration, receipt token/public URL hay tích hợp Zalo OA.
- Không trộn doanh thu chuyển khoản/ghi nợ vào `CashShift`; đó không phải tiền
  trong két. Báo cáo kinh doanh đa phương thức sẽ là vòng riêng nếu cần.
- Không deploy, không bật billing/provider; Gemini và TTS tiếp tục OFF.

## Kiểm chứng

- Focused Python: lịch sử/chi tiết đơn F&B và ledger ca.
- Focused Node: nút hóa đơn cuối, metadata bàn/bill và query receipt.
- Syntax check Python/JavaScript; full gate do người dùng chạy trước commit.
