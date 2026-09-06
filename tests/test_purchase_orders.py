"""Purchase Order R1: lifecycle, receipt bridge and side-effect boundaries."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from conftest import auth, new_seller, new_staff, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal


def _op(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _supplier(client, ctx):
    response = client.post(
        f"/api/suppliers/{ctx['shop_id']}",
        json={
            "name": f"NCC-{uuid.uuid4().hex[:8]}",
            "opening_balance": 0,
            "operation_id": _op("supplier"),
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _payload(ctx, supplier_id, *, quantity=4, operation_id=None):
    product_id = ctx.get("product_id") or ctx["product"]["id"]
    return {
        "supplier_id": supplier_id,
        "expected_date": (date.today() + timedelta(days=3)).isoformat(),
        "note": "Đơn đặt kiểm thử",
        "items": [{"product_id": product_id, "quantity": quantity}],
        "operation_id": operation_id or _op("purchase-order"),
    }


def _create_order(client, ctx, supplier_id, **changes):
    quantity = changes.pop("quantity", 4)
    payload = _payload(ctx, supplier_id, quantity=quantity)
    payload.update(changes)
    response = client.post(
        f"/api/purchase-orders/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json(), payload


def _place(client, ctx, order):
    response = client.post(
        f"/api/purchase-orders/order/{order['id']}/place",
        json={
            "operation_id": _op("place"),
            "draft_fingerprint": order["draft_fingerprint"],
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_and_ordered_do_not_mutate_inventory_money_or_payables(client):
    ctx = seller_with_shop(client)
    supplier = _supplier(client, ctx)
    product_id = ctx["product"]["id"]

    session = SessionLocal()
    try:
        before = session.query(models.Product).filter_by(id=product_id).one()
        stock_before = int(before.stock)
        payable_before = session.query(models.SupplierPayableEntry).count()
        payment_before = session.query(models.SupplierPayment).count()
        movement_before = session.query(models.CashMovement).count()
    finally:
        session.close()

    draft, _ = _create_order(client, ctx, supplier["id"])
    assert draft["status"] == "DRAFT"
    assert draft["items"][0]["quantity"] == 4
    ordered = _place(client, ctx, draft)
    assert ordered["status"] == "ORDERED"

    session = SessionLocal()
    try:
        assert int(session.query(models.Product).filter_by(id=product_id).one().stock) == stock_before
        assert session.query(models.SupplierPayableEntry).count() == payable_before
        assert session.query(models.SupplierPayment).count() == payment_before
        assert session.query(models.CashMovement).count() == movement_before
    finally:
        session.close()


def test_create_is_idempotent_and_operation_collision_is_rejected(client):
    ctx = seller_with_shop(client)
    supplier = _supplier(client, ctx)
    operation_id = _op("stable-order")
    payload = _payload(ctx, supplier["id"], operation_id=operation_id)

    first = client.post(
        f"/api/purchase-orders/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    second = client.post(
        f"/api/purchase-orders/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["repeated"] is True

    changed = {**payload, "items": [{"product_id": ctx["product"]["id"], "quantity": 5}]}
    collision = client.post(
        f"/api/purchase-orders/{ctx['shop_id']}", json=changed, headers=auth(ctx["token"])
    )
    assert collision.status_code == 409


def test_ordered_quantity_is_subtracted_from_forecast_then_cancel_restores_it(client):
    from tests.test_du_bao_nhap_hang import _dong, _du_bao, _shop_ban_deu

    ctx = _shop_ban_deu(client, ton_dau_ky=65, moi_ngay=2, so_ngay=30)
    supplier = _supplier(client, ctx)
    draft, _ = _create_order(client, ctx, supplier["id"], quantity=6)

    before = _dong(_du_bao(client, ctx).json(), ctx["product_id"])
    assert before["can_nhap"] == 15
    assert before["dang_ve"] == 0

    ordered = _place(client, ctx, draft)
    during = _dong(_du_bao(client, ctx).json(), ctx["product_id"])
    assert during["dang_ve"] == 6
    assert during["can_nhap"] == 9

    cancelled = client.post(
        f"/api/purchase-orders/order/{ordered['id']}/cancel",
        json={"operation_id": _op("cancel")},
        headers=auth(ctx["token"]),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    after = _dong(_du_bao(client, ctx).json(), ctx["product_id"])
    assert after["dang_ve"] == 0
    assert after["can_nhap"] == 15


def test_linked_receipt_must_match_and_confirm_marks_order_received(client):
    ctx = seller_with_shop(client)
    supplier = _supplier(client, ctx)
    order, _ = _create_order(client, ctx, supplier["id"], quantity=4)
    order = _place(client, ctx, order)
    product_id = ctx["product"]["id"]

    wrong = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json={
            "purchase_order_id": order["id"],
            "supplier_id": supplier["id"],
            "received_date": date.today().isoformat(),
            "items": [{"product_id": product_id, "quantity": 3, "unit_cost": 40_000}],
            "operation_id": _op("wrong-receipt"),
        },
        headers=auth(ctx["token"]),
    )
    assert wrong.status_code == 409

    created = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json={
            "purchase_order_id": order["id"],
            "supplier_id": supplier["id"],
            "received_date": date.today().isoformat(),
            "items": [{"product_id": product_id, "quantity": 4, "unit_cost": 40_000}],
            "operation_id": _op("linked-receipt"),
        },
        headers=auth(ctx["token"]),
    )
    assert created.status_code == 200, created.text
    receipt = created.json()
    assert receipt["purchase_order_id"] == order["id"]

    still_ordered = client.get(
        f"/api/purchase-orders/order/{order['id']}", headers=auth(ctx["token"])
    )
    assert still_ordered.json()["status"] == "ORDERED"

    confirmed = client.post(
        f"/api/purchase-receipts/receipt/{receipt['id']}/confirm",
        json={
            "operation_id": _op("confirm-linked"),
            "draft_fingerprint": receipt["draft_fingerprint"],
            "paid_amount": 0,
        },
        headers=auth(ctx["token"]),
    )
    assert confirmed.status_code == 200, confirmed.text
    received = client.get(
        f"/api/purchase-orders/order/{order['id']}", headers=auth(ctx["token"])
    )
    assert received.json()["status"] == "RECEIVED"
    assert received.json()["receipt_id"] == receipt["id"]


def test_other_shop_and_staff_cannot_manage_purchase_orders(client):
    owner = seller_with_shop(client)
    supplier = _supplier(client, owner)
    _, outsider_token = new_seller(client)
    _, manager_token = new_staff(client, owner, staff_role="MANAGER")
    payload = _payload(owner, supplier["id"])

    anonymous = client.post(f"/api/purchase-orders/{owner['shop_id']}", json=payload)
    outsider = client.post(
        f"/api/purchase-orders/{owner['shop_id']}",
        json=payload,
        headers=auth(outsider_token),
    )
    staff = client.post(
        f"/api/purchase-orders/{owner['shop_id']}",
        json=payload,
        headers=auth(manager_token),
    )
    assert anonymous.status_code == 401
    assert outsider.status_code in (403, 404)
    assert staff.status_code == 403


def test_free_can_read_existing_order_but_cannot_mutate_it(client):
    from test_subscription_feature_gates import _expire_trial_paid_and_gift

    ctx = seller_with_shop(client)
    supplier = _supplier(client, ctx)
    order, payload = _create_order(client, ctx, supplier["id"])
    _expire_trial_paid_and_gift(ctx["shop_id"])

    listed = client.get(
        f"/api/purchase-orders/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    detail = client.get(
        f"/api/purchase-orders/order/{order['id']}", headers=auth(ctx["token"])
    )
    create = client.post(
        f"/api/purchase-orders/{ctx['shop_id']}",
        json={**payload, "operation_id": _op("free-create")},
        headers=auth(ctx["token"]),
    )
    update_payload = {key: value for key, value in payload.items() if key != "operation_id"}
    update = client.put(
        f"/api/purchase-orders/order/{order['id']}",
        json=update_payload,
        headers=auth(ctx["token"]),
    )
    place = client.post(
        f"/api/purchase-orders/order/{order['id']}/place",
        json={"operation_id": _op("free-place"), "draft_fingerprint": order["draft_fingerprint"]},
        headers=auth(ctx["token"]),
    )
    delete = client.delete(
        f"/api/purchase-orders/order/{order['id']}", headers=auth(ctx["token"])
    )
    assert listed.status_code == detail.status_code == 200
    assert {create.status_code, update.status_code, place.status_code, delete.status_code} == {402}


def test_order_history_prevents_hard_delete_of_supplier_and_product(client):
    ctx = seller_with_shop(client)
    supplier = _supplier(client, ctx)
    _create_order(client, ctx, supplier["id"])

    supplier_delete = client.delete(
        f"/api/suppliers/member/{supplier['id']}", headers=auth(ctx["token"])
    )
    product_delete = client.delete(
        f"/api/products/{ctx['product']['id']}", headers=auth(ctx["token"])
    )
    assert supplier_delete.status_code == 200
    assert supplier_delete.json()["msg"] == "Deactivated"
    assert product_delete.status_code == 409
