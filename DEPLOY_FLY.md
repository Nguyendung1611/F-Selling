# Hướng dẫn deploy F-Selling lên Fly.io

> Lưu ý: Fly.io yêu cầu **thêm thẻ thanh toán để xác minh** (chống lạm dụng), nhưng
> sẽ **không tính phí** nếu bạn dùng ít và để máy tự tắt khi rảnh (đã cấu hình sẵn
> `min_machines_running = 0`). Nếu không muốn nhập thẻ, hãy dùng Render thay thế.

Tất cả lệnh dưới đây chạy **trong thư mục `python_app`** (nơi có `Dockerfile` và `fly.toml`).

## 1. Cài Fly CLI (flyctl)

Mở **PowerShell** và chạy:

```powershell
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

Đóng và mở lại PowerShell sau khi cài. Kiểm tra: `fly version`.

## 2. Đăng ký / đăng nhập

```powershell
fly auth signup   # hoặc: fly auth login
```

## 3. Đổi tên app

Mở `fly.toml`, đổi `app = "f-selling-dung"` thành tên **duy nhất** của bạn
(ví dụ `f-selling-abc123`). Đổi luôn dòng:

```
ALLOWED_ORIGINS = "https://<ten-app>.fly.dev"
```

## 4. Tạo app + volume lưu dữ liệu

```powershell
fly apps create <ten-app>
fly volumes create fselling_data --region sin --size 1 --app <ten-app>
```

(`--size 1` = 1GB, đủ cho SQLite + ảnh. Volume giữ dữ liệu qua các lần redeploy.)

## 5. Đặt secret (KHÔNG commit các giá trị này)

```powershell
fly secrets set --app <ten-app> ^
  SECRET_KEY=df40ce2d28f199d1f53723ae98397583e8203664b4c8bede0592615f4444ec32 ^
  ADMIN_INITIAL_PASSWORD=Admin@2026 ^
  PAYMENT_WEBHOOK_SECRET=4715cbac42a369478e2cbcb67169e52b97ada50538580311 ^
  SMTP_HOST=smtp.gmail.com ^
  SMTP_PORT=587 ^
  SMTP_USER=your_email@gmail.com ^
  SMTP_PASSWORD=your_new_gmail_app_password
```

- Nhớ **tạo Gmail App Password MỚI** (cái cũ trong `.env` đã bị lộ, nên thu hồi).
- Nếu không cần gửi email, bỏ 4 dòng SMTP — app vẫn chạy, chỉ in OTP ra log.

## 6. Deploy

```powershell
fly deploy --app <ten-app>
```

Lần đầu Fly build Docker image và khởi động. DB trống trên volume sẽ được tạo tự động,
và tài khoản `admin` được seed từ `ADMIN_INITIAL_PASSWORD`.

## 7. Mở web

```
https://<ten-app>.fly.dev
```

Đăng nhập: `admin` / `Admin@2026` → **đổi mật khẩu ngay** trong app.

## Lệnh hữu ích

```powershell
fly logs --app <ten-app>        # xem log
fly status --app <ten-app>      # trạng thái máy
fly secrets list --app <ten-app>
fly deploy --app <ten-app>      # deploy lại sau khi sửa code
```

## Ghi chú

- Dữ liệu (DB + ảnh) nằm ở `/data` trên volume `fselling_data`, không mất khi deploy lại.
- Muốn đổi mật khẩu admin trên server: `fly secrets set ADMIN_INITIAL_PASSWORD=...`
  chỉ có tác dụng khi DB **chưa** có admin. Nếu admin đã tồn tại, đổi mật khẩu bằng
  chức năng "Đổi mật khẩu" trong app, hoặc chạy `reset_admin.py` qua `fly ssh console`.
- Không upload file `.env`, `.db`, log lên server (đã chặn trong `.dockerignore`).
