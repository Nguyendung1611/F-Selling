"""I10-C adapter, strict normalization and durable inbox evidence."""
from __future__ import annotations

import asyncio
import inspect
import threading
import uuid

import pytest
from fastapi import HTTPException

from conftest import auth
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import qr_sales_service, qr_webhook_service
from i10c_helpers import (
    create_intent_context,
    enable_webhook,
    post_event,
    raw_event,
    ready_payload,
    webhook_headers,
)


def _event_count() -> int:
    session = SessionLocal()
    try:
        return session.query(models.BankWebhookEvent).count()
    finally:
        session.close()


def _raw_asgi_request(
    headers: list[tuple[bytes, bytes]],
    *,
    body: bytes,
    stream_error: Exception | None = None,
):
    reads = {"count": 0}

    async def receive():
        reads["count"] += 1
        if stream_error is not None:
            raise stream_error
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/qr-payments/webhook",
        "raw_path": b"/api/qr-payments/webhook",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    return qr_webhook_service.Request(scope, receive), reads


def _valid_raw_headers(runtime, body: bytes) -> list[tuple[bytes, bytes]]:
    return [
        (b"content-type", b"application/json"),
        (b"x-bank-webhook-token", b"i10c-test-token"),
        (
            b"x-bank-webhook-signature",
            runtime.adapter.signature_for(body).encode("ascii"),
        ),
        (b"content-length", str(len(body)).encode("ascii")),
    ]


def test_installed_webhook_is_disabled_and_reads_no_body_or_database(client, monkeypatch):
    before = _event_count()
    called = False
    # Even a hostile REPORT_ONLY environment label cannot install the mock.
    monkeypatch.setattr(
        qr_webhook_service.config, "QR_WEBHOOK_MODE", "REPORT_ONLY"
    )
    installed = qr_webhook_service.get_runtime()
    assert installed.enabled_test_adapter is False
    assert isinstance(installed.adapter, qr_webhook_service.DisabledWebhookAdapter)

    async def forbidden_stream(_request):
        nonlocal called
        called = True
        yield b"must-not-be-read"

    # The disabled decision is made before `request.stream()` is reached.
    monkeypatch.setattr(qr_webhook_service.Request, "stream", forbidden_stream)
    response = client.post("/api/qr-payments/webhook", content=b"private")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "QR_WEBHOOK_DISABLED"
    assert called is False
    assert _event_count() == before
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("kind", "expected_status", "expected_code"),
    [
        ("content_type", 415, "QR_WEBHOOK_CONTENT_TYPE_INVALID"),
        ("missing_auth", 401, "QR_WEBHOOK_AUTH_INVALID"),
        ("bad_signature", 401, "QR_WEBHOOK_AUTH_INVALID"),
        ("bad_json", 400, "QR_WEBHOOK_BODY_INVALID"),
        ("too_large", 413, "QR_WEBHOOK_BODY_TOO_LARGE"),
        ("lying_length", 413, "QR_WEBHOOK_BODY_TOO_LARGE"),
    ],
)
def test_invalid_type_auth_body_and_size_write_nothing(
    client, monkeypatch, kind, expected_status, expected_code
):
    runtime = enable_webhook(monkeypatch)
    before = _event_count()
    body = b"{}"
    headers = webhook_headers(runtime, body)
    if kind == "content_type":
        headers["Content-Type"] = "text/plain"
    elif kind == "missing_auth":
        headers.pop("X-Bank-Webhook-Token")
    elif kind == "bad_signature":
        headers["X-Bank-Webhook-Signature"] = "0" * 64
    elif kind == "bad_json":
        body = b'{"amount_vnd":'
        headers = webhook_headers(runtime, body)
    elif kind in {"too_large", "lying_length"}:
        body = b"{" + b"x" * qr_webhook_service.MAX_BODY_BYTES + b"}"
        headers = webhook_headers(runtime, body)
        if kind == "lying_length":
            headers["Content-Length"] = "1"

    response = client.post("/api/qr-payments/webhook", content=body, headers=headers)

    assert response.status_code == expected_status, response.text
    assert response.json()["detail"]["code"] == expected_code
    assert _event_count() == before
    text = response.text.lower()
    assert "signature" not in text and "token" not in text and body[:20].hex() not in text


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    ("header_name", "duplicate_value", "status", "code"),
    [
        (b"content-type", b"text/plain", 415, "QR_WEBHOOK_CONTENT_TYPE_INVALID"),
        (b"x-bank-webhook-token", b"hostile-token", 401, "QR_WEBHOOK_AUTH_INVALID"),
        (b"x-bank-webhook-signature", b"f" * 64, 401, "QR_WEBHOOK_AUTH_INVALID"),
        (b"content-length", b"2", 400, "QR_WEBHOOK_BODY_INVALID"),
    ],
)
def test_raw_asgi_duplicate_critical_headers_are_rejected_before_body_read(
    monkeypatch, header_name, duplicate_value, status, code, reverse
):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    headers = _valid_raw_headers(runtime, body)
    duplicate = (header_name.upper(), duplicate_value)
    headers = ([duplicate] + headers) if reverse else (headers + [duplicate])
    request, reads = _raw_asgi_request(headers, body=body)
    before = _event_count()

    with pytest.raises(HTTPException) as caught:
        qr_webhook_service.validate_metadata(request, runtime)

    assert caught.value.status_code == status
    assert caught.value.detail["code"] == code
    assert reads["count"] == 0
    assert _event_count() == before


