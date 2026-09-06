"""P0.3: persistence boundary theo từng bank event của webhook ORDER."""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from conftest import SHOP_PAYLOAD, _unique, auth, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.schemas.order import DebtPayment
from fselling.schemas.shop import ShopCreate
from fselling.services import order_service, payment_service, shop_service


SECRET = "webhook-transaction-persistence"
TOTAL = 100_000


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _post(client, payload):
    return client.post(
        "/api/orders/webhook",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )


def _create_customer(client, ctx):
    response = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": _unique("Khach P03"), "phone": _unique("09")[:15]},
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_order(client, ctx, *, method="transfer", customer_id=None):
    body = {
        "items": [
            {
                "product_id": ctx["product"]["id"],
                "price": 1,
                "quantity": 1,
            }
        ],
        "payment_method": method,
    }
    if customer_id is not None:
        body["customer_id"] = customer_id
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=body,
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()["order_id"]


def _enable_loyalty(client, ctx):
    response = client.put(
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
    assert response.status_code == 200, response.text


def _direct_debt_payment(ctx, order_id, *, amount=TOTAL):
    session = SessionLocal()
    try:
        user = (
            session.query(models.User)
            .filter(models.User.username == ctx["username"])
            .one()
        )
        return order_service.debt_payment(
            session,
            user,
            order_id,
            DebtPayment(
                amount=amount,
                method="transfer",
                operation_id=uuid.uuid4().hex,
            ),
        )
    finally:
        session.close()


def _direct_webhook(payload):
    session = SessionLocal()
    try:
        return order_service.apply_webhook_payment(session, payload)
    finally:
        session.close()


def _update_shop_account(client, ctx, account_no):
    payload = dict(SHOP_PAYLOAD)
    payload["name"] = _unique("Shop P03 account")
    payload["bank_account_no"] = account_no
    return client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )


def _direct_update_shop_account(ctx, account_no):
    session = SessionLocal()
    try:
        user = (
            session.query(models.User)
            .filter(models.User.username == ctx["username"])
            .one()
        )
        payload = dict(SHOP_PAYLOAD)
        payload["name"] = _unique("Shop P03 account race")
        payload["bank_account_no"] = account_no
        updated = shop_service.update_shop(
            session,
            user,
            ctx["shop_id"],
            ShopCreate(**payload),
        )
        return updated.bank_account_no
    finally:
        session.close()


def _durable_shop_account(shop_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.Shop.bank_account_no)
            .filter(models.Shop.id == shop_id)
            .scalar()
        )
    finally:
        session.close()


def _snapshot(order_id):
    """Đọc bằng Session mới để chỉ quan sát state thực sự durable."""
    session = SessionLocal()
    try:
        order = session.query(models.Order).filter(models.Order.id == order_id).one()
        return {
            "order": (
                order.status,
                order.paid_amount,
                order.cash_paid_amount,
                order.bank_txn_id,
                order.reconciliation_reason,
                order.refunded_amount,
                order.refund_due_amount,
                order.refund_completed_at,
                order.refund_completed_by,
                order.refund_method,
                order.refund_note,
                order.refund_reference,
                order.loyalty_points_earned,
                order.loyalty_awarded_at,
            ),
            "payments": [
                (
                    row.entry_type,
                    row.amount,
                    row.idempotency_key,
                    row.provider,
                    row.bank_txn_id,
                    row.account_no,
                    row.shift_id,
                )
                for row in session.query(models.OrderPayment)
                .filter(models.OrderPayment.order_id == order_id)
                .order_by(models.OrderPayment.id)
                .all()
            ],
            "loyalty": [
                (row.entry_type, row.points_delta, row.idempotency_key)
                for row in session.query(models.LoyaltyPointEntry)
                .filter(models.LoyaltyPointEntry.order_id == order_id)
                .order_by(models.LoyaltyPointEntry.id)
                .all()
            ],
            "logs": [
                (row.action, row.details, row.shop_id)
                for row in session.query(models.SystemLog)
                .filter(models.SystemLog.details.like(f"%Order {order_id}%"))
                .order_by(models.SystemLog.id)
                .all()
            ],
        }
    finally:
        session.close()


