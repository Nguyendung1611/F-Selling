"""D1: webhook phải đối chiếu SỐ TIỀN, không chỉ mã đơn.

Bản trước chỉ rút mã ORDERxxx rồi đánh dấu PAID, nên khách chuyển thiếu vẫn
được giao hàng, và một giao dịch tiền RA mang nội dung 'ORDER42' cũng đánh dấu
đơn 42 là đã thanh toán.
"""
from __future__ import annotations

import pytest
from conftest import auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.services import payment_service

SECRET = "webhook-secret-test"
TONG_TIEN = 100000


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _tao_don(client):
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": TONG_TIEN, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    return ctx, order_id


def _goi(client, payload):
    return client.post(
        "/api/orders/webhook", json=payload, headers={"X-Webhook-Secret": SECRET}
    )


def _trang_thai(client, ctx, order_id):
    return client.get(f"/api/orders/{order_id}", headers=auth(ctx["token"])).json()["status"]


def _don(order_id):
    s = SessionLocal()
    try:
        o = s.query(models.Order).filter(models.Order.id == order_id).first()
        return {"paid_amount": o.paid_amount, "bank_txn_id": o.bank_txn_id} if o else None
    finally:
        s.close()


def _financial_snapshot(order_id):
    """Ảnh chụp mọi side effect tiền/kho gắn với một đơn."""
    s = SessionLocal()
    try:
        o = s.query(models.Order).filter(models.Order.id == order_id).one()
        product_ids = [
            product_id
            for (product_id,) in s.query(models.OrderItem.product_id)
            .filter(models.OrderItem.order_id == order_id)
            .all()
            if product_id is not None
        ]
        return {
            "order": {
                "status": o.status,
                "paid_amount": o.paid_amount,
                "cash_paid_amount": o.cash_paid_amount,
                "bank_txn_id": o.bank_txn_id,
                "reconciliation_reason": o.reconciliation_reason,
                "refunded_amount": o.refunded_amount,
                "refund_due_amount": o.refund_due_amount,
                "refund_completed_at": o.refund_completed_at,
                "refund_completed_by": o.refund_completed_by,
                "refund_method": o.refund_method,
                "refund_note": o.refund_note,
                "refund_reference": o.refund_reference,
                "loyalty_points_earned": o.loyalty_points_earned,
                "loyalty_awarded_at": o.loyalty_awarded_at,
            },
            "payments": [
                (
                    p.entry_type,
                    p.amount,
                    p.idempotency_key,
                    p.bank_txn_id,
                    p.account_no,
                    p.shift_id,
                )
                for p in s.query(models.OrderPayment)
                .filter(models.OrderPayment.order_id == order_id)
                .order_by(models.OrderPayment.id)
                .all()
            ],
            "loyalty": [
                (e.entry_type, e.points_delta, e.idempotency_key)
                for e in s.query(models.LoyaltyPointEntry)
                .filter(models.LoyaltyPointEntry.order_id == order_id)
                .order_by(models.LoyaltyPointEntry.id)
                .all()
            ],
            "stocks": [
                (p.id, p.stock)
                for p in s.query(models.Product)
                .filter(models.Product.id.in_(product_ids))
                .order_by(models.Product.id)
                .all()
            ],
            "cash_movements": s.query(models.CashMovement).count(),
        }
    finally:
        s.close()


def _logs(action, order_id):
    s = SessionLocal()
    try:
        return (
            s.query(models.SystemLog)
            .filter(
                models.SystemLog.action == action,
                models.SystemLog.details.like(f"%Order {order_id}%"),
            )
            .all()
        )
    finally:
        s.close()


# ---------- Tiền ra ----------


def test_giao_dich_tien_ra_bi_tu_choi(client, webhook_secret):
    """Shop hoàn tiền với nội dung 'hoan ORDER42' không được đánh dấu đơn đã trả."""
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"hoan tien ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "transferType": "out",
    })
    assert res.status_code == 200, res.text
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"
    assert len(_logs("WEBHOOK_TU_CHOI", order_id)) == 1


