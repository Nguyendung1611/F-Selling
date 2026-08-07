"""Hàng rào Free/Pro ở đúng ranh giới nghiệp vụ.

Shop hết trial, paid (kể cả grace) và gift phải về Free. Free không bị khóa
những đường xử lý tiền đã phát sinh, nhưng không được tạo thêm nghiệp vụ Pro.
Các test đi qua HTTP để bảo vệ cả router, không chỉ gọi helper kiểm gói.
"""
from __future__ import annotations

import datetime
import uuid

from conftest import _unique, auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import report_service, subscription_service


LOYALTY_PROGRAM = {
    "enabled": True,
    "earn_amount": 10_000,
    "earn_points": 1,
    "redeem_points": 1,
    "redeem_amount": 1_000,
    "min_redeem_points": 1,
    "max_redeem_percent": 100,
    "expiry_days": None,
}


def _op(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _expire_trial_paid_and_gift(shop_id: int) -> None:
    """Tạo đủ ba nguồn quyền đã hết hạn rồi chứng minh shop thật sự là Free."""
    now = datetime.datetime.utcnow()
    session = SessionLocal()
    try:
        subscription = (
            session.query(models.ShopSubscription)
            .filter(models.ShopSubscription.shop_id == shop_id)
            .one()
        )
        subscription.trial_started_at = now - datetime.timedelta(days=100)
        subscription.trial_ends_at = now - datetime.timedelta(days=70)
        # Paid hết hơn 7 ngày để cả grace cũng đã kết thúc.
        subscription.paid_until = now - datetime.timedelta(days=8)
        subscription.updated_at = now

        shop = session.query(models.Shop).filter(models.Shop.id == shop_id).one()
        session.add(
            models.SubscriptionGrant(
                shop_id=shop_id,
                starts_at=now - datetime.timedelta(days=40),
                ends_at=now - datetime.timedelta(days=10),
                expires_on=(now.date() - datetime.timedelta(days=10)).isoformat(),
                reason="Quà cũ đã hết hạn để kiểm hàng rào Free",
                operation_id=_op("expired-gift"),
                operation_fingerprint=uuid.uuid4().hex * 2,
                granted_by_user_id=shop.owner_id,
            )
        )
        session.commit()

        state = subscription_service.get_subscription_state(session, shop_id, now=now)
        assert state["phase"] == "FREE"
        assert state["can_use_pro"] is False
        assert state["paid_grace_until"] < now
        assert state["active_grant_until"] is None
    finally:
        session.close()


def _order_payload(ctx: dict, method: str, *, customer_id: int | None = None) -> dict:
    body = {
        "items": [
            {
                "product_id": ctx["product"]["id"],
                "product_name": ctx["product"]["name"],
                "price": 1,
                "quantity": 1,
            }
        ],
        "payment_method": method,
        "operation_id": _op(f"order-{method}"),
    }
    if customer_id is not None:
        body["customer_id"] = customer_id
    return body


def _create_customer(client, ctx: dict) -> dict:
    response = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": _unique("Khách gói"), "phone": f"09{uuid.uuid4().hex[:8]}"},
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_supplier(client, ctx: dict, *, opening_balance: int = 0) -> dict:
    response = client.post(
        f"/api/suppliers/{ctx['shop_id']}",
        json={
            "name": _unique("NCC gói"),
            "opening_balance": opening_balance,
            "opening_note": "Nợ cũ trước khi hết Pro" if opening_balance else None,
            "operation_id": _op("supplier"),
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json().get("supplier", response.json())


def _receipt_payload(ctx: dict, supplier_id: int, *, operation_id: str | None = None) -> dict:
    return {
        "supplier_id": supplier_id,
        "items": [
            {
                "product_id": ctx["product"]["id"],
                "quantity": 2,
                "unit_cost": 40_000,
            }
        ],
        "supplier_invoice_number": _unique("HDN-GOI"),
        "note": "Kiểm hàng rào gói cước",
        "operation_id": operation_id or _op("receipt"),
    }


def test_free_owner_van_ban_cash_transfer_va_dong_bo_offline(client):
    ctx = seller_with_shop(client)
    _expire_trial_paid_and_gift(ctx["shop_id"])

    cash = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "cash"),
        headers=auth(ctx["token"]),
    )
    assert cash.status_code == 200, cash.text
    paid = client.post(
        f"/api/orders/{cash.json()['order_id']}/pay",
        json={"tendered_amount": 100_000},
        headers=auth(ctx["token"]),
    )
    assert paid.status_code == 200, paid.text

    transfer = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "transfer"),
        headers=auth(ctx["token"]),
    )
    assert transfer.status_code == 200, transfer.text
    assert transfer.json()["status"] == "PENDING"

    offline = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        json={
            "offline_uuid": _op("offline"),
            "sold_at": datetime.datetime.utcnow().isoformat(),
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "product_name": ctx["product"]["name"],
                    "unit_price": 100_000,
                    "quantity": 1,
                }
            ],
            "cash_tendered": 100_000,
            "device_label": "FREE-OFFLINE",
        },
        headers=auth(ctx["token"]),
    )
    assert offline.status_code == 200, offline.text
    assert offline.json()["created"] is True


