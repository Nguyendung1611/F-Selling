"""I10-B: phát hành intent QR bán hàng nguyên tử và idempotent."""
from __future__ import annotations

import inspect
import json
import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from conftest import _unique, auth, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.schemas.order import OrderCreate
from fselling.services import order_service, qr_sales_service


def _payload(ctx, *, method="transfer", qty=1, operation_id=None, product=None, **extra):
    selected = product or ctx["product"]
    body = {
        "items": [
            {
                "product_id": selected["id"],
                "product_name": selected["name"],
                "price": 1,
                "quantity": qty,
            }
        ],
        "payment_method": method,
    }
    if operation_id is not None:
        body["operation_id"] = operation_id
    body.update(extra)
    return body


def _enable_report_only(monkeypatch, adapter=None):
    runtime = qr_sales_service.report_only_test_runtime(adapter)
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: runtime)
    return runtime


def _intent_rows(shop_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.QrPaymentIntent)
            .filter(models.QrPaymentIntent.shop_id == shop_id)
            .order_by(models.QrPaymentIntent.id)
            .all()
        )
    finally:
        session.close()


def _issuance_audits(shop_id):
    session = SessionLocal()
    try:
        rows = (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.shop_id == shop_id,
                models.SystemLog.action
                == qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
            )
            .order_by(models.SystemLog.id)
            .all()
        )
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "shop_id": row.shop_id,
                "action": row.action,
                "details": row.details,
            }
            for row in rows
        ]
    finally:
        session.close()


class CountingMockAdapter(qr_sales_service.DeterministicMockQrAdapter):
    def __init__(self):
        self.calls = 0

    def render(self, instruction):
        self.calls += 1
        return super().render(instruction)


def test_default_off_preserves_v0_order_and_creates_no_intent(client):
    ctx = seller_with_shop(client)

    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx, operation_id=uuid.uuid4().hex),
        headers=auth(ctx["token"]),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "qr_intent" not in body
    assert body["qr_url"].startswith("https://img.vietqr.io/")
    assert _intent_rows(ctx["shop_id"]) == []
    assert _issuance_audits(ctx["shop_id"]) == []


def test_report_only_issues_exact_immutable_snapshot_in_existing_commit(
    client, monkeypatch
):
    adapter = CountingMockAdapter()
    _enable_report_only(monkeypatch, adapter)
    ctx = seller_with_shop(client)
    operation_id = uuid.uuid4().hex

    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx, qty=2, operation_id=operation_id),
        headers=auth(ctx["token"]),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    metadata = body["qr_intent"]
    assert body["total"] == metadata["expected_vnd"] == 200_000
    assert type(metadata["expected_vnd"]) is int
    assert body["status"] == "PENDING"
    assert body["qr_url"] is None
    assert metadata["contract_version"] == 1
    assert metadata["canonical_reference"].startswith("FS1-")
    assert metadata["bank_code"] == "VCB"
    assert metadata["bank_account_no"] == "0123456789"
    assert metadata["bank_account_name"] == "NGUYEN VAN TEST"
    assert metadata["instruction_only"] is True
    assert metadata["capability"] == {
        "mode": "REPORT_ONLY",
        "render_available": True,
        "render_endpoint": f"/api/orders/{body['order_id']}/qr/render",
    }
    assert "http" not in str(metadata).lower()
    assert adapter.calls == 0, "adapter/render không được chạy trong transaction tiền"

    session = SessionLocal()
    try:
        order = session.query(models.Order).filter_by(id=body["order_id"]).one()
        intent = session.query(models.QrPaymentIntent).filter_by(order_id=order.id).one()
        assert intent.expected_vnd == order.total_amount == 200_000
        assert intent.canonical_reference == metadata["canonical_reference"]
        assert intent.display_expires_at is None
        assert intent.cancel_after is None
        assert order.status == "PENDING"
        assert session.query(models.OrderPayment).filter_by(order_id=order.id).count() == 0
        audits = session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.user_id == order.created_by_user_id
        assert audit.shop_id == order.shop_id
        assert audit.action == "QR_PAYMENT_INTENT_ISSUED"
        assert json.loads(audit.details) == {
            "contract_version": 1,
            "entity": "qr_payment_intent",
            "intent_id": intent.id,
            "order_id": order.id,
            "shop_id": order.shop_id,
            "status": "ISSUED",
        }
        sensitive_values = (
            intent.canonical_reference,
            intent.bank_code,
            intent.account_no,
            intent.account_name,
            operation_id,
        )
        assert all(value not in audit.details for value in sensitive_values)
        assert all(
            marker not in audit.details.lower()
            for marker in (
                "account",
                "reference",
                "operation",
                "request",
                "provider",
                "payload",
                "token",
                "url",
                "bytes",
            )
        )
    finally:
        session.close()


