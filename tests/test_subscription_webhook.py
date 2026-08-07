"""Webhook gói cước: parser SUB, xác thực và cách ly khỏi ORDER."""
from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from fselling import models
from fselling.routers import webhooks
from fselling.services import payment_service, subscription_service


SECRET = "subscription-webhook-secret-test"
SUB_CODE = "SUBA1B2C3D4E5F6"
PLATFORM_ACCOUNT = "00123456789"


@pytest.fixture
def subscription_secret(monkeypatch):
    monkeypatch.setattr(
        webhooks, "get_subscription_webhook_secret", lambda: SECRET
    )
    return SECRET


def _post(client, payload=None, *, secret=SECRET, content=None):
    headers = {"X-Webhook-Secret": secret}
    if content is not None:
        return client.post(
            "/api/subscriptions/webhook", content=content, headers=headers
        )
    return client.post(
        "/api/subscriptions/webhook", json=payload, headers=headers
    )


def _configure_platform_bank(monkeypatch, *, account_no=PLATFORM_ACCOUNT):
    monkeypatch.setenv("SUBSCRIPTION_BANK_CODE", "MB")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NO", account_no)
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NAME", "F SELLING")


def _create_expired_trial_checkout(
    db,
    *,
    now: datetime.datetime,
    created_at: datetime.datetime | None = None,
    expires_at: datetime.datetime | None = None,
):
    """Tạo shop đã hết trial và một checkout chưa trả, chỉ dùng DB test."""
    suffix = uuid.uuid4().hex[:12].upper()
    owner = models.User(
        username=f"subscription_owner_{suffix}",
        hashed_password="not-used-in-this-test",
        role="SELLER",
        email=f"subscription_{suffix}@example.com",
        is_verified=True,
        is_active=True,
    )
    db.add(owner)
    db.flush()
    shop = models.Shop(
        name=f"Shop subscription {suffix}",
        owner_id=owner.id,
        bank_code="VCB",
        bank_account_no="SHOP-ACCOUNT-NOT-PLATFORM",
        bank_account_name="SHOP OWNER",
        is_active=True,
    )
    db.add(shop)
    db.flush()
    db.add(
        models.ShopSubscription(
            shop_id=shop.id,
            trial_started_at=now - datetime.timedelta(days=31),
            trial_ends_at=now - datetime.timedelta(days=1),
            updated_at=now,
        )
    )
    reference_code = "SUB" + suffix
    checkout = models.SubscriptionCheckout(
        shop_id=shop.id,
        reference_code=reference_code,
        cycle="MONTHLY",
        amount_due_vnd=99000,
        duration_days=30,
        status="PENDING",
        received_amount_vnd=0,
        refund_due_amount_vnd=0,
        operation_id=f"checkout-{suffix}",
        operation_fingerprint="a" * 64,
        created_by_user_id=owner.id,
        created_at=created_at or now,
        expires_at=expires_at or now + datetime.timedelta(hours=24),
    )
    db.add(checkout)
    db.commit()
    return {
        "shop_id": shop.id,
        "checkout_id": checkout.id,
        "reference_code": reference_code,
    }


def _order_ledger_counts(db):
    return (
        db.query(models.Order).count(),
        db.query(models.OrderPayment).count(),
    )


# ---------- Parser SUB riêng, không làm đổi parser ORDER ----------


def test_parser_sub_sepay_giu_du_metadata():
    transactions = payment_service.extract_subscription_transactions(
        {
            "content": f"Thanh toan {SUB_CODE}",
            "transferAmount": 99000,
            "transferType": "in",
            "id": 777,
            "accountNumber": "001234",
        }
    )

    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction.reference_code == SUB_CODE
    assert (transaction.amount, transaction.direction) == (99000, "in")
    assert (transaction.txn_id, transaction.account_no) == ("777", "001234")
    assert transaction.provider == "sepay"
    assert len(transaction.payload_fingerprint) == 64