def _install_fault(monkeypatch, fault):
    raised = {"value": False}

    if fault == "flush":
        original = Session.flush

        def fail_once(self, *args, **kwargs):
            if not raised["value"]:
                raised["value"] = True
                raise RuntimeError("forced webhook flush failure")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Session, "flush", fail_once)
    elif fault == "audit":
        original = order_service._them_nhat_ky

        def fail_once(*args, **kwargs):
            if not raised["value"]:
                raised["value"] = True
                raise RuntimeError("forced webhook audit failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(order_service, "_them_nhat_ky", fail_once)
    elif fault == "commit":
        original = Session.commit

        def fail_once(self, *args, **kwargs):
            if not raised["value"]:
                raised["value"] = True
                raise RuntimeError("forced webhook commit failure")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Session, "commit", fail_once)
    else:  # pragma: no cover - chỉ gọi bằng param cố định bên dưới
        raise AssertionError(fault)
    return raised


@pytest.mark.parametrize("fault", ["flush", "audit", "commit"])
def test_bank_unapplied_persistence_fault_rollback_va_retry_dung_mot_lan(
    client, webhook_secret, monkeypatch, fault
):
    ctx = seller_with_shop(client)
    customer = _create_customer(client, ctx)
    order_id = _create_order(
        client,
        ctx,
        method="debt",
        customer_id=customer["id"],
    )
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": 40_000,
        "transferType": "in",
        "id": f"P03-UNAPPLIED-{fault}-{uuid.uuid4().hex}",
    }
    before = _snapshot(order_id)

    with monkeypatch.context() as injected:
        raised = _install_fault(injected, fault)
        failed = _post(client, payload)

    assert raised["value"] is True
    assert failed.status_code == 500, failed.text
    assert _snapshot(order_id) == before

    first = _post(client, payload)
    retry = _post(client, payload)
    assert first.status_code == retry.status_code == 200
    assert first.json()["rejected_order_ids"] == [order_id]
    durable = _snapshot(order_id)
    assert durable["order"][0] == "DEBT"
    assert durable["order"][1] in (None, 0)
    assert [row[0] for row in durable["payments"]] == ["BANK_UNAPPLIED"]
    assert len(durable["logs"]) == 1
    assert durable["logs"][0][0] == "WEBHOOK_TU_CHOI"
    assert "BANK_UNAPPLIED" in durable["logs"][0][1]


@pytest.mark.parametrize("fault", ["flush", "audit", "commit"])
def test_bank_in_persistence_fault_rollback_order_refund_loyalty_audit(
    client, webhook_secret, monkeypatch, fault
):
    ctx = seller_with_shop(client)
    _enable_loyalty(client, ctx)
    customer = _create_customer(client, ctx)
    order_id = _create_order(client, ctx, customer_id=customer["id"])
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": 120_000,
        "transferType": "in",
        "id": f"P03-BANK-IN-{fault}-{uuid.uuid4().hex}",
    }
    before = _snapshot(order_id)

    with monkeypatch.context() as injected:
        raised = _install_fault(injected, fault)
        failed = _post(client, payload)

    assert raised["value"] is True
    assert failed.status_code == 500, failed.text
    assert _snapshot(order_id) == before

    first = _post(client, payload)
    retry = _post(client, payload)
    assert first.status_code == retry.status_code == 200
    assert first.json()["order_ids"] == [order_id]
    durable = _snapshot(order_id)
    assert durable["order"][0] == "PAID"
    assert durable["order"][1] == 120_000
    assert durable["order"][4] == "OVERPAID"
    assert durable["order"][6] == 20_000
    assert durable["order"][12] == 10
    assert [row[0] for row in durable["payments"]] == ["BANK_IN"]
    assert durable["loyalty"] == [("EARN", 10, f"earn:order:{order_id}")]
    assert len(durable["logs"]) == 1
    assert durable["logs"][0][0] == "WEBHOOK_PAYMENT"


