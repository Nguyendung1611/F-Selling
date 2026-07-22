"""Cấu hình chung cho test.

Nguyên tắc:
- Không bao giờ chạm vào DB thật: DB_PATH trỏ vào file tạm.
- Không gửi email thật: send_otp_email luôn bị thay bằng fake.
- Không gọi mạng: VietQR chỉ là chuỗi URL, webhook secret được monkeypatch.
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
os.environ["DB_PATH"] = str(_TMP / "test.db")
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["LOG_FILE"] = str(_TMP / "request_log.txt")
os.environ["SECRET_KEY"] = "test-secret-key-chi-dung-cho-test"
os.environ["ADMIN_INITIAL_PASSWORD"] = "AdminTest@2026"
os.environ["ALLOWED_ORIGINS"] = "http://testserver"
# Chặn mọi khả năng gửi mail thật
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from fselling.core import bootstrap  # noqa: E402
from fselling.core.database import SessionLocal  # noqa: E402
from fselling.main import create_app  # noqa: E402
from fselling.services import auth_service, email_service  # noqa: E402

SELLER_PASSWORD = "Seller@2026"
ADMIN_PASSWORD = os.environ["ADMIN_INITIAL_PASSWORD"]

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


def new_staff(client, owner_ctx: dict) -> tuple:
    """Chủ shop (owner_ctx) tạo một nhân viên cho shop của mình, rồi đăng nhập
    nhân viên đó. Trả về (username, token) của nhân viên."""
    username = _unique("staff")
    res = client.post(
        f"/api/staff/{owner_ctx['shop_id']}",
        json={"username": username, "password": STAFF_PASSWORD},
        headers=auth(owner_ctx["token"]),
    )
    assert res.status_code == 200, res.text
    token = login(client, username, STAFF_PASSWORD)
    return username, token