def test_parser_sub_batch_giu_tien_vao_khong_co_ma_de_doi_soat():
    transactions = payment_service.extract_subscription_transactions(
        {
            "data": [
                {
                    "description": SUB_CODE.lower(),
                    "amount": 50000,
                    "tid": "TXN-CO-MA",
                },
                {
                    "description": "khach quen ghi noi dung",
                    "amount": 49000,
                    "tid": "TXN-KHONG-MA",
                },
            ]
        }
    )

    assert [item.reference_code for item in transactions] == [SUB_CODE, None]
    assert [item.amount for item in transactions] == [50000, 49000]
    assert [item.txn_id for item in transactions] == [
        "TXN-CO-MA",
        "TXN-KHONG-MA",
    ]


def test_parser_sub_khong_coi_payos_ordercode_so_tran_la_ma_sub():
    transactions = payment_service.extract_subscription_transactions(
        {"data": {"orderCode": 42, "description": "", "amount": 99000}}
    )

    assert len(transactions) == 1
    assert transactions[0].reference_code is None
    assert transactions[0].amount == 99000
    assert transactions[0].provider == "payos"


def test_parser_sub_khong_nhan_order_va_parser_order_van_y_nghia_cu():
    payload = {
        "content": "ORDER42",
        "transferAmount": 99000,
        "id": "TXN-ORDER",
    }

    subscription_transactions = payment_service.extract_subscription_transactions(
        payload
    )
    order_transactions = payment_service.extract_transactions(payload)

    assert len(subscription_transactions) == 1
    assert subscription_transactions[0].reference_code is None
    assert [(item.order_id, item.amount) for item in order_transactions] == [
        (42, 99000)
    ]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("suba1b2c3d4e5f6", SUB_CODE),
        ("SUBA1B2C3D4E5", None),       # 11 ký tự
        ("SUBA1B2C3D4E5F67", None),   # 13 ký tự
        ("XSUBA1B2C3D4E5F6", None),   # dính tiền tố chữ/số khác
    ],
)
def test_parser_sub_chi_nhan_dung_12_chu_so(text, expected):
    result = payment_service.extract_subscription_transactions(
        {"content": text, "transferAmount": 99000}
    )
    assert result[0].reference_code == expected


def test_parser_sub_phan_biet_0_none_va_tien_ra():
    zero = payment_service.extract_subscription_transactions(
        {"content": SUB_CODE, "transferAmount": 0}
    )[0]
    missing = payment_service.extract_subscription_transactions(
        {"content": SUB_CODE}
    )[0]
    outgoing = payment_service.extract_subscription_transactions(
        {"content": SUB_CODE, "transferAmount": -99000}
    )[0]

    assert zero.amount == 0
    assert missing.amount is None
    assert (outgoing.amount, outgoing.direction) == (99000, "out")


def test_khoa_idempotency_sub_co_namespace_rieng_va_on_dinh():
    transaction = SimpleNamespace(
        provider="SePay",
        account_no="001234",
        txn_id="TXN-1",
        payload_fingerprint="khong-dung-khi-co-txn",
    )

    first = payment_service.bank_idempotency_key(
        transaction, namespace="sub-bank"
    )
    second = payment_service.bank_idempotency_key(
        transaction, fallback_account="999", namespace="sub-bank"
    )
    order_namespace = payment_service.bank_idempotency_key(transaction)

    assert first == second
    assert first.startswith("sub-bank:")
    assert order_namespace.startswith("bank:")
    assert first.split(":", 1)[1] == order_namespace.split(":", 1)[1]


def test_secret_sub_doc_dong_tu_bien_moi_truong(monkeypatch):
    monkeypatch.delenv("SUBSCRIPTION_WEBHOOK_SECRET", raising=False)
    assert payment_service.get_subscription_webhook_secret() == ""

    monkeypatch.setenv("SUBSCRIPTION_WEBHOOK_SECRET", "secret-moi")
    assert payment_service.get_subscription_webhook_secret() == "secret-moi"


# ---------- Router: fail-closed trước auth, HTTP 200 sau auth ----------


def test_webhook_sub_thieu_secret_fail_closed(client, monkeypatch):
    monkeypatch.setattr(
        webhooks, "get_subscription_webhook_secret", lambda: ""
    )
    monkeypatch.setattr(
        webhooks,
        "_apply_subscription_webhook_payment",
        lambda *_: pytest.fail("Không được gọi service khi thiếu secret"),
    )

    response = client.post(
        "/api/subscriptions/webhook", json={"content": SUB_CODE}
    )
    assert response.status_code == 503


