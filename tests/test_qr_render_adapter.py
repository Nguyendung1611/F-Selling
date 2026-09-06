"""I10-B: adapter server-side chỉ trả bytes, không provider/network/URL."""
from __future__ import annotations

import hashlib
import socket
import uuid

import pytest

from conftest import auth, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import qr_sales_service


def _payload(ctx):
    return {
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


def _create_v1(client, monkeypatch, adapter=None):
    runtime = qr_sales_service.report_only_test_runtime(adapter)
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: runtime)
    ctx = seller_with_shop(client)
    created = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json=_payload(ctx),
        headers=auth(ctx["token"]),
    )
    assert created.status_code == 200, created.text
    return ctx, created.json(), runtime


def _db_snapshot(order_id):
    session = SessionLocal()
    try:
        order = session.query(models.Order).filter_by(id=order_id).one()
        intent = session.query(models.QrPaymentIntent).filter_by(order_id=order_id).one()
        return {
            "order": (
                order.id,
                order.status,
                order.total_amount,
                order.payment_method,
                order.operation_id,
            ),
            "intent": (
                intent.id,
                intent.contract_version,
                intent.order_id,
                intent.shop_id,
                intent.canonical_reference,
                intent.expected_vnd,
                intent.bank_code,
                intent.account_no,
                intent.account_name,
                intent.adapter_profile_id,
                intent.issued_at,
                intent.display_expires_at,
                intent.cancel_after,
            ),
            "payments": session.query(models.OrderPayment).filter_by(
                order_id=order_id
            ).count(),
            "issuance_audits": session.query(models.SystemLog).filter_by(
                shop_id=order.shop_id,
                action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
            ).count(),
        }
    finally:
        session.close()


def _instruction(reference="FS1-" + "A" * 32):
    return qr_sales_service.QrInstruction(
        contract_version=1,
        order_id=12,
        shop_id=34,
        canonical_reference=reference,
        expected_vnd=123_456,
        bank_code="VCB",
        account_no="00112233",
        account_name="TEST ACCOUNT",
    )


def test_mock_adapter_is_deterministic_png_bytes_only():
    adapter = qr_sales_service.DeterministicMockQrAdapter()

    first = adapter.render(_instruction())
    retry = adapter.render(_instruction())
    changed = adapter.render(_instruction("FS1-" + "B" * 32))

    assert first == retry
    assert first.media_type == "image/png"
    assert type(first.content) is bytes
    assert first.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(first.content) == 165
    assert hashlib.sha256(first.content).hexdigest() == (
        "4c7882ab82316683a0a93f7db025fc558b833f1eb683248ffc5baefe042a9aed"
    )
    assert changed.content != first.content
    assert b"http" not in first.content.lower()


def test_mock_adapter_never_opens_a_network_connection(monkeypatch):
    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("QR mock attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    rendered = qr_sales_service.DeterministicMockQrAdapter().render(_instruction())

    assert rendered.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_retry_returns_exact_bytes_headers_and_never_mutates_payment(
    client, monkeypatch
):
    ctx, created, _runtime = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    before = _db_snapshot(order_id)

    first = client.get(
        f"/api/orders/{order_id}/qr/render", headers=auth(ctx["token"])
    )
    retry = client.get(
        f"/api/orders/{order_id}/qr/render", headers=auth(ctx["token"])
    )

    assert first.status_code == retry.status_code == 200
    assert first.content == retry.content
    assert first.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert first.headers["content-type"].startswith("image/png")
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert "content-disposition" not in first.headers
    assert _db_snapshot(order_id) == before
    assert before["order"][1] == "PENDING"
    assert before["payments"] == 0
    assert before["issuance_audits"] == 1


def test_adapter_unavailable_after_commit_keeps_intent_and_returns_stable_error(
    client, monkeypatch
):
    ctx, created, _runtime = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    reference = created["qr_intent"]["canonical_reference"]
    account_no = created["qr_intent"]["bank_account_no"]
    before = _db_snapshot(order_id)
    disabled = qr_sales_service.QrSalesRuntime(
        mode="OFF", adapter=qr_sales_service.DisabledQrAdapter()
    )
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: disabled)

    metadata = client.get(
        f"/api/orders/{order_id}/qr", headers=auth(ctx["token"])
    )
    rendered = client.get(
        f"/api/orders/{order_id}/qr/render", headers=auth(ctx["token"])
    )

    assert metadata.status_code == 200
    assert metadata.json()["canonical_reference"] == reference
    assert metadata.json()["capability"] == {
        "mode": "OFF",
        "render_available": False,
        "render_endpoint": None,
    }
    assert rendered.status_code == 503
    assert rendered.json()["detail"]["code"] == "QR_RENDER_UNAVAILABLE"
    assert rendered.headers["cache-control"] == "no-store"
    assert rendered.headers["x-content-type-options"] == "nosniff"
    assert reference not in rendered.text
    assert account_no not in rendered.text
    assert _db_snapshot(order_id) == before