def test_integrityerror_khong_co_duplicate_row_noi_5xx_va_rollback(
    client, webhook_secret, monkeypatch
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": TOTAL,
        "id": f"P03-INTEGRITY-{uuid.uuid4().hex}",
    }
    before = _snapshot(order_id)
    raised = {"value": False}
    original = Session.flush

    def unknown_integrity_error(self, *args, **kwargs):
        if not raised["value"]:
            raised["value"] = True
            raise IntegrityError(
                "forced non-idempotency integrity error",
                {},
                RuntimeError("no duplicate row"),
            )
        return original(self, *args, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(Session, "flush", unknown_integrity_error)
        failed = _post(client, payload)

    assert raised["value"] is True
    assert failed.status_code == 500, failed.text
    assert _snapshot(order_id) == before

    first = _post(client, payload)
    retry = _post(client, payload)
    assert first.status_code == retry.status_code == 200
    durable = _snapshot(order_id)
    assert [row[0] for row in durable["payments"]] == ["BANK_IN"]
    assert len(durable["logs"]) == 1


def test_duplicate_that_idempotent_con_collision_amount_order_audit_roi_200(
    client, webhook_secret
):
    ctx = seller_with_shop(client)
    first_order = _create_order(client, ctx)
    second_order = _create_order(client, ctx)
    txn_id = f"P03-COLLISION-{uuid.uuid4().hex}"
    first_payload = {
        "content": f"ORDER{first_order}",
        "transferAmount": 40_000,
        "id": txn_id,
    }

    applied = _post(client, first_payload)
    duplicate = _post(client, first_payload)
    assert applied.status_code == duplicate.status_code == 200
    assert _snapshot(first_order)["order"][1] == 40_000
    assert len(_snapshot(first_order)["payments"]) == 1
    first_before_collision = _snapshot(first_order)
    second_before_collision = _snapshot(second_order)

    amount_collision = _post(
        client,
        {
            **first_payload,
            "transferAmount": 50_000,
            "id": f"  {txn_id}  ",
        },
    )
    order_collision_payload = {
        "content": f"ORDER{second_order}",
        "transferAmount": 40_000,
        "id": f" {txn_id} ",
    }
    order_collision = _post(client, order_collision_payload)
    order_collision_retry = _post(client, order_collision_payload)
    assert amount_collision.status_code == 200
    assert order_collision.status_code == order_collision_retry.status_code == 200
    assert amount_collision.json()["rejected_order_ids"] == [first_order]
    assert order_collision.json()["rejected_order_ids"] == [second_order]
    assert order_collision_retry.json()["rejected_order_ids"] == [second_order]

    first_after = _snapshot(first_order)
    second_after = _snapshot(second_order)
    assert first_after["order"] == first_before_collision["order"]
    assert first_after["payments"] == first_before_collision["payments"]
    assert second_after["order"] == second_before_collision["order"]
    assert second_after["payments"] == second_before_collision["payments"]
    first_collision_logs = [
        row for row in first_after["logs"]
        if row[0] == "WEBHOOK_XUNG_DOT_IDEMPOTENCY"
    ]
    second_collision_logs = [
        row for row in second_after["logs"]
        if row[0] == "WEBHOOK_XUNG_DOT_IDEMPOTENCY"
    ]
    assert len(first_collision_logs) == len(second_collision_logs) == 1
    assert txn_id not in first_collision_logs[0][1]
    assert txn_id not in second_collision_logs[0][1]


def test_batch_item_dau_commit_item_sau_fail_retry_toan_batch_dung_mot_lan(
    client, webhook_secret, monkeypatch
):
    ctx = seller_with_shop(client)
    first_order = _create_order(client, ctx)
    second_order = _create_order(client, ctx)
    payload = {
        "data": [
            {
                "description": f"ORDER{first_order}",
                "amount": TOTAL,
                "tid": f"P03-BATCH-A-{uuid.uuid4().hex}",
            },
            {
                "description": f"ORDER{second_order}",
                "amount": TOTAL,
                "tid": f"P03-BATCH-B-{uuid.uuid4().hex}",
            },
        ]
    }
    first_committed = threading.Event()
    calls = {"value": 0}
    original_commit = Session.commit

    def fail_second_commit(self, *args, **kwargs):
        calls["value"] += 1
        if calls["value"] == 1:
            result = original_commit(self, *args, **kwargs)
            first_committed.set()
            return result
        assert first_committed.wait(timeout=5), "item đầu chưa commit"
        raise RuntimeError("forced second batch item persistence failure")

    with monkeypatch.context() as injected:
        injected.setattr(Session, "commit", fail_second_commit)
        failed = _post(client, payload)

    assert failed.status_code == 500, failed.text
    assert first_committed.is_set()
    assert calls["value"] == 2
    first_after_failure = _snapshot(first_order)
    second_after_failure = _snapshot(second_order)
    assert first_after_failure["order"][0] == "PAID"
    assert [row[0] for row in first_after_failure["payments"]] == ["BANK_IN"]
    assert len(first_after_failure["logs"]) == 1
    assert second_after_failure["order"][0] == "PENDING"
    assert second_after_failure["payments"] == []
    assert second_after_failure["logs"] == []

    retry = _post(client, payload)
    final_retry = _post(client, payload)
    assert retry.status_code == final_retry.status_code == 200
    assert retry.json()["order_ids"] == [first_order, second_order]
    for order_id in (first_order, second_order):
        durable = _snapshot(order_id)
        assert durable["order"][0] == "PAID"
        assert [row[0] for row in durable["payments"]] == ["BANK_IN"]
        assert len(durable["logs"]) == 1


@pytest.mark.parametrize("legacy_padding", [False, True])
def test_bank_unapplied_shared_raw_txn_qua_provider_va_sau_thu_no(
    client, webhook_secret, legacy_padding
):
    ctx = seller_with_shop(client)
    customer = _create_customer(client, ctx)
    _enable_loyalty(client, ctx)
    order_id = _create_order(
        client,
        ctx,
        method="debt",
        customer_id=customer["id"],
    )
    txn_id = f"P03-SHARED-RAW-{uuid.uuid4().hex}"

    casso = {
        "data": [{
            "description": f"ORDER{order_id}",
            "amount": 40_000,
            "tid": f"  {txn_id}  " if legacy_padding else txn_id,
        }]
    }
    sepay = {
        "content": f"ORDER{order_id}",
        "transferAmount": 40_000,
        "id": f"{txn_id} " if legacy_padding else txn_id,
    }
    payos = {
        "data": {
            "orderCode": order_id,
            "description": f"ORDER{order_id}",
            "amount": 40_000,
            "referenceCode": f" {txn_id}" if legacy_padding else txn_id,
        }
    }

    first = _post(client, casso)
    assert first.status_code == 200
    first_durable = _snapshot(order_id)
    assert first_durable["payments"][0][4] == txn_id
    if legacy_padding:
        # Mô phỏng row cũ từng lưu transaction ID chưa strip. Lookup vẫn phải
        # tương thích nhưng chỉ được scan trong chính order này.
        legacy = SessionLocal()
        try:
            payment = (
                legacy.query(models.OrderPayment)
                .filter(models.OrderPayment.order_id == order_id)
                .one()
            )
            payment.bank_txn_id = f"  {txn_id}  "
            legacy.commit()
        finally:
            legacy.close()
    changed_provider = _post(client, sepay)
    assert changed_provider.status_code == 200
    assert first.json()["rejected_order_ids"] == [order_id]
    assert changed_provider.json()["rejected_order_ids"] == [order_id]
    before_collection = _snapshot(order_id)
    assert [row[0] for row in before_collection["payments"]] == [
        "BANK_UNAPPLIED"
    ]
    assert len([
        row for row in before_collection["logs"]
        if row[0] == "WEBHOOK_TU_CHOI" and "BANK_UNAPPLIED" in row[1]
    ]) == 1

    collected = _direct_debt_payment(ctx, order_id)
    assert collected["status"] == "PAID"
    after_collection = _snapshot(order_id)
    after_collection_retry = _post(client, payos)
    assert after_collection_retry.status_code == 200
    assert after_collection_retry.json()["order_ids"] == [order_id]

    durable = _snapshot(order_id)
    assert durable["order"][0] == "PAID"
    assert durable["order"][1] == TOTAL
    assert durable["order"][4] != "OVERPAID"
    assert durable["order"][6] in (None, 0)
    assert durable["payments"] == after_collection["payments"]
    assert durable["loyalty"] == after_collection["loyalty"]
    assert [row[0] for row in durable["payments"]] == [
        "BANK_UNAPPLIED",
        "DEBT_TRANSFER",
    ]
    assert len([
        row for row in durable["logs"]
        if row[0] == "WEBHOOK_TU_CHOI" and "BANK_UNAPPLIED" in row[1]
    ]) == 1


@pytest.mark.parametrize("padded", [False, True])
def test_same_raw_txn_hai_shop_provider_account_duoc_ap_doc_lap_concurrent(
    client, webhook_secret, padded
):
    first_ctx = seller_with_shop(client)
    second_ctx = seller_with_shop(client)
    second_account = "0987654321"
    updated = _update_shop_account(client, second_ctx, second_account)
    assert updated.status_code == 200, updated.text
    first_order = _create_order(client, first_ctx)
    second_order = _create_order(client, second_ctx)
    raw_txn = f"P03-SAME-RAW-TWO-SHOPS-{uuid.uuid4().hex}"
    envelope_txn = f"  {raw_txn}  " if padded else raw_txn
    payloads = {
        "first": {
            "data": [{
                "description": f"ORDER{first_order}",
                "amount": TOTAL,
                "tid": envelope_txn,
                "accountNumber": SHOP_PAYLOAD["bank_account_no"],
            }]
        },
        "second": {
            "content": f"ORDER{second_order}",
            "transferAmount": TOTAL,
            "id": envelope_txn,
            "accountNumber": second_account,
        },
    }
    barrier = threading.Barrier(3)
    outcomes = {}

    def run(name):
        try:
            barrier.wait(timeout=5)
            outcomes[name] = _direct_webhook(payloads[name])
        except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
            outcomes[name] = {"error": (type(exc).__name__, str(exc))}

    workers = [
        threading.Thread(target=run, args=(name,), name=f"raw-{name}")
        for name in ("first", "second")
    ]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=5)
    for worker in workers:
        worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    assert "error" not in outcomes["first"], outcomes
    assert "error" not in outcomes["second"], outcomes
    assert outcomes["first"]["paid"] == [first_order]
    assert outcomes["second"]["paid"] == [second_order]
    for order_id in (first_order, second_order):
        durable = _snapshot(order_id)
        assert durable["order"][0] == "PAID"
        assert len(durable["payments"]) == 1
        assert durable["payments"][0][0] == "BANK_IN"
        assert durable["payments"][0][4] == raw_txn
        assert not any(
            row[0] == "WEBHOOK_XUNG_DOT_IDEMPOTENCY"
            for row in durable["logs"]
        )