def test_webhook_sub_sai_secret_bi_tu_choi(client, subscription_secret, monkeypatch):
    monkeypatch.setattr(
        webhooks,
        "_apply_subscription_webhook_payment",
        lambda *_: pytest.fail("Không được gọi service khi sai secret"),
    )

    response = _post(client, {"content": SUB_CODE}, secret="sai-secret")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Webhook-Secret": SECRET},
        {"Authorization": f"Bearer {SECRET}"},
        {"Authorization": f"Apikey {SECRET}"},
    ],
)
def test_webhook_sub_nhan_cac_kieu_header_secret(
    client, subscription_secret, monkeypatch, headers
):
    monkeypatch.setattr(
        webhooks,
        "_apply_subscription_webhook_payment",
        lambda _db, payload: {"status": "received", "payload": payload},
    )

    response = client.post(
        "/api/subscriptions/webhook",
        json={"content": SUB_CODE},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "received"


def test_webhook_sub_json_hong_sau_secret_dung_van_tra_200(
    client, subscription_secret, monkeypatch
):
    seen = []

    def fake_apply(_db, payload):
        seen.append(payload)
        return {"status": "rejected", "reason": "invalid_json"}

    monkeypatch.setattr(
        webhooks, "_apply_subscription_webhook_payment", fake_apply
    )

    response = _post(client, content=b"khong-phai-json")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert seen == [{}]


def test_webhook_sub_json_khong_phai_object_van_tra_200(
    client, subscription_secret, monkeypatch
):
    seen = []

    def fake_apply(_db, payload):
        seen.append(payload)
        return {"status": "rejected", "reason": "invalid_shape"}

    monkeypatch.setattr(
        webhooks, "_apply_subscription_webhook_payment", fake_apply
    )

    response = client.post(
        "/api/subscriptions/webhook",
        json=[{"content": SUB_CODE}],
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 200
    assert seen == [{}]


def test_webhook_sub_tu_choi_nghiep_vu_van_tra_200(
    client, subscription_secret, monkeypatch
):
    def reject(_db, _payload):
        raise HTTPException(status_code=404, detail="Mã SUB không tồn tại")

    monkeypatch.setattr(
        webhooks, "_apply_subscription_webhook_payment", reject
    )

    response = _post(client, {"content": SUB_CODE, "transferAmount": 99000})
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_webhook_sub_loi_server_that_van_tra_5xx_de_ngan_hang_retry(
    client, subscription_secret, monkeypatch
):
    def fail(_db, _payload):
        raise HTTPException(status_code=503, detail="database unavailable")

    monkeypatch.setattr(
        webhooks, "_apply_subscription_webhook_payment", fail
    )

    response = _post(client, {"content": SUB_CODE, "transferAmount": 99000})
    assert response.status_code == 503


def test_webhook_sub_thieu_tai_khoan_nen_tang_thi_fail_closed(
    client, subscription_secret, monkeypatch
):
    monkeypatch.delenv("SUBSCRIPTION_BANK_CODE", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_BANK_ACCOUNT_NO", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_BANK_ACCOUNT_NAME", raising=False)

    response = _post(
        client,
        {"content": SUB_CODE, "transferAmount": 99000, "transferType": "in"},
    )
    assert response.status_code == 503


def test_webhook_sub_khong_ghi_raw_payload_vao_file_log(
    client, subscription_secret, monkeypatch
):
    messages = []
    private_content = f"noi dung rieng {SUB_CODE} dien thoai 0900000000"
    monkeypatch.setattr(webhooks, "log_to_file", messages.append)
    monkeypatch.setattr(
        webhooks,
        "_apply_subscription_webhook_payment",
        lambda _db, _payload: {"status": "received"},
    )

    response = _post(
        client, {"content": private_content, "transferAmount": 99000}
    )

    assert response.status_code == 200
    assert messages
    assert private_content not in "\n".join(messages)
    assert SUB_CODE not in "\n".join(messages)


def test_route_sub_khong_goi_order_service(
    client, subscription_secret, monkeypatch
):
    monkeypatch.setattr(
        webhooks.order_service,
        "apply_webhook_payment",
        lambda *_: pytest.fail("Webhook SUB không được gọi order_service"),
    )
    monkeypatch.setattr(
        webhooks,
        "_apply_subscription_webhook_payment",
        lambda _db, _payload: {"status": "rejected"},
    )

    response = _post(
        client, {"content": "ORDER42", "transferAmount": 99000}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_route_order_khong_goi_subscription_service(client, monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: "order-secret")
    monkeypatch.setattr(
        webhooks,
        "_apply_subscription_webhook_payment",
        lambda *_: pytest.fail("Webhook ORDER không được gọi subscription service"),
    )
    monkeypatch.setattr(
        webhooks.order_service,
        "apply_webhook_payment",
        lambda _db, _payload: {
            "paid": [42],
            "unreconciled": [],
            "rejected": [],
        },
    )

    response = client.post(
        "/api/orders/webhook",
        json={"content": "ORDER42", "transferAmount": 99000},
        headers={"X-Webhook-Secret": "order-secret"},
    )
    assert response.status_code == 200
    assert response.json()["order_ids"] == [42]


def test_webhook_sub_exact_payment_tao_ledger_va_khong_dung_order(
    client, db, subscription_secret, monkeypatch
):
    """Đi xuyên router + service thật: tiền gói chỉ vào ledger thuê bao."""
    suffix = uuid.uuid4().hex[:12].upper()
    reference_code = "SUB" + suffix
    now = datetime.datetime.utcnow()

    owner = models.User(
        username=f"subscription_owner_{suffix}",
        hashed_password="not-used-in-this-test",
        role="SELLER",
        email=f"subscription_{suffix}@example.com",
        is_verified=True,
        is_active=True,
    )
    db.add(owner)
    db.flush()
    shop = models.Shop(
        name=f"Shop subscription {suffix}",
        owner_id=owner.id,
        bank_code="VCB",
        bank_account_no="SHOP-ACCOUNT-NOT-PLATFORM",
        bank_account_name="SHOP OWNER",
        is_active=True,
    )
    db.add(shop)
    db.flush()
    db.add(
        models.ShopSubscription(
            shop_id=shop.id,
            trial_started_at=now - datetime.timedelta(days=31),
            trial_ends_at=now - datetime.timedelta(days=1),
            updated_at=now,
        )
    )
    checkout = models.SubscriptionCheckout(
        shop_id=shop.id,
        reference_code=reference_code,
        cycle="MONTHLY",
        amount_due_vnd=99000,
        duration_days=30,
        status="PENDING",
        received_amount_vnd=0,
        refund_due_amount_vnd=0,
        operation_id=f"checkout-{suffix}",
        operation_fingerprint="a" * 64,
        created_by_user_id=owner.id,
        created_at=now,
        expires_at=now + datetime.timedelta(hours=24),
    )
    db.add(checkout)
    db.commit()
    shop_id = shop.id
    checkout_id = checkout.id

    orders_before = db.query(models.Order).count()
    order_payments_before = db.query(models.OrderPayment).count()
    monkeypatch.setenv("SUBSCRIPTION_BANK_CODE", "MB")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NO", "00123456789")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NAME", "F SELLING")

    response = _post(
        client,
        {
            "content": reference_code,
            "transferAmount": 99000,
            "transferType": "in",
            "id": f"TXN-{suffix}",
            "accountNumber": "00123456789",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["activated_shop_ids"] == [shop_id]
    db.expire_all()
    saved_checkout = (
        db.query(models.SubscriptionCheckout)
        .filter(models.SubscriptionCheckout.id == checkout_id)
        .one()
    )
    payment = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.checkout_id == checkout_id)
        .one()
    )
    subscription = (
        db.query(models.ShopSubscription)
        .filter(models.ShopSubscription.shop_id == shop_id)
        .one()
    )
    assert saved_checkout.status == "PAID"
    assert saved_checkout.received_amount_vnd == 99000
    assert saved_checkout.activated_at is not None
    assert payment.amount_vnd == 99000
    assert payment.needs_review is False
    assert payment.idempotency_key.startswith("sub-bank:")
    assert subscription.paid_until is not None
    assert db.query(models.Order).count() == orders_before
    assert db.query(models.OrderPayment).count() == order_payments_before


def test_webhook_sub_tien_vao_khong_ma_duoc_ghi_unapplied(
    client, db, subscription_secret, monkeypatch
):
    """Tiền thật không mã phải nổi lên Admin, không được biến mất trong log."""
    txn_id = f"TXN-NO-SUB-{uuid.uuid4().hex[:12].upper()}"
    monkeypatch.setenv("SUBSCRIPTION_BANK_CODE", "MB")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NO", "00123456789")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NAME", "F SELLING")

    response = _post(
        client,
        {
            "content": "khach chuyen tien nhung quen ma",
            "transferAmount": 12345,
            "transferType": "in",
            "id": txn_id,
            "accountNumber": "00123456789",
        },
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["review_payment_ids"]) == 1
    db.expire_all()
    payment = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.bank_txn_id == txn_id)
        .one()
    )
    assert payment.checkout_id is None
    assert payment.shop_id is None
    assert payment.reference_code is None
    assert payment.amount_vnd == 12345
    assert payment.needs_review is True
    assert payment.review_reason == "NO_REFERENCE"


