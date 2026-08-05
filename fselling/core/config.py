"""Cấu hình dùng chung: đường dẫn, biến môi trường, secret, logging ra file.

Mọi secret đều lấy từ biến môi trường (.env) - không hard-code trong source.
"""
from __future__ import annotations

import os
import secrets as _secrets
from datetime import datetime
from typing import List

# BASE_DIR phải trỏ về thư mục `python_app` (nơi chứa app.py, static/, *.db)
# chứ không phải thư mục của file này, để giữ nguyên vị trí DB và request_log.txt.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_dotenv() -> None:
    """Đọc file .env ở thư mục làm việc hiện tại (giữ nguyên hành vi cũ)."""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key, val = parts[0].strip(), parts[1].strip()
                        if (val.startswith('"') and val.endswith('"')) or (
                            val.startswith("'") and val.endswith("'")
                        ):
                            val = val[1:-1]
                        # Explicit process/container environment must take precedence over
                        # local .env values (matching standard dotenv behavior).
                        os.environ.setdefault(key, val)


load_dotenv()

# --- Đường dẫn ---
# Thư mục lưu ảnh upload - cấu hình qua env UPLOAD_DIR (trỏ vào volume khi deploy).
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR") or os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATIC_DIR: str = "static"  # giữ nguyên đường dẫn tương đối như code cũ
LOG_FILE: str = os.getenv("LOG_FILE") or os.path.join(BASE_DIR, "request_log.txt")

# --- Đọc tiền bằng giọng nói ---
# Chỉ dùng khi máy người bán KHÔNG có sẵn giọng tiếng Việt. Chưa cấu hình thì
# endpoint /api/tts trả 503 và frontend tự lùi về giọng của thiết bị.
TTS_PROVIDER: str = (os.getenv("TTS_PROVIDER") or "").strip().lower()
TTS_API_KEY: str = os.getenv("TTS_API_KEY") or ""
TTS_AZURE_REGION: str = os.getenv("TTS_AZURE_REGION") or ""
TTS_VOICE: str = os.getenv("TTS_VOICE") or ""      # để trống = dùng giọng mặc định của nhà cung cấp
TTS_MAX_CHARS: int = 300                            # câu thông báo dài nhất cũng chỉ ~80 ký tự

# Đặt cạnh UPLOAD_DIR để tự nằm trên cùng ổ đĩa bền khi deploy (Fly mount /data).
TTS_CACHE_DIR: str = os.getenv("TTS_CACHE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(UPLOAD_DIR)), "tts_cache"
)

# --- JWT ---
# JWT secret: lấy từ biến môi trường. Nếu chưa cấu hình, sinh key ngẫu nhiên an toàn
# cho phiên chạy hiện tại (token sẽ mất hiệu lực sau khi restart - đây là hành vi an toàn,
# tránh dùng secret hardcode). Nên đặt SECRET_KEY trong biến môi trường để token bền vững.
SECRET_KEY: str = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    SECRET_KEY = _secrets.token_hex(32)
    print(
        "[WARN] SECRET_KEY is not configured. Using a temporary random key; "
        "tokens will become invalid after restart. Configure SECRET_KEY for stable sessions."
    )

ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

# --- OTP ---
OTP_EXPIRE_MINUTES: int = 5

# --- Giới hạn nghiệp vụ ---
MAX_SHOPS_PER_USER: int = 3