def test_issuance_audit_source_has_no_commit_or_sensitive_payload_fields():
    source = inspect.getsource(qr_sales_service._add_issuance_audit)
    insert_source = inspect.getsource(qr_sales_service._insert_issuance_audit)

    assert "db.flush()" in insert_source
    assert ".commit(" not in source + insert_source
    for forbidden in (
        "canonical_reference",
        "bank_code",
        "account_no",
        "account_name",
        "operation_id",
        "raw_request",
        "provider_payload",
        "qr_bytes",
        "token",
        "url",
    ):
        assert forbidden not in source


def test_cash_debt_zero_total_and_offline_are_never_issued(client, monkeypatch):
    runtime = _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)

    cash = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx, method="cash", operation_id=uuid.uuid4().hex),
        headers=auth(ctx["token"]),
    )
    assert cash.status_code == 200, cash.text

    customer = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": _unique("Khach no"), "phone": _unique("09")[:15]},
        headers=auth(ctx["token"]),
    )
    assert customer.status_code == 200, customer.text
    debt = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(
            ctx,
            method="debt",
            operation_id=uuid.uuid4().hex,
            customer_id=customer.json()["id"],
        ),
        headers=auth(ctx["token"]),
    )
    assert debt.status_code == 200, debt.text

    free_code = "QRFREE" + uuid.uuid4().hex[:8].upper()
    full_discount = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={
            "code": free_code,
            "discount_type": "flat",
            "discount_value": 100_000,
            "min_order_value": 0,
            "usage_limit": 1,
            "expires_at": None,
        },
        headers=auth(ctx["token"]),
    )
    assert full_discount.status_code == 200, full_discount.text
    zero = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(
            ctx,
            operation_id=uuid.uuid4().hex,
            voucher_code=free_code,
        ),
        headers=auth(ctx["token"]),
    )
    assert zero.status_code == 200, zero.text
    assert zero.json()["total"] == 0

    # Guard dịch vụ: receipt offline không thể được nâng cấp/fabricate intent,
    # kể cả khi có hình thức/tiền giống đơn online.
    offline = models.Order(
        id=9_999_999,
        shop_id=ctx["shop_id"],
        payment_method="transfer",
        total_amount=100_000,
        offline_uuid=uuid.uuid4().hex,
    )
    shop = models.Shop(
        id=ctx["shop_id"],
        bank_code="VCB",
        bank_account_no="1",
        bank_account_name="TEST",
    )
    session = SessionLocal()
    try:
        assert qr_sales_service.issue_intent_if_enabled(
            session, offline, shop, runtime=runtime
        ) is None
    finally:
        session.rollback()
        session.close()

    assert _intent_rows(ctx["shop_id"]) == []
    assert _issuance_audits(ctx["shop_id"]) == []
    assert all("qr_intent" not in item.json() for item in (cash, debt, zero))