def test_webhook_sub_sai_tai_khoan_ghi_review_khong_cap_pro_khong_dung_order(
    client, db, subscription_secret, monkeypatch
):
    now = datetime.datetime(2026, 8, 7, 2, 0, 0)
    ctx = _create_expired_trial_checkout(db, now=now)
    _configure_platform_bank(monkeypatch)
    before_orders = _order_ledger_counts(db)
    txn_id = f"TXN-WRONG-ACCOUNT-{uuid.uuid4().hex[:12].upper()}"

    response = _post(
        client,
        {
            "content": ctx["reference_code"],
            "transferAmount": 99000,
            "transferType": "in",
            "id": txn_id,
            "accountNumber": "99999999999",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activated_shop_ids"] == []
    assert len(body["review_payment_ids"]) == 1
    db.expire_all()
    payment = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.bank_txn_id == txn_id)
        .one()
    )
    checkout = db.query(models.SubscriptionCheckout).get(ctx["checkout_id"])
    subscription = db.query(models.ShopSubscription).get(ctx["shop_id"])
    assert payment.checkout_id == ctx["checkout_id"]
    assert payment.shop_id == ctx["shop_id"]
    assert payment.needs_review is True
    assert payment.review_reason == "ACCOUNT_MISMATCH"
    assert (checkout.status, checkout.received_amount_vnd) == ("PENDING", 0)
    assert subscription.paid_until is None
    assert _order_ledger_counts(db) == before_orders


