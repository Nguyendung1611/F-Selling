"""A1c: máy trạng thái đơn hàng + chuyển trạng thái bằng UPDATE có điều kiện.

    PENDING ------> PAID          (xác nhận thủ công | webhook)
    PENDING ------> CANCELLED     (hủy đơn - endpoint sẽ có ở A1d)
    CANCELLED ----> UNRECONCILED  (CHỈ webhook)
    UNRECONCILED -> PAID          (CHỈ thủ công)

Commit này chưa có endpoint hủy đơn, nên test dựng trạng thái CANCELLED
bằng chính `transition_status()` - đúng cơ chế mà A1d sẽ dùng.
"""
import os
import threading

import pytest
from conftest import auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.services.order_service import (
    CANCEL_FROM,
    STATUS_CANCELLED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_UNRECONCILED,
    read_status,
    transition_status,
)

SECRET = "webhook-secret-a1c"


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _tao_don(client):
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 100000, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    return ctx, order_id


def _dat_trang_thai(order_id, to_state, from_states):
    session = SessionLocal()
    try:
        assert transition_status(session, order_id, from_states, to_state)
    finally:
        session.close()


def _huy_don(order_id):
    _dat_trang_thai(order_id, STATUS_CANCELLED, CANCEL_FROM)


def _trang_thai(order_id):
    session = SessionLocal()
    try:
        return read_status(session, order_id)
    finally:
        session.close()


def _dem_log(action, order_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == action,
                models.SystemLog.details.like(f"%{order_id}%"),
            )
            .count()
        )
    finally:
        session.close()


def _webhook(client, order_id, secret=SECRET):
    return client.post(
        "/api/orders/webhook",
        json={"order_id": order_id},
        headers={"X-Webhook-Secret": secret},
    )


# ---------- transition_status: đơn vị ----------
def test_transition_chi_thanh_cong_dung_mot_lan(client):
    _, order_id = _tao_don(client)
    session = SessionLocal()
    try:
        assert transition_status(session, order_id, (STATUS_PENDING,), STATUS_PAID) is True
        assert transition_status(session, order_id, (STATUS_PENDING,), STATUS_PAID) is False
        assert read_status(session, order_id) == STATUS_PAID
    finally:
        session.close()


def test_transition_that_bai_khi_sai_trang_thai_nguon(client):
    _, order_id = _tao_don(client)
    _huy_don(order_id)
    session = SessionLocal()
    try:
        # CANCELLED không nằm trong nguồn cho phép -> không được đổi
        assert transition_status(session, order_id, (STATUS_PENDING,), STATUS_PAID) is False
        assert read_status(session, order_id) == STATUS_CANCELLED
    finally:
        session.close()


def test_transition_don_khong_ton_tai_tra_false(client):
    session = SessionLocal()
    try:
        assert transition_status(session, 999999, (STATUS_PENDING,), STATUS_PAID) is False
        assert read_status(session, 999999) is None
    finally:
        session.close()


# ---------- Xác nhận thủ công ----------
def test_thu_cong_pending_sang_paid(client):
    ctx, order_id = _tao_don(client)
    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 200
    assert res.json() == {"msg": "Paid successfully"}
    assert _trang_thai(order_id) == STATUS_PAID


def test_thu_cong_bam_trung_tren_don_da_paid_tra_200_im_lang(client):
    ctx, order_id = _tao_don(client)
    client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))

    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 200
    assert res.json() == {"msg": "Paid successfully"}
    assert _trang_thai(order_id) == STATUS_PAID
    # Không ghi thêm log thanh toán cho lần bấm trùng
    assert _dem_log("PAY_ORDER", f"#{order_id} ") == 1


def test_thu_cong_tren_don_da_huy_bi_tu_choi_409(client):
    ctx, order_id = _tao_don(client)
    _huy_don(order_id)

    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 409
    assert STATUS_CANCELLED in res.json()["detail"]
    assert _trang_thai(order_id) == STATUS_CANCELLED, "Đơn đã hủy không được hồi sinh"


def test_thu_cong_giai_quyet_don_can_doi_soat(client, webhook_secret):
    """UNRECONCILED -> PAID: seller đã đối soát sao kê và xác nhận."""
    ctx, order_id = _tao_don(client)
    _huy_don(order_id)
    _webhook(client, order_id)
    assert _trang_thai(order_id) == STATUS_UNRECONCILED

    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 200
    assert _trang_thai(order_id) == STATUS_PAID


def test_thu_cong_van_kiem_tra_quyen_va_don_khong_ton_tai(client):
    from conftest import new_seller

    ctx, order_id = _tao_don(client)
    _, token_b = new_seller(client)
    assert client.post(f"/api/orders/{order_id}/pay", headers=auth(token_b)).status_code == 403
    assert client.post("/api/orders/999999/pay", headers=auth(ctx["token"])).status_code == 404


# ---------- Webhook ----------
def test_webhook_pending_sang_paid(client, webhook_secret):
    _, order_id = _tao_don(client)
    res = _webhook(client, order_id)
    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]
    assert res.json()["unreconciled_order_ids"] == []
    assert _trang_thai(order_id) == STATUS_PAID