@pytest.mark.parametrize("fault", ["audit", "commit"])
def test_account_mismatch_audit_commit_fault_rollback_va_retry(
    client, webhook_secret, monkeypatch, fault
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": TOTAL,
        "accountNumber": "9999999999",
        "id": f"P03-MISMATCH-{fault}-{uuid.uuid4().hex}",
    }
    before = _snapshot(order_id)

    with monkeypatch.context() as injected:
        raised = _install_fault(injected, fault)
        failed = _post(client, payload)

    assert raised["value"] is True
    assert failed.status_code == 500, failed.text
    assert _snapshot(order_id) == before

    first = _post(client, payload)
    retry = _post(client, payload)
    assert first.status_code == retry.status_code == 200
    assert first.json()["rejected_order_ids"] == [order_id]
    durable = _snapshot(order_id)
    assert durable["order"] == before["order"]
    assert durable["payments"] == []
    assert durable["loyalty"] == []
    mismatch_logs = [
        row for row in durable["logs"]
        if row[0] == "WEBHOOK_TU_CHOI" and "ACCOUNT_MISMATCH" in row[1]
    ]
    assert len(mismatch_logs) == 1


@pytest.mark.parametrize("winner", ["update", "webhook"])
def test_concurrent_bank_account_update_webhook_quyet_dinh_duoi_shop_lock(
    client, webhook_secret, monkeypatch, winner
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    before = _snapshot(order_id)
    old_account = SHOP_PAYLOAD["bank_account_no"]
    new_account = "0987654321"
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": TOTAL,
        "accountNumber": new_account,
        "id": f"P03-ACCOUNT-RACE-{winner}-{uuid.uuid4().hex}",
    }
    reached_lock = threading.Event()
    release_lock = threading.Event()
    outcomes = {}

    if winner == "update":
        real_webhook_lock = order_service._lock_shop_for_order

        def block_webhook_before_lock(db, shop_id):
            reached_lock.set()
            assert release_lock.wait(timeout=5), "webhook lock was not released"
            return real_webhook_lock(db, shop_id)

        monkeypatch.setattr(
            order_service,
            "_lock_shop_for_order",
            block_webhook_before_lock,
        )

        def run_blocked():
            try:
                outcomes["webhook"] = _post(client, payload)
            except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
                outcomes["thread_error"] = (type(exc).__name__, str(exc))

        blocked = threading.Thread(target=run_blocked, name="blocked-webhook")
        blocked.start()
        assert reached_lock.wait(timeout=5), "webhook did not reach shop lock"
        try:
            outcomes["update"] = _direct_update_shop_account(ctx, new_account)
            assert outcomes["update"] == new_account
            assert _durable_shop_account(ctx["shop_id"]) == new_account
        finally:
            release_lock.set()
    else:
        real_update_lock = shop_service._lock_shop_for_write

        def block_update_before_lock(db, shop_id, owner_id):
            reached_lock.set()
            assert release_lock.wait(timeout=5), "update lock was not released"
            return real_update_lock(db, shop_id, owner_id)

        monkeypatch.setattr(
            shop_service,
            "_lock_shop_for_write",
            block_update_before_lock,
        )

        def run_blocked():
            try:
                outcomes["update"] = _direct_update_shop_account(ctx, new_account)
            except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
                outcomes["thread_error"] = (type(exc).__name__, str(exc))

        blocked = threading.Thread(target=run_blocked, name="blocked-update")
        blocked.start()
        assert reached_lock.wait(timeout=5), "update did not reach shop lock"
        assert _durable_shop_account(ctx["shop_id"]) == old_account
        try:
            outcomes["webhook"] = _post(client, payload)
        finally:
            release_lock.set()

    blocked.join(timeout=10)
    assert not blocked.is_alive()
    assert "thread_error" not in outcomes, outcomes.get("thread_error")
    assert outcomes["update"] == new_account
    assert outcomes["webhook"].status_code == 200, outcomes["webhook"].text
    assert _durable_shop_account(ctx["shop_id"]) == new_account

    durable = _snapshot(order_id)
    mismatch_logs = [
        row for row in durable["logs"]
        if row[0] == "WEBHOOK_TU_CHOI" and "ACCOUNT_MISMATCH" in row[1]
    ]
    if winner == "update":
        assert outcomes["webhook"].json()["order_ids"] == [order_id]
        assert durable["order"][0] == "PAID"
        assert [row[0] for row in durable["payments"]] == ["BANK_IN"]
        assert mismatch_logs == []
    else:
        assert outcomes["webhook"].json()["rejected_order_ids"] == [order_id]
        assert durable["order"] == before["order"]
        assert durable["payments"] == before["payments"] == []
        assert durable["loyalty"] == before["loyalty"] == []
        assert len(mismatch_logs) == 1