def test_webhook_sub_ma_khong_ton_tai_ghi_review_khong_cap_pro_khong_dung_order(
    client, db, subscription_secret, monkeypatch
):
    now = datetime.datetime(2026, 8, 7, 2, 0, 0)
    ctx = _create_expired_trial_checkout(db, now=now)
    _configure_platform_bank(monkeypatch)
    before_orders = _order_ledger_counts(db)
    unknown_reference = "SUB" + uuid.uuid4().hex[:12].upper()
    txn_id = f"TXN-UNKNOWN-{uuid.uuid4().hex[:12].upper()}"

    response = _post(
        client,
        {
            "content": unknown_reference,
            "transferAmount": 99000,
            "transferType": "in",
            "id": txn_id,
            "accountNumber": PLATFORM_ACCOUNT,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activated_shop_ids"] == []
    assert len(body["review_payment_ids"]) == 1
    db.expire_all()
    payment = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.bank_txn_id == txn_id)
        .one()
    )
    checkout = db.query(models.SubscriptionCheckout).get(ctx["checkout_id"])
    subscription = db.query(models.ShopSubscription).get(ctx["shop_id"])
    assert payment.reference_code == unknown_reference
    assert payment.checkout_id is None
    assert payment.shop_id is None
    assert payment.needs_review is True
    assert payment.review_reason == "UNKNOWN_REFERENCE"
    assert (checkout.status, checkout.received_amount_vnd) == ("PENDING", 0)
    assert subscription.paid_until is None
    assert _order_ledger_counts(db) == before_orders