def _int_env(name: str, default: int) -> int:
    """Đọc số nguyên từ env; giá trị rác -> dùng mặc định thay vì crash lúc khởi động."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        print(f"[WARN] {name}='{raw}' is not an integer. Using default {default}.")
        return default


# Tự hủy đơn PENDING quá hạn và hoàn lại tồn kho sau bao nhiêu phút.
# 0 = TẮT (mặc định). Job này ghi lên dữ liệu thật nên phải bật có chủ ý:
# đặt ORDER_PENDING_TIMEOUT_MINUTES=30 trong .env để bật.
ORDER_PENDING_TIMEOUT_MINUTES: int = _int_env("ORDER_PENDING_TIMEOUT_MINUTES", 0)

# --- Chống dò mật khẩu và dò mã OTP ---
# Bộ đếm nằm trong DB chứ không phải trong bộ nhớ tiến trình: khởi động lại
# server là kẻ tấn công được reset bộ đếm, mà restart thì họ ép được (chỉ cần
# làm app lỗi). DB cũng là nơi duy nhất còn đúng khi chạy nhiều worker/máy.
LOGIN_MAX_ATTEMPTS: int = _int_env("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_LOCKOUT_MINUTES: int = _int_env("LOGIN_LOCKOUT_MINUTES", 15)

# Mã OTP chỉ có 6 chữ số = 1 triệu khả năng, script quét vài phút là ra. Chạm
# ngưỡng thì HỦY MÃ chứ không khóa tài khoản: khóa tài khoản theo email là mở
# đường cho kẻ xấu khóa tài khoản người khác chỉ bằng cách đoán bừa.
OTP_MAX_ATTEMPTS: int = _int_env("OTP_MAX_ATTEMPTS", 5)

# Khoảng cách tối thiểu giữa hai lần xin mã, chống dội bom email vào hộp thư
# nạn nhân và chống kéo dài vô hạn cửa sổ để dò mã.
OTP_RESEND_COOLDOWN_SECONDS: int = _int_env("OTP_RESEND_COOLDOWN_SECONDS", 60)

# --- SMTP ---
# `smtplib.SMTP(host, port)` KHÔNG có timeout mặc định: máy chủ mail treo là
# request treo vĩnh viễn, và mỗi request treo giữ một luồng trong threadpool của
# FastAPI. Hết luồng thì cả app đứng - kể cả POS đang bán hàng, dù POS chẳng
# liên quan gì tới email. Con số này là trần thiệt hại.
SMTP_TIMEOUT_SECONDS: int = _int_env("SMTP_TIMEOUT_SECONDS", 10)

# --- Sao lưu lên Cloudflare R2 ---
# Toàn bộ dữ liệu nằm trong MỘT file SQLite trên MỘT volume. Thiếu bất kỳ giá
# trị nào trong bốn cái đầu thì tính năng TẮT hẳn và endpoint trả 503 - không
# có chế độ "sao lưu một nửa". Xem `services/backup_service.py`.
R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID") or ""
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID") or ""
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY") or ""
R2_BUCKET: str = os.getenv("R2_BUCKET") or ""
R2_PREFIX: str = os.getenv("R2_PREFIX") or "backup"

# Secret riêng cho POST /api/cron/backup. KHÔNG dùng chung với
# PAYMENT_WEBHOOK_SECRET: hai cái này do hai bên ngoài khác nhau giữ (ngân hàng
# và dịch vụ cron), lộ một cái không được kéo theo cái kia.
BACKUP_CRON_SECRET: str = os.getenv("BACKUP_CRON_SECRET") or ""

# Trần thiệt hại khi R2 treo, cùng lý do với SMTP_TIMEOUT_SECONDS ở trên: một
# request giữ luồng threadpool vô hạn là cả app đứng, kể cả POS đang bán hàng.
BACKUP_TIMEOUT_SECONDS: int = _int_env("BACKUP_TIMEOUT_SECONDS", 60)

# --- Upload ---
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE: int = 2 * 1024 * 1024  # 2MB


def get_allowed_origins() -> List[str]:
    """CORS: giới hạn theo danh sách domain trong biến môi trường ALLOWED_ORIGINS
    (phân tách bằng dấu phẩy). Mặc định chỉ cho phép localhost khi phát triển."""
    origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return [o.strip() for o in origins_env.split(",") if o.strip()]


def log_to_file(msg: str) -> None:
    """Ghi log request ra file. Không bao giờ ghi password/OTP/JWT/secret vào đây."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError as e:
        print(f"Error logging to file: {e}")
