# Nhật ký xác minh và hoàn thiện F-Selling

Ngày thực hiện: 2026-07-21  
Môi trường chính: Windows, Python 3.14.5, Docker Desktop Linux engine 29.6.1

## 1. Bảo vệ dữ liệu và tạo mốc Git

- Kiểm tra project chưa có Git repository.
- Bổ sung `.gitignore` trước khi stage để loại trừ `.env`, `.venv/`, `*.db`,
  `request_log.txt`, cache Python/pytest và ảnh upload runtime.
- Kiểm tra danh sách file stage; không có secret, database, log hoặc virtualenv.
- Khởi tạo nhánh `main` và tạo commit mốc refactor:
  `15fcf18 refactor backend into modular monolith`.
- Git identity chỉ đặt trong repository: `Codex <codex@local>`; không thay cấu hình Git global.

## 2. Kiểm thử backend hiện có

Các lệnh đã chạy trên `.venv` Windows:

```text
.venv\Scripts\python.exe -m pytest -q --tb=short
.venv\Scripts\python.exe -m compileall -q app.py fselling tests
.venv\Scripts\python.exe -m pip check
```

Kết quả cuối:

- 85/85 test pass.
- `compileall` pass.
- `pip check`: không có dependency hỏng.
- `request_log.txt` giữ nguyên 1.105.800 byte trước và sau test.
- Test sử dụng database, upload directory và log file tạm.

## 3. Lỗi runtime phát hiện và đã sửa

### Console Windows làm ứng dụng không khởi động

Khi stdout dùng CP1252, thông báo bootstrap bằng tiếng Việt gây
`UnicodeEncodeError` và Uvicorn dừng lúc startup. Các thông báo console bootstrap,
cảnh báo secret và script cleanup đã được đổi sang ASCII. Nội dung giao diện và API
không thay đổi.

### `.env` ghi đè biến môi trường hệ thống

Hàm `load_dotenv()` cũ gán trực tiếp vào `os.environ`, khiến secret hoặc cấu hình do
Docker/Fly/test truyền vào bị `.env` local ghi đè. Đã đổi sang `os.environ.setdefault()`:

- Biến môi trường của process/container có độ ưu tiên cao nhất.
- `.env` chỉ cung cấp giá trị mặc định khi biến chưa tồn tại.
- Bổ sung test hồi quy cho `SECRET_KEY`, `ADMIN_INITIAL_PASSWORD` và `LOG_FILE`.

## 4. End-to-end qua Uvicorn thật

Uvicorn được chạy trên cổng tạm với database/upload/log tạm, không sử dụng dữ liệu thật.
Luồng sau đã chạy thành công qua HTTP thật:

- Tải 8 trang/tài nguyên: trang chủ, đăng ký, xác minh, seller, POS, admin, JS và CSS.
- Đăng ký seller, lấy OTP từ database tạm, xác minh email và đăng nhập.
- Tạo shop, danh mục và sản phẩm.
- Tạo và áp voucher phần trăm.
- Tạo đơn với giá client giả; server vẫn tính giá từ database.
- Sinh URL VietQR, kiểm tra trạng thái PENDING, xác nhận thanh toán thành PAID.
- Kiểm tra doanh thu seller và xuất Excel.
- Đăng nhập admin, đọc dashboard/log và xuất Excel.
- Đăng nhập seller lần hai và xác nhận token phiên cũ bị từ chối.

Kết quả: `E2E_HTTP_PASS` cho toàn bộ các nhóm trên.

Hai thư mục dữ liệu E2E tạm và các tiến trình Uvicorn tạm đã được dọn sau khi kiểm tra.

## 5. Khóa dependency

Chỉ pin dependency trực tiếp, không chép toàn bộ `pip freeze`:

- Production: FastAPI, Uvicorn, SQLAlchemy, OpenPyXL, PyJWT, bcrypt, passlib,
  Pydantic, email-validator, python-multipart, APScheduler và pyngrok.
- Development: pytest và httpx.

Các phiên bản trong `requirements.txt` và `requirements-dev.txt` khớp đúng môi trường
đã chạy test và image Docker đã build thành công.

## 6. Docker

Đã chạy:

```text
docker build --tag fselling:refactor-verified .
```

Kết quả:

- Build thành công từ `python:3.12-slim` với dependency được cài mới hoàn toàn.
- Image: `fselling:refactor-verified`.
- Image ID: `sha256:766173511b83024879f48854152f709c0520e4a9f1bc7e026f99f6c16886d029`.
- Chạy container với volume `/data` tạm: GET `/` trả HTTP 200.
- Login admin và GET `/api/dashboard/admin` thành công.
- Xác nhận image không chứa `/app/.env`, database hoặc `request_log.txt`.
- Container và volume smoke-test đã được xóa; image được giữ lại để kiểm tra/chạy tiếp.

## 7. Các file dữ liệu thật

Không sửa nội dung hoặc mtime của:

- `.env`.
- `fselling.db`, `fselling_v2.db`, `fselling_v3.db`, `fselling_v4.db`.
- `request_log.txt`.

Không push repository và không deploy Fly.io.

## 8. Hạng mục không thể tự động hoàn thành

### Kiểm thử bằng thao tác bấm trình duyệt

Plugin điều khiển Chrome thiếu entrypoint được yêu cầu; plugin trình duyệt trong Codex
cũng không khởi tạo được và báo lỗi không ghi được runtime assets. Không dùng công cụ
điều khiển không được hỗ trợ để tránh thao tác sai. Phần này được bù bằng kiểm thử HTTP
end-to-end và kiểm tra toàn bộ trang/tài nguyên ở mục 4.

### Gmail App Password

Không thể mở trang Google Account trong phiên đăng nhập hiện có do cùng lỗi điều khiển
trình duyệt. Vì vậy chưa thu hồi/tạo Gmail App Password và không thay đổi
`SMTP_PASSWORD` trong `.env`. Không có secret nào được đọc ra log hoặc đưa vào Git/Docker.

Đây là hạng mục duy nhất còn cần thực hiện sau khi chức năng điều khiển trình duyệt hoạt
động trở lại hoặc người dùng thao tác trực tiếp trong Google Account.
