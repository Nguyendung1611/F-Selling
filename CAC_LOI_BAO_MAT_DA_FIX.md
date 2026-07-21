# Các Lỗi Bảo Mật Đã Được Sửa — F-Selling

Tài liệu này liệt kê các lỗ hổng theo báo cáo `BAO_CAO_LOI_BAO_MAT_TIENG_VIET.md`
và cách đã khắc phục trong code.

## Bảng tổng hợp

| # | Lỗi | Mức độ | Trạng thái |
|---|---|---|---|
| 1 | JWT secret hardcode + token qua query string / URL | High | ✅ Đã sửa |
| 2 | Admin mặc định `admin / 123456` | Critical | ✅ Đã sửa |
| 3 | Đăng ký gửi `role=ADMIN` để tự lên admin | Critical | ✅ Đã sửa |
| 4 | Seller truy cập dữ liệu shop người khác (IDOR) | Critical | ✅ Đã sửa |
| 5 | Tạo đơn không cần đăng nhập + sửa giá từ client | Critical | ✅ Đã sửa |
| 6 | Webhook thanh toán fail-open (thiếu secret vẫn chạy) | Critical | ✅ Đã sửa |
| 7 | XSS do render dữ liệu người dùng bằng `innerHTML` | High | ✅ Đã sửa |
| 8 | Upload file không kiểm tra loại/kích thước/tên | Medium/High | ✅ Đã sửa |
| 9 | CORS mở toàn bộ (`*`) | Medium | ✅ Đã sửa |

---

## 1. JWT secret & token

- Bỏ secret hardcode `SECRET_KEY = "supersecretkey"`; giờ đọc từ biến môi trường
  `SECRET_KEY`, nếu chưa có thì sinh khóa ngẫu nhiên an toàn cho phiên chạy.
- `get_current_user` **không còn nhận token qua query string** — chỉ nhận qua
  header `Authorization: Bearer`. Tránh lộ token qua lịch sử trình duyệt / log / screenshot.
- Frontend tải Excel bằng `fetch` + header thay vì `?token=...` trên URL.
- **File:** `app.py`, `static/js/seller.js`, `static/js/api.js`

## 2. Admin mặc định `admin / 123456`

- Bỏ tạo admin với mật khẩu cố định `123456`.
- App tự tạo/đồng bộ admin theo biến `ADMIN_INITIAL_PASSWORD` (mật khẩu mạnh, ≥ 8 ký tự).
- Mật khẩu cũ `123456` không còn đăng nhập được.
- **File:** `app.py` (khối `lifespan`)

## 3. Tự đăng ký thành Admin

- Bỏ trường `role` khỏi dữ liệu đăng ký; API đăng ký công khai **luôn ép `role = "SELLER"`**,
  không tin `role` gửi từ client.
- **File:** `app.py` (schema `UserCreate`, hàm `register`)

## 4. Seller truy cập dữ liệu shop người khác (IDOR)

- Thêm hàm kiểm tra quyền `require_shop_access()`: chỉ chủ shop (hoặc ADMIN) mới được truy cập.
- Áp dụng cho: dashboard/seller, shops/stats, export/seller, orders/pay,
  products/status, xóa product, tạo/xóa voucher, categories, order pay...
- Truy cập shop không thuộc mình → **HTTP 403**.
- **File:** `app.py`

## 5. Tạo đơn giả & sửa giá

- Endpoint tạo đơn **bắt buộc đăng nhập** và kiểm tra quyền chủ shop.
- **Giá tính từ DB**, bỏ qua giá client gửi; kiểm tra số lượng > 0 và đủ tồn kho;
  dùng transaction khi trừ kho + tăng lượt voucher.
- Gửi `price=1` không còn làm tổng tiền sai.
- **File:** `app.py` (hàm `create_order`)

## 6. Webhook thanh toán fail-open

- Nếu chưa cấu hình `PAYMENT_WEBHOOK_SECRET`, webhook **trả 503** (fail-closed),
  không cho chuyển đơn sang PAID.
- So sánh secret bằng `compare_digest` (chống timing attack).
- **File:** `app.py` (hàm `order_webhook`)

## 7. XSS qua `innerHTML`

- Thêm hàm `escapeHtml()` và bọc mọi dữ liệu người dùng trước khi đưa vào `innerHTML`
  (tên shop, danh mục, sản phẩm, mã voucher, username, log...).
- Chuỗi như `<img src=x onerror=alert(1)>` giờ hiển thị như text, không chạy script.
- **File:** `static/js/api.js`, `pos.js`, `seller.js`, `admin.js`

## 8. Upload file

- Chỉ chấp nhận ảnh JPG/PNG/WEBP: kiểm tra `content_type`, đuôi file,
  kích thước tối đa 2MB, và **magic bytes** (nội dung thật sự là ảnh).
- Tên file tự sinh bằng **UUID** (chống path traversal, trùng tên).
- **File:** `app.py` (hàm `create_product`)

## 9. CORS

- Bỏ `allow_origins=["*"]`; giới hạn theo biến `ALLOWED_ORIGINS`, chỉ cho phép
  các method/header cần thiết.
- **File:** `app.py`

---

## Việc bạn cần tự làm

- **Thu hồi Gmail App Password cũ** (đã lộ trong `.env`) và tạo mật khẩu ứng dụng mới.
- Đặt các biến môi trường mạnh khi chạy thật: `SECRET_KEY`, `ADMIN_INITIAL_PASSWORD`,
  `PAYMENT_WEBHOOK_SECRET`, `ALLOWED_ORIGINS`.
- Không đưa `.env`, `.db`, log lên git hoặc gửi cho người khác.