@pytest.mark.parametrize("with_content_length", [False, True])
def test_raw_asgi_transfer_encoding_is_always_rejected_before_body_read(
    monkeypatch, with_content_length
):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    headers = _valid_raw_headers(runtime, body)
    if not with_content_length:
        headers = [item for item in headers if item[0] != b"content-length"]
    headers.append((b"Transfer-Encoding", b"chunked"))
    request, reads = _raw_asgi_request(headers, body=body)

    with pytest.raises(HTTPException) as caught:
        qr_webhook_service.validate_metadata(request, runtime)

    assert caught.value.status_code == 400
    assert caught.value.detail["code"] == "QR_WEBHOOK_BODY_INVALID"
    assert reads["count"] == 0


@pytest.mark.parametrize(
    ("content_type", "status"),
    [
        (b"application/json; charset=utf-8", 415),
        (b"Application/JSON", 415),
        (b" application/json", 415),
        (b"application/json ", 415),
    ],
)
def test_raw_asgi_content_type_must_be_exact_canonical_value(
    monkeypatch, content_type, status
):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    headers = _valid_raw_headers(runtime, body)
    headers[0] = (b"Content-Type", content_type)
    request, reads = _raw_asgi_request(headers, body=body)

    with pytest.raises(HTTPException) as caught:
        qr_webhook_service.validate_metadata(request, runtime)

    assert caught.value.status_code == status
    assert caught.value.detail["code"] == "QR_WEBHOOK_CONTENT_TYPE_INVALID"
    assert reads["count"] == 0


@pytest.mark.parametrize(
    ("declared", "status", "code"),
    [
        (b"+2", 400, "QR_WEBHOOK_BODY_INVALID"),
        (b" 2", 400, "QR_WEBHOOK_BODY_INVALID"),
        (b"2 ", 400, "QR_WEBHOOK_BODY_INVALID"),
        (b"02", 400, "QR_WEBHOOK_BODY_INVALID"),
        (b"", 400, "QR_WEBHOOK_BODY_INVALID"),
        (b"2, 2", 400, "QR_WEBHOOK_BODY_INVALID"),
        (b"9" * 200, 413, "QR_WEBHOOK_BODY_TOO_LARGE"),
        (
            str(qr_webhook_service.MAX_BODY_BYTES + 1).encode("ascii"),
            413,
            "QR_WEBHOOK_BODY_TOO_LARGE",
        ),
    ],
)
def test_raw_asgi_content_length_is_canonical_and_bounded(
    monkeypatch, declared, status, code
):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    headers = _valid_raw_headers(runtime, body)
    headers[-1] = (b"Content-Length", declared)
    request, reads = _raw_asgi_request(headers, body=body)

    with pytest.raises(HTTPException) as caught:
        qr_webhook_service.validate_metadata(request, runtime)

    assert caught.value.status_code == status
    assert caught.value.detail["code"] == code
    assert reads["count"] == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (b"x-bank-webhook-token", b"i10c-test-token\r"),
        (b"content-type", b"application/json\xff"),
        (b"bad header", b"value"),
    ],
)
def test_raw_asgi_malformed_non_ascii_or_control_headers_are_rejected(
    monkeypatch, name, value
):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    headers = _valid_raw_headers(runtime, body)
    headers.append((name, value))
    request, reads = _raw_asgi_request(headers, body=body)

    with pytest.raises(HTTPException) as caught:
        qr_webhook_service.validate_metadata(request, runtime)

    assert caught.value.status_code == 400
    assert caught.value.detail["code"] == "QR_WEBHOOK_BODY_INVALID"
    assert reads["count"] == 0