def test_lock_order_create_order_va_thu_no_tien_mat_la_shop_roi_cash_shift(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    customer = _create_customer(client, ctx)
    debt_order = _create_order(
        client,
        ctx,
        method="debt",
        customer_id=customer["id"],
    )
    opened = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": 500_000},
        headers=auth(ctx["token"]),
    )
    assert opened.status_code == 200, opened.text

    calls = []
    real_shop_lock = order_service._lock_shop_for_order
    real_cash_shift = order_service._current_cash_shift

    def record_shop_lock(*args, **kwargs):
        calls.append("shop")
        return real_shop_lock(*args, **kwargs)

    def record_cash_shift(*args, **kwargs):
        calls.append("cash_shift")
        return real_cash_shift(*args, **kwargs)

    monkeypatch.setattr(order_service, "_lock_shop_for_order", record_shop_lock)
    monkeypatch.setattr(order_service, "_current_cash_shift", record_cash_shift)

    _create_order(client, ctx, method="cash")
    assert calls == ["shop", "cash_shift"]

    calls.clear()
    collected = client.post(
        f"/api/orders/{debt_order}/debt-payment",
        json={
            "amount": TOTAL,
            "method": "cash",
            "operation_id": uuid.uuid4().hex,
        },
        headers=auth(ctx["token"]),
    )
    assert collected.status_code == 200, collected.text
    assert calls == ["shop", "cash_shift"]


