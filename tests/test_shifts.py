"""E1: ca thu ngân durable và sổ thu/chi tiền mặt."""
import uuid

from conftest import STAFF_PASSWORD, auth, login, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _open(client, ctx, token=None, amount=500_000):
    res = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": amount, "note": "Tiền đầu ca"},
        headers=auth(token or ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _movement(client, token, shift_id, movement_type, amount, operation_id=None):
    return client.post(
        f"/api/shifts/{shift_id}/movements",
        json={
            "movement_type": movement_type,
            "amount": amount,
            "note": f"{movement_type} kiểm thử",
            "operation_id": operation_id or uuid.uuid4().hex,
        },
        headers=auth(token),
    )


def _new_staff_with_role(client, ctx, staff_role):
    username = f"shift_{staff_role.lower()}_{uuid.uuid4().hex[:8]}"
    res = client.post(
        f"/api/staff/{ctx['shop_id']}",
        json={
            "username": username,
            "password": STAFF_PASSWORD,
            "staff_role": staff_role,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return login(client, username, STAFF_PASSWORD)


def test_mo_ca_current_va_retry_khong_sinh_trung(client):
    ctx = seller_with_shop(client)
    before = client.get(
        f"/api/shifts/current/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    )
    assert before.status_code == 200
    assert before.json() == {"shift": None}

    opened = _open(client, ctx, amount=500_000)
    assert opened["status"] == "OPEN"
    assert opened["opening_cash_amount"] == 500_000
    assert opened["expected_cash_amount"] == 500_000

    current = client.get(
        f"/api/shifts/current/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()["shift"]
    assert current["id"] == opened["id"]

    # Double-click/retry với body khác vẫn trả đúng ca đang mở, không tạo ca mới.
    retried = _open(client, ctx, amount=999_999)
    assert retried["id"] == opened["id"]
    assert retried["opening_cash_amount"] == 500_000

    session = SessionLocal()
    try:
        count = (
            session.query(models.CashShift)
            .filter(
                models.CashShift.shop_id == ctx["shop_id"],
                models.CashShift.status == "OPEN",
            )
            .count()
        )
        assert count == 1
    finally:
        session.close()


def test_nhieu_thu_ngan_duoc_mo_ca_doc_lap_cung_shop(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)

    owner_shift = _open(client, ctx, amount=100_000)
    staff_shift = _open(client, ctx, token=staff_token, amount=200_000)
    assert owner_shift["id"] != staff_shift["id"]

    owner_current = client.get(
        f"/api/shifts/current/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()["shift"]
    staff_current = client.get(
        f"/api/shifts/current/{ctx['shop_id']}",
        headers=auth(staff_token),
    ).json()["shift"]
    assert owner_current["id"] == owner_shift["id"]
    assert staff_current["id"] == staff_shift["id"]


def test_thu_chi_tinh_expected_va_idempotent_theo_operation_id(client):
    ctx = seller_with_shop(client)
    shift = _open(client, ctx, amount=500_000)
    operation_id = uuid.uuid4().hex

    pay_in = _movement(
        client, ctx["token"], shift["id"], "PAY_IN", 100_000, operation_id
    )
    assert pay_in.status_code == 200, pay_in.text
    assert pay_in.json()["shift"]["expected_cash_amount"] == 600_000

    # Retry cùng operation_id và cùng payload không cộng lần hai.
    retried = _movement(
        client, ctx["token"], shift["id"], "PAY_IN", 100_000, operation_id
    )
    assert retried.status_code == 200
    assert retried.json()["movement"]["id"] == pay_in.json()["movement"]["id"]
    assert retried.json()["shift"]["expected_cash_amount"] == 600_000

    pay_out = _movement(client, ctx["token"], shift["id"], "PAY_OUT", 50_000)
    assert pay_out.status_code == 200
    assert pay_out.json()["shift"]["expected_cash_amount"] == 550_000

    too_much = _movement(client, ctx["token"], shift["id"], "PAY_OUT", 600_000)
    assert too_much.status_code == 409

    session = SessionLocal()
    try:
        assert (
            session.query(models.CashMovement)
            .filter(models.CashMovement.shift_id == shift["id"])
            .count()
            == 2
        )
    finally:
        session.close()


def test_expected_cong_cash_order_payment_va_tru_refund_cash(client):
    ctx = seller_with_shop(client)
    shift = _open(client, ctx, amount=300_000)

    session = SessionLocal()
    try:
        order = models.Order(
            shop_id=ctx["shop_id"],
            total_amount=100_000,
            payment_method="cash",
            status="PAID",
            shift_id=shift["id"],
        )
        session.add(order)
        session.flush()
        session.add_all(
            [
                models.OrderPayment(
                    order_id=order.id,
                    entry_type="CASH_TOPUP",
                    amount=100_000,
                    shift_id=shift["id"],
                ),
                models.OrderPayment(
                    order_id=order.id,
                    entry_type="REFUND_CASH",
                    amount=20_000,
                    shift_id=shift["id"],
                ),
                # Chuyển khoản không được tính vào két tiền mặt.
                models.OrderPayment(
                    order_id=order.id,
                    entry_type="BANK_IN",
                    amount=999_000,
                    shift_id=shift["id"],
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    current = client.get(
        f"/api/shifts/current/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()["shift"]
    assert current["cash_payment_in_amount"] == 100_000
    assert current["cash_refund_amount"] == 20_000
    assert current["expected_cash_amount"] == 380_000


def test_dong_ca_luu_snapshot_chenh_lech_va_khoa_ledger(client):
    ctx = seller_with_shop(client)
    shift = _open(client, ctx, amount=100_000)
    assert _movement(
        client, ctx["token"], shift["id"], "PAY_IN", 50_000
    ).status_code == 200

    closed = client.post(
        f"/api/shifts/{shift['id']}/close",
        json={"counted_cash_amount": 140_000, "note": "Thiếu 10k"},
        headers=auth(ctx["token"]),
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "CLOSED"
    assert body["expected_cash_amount"] == 150_000
    assert body["counted_cash_amount"] == 140_000
    assert body["variance_amount"] == -10_000

    # Retry đóng ca trả lại snapshot, không ghi đè bằng số đếm mới.
    retried = client.post(
        f"/api/shifts/{shift['id']}/close",
        json={"counted_cash_amount": 999_000},
        headers=auth(ctx["token"]),
    )
    assert retried.status_code == 200
    assert retried.json()["counted_cash_amount"] == 140_000

    assert (
        client.get(
            f"/api/shifts/current/{ctx['shop_id']}",
            headers=auth(ctx["token"]),
        ).json()
        == {"shift": None}
    )
    assert (
        _movement(client, ctx["token"], shift["id"], "PAY_IN", 10_000).status_code
        == 409
    )

    detail = client.get(
        f"/api/shifts/{shift['id']}", headers=auth(ctx["token"])
    ).json()
    assert len(detail["movements"]) == 1
    history = client.get(
        f"/api/shifts/history/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()
    assert history["items"][0]["id"] == shift["id"]


def test_khong_dong_ca_khi_con_don_tien_mat_pending(client):
    ctx = seller_with_shop(client)
    shift = _open(client, ctx, amount=0)

    session = SessionLocal()
    try:
        order = models.Order(
            shop_id=ctx["shop_id"],
            total_amount=100_000,
            payment_method="cash",
            status="PENDING",
            shift_id=shift["id"],
        )
        session.add(order)
        session.commit()
        order_id = order.id
    finally:
        session.close()

    blocked = client.post(
        f"/api/shifts/{shift['id']}/close",
        json={"counted_cash_amount": 0},
        headers=auth(ctx["token"]),
    )
    assert blocked.status_code == 409
    assert "chưa thanh toán" in blocked.json()["detail"]

    session = SessionLocal()
    try:
        order = session.query(models.Order).filter(models.Order.id == order_id).first()
        order.status = "CANCELLED"
        session.commit()
    finally:
        session.close()
    assert (
        client.post(
            f"/api/shifts/{shift['id']}/close",
            json={"counted_cash_amount": 0},
            headers=auth(ctx["token"]),
        ).status_code
        == 200
    )


def test_staff_chi_xem_ca_cua_minh_nhung_chu_shop_xem_duoc(client):
    ctx = seller_with_shop(client)
    staff_a_token = _new_staff_with_role(client, ctx, "CASHIER")
    staff_b_token = _new_staff_with_role(client, ctx, "CASHIER")
    manager_token = _new_staff_with_role(client, ctx, "MANAGER")
    shift_a = _open(client, ctx, token=staff_a_token, amount=100_000)

    assert (
        client.get(
            f"/api/shifts/{shift_a['id']}", headers=auth(staff_b_token)
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/shifts/{shift_a['id']}", headers=auth(ctx["token"])
        ).status_code
        == 200
    )

    history_b = client.get(
        f"/api/shifts/history/{ctx['shop_id']}",
        headers=auth(staff_b_token),
    ).json()
    assert history_b["items"] == []

    history_owner = client.get(
        f"/api/shifts/history/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    ).json()
    assert [item["id"] for item in history_owner["items"]] == [shift_a["id"]]

    # Manager là quản lý ca trong shop nên xem được ca của cashier khác.
    assert (
        client.get(
            f"/api/shifts/{shift_a['id']}", headers=auth(manager_token)
        ).status_code
        == 200
    )
    assert (
        _movement(
            client, manager_token, shift_a["id"], "PAY_IN", 10_000
        ).status_code
        == 200
    )
    managed_close = client.post(
        f"/api/shifts/{shift_a['id']}/close",
        json={"counted_cash_amount": 110_000, "note": "Manager chốt ca"},
        headers=auth(manager_token),
    )
    assert managed_close.status_code == 200
    assert managed_close.json()["expected_cash_amount"] == 110_000


def test_warehouse_khong_co_quyen_dung_api_ca(client):
    ctx = seller_with_shop(client)
    warehouse_token = _new_staff_with_role(client, ctx, "WAREHOUSE")
    assert (
        client.get(
            f"/api/shifts/current/{ctx['shop_id']}",
            headers=auth(warehouse_token),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/shifts/{ctx['shop_id']}/open",
            json={"opening_cash_amount": 0},
            headers=auth(warehouse_token),
        ).status_code
        == 403
    )


def test_xoa_shop_don_ca_ledger_va_vo_hieu_staff(client):
    ctx = seller_with_shop(client)
    staff_username, staff_token = new_staff(client, ctx, "CASHIER")
    staff_shift = _open(client, ctx, token=staff_token, amount=100_000)
    assert _movement(
        client, staff_token, staff_shift["id"], "PAY_IN", 20_000
    ).status_code == 200

    deleted = client.delete(
        f"/api/shops/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert deleted.status_code == 200, deleted.text

    session = SessionLocal()
    try:
        assert session.query(models.CashShift).filter(
            models.CashShift.shop_id == ctx["shop_id"]
        ).count() == 0
        assert session.query(models.CashMovement).filter(
            models.CashMovement.shift_id == staff_shift["id"]
        ).count() == 0
        staff = session.query(models.User).filter(
            models.User.username == staff_username
        ).first()
        assert staff.is_active is False
        assert staff.staff_shop_id is None
    finally:
        session.close()