def test_so_tien_am_coi_la_tien_ra(client, webhook_secret):
    """Casso không có transferType, tiền ra thể hiện bằng số tiền âm."""
    ctx, order_id = _tao_don(client)
    res = _goi(client, {"data": [{"description": f"ORDER{order_id}", "amount": -TONG_TIEN}]})
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"


# ---------- Thiếu số tiền trong payload ----------


def test_khong_co_so_tien_thi_khong_cho_paid(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {"order_id": order_id})
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == []
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_tu_choi_van_tra_200_de_ngan_hang_khong_retry_vo_han(client, webhook_secret):
    _, order_id = _tao_don(client)
    assert _goi(client, {"order_id": order_id}).status_code == 200


# ---------- Chuyển thiếu ----------


def test_chuyen_thieu_thi_can_doi_soat(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": 10000, "transferType": "in"
    })
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == []
    assert res.json()["unreconciled_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "UNRECONCILED"


def test_chuyen_thieu_van_ghi_lai_so_tien_da_nhan(client, webhook_secret):
    """Tiền đã vào tài khoản shop nên phải để lại dấu vết, không được bỏ qua."""
    _, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": 10000, "id": "TXN-THIEU"})
    assert _don(order_id) == {"paid_amount": 10000, "bank_txn_id": "TXN-THIEU"}

    log = _logs("WEBHOOK_THIEU_TIEN", order_id)
    assert len(log) == 1
    assert "thiếu" in log[0].details


def test_thieu_mot_dong_van_bi_chan(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN - 1})
    assert _trang_thai(client, ctx, order_id) == "UNRECONCILED"


# ---------- Đủ và thừa ----------


def test_dung_so_tien_thi_paid(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": TONG_TIEN,
        "transferType": "in", "id": "TXN-DU",
    })
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PAID"
    assert _don(order_id) == {"paid_amount": TONG_TIEN, "bank_txn_id": "TXN-DU"}


def test_chuyen_thua_van_paid_va_ghi_log_so_du(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN + 50000})
    assert _trang_thai(client, ctx, order_id) == "PAID"

    log = _logs("WEBHOOK_PAYMENT", order_id)
    assert len(log) == 1
    assert "DƯ" in log[0].details


# ---------- Trả trùng ----------


def test_tra_hai_lan_bang_hai_giao_dich_khac_nhau_thi_ghi_log(client, webhook_secret):
    """Máy trạng thái chặn xử lý lại, nhưng shop đã nhận dư tiền thật."""
    ctx, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN, "id": "TXN-1"})
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN, "id": "TXN-2"})

    assert _trang_thai(client, ctx, order_id) == "PAID"
    log = _logs("WEBHOOK_TRA_TRUNG", order_id)
    assert len(log) == 1
    assert "TXN-2" in log[0].details


def test_cung_mot_giao_dich_gui_lai_khong_bao_tra_trung(client, webhook_secret):
    """Ngân hàng gửi lại đúng giao dịch cũ là chuyện bình thường."""
    _, order_id = _tao_don(client)
    payload = {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN, "id": "TXN-SAME"}
    _goi(client, payload)
    _goi(client, payload)
    assert _logs("WEBHOOK_TRA_TRUNG", order_id) == []


# ---------- Sai tài khoản: từ chối trước mọi side effect ----------


def test_sai_tai_khoan_pending_bi_tu_choi_khong_co_side_effect(
    client, webhook_secret
):
    ctx, order_id = _tao_don(client)
    before = _financial_snapshot(order_id)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": TONG_TIEN,
        "accountNumber": "9999999999", "id": "ACCOUNT-MISMATCH-PENDING",
    })
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == []
    assert res.json()["unreconciled_order_ids"] == []
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"
    assert _financial_snapshot(order_id) == before

    logs = _logs("WEBHOOK_TU_CHOI", order_id)
    assert len(logs) == 1
    assert "ACCOUNT_MISMATCH" in logs[0].details
    human_details = logs[0].details.split("(event", 1)[0]
    assert "9999999999" not in human_details
    assert "0123456789" not in human_details


