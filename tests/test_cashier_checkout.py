"""Thu ngân: gắn người bán/ca và tính tiền thừa hoàn toàn ở server."""
import uuid

from conftest import auth, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _cash_order(client, ctx, token=None):
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "product_name": ctx["product"]["name"],
                    "price": 1,
                    "quantity": 1,
                }
            ],
            "payment_method": "cash",
        },
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()["order_id"]


def _open_shift(client, ctx, token=None, opening=200_000):
    response = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": opening},
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_tien_khach_dua_tien_thua_va_ca_duoc_luu_server_side(client):
    ctx = seller_with_shop(client)
    shift = _open_shift(client, ctx)
    order_id = _cash_order(client, ctx)

    paid = client.post(
        f"/api/orders/{order_id}/pay",
        json={"tendered_amount": 150_000},
        headers=auth(ctx["token"]),
    )
    assert paid.status_code == 200, paid.text

    detail = client.get(
        f"/api/orders/{order_id}/detail", headers=auth(ctx["token"])
    ).json()
    assert detail["cashier_username"] == ctx["username"]
    assert detail["shift_id"] == shift["id"]
    assert detail["cash_paid_amount"] == 100_000
    assert detail["cash_tendered_amount"] == 150_000
    assert detail["cash_change_amount"] == 50_000

    current = client.get(
        f"/api/shifts/current/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()["shift"]
    # Két tăng theo doanh thu thực giữ lại, không tăng theo tiền khách đưa.
    assert current["cash_payment_in_amount"] == 100_000
    assert current["expected_cash_amount"] == 300_000

    dashboard = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()
    dashboard_order = next(item for item in dashboard["orders"] if item["id"] == order_id)
    assert dashboard_order["cashier_username"] == ctx["username"]
    assert dashboard_order["shift_id"] == shift["id"]

    # Double-click/retry không ghi thêm payment và không thay tiền thừa ban đầu.
    retry = client.post(
        f"/api/orders/{order_id}/pay",
        json={"tendered_amount": 200_000},
        headers=auth(ctx["token"]),
    )
    assert retry.status_code == 200
    after_retry = client.get(
        f"/api/orders/{order_id}/detail", headers=auth(ctx["token"])
    ).json()
    assert after_retry["cash_tendered_amount"] == 150_000
    assert after_retry["cash_change_amount"] == 50_000

    session = SessionLocal()
    try:
        payments = (
            session.query(models.OrderPayment)
            .filter(models.OrderPayment.order_id == order_id)
            .all()
        )
        assert len(payments) == 1
        assert payments[0].shift_id == shift["id"]
    finally:
        session.close()


def test_server_tu_choi_tien_khach_dua_chua_du(client):
    ctx = seller_with_shop(client)
    _open_shift(client, ctx, opening=0)
    order_id = _cash_order(client, ctx)

    response = client.post(
        f"/api/orders/{order_id}/pay",
        json={"tendered_amount": 99_999},
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 400

    order = client.get(
        f"/api/orders/{order_id}", headers=auth(ctx["token"])
    ).json()
    assert order["status"] == "PENDING"
    assert order["cash_paid_amount"] == 0


def test_retry_tao_don_khong_tru_kho_hai_lan(client):
    ctx = seller_with_shop(client)
    operation_id = uuid.uuid4().hex
    payload = {
        "items": [{
            "product_id": ctx["product"]["id"],
            "product_name": ctx["product"]["name"],
            "price": 1,
            "quantity": 2,
        }],
        "payment_method": "cash",
        "operation_id": operation_id,
    }

    first = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    retry = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()

    session = SessionLocal()
    try:
        product = session.query(models.Product).filter(
            models.Product.id == ctx["product"]["id"]
        ).first()
        assert product.stock == 8
        assert session.query(models.Order).filter(
            models.Order.operation_id == operation_id
        ).count() == 1
    finally:
        session.close()

    changed_payload = dict(payload)
    changed_payload["items"] = [dict(payload["items"][0], quantity=1)]
    conflict = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=changed_payload,
        headers=auth(ctx["token"]),
    )
    assert conflict.status_code == 409


def test_cashier_phai_mo_ca_truoc_khi_thu_tien_mat(client):
    ctx = seller_with_shop(client)
    _, cashier_token = new_staff(client, ctx, "CASHIER")
    order_id = _cash_order(client, ctx, cashier_token)

    blocked = client.post(
        f"/api/orders/{order_id}/pay",
        json={"tendered_amount": 100_000},
        headers=auth(cashier_token),
    )
    assert blocked.status_code == 409
    assert "mở ca" in blocked.json()["detail"]

    shift = _open_shift(client, ctx, cashier_token, opening=0)
    paid = client.post(
        f"/api/orders/{order_id}/pay",
        json={"tendered_amount": 100_000},
        headers=auth(cashier_token),
    )
    assert paid.status_code == 200, paid.text

    detail = client.get(
        f"/api/orders/{order_id}/detail", headers=auth(cashier_token)
    ).json()
    assert detail["shift_id"] == shift["id"]


def test_ngung_tai_khoan_van_giu_ten_thu_ngan_tren_hoa_don(client):
    ctx = seller_with_shop(client)
    cashier_username, cashier_token = new_staff(client, ctx, "CASHIER")
    shift = _open_shift(client, ctx, cashier_token, opening=0)
    order_id = _cash_order(client, ctx, cashier_token)
    assert client.post(
        f"/api/orders/{order_id}/pay",
        json={"tendered_amount": 100_000},
        headers=auth(cashier_token),
    ).status_code == 200
    assert client.post(
        f"/api/shifts/{shift['id']}/close",
        json={"counted_cash_amount": 100_000},
        headers=auth(cashier_token),
    ).status_code == 200

    staff = client.get(
        f"/api/staff/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    cashier_id = next(
        item["id"] for item in staff if item["username"] == cashier_username
    )
    disabled = client.delete(
        f"/api/staff/member/{cashier_id}", headers=auth(ctx["token"])
    )
    assert disabled.status_code == 200

    detail = client.get(
        f"/api/orders/{order_id}/detail", headers=auth(ctx["token"])
    ).json()
    assert detail["cashier_username"] == cashier_username
