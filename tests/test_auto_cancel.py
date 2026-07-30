"""A2: tự động hủy đơn PENDING quá hạn và hoàn tồn kho.

Job dùng chung cơ chế với hủy thủ công (A1c/A1d), nên mọi bảo đảm về
"không hoàn kho hai lần" vẫn giữ nguyên.
"""
from datetime import datetime, timedelta

import pytest
from conftest import auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.services.maintenance_service import cancel_expired_pending_orders
from fselling.services.order_service import (
    STATUS_CANCELLED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_UNRECONCILED,
    read_status,
)

SECRET = "webhook-secret-a2"


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _tao_don(client, quantity=3, payment_method="transfer"):
    ctx = seller_with_shop(client)  # SP giá 100000, tồn 10
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {"product_name": ctx["product"]["name"], "price": 100000, "quantity": quantity}
            ],
            "payment_method": payment_method,
        },
        headers=auth(ctx["token"]),
    ).json()
    return ctx, order["order_id"]


def _lam_cu_don(order_id, phut_truoc):
    """Đẩy created_at về quá khứ để giả lập đơn đã quá hạn."""
    session = SessionLocal()
    try:
        order = session.query(models.Order).filter(models.Order.id == order_id).first()
        order.created_at = datetime.utcnow() - timedelta(minutes=phut_truoc)
        session.commit()
    finally:
        session.close()


def _trang_thai(order_id):
    session = SessionLocal()
    try:
        return read_status(session, order_id)
    finally:
        session.close()


def _ton_kho(product_id):
    session = SessionLocal()
    try:
        return session.query(models.Product).filter(models.Product.id == product_id).first().stock
    finally:
        session.close()


# ---------- Mặc định TẮT ----------
def test_mac_dinh_tat_khong_dung_vao_du_lieu(client):
    ctx, order_id = _tao_don(client, quantity=3)
    _lam_cu_don(order_id, 999)

    # Không truyền tham số -> lấy ORDER_PENDING_TIMEOUT_MINUTES (mặc định 0 = tắt)
    assert cancel_expired_pending_orders() == 0
    assert _trang_thai(order_id) == STATUS_PENDING
    assert _ton_kho(ctx["product"]["id"]) == 7


def test_timeout_bang_khong_hoac_am_deu_la_tat(client):
    _, order_id = _tao_don(client, quantity=1)
    _lam_cu_don(order_id, 999)

    assert cancel_expired_pending_orders(timeout_minutes=0) == 0
    assert cancel_expired_pending_orders(timeout_minutes=-5) == 0
    assert _trang_thai(order_id) == STATUS_PENDING


# ---------- Khi được bật ----------
def test_huy_don_qua_han_va_hoan_kho(client):
    ctx, order_id = _tao_don(client, quantity=3)
    assert _ton_kho(ctx["product"]["id"]) == 7
    _lam_cu_don(order_id, 60)

    da_huy = cancel_expired_pending_orders(timeout_minutes=30)

    assert da_huy >= 1
    assert _trang_thai(order_id) == STATUS_CANCELLED
    assert _ton_kho(ctx["product"]["id"]) == 10


def test_khong_dung_vao_don_chua_qua_han(client):
    ctx, order_id = _tao_don(client, quantity=2)
    _lam_cu_don(order_id, 5)  # mới 5 phút

    cancel_expired_pending_orders(timeout_minutes=30)

    assert _trang_thai(order_id) == STATUS_PENDING
    assert _ton_kho(ctx["product"]["id"]) == 8


def test_khong_dung_vao_don_da_thanh_toan(client):
    ctx, order_id = _tao_don(client, quantity=4, payment_method="cash")
    client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    _lam_cu_don(order_id, 999)
    ton_sau_ban = _ton_kho(ctx["product"]["id"])

    cancel_expired_pending_orders(timeout_minutes=30)

    assert _trang_thai(order_id) == STATUS_PAID
    assert _ton_kho(ctx["product"]["id"]) == ton_sau_ban, "Đơn đã bán không được hoàn kho"


