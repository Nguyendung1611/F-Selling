"""D4: đối soát cộng dồn, bù tiền mặt và hoàn tiền.

Các test này khóa ba nguyên tắc:
- webhook chỉ cộng mỗi giao dịch ngân hàng đúng một lần;
- chuyển đủ tự PAID, chuyển thừa vẫn xuất hóa đơn nhưng mở khoản phải hoàn;
- tiền về sau khi hủy tuyệt đối không hồi sinh đơn thành PAID.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from conftest import (
    PAYMENT_SUMMARY_KEYS,
    auth,
    new_seller,
    new_staff,
    seller_with_shop,
)
from fselling import models
from fselling.core import bootstrap
from fselling.core.database import SessionLocal
from fselling.routers import webhooks

SECRET = "webhook-secret-reconciliation"
TOTAL = 100000


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _tao_don(client, ctx, payment_method="transfer"):
    res = client.post(
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
            "payment_method": payment_method,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()["order_id"]


def _goi_webhook(client, order_id, amount, txn_id):
    return client.post(
        "/api/orders/webhook",
        json={
            "content": f"ORDER{order_id}",
            "transferAmount": amount,
            "transferType": "in",
            "id": txn_id,
        },
        headers={"X-Webhook-Secret": SECRET},
    )


def _lay_don(client, ctx, order_id):
    res = client.get(
        f"/api/orders/{order_id}",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _payments(order_id):
    session = SessionLocal()
    try:
        rows = (
            session.query(models.OrderPayment)
            .filter(models.OrderPayment.order_id == order_id)
            .order_by(models.OrderPayment.id)
            .all()
        )
        return [
            {
                "entry_type": p.entry_type,
                "amount": p.amount,
                "bank_txn_id": p.bank_txn_id,
                "created_by_user_id": p.created_by_user_id,
                "note": p.note,
                "reference": p.reference,
            }
            for p in rows
        ]
    finally:
        session.close()


def _logs(action, order_id):
    session = SessionLocal()
    try:
        rows = (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == action,
                models.SystemLog.details.like(f"%Order {order_id}%"),
            )
            .order_by(models.SystemLog.id)
            .all()
        )
        return [
            {"user_id": row.user_id, "details": row.details}
            for row in rows
        ]
    finally:
        session.close()


def _user_id(username):
    session = SessionLocal()
    try:
        return (
            session.query(models.User.id)
            .filter(models.User.username == username)
            .scalar()
        )
    finally:
        session.close()


def _stock(product_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.Product.stock)
            .filter(models.Product.id == product_id)
            .scalar()
        )
    finally:
        session.close()


def _dashboard(client, ctx, token=None, **params):
    return client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}",
        params=params,
        headers=auth(token or ctx["token"]),
    )


def test_webhook_du_tien_tu_dong_paid_va_xuat_hoa_don(client, webhook_secret):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)

    res = _goi_webhook(client, order_id, TOTAL, f"EXACT-{order_id}")
    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]
    assert res.json()["unreconciled_order_ids"] == []

    order = _lay_don(client, ctx, order_id)
    assert order["status"] == "PAID"
    assert order["received_amount"] == TOTAL
    assert order["remaining_amount"] == 0
    assert order["overpaid_amount"] == 0
    assert order["refund_pending"] is False
    assert order["reconciliation_reason"] is None
    assert order["invoice_issued"] is True
    assert _payments(order_id) == [
        {
            "entry_type": "BANK_IN",
            "amount": TOTAL,
            "bank_txn_id": f"EXACT-{order_id}",
            "created_by_user_id": None,
            "note": None,
            "reference": None,
        }
    ]
    assert len(_logs("WEBHOOK_PAYMENT", order_id)) == 1
    assert _logs("PAY_ORDER", order_id) == []

    stats = client.get(
        f"/api/shops/{ctx['shop_id']}/stats",
        headers=auth(ctx["token"]),
    ).json()
    assert stats["total_revenue"] == TOTAL


def test_hai_giao_dich_khac_ma_duoc_cong_don_den_du(client, webhook_secret):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)

    first = _goi_webhook(client, order_id, 40000, f"CUM-A-{order_id}")
    assert first.json()["unreconciled_order_ids"] == [order_id]
    underpaid = _lay_don(client, ctx, order_id)
    assert underpaid["status"] == "UNRECONCILED"
    assert underpaid["reconciliation_reason"] == "UNDERPAID"
    assert underpaid["received_amount"] == 40000
    assert underpaid["remaining_amount"] == 60000
    assert underpaid["invoice_issued"] is False

    second = _goi_webhook(client, order_id, 60000, f"CUM-B-{order_id}")
    assert second.json()["order_ids"] == [order_id]
    paid = _lay_don(client, ctx, order_id)
    assert paid["status"] == "PAID"
    assert paid["received_amount"] == TOTAL
    assert paid["remaining_amount"] == 0
    assert paid["reconciliation_reason"] is None
    assert paid["invoice_issued"] is True
    assert [(p["entry_type"], p["amount"]) for p in _payments(order_id)] == [
        ("BANK_IN", 40000),
        ("BANK_IN", 60000),
    ]
    assert len(_logs("WEBHOOK_THIEU_TIEN", order_id)) == 1
    assert len(_logs("WEBHOOK_PAYMENT", order_id)) == 1


def test_hai_giao_dich_cung_don_trong_mot_payload_deu_duoc_cong(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)

    res = client.post(
        "/api/orders/webhook",
        json={
            "data": [
                {
                    "description": f"ORDER{order_id}",
                    "amount": 40000,
                    "tid": f"BATCH-A-{order_id}",
                },
                {
                    "description": f"ORDER{order_id}",
                    "amount": 60000,
                    "tid": f"BATCH-B-{order_id}",
                },
            ]
        },
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]
    assert res.json()["unreconciled_order_ids"] == []
    assert _lay_don(client, ctx, order_id)["received_amount"] == TOTAL
    assert len(_payments(order_id)) == 2


def test_webhook_trung_ma_khong_cong_lai_va_xung_dot_bi_tu_choi(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    txn_id = f"IDEMP-{order_id}"

    payload = _goi_webhook(client, order_id, 40000, txn_id)
    assert payload.status_code == 200
    for _ in range(3):
        retry = _goi_webhook(client, order_id, 40000, txn_id)
        assert retry.status_code == 200
        assert retry.json()["unreconciled_order_ids"] == [order_id]

    order = _lay_don(client, ctx, order_id)
    assert order["received_amount"] == 40000
    assert len(_payments(order_id)) == 1
    assert len(_logs("WEBHOOK_THIEU_TIEN", order_id)) == 1

    collision = _goi_webhook(client, order_id, 50000, txn_id)
    assert collision.status_code == 200
    assert collision.json()["rejected_order_ids"] == [order_id]
    assert _lay_don(client, ctx, order_id)["received_amount"] == 40000
    assert len(_payments(order_id)) == 1
    assert len(_logs("WEBHOOK_XUNG_DOT_IDEMPOTENCY", order_id)) == 1


def test_cash_topup_chi_thu_dung_toan_bo_phan_con_lai(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    _goi_webhook(client, order_id, 40000, f"CASH-BANK-{order_id}")

    partial = client.post(
        f"/api/orders/{order_id}/cash-topup",
        json={"amount": 20000, "note": "Khách bù một phần"},
        headers=auth(ctx["token"]),
    )
    assert partial.status_code == 400, partial.text
    assert _lay_don(client, ctx, order_id)["received_amount"] == 40000

    exact = client.post(
        f"/api/orders/{order_id}/cash-topup",
        json={},
        headers=auth(ctx["token"]),
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["status"] == "PAID"
    assert exact.json()["cash_paid_amount"] == 60000
    assert exact.json()["received_amount"] == TOTAL
    assert exact.json()["remaining_amount"] == 0
    assert exact.json()["invoice_issued"] is True

    owner_id = _user_id(ctx["username"])
    payments = _payments(order_id)
    assert [(p["entry_type"], p["amount"]) for p in payments] == [
        ("BANK_IN", 40000),
        ("CASH_TOPUP", 60000),
    ]
    assert payments[1]["created_by_user_id"] == owner_id
    assert len(_logs("CASH_TOPUP", order_id)) == 1

    repeated = client.post(
        f"/api/orders/{order_id}/cash-topup",
        json={},
        headers=auth(ctx["token"]),
    )
    assert repeated.status_code == 409
    assert len(_payments(order_id)) == 2


def test_cash_topup_sai_so_tien_khong_lam_thay_doi_don(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    _goi_webhook(client, order_id, 40000, f"CASH-INVALID-{order_id}")

    for amount in (0, -1, 20000, 60001):
        res = client.post(
            f"/api/orders/{order_id}/cash-topup",
            json={"amount": amount},
            headers=auth(ctx["token"]),
        )
        assert res.status_code == 400, (amount, res.text)

    order = _lay_don(client, ctx, order_id)
    assert order["received_amount"] == 40000
    assert order["cash_paid_amount"] == 0
    assert order["remaining_amount"] == 60000
    assert len(_payments(order_id)) == 1
    assert _logs("CASH_TOPUP", order_id) == []


def test_cash_topup_chi_ap_dung_cho_underpaid(client, webhook_secret):
    ctx = seller_with_shop(client)
    pending_id = _tao_don(client, ctx)
    assert client.post(
        f"/api/orders/{pending_id}/cash-topup",
        json={},
        headers=auth(ctx["token"]),
    ).status_code == 409

    paid_id = _tao_don(client, ctx)
    _goi_webhook(client, paid_id, TOTAL, f"CASH-PAID-{paid_id}")
    assert client.post(
        f"/api/orders/{paid_id}/cash-topup",
        json={},
        headers=auth(ctx["token"]),
    ).status_code == 409


def test_chuyen_thua_van_paid_va_mo_khoan_cho_hoan(client, webhook_secret):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)

    res = _goi_webhook(client, order_id, 120000, f"OVER-{order_id}")
    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]

    order = _lay_don(client, ctx, order_id)
    assert order["status"] == "PAID"
    assert order["received_amount"] == 120000
    assert order["overpaid_amount"] == 20000
    assert order["refund_due_amount"] == 20000
    assert order["refund_pending"] is True
    assert order["reconciliation_reason"] == "OVERPAID"
    assert order["reconciliation_pending"] is True
    assert order["invoice_issued"] is True

    stats = client.get(
        f"/api/shops/{ctx['shop_id']}/stats",
        headers=auth(ctx["token"]),
    ).json()
    assert stats["total_revenue"] == TOTAL, "Tiền dư không được tính thành doanh thu"


def test_giao_dich_moi_sau_paid_duoc_ghi_nhan_la_tien_du(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    _goi_webhook(client, order_id, TOTAL, f"PAID-FIRST-{order_id}")
    _goi_webhook(client, order_id, 10000, f"PAID-EXTRA-{order_id}")

    order = _lay_don(client, ctx, order_id)
    assert order["status"] == "PAID"
    assert order["received_amount"] == 110000
    assert order["refund_due_amount"] == 10000
    assert order["refund_pending"] is True
    assert len(_payments(order_id)) == 2
    assert len(_logs("WEBHOOK_TRA_TRUNG", order_id)) == 1


def test_refund_complete_luu_du_audit_va_bam_lap_idempotent(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    staff_username, staff_token = new_staff(client, ctx)
    staff_id = _user_id(staff_username)
    order_id = _tao_don(client, ctx)
    _goi_webhook(client, order_id, 120000, f"REFUND-{order_id}")

    body = {
        "method": "transfer",
        "note": "Đã chuyển lại cho khách",
        "reference": f"REF-{order_id}",
        "operation_id": f"refund-operation-{order_id}",
    }
    res = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json=body,
        headers=auth(staff_token),
    )
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["status"] == "PAID"
    assert result["received_amount"] == 120000
    assert result["refunded_amount"] == 20000
    assert result["refund_due_amount"] == 0
    assert result["refund_pending"] is False
    assert result["refund_completed_at"] is not None
    assert result["refund_completed_by"] == staff_id
    assert result["refund_method"] == "transfer"
    assert result["refund_note"] == body["note"]
    assert result["refund_reference"] == body["reference"]
    assert result["invoice_issued"] is True

    payments = _payments(order_id)
    assert [(p["entry_type"], p["amount"]) for p in payments] == [
        ("BANK_IN", 120000),
        ("REFUND_TRANSFER", 20000),
    ]
    assert payments[1]["created_by_user_id"] == staff_id
    assert payments[1]["note"] == body["note"]
    assert payments[1]["reference"] == body["reference"]

    logs = _logs("REFUND_COMPLETE", order_id)
    assert len(logs) == 1
    assert logs[0]["user_id"] == staff_id
    assert "20,000" in logs[0]["details"]
    assert body["reference"] in logs[0]["details"]

    repeated = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json=body,
        headers=auth(staff_token),
    )
    assert repeated.status_code == 200
    assert len(_payments(order_id)) == 2
    assert len(_logs("REFUND_COMPLETE", order_id)) == 1


def test_refund_complete_validate_method_va_can_co_tien_du(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    exact_id = _tao_don(client, ctx)
    _goi_webhook(client, exact_id, TOTAL, f"NO-REFUND-{exact_id}")
    no_due = client.post(
        f"/api/orders/{exact_id}/refund-complete",
        json={"method": "cash", "operation_id": f"no-refund-operation-{exact_id}"},
        headers=auth(ctx["token"]),
    )
    assert no_due.status_code == 409

    over_id = _tao_don(client, ctx)
    _goi_webhook(client, over_id, 120000, f"BAD-METHOD-{over_id}")
    invalid = client.post(
        f"/api/orders/{over_id}/refund-complete",
        json={"method": "crypto", "operation_id": f"bad-method-operation-{over_id}"},
        headers=auth(ctx["token"]),
    )
    assert invalid.status_code == 422
    assert _lay_don(client, ctx, over_id)["refund_due_amount"] == 20000
    assert len(_payments(over_id)) == 1


def test_retry_hoan_cu_khong_xac_nhan_nham_khoan_du_moi(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    _goi_webhook(client, order_id, 120000, f"REFUND-CYCLE-1-{order_id}")
    old_body = {
        "method": "transfer",
        "operation_id": f"refund-old-cycle-{order_id}",
    }
    first = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json=old_body,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == 200

    _goi_webhook(client, order_id, 10000, f"REFUND-CYCLE-2-{order_id}")
    assert _lay_don(client, ctx, order_id)["refund_due_amount"] == 10000

    delayed_retry = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json=old_body,
        headers=auth(ctx["token"]),
    )
    assert delayed_retry.status_code == 200
    assert delayed_retry.json()["refund_due_amount"] == 10000
    assert delayed_retry.json()["refund_pending"] is True
    assert [p["entry_type"] for p in _payments(order_id)].count(
        "REFUND_TRANSFER"
    ) == 1

    new_cycle = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json={
            "method": "cash",
            "operation_id": f"refund-new-cycle-{order_id}",
        },
        headers=auth(ctx["token"]),
    )
    assert new_cycle.status_code == 200
    assert new_cycle.json()["refund_due_amount"] == 0
    assert new_cycle.json()["refunded_amount"] == 30000


def test_tien_ve_sau_huy_giu_unreconciled_den_khi_hoan_xong(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    assert _stock(ctx["product"]["id"]) == 9

    cancelled = client.post(
        f"/api/orders/{order_id}/cancel",
        headers=auth(ctx["token"]),
    )
    assert cancelled.status_code == 200
    assert _stock(ctx["product"]["id"]) == 10

    webhook = _goi_webhook(client, order_id, TOTAL, f"LATE-{order_id}")
    assert webhook.status_code == 200
    assert webhook.json()["unreconciled_order_ids"] == [order_id]
    late = _lay_don(client, ctx, order_id)
    assert late["status"] == "UNRECONCILED"
    assert late["reconciliation_reason"] == "LATE_PAYMENT"
    assert late["received_amount"] == TOTAL
    assert late["refund_due_amount"] == TOTAL
    assert late["refund_pending"] is True
    assert late["invoice_issued"] is False
    assert _stock(ctx["product"]["id"]) == 10

    assert client.post(
        f"/api/orders/{order_id}/pay",
        headers=auth(ctx["token"]),
    ).status_code == 409
    assert client.post(
        f"/api/orders/{order_id}/cash-topup",
        json={},
        headers=auth(ctx["token"]),
    ).status_code == 409

    stats = client.get(
        f"/api/shops/{ctx['shop_id']}/stats",
        headers=auth(ctx["token"]),
    ).json()
    assert stats["total_revenue"] == 0

    completed = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json={
            "method": "cash",
            "note": "Hoàn toàn bộ tiền về muộn",
            "operation_id": f"late-refund-operation-{order_id}",
        },
        headers=auth(ctx["token"]),
    )
    assert completed.status_code == 200, completed.text
    resolved = completed.json()
    assert resolved["status"] == "CANCELLED"
    assert resolved["refunded_amount"] == TOTAL
    assert resolved["refund_due_amount"] == 0
    assert resolved["refund_pending"] is False
    assert resolved["reconciliation_pending"] is False
    assert resolved["invoice_issued"] is False
    assert _stock(ctx["product"]["id"]) == 10
    assert [(p["entry_type"], p["amount"]) for p in _payments(order_id)] == [
        ("BANK_IN", TOTAL),
        ("REFUND_CASH", TOTAL),
    ]

    repeated = client.post(
        f"/api/orders/{order_id}/refund-complete",
        json={
            "method": "cash",
            "operation_id": f"late-refund-operation-{order_id}",
        },
        headers=auth(ctx["token"]),
    )
    assert repeated.status_code == 200
    assert len(_payments(order_id)) == 2
    assert len(_logs("REFUND_COMPLETE", order_id)) == 1


def test_staff_dung_shop_duoc_doi_soat_shop_khac_va_anonymous_bi_chan(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    _, other_token = new_seller(client)

    underpaid_id = _tao_don(client, ctx)
    _goi_webhook(
        client,
        underpaid_id,
        40000,
        f"AUTH-CASH-{underpaid_id}",
    )
    path = f"/api/orders/{underpaid_id}/cash-topup"
    assert client.post(path, json={}).status_code == 401
    assert client.post(
        path,
        json={},
        headers=auth(other_token),
    ).status_code == 403
    allowed = client.post(
        path,
        json={},
        headers=auth(staff_token),
    )
    assert allowed.status_code == 200
    assert allowed.json()["received_amount"] == TOTAL

    overpaid_id = _tao_don(client, ctx)
    _goi_webhook(
        client,
        overpaid_id,
        120000,
        f"AUTH-REFUND-{overpaid_id}",
    )
    refund_path = f"/api/orders/{overpaid_id}/refund-complete"
    assert client.post(
        refund_path,
        json={"method": "cash", "operation_id": f"auth-refund-{overpaid_id}"},
    ).status_code == 401
    assert client.post(
        refund_path,
        json={"method": "cash", "operation_id": f"auth-refund-{overpaid_id}"},
        headers=auth(other_token),
    ).status_code == 403
    assert client.post(
        refund_path,
        json={"method": "cash", "operation_id": f"auth-refund-{overpaid_id}"},
        headers=auth(staff_token),
    ).status_code == 200

    assert _dashboard(
        client,
        ctx,
        token=staff_token,
        reconciliation_only=True,
    ).status_code == 200
    assert _dashboard(
        client,
        ctx,
        token=other_token,
        reconciliation_only=True,
    ).status_code == 403


def test_dashboard_reconciliation_only_loc_dung_ba_nhom_dang_mo(
    client, webhook_secret
):
    ctx = seller_with_shop(client)

    pending_id = _tao_don(client, ctx)

    exact_id = _tao_don(client, ctx)
    _goi_webhook(client, exact_id, TOTAL, f"DASH-EXACT-{exact_id}")

    underpaid_id = _tao_don(client, ctx)
    _goi_webhook(client, underpaid_id, 40000, f"DASH-UNDER-{underpaid_id}")

    overpaid_open_id = _tao_don(client, ctx)
    _goi_webhook(
        client,
        overpaid_open_id,
        120000,
        f"DASH-OVER-OPEN-{overpaid_open_id}",
    )

    overpaid_done_id = _tao_don(client, ctx)
    _goi_webhook(
        client,
        overpaid_done_id,
        120000,
        f"DASH-OVER-DONE-{overpaid_done_id}",
    )
    client.post(
        f"/api/orders/{overpaid_done_id}/refund-complete",
        json={
            "method": "transfer",
            "operation_id": f"dash-over-refund-{overpaid_done_id}",
        },
        headers=auth(ctx["token"]),
    )

    late_open_id = _tao_don(client, ctx)
    client.post(
        f"/api/orders/{late_open_id}/cancel",
        headers=auth(ctx["token"]),
    )
    _goi_webhook(client, late_open_id, TOTAL, f"DASH-LATE-OPEN-{late_open_id}")

    late_done_id = _tao_don(client, ctx)
    client.post(
        f"/api/orders/{late_done_id}/cancel",
        headers=auth(ctx["token"]),
    )
    _goi_webhook(client, late_done_id, TOTAL, f"DASH-LATE-DONE-{late_done_id}")
    client.post(
        f"/api/orders/{late_done_id}/refund-complete",
        json={
            "method": "cash",
            "operation_id": f"dash-late-refund-{late_done_id}",
        },
        headers=auth(ctx["token"]),
    )

    default = _dashboard(client, ctx).json()
    assert default["total_orders"] == 7
    assert default["reconciliation_count"] == 3

    page1 = _dashboard(
        client,
        ctx,
        reconciliation_only=True,
        page=1,
        per_page=2,
    ).json()
    page2 = _dashboard(
        client,
        ctx,
        reconciliation_only=True,
        page=2,
        per_page=2,
    ).json()
    assert page1["total_orders"] == page2["total_orders"] == 3
    assert page1["reconciliation_count"] == page2["reconciliation_count"] == 3
    assert page1["has_more"] is True
    assert page2["has_more"] is False

    rows = page1["orders"] + page2["orders"]
    assert {row["id"] for row in rows} == {
        underpaid_id,
        overpaid_open_id,
        late_open_id,
    }
    assert all(
        set(row.keys())
        == {"id", "total", "status", "date"} | PAYMENT_SUMMARY_KEYS
        for row in rows
    )
    reason_by_id = {row["id"]: row["reconciliation_reason"] for row in rows}
    assert reason_by_id == {
        underpaid_id: "UNDERPAID",
        overpaid_open_id: "OVERPAID",
        late_open_id: "LATE_PAYMENT",
    }
    assert {
        pending_id,
        exact_id,
        overpaid_done_id,
        late_done_id,
    }.isdisjoint({row["id"] for row in rows})


def test_pay_chi_danh_cho_tien_mat_khong_giai_quyet_transfer(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    transfer_id = _tao_don(client, ctx)
    assert client.post(
        f"/api/orders/{transfer_id}/pay",
        headers=auth(ctx["token"]),
    ).status_code == 409

    _goi_webhook(
        client,
        transfer_id,
        40000,
        f"NO-MANUAL-{transfer_id}",
    )
    assert client.post(
        f"/api/orders/{transfer_id}/pay",
        headers=auth(ctx["token"]),
    ).status_code == 409
    assert _lay_don(client, ctx, transfer_id)["status"] == "UNRECONCILED"

    cash_id = _tao_don(client, ctx, payment_method="cash")
    paid = client.post(
        f"/api/orders/{cash_id}/pay",
        headers=auth(ctx["token"]),
    )
    assert paid.status_code == 200
    assert _lay_don(client, ctx, cash_id)["status"] == "PAID"


def test_unique_index_idempotency_ton_tai(client, db):
    indexes = {
        row[1]: row[2]
        for row in db.execute(text("PRAGMA index_list(order_payments)"))
    }
    assert indexes["ux_order_payments_idempotency_key"] == 1
    assert "ux_order_payments_idempotency_key" not in (
        bootstrap.verify_required_indexes(db)
    )


def test_backfill_legacy_chay_lap_va_chan_retry_ma_cu(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    order_id = _tao_don(client, ctx)
    session = SessionLocal()
    try:
        order = session.query(models.Order).filter(models.Order.id == order_id).one()
        order.status = "PAID"
        order.paid_amount = TOTAL
        order.bank_txn_id = f"LEGACY-{order_id}"
        session.commit()

        assert bootstrap.backfill_legacy_order_payments(session) == 1
        assert bootstrap.backfill_legacy_order_payments(session) == 0
    finally:
        session.close()

    _goi_webhook(client, order_id, 10000, f"NEW-AFTER-LEGACY-{order_id}")
    before_retry = _lay_don(client, ctx, order_id)
    assert before_retry["received_amount"] == 110000
    assert len(_payments(order_id)) == 2

    retry_old = _goi_webhook(client, order_id, TOTAL, f"LEGACY-{order_id}")
    assert retry_old.status_code == 200
    assert _lay_don(client, ctx, order_id)["received_amount"] == 110000
    assert len(_payments(order_id)) == 2
