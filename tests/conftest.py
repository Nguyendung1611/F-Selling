"""Cấu hình chung cho test.

Nguyên tắc:
- Không bao giờ chạm vào DB thật: DB_PATH trỏ vào file tạm.
- Không gửi email thật: send_otp_email luôn bị thay bằng fake.
- Không gọi mạng: VietQR chỉ là chuỗi URL, webhook secret được monkeypatch, và
  `GEMINI_API_KEY` bị xóa nên trợ lý không bao giờ gọi ra Google thật.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List

import pytest

# --- Phải cấu hình môi trường TRƯỚC khi import package ---
_TMP = Path(tempfile.mkdtemp(prefix="fselling_test_"))


def pytest_configure(config):
    """Đặt thư mục tạm của `tmp_path` vào cùng chỗ với DB test.

    KHÔNG dùng chỗ mặc định và KHÔNG dùng thư mục cố định trong dự án - cả hai
    đều đã gây ra "TEST FAIL" GIẢ trên máy dev, tức là bộ test đỏ trong khi code
    không có lỗi gì, và `test-commit.ps1` từ chối commit:

      - Mặc định `%TEMP%\\pytest-of-<user>`: pytest tạo symlink `pytest-current`
        ở đó. Symlink hỏng thì bước dọn dẹp cuối phiên ném `PermissionError` và
        pytest thoát mã lỗi DÙ MỌI TEST ĐỀU PASS.
      - `.pytest-tmp` trong dự án (bản trước): thư mục đó đã dính hỏng ACL, đọc
        còn không được. Mọi test dùng `tmp_path` (`test_tts.py`,
        `test_liet_ke_don_treo.py`) lỗi `PermissionError` ngay từ bước setup.

    `tempfile.mkdtemp()` cho một thư mục MỚI, tên duy nhất, mỗi lần chạy: không
    có symlink để hỏng, không có thư mục cũ để kế thừa quyền hỏng. Đặt ở đây
    thay vì `addopts` của pytest.ini vì file ini không nội suy được biến môi
    trường, mà đường dẫn này phải do Python tính ra lúc chạy.

    Dùng thư mục con `pytest/`: pytest XÓA SẠCH basetemp lúc khởi động, trỏ
    thẳng vào `_TMP` là mất luôn DB test nằm cạnh.
    """
    config.option.basetemp = str(_TMP / "pytest")
os.environ["DB_PATH"] = str(_TMP / "test.db")
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["LOG_FILE"] = str(_TMP / "request_log.txt")
os.environ["SECRET_KEY"] = "test-secret-key-chi-dung-cho-test"
os.environ["ADMIN_INITIAL_PASSWORD"] = "AdminTest@2026"
os.environ["ALLOWED_ORIGINS"] = "http://testserver"
# Chặn mọi khả năng gửi mail thật
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
# Chặn mọi khả năng gọi Gemini thật. Máy dev có `GEMINI_API_KEY` trong `.env`
# là bộ test sẽ gọi ra Google thật: tiêu hạn mức miễn phí của chủ dự án mỗi lần
# chạy test, và đỏ ngẫu nhiên vào đúng hôm Google chậm hoặc đổi model.
# Test nào cần tầng dự phòng thì tự monkeypatch `gemini_service` (xem
# `tests/test_tro_ly_gemini.py`) - đó mới là cách kiểm nó.
os.environ["GEMINI_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from fselling.core import bootstrap  # noqa: E402
from fselling.core.database import SessionLocal  # noqa: E402
from fselling.main import create_app  # noqa: E402
from fselling.services import auth_service, email_service  # noqa: E402

SELLER_PASSWORD = "Seller@2026"
ADMIN_PASSWORD = os.environ["ADMIN_INITIAL_PASSWORD"]

# Các khóa đối soát được thêm an toàn vào GET order/detail/dashboard.
# Gom một chỗ để các test contract không lệch nhau khi backend mở rộng summary.
PAYMENT_SUMMARY_KEYS = {
    "bank_paid_amount",
    "cash_paid_amount",
    "received_amount",
    "remaining_amount",
    "overpaid_amount",
    "refunded_amount",
    "refund_due_amount",
    "refund_pending",
    "refund_completed_at",
    "refund_completed_by",
    "refund_method",
    "refund_note",
    "refund_reference",
    "reconciliation_reason",
    "reconciliation_pending",
    "invoice_issued",
}

sent_emails: List[Dict[str, str]] = []


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """Thay send_otp_email bằng fake - test không bao giờ gửi mail thật."""
    sent_emails.clear()

    def _fake_send(email_to: str, otp_code: str, subject: str = "") -> bool:
        sent_emails.append({"to": email_to, "code": otp_code, "subject": subject})
        return True

    monkeypatch.setattr(email_service, "send_otp_email", _fake_send)
    monkeypatch.setattr(auth_service.email_service, "send_otp_email", _fake_send)
    return sent_emails


@pytest.fixture(scope="session")
def app():
    """App test dùng lifespan rỗng (không chạy APScheduler nền)."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(_app):
        bootstrap.initialize()
        yield

    return create_app(lifespan_handler=_noop_lifespan)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------- Helpers ----------