def test_account_shop_b_khong_duoc_ap_vao_order_shop_a(client, webhook_secret):
    ctx_a, order_id = _tao_don(client)
    ctx_b = seller_with_shop(client)

    s = SessionLocal()
    try:
        shop_b = s.query(models.Shop).filter(models.Shop.id == ctx_b["shop_id"]).one()
        shop_b.bank_account_no = "9876543210"
        s.commit()
    finally:
        s.close()

    before_order = _financial_snapshot(order_id)
    res = _goi(client, {
        "content": f"ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "accountNumber": "9876543210",
        "id": "CROSS-SHOP-ACCOUNT",
    })

    assert res.status_code == 200, res.text
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _financial_snapshot(order_id) == before_order

    s = SessionLocal()
    try:
        product_b = (
            s.query(models.Product)
            .filter(models.Product.id == ctx_b["product"]["id"])
            .one()
        )
        assert product_b.stock == 10
        assert (
            s.query(models.OrderPayment)
            .join(models.Order)
            .filter(models.Order.shop_id == ctx_b["shop_id"])
            .count()
            == 0
        )
    finally:
        s.close()


def test_sai_tai_khoan_debt_khong_tao_bank_unapplied_va_cong_no_khong_doi(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    customer = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": "Khach no sai account", "phone": "0901234567"},
        headers=auth(ctx["token"]),
    ).json()
    created = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{
                "product_id": ctx["product"]["id"],
                "price": TONG_TIEN,
                "quantity": 1,
            }],
            "payment_method": "debt",
            "customer_id": customer["id"],
        },
        headers=auth(ctx["token"]),
    )
    assert created.status_code == 200, created.text
    order_id = created.json()["order_id"]
    before = _financial_snapshot(order_id)
    receivable_before = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    ).json()["receivable_amount"]

    res = _goi(client, {
        "content": f"ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "accountNumber": "9999999999",
        "id": "ACCOUNT-MISMATCH-DEBT",
    })

    assert res.status_code == 200, res.text
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _financial_snapshot(order_id) == before
    assert client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    ).json()["receivable_amount"] == receivable_before


@pytest.mark.parametrize("state", ["CANCELLED", "UNRECONCILED", "PAID"])
def test_sai_tai_khoan_khong_dung_trang_thai_doi_soat_hien_tai(
    client, webhook_secret, state
):
    ctx, order_id = _tao_don(client)
    if state == "CANCELLED":
        cancelled = client.post(
            f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"])
        )
        assert cancelled.status_code == 200, cancelled.text
    elif state == "UNRECONCILED":
        underpaid = _goi(client, {
            "content": f"ORDER{order_id}",
            "transferAmount": 40_000,
            "accountNumber": "0123456789",
            "id": f"SETUP-UNDERPAID-{order_id}",
        })
        assert underpaid.json()["unreconciled_order_ids"] == [order_id]
    else:
        paid = _goi(client, {
            "content": f"ORDER{order_id}",
            "transferAmount": TONG_TIEN,
            "accountNumber": "0123456789",
            "id": f"SETUP-PAID-{order_id}",
        })
        assert paid.json()["order_ids"] == [order_id]

    assert _trang_thai(client, ctx, order_id) == state
    before = _financial_snapshot(order_id)
    res = _goi(client, {
        "content": f"ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "accountNumber": "9999999999",
        "id": f"ACCOUNT-MISMATCH-{state}-{order_id}",
    })

    assert res.status_code == 200, res.text
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _financial_snapshot(order_id) == before


