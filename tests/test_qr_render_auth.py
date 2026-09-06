"""I10-B: QR intent/render dùng auth shop-scope trước existence disclosure."""
from __future__ import annotations

import uuid

from conftest import admin_token, auth, new_seller, new_staff, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import qr_sales_service


def _create_v1(client, monkeypatch):
    runtime = qr_sales_service.report_only_test_runtime()
    monkeypatch.setattr(qr_sales_service, "get_runtime", lambda: runtime)
    ctx = seller_with_shop(client)
    created = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
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
        },
        headers=auth(ctx["token"]),
    )
    assert created.status_code == 200, created.text
    return ctx, created.json()


def test_owner_cashier_manager_and_admin_can_fetch_shop_qr(client, monkeypatch):
    ctx, created = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    _, cashier = new_staff(client, ctx, "CASHIER")
    _, manager = new_staff(client, ctx, "MANAGER")
    admin = admin_token(client)

    for token in (ctx["token"], cashier, manager, admin):
        metadata = client.get(f"/api/orders/{order_id}/qr", headers=auth(token))
        rendered = client.get(
            f"/api/orders/{order_id}/qr/render", headers=auth(token)
        )
        assert metadata.status_code == 200, metadata.text
        assert rendered.status_code == 200, rendered.text
        assert metadata.headers["cache-control"] == "no-store"
        assert rendered.headers["cache-control"] == "no-store"
        assert rendered.headers["x-content-type-options"] == "nosniff"


def test_warehouse_denied_without_cross_shop_existence_leak(client, monkeypatch):
    ctx, created = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    _, same_shop_warehouse = new_staff(client, ctx, "WAREHOUSE")
    other = seller_with_shop(client)
    _, other_warehouse = new_staff(client, other, "WAREHOUSE")

    for suffix in ("qr", "qr/render"):
        same_shop = client.get(
            f"/api/orders/{order_id}/{suffix}",
            headers=auth(same_shop_warehouse),
        )
        cross_shop = client.get(
            f"/api/orders/{order_id}/{suffix}", headers=auth(other_warehouse)
        )
        unknown = client.get(
            f"/api/orders/999999999/{suffix}", headers=auth(other_warehouse)
        )
        assert same_shop.status_code == 403
        assert cross_shop.status_code == unknown.status_code == 404
        assert cross_shop.json() == unknown.json()
        assert cross_shop.headers["cache-control"] == "no-store"
        if suffix.endswith("render"):
            assert cross_shop.headers["x-content-type-options"] == "nosniff"


def test_other_seller_and_unknown_order_are_indistinguishable_404(client, monkeypatch):
    ctx, created = _create_v1(client, monkeypatch)
    order_id = created["order_id"]
    _, other_token = new_seller(client)

    for suffix in ("qr", "qr/render"):
        hidden = client.get(
            f"/api/orders/{order_id}/{suffix}", headers=auth(other_token)
        )
        unknown = client.get(
            f"/api/orders/999999998/{suffix}", headers=auth(other_token)
        )
        assert hidden.status_code == unknown.status_code == 404
        assert hidden.json() == unknown.json() == {
            "detail": {
                "code": "QR_INTENT_NOT_FOUND",
                "message": "Không tìm thấy hướng dẫn chuyển khoản",
            }
        }


def test_qr_endpoints_require_bearer_header_not_query_or_cookie(client, monkeypatch):
    ctx, created = _create_v1(client, monkeypatch)
    order_id = created["order_id"]

    for suffix in ("qr", "qr/render"):
        no_auth = client.get(f"/api/orders/{order_id}/{suffix}")
        query_token = client.get(
            f"/api/orders/{order_id}/{suffix}",
            params={"token": ctx["token"]},
        )
        cookie_token = client.get(
            f"/api/orders/{order_id}/{suffix}",
            cookies={"access_token": ctx["token"]},
        )
        assert no_auth.status_code == query_token.status_code == cookie_token.status_code == 401
        assert query_token.headers["cache-control"] == "no-store"
        assert ctx["token"] not in query_token.text
        assert ctx["token"] not in cookie_token.text


def test_metadata_contract_is_sanitized_exact_integer_and_no_provider_url(
    client, monkeypatch
):
    ctx, created = _create_v1(client, monkeypatch)
    order_id = created["order_id"]

    response = client.get(
        f"/api/orders/{order_id}/qr", headers=auth(ctx["token"])
    )
    order_response = client.get(
        f"/api/orders/{order_id}", headers=auth(ctx["token"])
    )

    assert response.status_code == order_response.status_code == 200
    metadata = response.json()
    assert set(metadata) == {
        "contract_version",
        "canonical_reference",
        "expected_vnd",
        "bank_code",
        "bank_account_no",
        "bank_account_name",
        "issued_at",
        "instruction_only",
        "capability",
    }
    assert set(metadata["capability"]) == {
        "mode",
        "render_available",
        "render_endpoint",
    }
    assert type(metadata["expected_vnd"]) is int
    assert metadata["expected_vnd"] == 100_000
    assert metadata["instruction_only"] is True
    assert metadata["capability"]["render_endpoint"] == (
        f"/api/orders/{order_id}/qr/render"
    )
    assert order_response.json()["qr_intent"] == metadata
    serialized = str(metadata).lower()
    for forbidden in (
        "adapter_profile_id",
        "provider",
        "payload",
        "secret",
        "token",
        "http://",
        "https://",
    ):
        assert forbidden not in serialized
    session = SessionLocal()
    try:
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == 1
    finally:
        session.close()


def test_legacy_and_off_mode_orders_return_same_404_without_fabrication(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    legacy = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": ctx["product"]["id"], "price": 1, "quantity": 1}],
            "payment_method": "transfer",
            "operation_id": uuid.uuid4().hex,
        },
        headers=auth(ctx["token"]),
    )
    assert legacy.status_code == 200
    assert "qr_intent" not in legacy.json()
    order_id = legacy.json()["order_id"]

    for suffix in ("qr", "qr/render"):
        missing_intent = client.get(
            f"/api/orders/{order_id}/{suffix}", headers=auth(ctx["token"])
        )
        unknown = client.get(
            f"/api/orders/999999997/{suffix}", headers=auth(ctx["token"])
        )
        assert missing_intent.status_code == unknown.status_code == 404
        assert missing_intent.json() == unknown.json()

    session = SessionLocal()
    try:
        assert session.query(models.QrPaymentIntent).filter_by(order_id=order_id).count() == 0
        assert session.query(models.SystemLog).filter_by(
            shop_id=ctx["shop_id"],
            action=qr_sales_service.AUDIT_ACTION_INTENT_ISSUED,
        ).count() == 0
    finally:
        session.close()