def test_free_van_thu_no_khach_da_phat_sinh(client):
    ctx = seller_with_shop(client)
    customer = _create_customer(client, ctx)
    debt_order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "debt", customer_id=customer["id"]),
        headers=auth(ctx["token"]),
    )
    assert debt_order.status_code == 200, debt_order.text
    _expire_trial_paid_and_gift(ctx["shop_id"])

    payment = client.post(
        f"/api/orders/{debt_order.json()['order_id']}/debt-payment",
        json={
            "amount": 100_000,
            "method": "transfer",
            "reference": "FREE-THU-NO-CU",
            "operation_id": _op("debt-payment"),
        },
        headers=auth(ctx["token"]),
    )
    assert payment.status_code == 200, payment.text
    assert payment.json()["remaining_amount"] == 0


def test_free_van_tra_no_nha_cung_cap_da_phat_sinh(client):
    ctx = seller_with_shop(client)
    supplier = _create_supplier(client, ctx, opening_balance=100_000)
    _expire_trial_paid_and_gift(ctx["shop_id"])

    payment = client.post(
        f"/api/suppliers/member/{supplier['id']}/payments",
        json={
            "amount": 100_000,
            "method": "TRANSFER",
            "reference": "FREE-TRA-NO-CU",
            "operation_id": _op("supplier-payment"),
        },
        headers=auth(ctx["token"]),
    )
    assert payment.status_code == 200, payment.text
    detail = client.get(
        f"/api/suppliers/member/{supplier['id']}", headers=auth(ctx["token"])
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["supplier"]["payable_balance"] == 0


def test_free_van_dong_duoc_ca_da_mo(client):
    ctx = seller_with_shop(client)
    opened = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": 250_000, "note": "Ca mở trước khi hết Pro"},
        headers=auth(ctx["token"]),
    )
    assert opened.status_code == 200, opened.text
    _expire_trial_paid_and_gift(ctx["shop_id"])

    closed = client.post(
        f"/api/shifts/{opened.json()['id']}/close",
        json={"counted_cash_amount": 250_000, "note": "Đóng ca sau khi về Free"},
        headers=auth(ctx["token"]),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"


def test_free_van_tao_checkout_de_mua_pro(client, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_BANK_CODE", "MB")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NO", "00123456789")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NAME", "F SELLING")
    ctx = seller_with_shop(client)
    _expire_trial_paid_and_gift(ctx["shop_id"])

    checkout = client.post(
        f"/api/subscriptions/{ctx['shop_id']}/checkouts",
        json={"cycle": "MONTHLY", "operation_id": _op("free-checkout")},
        headers=auth(ctx["token"]),
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["amount_due_vnd"] == 99_000
    assert checkout.json()["reference_code"].startswith("SUB")


def test_free_chan_402_khi_tao_nghiep_vu_pro_moi(client):
    ctx = seller_with_shop(client)
    customer = _create_customer(client, ctx)
    supplier = _create_supplier(client, ctx)
    _expire_trial_paid_and_gift(ctx["shop_id"])

    responses = {
        "đơn ghi nợ": client.post(
            f"/api/orders/{ctx['shop_id']}",
            json=_order_payload(ctx, "debt", customer_id=customer["id"]),
            headers=auth(ctx["token"]),
        ),
        "voucher": client.post(
            "/api/vouchers",
            params={"shop_id": ctx["shop_id"]},
            json={
                "code": _unique("FREEBLOCK"),
                "discount_type": "flat",
                "discount_value": 10_000,
            },
            headers=auth(ctx["token"]),
        ),
        "cấu hình tích điểm": client.put(
            f"/api/loyalty/{ctx['shop_id']}",
            json=LOYALTY_PROGRAM,
            headers=auth(ctx["token"]),
        ),
        "nhà cung cấp mới": client.post(
            f"/api/suppliers/{ctx['shop_id']}",
            json={
                "name": _unique("NCC bị chặn"),
                "opening_balance": 0,
                "operation_id": _op("blocked-supplier"),
            },
            headers=auth(ctx["token"]),
        ),
        "phiếu nhập mới": client.post(
            f"/api/purchase-receipts/{ctx['shop_id']}",
            json=_receipt_payload(ctx, supplier["id"]),
            headers=auth(ctx["token"]),
        ),
        "kiểm kê": client.post(
            f"/api/products/{ctx['shop_id']}/stocktake",
            json={
                "items": [
                    {
                        "product_id": ctx["product"]["id"],
                        "counted": 10,
                        "stock_snapshot": 10,
                    }
                ]
            },
            headers=auth(ctx["token"]),
        ),
        "hủy hàng": client.post(
            f"/api/products/{ctx['shop_id']}/write-off",
            json={
                "reason": "LOST",
                "items": [
                    {
                        "product_id": ctx["product"]["id"],
                        "quantity": 1,
                    }
                ],
                "operation_id": _op("blocked-writeoff"),
            },
            headers=auth(ctx["token"]),
        ),
        "nhân viên mới": client.post(
            f"/api/staff/{ctx['shop_id']}",
            json={
                "username": _unique("nv_free"),
                "password": "Nhanvien@2026",
                "staff_role": "CASHIER",
            },
            headers=auth(ctx["token"]),
        ),
        "lô mới": client.post(
            f"/api/products/{ctx['product']['id']}/stock",
            json={
                "delta": 1,
                "reason": "Thử tạo lô khi Free",
                "unit_cost": 40_000,
                "expiry_date": (
                    datetime.date.today() + datetime.timedelta(days=90)
                ).isoformat(),
            },
            headers=auth(ctx["token"]),
        ),
    }

    statuses = {name: response.status_code for name, response in responses.items()}
    assert statuses == {name: 402 for name in responses}, {
        name: response.text for name, response in responses.items()
    }


def test_free_van_ap_voucher_cu_nhung_khong_tao_voucher_moi(client):
    ctx = seller_with_shop(client)
    code = _unique("VOUCHER-CU")
    created = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={
            "code": code,
            "discount_type": "flat",
            "discount_value": 10_000,
        },
        headers=auth(ctx["token"]),
    )
    assert created.status_code == 200, created.text
    _expire_trial_paid_and_gift(ctx["shop_id"])

    applied = client.post(
        f"/api/vouchers/apply/{ctx['shop_id']}",
        data={"subtotal": 100_000, "voucher_code": code},
        headers=auth(ctx["token"]),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["discount_amount"] == 10_000

    blocked = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={
            "code": _unique("VOUCHER-MOI"),
            "discount_type": "flat",
            "discount_value": 5_000,
        },
        headers=auth(ctx["token"]),
    )
    assert blocked.status_code == 402, blocked.text


def test_free_xem_duoc_phieu_nhap_cu_nhung_khong_duoc_sua_chot_xoa(client):
    ctx = seller_with_shop(client)
    supplier = _create_supplier(client, ctx)
    receipt_payload = _receipt_payload(ctx, supplier["id"])
    created = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=receipt_payload,
        headers=auth(ctx["token"]),
    )
    assert created.status_code == 200, created.text
    receipt = created.json().get("receipt", created.json())
    receipt_id = receipt["id"]
    _expire_trial_paid_and_gift(ctx["shop_id"])

    listed = client.get(
        f"/api/purchase-receipts/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    detail = client.get(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    )
    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    draft_fingerprint = detail.json()["draft_fingerprint"]

    update_payload = dict(receipt_payload)
    update_payload.pop("operation_id")
    changed = client.put(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        json=update_payload,
        headers=auth(ctx["token"]),
    )
    confirmed = client.post(
        f"/api/purchase-receipts/receipt/{receipt_id}/confirm",
        json={
            "operation_id": _op("blocked-confirm"),
            "draft_fingerprint": draft_fingerprint,
            "paid_amount": 0,
        },
        headers=auth(ctx["token"]),
    )
    deleted = client.delete(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    )
    assert {
        "sửa": changed.status_code,
        "chốt": confirmed.status_code,
        "xóa": deleted.status_code,
    } == {"sửa": 402, "chốt": 402, "xóa": 402}


def test_moc_bao_cao_free_tinh_theo_ngay_viet_nam(client, monkeypatch):
    ctx = seller_with_shop(client)
    _expire_trial_paid_and_gift(ctx["shop_id"])
    monkeypatch.setattr(
        report_service,
        "_today_vietnam",
        lambda: datetime.date(2026, 8, 8),
    )
    session = SessionLocal()
    try:
        tu_ngay, den_ngay = report_service._limit_free_report_range(
            session, ctx["shop_id"], None, None
        )
    finally:
        session.close()
    assert tu_ngay == "2026-07-09"
    assert den_ngay is None


def test_bao_cao_free_giu_don_00h30_viet_nam_o_ngay_cuoi(client, monkeypatch):
    ctx = seller_with_shop(client)
    trong_moc = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "transfer"),
        headers=auth(ctx["token"]),
    )
    truoc_moc = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "transfer"),
        headers=auth(ctx["token"]),
    )
    assert trong_moc.status_code == truoc_moc.status_code == 200

    session = SessionLocal()
    try:
        session.query(models.Order).filter(
            models.Order.id == trong_moc.json()["order_id"]
        ).one().created_at = datetime.datetime(2026, 7, 8, 17, 30)
        session.query(models.Order).filter(
            models.Order.id == truoc_moc.json()["order_id"]
        ).one().created_at = datetime.datetime(2026, 7, 8, 16, 59)
        session.commit()
    finally:
        session.close()

    _expire_trial_paid_and_gift(ctx["shop_id"])
    monkeypatch.setattr(
        report_service,
        "_today_vietnam",
        lambda: datetime.date(2026, 8, 8),
    )
    response = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}",
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["orders"]] == [
        trong_moc.json()["order_id"]
    ]


