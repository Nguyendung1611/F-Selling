# Hướng Dẫn Sử Dụng F-Selling

Ứng dụng quản lý bán hàng (POS) cho nhiều cửa hàng: quản lý sản phẩm, danh mục,
khuyến mãi, bán hàng, thống kê doanh thu, và trang quản trị (admin).

## 1. Yêu cầu

- Cài **Python 3.10 trở lên** (máy đang dùng Python 3.14 là được).
- Kết nối internet (để cài thư viện lần đầu và nếu dùng ngrok).

## 2. Chạy trên máy (local)

Vào thư mục `python_app`, nhấp đúp **`run.bat`**.

Lần đầu script sẽ tự tạo môi trường ảo và cài thư viện (mất vài phút). Khi thấy dòng:

```
Uvicorn running on http://127.0.0.1:8000
```

là server đã chạy. Mở trình duyệt vào: **http://127.0.0.1:8000**

Để **dừng** server: đóng cửa sổ terminal đó (hoặc nhấn `Ctrl + C`).

## 3. Chia sẻ ra internet (miễn phí, qua ngrok)

Nếu muốn người khác truy cập qua một đường link công khai, nhấp đúp **`run_ngrok.bat`**.

Lần đầu cần authtoken ngrok (miễn phí, không cần thẻ):

1. Đăng ký: https://dashboard.ngrok.com/signup
2. Lấy token: https://dashboard.ngrok.com/get-started/your-authtoken
3. Mở terminal chạy 1 lần: `ngrok config add-authtoken <token_của_bạn>`

Sau đó chạy lại `run_ngrok.bat`, cửa sổ ngrok sẽ hiện **LINK CÔNG KHAI** dạng
`https://xxxx.ngrok-free.app` — gửi link này cho người khác để truy cập.

## 4. Đăng nhập Admin

- Tên đăng nhập: `admin`
- Mật khẩu: xem dòng `ADMIN_INITIAL_PASSWORD` trong file `.env` (hiện tại là `Admin@2026`).

### Đổi mật khẩu admin

Cách 1 (khuyến nghị cho lúc setup): mở `.env`, sửa `ADMIN_INITIAL_PASSWORD=<mật khẩu mới>`
rồi khởi động lại server. App tự cập nhật, **không cần chạy script gì thêm**.

Cách 2: sau khi đã chốt mật khẩu, **xóa dòng `ADMIN_INITIAL_PASSWORD` khỏi `.env`**.
Từ đó app không tự đổi nữa, bạn quản lý mật khẩu bằng chức năng "Đổi mật khẩu" trong app.

> Lưu ý: khi còn dòng `ADMIN_INITIAL_PASSWORD` trong `.env`, nếu bạn đổi mật khẩu
> trong app thì lần khởi động sau sẽ bị ghi đè về giá trị trong `.env`.

## 5. Người bán (Seller)

- Vào trang chủ → **Đăng ký Người bán** để tạo tài khoản (cần xác minh email nếu có cấu hình SMTP).
- Đăng nhập → tạo **Cửa hàng** (tối đa 3), thêm **Danh mục**, **Sản phẩm**, **Khuyến mãi**.
- Mở **POS** để bán hàng: chọn sản phẩm, áp voucher, thanh toán (chuyển khoản QR hoặc tiền mặt).
- Xem **Dashboard**: doanh thu, số đơn, sản phẩm bán chạy, biểu đồ.

## 6. File cấu hình `.env`

| Biến | Ý nghĩa |
|---|---|
| `SECRET_KEY` | Khóa ký JWT. Bắt buộc, giữ bí mật. |
| `ADMIN_INITIAL_PASSWORD` | Mật khẩu admin (app tự đồng bộ khi khởi động). |
| `PAYMENT_WEBHOOK_SECRET` | Secret cho webhook thanh toán (thiếu thì webhook trả 503). |
| `ALLOWED_ORIGINS` | Domain được phép gọi API (CORS). |
| `SMTP_HOST/PORT/USER/PASSWORD` | Cấu hình gửi email OTP (tùy chọn). |

## 7. Deploy lên server (tùy chọn)

Nếu muốn chạy 24/7 trên máy chủ (không cần bật máy tính), xem file **`DEPLOY_FLY.md`**
(hướng dẫn deploy miễn phí lên Fly.io kèm lưu trữ dữ liệu bền).

## 8. Cấu trúc mã nguồn

Backend đã được tách thành package `fselling/` (routers / services / models / schemas).
Cách chạy **không đổi** (`run.bat`, `uvicorn app:app`, Docker, Fly.io).
Chi tiết kiến trúc và cách chạy test: xem **`KIEN_TRUC.md`**.

## 9. Lưu ý bảo mật quan trọng

- **Thu hồi Gmail App Password cũ** trong `.env` (đã từng bị lộ) và tạo cái mới.
- **Không** commit lên git / **không** gửi cho ai file `.env` và các file `.db`
  (chúng chứa mật khẩu và dữ liệu thật).
- Chi tiết các lỗi bảo mật đã được sửa: xem file **`CAC_LOI_BAO_MAT_DA_FIX.md`**.
