"""Webhook thanh toán: fail-closed, sai secret, hợp lệ, gửi lặp."""
import pytest
from conftest import auth, seller_with_shop

from fselling.services import payment_service
from fselling.routers import webhooks

SECRET = "webhook-secret-test"


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


@pytest.fixture
def khong_co_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: "")


def _tao_don(client):
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 100000, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    return ctx, order_id


def _trang_thai(client, ctx, order_id):
    return client.get(f"/api/orders/{order_id}", headers=auth(ctx["token"])).json()["status"]


def test_thieu_secret_thi_tu_choi_fail_closed(client, khong_co_secret):
    ctx, order_id = _tao_don(client)
    res = client.post("/api/orders/webhook", json={"order_id": order_id})
    assert res.status_code == 503
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_sai_secret_bi_tu_choi(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"order_id": order_id},
        headers={"X-Webhook-Secret": "sai-secret"},
    )
    assert res.status_code == 401
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_khong_gui_secret_bi_tu_choi(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post("/api/orders/webhook", json={"order_id": order_id})
    assert res.status_code == 401
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_secret_dung_cap_nhat_don_sang_paid(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"order_id": order_id},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_chap_nhan_secret_qua_header_authorization(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    for header in (f"Bearer {SECRET}", f"Apikey {SECRET}"):
        res = client.post(
            "/api/orders/webhook",
            json={"order_id": order_id},
            headers={"Authorization": header},
        )
        assert res.status_code == 200


def test_webhook_gui_lap_khong_xu_ly_lai(client, webhook_secret):
    from fselling import models
    from fselling.core.database import SessionLocal

    ctx, order_id = _tao_don(client)
    headers = {"X-Webhook-Secret": SECRET}
    payload = {"order_id": order_id}

    for _ in range(3):
        res = client.post("/api/orders/webhook", json=payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["order_ids"] == [order_id]

    assert _trang_thai(client, ctx, order_id) == "PAID"

    # Chỉ được ghi đúng 1 log WEBHOOK_PAYMENT cho đơn này, và tồn kho không bị trừ thêm
    session = SessionLocal()
    try:
        logs = (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == "WEBHOOK_PAYMENT",
                models.SystemLog.details.like(f"Order {order_id} %"),
            )
            .all()
        )
        assert len(logs) == 1
        prod = session.query(models.Product).filter(
            models.Product.id == ctx["product"]["id"]
        ).first()
        assert prod.stock == 9
    finally:
        session.close()


def test_khong_tim_thay_ma_don_tra_400(client, webhook_secret):
    res = client.post(
        "/api/orders/webhook",
        json={"content": "chuyen khoan khong co ma"},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 400


def test_don_khong_ton_tai_tra_404(client, webhook_secret):
    res = client.post(
        "/api/orders/webhook",
        json={"order_id": 999999},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 404


def test_body_khong_phai_json_van_bi_chan_boi_secret(client, webhook_secret):
    res = client.post(
        "/api/orders/webhook",
        content=b"khong-phai-json",
        headers={"X-Webhook-Secret": "sai"},
    )
    assert res.status_code == 401


def test_dinh_dang_casso_danh_sach_giao_dich(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"data": [{"description": f"CK ORDER{order_id} noi dung"}]},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_dinh_dang_payos_ordercode(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"data": {"orderCode": order_id, "description": ""}},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_dinh_dang_sepay_content(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"content": f"ORDER{order_id}", "transferAmount": 100000},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert _trang_thai(client, ctx, order_id) == "PAID"


# --- Unit test cho bộ phân tích payload (không cần HTTP) ---
def test_extract_order_ids_cac_dinh_dang():
    assert payment_service.extract_order_ids({"order_id": 7}) == [7]
    assert payment_service.extract_order_ids({"data": [{"description": "ORDER12"}]}) == [12]
    assert payment_service.extract_order_ids({"content": "abc ORDER3 xyz"}) == [3]
    assert payment_service.extract_order_ids({"data": {"orderCode": 9, "description": ""}}) == [9]
    assert payment_service.extract_order_ids({}) == []
    assert payment_service.extract_order_ids({"note": "order55"}) == [55]  # fallback, khong phan biet hoa thuong


def test_build_qr_url_chua_ma_don():
    class _Shop:
        bank_code = "VCB"
        bank_account_no = "123"
        bank_account_name = "TEST"

    url = payment_service.build_qr_url(_Shop(), 150000.0, 42)
    assert "amount=150000" in url
    assert "addInfo=ORDER42" in url