def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def register_seller(client, username: str = None, password: str = SELLER_PASSWORD) -> str:
    """Đăng ký + xác minh sẵn một seller, trả về username."""
    from fselling import models

    username = username or _unique("seller")
    res = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": f"{username}@example.com"},
    )
    assert res.status_code == 200, res.text

    session = SessionLocal()
    try:
        user = session.query(models.User).filter(models.User.username == username).first()
        user.is_verified = True
        user.verification_code = None
        # Helper này giả lập một tài khoản ĐÃ LẬP TỪ TRƯỚC, không phải người vừa
        # bấm đăng ký xong. Giữ lại mốc phát mã của lúc register thì mọi test
        # xin mã ngay sau đó đều dính cooldown chống dội bom email (F3).
        user.verification_code_sent_at = None
        session.commit()
    finally:
        session.close()
    return username


def login(client, username: str, password: str = SELLER_PASSWORD) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_seller(client) -> tuple:
    """Trả về (username, token)."""
    username = register_seller(client)
    return username, login(client, username)


SHOP_PAYLOAD = {
    "name": "Shop Test",
    "business_address": "123 Đường Test",
    "tax_code": "0123456789",
    "phone": "0900000000",
    "email": "shop@example.com",
    "bank_account_no": "0123456789",
    "bank_account_name": "NGUYEN VAN TEST",
    "bank_code": "VCB",
}


def create_shop(client, token: str, name: str = None) -> int:
    payload = dict(SHOP_PAYLOAD)
    payload["name"] = name or _unique("Shop")
    res = client.post("/api/shops", json=payload, headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()["id"]


def create_category(client, token: str, shop_id: int, name: str = "Danh mục A") -> int:
    res = client.post(
        "/api/categories", params={"name": name, "shop_id": shop_id}, headers=auth(token)
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def create_product(
    client, token: str, shop_id: int, name: str, price: float, stock: int, category_id: int
) -> dict:
    res = client.post(
        "/api/products",
        params={"shop_id": shop_id},
        data={"name": name, "price": price, "stock": stock, "category_id": category_id},
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    return res.json()


def seller_with_shop(client) -> dict:
    """Seller + shop + category + 1 sản phẩm giá 100000, tồn 10."""
    username, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    product = create_product(client, token, shop_id, _unique("SP"), 100000, 10, cat_id)
    return {
        "username": username,
        "token": token,
        "shop_id": shop_id,
        "category_id": cat_id,
        "product": product,
    }


def admin_token(client) -> str:
    return login(client, "admin", ADMIN_PASSWORD)


STAFF_PASSWORD = "Nhanvien@2026"


def new_staff(client, owner_ctx: dict, staff_role: str = "MANAGER") -> tuple:
    """Chủ shop (owner_ctx) tạo một nhân viên cho shop của mình, rồi đăng nhập
    nhân viên đó. Trả về (username, token) của nhân viên."""
    username = _unique("staff")
    res = client.post(
        f"/api/staff/{owner_ctx['shop_id']}",
        json={
            "username": username,
            "password": STAFF_PASSWORD,
            "staff_role": staff_role,
        },
        headers=auth(owner_ctx["token"]),
    )
    assert res.status_code == 200, res.text
    token = login(client, username, STAFF_PASSWORD)
    return username, token