def test_http_exception_noi_bo_sau_mutation_thanh_500_va_rollback(
    client, webhook_secret, monkeypatch
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": TOTAL,
        "id": f"P03-INTERNAL-HTTP-{uuid.uuid4().hex}",
    }
    before = _snapshot(order_id)

    def loyalty_http_failure(*_args, **_kwargs):
        raise HTTPException(status_code=409, detail="forced internal conflict")

    with monkeypatch.context() as injected:
        injected.setattr(
            order_service,
            "_award_loyalty_paid_order",
            loyalty_http_failure,
        )
        failed = _post(client, payload)

    assert failed.status_code == 500, failed.text
    assert _snapshot(order_id) == before
    applied = _post(client, payload)
    duplicate = _post(client, payload)
    assert applied.status_code == duplicate.status_code == 200
    durable = _snapshot(order_id)
    assert durable["order"][0] == "PAID"
    assert [row[0] for row in durable["payments"]] == ["BANK_IN"]
    assert len([
        row for row in durable["logs"] if row[0] == "WEBHOOK_PAYMENT"
    ]) == 1


def test_collision_audit_failure_thanh_5xx_roi_retry_audit_dung_mot_lan(
    client, webhook_secret, monkeypatch
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    txn_id = f"P03-COLLISION-AUDIT-{uuid.uuid4().hex}"
    original = {
        "content": f"ORDER{order_id}",
        "transferAmount": 40_000,
        "id": txn_id,
    }
    assert _post(client, original).status_code == 200
    before = _snapshot(order_id)
    real_audit = order_service._them_nhat_ky

    def fail_collision_audit(db, user_id, action, details, **kwargs):
        if action == "WEBHOOK_XUNG_DOT_IDEMPOTENCY":
            raise RuntimeError("forced collision audit failure")
        return real_audit(db, user_id, action, details, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(order_service, "_them_nhat_ky", fail_collision_audit)
        failed = _post(
            client,
            {**original, "transferAmount": 50_000},
        )

    assert failed.status_code == 500, failed.text
    assert _snapshot(order_id) == before

    first = _post(client, {**original, "transferAmount": 50_000})
    retry = _post(client, {**original, "transferAmount": 50_000})
    assert first.status_code == retry.status_code == 200
    assert first.json()["rejected_order_ids"] == [order_id]
    durable = _snapshot(order_id)
    assert durable["payments"] == before["payments"]
    assert len([
        row for row in durable["logs"]
        if row[0] == "WEBHOOK_XUNG_DOT_IDEMPOTENCY"
    ]) == 1


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(TOTAL, "paid"), (40_000, "unreconciled")],
)
def test_duplicate_phan_loai_order_tu_session_sach_khong_dung_object_pending_cu(
    client, webhook_secret, amount, expected
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": amount,
        "id": f"P03-STALE-CLASSIFY-{expected}-{uuid.uuid4().hex}",
    }
    gd = payment_service.extract_transactions(payload)[0]
    key = order_service._bank_idempotency_key(gd)

    loser = SessionLocal()
    try:
        stale_order = (
            loser.query(models.Order).filter(models.Order.id == order_id).one()
        )
        assert stale_order.status == "PENDING"

        winner = _direct_webhook(payload)
        assert winner[expected] == [order_id]
        existing = (
            loser.query(models.OrderPayment)
            .filter(models.OrderPayment.idempotency_key == key)
            .all()
        )
        assert stale_order.status == "PENDING"

        outcome = order_service._duplicate_or_collision_outcome(
            loser,
            order=stale_order,
            gd=gd,
            amount=float(amount),
            existing=existing,
            key=key,
        )
    finally:
        loser.close()

    assert outcome == expected