def test_webhook_sub_checkout_het_han_dung_bien_24_gio(
    client, db, subscription_secret, monkeypatch
):
    """Trước mốc độc quyền còn nhận; đúng mốc 24h phải đưa vào review."""
    boundary = datetime.datetime(2026, 8, 7, 2, 0, 0)
    exact = _create_expired_trial_checkout(
        db,
        now=boundary,
        created_at=boundary - datetime.timedelta(hours=24),
        expires_at=boundary,
    )
    just_before = _create_expired_trial_checkout(
        db,
        now=boundary,
        created_at=(
            boundary - datetime.timedelta(hours=24)
            + datetime.timedelta(microseconds=1)
        ),
        expires_at=boundary + datetime.timedelta(microseconds=1),
    )
    _configure_platform_bank(monkeypatch)
    monkeypatch.setattr(subscription_service, "utcnow", lambda: boundary)
    before_orders = _order_ledger_counts(db)

    exact_response = _post(
        client,
        {
            "content": exact["reference_code"],
            "transferAmount": 99000,
            "transferType": "in",
            "id": f"TXN-EXACT-{uuid.uuid4().hex[:12].upper()}",
            "accountNumber": PLATFORM_ACCOUNT,
        },
    )
    before_response = _post(
        client,
        {
            "content": just_before["reference_code"],
            "transferAmount": 99000,
            "transferType": "in",
            "id": f"TXN-BEFORE-{uuid.uuid4().hex[:12].upper()}",
            "accountNumber": PLATFORM_ACCOUNT,
        },
    )

    assert exact_response.status_code == 200, exact_response.text
    assert before_response.status_code == 200, before_response.text
    assert exact_response.json()["activated_shop_ids"] == []
    assert len(exact_response.json()["review_payment_ids"]) == 1
    assert before_response.json()["activated_shop_ids"] == [just_before["shop_id"]]
    db.expire_all()
    exact_checkout = db.query(models.SubscriptionCheckout).get(exact["checkout_id"])
    before_checkout = db.query(models.SubscriptionCheckout).get(
        just_before["checkout_id"]
    )
    exact_payment = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.checkout_id == exact["checkout_id"])
        .one()
    )
    exact_subscription = db.query(models.ShopSubscription).get(exact["shop_id"])
    before_subscription = db.query(models.ShopSubscription).get(
        just_before["shop_id"]
    )
    assert exact_checkout.status == "EXPIRED"
    assert exact_checkout.received_amount_vnd == 0
    assert exact_payment.needs_review is True
    assert exact_payment.review_reason == "EXPIRED_CHECKOUT"
    assert exact_subscription.paid_until is None
    assert before_checkout.status == "PAID"
    assert before_checkout.received_amount_vnd == 99000
    assert before_subscription.paid_until == boundary + datetime.timedelta(days=30)
    assert _order_ledger_counts(db) == before_orders