def test_raw_asgi_stream_exception_is_sanitized_and_writes_nothing(monkeypatch):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    request, _reads = _raw_asgi_request(
        _valid_raw_headers(runtime, body),
        body=body,
        stream_error=RuntimeError("raw-private-stream-failure"),
    )
    metadata = qr_webhook_service.validate_metadata(request, runtime)
    before = _event_count()

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            qr_webhook_service.read_authenticated_envelope(
                request, runtime, metadata
            )
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == {
        "code": "QR_WEBHOOK_BODY_INVALID",
        "message": "Webhook body is invalid",
    }
    assert "private" not in str(caught.value.detail).lower()
    assert _event_count() == before


@pytest.mark.parametrize("declared", [b"1", b"3"])
def test_raw_asgi_declared_and_actual_lengths_must_match(monkeypatch, declared):
    runtime = enable_webhook(monkeypatch)
    body = b"{}"
    headers = _valid_raw_headers(runtime, body)
    headers[-1] = (b"content-length", declared)
    request, _reads = _raw_asgi_request(headers, body=body)
    metadata = qr_webhook_service.validate_metadata(request, runtime)
    before = _event_count()

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            qr_webhook_service.read_authenticated_envelope(
                request, runtime, metadata
            )
        )

    assert caught.value.status_code == 400
    assert caught.value.detail["code"] == "QR_WEBHOOK_BODY_INVALID"
    assert _event_count() == before