def test_subscription_qr_never_uses_sales_intent_even_in_report_only(
    client, monkeypatch
):
    _enable_report_only(monkeypatch)
    monkeypatch.setenv("SUBSCRIPTION_BANK_CODE", "MB")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NO", "00123456789")
    monkeypatch.setenv("SUBSCRIPTION_BANK_ACCOUNT_NAME", "F SELLING TEST")
    ctx = seller_with_shop(client)

    checkout = client.post(
        f"/api/subscriptions/{ctx['shop_id']}/checkouts",
        json={"cycle": "MONTHLY", "operation_id": uuid.uuid4().hex},
        headers=auth(ctx["token"]),
    )

    assert checkout.status_code == 200, checkout.text
    assert "qr_url" in checkout.json(), "giữ nguyên contract QR subscription riêng"
    assert _intent_rows(ctx["shop_id"]) == []
    assert _issuance_audits(ctx["shop_id"]) == []
    session = SessionLocal()
    try:
        assert session.query(models.SubscriptionCheckout).filter_by(
            shop_id=ctx["shop_id"]
        ).count() == 1
    finally:
        session.close()


def test_lost_response_retry_returns_same_order_intent_and_effects_once(
    client, monkeypatch
):
    adapter = CountingMockAdapter()
    _enable_report_only(monkeypatch, adapter)
    ctx = seller_with_shop(client)
    operation_id = uuid.uuid4().hex
    payload = _payload(ctx, qty=2, operation_id=operation_id)

    first = client.post(
        f"/api/orders/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    retry = client.post(
        f"/api/orders/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )

    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert adapter.calls == 0
    session = SessionLocal()
    try:
        assert session.query(models.Order).filter_by(operation_id=operation_id).count() == 1
        assert session.query(models.QrPaymentIntent).filter_by(
            order_id=first.json()["order_id"]
        ).count() == 1
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == 1
        product = session.query(models.Product).filter_by(id=ctx["product"]["id"]).one()
        assert product.stock == 8
    finally:
        session.close()


def test_concurrent_same_operation_id_returns_one_exact_intent_without_sleep(
    client, monkeypatch
):
    _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)
    operation_id = uuid.uuid4().hex
    barrier = threading.Barrier(2)
    real_lock = order_service._lock_shop_for_order

    def synchronized_lock(db, shop_id):
        barrier.wait(timeout=5)
        return real_lock(db, shop_id)

    monkeypatch.setattr(order_service, "_lock_shop_for_order", synchronized_lock)
    outcomes = []
    outcomes_lock = threading.Lock()

    def submit():
        session = SessionLocal()
        try:
            user = session.query(models.User).filter_by(username=ctx["username"]).one()
            request = OrderCreate.model_validate(
                _payload(ctx, qty=2, operation_id=operation_id)
            )
            outcome = order_service.create_order(session, user, ctx["shop_id"], request)
        except Exception as exc:  # pragma: no cover - hiện lỗi thread rõ ràng
            outcome = {"error": type(exc).__name__, "detail": str(exc)}
        finally:
            session.close()
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(outcomes) == 2
    assert all("error" not in outcome for outcome in outcomes), outcomes
    assert outcomes[0] == outcomes[1]
    reference = outcomes[0]["qr_intent"]["canonical_reference"]
    session = SessionLocal()
    try:
        orders = session.query(models.Order).filter_by(operation_id=operation_id).all()
        assert len(orders) == 1
        intent = session.query(models.QrPaymentIntent).filter_by(order_id=orders[0].id).one()
        assert intent.canonical_reference == reference
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == 1
        assert session.query(models.Product).filter_by(
            id=ctx["product"]["id"]
        ).one().stock == 8
    finally:
        session.close()