def test_khong_dung_vao_don_da_huy_truoc_do(client):
    ctx, order_id = _tao_don(client, quantity=3)
    client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))
    assert _ton_kho(ctx["product"]["id"]) == 10
    _lam_cu_don(order_id, 999)

    cancel_expired_pending_orders(timeout_minutes=30)

    assert _trang_thai(order_id) == STATUS_CANCELLED
    assert _ton_kho(ctx["product"]["id"]) == 10, "Không hoàn kho lần hai"


def test_khong_dung_vao_don_can_doi_soat(client, webhook_secret):
    ctx, order_id = _tao_don(client, quantity=3)
    client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))
    client.post(
        "/api/orders/webhook",
        json={"order_id": order_id, "amount": 300000},   # 3 x 100000
        headers={"X-Webhook-Secret": SECRET},
    )
    assert _trang_thai(order_id) == STATUS_UNRECONCILED
    _lam_cu_don(order_id, 999)
    ton_hien_tai = _ton_kho(ctx["product"]["id"])

    cancel_expired_pending_orders(timeout_minutes=30)

    assert _trang_thai(order_id) == STATUS_UNRECONCILED
    assert _ton_kho(ctx["product"]["id"]) == ton_hien_tai


def test_chay_lai_khong_hoan_kho_them_lan_nua(client):
    ctx, order_id = _tao_don(client, quantity=5)
    _lam_cu_don(order_id, 60)

    cancel_expired_pending_orders(timeout_minutes=30)
    assert _ton_kho(ctx["product"]["id"]) == 10

    cancel_expired_pending_orders(timeout_minutes=30)
    assert _ton_kho(ctx["product"]["id"]) == 10, "Tồn kho không được vượt quá ban đầu"
    assert _trang_thai(order_id) == STATUS_CANCELLED


def test_ghi_log_he_thong_khi_tu_dong_huy(client):
    _, order_id = _tao_don(client, quantity=1)
    _lam_cu_don(order_id, 60)

    cancel_expired_pending_orders(timeout_minutes=30)

    session = SessionLocal()
    try:
        log = (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == "AUTO_CANCEL_ORDER",
                models.SystemLog.details.like(f"%#{order_id} %"),
            )
            .first()
        )
        assert log is not None, "Phải ghi lại việc hệ thống tự hủy đơn"
        assert log.user_id is None, "Hành động của hệ thống, không gắn với người dùng"
        assert "quá hạn" in log.details
    finally:
        session.close()


def test_huy_nhieu_don_qua_han_cung_luc(client):
    ctx1, order1 = _tao_don(client, quantity=2)
    ctx2, order2 = _tao_don(client, quantity=3)
    _lam_cu_don(order1, 60)
    _lam_cu_don(order2, 60)

    cancel_expired_pending_orders(timeout_minutes=30)

    assert _trang_thai(order1) == STATUS_CANCELLED
    assert _trang_thai(order2) == STATUS_CANCELLED
    assert _ton_kho(ctx1["product"]["id"]) == 10
    assert _ton_kho(ctx2["product"]["id"]) == 10


def test_tra_lai_luot_voucher_khi_tu_dong_huy(client):
    ctx = seller_with_shop(client)
    client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "AUTO10K", "discount_type": "flat", "discount_value": 10000},
        headers=auth(ctx["token"]),
    )
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
            "voucher_code": "AUTO10K",
        },
        headers=auth(ctx["token"]),
    ).json()["order_id"]

    session = SessionLocal()
    try:
        v = session.query(models.Voucher).filter(models.Voucher.code == "AUTO10K").first()
        assert v.usage_count == 1
    finally:
        session.close()

    _lam_cu_don(order_id, 60)
    cancel_expired_pending_orders(timeout_minutes=30)

    session = SessionLocal()
    try:
        v = session.query(models.Voucher).filter(models.Voucher.code == "AUTO10K").first()
        assert v.usage_count == 0
    finally:
        session.close()