class FailingMockAdapter:
    profile_id = qr_sales_service.ADAPTER_PROFILE_MOCK
    test_only = True

    def __init__(self, marker):
        self.marker = marker

    def render(self, instruction):
        raise RuntimeError(
            f"{self.marker}:{instruction.canonical_reference}:{instruction.account_no}"
        )


def test_render_exception_is_sanitized_and_never_logs_reference_or_account(
    client, monkeypatch
):
    ctx, created, _runtime = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    reference = created["qr_intent"]["canonical_reference"]
    account_no = created["qr_intent"]["bank_account_no"]
    marker = "RAW-ADAPTER-SECRET"
    failing = qr_sales_service.report_only_test_runtime(FailingMockAdapter(marker))
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: failing)
    logs = []
    monkeypatch.setattr(qr_sales_service, "log_to_file", logs.append)
    before = _db_snapshot(order_id)

    response = client.get(
        f"/api/orders/{order_id}/qr/render", headers=auth(ctx["token"])
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "QR_RENDER_FAILED"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    combined = response.text + "\n" + "\n".join(logs)
    assert marker not in combined
    assert reference not in combined
    assert account_no not in combined
    assert logs == ["QR render failed code=QR_RENDER_FAILED"]
    assert _db_snapshot(order_id) == before


class InvalidMockAdapter:
    profile_id = qr_sales_service.ADAPTER_PROFILE_MOCK
    test_only = True

    def __init__(self, result):
        self.result = result

    def render(self, _instruction):
        return self.result


@pytest.mark.parametrize(
    "result",
    [
        qr_sales_service.QrRenderResult(b"not-png", "image/svg+xml"),
        qr_sales_service.QrRenderResult(
            b"x" * (qr_sales_service.RENDER_MAX_BYTES + 1), "image/png"
        ),
        qr_sales_service.QrRenderResult(b"", "image/png"),
        qr_sales_service.QrRenderResult("not-bytes", "image/png"),
        (b"raw tuple", "image/png"),
    ],
)
def test_render_rejects_nonallowlisted_oversized_or_malformed_output(
    client, monkeypatch, result
):
    ctx, created, _runtime = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    invalid = qr_sales_service.report_only_test_runtime(InvalidMockAdapter(result))
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: invalid)
    logs = []
    monkeypatch.setattr(qr_sales_service, "log_to_file", logs.append)
    before = _db_snapshot(order_id)

    response = client.get(
        f"/api/orders/{order_id}/qr/render", headers=auth(ctx["token"])
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "QR_RENDER_INVALID_OUTPUT"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert logs == ["QR render failed code=QR_RENDER_INVALID_OUTPUT"]
    assert _db_snapshot(order_id) == before


def test_disabled_adapter_cannot_be_installed_as_report_only_test_runtime():
    with pytest.raises(ValueError, match="test-only adapter"):
        qr_sales_service.report_only_test_runtime(
            qr_sales_service.DisabledQrAdapter()
        )