def test_concurrent_reference_collision_retries_bounded_without_duplicate_effects(
    client, monkeypatch
):
    _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)
    barrier = threading.Barrier(2)
    real_lock = order_service._lock_shop_for_order

    def synchronized_lock(db, shop_id):
        barrier.wait(timeout=5)
        return real_lock(db, shop_id)

    monkeypatch.setattr(order_service, "_lock_shop_for_order", synchronized_lock)
    call_lock = threading.Lock()
    calls = 0
    shared = "FS1-" + "A" * 32
    unique = "FS1-" + "B" * 32

    def deterministic_reference():
        nonlocal calls
        with call_lock:
            calls += 1
            return shared if calls <= 2 else unique

    monkeypatch.setattr(qr_sales_service, "_canonical_reference", deterministic_reference)
    outcomes = []
    outcomes_lock = threading.Lock()

    def submit(operation_id):
        session = SessionLocal()
        try:
            user = session.query(models.User).filter_by(username=ctx["username"]).one()
            request = OrderCreate.model_validate(
                _payload(ctx, operation_id=operation_id)
            )
            outcome = order_service.create_order(session, user, ctx["shop_id"], request)
        except Exception as exc:  # pragma: no cover
            outcome = {"error": type(exc).__name__, "detail": str(exc)}
        finally:
            session.close()
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=submit, args=(uuid.uuid4().hex,)),
        threading.Thread(target=submit, args=(uuid.uuid4().hex,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert all("error" not in outcome for outcome in outcomes), outcomes
    assert calls == 3
    assert {
        outcome["qr_intent"]["canonical_reference"] for outcome in outcomes
    } == {shared, unique}
    session = SessionLocal()
    try:
        assert session.query(models.Order).filter_by(shop_id=ctx["shop_id"]).count() == 2
        assert session.query(models.QrPaymentIntent).filter_by(
            shop_id=ctx["shop_id"]
        ).count() == 2
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == 2
        assert session.query(models.Product).filter_by(
            id=ctx["product"]["id"]
        ).one().stock == 8
    finally:
        session.close()


@pytest.mark.parametrize(
    "failure_point",
    ("intent_flush", "audit_add", "audit_flush", "outer_commit"),
)
def test_issuance_boundary_failure_rolls_back_all_order_effects(
    client, monkeypatch, failure_point
):
    _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)
    program = client.put(
        f"/api/loyalty/{ctx['shop_id']}",
        json={
            "enabled": True,
            "earn_amount": 10_000,
            "earn_points": 1,
            "redeem_points": 1,
            "redeem_amount": 1_000,
            "min_redeem_points": 1,
            "max_redeem_percent": 100,
            "expiry_days": None,
        },
        headers=auth(ctx["token"]),
    )
    assert program.status_code == 200, program.text
    customer = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": _unique("Khach rollback"), "phone": _unique("09")[:15]},
        headers=auth(ctx["token"]),
    )
    assert customer.status_code == 200, customer.text
    earned = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(
            ctx,
            method="cash",
            operation_id=uuid.uuid4().hex,
            customer_id=customer.json()["id"],
        ),
        headers=auth(ctx["token"]),
    )
    assert earned.status_code == 200, earned.text
    paid = client.post(
        f"/api/orders/{earned.json()['order_id']}/pay",
        headers=auth(ctx["token"]),
    )
    assert paid.status_code == 200, paid.text

    voucher_code = "QRFAIL" + uuid.uuid4().hex[:8].upper()
    voucher = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={
            "code": voucher_code,
            "discount_type": "flat",
            "discount_value": 10_000,
            "min_order_value": 0,
            "usage_limit": 2,
            "expires_at": None,
        },
        headers=auth(ctx["token"]),
    )
    assert voucher.status_code == 200, voucher.text

    session = SessionLocal()
    try:
        product = session.query(models.Product).filter_by(id=ctx["product"]["id"]).one()
        before_product = (
            product.stock,
            product.cost_known_qty,
            product.cost_unknown_qty,
            product.cost_basis_vnd,
            product.cost_deficit_qty,
        )
        before_counts = {
            "orders": session.query(models.Order).filter_by(
                shop_id=ctx["shop_id"]
            ).count(),
            "items": session.query(models.OrderItem).join(models.Order).filter(
                models.Order.shop_id == ctx["shop_id"]
            ).count(),
            "payments": session.query(models.OrderPayment).join(models.Order).filter(
                models.Order.shop_id == ctx["shop_id"]
            ).count(),
            "loyalty": session.query(models.LoyaltyPointEntry).filter_by(
                customer_id=customer.json()["id"]
            ).count(),
            "qr_audits": session.query(models.SystemLog).filter_by(
                shop_id=ctx["shop_id"],
                action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
            ).count(),
        }
        before_points = sum(
            row.points_delta
            for row in session.query(models.LoyaltyPointEntry).filter_by(
                customer_id=customer.json()["id"]
            )
        )
        assert before_points == 10
    finally:
        session.close()

    if failure_point == "intent_flush":
        def fail_intent_flush(_db, _intent):
            raise IntegrityError("forced", {}, RuntimeError("different constraint"))

        monkeypatch.setattr(
            qr_sales_service, "_insert_intent_candidate", fail_intent_flush
        )
    elif failure_point == "audit_add":
        def fail_audit_add(_db, _audit):
            raise RuntimeError("forced audit add failure")

        monkeypatch.setattr(
            qr_sales_service, "_insert_issuance_audit", fail_audit_add
        )
    elif failure_point == "audit_flush":
        def fail_audit_flush(db, audit):
            db.add(audit)
            raise IntegrityError("forced", {}, RuntimeError("audit flush failure"))

        monkeypatch.setattr(
            qr_sales_service, "_insert_issuance_audit", fail_audit_flush
        )

    sanitized_logs = []
    monkeypatch.setattr(qr_sales_service, "log_to_file", sanitized_logs.append)
    attempt = SessionLocal()
    if failure_point == "outer_commit":
        def fail_outer_commit():
            raise RuntimeError("forced outer commit failure")

        monkeypatch.setattr(attempt, "commit", fail_outer_commit)
    try:
        user = attempt.query(models.User).filter_by(username=ctx["username"]).one()
        request = OrderCreate.model_validate(
            _payload(
                ctx,
                operation_id=uuid.uuid4().hex,
                voucher_code=voucher_code,
                customer_id=customer.json()["id"],
                loyalty_points_to_use=1,
            )
        )
        with pytest.raises(Exception) as caught:
            order_service.create_order(attempt, user, ctx["shop_id"], request)
        if failure_point == "intent_flush":
            assert isinstance(caught.value, HTTPException)
            assert caught.value.status_code == 503
            assert caught.value.detail["code"] == "QR_INTENT_ISSUANCE_FAILED"
            assert sanitized_logs == [
                "QR intent issuance failed code=QR_INTENT_ISSUANCE_FAILED"
            ]
        elif failure_point in {"audit_add", "audit_flush"}:
            assert isinstance(caught.value, HTTPException)
            assert caught.value.status_code == 503
            assert caught.value.detail["code"] == "QR_INTENT_AUDIT_FAILED"
            assert "forced" not in str(caught.value.detail).lower()
            assert sanitized_logs == [
                "QR intent issuance failed code=QR_INTENT_AUDIT_FAILED"
            ]
        else:
            assert isinstance(caught.value, RuntimeError)
            assert str(caught.value) == "forced outer commit failure"
            assert sanitized_logs == []
    finally:
        attempt.close()

    session = SessionLocal()
    try:
        product = session.query(models.Product).filter_by(id=ctx["product"]["id"]).one()
        assert (
            product.stock,
            product.cost_known_qty,
            product.cost_unknown_qty,
            product.cost_basis_vnd,
            product.cost_deficit_qty,
        ) == before_product
        stored_voucher = session.query(models.Voucher).filter_by(
            shop_id=ctx["shop_id"], code=voucher_code
        ).one()
        assert stored_voucher.usage_count == 0
        assert session.query(models.Order).filter_by(
            shop_id=ctx["shop_id"]
        ).count() == before_counts["orders"]
        assert session.query(models.OrderItem).join(models.Order).filter(
            models.Order.shop_id == ctx["shop_id"]
        ).count() == before_counts["items"]
        assert session.query(models.OrderPayment).join(models.Order).filter(
            models.Order.shop_id == ctx["shop_id"]
        ).count() == before_counts["payments"]
        assert session.query(models.QrPaymentIntent).filter_by(
            shop_id=ctx["shop_id"]
        ).count() == 0
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == before_counts["qr_audits"] == 0
        entries = session.query(models.LoyaltyPointEntry).filter_by(
            customer_id=customer.json()["id"]
        ).all()
        assert len(entries) == before_counts["loyalty"]
        assert sum(row.points_delta for row in entries) == before_points
    finally:
        session.close()