@pytest.mark.parametrize(
    "amount_field, transfer_type",
    [
        (99000, "out"),
        (0, "in"),
        (None, "in"),
    ],
    ids=["tien-ra", "so-tien-0", "thieu-so-tien"],
)
def test_webhook_sub_tien_ra_0_hoac_thieu_tien_bi_tu_choi_khong_ghi_ledger(
    client,
    db,
    subscription_secret,
    monkeypatch,
    amount_field,
    transfer_type,
):
    now = datetime.datetime(2026, 8, 7, 2, 0, 0)
    ctx = _create_expired_trial_checkout(db, now=now)
    _configure_platform_bank(monkeypatch)
    before_orders = _order_ledger_counts(db)
    before_payments = db.query(models.SubscriptionPayment).count()
    payload = {
        "content": ctx["reference_code"],
        "transferType": transfer_type,
        "id": f"TXN-REJECT-{uuid.uuid4().hex[:12].upper()}",
        "accountNumber": PLATFORM_ACCOUNT,
    }
    if amount_field is not None:
        payload["transferAmount"] = amount_field

    response = _post(client, payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activated_shop_ids"] == []
    assert body["review_payment_ids"] == []
    assert body["rejected_references"] == [ctx["reference_code"]]
    db.expire_all()
    checkout = db.query(models.SubscriptionCheckout).get(ctx["checkout_id"])
    subscription = db.query(models.ShopSubscription).get(ctx["shop_id"])
    assert (checkout.status, checkout.received_amount_vnd) == ("PENDING", 0)
    assert subscription.paid_until is None
    assert db.query(models.SubscriptionPayment).count() == before_payments
    assert _order_ledger_counts(db) == before_orders


def test_webhook_sub_payload_thieu_account_dung_tai_khoan_env_lam_fallback(
    client, db, subscription_secret, monkeypatch
):
    now = datetime.datetime(2026, 8, 7, 2, 0, 0)
    ctx = _create_expired_trial_checkout(db, now=now)
    _configure_platform_bank(monkeypatch)
    monkeypatch.setattr(subscription_service, "utcnow", lambda: now)
    before_orders = _order_ledger_counts(db)
    txn_id = f"TXN-NO-ACCOUNT-{uuid.uuid4().hex[:12].upper()}"
    payload = {
        "content": ctx["reference_code"],
        "transferAmount": 99000,
        "transferType": "in",
        "id": txn_id,
        # Nhà cung cấp không gửi accountNumber: dùng tài khoản nền tảng cấu hình.
    }

    response = _post(client, payload)
    retry = _post(client, payload)

    assert response.status_code == 200, response.text
    assert retry.status_code == 200, retry.text
    assert response.json()["activated_shop_ids"] == [ctx["shop_id"]]
    assert len(retry.json()["duplicate_payment_ids"]) == 1
    db.expire_all()
    payments = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.bank_txn_id == txn_id)
        .all()
    )
    assert len(payments) == 1
    payment = payments[0]
    parsed = payment_service.extract_subscription_transactions(payload)[0]
    expected_key = payment_service.bank_idempotency_key(
        parsed,
        PLATFORM_ACCOUNT,
        namespace="sub-bank",
    )
    subscription = db.query(models.ShopSubscription).get(ctx["shop_id"])
    assert payment.account_no is None
    assert payment.idempotency_key == expected_key
    assert payment.needs_review is False
    assert subscription.paid_until == now + datetime.timedelta(days=30)
    assert _order_ledger_counts(db) == before_orders


def test_webhook_sub_trung_khoa_idempotency_payload_khac_khong_cap_pro(
    client, db, subscription_secret, monkeypatch
):
    now = datetime.datetime(2026, 8, 7, 2, 0, 0)
    ctx = _create_expired_trial_checkout(db, now=now)
    _configure_platform_bank(monkeypatch)
    monkeypatch.setattr(subscription_service, "utcnow", lambda: now)
    before_orders = _order_ledger_counts(db)
    txn_id = f"TXN-COLLISION-{uuid.uuid4().hex[:12].upper()}"
    base_payload = {
        "content": ctx["reference_code"],
        "transferType": "in",
        "id": txn_id,
        "accountNumber": PLATFORM_ACCOUNT,
    }

    first = _post(client, {**base_payload, "transferAmount": 40000})
    collision = _post(client, {**base_payload, "transferAmount": 99000})

    assert first.status_code == 200, first.text
    assert collision.status_code == 200, collision.text
    assert first.json()["underpaid_checkout_ids"] == [ctx["checkout_id"]]
    assert collision.json()["activated_shop_ids"] == []
    assert collision.json()["duplicate_payment_ids"] == []
    assert collision.json()["rejected_references"] == [ctx["reference_code"]]
    db.expire_all()
    payments = (
        db.query(models.SubscriptionPayment)
        .filter(models.SubscriptionPayment.bank_txn_id == txn_id)
        .all()
    )
    checkout = db.query(models.SubscriptionCheckout).get(ctx["checkout_id"])
    subscription = db.query(models.ShopSubscription).get(ctx["shop_id"])
    assert len(payments) == 1
    assert payments[0].amount_vnd == 40000
    assert payments[0].needs_review is True
    assert payments[0].review_reason == "UNDERPAID"
    assert (checkout.status, checkout.received_amount_vnd) == ("UNDERPAID", 40000)
    assert checkout.activated_at is None
    assert subscription.paid_until is None
    assert _order_ledger_counts(db) == before_orders
