"""I09-H rollout gate: public capability and v0 cutoff stay fail-closed."""

from datetime import datetime
import uuid

import pytest

from conftest import auth, seller_with_shop
from fselling import models
from fselling.core import config
from fselling.core.database import SessionLocal
from fselling.services import offline_service


def _v0(product_id: int, *, offline_uuid: str | None = None) -> dict:
    return {
        "offline_uuid": offline_uuid or f"rollout-{uuid.uuid4().hex}",
        "sold_at": datetime.utcnow().isoformat(),
        "items": [{
            "product_id": product_id, "product_name": "Hàng rollout",
            "unit_price": 100_000, "quantity": 1,
        }],
        "cash_tendered": 100_000,
        "device_label": "test",
    }


def _counts(shop_id: int, product_id: int) -> tuple[int, int, int]:
    session = SessionLocal()
    try:
        order_ids = [row[0] for row in session.query(models.Order.id).filter(
            models.Order.shop_id == shop_id
        ).all()]
        return (
            len(order_ids),
            session.query(models.OrderPayment).filter(
                models.OrderPayment.order_id.in_(order_ids or [-1])
            ).count(),
            int(session.get(models.Product, product_id).stock),
        )
    finally:
        session.close()


def test_rollout_default_is_phase_a_and_phase_b_needs_14_days(monkeypatch):
    monkeypatch.delenv("OFFLINE_CONTRACT_MIN_VERSION", raising=False)
    monkeypatch.delenv("OFFLINE_CONTRACT_PHASE_A_STARTED_AT", raising=False)
    monkeypatch.delenv("OFFLINE_CONTRACT_CUTOFF_AT", raising=False)
    minimum, phase, started, cutoff, code = config._offline_contract_rollout_from_env()
    assert (minimum, phase, started, cutoff, code) == (
        0, "PHASE_A", None, None, "OFFLINE_CONTRACT_PHASE_A_V0_V1"
    )

    monkeypatch.setenv("OFFLINE_CONTRACT_MIN_VERSION", "1")
    monkeypatch.setenv("OFFLINE_CONTRACT_PHASE_A_STARTED_AT", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("OFFLINE_CONTRACT_CUTOFF_AT", "2026-01-15T00:00:00Z")
    assert config._offline_contract_rollout_from_env()[0:2] == (1, "PHASE_B")

    monkeypatch.setenv("OFFLINE_CONTRACT_CUTOFF_AT", "2026-01-14T23:59:59Z")
    with pytest.raises(RuntimeError, match="14 days"):
        config._offline_contract_rollout_from_env()
    monkeypatch.delenv("OFFLINE_CONTRACT_PHASE_A_STARTED_AT")
    with pytest.raises(RuntimeError, match="requires"):
        config._offline_contract_rollout_from_env()


def test_capability_is_authenticated_public_and_never_cached(client):
    ctx = seller_with_shop(client)
    denied = client.get("/api/offline/capability")
    assert denied.status_code == 401
    response = client.get("/api/offline/capability", headers=auth(ctx["token"]))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {
        "supported_versions", "minimum_accepted_version", "phase", "cutoff_at_utc", "policy_code"
    }
    assert "token" not in response.text.lower() and "digest" not in response.text.lower()


def test_phase_b_rejects_new_v0_without_writes_but_keeps_durable_retry(client, monkeypatch):
    ctx = seller_with_shop(client)
    product = ctx["product"]
    client.post(f"/api/shifts/{ctx['shop_id']}/open", headers=auth(ctx["token"]), json={"opening_cash_amount": 0})
    durable = _v0(product["id"])
    first = client.post(f"/api/orders/{ctx['shop_id']}/offline", headers=auth(ctx["token"]), json=durable)
    assert first.status_code == 200
    before = _counts(ctx["shop_id"], product["id"])
    monkeypatch.setattr(config, "OFFLINE_CONTRACT_MIN_VERSION", 1)
    retry = client.post(f"/api/orders/{ctx['shop_id']}/offline", headers=auth(ctx["token"]), json=durable)
    assert retry.status_code == 200 and retry.json()["created"] is False
    rejected = client.post(
        f"/api/orders/{ctx['shop_id']}/offline", headers=auth(ctx["token"]), json=_v0(product["id"])
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == offline_service.ERROR_V0_CUTOFF_RECOVERY_REQUIRED
    assert _counts(ctx["shop_id"], product["id"]) == before