def test_shop_snapshot_is_refreshed_after_shared_serialization_lock(client, monkeypatch):
    _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)
    real_lock = order_service._lock_shop_for_order
    changed = False

    def update_then_lock(db, shop_id):
        nonlocal changed
        if not changed:
            changed = True
            other = SessionLocal()
            try:
                shop = other.query(models.Shop).filter_by(id=shop_id).one()
                shop.bank_code = "MB"
                shop.bank_account_no = "99887766"
                shop.bank_account_name = "SNAPSHOT MOI"
                other.commit()
            finally:
                other.close()
        return real_lock(db, shop_id)

    monkeypatch.setattr(order_service, "_lock_shop_for_order", update_then_lock)
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx, operation_id=uuid.uuid4().hex),
        headers=auth(ctx["token"]),
    )

    assert response.status_code == 200, response.text
    metadata = response.json()["qr_intent"]
    assert (
        metadata["bank_code"],
        metadata["bank_account_no"],
        metadata["bank_account_name"],
    ) == ("MB", "99887766", "SNAPSHOT MOI")


def test_report_only_order_uses_exactly_one_existing_commit(client, monkeypatch):
    runtime = _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)
    session = SessionLocal()
    commits = 0
    real_commit = session.commit

    def counted_commit():
        nonlocal commits
        commits += 1
        return real_commit()

    monkeypatch.setattr(session, "commit", counted_commit)
    try:
        user = session.query(models.User).filter_by(username=ctx["username"]).one()
        request = OrderCreate.model_validate(
            _payload(ctx, operation_id=uuid.uuid4().hex)
        )
        result = order_service.create_order(
            session, user, ctx["shop_id"], request
        )
        assert result["qr_intent"]["capability"]["mode"] == runtime.mode
        assert commits == 1
    finally:
        session.close()


def test_reference_collision_exhaustion_is_stable_and_rolls_back(client, monkeypatch):
    _enable_report_only(monkeypatch)
    ctx = seller_with_shop(client)
    collision = "FS1-" + "C" * 32
    monkeypatch.setattr(qr_sales_service, "_canonical_reference", lambda: collision)

    first = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx, operation_id=uuid.uuid4().hex),
        headers=auth(ctx["token"]),
    )
    assert first.status_code == 200
    session = SessionLocal()
    try:
        stock_before = session.query(models.Product).filter_by(
            id=ctx["product"]["id"]
        ).one().stock
    finally:
        session.close()

    failed = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx, operation_id=uuid.uuid4().hex),
        headers=auth(ctx["token"]),
    )
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "QR_INTENT_REFERENCE_UNAVAILABLE"
    session = SessionLocal()
    try:
        assert session.query(models.Order).filter_by(shop_id=ctx["shop_id"]).count() == 1
        assert session.query(models.QrPaymentIntent).filter_by(
            shop_id=ctx["shop_id"]
        ).count() == 1
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == 1
        assert session.query(models.Product).filter_by(
            id=ctx["product"]["id"]
        ).one().stock == stock_before
    finally:
        session.close()
