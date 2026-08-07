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
fly secrets set --app <ten-app> `
  SECRET_KEY="<dán giá trị SECRET_KEY trong file .env>" `
  ADMIN_INITIAL_PASSWORD="<dán giá trị ADMIN_INITIAL_PASSWORD trong file .env>" `
  PAYMENT_WEBHOOK_SECRET="<dán giá trị PAYMENT_WEBHOOK_SECRET trong file .env>" `
  SUBSCRIPTION_BANK_CODE="<mã ngân hàng nhận phí F-Selling>" `
  SUBSCRIPTION_BANK_ACCOUNT_NO="<số tài khoản nền tảng nhận phí Pro>" `
  SUBSCRIPTION_BANK_ACCOUNT_NAME="<tên chủ tài khoản nhận phí Pro>" `
  SUBSCRIPTION_WEBHOOK_SECRET="<secret riêng cho webhook tiền gói Pro>" `
  SMTP_HOST="smtp.gmail.com" `
  SMTP_PORT="587" `
  SMTP_USER="<email Gmail của bạn>" `
  SMTP_PASSWORD="<Gmail App Password mới>"
```

- Bảy dòng đầu chỉ là **chỗ trống hướng dẫn**. Mở file `.env` trên máy, sao chép
  đúng giá trị tương ứng rồi dán vào PowerShell; tuyệt đối không dán giá trị thật
  vào tài liệu, `fly.toml` hoặc bất kỳ file nào sẽ commit.
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

Đăng nhập: `admin` / giá trị `ADMIN_INITIAL_PASSWORD` trong `.env`.

## Lệnh hữu ích

```powershell
fly logs --app <ten-app>        # xem log
fly status --app <ten-app>      # trạng thái máy
fly secrets list --app <ten-app>
fly deploy --app <ten-app>      # deploy lại sau khi sửa code
```

## 8. Sao lưu database lên Cloudflare R2 (nên làm ngay)

Volume của Fly giữ dữ liệu qua các lần deploy, nhưng nó vẫn là **một chỗ duy
nhất**. Xóa nhầm volume, hỏng máy, hoặc gõ nhầm một lệnh là mất sạch sổ nợ,
lịch sử ca và giá vốn của mọi cửa hàng. Snapshot của Fly là lưới an toàn *của
Fly*, không phải của bạn.

R2 miễn phí 10GB và **không tính phí băng thông tải ra** — bản sao nén của DB
hiện tại chỉ vài chục KB, nên thực tế chi phí là 0đ.

### 8.1. Tạo bucket và khóa

1. Vào Cloudflare Dashboard → **R2** → **Create bucket**, đặt tên (ví dụ
   `fselling-backup`).
2. **R2** → **Manage R2 API Tokens** → **Create API token**.
   - Permission: **Object Read & Write**
   - Scope: chỉ đúng bucket vừa tạo — đừng cấp cho toàn tài khoản.
3. Ghi lại **Access Key ID**, **Secret Access Key** và **Account ID**
   (Account ID nằm ở trang tổng quan R2).

### 8.2. Đặt secret cho app

```powershell
fly secrets set --app <ten-app> ^
  R2_ACCOUNT_ID=<account-id> ^
  R2_ACCESS_KEY_ID=<access-key-id> ^
  R2_SECRET_ACCESS_KEY=<secret-access-key> ^
  R2_BUCKET=fselling-backup ^
  BACKUP_CRON_SECRET=<chuoi-ngau-nhien-dai>
```

Sinh `BACKUP_CRON_SECRET` ngẫu nhiên:

```powershell
.\.venv\Scripts\python.exe -c "import secrets;print(secrets.token_hex(24))"
```

Thiếu bất kỳ biến `R2_*` nào thì tính năng **tắt hẳn** và endpoint trả 503 —
không có chế độ chạy nửa vời.

### 8.3. Đặt hạn lưu (thay cho code xóa bản cũ)

Cloudflare Dashboard → bucket → **Settings** → **Object lifecycle rules** →
thêm rule xóa object sau **30 ngày**, áp cho tiền tố `backup/`.

