"""Cấu hình dùng chung: đường dẫn, biến môi trường, secret, logging ra file.

Mọi secret đều lấy từ biến môi trường (.env) - không hard-code trong source.
"""
from __future__ import annotations

import os
import secrets as _secrets
from datetime import datetime, timedelta, timezone
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


def _int_env(name: str, default: int) -> int:
    """Read an integer env value without making a typo crash startup."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        print(f"[WARN] {name}='{raw}' is not an integer. Using default {default}.")
        return default


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        print(f"[WARN] {name} must be positive. Using default {default}.")
        return default
    return value


def _bool_env_fail_closed(name: str) -> bool:
    """Only explicit enable values may open a sensitive capability."""
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}

# --- Đường dẫn ---
# Thư mục lưu ảnh upload - cấu hình qua env UPLOAD_DIR (trỏ vào volume khi deploy).
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR") or os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Dùng đường dẫn tuyệt đối để operator CLI/test có thể chạy từ maintenance cwd
# không chứa `.env`; web không được phụ thuộc current working directory.
STATIC_DIR: str = os.path.join(BASE_DIR, "static")
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

# --- Trợ lý: hiểu câu hỏi lạ bằng Gemini ---
# Chỉ là TẦNG DỰ PHÒNG. Bộ so khớp mẫu trong `assistant_service` xử lý mọi câu
# hỏi thường gặp ngay tại máy chủ: 0 đồng, không ra mạng, dưới 50ms. Gemini chỉ
# vào cuộc khi bộ đó chịu thua.
#
# P0A thêm kill switch riêng, mặc định OFF. Chỉ có key vẫn chưa đủ để mở kết
# nối ngoài; câu lạ tiếp tục nhận câu trả lời "chưa hiểu" như trước.
#
# Gemini KHÔNG nhận dữ liệu cửa hàng. Nó chỉ thấy câu hỏi và danh sách tên báo
# cáo, rồi trả về một tên. Mọi con số vẫn do service trong app tính.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY") or ""

# P0B pins one GA model reviewed against official docs on 2026-08-22. An env
# typo, alias or preview name must fail closed rather than silently drift.
GEMINI_MODEL_PINNED: str = "gemini-3.5-flash-lite"
GEMINI_MODEL: str = (os.getenv("GEMINI_MODEL") or GEMINI_MODEL_PINNED).strip()

# Trần lượt gọi mỗi shop mỗi ngày. Đây là trần cho các câu bộ so khớp nội bộ
# KHÔNG hiểu, không phải trần số câu hỏi - hỏi bình thường không tiêu lượt nào.
GEMINI_TRAN_MOI_NGAY: int = 20

# Chống giữ Enter: một người không gọi quá ngần này lượt trong một phút.
GEMINI_TRAN_MOI_PHUT: int = 5

# Trần thiệt hại khi Google treo, cùng lý do với SMTP_TIMEOUT_SECONDS: một
# request treo giữ một luồng threadpool, hết luồng là cả app đứng kể cả POS.
# KHÔNG tự thử lại khi hết giờ - retry là nhân đôi lượt gọi cho một người vốn
# đã đang chờ.
GEMINI_TIMEOUT_SECONDS: int = min(
    _positive_int_env("GEMINI_TIMEOUT_SECONDS", 6), 8
)

# Conservative reservation per call: the prompt is capped at 200 user chars
# plus a fixed allowlist and output is capped at 40 tokens. At the paid-tier
# prices reviewed on 2026-08-22 this deliberately over-reserves for FX/token
# variance. Failed calls are never refunded.
GEMINI_RESERVED_VND_PER_CALL: int = _positive_int_env(
    "GEMINI_RESERVED_VND_PER_CALL", 25
)
GEMINI_MONTHLY_CAP_VND: int = min(
    _positive_int_env("GEMINI_MONTHLY_CAP_VND", 350_000), 350_000
)
GEMINI_SHOP_MONTHLY_CAP_VND: int = min(
    _positive_int_env("GEMINI_SHOP_MONTHLY_CAP_VND", 15_000),
    GEMINI_MONTHLY_CAP_VND,
)
GEMINI_DEGRADE_PERCENT: int = max(
    1, min(_positive_int_env("GEMINI_DEGRADE_PERCENT", 80), 100)
)
GEMINI_CIRCUIT_FAILURE_THRESHOLD: int = _positive_int_env(
    "GEMINI_CIRCUIT_FAILURE_THRESHOLD", 3
)
GEMINI_CIRCUIT_COOLDOWN_SECONDS: int = _positive_int_env(
    "GEMINI_CIRCUIT_COOLDOWN_SECONDS", 60
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


# Hai capability ngoài mạng luôn OFF trừ khi operator bật tường minh. Credentials
# có thể còn trong môi trường deploy nhưng tự chúng không được phép mở kết nối.
GEMINI_ENABLED: bool = _bool_env_fail_closed("GEMINI_ENABLED")
TTS_SERVER_ENABLED: bool = _bool_env_fail_closed("TTS_SERVER_ENABLED")


# I10-B sales-QR rollout.  REPORT_ONLY is deliberately only a capability
# label here: the runtime still installs a disabled adapter.  Issuance becomes
# possible only when a caller injects the explicit deterministic mock/test
# runtime from ``qr_sales_service``; an environment variable alone can never
# select a provider or open network traffic.
QR_SALES_MODE_OFF = "OFF"
QR_SALES_MODE_REPORT_ONLY = "REPORT_ONLY"
QR_SALES_MODES = frozenset({QR_SALES_MODE_OFF, QR_SALES_MODE_REPORT_ONLY})


def _qr_sales_mode_from_env() -> str:
    """Parse the strict sales-QR mode allowlist and fail safe to OFF."""
    raw = (os.getenv("QR_SALES_MODE") or QR_SALES_MODE_OFF).strip().upper()
    if raw in QR_SALES_MODES:
        return raw
    print("[WARN] QR_SALES_MODE is invalid. Sales QR remains OFF.")
    return QR_SALES_MODE_OFF


QR_SALES_MODE: str = _qr_sales_mode_from_env()


# I10-C normalized bank-inbox rollout.  Like I10-B, REPORT_ONLY is only a
# capability label: the installed webhook runtime remains the disabled adapter.
# No environment value can install credentials, a provider adapter or network
# traffic; the deterministic adapter is reachable solely through the explicit
# test seam in ``qr_webhook_service``.
QR_WEBHOOK_MODE_OFF = "OFF"
QR_WEBHOOK_MODE_REPORT_ONLY = "REPORT_ONLY"
QR_WEBHOOK_MODES = frozenset(
    {QR_WEBHOOK_MODE_OFF, QR_WEBHOOK_MODE_REPORT_ONLY}
)


def _qr_webhook_mode_from_env() -> str:
    raw = (os.getenv("QR_WEBHOOK_MODE") or QR_WEBHOOK_MODE_OFF).strip().upper()
    if raw in QR_WEBHOOK_MODES:
        return raw
    print("[WARN] QR_WEBHOOK_MODE is invalid. QR webhook remains OFF.")
    return QR_WEBHOOK_MODE_OFF


QR_WEBHOOK_MODE: str = _qr_webhook_mode_from_env()


# Cấp credential bán offline là capability mới, nên mặc định TẮT. Cờ này chỉ
# chặn ISSUE; heartbeat/reclaim/revoke của credential đã phát hành vẫn chạy để
# máy mất hoặc shop vừa tắt rollout không làm mất đường cứu chứng từ đã có.
OFFLINE_LEASE_ISSUANCE_ENABLED: bool = _bool_env_fail_closed(
    "OFFLINE_LEASE_ISSUANCE_ENABLED"
)


# I09-H: contract rollout is deliberately a binary configuration, never a
# database switch.  The default remains Phase A so a newly deployed binary
# accepts the immutable v0 and v1 contracts.  Phase B has to carry both public
# UTC timestamps: the configured cutoff must itself be at least 14 days after
# the beginning of Phase A and must already have arrived.  Any typo is a boot
# failure, rather than an accidental financial cutoff with an unclear policy.
OFFLINE_CONTRACT_SUPPORTED_VERSIONS: tuple[int, int] = (0, 1)
OFFLINE_CONTRACT_PHASE_A = "PHASE_A"
OFFLINE_CONTRACT_PHASE_B = "PHASE_B"
OFFLINE_CONTRACT_POLICY_PHASE_A = "OFFLINE_CONTRACT_PHASE_A_V0_V1"
OFFLINE_CONTRACT_POLICY_PHASE_B = "OFFLINE_CONTRACT_PHASE_B_V1_MINIMUM"
_OFFLINE_CONTRACT_MIN_PHASE_A_SECONDS = 14 * 24 * 60 * 60


def _parse_utc_rollout_timestamp(name: str, raw: str) -> datetime:
    """Accept one explicit, timezone-aware UTC timestamp for the rollout."""
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a valid UTC ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise RuntimeError(f"{name} must include UTC timezone (+00:00 or Z)")
    return parsed.astimezone(timezone.utc)


def _canonical_utc_rollout_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _offline_contract_rollout_from_env() -> tuple[int, str, str | None, str | None, str]:
    raw_minimum = (os.getenv("OFFLINE_CONTRACT_MIN_VERSION") or "0").strip()
    if raw_minimum not in {"0", "1"}:
        raise RuntimeError("OFFLINE_CONTRACT_MIN_VERSION must be exactly 0 or 1")
    minimum = int(raw_minimum)
    phase_a_started_raw = os.getenv("OFFLINE_CONTRACT_PHASE_A_STARTED_AT")
    cutoff_raw = os.getenv("OFFLINE_CONTRACT_CUTOFF_AT")
    if minimum == 0:
        # Timestamp values with a Phase-A policy are harmless public history but
        # a lone/malformed value would make rollback semantics ambiguous.
        if bool(phase_a_started_raw) != bool(cutoff_raw):
            raise RuntimeError(
                "OFFLINE_CONTRACT_PHASE_A_STARTED_AT and OFFLINE_CONTRACT_CUTOFF_AT must be set together"
            )
        if phase_a_started_raw and cutoff_raw:
            started = _parse_utc_rollout_timestamp(
                "OFFLINE_CONTRACT_PHASE_A_STARTED_AT", phase_a_started_raw
            )
            cutoff = _parse_utc_rollout_timestamp("OFFLINE_CONTRACT_CUTOFF_AT", cutoff_raw)
            if cutoff < started + timedelta(seconds=_OFFLINE_CONTRACT_MIN_PHASE_A_SECONDS):
                raise RuntimeError("offline Phase A timestamp range is shorter than 14 days")
            return (minimum, OFFLINE_CONTRACT_PHASE_A, _canonical_utc_rollout_timestamp(started),
                    _canonical_utc_rollout_timestamp(cutoff), OFFLINE_CONTRACT_POLICY_PHASE_A)
        return (minimum, OFFLINE_CONTRACT_PHASE_A, None, None, OFFLINE_CONTRACT_POLICY_PHASE_A)

    if not phase_a_started_raw or not cutoff_raw:
        raise RuntimeError(
            "Phase B requires OFFLINE_CONTRACT_PHASE_A_STARTED_AT and OFFLINE_CONTRACT_CUTOFF_AT"
        )
    started = _parse_utc_rollout_timestamp("OFFLINE_CONTRACT_PHASE_A_STARTED_AT", phase_a_started_raw)
    cutoff = _parse_utc_rollout_timestamp("OFFLINE_CONTRACT_CUTOFF_AT", cutoff_raw)
    if cutoff < started + timedelta(seconds=_OFFLINE_CONTRACT_MIN_PHASE_A_SECONDS):
        raise RuntimeError("offline Phase A must last at least 14 days before Phase B")
    if cutoff > datetime.now(timezone.utc):
        raise RuntimeError("OFFLINE_CONTRACT_CUTOFF_AT must not be in the future for Phase B")
    return (minimum, OFFLINE_CONTRACT_PHASE_B, _canonical_utc_rollout_timestamp(started),
            _canonical_utc_rollout_timestamp(cutoff), OFFLINE_CONTRACT_POLICY_PHASE_B)


(
    OFFLINE_CONTRACT_MIN_VERSION,
    OFFLINE_CONTRACT_PHASE,
    OFFLINE_CONTRACT_PHASE_A_STARTED_AT,
    OFFLINE_CONTRACT_CUTOFF_AT,
    OFFLINE_CONTRACT_POLICY_CODE,
) = _offline_contract_rollout_from_env()


# Trần body webhook ORDER ở TẦNG ỨNG DỤNG. 256 KiB là default khởi đầu cho
# pilot, chưa phải kích thước đã được provider xác minh. App chỉ đọc/đếm stream
# sau khi secret hợp lệ; giá trị cấu hình lỗi quay về default dương này.
_ORDER_WEBHOOK_MAX_BODY_BYTES_DEFAULT = 256 * 1024
ORDER_WEBHOOK_MAX_BODY_BYTES: int = _positive_int_env(
    "ORDER_WEBHOOK_MAX_BODY_BYTES", _ORDER_WEBHOOK_MAX_BODY_BYTES_DEFAULT
)


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
