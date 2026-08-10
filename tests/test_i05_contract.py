"""I05 exact-money contracts across order, QR, webhook and reports."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from conftest import _unique, auth, create_product, seller_with_shop
from fselling.routers import webhooks


SECRET = "i05-contract-webhook-secret"
LARGE_DOCUMENT_VND = 6_000_000_000_000_000


def _create_large_order(client, ctx, product: dict) -> dict:
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": product["id"],
                    "price": str(LARGE_DOCUMENT_VND),
                    "quantity": 1,
                }
            ],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _pay_by_webhook(client, monkeypatch, order: dict) -> None:
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    response = client.post(
        "/api/orders/webhook",
        json={
            "content": f"ORDER{order['order_id']}",
            "transferAmount": str(order["total"]),
            "transferType": "in",
            "id": f"I05-{order['order_id']}",
        },
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 200, response.text
    assert response.json()["order_ids"] == [order["order_id"]]


def test_qr_order_webhook_share_one_exact_integer(client, monkeypatch):
    ctx = seller_with_shop(client)
    product = create_product(
        client,
        ctx["token"],
        ctx["shop_id"],
        _unique("I05Exact"),
        str(LARGE_DOCUMENT_VND),
        2,
        ctx["category_id"],
    )
    order = _create_large_order(client, ctx, product)

    qr_amount = parse_qs(urlparse(order["qr_url"]).query)["amount"][0]
    assert order["total"] == LARGE_DOCUMENT_VND
    assert qr_amount == str(order["total"])

    _pay_by_webhook(client, monkeypatch, order)
    detail = client.get(
        f"/api/orders/{order['order_id']}", headers=auth(ctx["token"])
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["total_amount"] == LARGE_DOCUMENT_VND
    assert detail.json()["bank_paid_amount"] == LARGE_DOCUMENT_VND


def test_report_v2_strings_only_unsafe_aggregate(client, monkeypatch):
    ctx = seller_with_shop(client)
    product = create_product(
        client,
        ctx["token"],
        ctx["shop_id"],
        _unique("I05Aggregate"),
        str(LARGE_DOCUMENT_VND),
        2,
        ctx["category_id"],
    )
    first = _create_large_order(client, ctx, product)
    second = _create_large_order(client, ctx, product)
    _pay_by_webhook(client, monkeypatch, first)
    _pay_by_webhook(client, monkeypatch, second)

    v1 = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}?contract_version=1",
        headers=auth(ctx["token"]),
    )
    v2 = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}?contract_version=2",
        headers=auth(ctx["token"]),
    )
    assert v1.status_code == 200, v1.text
    assert v2.status_code == 200, v2.text
    expected = LARGE_DOCUMENT_VND * 2
    assert v1.json()["total_revenue"] == expected
    assert v2.json()["total_revenue"] == str(expected)
    assert v2.json()["contract_version"] == 2
    assert all(
        isinstance(order["total"], int) for order in v2.json()["orders"]
    )


def test_fractional_vnd_is_rejected_at_json_and_form_boundaries(client):
    ctx = seller_with_shop(client)
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "price": "100000.5",
                    "quantity": 1,
                }
            ]
        },
        headers=auth(ctx["token"]),
    )
    assert order.status_code == 422, order.text

    product = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("Fractional"),
            "price": "1000.5",
            "stock": 1,
            "category_id": ctx["category_id"],
        },
        headers=auth(ctx["token"]),
    )
    assert product.status_code == 422, product.text