def test_tai_khoan_khop_khi_chi_khac_so_0_dau_van_duoc_xu_ly(
    client, webhook_secret
):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "accountNumber": "000123456789",
        "id": "LEADING-ZERO-MATCH",
    })
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_payload_khong_co_account_giu_hanh_vi_tuong_thich(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "id": "MISSING-ACCOUNT-COMPAT",
    })
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_batch_mixed_account_dung_van_ap_account_sai_bi_tu_choi(
    client, webhook_secret
):
    ctx, correct_order_id = _tao_don(client)
    second = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{
                "product_id": ctx["product"]["id"],
                "price": TONG_TIEN,
                "quantity": 1,
            }]
        },
        headers=auth(ctx["token"]),
    )
    assert second.status_code == 200, second.text
    rejected_order_id = second.json()["order_id"]
    rejected_before = _financial_snapshot(rejected_order_id)

    res = _goi(client, {"data": [
        {
            "description": f"ORDER{correct_order_id}",
            "amount": TONG_TIEN,
            "accountNumber": "0123456789",
            "tid": "BATCH-CORRECT",
        },
        {
            "description": f"ORDER{rejected_order_id}",
            "amount": TONG_TIEN,
            "accountNumber": "9999999999",
            "tid": "BATCH-MISMATCH",
        },
    ]})

    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == [correct_order_id]
    assert res.json()["rejected_order_ids"] == [rejected_order_id]
    assert _trang_thai(client, ctx, correct_order_id) == "PAID"
    assert _financial_snapshot(rejected_order_id) == rejected_before


def test_retry_sai_tai_khoan_chi_ghi_mot_system_log(client, webhook_secret):
    _, order_id = _tao_don(client)
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "accountNumber": "9999999999",
        "id": "ACCOUNT-MISMATCH-RETRY",
    }

    for _ in range(3):
        res = _goi(client, payload)
        assert res.status_code == 200, res.text
        assert res.json()["rejected_order_ids"] == [order_id]

    logs = _logs("WEBHOOK_TU_CHOI", order_id)
    assert len(logs) == 1
    assert "ACCOUNT_MISMATCH" in logs[0].details


def test_tai_khoan_khop_thi_duoc_xu_ly(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": TONG_TIEN,
        "accountNumber": "0123456789",     # khớp SHOP_PAYLOAD trong conftest
    })
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == [order_id]
    assert res.json()["rejected_order_ids"] == []
    assert _trang_thai(client, ctx, order_id) == "PAID"


# ---------- Bộ phân tích payload ----------


def test_extract_transactions_sepay():
    gd = payment_service.extract_transactions({
        "content": "CK ORDER42", "transferAmount": 150000,
        "transferType": "in", "id": 777, "accountNumber": "0011",
    })
    assert len(gd) == 1
    assert (gd[0].order_id, gd[0].amount, gd[0].direction) == (42, 150000, "in")
    assert (gd[0].txn_id, gd[0].account_no) == ("777", "0011")


def test_extract_transactions_casso_nhieu_giao_dich():
    gd = payment_service.extract_transactions({"data": [
        {"description": "ORDER1", "amount": 1000, "tid": "A"},
        {"description": "ORDER2", "amount": 2000, "tid": "B"},
    ]})
    assert [(g.order_id, g.amount, g.txn_id) for g in gd] == [(1, 1000, "A"), (2, 2000, "B")]


def test_extract_transactions_payos_lay_ordercode():
    gd = payment_service.extract_transactions(
        {"data": {"orderCode": 9, "description": "", "amount": 5000, "reference": "R9"}}
    )
    assert (gd[0].order_id, gd[0].amount, gd[0].txn_id) == (9, 5000, "R9")


def test_so_tien_bang_0_khac_voi_khong_co_so_tien():
    """0 là một số tiền thật (và sai); thiếu trường mới là None."""
    co_0 = payment_service.extract_transactions({"content": "ORDER5", "transferAmount": 0})
    khong_co = payment_service.extract_transactions({"order_id": 5})
    assert co_0[0].amount == 0
    assert khong_co[0].amount is None


def test_fallback_khong_co_so_tien():
    gd = payment_service.extract_transactions({"note": "thanh toan ORDER77"})
    assert gd[0].order_id == 77
    assert gd[0].amount is None
