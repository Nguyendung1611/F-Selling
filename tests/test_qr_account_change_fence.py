"""I10-C bank-account snapshot fence and deterministic cross-operation races."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

from fastapi import HTTPException

from conftest import SHOP_PAYLOAD, admin_token, auth, new_staff, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.schemas.order import OrderCreate
from fselling.schemas.qr_reconciliation import ReconciliationActionRequest
from fselling.schemas.shop import ShopCreate
from fselling.services import (
    maintenance_service,
    order_service,
    qr_reconciliation_service,
    qr_sales_service,
    qr_webhook_service,
    shop_service,
)
from i10c_helpers import (
    create_intent_context,
    enable_webhook,
    ingest_ready,
    post_event,
    ready_payload,
)


def _shop_payload(*, bank_no="99887766", name=None) -> dict:
    payload = dict(SHOP_PAYLOAD)
    payload["bank_code"] = "MB"
    payload["bank_account_no"] = bank_no
    payload["bank_account_name"] = "TAI KHOAN MOI"
    if name is not None:
        payload["name"] = name
    return payload


def _order_request(ctx: dict) -> OrderCreate:
    return OrderCreate.model_validate(
        {
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "product_name": ctx["product"]["name"],
                    "price": 1,
                    "quantity": 1,
                }
            ],
            "payment_method": "transfer",
            "operation_id": uuid.uuid4().hex,
        }
    )


def _reject_event(client, token: str, event_id: int) -> None:
    response = client.post(
        f"/api/qr-reconciliation/events/{event_id}/actions",
        json={
            "expected_state_version": 0,
            "action": "REJECT_NOT_OURS",
            "note": "Giao dịch không thuộc cửa hàng",
        },
        headers=auth(token),
    )
    assert response.status_code == 200, response.text


def _collision_evidence(
    ctx: dict, provider_event_id: str, *, exact_reference: bool = False
):
    return qr_webhook_service.NormalizedBankEvent(
        provider="mock_bank",
        provider_event_id=provider_event_id,
        normalized_account_no=ctx["account_no"],
        direction="IN",
        amount_vnd=ctx["expected_vnd"] + 1,
        reference_state="EXACT" if exact_reference else "MISSING",
        normalized_reference=ctx["reference"] if exact_reference else None,
        occurred_at="2026-08-13 01:02:03.000000",
    )


def test_only_actual_bank_changes_are_fenced_and_off_does_not_waive_evidence(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    # An unrelated edit retains the exact bank snapshot and remains available.
    unrelated = dict(SHOP_PAYLOAD)
    unrelated["name"] = "Tên mới không đổi ngân hàng"
    response = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=unrelated,
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text

    # Turn the QR runtime back OFF: durable v1 evidence still protects itself.
    disabled = qr_sales_service.QrSalesRuntime(
        mode="OFF", adapter=qr_sales_service.DisabledQrAdapter()
    )
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: disabled)
    blocked = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(),
        headers=auth(ctx["token"]),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "QR_BANK_ACCOUNT_CHANGE_BLOCKED"
    session = SessionLocal()
    try:
        intent = session.query(models.QrPaymentIntent).filter_by(
            id=ctx["intent_id"]
        ).one()
        shop = session.query(models.Shop).filter_by(id=ctx["shop_id"]).one()
        assert intent.account_no == ctx["account_no"]
        assert shop.bank_account_no == SHOP_PAYLOAD["bank_account_no"]
    finally:
        session.close()


def test_every_event_must_be_terminal_before_bank_change(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    first = ingest_ready(client, monkeypatch, ctx, provider_event_id="evt-fence-one")
    second = ingest_ready(client, monkeypatch, ctx, provider_event_id="evt-fence-two")
    reject = {
        "expected_state_version": 0,
        "action": "REJECT_NOT_OURS",
        "note": "Giao dịch không thuộc cửa hàng",
    }
    assert client.post(
        f"/api/qr-reconciliation/events/{first['id']}/actions",
        json=reject,
        headers=auth(ctx["token"]),
    ).status_code == 200
    still_blocked = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(),
        headers=auth(ctx["token"]),
    )
    assert still_blocked.status_code == 409
    assert client.post(
        f"/api/qr-reconciliation/events/{second['id']}/actions",
        json=reject,
        headers=auth(ctx["token"]),
    ).status_code == 200
    allowed = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(),
        headers=auth(ctx["token"]),
    )
    assert allowed.status_code == 200, allowed.text
    session = SessionLocal()
    try:
        intent = session.query(models.QrPaymentIntent).filter_by(
            id=ctx["intent_id"]
        ).one()
        shop = session.query(models.Shop).filter_by(id=ctx["shop_id"]).one()
        assert intent.account_no == ctx["account_no"]
        assert shop.bank_account_no == "99887766"
    finally:
        session.close()


def test_unscoped_provider_collision_lineage_blocks_until_admin_terminal(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    identity = f"evt-fence-collision-{uuid.uuid4().hex}"
    original = post_event(
        client,
        runtime,
        ready_payload(ctx, provider_event_id=identity),
    ).json()
    _reject_event(client, ctx["token"], original["id"])

    collision_response = post_event(
        client,
        runtime,
        ready_payload(
            ctx,
            provider_event_id=identity,
            amount_vnd=ctx["expected_vnd"] + 1,
            references=None,
        ),
    )
    assert collision_response.status_code == 200, collision_response.text
    collision = collision_response.json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"
    assert collision["intent_id"] is None and collision["shop_id"] is None
    assert client.get(
        f"/api/qr-reconciliation/events/{collision['id']}",
        headers=auth(ctx["token"]),
    ).status_code == 404

    blocked = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(),
        headers=auth(ctx["token"]),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "QR_BANK_ACCOUNT_CHANGE_BLOCKED"

    admin = admin_token(client)
    terminal = client.post(
        f"/api/qr-reconciliation/events/{collision['id']}/actions",
        json={
            "expected_state_version": 0,
            "action": "REJECT_NOT_OURS",
            "note": "Bằng chứng xung đột ngoài phạm vi cửa hàng",
        },
        headers=auth(admin),
    )
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["event"]["disposition"] == "REJECTED_NOT_OURS"

    allowed = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(),
        headers=auth(ctx["token"]),
    )
    assert allowed.status_code == 200, allowed.text


def test_cross_shop_exact_collision_never_acquires_scope_or_fences_target_shop(
    client, monkeypatch
):
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    _manager_name, manager_b = new_staff(client, shop_b, "MANAGER")
    identity = f"evt-cross-shop-{uuid.uuid4().hex}"

    root_a = ingest_ready(
        client, monkeypatch, shop_a, provider_event_id=identity
    )
    root_b = ingest_ready(
        client,
        monkeypatch,
        shop_b,
        provider_event_id=f"evt-shop-b-root-{uuid.uuid4().hex}",
    )
    _reject_event(client, shop_a["token"], root_a["id"])
    _reject_event(client, shop_b["token"], root_b["id"])

    runtime = enable_webhook(monkeypatch)
    collision_response = post_event(
        client,
        runtime,
        ready_payload(
            shop_b,
            provider_event_id=identity,
            amount_vnd=shop_b["expected_vnd"] + 1,
        ),
    )
    assert collision_response.status_code == 200, collision_response.text
    collision = collision_response.json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"
    assert collision["intent_id"] is None
    assert collision["order_id"] is None
    assert collision["shop_id"] is None

    for token in (shop_a["token"], shop_b["token"], manager_b):
        assert client.get(
            f"/api/qr-reconciliation/events/{collision['id']}",
            headers=auth(token),
        ).status_code == 404
        assert client.post(
            f"/api/qr-reconciliation/events/{collision['id']}/actions",
            json={"expected_state_version": 0, "action": "KEEP_OPEN"},
            headers=auth(token),
        ).status_code == 404

    # Shop B's own lineage is terminal. The collision's exact B reference is
    # untrusted and therefore cannot block B or grant B visibility.
    update_b = client.put(
        f"/api/shops/{shop_b['shop_id']}",
        json=_shop_payload(bank_no="88770001"),
        headers=auth(shop_b["token"]),
    )
    assert update_b.status_code == 200, update_b.text

    # The durable provider identity came from root A, so A remains fenced.
    blocked_a = client.put(
        f"/api/shops/{shop_a['shop_id']}",
        json=_shop_payload(bank_no="88770002"),
        headers=auth(shop_a["token"]),
    )
    assert blocked_a.status_code == 409
    admin = admin_token(client)
    terminal = client.post(
        f"/api/qr-reconciliation/events/{collision['id']}/actions",
        json={
            "expected_state_version": 0,
            "action": "REJECT_NOT_OURS",
            "note": "Bằng chứng xung đột do quản trị viên xử lý",
        },
        headers=auth(admin),
    )
    assert terminal.status_code == 200, terminal.text
    allowed_a = client.put(
        f"/api/shops/{shop_a['shop_id']}",
        json=_shop_payload(bank_no="88770002"),
        headers=auth(shop_a["token"]),
    )
    assert allowed_a.status_code == 200, allowed_a.text


def test_unknown_unscoped_root_collision_cannot_create_arbitrary_shop_fence(
    client, monkeypatch
):
    shop_b = create_intent_context(client, monkeypatch)
    own_root = ingest_ready(
        client,
        monkeypatch,
        shop_b,
        provider_event_id=f"evt-known-b-{uuid.uuid4().hex}",
    )
    _reject_event(client, shop_b["token"], own_root["id"])

    identity = f"evt-unknown-root-{uuid.uuid4().hex}"
    runtime = enable_webhook(monkeypatch)
    unknown_root = post_event(
        client,
        runtime,
        ready_payload(
            shop_b,
            provider_event_id=identity,
            references="FS1-UNKNOWN-ROOT",
        ),
    ).json()
    collision = post_event(
        client,
        runtime,
        ready_payload(
            shop_b,
            provider_event_id=identity,
            amount_vnd=shop_b["expected_vnd"] + 1,
        ),
    ).json()
    assert unknown_root["reason_code"] == "REFERENCE_UNKNOWN"
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"
    for evidence in (unknown_root, collision):
        assert evidence["intent_id"] is None
        assert evidence["order_id"] is None
        assert evidence["shop_id"] is None
        assert client.get(
            f"/api/qr-reconciliation/events/{evidence['id']}",
            headers=auth(shop_b["token"]),
        ).status_code == 404

    allowed_b = client.put(
        f"/api/shops/{shop_b['shop_id']}",
        json=_shop_payload(bank_no="88771111"),
        headers=auth(shop_b["token"]),
    )
    assert allowed_b.status_code == 200, allowed_b.text
    admin = admin_token(client)
    for evidence in (unknown_root, collision):
        assert client.get(
            f"/api/qr-reconciliation/events/{evidence['id']}",
            headers=auth(admin),
        ).status_code == 200


def test_unrelated_unscoped_provider_identity_does_not_block_shop(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    original = ingest_ready(
        client,
        monkeypatch,
        ctx,
        provider_event_id=f"evt-related-{uuid.uuid4().hex}",
    )
    _reject_event(client, ctx["token"], original["id"])
    runtime = enable_webhook(monkeypatch)
    unrelated = post_event(
        client,
        runtime,
        ready_payload(
            ctx,
            provider_event_id=f"evt-unrelated-{uuid.uuid4().hex}",
            references=None,
        ),
    ).json()
    assert unrelated["shop_id"] is None
    assert unrelated["disposition"] == "UNAPPLIED"
    assert client.get(
        f"/api/qr-reconciliation/events/{unrelated['id']}",
        headers=auth(ctx["token"]),
    ).status_code == 404

    allowed = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(),
        headers=auth(ctx["token"]),
    )
    assert allowed.status_code == 200, allowed.text


def test_collision_ingest_wins_then_account_update_is_blocked_without_sleep(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    identity = f"evt-ingest-first-{uuid.uuid4().hex}"
    original = ingest_ready(
        client, monkeypatch, ctx, provider_event_id=identity
    )
    _reject_event(client, ctx["token"], original["id"])
    session = SessionLocal()
    try:
        actor_id = session.query(models.User).filter_by(
            username=ctx["username"]
        ).one().id
    finally:
        session.close()

    collision_at_commit = threading.Event()
    allow_collision_commit = threading.Event()
    update_at_lock = threading.Event()
    real_commit = qr_webhook_service._commit_inbox
    real_update_lock = shop_service._lock_shop_for_write

    def hold_collision_commit(db):
        collision_at_commit.set()
        assert allow_collision_commit.wait(timeout=5)
        real_commit(db)

    def observe_update_lock(db, shop_id, owner_id):
        update_at_lock.set()
        return real_update_lock(db, shop_id, owner_id)

    monkeypatch.setattr(qr_webhook_service, "_commit_inbox", hold_collision_commit)
    monkeypatch.setattr(shop_service, "_lock_shop_for_write", observe_update_lock)
    outcomes: dict[str, object] = {}

    def ingest_collision():
        db = SessionLocal()
        try:
            row, _replay = qr_webhook_service.ingest_normalized(
                db,
                _collision_evidence(ctx, identity, exact_reference=True),
                f"collision-{uuid.uuid4().hex}".encode("ascii"),
            )
            outcomes["ingest"] = (
                row.reason_code,
                row.intent_id,
                row.order_id,
                row.shop_id,
            )
        finally:
            db.close()

    def update():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            shop_service.update_shop(
                db, actor, ctx["shop_id"], ShopCreate.model_validate(_shop_payload())
            )
            outcomes["update"] = "ok"
        except HTTPException as exc:
            outcomes["update"] = f"http:{exc.status_code}"
        finally:
            db.close()

    ingest_thread = threading.Thread(target=ingest_collision)
    update_thread = threading.Thread(target=update)
    ingest_thread.start()
    assert collision_at_commit.wait(timeout=5)
    update_thread.start()
    assert update_at_lock.wait(timeout=5)
    allow_collision_commit.set()
    ingest_thread.join(timeout=10)
    update_thread.join(timeout=10)
    assert not ingest_thread.is_alive() and not update_thread.is_alive()
    assert outcomes == {
        "ingest": ("PROVIDER_EVENT_COLLISION", None, None, None),
        "update": "http:409",
    }


def test_account_update_wins_then_collision_ingest_is_ordered_without_sleep(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    identity = f"evt-update-first-{uuid.uuid4().hex}"
    original = ingest_ready(
        client, monkeypatch, ctx, provider_event_id=identity
    )
    _reject_event(client, ctx["token"], original["id"])
    session = SessionLocal()
    try:
        actor_id = session.query(models.User).filter_by(
            username=ctx["username"]
        ).one().id
    finally:
        session.close()

    update_holds_lock = threading.Event()
    allow_update = threading.Event()
    ingest_at_lock = threading.Event()
    real_fence = shop_service._assert_qr_account_change_allowed
    real_ingest_lock = qr_webhook_service._acquire_inbox_write_lock

    def hold_after_fence(db, shop_id):
        real_fence(db, shop_id)
        update_holds_lock.set()
        assert allow_update.wait(timeout=5)

    def observe_ingest_lock(db):
        ingest_at_lock.set()
        return real_ingest_lock(db)

    monkeypatch.setattr(shop_service, "_assert_qr_account_change_allowed", hold_after_fence)
    monkeypatch.setattr(qr_webhook_service, "_acquire_inbox_write_lock", observe_ingest_lock)
    outcomes: dict[str, object] = {}

    def update():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            shop_service.update_shop(
                db, actor, ctx["shop_id"], ShopCreate.model_validate(_shop_payload())
            )
            outcomes["update"] = "ok"
        finally:
            db.close()

    def ingest_collision():
        db = SessionLocal()
        try:
            row, _replay = qr_webhook_service.ingest_normalized(
                db,
                _collision_evidence(ctx, identity, exact_reference=True),
                f"collision-{uuid.uuid4().hex}".encode("ascii"),
            )
            outcomes["ingest"] = (
                row.reason_code,
                row.intent_id,
                row.order_id,
                row.shop_id,
            )
        finally:
            db.close()

    update_thread = threading.Thread(target=update)
    ingest_thread = threading.Thread(target=ingest_collision)
    update_thread.start()
    assert update_holds_lock.wait(timeout=5)
    ingest_thread.start()
    assert ingest_at_lock.wait(timeout=5)
    allow_update.set()
    update_thread.join(timeout=10)
    ingest_thread.join(timeout=10)
    assert not update_thread.is_alive() and not ingest_thread.is_alive()
    assert outcomes == {
        "update": "ok",
        "ingest": ("PROVIDER_EVENT_COLLISION", None, None, None),
    }
    session = SessionLocal()
    try:
        assert session.query(models.Shop).filter_by(
            id=ctx["shop_id"]
        ).one().bank_account_no == "99887766"
        collision = session.query(models.BankWebhookEvent).filter_by(
            provider_event_id=identity,
            reason_code="PROVIDER_EVENT_COLLISION",
        ).one()
        assert collision.shop_id is None and collision.disposition == "UNAPPLIED"
    finally:
        session.close()
    blocked_again = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json=_shop_payload(bank_no="88776655"),
        headers=auth(ctx["token"]),
    )
    assert blocked_again.status_code == 409


def test_concurrent_cross_shop_collision_never_leaks_target_tenant_without_sleep(
    client, monkeypatch
):
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    identity = f"evt-cross-race-{uuid.uuid4().hex}"
    root_a = ingest_ready(
        client, monkeypatch, shop_a, provider_event_id=identity
    )
    root_b = ingest_ready(
        client,
        monkeypatch,
        shop_b,
        provider_event_id=f"evt-b-race-root-{uuid.uuid4().hex}",
    )
    _reject_event(client, shop_a["token"], root_a["id"])
    _reject_event(client, shop_b["token"], root_b["id"])
    session = SessionLocal()
    try:
        actor_b_id = session.query(models.User).filter_by(
            username=shop_b["username"]
        ).one().id
    finally:
        session.close()

    collision_at_commit = threading.Event()
    allow_collision_commit = threading.Event()
    update_b_at_lock = threading.Event()
    real_commit = qr_webhook_service._commit_inbox
    real_update_lock = shop_service._lock_shop_for_write

    def hold_collision_commit(db):
        collision_at_commit.set()
        assert allow_collision_commit.wait(timeout=5)
        real_commit(db)

    def observe_update_b_lock(db, shop_id, owner_id):
        update_b_at_lock.set()
        return real_update_lock(db, shop_id, owner_id)

    monkeypatch.setattr(qr_webhook_service, "_commit_inbox", hold_collision_commit)
    monkeypatch.setattr(shop_service, "_lock_shop_for_write", observe_update_b_lock)
    outcomes: dict[str, object] = {}

    def ingest_collision():
        db = SessionLocal()
        try:
            row, _replay = qr_webhook_service.ingest_normalized(
                db,
                _collision_evidence(shop_b, identity, exact_reference=True),
                f"cross-collision-{uuid.uuid4().hex}".encode("ascii"),
            )
            outcomes["ingest"] = (
                int(row.id),
                row.reason_code,
                row.intent_id,
                row.order_id,
                row.shop_id,
            )
        finally:
            db.close()

    def update_b():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_b_id).one()
            shop_service.update_shop(
                db,
                actor,
                shop_b["shop_id"],
                ShopCreate.model_validate(_shop_payload(bank_no="88772222")),
            )
            outcomes["update_b"] = "ok"
        finally:
            db.close()

    ingest_thread = threading.Thread(target=ingest_collision)
    update_thread = threading.Thread(target=update_b)
    ingest_thread.start()
    assert collision_at_commit.wait(timeout=5)
    update_thread.start()
    assert update_b_at_lock.wait(timeout=5)
    allow_collision_commit.set()
    ingest_thread.join(timeout=10)
    update_thread.join(timeout=10)
    assert not ingest_thread.is_alive() and not update_thread.is_alive()
    assert outcomes["update_b"] == "ok"
    collision_id, reason, intent_id, order_id, shop_id = outcomes["ingest"]
    assert reason == "PROVIDER_EVENT_COLLISION"
    assert (intent_id, order_id, shop_id) == (None, None, None)
    assert client.get(
        f"/api/qr-reconciliation/events/{collision_id}",
        headers=auth(shop_b["token"]),
    ).status_code == 404

    # Only the mapped non-collision root A seeds this identity lineage.
    blocked_a = client.put(
        f"/api/shops/{shop_a['shop_id']}",
        json=_shop_payload(bank_no="88773333"),
        headers=auth(shop_a["token"]),
    )
    assert blocked_a.status_code == 409


def test_v1_pending_order_is_excluded_from_legacy_auto_cancel(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    legacy = seller_with_shop(client)
    disabled = qr_sales_service.QrSalesRuntime(
        mode="OFF", adapter=qr_sales_service.DisabledQrAdapter()
    )
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: disabled)
    legacy_response = client.post(
        f"/api/orders/{legacy['shop_id']}",
        json=_order_request(legacy).model_dump(),
        headers=auth(legacy["token"]),
    )
    assert legacy_response.status_code == 200, legacy_response.text
    legacy_order_id = legacy_response.json()["order_id"]
    session = SessionLocal()
    try:
        for order_id in (ctx["order_id"], legacy_order_id):
            order = session.query(models.Order).filter_by(id=order_id).one()
            order.created_at = datetime(2000, 1, 1)
        session.commit()
    finally:
        session.close()

    maintenance_service.cancel_expired_pending_orders(timeout_minutes=1_000_000)
    session = SessionLocal()
    try:
        assert session.query(models.Order).filter_by(id=ctx["order_id"]).one().status == "PENDING"
        assert session.query(models.Order).filter_by(id=legacy_order_id).one().status == "CANCELLED"
    finally:
        session.close()


def test_issuance_wins_then_account_update_is_blocked_without_sleep(
    client, monkeypatch
):
    runtime = qr_sales_service.report_only_test_runtime()
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: runtime)
    ctx = seller_with_shop(client)
    actor_id: int
    session = SessionLocal()
    try:
        actor_id = session.query(models.User).filter_by(username=ctx["username"]).one().id
    finally:
        session.close()
    intent_written = threading.Event()
    allow_order_commit = threading.Event()
    update_at_lock = threading.Event()
    real_audit = qr_sales_service._insert_issuance_audit
    real_update_lock = shop_service._lock_shop_for_write

    def hold_after_intent(db, audit):
        real_audit(db, audit)
        intent_written.set()
        assert allow_order_commit.wait(timeout=5)

    def observe_update_lock(db, shop_id, owner_id):
        update_at_lock.set()
        return real_update_lock(db, shop_id, owner_id)

    monkeypatch.setattr(qr_sales_service, "_insert_issuance_audit", hold_after_intent)
    monkeypatch.setattr(shop_service, "_lock_shop_for_write", observe_update_lock)
    outcomes: dict[str, str] = {}

    def issue():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            order_service.create_order(db, actor, ctx["shop_id"], _order_request(ctx))
            outcomes["issue"] = "ok"
        except Exception as exc:  # pragma: no cover
            outcomes["issue"] = type(exc).__name__
        finally:
            db.close()

    def update():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            shop_service.update_shop(
                db, actor, ctx["shop_id"], ShopCreate.model_validate(_shop_payload())
            )
            outcomes["update"] = "ok"
        except HTTPException as exc:
            outcomes["update"] = f"http:{exc.status_code}"
        finally:
            db.close()

    issue_thread = threading.Thread(target=issue)
    update_thread = threading.Thread(target=update)
    issue_thread.start()
    assert intent_written.wait(timeout=5)
    update_thread.start()
    assert update_at_lock.wait(timeout=5)
    allow_order_commit.set()
    issue_thread.join(timeout=10)
    update_thread.join(timeout=10)
    assert not issue_thread.is_alive() and not update_thread.is_alive()
    assert outcomes == {"issue": "ok", "update": "http:409"}


def test_account_update_wins_then_issuance_snapshots_new_account_without_sleep(
    client, monkeypatch
):
    runtime = qr_sales_service.report_only_test_runtime()
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: runtime)
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        actor_id = session.query(models.User).filter_by(username=ctx["username"]).one().id
    finally:
        session.close()
    update_holds_lock = threading.Event()
    allow_update = threading.Event()
    issuance_at_lock = threading.Event()
    real_fence = shop_service._assert_qr_account_change_allowed
    real_order_lock = order_service._lock_shop_for_order

    def hold_update_fence(db, shop_id):
        real_fence(db, shop_id)
        update_holds_lock.set()
        assert allow_update.wait(timeout=5)

    def observe_order_lock(db, shop_id):
        issuance_at_lock.set()
        return real_order_lock(db, shop_id)

    monkeypatch.setattr(shop_service, "_assert_qr_account_change_allowed", hold_update_fence)
    monkeypatch.setattr(order_service, "_lock_shop_for_order", observe_order_lock)
    outcomes: dict[str, object] = {}

    def update():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            shop_service.update_shop(
                db, actor, ctx["shop_id"], ShopCreate.model_validate(_shop_payload())
            )
            outcomes["update"] = "ok"
        finally:
            db.close()

    def issue():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            outcomes["issue"] = order_service.create_order(
                db, actor, ctx["shop_id"], _order_request(ctx)
            )
        finally:
            db.close()

    update_thread = threading.Thread(target=update)
    issue_thread = threading.Thread(target=issue)
    update_thread.start()
    assert update_holds_lock.wait(timeout=5)
    issue_thread.start()
    assert issuance_at_lock.wait(timeout=5)
    allow_update.set()
    update_thread.join(timeout=10)
    issue_thread.join(timeout=10)
    assert not update_thread.is_alive() and not issue_thread.is_alive()
    assert outcomes["update"] == "ok"
    assert outcomes["issue"]["qr_intent"]["bank_account_no"] == "99887766"


def test_terminal_action_wins_then_account_update_is_allowed_without_sleep(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    session = SessionLocal()
    try:
        actor_id = session.query(models.User).filter_by(username=ctx["username"]).one().id
    finally:
        session.close()
    action_inserted = threading.Event()
    allow_action_commit = threading.Event()
    update_at_lock = threading.Event()
    real_add_action = qr_reconciliation_service._add_reconciliation_action
    real_update_lock = shop_service._lock_shop_for_write

    def hold_terminal_action(db, action):
        real_add_action(db, action)
        action_inserted.set()
        assert allow_action_commit.wait(timeout=5)

    def observe_update_lock(db, shop_id, owner_id):
        update_at_lock.set()
        return real_update_lock(db, shop_id, owner_id)

    monkeypatch.setattr(qr_reconciliation_service, "_add_reconciliation_action", hold_terminal_action)
    monkeypatch.setattr(shop_service, "_lock_shop_for_write", observe_update_lock)
    outcomes: dict[str, str] = {}

    def reject():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            qr_reconciliation_service.reconcile_event(
                db,
                actor,
                event["id"],
                ReconciliationActionRequest(
                    expected_state_version=0,
                    action="REJECT_NOT_OURS",
                    note="Giao dịch không thuộc cửa hàng",
                ),
            )
            outcomes["action"] = "ok"
        finally:
            db.close()

    def update():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            shop_service.update_shop(
                db, actor, ctx["shop_id"], ShopCreate.model_validate(_shop_payload())
            )
            outcomes["update"] = "ok"
        finally:
            db.close()

    action_thread = threading.Thread(target=reject)
    update_thread = threading.Thread(target=update)
    action_thread.start()
    assert action_inserted.wait(timeout=5)
    update_thread.start()
    assert update_at_lock.wait(timeout=5)
    allow_action_commit.set()
    action_thread.join(timeout=10)
    update_thread.join(timeout=10)
    assert not action_thread.is_alive() and not update_thread.is_alive()
    assert outcomes == {"action": "ok", "update": "ok"}


def test_blocked_account_update_releases_lock_then_terminal_action_wins_without_sleep(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    session = SessionLocal()
    try:
        actor_id = session.query(models.User).filter_by(username=ctx["username"]).one().id
    finally:
        session.close()
    update_holds_lock = threading.Event()
    allow_fence_check = threading.Event()
    action_at_lock = threading.Event()
    real_fence = shop_service._assert_qr_account_change_allowed
    real_order_lock = order_service._lock_shop_for_order

    def hold_before_block(db, shop_id):
        update_holds_lock.set()
        assert allow_fence_check.wait(timeout=5)
        return real_fence(db, shop_id)

    def observe_action_lock(db, shop_id):
        action_at_lock.set()
        return real_order_lock(db, shop_id)

    monkeypatch.setattr(shop_service, "_assert_qr_account_change_allowed", hold_before_block)
    monkeypatch.setattr(order_service, "_lock_shop_for_order", observe_action_lock)
    outcomes: dict[str, str] = {}

    def update():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            shop_service.update_shop(
                db, actor, ctx["shop_id"], ShopCreate.model_validate(_shop_payload())
            )
            outcomes["update"] = "ok"
        except HTTPException as exc:
            outcomes["update"] = f"http:{exc.status_code}"
        finally:
            db.close()

    def reject():
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            qr_reconciliation_service.reconcile_event(
                db,
                actor,
                event["id"],
                ReconciliationActionRequest(
                    expected_state_version=0,
                    action="REJECT_NOT_OURS",
                    note="Giao dịch không thuộc cửa hàng",
                ),
            )
            outcomes["action"] = "ok"
        finally:
            db.close()

    update_thread = threading.Thread(target=update)
    action_thread = threading.Thread(target=reject)
    update_thread.start()
    assert update_holds_lock.wait(timeout=5)
    action_thread.start()
    assert action_at_lock.wait(timeout=5)
    allow_fence_check.set()
    update_thread.join(timeout=10)
    action_thread.join(timeout=10)
    assert not update_thread.is_alive() and not action_thread.is_alive()
    assert outcomes == {"update": "http:409", "action": "ok"}
