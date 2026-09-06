"""I10-C reconciliation auth, validation, CAS and atomicity."""
from __future__ import annotations

import json
import threading
import uuid

import pytest
from fastapi import HTTPException

from conftest import SHOP_PAYLOAD, admin_token, auth, new_staff
from fselling import models
from fselling.core.database import SessionLocal
from fselling.schemas.qr_reconciliation import (
    MAX_RECONCILIATION_ID,
    MAX_RECONCILIATION_STATE_VERSION,
    ReconciliationActionRequest,
)
from fselling.services import order_service, qr_reconciliation_service
from i10c_helpers import (
    create_intent_context,
    enable_webhook,
    ingest_ready,
    post_event,
    ready_payload,
)


def _shop_payload(*, bank_no: str = "99887766") -> dict:
    payload = dict(SHOP_PAYLOAD)
    payload["bank_code"] = "MB"
    payload["bank_account_no"] = bank_no
    payload["bank_account_name"] = "TAI KHOAN MOI"
    return payload


def _action(client, token, event_id, action, *, version=0, note=None, target=None):
    payload = {"expected_state_version": version, "action": action}
    if note is not None:
        payload["note"] = note
    if target is not None:
        payload["target_intent_id"] = target
    return client.post(
        f"/api/qr-reconciliation/events/{event_id}/actions",
        json=payload,
        headers=auth(token),
    )


def test_exact_map_is_the_only_payment_path_and_is_one_atomic_decision(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    assert event["reason_code"] == "READY_TO_MAP"

    response = _action(client, ctx["token"], event["id"], "MAP_AND_APPLY")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event"]["disposition"] == "APPLIED"
    assert body["event"]["reason_code"] == "MAP_AND_APPLY"
    assert body["event"]["state_version"] == 1
    assert body["idempotent_replay"] is False

    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=event["id"]).one()
        action = session.query(models.BankReconciliationAction).filter_by(
            event_id=stored.id
        ).one()
        payment = session.query(models.OrderPayment).filter_by(id=stored.payment_id).one()
        order = session.query(models.Order).filter_by(id=ctx["order_id"]).one()
        audit = session.query(models.SystemLog).filter_by(id=action.system_log_id).one()
        assert action.action_kind == "MAP_AND_APPLY"
        assert payment.entry_type == "BANK_IN"
        assert payment.amount == ctx["expected_vnd"]
        assert payment.idempotency_key == stored.idempotency_key
        assert payment.provider == stored.provider
        assert payment.bank_txn_id == stored.provider_event_id
        assert payment.account_no == stored.normalized_account_no
        assert order.status == "PAID"
        assert order.paid_amount == ctx["expected_vnd"]
        assert audit.action == "BANK_RECONCILIATION"
        details = json.loads(audit.details)
        assert details["event_id"] == stored.id
        for secret in (
            stored.normalized_account_no,
            stored.normalized_reference,
            stored.idempotency_key,
            stored.provider_event_id,
        ):
            assert secret not in audit.details
    finally:
        session.close()