Cố ý làm ở đây chứ không viết code xóa: code xóa dữ liệu là loại code đắt nhất
khi viết sai, mà lợi ích thì đúng bằng một ô cấu hình bấm một lần.

### 8.4. Hẹn giờ chạy hằng đêm

`min_machines_running = 0` nghĩa là máy **tự tắt khi rảnh**, nên APScheduler
trong app không chạy được job ban đêm — lúc đó chẳng ai truy cập để giữ máy
thức. Đồng hồ phải nằm ngoài.

Dùng [cron-job.org](https://cron-job.org) (miễn phí):

| Ô | Điền |
|---|---|
| URL | `https://<ten-app>.fly.dev/api/cron/backup` |
| Method | `POST` |
| Header | `X-Cron-Secret: <BACKUP_CRON_SECRET>` |
| Lịch | 1 lần/ngày, giờ thấp điểm (ví dụ 03:00) |

Bật thông báo email khi request lỗi. Endpoint **cố ý trả 500 khi sao lưu
hỏng** (khác webhook ngân hàng luôn trả 200) — nhờ vậy trang cron báo động
được. Đó là hệ thống giám sát sao lưu của bạn, miễn phí.

### 8.5. Kiểm thật MỘT lần, ngay sau khi cắm khóa

Bộ test dùng mạng giả nên nó không chứng minh được R2 chấp nhận chữ ký. Chỉ một
lần chạy thật mới trả lời được:

```powershell
.\.venv\Scripts\python.exe scripts\backup_thu.py
```

Hoặc gọi thẳng endpoint trên server:

```powershell
curl -X POST -H "X-Cron-Secret: <secret>" https://<ten-app>.fly.dev/api/cron/backup
```

Rồi **tải file về, giải nén, mở thử một lần**. Một bản sao chưa từng phục hồi
thử thì chưa phải bản sao.

### 8.6. Phục hồi khi có sự cố

```powershell
# 1. Tải file .db.gz từ Cloudflare Dashboard > R2 > bucket

# 2. Giải nén
.\.venv\Scripts\python.exe -c "import gzip,shutil;shutil.copyfileobj(gzip.open(r'fselling-20260805-030000.db.gz','rb'),open(r'phuc_hoi.db','wb'))"

# 3. Kiểm tra file lành lặn TRƯỚC khi dùng
.\.venv\Scripts\python.exe -c "import sqlite3;print(sqlite3.connect(r'phuc_hoi.db').execute('PRAGMA integrity_check').fetchone()[0])"
```

Kết quả phải in ra `ok`. Sau đó đẩy lên volume:

```powershell
fly machine stop --app <ten-app>          # PHẢI dừng trước
fly ssh sftp shell --app <ten-app>
# trong shell: put phuc_hoi.db /data/fselling_v4.db
fly machine start --app <ten-app>
```

> **Dừng máy trước khi ghi đè.** Chép đè file DB trong lúc app đang chạy là cách
> chắc chắn nhất để hỏng cả bản đang có lẫn bản vừa phục hồi.

## Ghi chú

- Dữ liệu (DB + ảnh) nằm ở `/data` trên volume `fselling_data`, không mất khi deploy lại.
- Sao lưu chỉ gồm **database**, không gồm ảnh trong `uploads/`: ảnh nặng hơn
  nhiều lần và chụp lại được, sổ nợ thì không.
- Muốn đổi mật khẩu admin trên server: đặt giá trị mới bằng
  `fly secrets set --app <ten-app> ADMIN_INITIAL_PASSWORD="<mật khẩu mới>"`.
  App sẽ đồng bộ cả tài khoản admin đã tồn tại ở lần khởi động kế tiếp. Khi đã
  đăng nhập ổn định và muốn tự đổi trong app, gỡ biến này khỏi secret của server
  để lần khởi động sau không ghi đè mật khẩu bạn vừa đổi.
- Không upload file `.env`, `.db`, log lên server (đã chặn trong `.dockerignore`).
