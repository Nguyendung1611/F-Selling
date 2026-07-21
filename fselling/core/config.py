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
                        os.environ[key] = val


load_dotenv()

# --- Đường dẫn ---
# Thư mục lưu ảnh upload - cấu hình qua env UPLOAD_DIR (trỏ vào volume khi deploy).
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR") or os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATIC_DIR: str = "static"  # giữ nguyên đường dẫn tương đối như code cũ
LOG_FILE: str = os.getenv("LOG_FILE") or os.path.join(BASE_DIR, "request_log.txt")

# --- JWT ---
# JWT secret: lấy từ biến môi trường. Nếu chưa cấu hình, sinh key ngẫu nhiên an toàn
# cho phiên chạy hiện tại (token sẽ mất hiệu lực sau khi restart - đây là hành vi an toàn,
# tránh dùng secret hardcode). Nên đặt SECRET_KEY trong biến môi trường để token bền vững.
SECRET_KEY: str = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    SECRET_KEY = _secrets.token_hex(32)
    print(
        "[WARN] SECRET_KEY chưa được cấu hình trong môi trường. "
        "Đang dùng key ngẫu nhiên tạm thời - token sẽ mất hiệu lực khi restart. "
        "Hãy đặt biến môi trường SECRET_KEY để bảo mật ổn định."
    )

ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

# --- OTP ---
OTP_EXPIRE_MINUTES: int = 5

# --- Giới hạn nghiệp vụ ---
MAX_SHOPS_PER_USER: int = 3

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