@pytest.mark.parametrize("winner", ["manual", "webhook"])
def test_debt_payment_va_webhook_tuan_tu_hoa_truoc_khi_chon_ledger(
    client, webhook_secret, monkeypatch, winner
):
    ctx = seller_with_shop(client)
    customer = _create_customer(client, ctx)
    order_id = _create_order(
        client,
        ctx,
        method="debt",
        customer_id=customer["id"],
    )
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": 40_000,
        "id": f"P03-DEBT-RACE-{winner}-{uuid.uuid4().hex}",
    }
    blocked_name = "webhook-worker" if winner == "manual" else "manual-worker"
    reached_lock = threading.Event()
    release_lock = threading.Event()
    real_lock = order_service._lock_shop_for_order
    outcomes = {}

    def controlled_lock(db, shop_id):
        if threading.current_thread().name == blocked_name:
            reached_lock.set()
            assert release_lock.wait(timeout=5), "race lock was not released"
        return real_lock(db, shop_id)

    def run_blocked():
        try:
            if blocked_name == "webhook-worker":
                outcomes["webhook"] = _direct_webhook(payload)
            else:
                outcomes["manual"] = _direct_debt_payment(ctx, order_id)
        except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
            outcomes["error"] = (type(exc).__name__, str(exc))

    monkeypatch.setattr(order_service, "_lock_shop_for_order", controlled_lock)
    blocked = threading.Thread(target=run_blocked, name=blocked_name)
    blocked.start()
    assert reached_lock.wait(timeout=5), "blocked request did not reach write lock"

    if winner == "manual":
        outcomes["manual"] = _direct_debt_payment(ctx, order_id)
    else:
        outcomes["webhook"] = _direct_webhook(payload)
    release_lock.set()
    blocked.join(timeout=10)

    assert not blocked.is_alive()
    assert "error" not in outcomes, outcomes.get("error")
    durable = _snapshot(order_id)
    entry_types = [row[0] for row in durable["payments"]]
    if winner == "manual":
        assert entry_types == ["DEBT_TRANSFER", "BANK_IN"]
        assert "BANK_UNAPPLIED" not in entry_types
        assert durable["order"][1] == TOTAL + 40_000
        assert durable["order"][4] == "OVERPAID"
        assert durable["order"][6] == 40_000
    else:
        assert entry_types == ["BANK_UNAPPLIED", "DEBT_TRANSFER"]
        assert durable["order"][1] == TOTAL
        assert durable["order"][4] != "OVERPAID"
        assert durable["order"][6] in (None, 0)