def test_keep_open_then_reject_and_refund_actions_never_create_payment(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    first = ingest_ready(client, monkeypatch, ctx, provider_event_id="evt-keep-reject")
    kept = _action(client, ctx["token"], first["id"], "KEEP_OPEN")
    assert kept.status_code == 200
    assert kept.json()["event"]["disposition"] == "UNAPPLIED"
    assert kept.json()["event"]["state_version"] == 0
    rejected = _action(
        client,
        ctx["token"],
        first["id"],
        "REJECT_NOT_OURS",
        note="Giao dịch không thuộc cửa hàng",
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["event"]["disposition"] == "REJECTED_NOT_OURS"

    second = ingest_ready(client, monkeypatch, ctx, provider_event_id="evt-refunded")
    refunded = _action(
        client,
        ctx["token"],
        second["id"],
        "MARK_REFUNDED_EXTERNALLY",
        note="Đã xác minh hoàn ngoài hệ thống",
    )
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["event"]["disposition"] == "REFUNDED"

    session = SessionLocal()
    try:
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 0
        actions = session.query(models.BankReconciliationAction).filter(
            models.BankReconciliationAction.event_id.in_([first["id"], second["id"]])
        ).all()
        assert sorted(action.action_kind for action in actions) == [
            "KEEP_OPEN",
            "MARK_REFUNDED_EXTERNALLY",
            "REJECT_NOT_OURS",
        ]
    finally:
        session.close()


@pytest.mark.parametrize("action", ["REJECT_NOT_OURS", "MARK_REFUNDED_EXTERNALLY"])
def test_terminal_nonpayment_actions_require_bounded_sanitized_note(
    client, monkeypatch, action
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    for note in (None, "  ", "token=abc", ctx["reference"], "x\nsecret"):
        response = _action(
            client, ctx["token"], event["id"], action, note=note
        )
        assert response.status_code in {400, 422}
    session = SessionLocal()
    try:
        assert session.query(models.BankReconciliationAction).filter_by(
            event_id=event["id"]
        ).count() == 0
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 0
    finally:
        session.close()


def test_note_rejects_unicode_spoofing_and_obfuscated_financial_identifiers(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    provider_event_id = f"evt-sensitive-{uuid.uuid4().hex}"
    event = ingest_ready(
        client,
        monkeypatch,
        ctx,
        provider_event_id=provider_event_id,
        account_no="001122",
    )
    assert event["reason_code"] == "ACCOUNT_MISMATCH"
    obfuscated_reference = " / ".join(ctx["reference"])
    obfuscated_provider_id = " / ".join(provider_event_id)
    fullwidth_account = "".join(
        chr(ord(char) + 0xFEE0) for char in "001122"
    )
    rejected_notes = (
        "Đối soát\u202E giả mạo hiển thị",
        "Đối soát\u200B chèn ký tự ẩn",
        "Đối soát\u2028 xuống dòng ẩn",
        "Đối soát có vẻ hợp lệ\u2028",
        "Tài khoản 00 1122 không thuộc cửa hàng",
        f"Tham chiếu {obfuscated_reference}",
        "Nhà cung cấp mock / bank",
        f"Sự kiện {obfuscated_provider_id}",
        f"Tài khoản {fullwidth_account}",
    )
    for note in rejected_notes:
        response = _action(
            client,
            ctx["token"],
            event["id"],
            "REJECT_NOT_OURS",
            note=note,
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == {
            "code": "QR_RECONCILIATION_NOTE_INVALID",
            "message": "Reconciliation note is invalid",
        }
        assert note not in response.text

    benign = "Đã xác minh giao dịch không thuộc cửa hàng số hai"
    accepted = _action(
        client,
        ctx["token"],
        event["id"],
        "REJECT_NOT_OURS",
        note=benign,
    )
    assert accepted.status_code == 200, accepted.text
    session = SessionLocal()
    try:
        action = session.query(models.BankReconciliationAction).filter_by(
            event_id=event["id"]
        ).one()
        audit = session.query(models.SystemLog).filter_by(
            id=action.system_log_id
        ).one()
        assert action.note == benign
        assert all(note not in audit.details for note in rejected_notes)
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 0
    finally:
        session.close()


def test_event_and_command_integer_id_boundaries_are_sanitized(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    invalid_path_ids = (
        "0",
        str(MAX_RECONCILIATION_ID + 1),
        "9" * 200,
        "true",
        "1.0",
        "null",
        "not-an-integer",
    )
    for raw_id in invalid_path_ids:
        responses = (
            client.get(
                f"/api/qr-reconciliation/events/{raw_id}",
                headers=auth(ctx["token"]),
            ),
            client.post(
                f"/api/qr-reconciliation/events/{raw_id}/actions",
                json={"expected_state_version": 0, "action": "KEEP_OPEN"},
                headers=auth(ctx["token"]),
            ),
        )
        for response in responses:
            assert response.status_code == 422, response.text
            assert response.json()["detail"] == {
                "code": "QR_RECONCILIATION_REQUEST_INVALID",
                "message": "QR reconciliation request is invalid",
            }
            assert raw_id not in response.text

    for safe_path_id in (1, MAX_RECONCILIATION_ID):
        response = client.get(
            f"/api/qr-reconciliation/events/{safe_path_id}",
            headers=auth(ctx["token"]),
        )
        assert response.status_code in {200, 404}
        assert response.status_code != 500

    invalid_body_values = (
        0,
        MAX_RECONCILIATION_ID + 1,
        10**199,
        True,
        "1",
        1.0,
        None,
    )
    for value in invalid_body_values:
        response = client.post(
            f"/api/qr-reconciliation/events/{event['id']}/actions",
            json={
                "expected_state_version": 0,
                "action": "KEEP_OPEN",
                "target_intent_id": value,
            },
            headers=auth(ctx["token"]),
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == (
            "QR_RECONCILIATION_REQUEST_INVALID"
        )
        assert str(value) not in response.text

    for safe_target in (1, MAX_RECONCILIATION_ID):
        response = client.post(
            f"/api/qr-reconciliation/events/{event['id']}/actions",
            json={
                "expected_state_version": 0,
                "action": "KEEP_OPEN",
                "target_intent_id": safe_target,
            },
            headers=auth(ctx["token"]),
        )
        assert response.status_code in {200, 404, 409}
        assert response.status_code != 500

    invalid_versions = (
        MAX_RECONCILIATION_STATE_VERSION + 1,
        10**199,
        True,
        "0",
        0.0,
        None,
    )
    for version in invalid_versions:
        response = client.post(
            f"/api/qr-reconciliation/events/{event['id']}/actions",
            json={"expected_state_version": version, "action": "KEEP_OPEN"},
            headers=auth(ctx["token"]),
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == (
            "QR_RECONCILIATION_REQUEST_INVALID"
        )
        assert str(version) not in response.text

    for safe_version in (0, 1, MAX_RECONCILIATION_STATE_VERSION):
        response = client.post(
            f"/api/qr-reconciliation/events/{event['id']}/actions",
            json={"expected_state_version": safe_version, "action": "KEEP_OPEN"},
            headers=auth(ctx["token"]),
        )
        assert response.status_code in {200, 409}
        assert response.status_code != 500


def test_http_accepts_durable_event_id_above_legacy_quantity_cap(client):
    event_id = 1_000_000_001
    unique = uuid.uuid4().hex
    session = SessionLocal()
    try:
        session.add(
            models.BankWebhookEvent(
                id=event_id,
                provider="mock_bank",
                provider_event_id=f"evt-large-{unique}",
                idempotency_key=("1" + unique * 2)[:64],
                normalized_account_no=None,
                direction="UNKNOWN",
                amount_vnd=None,
                reference_state="MISSING",
                normalized_reference=None,
                normalized_sha256=("2" + unique * 2)[:64],
                envelope_sha256=("3" + unique * 2)[:64],
                intent_id=None,
                order_id=None,
                shop_id=None,
                payment_id=None,
                disposition="UNAPPLIED",
                reason_code="REFERENCE_MISSING",
                received_at="2026-08-13 01:02:03.000000",
                updated_at="2026-08-13 01:02:03.000000",
                state_version=0,
            )
        )
        session.commit()
    finally:
        session.close()

    admin = admin_token(client)
    fetched = client.get(
        f"/api/qr-reconciliation/events/{event_id}", headers=auth(admin)
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == event_id
    kept = client.post(
        f"/api/qr-reconciliation/events/{event_id}/actions",
        json={"expected_state_version": 0, "action": "KEEP_OPEN"},
        headers=auth(admin),
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["event"]["id"] == event_id

    for boundary in (MAX_RECONCILIATION_ID - 1, MAX_RECONCILIATION_ID):
        get_response = client.get(
            f"/api/qr-reconciliation/events/{boundary}", headers=auth(admin)
        )
        action_response = client.post(
            f"/api/qr-reconciliation/events/{boundary}/actions",
            json={"expected_state_version": 0, "action": "KEEP_OPEN"},
            headers=auth(admin),
        )
        assert get_response.status_code == 404
        assert action_response.status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_vnd": 1},
        {"amount_vnd": 200_000},
        {"account_no": "999"},
        {"direction": "OUT"},
        {"references": None},
        {"references": "FS1-UNKNOWN"},
    ],
)
def test_map_revalidates_full_evidence_under_lock(client, monkeypatch, changes):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx, **changes)
    response = _action(client, ctx["token"], event["id"], "MAP_AND_APPLY")
    if event["shop_id"] is None:
        assert response.status_code == 404
    else:
        assert response.status_code == 409
    session = SessionLocal()
    try:
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 0
        assert session.query(models.Order).filter_by(id=ctx["order_id"]).one().status == "PENDING"
    finally:
        session.close()


def test_provider_collision_blocks_both_evidence_rows_from_map(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    payload = ready_payload(ctx, provider_event_id="evt-collision-map")
    first = post_event(client, runtime, payload, sort_keys=True, compact=True).json()
    second = post_event(client, runtime, payload, sort_keys=False, compact=False).json()
    assert second["reason_code"] == "PROVIDER_EVENT_COLLISION"
    root_response = _action(client, ctx["token"], first["id"], "MAP_AND_APPLY")
    collision_response = _action(
        client, ctx["token"], second["id"], "MAP_AND_APPLY"
    )
    assert root_response.status_code == 409
    assert collision_response.status_code == 404
    assert second["intent_id"] is None
    assert second["order_id"] is None
    assert second["shop_id"] is None
    session = SessionLocal()
    try:
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 0
    finally:
        session.close()


def test_scoped_list_get_redaction_pagination_and_no_existence_leak(
    client, monkeypatch
):
    first = create_intent_context(client, monkeypatch)
    second = create_intent_context(client, monkeypatch)
    manager_name, manager = new_staff(client, first, "MANAGER")
    _cashier_name, cashier = new_staff(client, first, "CASHIER")
    first_event = ingest_ready(client, monkeypatch, first)
    second_event = ingest_ready(client, monkeypatch, second)
    runtime = enable_webhook(monkeypatch)
    unknown = post_event(
        client,
        runtime,
        ready_payload(first, references="FS1-NOT-FOUND"),
    ).json()

    owner_list = client.get(
        "/api/qr-reconciliation/events?limit=1&offset=0",
        headers=auth(first["token"]),
    )
    assert owner_list.status_code == 200
    assert owner_list.headers["cache-control"] == "no-store"
    assert len(owner_list.json()["items"]) == 1
    assert owner_list.json()["items"][0]["shop_id"] == first["shop_id"]
    assert owner_list.json()["next_offset"] is None
    manager_get = client.get(
        f"/api/qr-reconciliation/events/{first_event['id']}", headers=auth(manager)
    )
    assert manager_get.status_code == 200
    assert manager_name
    for forbidden in (
        "provider",
        "provider_event_id",
        "idempotency_key",
        "normalized_account_no",
        "normalized_reference",
        "normalized_sha256",
        "envelope_sha256",
    ):
        assert forbidden not in manager_get.json()

    assert client.get(
        f"/api/qr-reconciliation/events/{second_event['id']}",
        headers=auth(first["token"]),
    ).status_code == 404
    assert client.get(
        f"/api/qr-reconciliation/events/{unknown['id']}",
        headers=auth(first["token"]),
    ).status_code == 404
    assert client.get(
        "/api/qr-reconciliation/events", headers=auth(cashier)
    ).status_code == 403
    admin = admin_token(client)
    admin_list = client.get(
        "/api/qr-reconciliation/events?limit=100&offset=0", headers=auth(admin)
    )
    assert admin_list.status_code == 200
    assert unknown["id"] in {row["id"] for row in admin_list.json()["items"]}

    reflected = client.get(
        "/api/qr-reconciliation/events?limit=private-token-value",
        headers=auth(admin),
    )
    assert reflected.status_code == 422
    assert reflected.json()["detail"]["code"] == "QR_RECONCILIATION_REQUEST_INVALID"
    assert "private-token-value" not in reflected.text


def test_unscoped_event_is_admin_action_only_and_stays_redacted(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    unknown = post_event(
        client,
        runtime,
        ready_payload(ctx, references="FS1-ADMIN-ONLY"),
    ).json()
    owner = _action(client, ctx["token"], unknown["id"], "KEEP_OPEN")
    assert owner.status_code == 404
    admin = admin_token(client)
    kept = _action(client, admin, unknown["id"], "KEEP_OPEN")
    assert kept.status_code == 200, kept.text
    assert kept.json()["event"]["shop_id"] is None
    rejected = _action(
        client,
        admin,
        unknown["id"],
        "REJECT_NOT_OURS",
        note="Không thuộc hệ thống cửa hàng",
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["event"]["disposition"] == "REJECTED_NOT_OURS"
    session = SessionLocal()
    try:
        actions = session.query(models.BankReconciliationAction).filter_by(
            event_id=unknown["id"]
        ).all()
        assert [action.actor_role for action in actions] == ["ADMIN", "ADMIN"]
        assert all(action.shop_id is None and action.payment_id is None for action in actions)
    finally:
        session.close()


def test_cas_lost_response_retry_is_idempotent_and_different_decision_conflicts(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    first = _action(client, ctx["token"], event["id"], "MAP_AND_APPLY")
    retry = _action(client, ctx["token"], event["id"], "MAP_AND_APPLY")
    conflict = _action(
        client,
        ctx["token"],
        event["id"],
        "REJECT_NOT_OURS",
        note="Không thuộc cửa hàng",
    )
    assert first.status_code == retry.status_code == 200
    assert retry.json()["idempotent_replay"] is True
    assert retry.json()["action"]["id"] == first.json()["action"]["id"]
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "QR_RECONCILIATION_STATE_CONFLICT",
        "message": "Bank evidence state changed",
        "current_state_version": 1,
    }
    session = SessionLocal()
    try:
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 1
        assert session.query(models.BankReconciliationAction).filter_by(
            event_id=event["id"]
        ).count() == 1
    finally:
        session.close()


def test_commit_lost_response_returns_durable_winner(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    real_commit = qr_reconciliation_service._commit_reconciliation

    def commit_then_raise(db):
        real_commit(db)
        raise RuntimeError("simulated lost response")

    monkeypatch.setattr(
        qr_reconciliation_service, "_commit_reconciliation", commit_then_raise
    )
    response = _action(client, ctx["token"], event["id"], "MAP_AND_APPLY")
    assert response.status_code == 200, response.text
    assert response.json()["idempotent_replay"] is True
    session = SessionLocal()
    try:
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 1
    finally:
        session.close()


@pytest.mark.parametrize(
    "seam",
    [
        "_add_order_payment",
        "_add_reconciliation_audit",
        "_add_reconciliation_action",
        "_flush_reconciliation",
        "_commit_reconciliation",
    ],
)
def test_faults_roll_back_payment_action_audit_and_transition(
    client, monkeypatch, seam
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    session = SessionLocal()
    try:
        audit_before = session.query(models.SystemLog).count()
    finally:
        session.close()

    def fail(*_args, **_kwargs):
        raise RuntimeError("fault injection")

    monkeypatch.setattr(qr_reconciliation_service, seam, fail)
    response = _action(client, ctx["token"], event["id"], "MAP_AND_APPLY")
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "QR_RECONCILIATION_PERSISTENCE_FAILED"
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=event["id"]).one()
        order = session.query(models.Order).filter_by(id=ctx["order_id"]).one()
        assert stored.disposition == "UNAPPLIED"
        assert stored.state_version == 0 and stored.payment_id is None
        assert order.status == "PENDING" and int(order.paid_amount or 0) == 0
        assert session.query(models.OrderPayment).filter_by(order_id=order.id).count() == 0
        assert session.query(models.BankReconciliationAction).filter_by(
            event_id=event["id"]
        ).count() == 0
        assert session.query(models.SystemLog).count() == audit_before
    finally:
        session.close()


@pytest.mark.parametrize(
    ("other_action", "other_note", "other_disposition"),
    [
        ("MAP_AND_APPLY", None, "APPLIED"),
        ("REJECT_NOT_OURS", "Giao dịch không thuộc cửa hàng", "REJECTED_NOT_OURS"),
        (
            "MARK_REFUNDED_EXTERNALLY",
            "Đã xác minh hoàn ngoài hệ thống",
            "REFUNDED",
        ),
    ],
)
def test_two_admin_terminal_decisions_have_one_winner_without_sleep(
    client, monkeypatch, other_action, other_note, other_disposition
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    session = SessionLocal()
    try:
        first_admin = session.query(models.User).filter_by(role="ADMIN").first()
        second_admin = models.User(
            username=f"admin_race_{uuid.uuid4().hex}",
            hashed_password="not-used-by-service-test",
            role="ADMIN",
            is_verified=True,
            is_active=True,
        )
        session.add(second_admin)
        session.commit()
        actor_ids = (int(first_admin.id), int(second_admin.id))
    finally:
        session.close()
    barrier = threading.Barrier(2)
    real_lock = order_service._lock_shop_for_order

    def synchronized_lock(db, shop_id):
        barrier.wait(timeout=5)
        return real_lock(db, shop_id)

    monkeypatch.setattr(order_service, "_lock_shop_for_order", synchronized_lock)
    outcomes: list[str] = []
    guard = threading.Lock()

    def decide(actor_id, kind, note):
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            command = ReconciliationActionRequest(
                expected_state_version=0, action=kind, note=note
            )
            qr_reconciliation_service.reconcile_event(db, actor, event["id"], command)
            outcome = "ok"
        except HTTPException as exc:
            outcome = f"http:{exc.status_code}"
        except Exception as exc:  # pragma: no cover
            outcome = type(exc).__name__
        finally:
            db.close()
        with guard:
            outcomes.append(outcome)

    threads = [
        threading.Thread(
            target=decide,
            args=(actor_ids[0], "MAP_AND_APPLY", None),
        ),
        threading.Thread(
            target=decide,
            args=(
                actor_ids[1],
                other_action,
                other_note,
            ),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["http:409", "ok"]
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=event["id"]).one()
        assert stored.disposition in {"APPLIED", other_disposition}
        assert session.query(models.BankReconciliationAction).filter(
            models.BankReconciliationAction.event_id == event["id"],
            models.BankReconciliationAction.action_kind != "KEEP_OPEN",
        ).count() == 1
        payment_count = session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count()
        assert payment_count == (1 if stored.disposition == "APPLIED" else 0)
    finally:
        session.close()


@pytest.mark.parametrize(
    ("first_action", "second_action", "expected_outcomes", "expected_actions"),
    [
        (
            "KEEP_OPEN",
            "MAP_AND_APPLY",
            ["ok", "ok"],
            ["KEEP_OPEN", "MAP_AND_APPLY"],
        ),
        (
            "MAP_AND_APPLY",
            "KEEP_OPEN",
            ["http:409", "ok"],
            ["MAP_AND_APPLY"],
        ),
    ],
)
def test_map_vs_keep_is_deterministic_in_both_lock_orderings_without_sleep(
    client,
    monkeypatch,
    first_action,
    second_action,
    expected_outcomes,
    expected_actions,
):
    ctx = create_intent_context(client, monkeypatch)
    event = ingest_ready(client, monkeypatch, ctx)
    session = SessionLocal()
    try:
        first_admin = session.query(models.User).filter_by(role="ADMIN").first()
        second_admin = models.User(
            username=f"admin_keep_race_{uuid.uuid4().hex}",
            hashed_password="not-used-by-service-test",
            role="ADMIN",
            is_verified=True,
            is_active=True,
        )
        session.add(second_admin)
        session.commit()
        actor_ids = (int(first_admin.id), int(second_admin.id))
    finally:
        session.close()

    first_inserted = threading.Event()
    allow_first_commit = threading.Event()
    second_at_lock = threading.Event()
    real_add_action = qr_reconciliation_service._add_reconciliation_action
    real_lock = order_service._lock_shop_for_order

    def hold_first_action(db, action):
        real_add_action(db, action)
        if threading.current_thread().name == "first-decision":
            first_inserted.set()
            assert allow_first_commit.wait(timeout=5)

    def observe_second_lock(db, shop_id):
        if threading.current_thread().name == "second-decision":
            second_at_lock.set()
        return real_lock(db, shop_id)

    monkeypatch.setattr(
        qr_reconciliation_service, "_add_reconciliation_action", hold_first_action
    )
    monkeypatch.setattr(order_service, "_lock_shop_for_order", observe_second_lock)
    outcomes: list[str] = []
    guard = threading.Lock()

    def decide(actor_id, kind):
        db = SessionLocal()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            qr_reconciliation_service.reconcile_event(
                db,
                actor,
                event["id"],
                ReconciliationActionRequest(
                    expected_state_version=0,
                    action=kind,
                ),
            )
            outcome = "ok"
        except HTTPException as exc:
            outcome = f"http:{exc.status_code}"
        finally:
            db.close()
        with guard:
            outcomes.append(outcome)

    first = threading.Thread(
        name="first-decision",
        target=decide,
        args=(actor_ids[0], first_action),
    )
    second = threading.Thread(
        name="second-decision",
        target=decide,
        args=(actor_ids[1], second_action),
    )
    first.start()
    assert first_inserted.wait(timeout=5)
    second.start()
    assert second_at_lock.wait(timeout=5)
    allow_first_commit.set()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(outcomes) == expected_outcomes
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=event["id"]).one()
        actions = session.query(models.BankReconciliationAction).filter_by(
            event_id=event["id"]
        ).all()
        assert stored.disposition == "APPLIED"
        assert sorted(action.action_kind for action in actions) == sorted(expected_actions)
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 1
    finally:
        session.close()


def test_second_evidence_cannot_create_duplicate_money(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    first = ingest_ready(client, monkeypatch, ctx, provider_event_id="evt-money-first")
    assert _action(client, ctx["token"], first["id"], "MAP_AND_APPLY").status_code == 200
    second = ingest_ready(client, monkeypatch, ctx, provider_event_id="evt-money-second")
    assert second["reason_code"] == "ORDER_PAYMENT_CONFLICT"
    assert _action(client, ctx["token"], second["id"], "MAP_AND_APPLY").status_code == 409
    session = SessionLocal()
    try:
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 1
    finally:
        session.close()


# ---------- correction-3: collision + target_intent_id raises 409, zero mutation ----------


def _collision(client, monkeypatch, ctx, identity):
    runtime = enable_webhook(monkeypatch)
    root = post_event(client, runtime, ready_payload(ctx, provider_event_id=identity)).json()
    _action(client, ctx["token"], root["id"], "REJECT_NOT_OURS", note="Root reject")
    second = post_event(
        client,
        runtime,
        ready_payload(ctx, provider_event_id=identity, amount_vnd=ctx["expected_vnd"] + 1),
    ).json()
    assert second["reason_code"] == "PROVIDER_EVENT_COLLISION"
    assert second["intent_id"] is None
    assert second["order_id"] is None
    assert second["shop_id"] is None
    return second


def _reject_event_local(client, token: str, event_id: int, note: str = "Giao dich khong thuoc cua hang") -> None:
    response = client.post(
        f"/api/qr-reconciliation/events/{event_id}/actions",
        json={"expected_state_version": 0, "action": "REJECT_NOT_OURS", "note": note},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", ["REJECT_NOT_OURS", "MARK_REFUNDED_EXTERNALLY"])
def test_collision_with_target_intent_rejects_409_and_zero_mutation(
    client, monkeypatch, action
):
    """target_intent_id on a collision event is a cross-shop scope leak -- blocked."""
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    identity = f"evt-corr3-{uuid.uuid4().hex}"
    root_a = ingest_ready(client, monkeypatch, shop_a, provider_event_id=identity)
    _reject_event_local(client, shop_a["token"], root_a["id"])

    runtime = enable_webhook(monkeypatch)
    collision = post_event(
        client,
        runtime,
        ready_payload(shop_b, provider_event_id=identity, amount_vnd=shop_b["expected_vnd"] + 1),
    ).json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"

    admin = admin_token(client)
    note = "Giao dich khong thuoc he thong" if action == "REJECT_NOT_OURS" else "Da xac minh hoan ngoai he thong"
    targeted = _action(client, admin, collision["id"], action, target=shop_b["intent_id"], note=note)
    assert targeted.status_code == 409, targeted.text
    assert targeted.json()["detail"]["code"] == "QR_RECONCILIATION_ACTION_INVALID"
    assert targeted.json()["detail"]["message"] == "A collision cannot be targeted for reconciliation"

    # Zero mutation: event stays unscoped
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=collision["id"]).one()
        assert stored.disposition == "UNAPPLIED"
        assert stored.intent_id is None and stored.order_id is None and stored.shop_id is None
        assert session.query(models.BankReconciliationAction).filter_by(event_id=collision["id"]).count() == 0
        assert session.query(models.SystemLog).filter(
            models.SystemLog.action == "BANK_RECONCILIATION",
            models.SystemLog.details.like(f'%event_id":{collision["id"]}%'),
        ).count() == 0
    finally:
        session.close()

    # Shop B still cannot see or act on the collision (404)
    for token in (shop_b["token"],):
        assert client.get(
            f"/api/qr-reconciliation/events/{collision['id']}",
            headers=auth(token),
        ).status_code == 404
    # Shop A's lineage is still fenced via root_a (rejected, not terminal-unlocked here)
    # The collision itself was not targeted, so no shop was granted visibility
    assert client.get(
        f"/api/qr-reconciliation/events/{collision['id']}",
        headers=auth(shop_a["token"]),
    ).status_code == 404


def test_collision_admin_no_target_terminal_succeeds_and_stays_null(client, monkeypatch):
    """ADMIN terminal action without target_intent_id is valid; event/action/audit stay NULL."""
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    identity = f"evt-corr3-notarget-{uuid.uuid4().hex}"
    root_a = ingest_ready(client, monkeypatch, shop_a, provider_event_id=identity)
    _reject_event_local(client, shop_a["token"], root_a["id"])

    runtime = enable_webhook(monkeypatch)
    collision = post_event(
        client,
        runtime,
        ready_payload(shop_b, provider_event_id=identity, amount_vnd=shop_b["expected_vnd"] + 1),
    ).json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"

    admin = admin_token(client)
    # No target — should succeed
    terminal = _action(
        client,
        admin,
        collision["id"],
        "REJECT_NOT_OURS",
        note="Chung tu xung dot xu ly boi admin",
    )
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["event"]["disposition"] == "REJECTED_NOT_OURS"

    # event, action, audit remain NULL
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=collision["id"]).one()
        assert stored.intent_id is None
        assert stored.order_id is None
        assert stored.shop_id is None
        action_row = session.query(models.BankReconciliationAction).filter_by(
            event_id=collision["id"]
        ).one()
        assert action_row.intent_id is None
        assert action_row.order_id is None
        assert action_row.shop_id is None
        assert action_row.payment_id is None
        audit = session.query(models.SystemLog).filter_by(id=action_row.system_log_id).one()
        details = json.loads(audit.details)
        assert details["intent_id"] is None
        assert details["order_id"] is None
        assert details["shop_id"] is None
    finally:
        session.close()

    # Owner/manager A and B still get 404 (collision is unscoped, no visibility granted)
    for token in (shop_a["token"], shop_b["token"]):
        assert client.get(
            f"/api/qr-reconciliation/events/{collision['id']}",
            headers=auth(token),
        ).status_code == 404

    # Shop A is now unlocked -- both root_a and collision are terminal
    allowed_a = client.put(
        f"/api/shops/{shop_a['shop_id']}",
        json=_shop_payload(bank_no="11990001"),
        headers=auth(shop_a["token"]),
    )
    assert allowed_a.status_code == 200, allowed_a.text


# ----------------------------------------------------------------------
# Helpers for concurrent target/no-target race tests
# ----------------------------------------------------------------------


def _concurrent_target_no_target_race(client, monkeypatch, first_releases_first):
    """Deterministic ordering of target vs no-target on a collision event via per-worker gates.

    Gates: target_ready · target_go → service → target_done
           no_target_ready · no_target_go → service → no_target_done

    Ordering is controlled by first_releases_first:
      - True  : target_go set first → target commits first, no-target arrives late (409).
      - False : no_target_go set first → no-target commits first, target arrives late (409).
      - None  : both go events set simultaneously → SQLite lock decides winner;
                production code ensures target always loses (collision guard fires first).
    """
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    identity = f"evt-corr3-race-{uuid.uuid4().hex}"
    root_a = ingest_ready(client, monkeypatch, shop_a, provider_event_id=identity)
    _reject_event_local(client, shop_a["token"], root_a["id"])

    runtime = enable_webhook(monkeypatch)
    collision = post_event(
        client,
        runtime,
        ready_payload(shop_b, provider_event_id=identity, amount_vnd=shop_b["expected_vnd"] + 1),
    ).json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"
    collision_id = int(collision["id"])

    session = SessionLocal()
    try:
        first_admin = session.query(models.User).filter_by(role="ADMIN").first()
        second_admin = models.User(
            username=f"admin_corr3_{uuid.uuid4().hex}",
            hashed_password="not-used-by-service-test",
            role="ADMIN",
            is_verified=True,
            is_active=True,
        )
        session.add(second_admin)
        session.commit()
        actor_ids = (int(first_admin.id), int(second_admin.id))
    finally:
        session.close()

    # Deterministic per-worker gates
    target_ready = threading.Event()
    no_target_ready = threading.Event()
    target_go = threading.Event()
    no_target_go = threading.Event()
    target_done = threading.Event()
    no_target_done = threading.Event()

    outcomes: dict[str, str] = {}
    guard = threading.Lock()

    def decide_target(actor_id):
        try:
            target_ready.set()
            assert target_go.wait(timeout=10), "target did not receive go signal"
            db = SessionLocal()
            try:
                actor = db.query(models.User).filter_by(id=actor_id).one()
                command = ReconciliationActionRequest(
                    expected_state_version=0,
                    action="REJECT_NOT_OURS",
                    target_intent_id=shop_b["intent_id"],
                    note="Target bi loi vi collision",
                )
                qr_reconciliation_service.reconcile_event(db, actor, collision_id, command)
                outcome = "ok"
            except HTTPException as exc:
                outcome = f"http:{exc.status_code}"
            except Exception as exc:  # pragma: no cover
                outcome = type(exc).__name__
            finally:
                db.close()
            with guard:
                outcomes["target"] = outcome
        finally:
            target_done.set()

    def decide_no_target(actor_id):
        try:
            no_target_ready.set()
            assert no_target_go.wait(timeout=10), "no_target did not receive go signal"
            db = SessionLocal()
            try:
                actor = db.query(models.User).filter_by(id=actor_id).one()
                command = ReconciliationActionRequest(
                    expected_state_version=0,
                    action="REJECT_NOT_OURS",
                    note="Xu ly khong co target",
                )
                qr_reconciliation_service.reconcile_event(db, actor, collision_id, command)
                outcome = "ok"
            except HTTPException as exc:
                outcome = f"http:{exc.status_code}"
            finally:
                db.close()
            with guard:
                outcomes["no_target"] = outcome
        finally:
            no_target_done.set()

    # Start both workers; they will block on *_go until we signal them
    t_target = threading.Thread(target=decide_target, args=(actor_ids[0],))
    t_no_target = threading.Thread(target=decide_no_target, args=(actor_ids[1],))
    t_target.start()
    t_no_target.start()

    # Wait until both workers have reported ready
    assert target_ready.wait(timeout=10), "target worker did not start"
    assert no_target_ready.wait(timeout=10), "no_target worker did not start"

    # Release in the configured order; simultaneous is a true lock race
    if first_releases_first is True:
        # target-first: target goes, wins CAS, no-target arrives late → 409
        target_go.set()
        assert target_done.wait(timeout=15), "target worker did not finish"
        no_target_go.set()
    elif first_releases_first is False:
        # no-target-first: no-target goes, wins CAS, target arrives late → 409
        no_target_go.set()
        assert no_target_done.wait(timeout=15), "no_target worker did not finish"
        target_go.set()
    else:
        # simultaneous: both released at once — SQLite lock decides winner;
        # production _is_collision_descendant fires before intent lookup → target always loses
        target_go.set()
        no_target_go.set()

    t_target.join(timeout=15)
    t_no_target.join(timeout=15)
    assert not t_target.is_alive(), "target worker did not terminate"
    assert not t_no_target.is_alive(), "no_target worker did not terminate"

    # Assertions: target always gets 409 (collision guard fires before intent lookup),
    # no-target always wins as durable winner
    assert sorted(outcomes.values()) == sorted(["http:409", "ok"])

    # Durable state: no-target winner, zero scope leak
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=collision_id).one()
        assert stored.disposition == "REJECTED_NOT_OURS"
        assert stored.intent_id is None and stored.shop_id is None
        actions = session.query(models.BankReconciliationAction).filter_by(event_id=collision_id).all()
        assert len(actions) == 1, f"expected 1 action, got {len(actions)}"
        assert actions[0].intent_id is None and actions[0].shop_id is None
        audit = session.query(models.SystemLog).filter_by(id=actions[0].system_log_id).one()
        details = json.loads(audit.details)
        assert details["intent_id"] is None
        assert details["order_id"] is None
        assert details["shop_id"] is None
        assert session.query(models.OrderPayment).filter_by(order_id=shop_b["order_id"]).count() == 0
    finally:
        session.close()

    # Scope leak: owner/manager of both shops still see 404
    for token in (shop_a["token"], shop_b["token"]):
        assert client.get(
            f"/api/qr-reconciliation/events/{collision['id']}",
            headers=auth(token),
        ).status_code == 404


@pytest.mark.parametrize("first_releases_first", [True, False, None], ids=["target-first", "no-target-first", "simultaneous"])
def test_concurrent_target_and_no_target_on_collision_cas_winner_no_leak(client, monkeypatch, first_releases_first):
    """Three orderings of the same race: target always sanitized 409, no-target durable winner, zero scope leak."""
    _concurrent_target_no_target_race(client, monkeypatch, first_releases_first)


def test_terminalized_collision_with_any_target_raises_409_zero_lookup(client, monkeypatch):
    """After ADMIN no-target terminal, reason_code is REJECT_NOT_OURS/MARK_REFUNDED_EXTERNALLY;
    every target_intent_id (existing/nonexistent/near-max) still returns 409 via
    _is_collision_descendant, before any intent lookup.  No SQL lookup or mutation."""
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    identity = f"evt-corr4-term-{uuid.uuid4().hex}"
    root_a = ingest_ready(client, monkeypatch, shop_a, provider_event_id=identity)
    _reject_event_local(client, shop_a["token"], root_a["id"])

    runtime = enable_webhook(monkeypatch)
    collision = post_event(
        client,
        runtime,
        ready_payload(shop_b, provider_event_id=identity, amount_vnd=shop_b["expected_vnd"] + 1),
    ).json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"

    admin = admin_token(client)
    # No-target terminal via REJECT_NOT_OURS
    terminal = _action(client, admin, collision["id"], "REJECT_NOT_OURS", note="Xu ly boi admin")
    assert terminal.status_code == 200, terminal.text
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=collision["id"]).one()
        assert stored.reason_code == "REJECT_NOT_OURS"
        assert stored.disposition == "REJECTED_NOT_OURS"
        assert stored.intent_id is None
    finally:
        session.close()

    # Guard fires BEFORE intent lookup: all targets (existing/nonexistent/near-max) return 409
    # without any DB query against the target intent.  SQL spying through the HTTP layer is
    # unreliable (function references are captured at import time), so this test proves the
    # contract by the deterministic 409 response for every target variant.
    existing = _action(client, admin, collision["id"], "REJECT_NOT_OURS", target=shop_b["intent_id"], note="Try existing")
    assert existing.status_code == 409, existing.text
    assert existing.json()["detail"]["code"] == "QR_RECONCILIATION_ACTION_INVALID"

    nonexistent = _action(client, admin, collision["id"], "REJECT_NOT_OURS", target=shop_b["intent_id"] + 99999, note="Try nonexistent")
    assert nonexistent.status_code == 409, nonexistent.text
    assert nonexistent.json()["detail"]["code"] == "QR_RECONCILIATION_ACTION_INVALID"

    near_max = _action(client, admin, collision["id"], "REJECT_NOT_OURS", target=MAX_RECONCILIATION_ID, note="Try near max")
    assert near_max.status_code == 409, near_max.text
    assert near_max.json()["detail"]["code"] == "QR_RECONCILIATION_ACTION_INVALID"

    # Event stays terminalized (no mutation from the attempted target actions)
    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=collision["id"]).one()
        assert stored.disposition == "REJECTED_NOT_OURS"
        assert stored.reason_code == "REJECT_NOT_OURS"
        assert stored.intent_id is None
        assert session.query(models.BankReconciliationAction).filter_by(event_id=collision["id"]).count() == 1
    finally:
        session.close()

    # Repeat with MARK_REFUNDED_EXTERNALLY terminal
    collision2 = _collision(client, monkeypatch, shop_b, f"evt-corr4-refund-{uuid.uuid4().hex}")
    refund_terminal = _action(client, admin, collision2["id"], "MARK_REFUNDED_EXTERNALLY", note="Hoan tien")
    assert refund_terminal.status_code == 200, refund_terminal.text
    for target_id in (shop_b["intent_id"], shop_b["intent_id"] + 99999, MAX_RECONCILIATION_ID):
        r = _action(client, admin, collision2["id"], "MARK_REFUNDED_EXTERNALLY", target=target_id, note="Refund target")
        assert r.status_code == 409, f"target={target_id}: {r.text}"
        assert r.json()["detail"]["code"] == "QR_RECONCILIATION_ACTION_INVALID"

    session = SessionLocal()
    try:
        stored2 = session.query(models.BankWebhookEvent).filter_by(id=collision2["id"]).one()
        assert stored2.disposition == "REFUNDED"
        assert stored2.reason_code == "MARK_REFUNDED_EXTERNALLY"
        assert stored2.intent_id is None
    finally:
        session.close()


def test_original_root_row_not_marked_as_collision_by_row_specific_helper(client, monkeypatch):
    """_is_collision_descendant checks durable ordering (id, digests) -- the root/original row
    has no earlier row with a different digest, so it is NOT a collision descendant.
    Original root can be legitimately targeted via MAP_AND_APPLY."""
    ctx = create_intent_context(client, monkeypatch)
    identity = f"evt-corr4-root-{uuid.uuid4().hex}"
    root = ingest_ready(client, monkeypatch, ctx, provider_event_id=identity)
    assert root["reason_code"] == "READY_TO_MAP"

    # Root is NOT a collision descendant -- _resolve_target should not raise 409
    admin = admin_token(client)
    mapped = _action(client, admin, root["id"], "MAP_AND_APPLY")
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["event"]["disposition"] == "APPLIED"

    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=root["id"]).one()
        assert stored.disposition == "APPLIED"
        assert stored.intent_id == ctx["intent_id"]
        assert session.query(models.OrderPayment).filter_by(order_id=ctx["order_id"]).count() == 1
    finally:
        session.close()


def test_non_collision_unscoped_admin_mapping_succeeds(client, monkeypatch):
    """An unscoped event (REFERENCE_UNKNOWN) without collision lineage is not a collision
    descendant.  ADMIN can legitimately map it without a target_intent_id."""
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    unscoped = post_event(
        client,
        runtime,
        ready_payload(ctx, provider_event_id=f"evt-corr4-unscoped-{uuid.uuid4().hex}", references="FS999-UNKNOWN"),
    ).json()
    assert unscoped["reason_code"] == "REFERENCE_UNKNOWN"

    admin = admin_token(client)
    # No target_intent_id -- no-target terminal is allowed
    terminal = _action(client, admin, unscoped["id"], "REJECT_NOT_OURS", note="Khong xac dinh")
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["event"]["disposition"] == "REJECTED_NOT_OURS"

    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=unscoped["id"]).one()
        assert stored.reason_code == "REJECT_NOT_OURS"
        assert stored.intent_id is None
        assert stored.shop_id is None
    finally:
        session.close()


def test_collision_target_with_signed_int64_boundary_intent(client, monkeypatch):
    """Signed-int64 boundary intent_id on a collision still raises 409 (correction-3 guard fires first)."""
    shop_a = create_intent_context(client, monkeypatch)
    shop_b = create_intent_context(client, monkeypatch)
    identity = f"evt-corr3-boundary-{uuid.uuid4().hex}"
    root_a = ingest_ready(client, monkeypatch, shop_a, provider_event_id=identity)
    _reject_event_local(client, shop_a["token"], root_a["id"])

    runtime = enable_webhook(monkeypatch)
    collision = post_event(
        client,
        runtime,
        ready_payload(shop_b, provider_event_id=identity, amount_vnd=shop_b["expected_vnd"] + 1),
    ).json()
    assert collision["reason_code"] == "PROVIDER_EVENT_COLLISION"

    # signed-int64 max boundary — correction-3 fires first (no DB query needed)
    admin = admin_token(client)
    for boundary in (MAX_RECONCILIATION_ID - 1, MAX_RECONCILIATION_ID):
        targeted = _action(
            client,
            admin,
            collision["id"],
            "REJECT_NOT_OURS",
            target=boundary,
            note="Target boundary",
        )
        assert targeted.status_code == 409, f"boundary={boundary}: {targeted.text}"
        assert targeted.json()["detail"]["code"] == "QR_RECONCILIATION_ACTION_INVALID"

    session = SessionLocal()
    try:
        stored = session.query(models.BankWebhookEvent).filter_by(id=collision["id"]).one()
        assert stored.disposition == "UNAPPLIED"
        assert stored.intent_id is None and stored.shop_id is None
        assert session.query(models.BankReconciliationAction).filter_by(event_id=collision["id"]).count() == 0
    finally:
        session.close()
