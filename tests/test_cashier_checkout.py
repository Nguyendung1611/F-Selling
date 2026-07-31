"""Thu ngân: gắn người bán/ca và tính tiền thừa hoàn toàn ở server."""
import threading
import uuid

from conftest import auth, new_staff, seller_with_shop
from fastapi import HTTPException

from fselling import models
from fselling.core.database import SessionLocal
from fselling.schemas.order import OrderCreate
from fselling.services import order_service


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


def test_hai_thu_ngan_khong_the_ban_am_kho_hoac_vuot_luot_voucher(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    voucher_code = f"RACE{uuid.uuid4().hex[:8].upper()}"

    session = SessionLocal()
    try:
        product = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product"]["id"])
            .first()
        )
        product.stock = 1
        session.commit()
    finally:
        session.close()

    voucher = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={
            "code": voucher_code,
            "discount_type": "flat",
            "discount_value": 10_000,
            "min_order_value": 0,
            "usage_limit": 1,
            "expires_at": None,
        },
        headers=auth(ctx["token"]),
    )
    assert voucher.status_code == 200, voucher.text

    cashier_a, token_a = new_staff(client, ctx, "CASHIER")
    cashier_b, token_b = new_staff(client, ctx, "CASHIER")
    _open_shift(client, ctx, token_a, opening=0)
    _open_shift(client, ctx, token_b, opening=0)

    # Ép hai request cùng vượt qua fast-path rồi tranh đúng shop lock. Nếu
    # resolve tồn/voucher xảy ra trước lock, cả hai sẽ cùng thấy stock/limit=1.
    ready = threading.Barrier(2)
    real_lock = order_service._lock_shop_for_order

    def synchronized_shop_lock(db, shop_id):
        ready.wait(timeout=5)
        return real_lock(db, shop_id)

    monkeypatch.setattr(
        order_service, "_lock_shop_for_order", synchronized_shop_lock
    )

    outcomes = []
    outcomes_lock = threading.Lock()

    def submit(username, operation_id):
        thread_session = SessionLocal()
        try:
            user = (
                thread_session.query(models.User)
                .filter(models.User.username == username)
                .first()
            )
            request = OrderCreate(
                items=[
                    {
                        "product_id": ctx["product"]["id"],
                        "product_name": ctx["product"]["name"],
                        "price": 1,
                        "quantity": 1,
                    }
                ],
                voucher_code=voucher_code,
                payment_method="cash",
                operation_id=operation_id,
            )
            result = order_service.create_order(
                thread_session, user, ctx["shop_id"], request
            )
            outcome = ("ok", result["order_id"])
        except HTTPException as exc:
            outcome = ("http", exc.status_code, str(exc.detail))
        except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
            outcome = ("error", type(exc).__name__, str(exc))
        finally:
            thread_session.close()
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=submit, args=(cashier_a, uuid.uuid4().hex)),
        threading.Thread(target=submit, args=(cashier_b, uuid.uuid4().hex)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len([result for result in outcomes if result[0] == "ok"]) == 1
    rejected = [result for result in outcomes if result[0] == "http"]
    assert len(rejected) == 1
    assert rejected[0][1] == 400
    assert "không đủ tồn kho" in rejected[0][2]

    session = SessionLocal()
    try:
        product = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product"]["id"])
            .first()
        )
        stored_voucher = (
            session.query(models.Voucher)
            .filter(
                models.Voucher.shop_id == ctx["shop_id"],
                models.Voucher.code == voucher_code,
            )
            .first()
        )
        assert product.stock == 0
        assert stored_voucher.usage_count == 1
        assert (
            session.query(models.Order)
            .filter(models.Order.shop_id == ctx["shop_id"])
            .count()
            == 1
        )
    finally:
        session.close()


def test_retry_dong_thoi_recheck_operation_id_sau_shop_lock(client, monkeypatch):
    ctx = seller_with_shop(client)
    cashier, cashier_token = new_staff(client, ctx, "CASHIER")
    _open_shift(client, ctx, cashier_token, opening=0)
    operation_id = uuid.uuid4().hex

    ready = threading.Barrier(2)
    real_lock = order_service._lock_shop_for_order

    def synchronized_shop_lock(db, shop_id):
        ready.wait(timeout=5)
        return real_lock(db, shop_id)

    monkeypatch.setattr(
        order_service, "_lock_shop_for_order", synchronized_shop_lock
    )

    real_resolve = order_service.inventory_service.resolve_items
    resolve_calls = 0
    counter_lock = threading.Lock()

    def counted_resolve(db, shop_id, wanted):
        nonlocal resolve_calls
        with counter_lock:
            resolve_calls += 1
        return real_resolve(db, shop_id, wanted)

    monkeypatch.setattr(
        order_service.inventory_service, "resolve_items", counted_resolve
    )

    outcomes = []
    outcomes_lock = threading.Lock()

    def submit():
        thread_session = SessionLocal()
        try:
            user = (
                thread_session.query(models.User)
                .filter(models.User.username == cashier)
                .first()
            )
            request = OrderCreate(
                items=[
                    {
                        "product_id": ctx["product"]["id"],
                        "product_name": ctx["product"]["name"],
                        "price": 1,
                        "quantity": 1,
                    }
                ],
                payment_method="cash",
                operation_id=operation_id,
            )
            outcome = order_service.create_order(
                thread_session, user, ctx["shop_id"], request
            )
        except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
            outcome = {"error": type(exc).__name__, "detail": str(exc)}
        finally:
            thread_session.close()
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(outcomes) == 2
    assert all("error" not in result for result in outcomes)
    assert outcomes[0] == outcomes[1]
    assert resolve_calls == 1

    session = SessionLocal()
    try:
        product = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product"]["id"])
            .first()
        )
        assert product.stock == 9
        assert (
            session.query(models.Order)
            .filter(models.Order.operation_id == operation_id)
            .count()
            == 1
        )
    finally:
        session.close()


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