@pytest.mark.parametrize(
    ("loser_amount", "loser_bucket", "collision"),
    [(40_000, "unreconciled", False), (50_000, "rejected", True)],
)
def test_integrityerror_fresh_session_thay_durable_winner(
    client,
    webhook_secret,
    monkeypatch,
    loser_amount,
    loser_bucket,
    collision,
):
    ctx = seller_with_shop(client)
    order_id = _create_order(client, ctx)
    txn_id = f"P03-FRESH-WINNER-{uuid.uuid4().hex}"
    winner_payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": 40_000,
        "id": txn_id,
    }
    loser_payload = {**winner_payload, "transferAmount": loser_amount}
    loser_prequery_done = threading.Event()
    winner_committed = threading.Event()
    fresh_path_seen = threading.Event()
    real_find = order_service._find_existing_bank_events
    real_fresh = order_service._fresh_duplicate_outcome
    real_flush = Session.flush
    real_commit = Session.commit
    loser_find_calls = {"value": 0}
    outcomes = {}

    # Bỏ shop lock chỉ trong test này để ép đúng hàng rào unique cuối cùng. Hai
    # request vẫn dùng Session riêng và winner thật sự commit trước loser flush.
    monkeypatch.setattr(order_service, "_lock_shop_for_order", lambda *_args: None)

    def synchronized_find(db, *, key, order_id, gd):
        if threading.current_thread().name == "loser":
            loser_find_calls["value"] += 1
            if loser_find_calls["value"] == 1:
                loser_prequery_done.set()
                return []
        return real_find(db, key=key, order_id=order_id, gd=gd)

    def synchronized_flush(self, *args, **kwargs):
        if threading.current_thread().name == "loser":
            assert winner_committed.wait(timeout=5), "winner did not commit"
        return real_flush(self, *args, **kwargs)

    def synchronized_commit(self, *args, **kwargs):
        result = real_commit(self, *args, **kwargs)
        if threading.current_thread().name == "winner":
            winner_committed.set()
        return result

    def tracked_fresh(*args, **kwargs):
        if threading.current_thread().name == "loser":
            fresh_path_seen.set()
        return real_fresh(*args, **kwargs)

    monkeypatch.setattr(order_service, "_find_existing_bank_events", synchronized_find)
    monkeypatch.setattr(order_service, "_fresh_duplicate_outcome", tracked_fresh)
    monkeypatch.setattr(Session, "flush", synchronized_flush)
    monkeypatch.setattr(Session, "commit", synchronized_commit)

    def run(name, payload):
        try:
            outcomes[name] = _direct_webhook(payload)
        except Exception as exc:  # pragma: no cover - làm lỗi thread hiện rõ
            outcomes[name] = {"error": (type(exc).__name__, str(exc))}

    loser = threading.Thread(
        target=run,
        args=("loser", loser_payload),
        name="loser",
    )
    loser.start()
    assert loser_prequery_done.wait(timeout=5), "loser did not pass prequery"
    winner = threading.Thread(
        target=run,
        args=("winner", winner_payload),
        name="winner",
    )
    winner.start()
    winner.join(timeout=10)
    loser.join(timeout=10)

    assert not winner.is_alive() and not loser.is_alive()
    assert fresh_path_seen.is_set(), outcomes
    assert "error" not in outcomes["winner"], outcomes
    assert "error" not in outcomes["loser"], outcomes
    assert outcomes["winner"]["unreconciled"] == [order_id]
    assert outcomes["loser"][loser_bucket] == [order_id]
    durable = _snapshot(order_id)
    assert [row[0] for row in durable["payments"]] == ["BANK_IN"]
    collision_logs = [
        row for row in durable["logs"]
        if row[0] == "WEBHOOK_XUNG_DOT_IDEMPOTENCY"
    ]
    assert len(collision_logs) == (1 if collision else 0)