def test_free_dashboard_mac_dinh_31_ngay_va_chan_export_log(client):
    ctx = seller_with_shop(client)
    old = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "transfer"),
        headers=auth(ctx["token"]),
    )
    recent = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_order_payload(ctx, "transfer"),
        headers=auth(ctx["token"]),
    )
    assert old.status_code == recent.status_code == 200

    session = SessionLocal()
    try:
        old_order = (
            session.query(models.Order)
            .filter(models.Order.id == old.json()["order_id"])
            .one()
        )
        old_order.created_at = datetime.datetime.utcnow() - datetime.timedelta(days=40)
        # Một đơn PAID cũ đã đóng không được rò tổng tiền qua cửa Đối Soát.
        old_order.status = "PAID"
        session.commit()
    finally:
        session.close()
    _expire_trial_paid_and_gift(ctx["shop_id"])

    dashboard = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["total_orders"] == 1
    assert [row["id"] for row in dashboard.json()["orders"]] == [
        recent.json()["order_id"]
    ]

    reconciliation = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}",
        params={"reconciliation_only": "true"},
        headers=auth(ctx["token"]),
    )
    assert reconciliation.status_code == 200, reconciliation.text
    assert reconciliation.json()["total_revenue"] == 0

    old_range = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}",
        params={
            "tu_ngay": (
                datetime.date.today() - datetime.timedelta(days=60)
            ).isoformat(),
            "den_ngay": (
                datetime.date.today() - datetime.timedelta(days=40)
            ).isoformat(),
        },
        headers=auth(ctx["token"]),
    )
    exported = client.get(
        f"/api/export/seller/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    logs = client.get(
        f"/api/logs/shop/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert {
        "kỳ cũ": old_range.status_code,
        "export": exported.status_code,
        "log": logs.status_code,
    } == {"kỳ cũ": 402, "export": 402, "log": 402}