def test_webhook_gui_lap_tren_don_da_paid(client, webhook_secret):
    _, order_id = _tao_don(client)
    _webhook(client, order_id)
    res = _webhook(client, order_id)

    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(order_id) == STATUS_PAID
    assert _dem_log("WEBHOOK_PAYMENT", order_id) == 1


def test_webhook_tren_don_da_huy_chuyen_sang_unreconciled(client, webhook_secret):
    """Đây là lỗ hổng cũ: webhook từng hồi sinh đơn CANCELLED thành PAID."""
    _, order_id = _tao_don(client)
    _huy_don(order_id)

    res = _webhook(client, order_id)
    assert res.status_code == 200, "Không được trả lỗi cho ngân hàng (tránh retry vô hạn)"
    assert res.json()["order_ids"] == []
    assert res.json()["unreconciled_order_ids"] == [order_id]
    assert "đối soát" in res.json()["msg"]

    assert _trang_thai(order_id) == STATUS_UNRECONCILED
    assert _trang_thai(order_id) != STATUS_PAID, "Đơn đã hủy KHÔNG được tự động thành PAID"
    assert _dem_log("WEBHOOK_UNRECONCILED", order_id) == 1
    assert _dem_log("WEBHOOK_PAYMENT", order_id) == 0


def test_webhook_gui_lap_tren_don_unreconciled_khong_doi_gi(client, webhook_secret):
    _, order_id = _tao_don(client)
    _huy_don(order_id)
    _webhook(client, order_id)

    res = _webhook(client, order_id)
    assert res.status_code == 200
    assert res.json()["unreconciled_order_ids"] == [order_id]
    assert _trang_thai(order_id) == STATUS_UNRECONCILED
    assert _dem_log("WEBHOOK_UNRECONCILED", order_id) == 1, "Không ghi log lặp"


def test_webhook_khong_dung_secret_khong_doi_trang_thai(client, webhook_secret):
    _, order_id = _tao_don(client)
    assert _webhook(client, order_id, secret="sai").status_code == 401
    assert _trang_thai(order_id) == STATUS_PENDING


# ---------- Đua tất định giữa các đường ----------
def test_huy_truoc_webhook_sau(client, webhook_secret):
    _, order_id = _tao_don(client)
    _huy_don(order_id)
    _webhook(client, order_id)
    assert _trang_thai(order_id) == STATUS_UNRECONCILED


def test_webhook_truoc_huy_sau(client, webhook_secret):
    _, order_id = _tao_don(client)
    _webhook(client, order_id)

    session = SessionLocal()
    try:
        # Hủy đơn đã PAID phải thất bại
        assert transition_status(session, order_id, CANCEL_FROM, STATUS_CANCELLED) is False
    finally:
        session.close()
    assert _trang_thai(order_id) == STATUS_PAID


def test_thu_cong_truoc_huy_sau(client):
    ctx, order_id = _tao_don(client)
    client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))

    session = SessionLocal()
    try:
        assert transition_status(session, order_id, CANCEL_FROM, STATUS_CANCELLED) is False
    finally:
        session.close()
    assert _trang_thai(order_id) == STATUS_PAID


def test_huy_hai_lan_chi_thanh_cong_mot_lan(client):
    _, order_id = _tao_don(client)
    session = SessionLocal()
    try:
        assert transition_status(session, order_id, CANCEL_FROM, STATUS_CANCELLED) is True
        assert transition_status(session, order_id, CANCEL_FROM, STATUS_CANCELLED) is False
    finally:
        session.close()
    assert _trang_thai(order_id) == STATUS_CANCELLED


# ---------- Đa luồng thật (opt-in) ----------
@pytest.mark.skipif(
    not os.getenv("RUN_CONCURRENCY_TESTS"),
    reason="Test đa luồng trên SQLite dễ nhiễu; bật bằng RUN_CONCURRENCY_TESTS=1",
)
def test_dong_thoi_chi_mot_luong_thang(client):
    _, order_id = _tao_don(client)
    ket_qua = []
    barrier = threading.Barrier(2)

    def chay(to_state, from_states):
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            ket_qua.append(transition_status(session, order_id, from_states, to_state))
        except Exception:  # noqa: BLE001 - ghi nhận để assert bên dưới
            ket_qua.append(False)
        finally:
            session.close()

    threads = [
        threading.Thread(target=chay, args=(STATUS_PAID, (STATUS_PENDING,))),
        threading.Thread(target=chay, args=(STATUS_CANCELLED, CANCEL_FROM)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sum(1 for r in ket_qua if r) == 1, "Đúng một luồng được phép chuyển trạng thái"
    assert _trang_thai(order_id) in (STATUS_PAID, STATUS_CANCELLED)


# ---------- Contract ----------
def test_get_order_hien_thi_trang_thai_moi(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    _huy_don(order_id)
    _webhook(client, order_id)

    body = client.get(f"/api/orders/{order_id}", headers=auth(ctx["token"])).json()
    assert set(body.keys()) == {"id", "shop_id", "status", "total_amount", "payment_method"}
    assert body["status"] == STATUS_UNRECONCILED


def test_doanh_thu_khong_tinh_don_huy_va_can_doi_soat(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    _huy_don(order_id)
    _webhook(client, order_id)

    stats = client.get(f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])).json()
    assert stats["total_revenue"] == 0, "Chỉ đơn PAID mới được tính doanh thu"
