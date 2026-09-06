"""Local-only fixtures/helpers shared by focused I10-C tests."""
from __future__ import annotations

import json
import uuid

from conftest import auth, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import qr_sales_service, qr_webhook_service


def enable_sales_qr(monkeypatch):
    runtime = qr_sales_service.report_only_test_runtime()
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: runtime)
    return runtime


def create_intent_context(client, monkeypatch, *, quantity: int = 1) -> dict:
    enable_sales_qr(monkeypatch)
    ctx = seller_with_shop(client)
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "product_name": ctx["product"]["name"],
                    "price": 1,
                    "quantity": quantity,
                }
            ],
            "payment_method": "transfer",
            "operation_id": uuid.uuid4().hex,
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    ctx.update(
        {
            "order_id": body["order_id"],
            "intent": body["qr_intent"],
            "reference": body["qr_intent"]["canonical_reference"],
            "expected_vnd": body["qr_intent"]["expected_vnd"],
            "account_no": body["qr_intent"]["bank_account_no"],
        }
    )
    session = SessionLocal()
    try:
        ctx["intent_id"] = (
            session.query(models.QrPaymentIntent)
            .filter_by(order_id=ctx["order_id"])
            .one()
            .id
        )
    finally:
        session.close()
    return ctx


def enable_webhook(monkeypatch):
    runtime = qr_webhook_service.report_only_test_runtime()
    monkeypatch.setattr(qr_webhook_service, "get_runtime", lambda: runtime)
    return runtime


def raw_event(payload: dict, *, sort_keys: bool = True, compact: bool = True) -> bytes:
    separators = (",", ":") if compact else None
    return json.dumps(payload, sort_keys=sort_keys, separators=separators).encode("utf-8")


def webhook_headers(runtime, body: bytes) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Bank-Webhook-Token": "i10c-test-token",
        "X-Bank-Webhook-Signature": runtime.adapter.signature_for(body),
    }


def post_event(client, runtime, payload: dict, **json_options):
    body = raw_event(payload, **json_options)
    return client.post(
        "/api/qr-payments/webhook",
        content=body,
        headers=webhook_headers(runtime, body),
    )


def ready_payload(ctx: dict, *, provider_event_id: str | None = None, **changes) -> dict:
    payload = {
        "provider_event_id": provider_event_id or f"evt-{uuid.uuid4().hex}",
        "account_no": ctx["account_no"],
        "direction": "IN",
        "amount_vnd": ctx["expected_vnd"],
        "references": ctx["reference"],
        "occurred_at": "2026-08-13T01:02:03+00:00",
    }
    payload.update(changes)
    return payload


def ingest_ready(client, monkeypatch, ctx: dict, **changes) -> dict:
    runtime = enable_webhook(monkeypatch)
    response = post_event(client, runtime, ready_payload(ctx, **changes))
    assert response.status_code == 200, response.text
    return response.json()