@pytest.mark.parametrize(
    "body",
    [
        b'{"amount_vnd":1,"amount_vnd":2}',
        b'{"unexpected":"field"}',
        b'{"occurred_at":"2026-08-13 01:02:03"}',
        b'[1,2,3]',
        b'{"references":' + b"[" * 1100 + b"]" * 1100 + b"}",
    ],
)
def test_duplicate_keys_extra_fields_naive_time_and_nonobject_are_rejected(
    client, monkeypatch, body
):
    runtime = enable_webhook(monkeypatch)
    before = _event_count()
    response = client.post(
        "/api/qr-payments/webhook",
        content=body,
        headers=webhook_headers(runtime, body),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "QR_WEBHOOK_BODY_INVALID"
    assert _event_count() == before


@pytest.mark.parametrize("amount", [True, 100_000.0, "100000", -1])
def test_exact_integer_vnd_rejects_bool_float_string_and_negative(
    client, monkeypatch, amount
):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    before = _event_count()
    response = post_event(
        client,
        runtime,
        ready_payload(ctx, amount_vnd=amount),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "QR_WEBHOOK_BODY_INVALID"
    assert _event_count() == before


def test_normalized_digest_exact_replay_and_provider_collision_are_durable(
    client, monkeypatch
):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    payload = ready_payload(ctx, provider_event_id="evt-format-collision")
    session = SessionLocal()
    try:
        audits_before = session.query(models.SystemLog).count()
    finally:
        session.close()
    first = post_event(client, runtime, payload, sort_keys=True, compact=True)
    replay = post_event(client, runtime, payload, sort_keys=True, compact=True)
    reformatted = post_event(client, runtime, payload, sort_keys=False, compact=False)

    assert first.status_code == replay.status_code == reformatted.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert first.json()["exact_replay"] is False
    assert replay.json()["exact_replay"] is True
    assert reformatted.json()["id"] != first.json()["id"]
    assert reformatted.json()["reason_code"] == "PROVIDER_EVENT_COLLISION"

    session = SessionLocal()
    try:
        rows = session.query(models.BankWebhookEvent).filter_by(
            provider_event_id="evt-format-collision"
        ).order_by(models.BankWebhookEvent.id).all()
        assert len(rows) == 2
        assert rows[0].normalized_sha256 == rows[1].normalized_sha256
        assert rows[0].envelope_sha256 != rows[1].envelope_sha256
        assert all(row.disposition == "UNAPPLIED" for row in rows)
        assert all(row.state_version == 0 and row.payment_id is None for row in rows)
        assert session.query(models.OrderPayment).filter_by(
            order_id=ctx["order_id"]
        ).count() == 0
        assert session.query(models.BankReconciliationAction).filter(
            models.BankReconciliationAction.event_id.in_([row.id for row in rows])
        ).count() == 0
        assert session.query(models.SystemLog).count() == audits_before
    finally:
        session.close()


@pytest.mark.parametrize(
    ("changes", "reason", "mapped"),
    [
        ({"amount_vnd": 50_000}, "AMOUNT_UNDERPAID", True),
        ({"amount_vnd": 150_000}, "AMOUNT_OVERPAID", True),
        ({"amount_vnd": 0}, "AMOUNT_ZERO", True),
        ({"amount_vnd": None}, "AMOUNT_MISSING", True),
        ({"account_no": "999999"}, "ACCOUNT_MISMATCH", True),
        ({"account_no": None}, "ACCOUNT_MISSING", True),
        ({"direction": "OUT"}, "DIRECTION_OUTBOUND", True),
        ({"direction": "UNKNOWN"}, "DIRECTION_UNKNOWN", True),
        ({"references": None}, "REFERENCE_MISSING", False),
        ({"references": ["FS1-A", "FS1-B"]}, "REFERENCE_MULTIPLE", False),
        ({"references": "bad reference !"}, "REFERENCE_INVALID", False),
        (
            {"references": "FS1-TRUNC", "reference_truncated": True},
            "REFERENCE_TRUNCATED",
            False,
        ),
        ({"references": "FS1-UNKNOWN"}, "REFERENCE_UNKNOWN", False),
    ],
)
def test_conservative_truth_table_never_auto_applies(
    client, monkeypatch, changes, reason, mapped
):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    response = post_event(client, runtime, ready_payload(ctx, **changes))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reason_code"] == reason
    assert body["disposition"] == "UNAPPLIED"
    assert body["state_version"] == 0
    assert (body["intent_id"] == ctx["intent_id"]) is mapped
    session = SessionLocal()
    try:
        order = session.query(models.Order).filter_by(id=ctx["order_id"]).one()
        assert order.status == "PENDING"
        assert session.query(models.OrderPayment).filter_by(order_id=order.id).count() == 0
    finally:
        session.close()


@pytest.mark.parametrize(
    ("status", "reason"),
    [("CANCELLED", "ORDER_FINAL_CANCELLED"), ("UNRECONCILED", "ORDER_NOT_PENDING")],
)
def test_late_or_final_cancelled_evidence_never_resurrects(
    client, monkeypatch, status, reason
):
    ctx = create_intent_context(client, monkeypatch)
    session = SessionLocal()
    try:
        order = session.query(models.Order).filter_by(id=ctx["order_id"]).one()
        order.status = status
        if status == "UNRECONCILED":
            order.reconciliation_reason = "UNDERPAID"
        session.commit()
    finally:
        session.close()
    runtime = enable_webhook(monkeypatch)
    response = post_event(client, runtime, ready_payload(ctx))
    assert response.status_code == 200
    assert response.json()["reason_code"] == reason
    session = SessionLocal()
    try:
        assert session.query(models.Order).filter_by(id=ctx["order_id"]).one().status == status
        assert session.query(models.OrderPayment).filter_by(order_id=ctx["order_id"]).count() == 0
    finally:
        session.close()


def test_underpayment_hides_existing_qr_without_replacement(client, monkeypatch):
    ctx = create_intent_context(client, monkeypatch)
    runtime = enable_webhook(monkeypatch)
    response = post_event(
        client,
        runtime,
        ready_payload(ctx, amount_vnd=ctx["expected_vnd"] - 1),
    )
    assert response.status_code == 200
    metadata = client.get(
        f"/api/orders/{ctx['order_id']}/qr", headers=auth(ctx["token"])
    )
    assert metadata.status_code == 200
    assert metadata.json()["hidden"] is True
    assert metadata.json()["capability"]["render_available"] is False
    assert "canonical_reference" not in metadata.json()
    assert "bank_account_no" not in metadata.json()
    render = client.get(
        f"/api/orders/{ctx['order_id']}/qr/render", headers=auth(ctx["token"])
    )
    assert render.status_code == 409
    assert render.json()["detail"]["code"] == "QR_RENDER_HIDDEN_UNDERPAYMENT"
    session = SessionLocal()
    try:
        assert session.query(models.QrPaymentIntent).filter_by(
            order_id=ctx["order_id"]
        ).count() == 1
    finally:
        session.close()


def test_concurrent_exact_replay_has_one_durable_winner(monkeypatch):
    normalized = qr_webhook_service.NormalizedBankEvent(
        provider="mock_bank",
        provider_event_id=f"evt-race-{uuid.uuid4().hex}",
        normalized_account_no="123",
        direction="IN",
        amount_vnd=1,
        reference_state="EXACT",
        normalized_reference="FS1-UNKNOWN-RACE",
        occurred_at="2026-08-13 01:02:03.000000",
    )
    envelope = raw_event({"race": uuid.uuid4().hex})
    barrier = threading.Barrier(2)
    real_lock = qr_webhook_service._acquire_inbox_write_lock

    def synchronized_lock(db):
        barrier.wait(timeout=5)
        return real_lock(db)

    monkeypatch.setattr(qr_webhook_service, "_acquire_inbox_write_lock", synchronized_lock)
    outcomes: list[tuple[int, bool]] = []
    errors: list[str] = []
    guard = threading.Lock()

    def worker():
        session = SessionLocal()
        try:
            row, replay = qr_webhook_service.ingest_normalized(
                session, normalized, envelope
            )
            result = (int(row.id), replay)
            with guard:
                outcomes.append(result)
        except Exception as exc:  # pragma: no cover - make thread failure visible
            with guard:
                errors.append(f"{type(exc).__name__}:{exc}")
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(outcomes) == 2
    assert outcomes[0][0] == outcomes[1][0]
    assert sorted(replay for _, replay in outcomes) == [False, True]
    session = SessionLocal()
    try:
        assert session.query(models.BankWebhookEvent).filter_by(
            provider_event_id=normalized.provider_event_id
        ).count() == 1
    finally:
        session.close()


def test_ambiguous_inbox_commit_recovers_exact_durable_winner(monkeypatch):
    provider_event_id = f"evt-commit-winner-{uuid.uuid4().hex}"
    normalized = qr_webhook_service.NormalizedBankEvent(
        provider="mock_bank",
        provider_event_id=provider_event_id,
        normalized_account_no="001122",
        direction="IN",
        amount_vnd=1,
        reference_state="MISSING",
        normalized_reference=None,
        occurred_at="2026-08-13 01:02:03.000000",
    )
    envelope = raw_event({"commit": uuid.uuid4().hex})
    real_commit = qr_webhook_service._commit_inbox

    def commit_then_raise(db):
        real_commit(db)
        raise RuntimeError("simulated ambiguous commit")

    monkeypatch.setattr(qr_webhook_service, "_commit_inbox", commit_then_raise)
    session = SessionLocal()
    try:
        row, replay = qr_webhook_service.ingest_normalized(
            session, normalized, envelope
        )
        assert replay is True
        assert row.provider_event_id == provider_event_id
        assert row.reason_code == "REFERENCE_MISSING"
    finally:
        session.close()
    verification = SessionLocal()
    try:
        assert verification.query(models.BankWebhookEvent).filter_by(
            provider_event_id=provider_event_id
        ).count() == 1
    finally:
        verification.close()


def test_true_precommit_inbox_failure_returns_503_and_zero_rows(monkeypatch):
    provider_event_id = f"evt-precommit-fail-{uuid.uuid4().hex}"
    normalized = qr_webhook_service.NormalizedBankEvent(
        provider="mock_bank",
        provider_event_id=provider_event_id,
        normalized_account_no="001122",
        direction="IN",
        amount_vnd=1,
        reference_state="MISSING",
        normalized_reference=None,
        occurred_at="2026-08-13 01:02:03.000000",
    )

    def fail_before_commit(_db):
        raise RuntimeError("simulated precommit failure")

    monkeypatch.setattr(qr_webhook_service, "_commit_inbox", fail_before_commit)
    session = SessionLocal()
    try:
        with pytest.raises(HTTPException) as caught:
            qr_webhook_service.ingest_normalized(
                session, normalized, raw_event({"precommit": uuid.uuid4().hex})
            )
        assert caught.value.status_code == 503
        assert caught.value.detail["code"] == "QR_WEBHOOK_PERSISTENCE_FAILED"
    finally:
        session.close()
    verification = SessionLocal()
    try:
        assert verification.query(models.BankWebhookEvent).filter_by(
            provider_event_id=provider_event_id
        ).count() == 0
    finally:
        verification.close()


def test_collision_ambiguous_commit_recovers_collision_not_original(monkeypatch):
    provider_event_id = f"evt-collision-commit-{uuid.uuid4().hex}"
    first_normalized = qr_webhook_service.NormalizedBankEvent(
        provider="mock_bank",
        provider_event_id=provider_event_id,
        normalized_account_no="001122",
        direction="IN",
        amount_vnd=1,
        reference_state="MISSING",
        normalized_reference=None,
        occurred_at="2026-08-13 01:02:03.000000",
    )
    session = SessionLocal()
    try:
        original, replay = qr_webhook_service.ingest_normalized(
            session, first_normalized, raw_event({"amount": 1})
        )
        assert replay is False
    finally:
        session.close()

    real_commit = qr_webhook_service._commit_inbox

    def commit_then_raise(db):
        real_commit(db)
        raise RuntimeError("simulated collision lost response")

    monkeypatch.setattr(qr_webhook_service, "_commit_inbox", commit_then_raise)
    conflicting = qr_webhook_service.NormalizedBankEvent(
        provider="mock_bank",
        provider_event_id=provider_event_id,
        normalized_account_no="001122",
        direction="IN",
        amount_vnd=2,
        reference_state="MISSING",
        normalized_reference=None,
        occurred_at="2026-08-13 01:02:03.000000",
    )
    session = SessionLocal()
    try:
        collision, replay = qr_webhook_service.ingest_normalized(
            session, conflicting, raw_event({"amount": 2})
        )
        assert replay is True
        assert collision.id != original.id
        assert collision.reason_code == "PROVIDER_EVENT_COLLISION"
        assert collision.intent_id is None and collision.shop_id is None
    finally:
        session.close()
    verification = SessionLocal()
    try:
        rows = verification.query(models.BankWebhookEvent).filter_by(
            provider_event_id=provider_event_id
        ).all()
        assert len(rows) == 2
        assert {row.amount_vnd for row in rows} == {1, 2}
        assert verification.query(models.OrderPayment).filter(
            models.OrderPayment.idempotency_key.in_([row.idempotency_key for row in rows])
        ).count() == 0
        assert verification.query(models.BankReconciliationAction).filter(
            models.BankReconciliationAction.event_id.in_([row.id for row in rows])
        ).count() == 0
    finally:
        verification.close()


def test_adapter_boundary_has_no_network_or_raw_persistence_surface():
    source = inspect.getsource(qr_webhook_service)
    for forbidden in (
        "requests.",
        "httpx.",
        "urllib.",
        "provider_url",
        "secret_from_env",
        "raw_body=",
        "payload=",
    ):
        assert forbidden not in source
