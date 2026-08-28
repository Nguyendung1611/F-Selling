import uuid

import pytest

from fselling import models
from fselling.core.database import SessionLocal

from conftest import (
    SHOP_PAYLOAD,
    auth,
    create_category,
    create_product,
    new_seller,
    seller_with_shop,
)


@pytest.fixture
def minimum_shop(client):
    username, token = new_seller(client)
    response = client.post(
        "/api/shops",
        json={"name": "Tạp hóa An", "phone": "0774867057"},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return {
        "username": username,
        "token": token,
        "shop_id": response.json()["id"],
    }


@pytest.fixture
def minimum_shop_with_product(client, minimum_shop):
    category_id = create_category(
        client,
        minimum_shop["token"],
        minimum_shop["shop_id"],
        "Đồ ăn nhanh",
    )
    product = create_product(
        client,
        minimum_shop["token"],
        minimum_shop["shop_id"],
        "Mì gói",
        15000,
        7,
        category_id,
    )
    return {
        **minimum_shop,
        "product_id": product["id"],
        "product_name": product["name"],
        "opening_stock": 7,
    }


def test_owner_can_create_minimum_real_shop(client):
    _, token = new_seller(client)
    response = client.post(
        "/api/shops",
        json={"name": "Tạp hóa An", "phone": "0774867057"},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Tạp hóa An"
    assert body["phone"] == "0774867057"
    assert body["bank_code"] == ""
    assert body["bank_account_no"] == ""
    assert body["bank_account_name"] == ""


def test_full_shop_payload_remains_compatible(client):
    _, token = new_seller(client)
    response = client.post("/api/shops", json=SHOP_PAYLOAD, headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.json()["bank_code"] == SHOP_PAYLOAD["bank_code"]


def test_partial_bank_group_is_rejected(client):
    _, token = new_seller(client)
    response = client.post(
        "/api/shops",
        json={
            "name": "Tạp hóa An",
            "phone": "0774867057",
            "bank_code": "VCB",
        },
        headers=auth(token),
    )
    assert response.status_code == 400
    assert "ngân hàng" in str(response.json()["detail"]).lower()


def test_transfer_without_bank_fails_before_order_or_stock_mutation(
    client, minimum_shop_with_product
):
    ctx = minimum_shop_with_product
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product_name"], "price": 1, "quantity": 1}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "QR_BANK_ACCOUNT_NOT_CONFIGURED"
    with SessionLocal() as db:
        product = db.query(models.Product).filter_by(id=ctx["product_id"]).one()
        assert product.stock == ctx["opening_stock"]
        assert db.query(models.Order).filter_by(shop_id=ctx["shop_id"]).count() == 0


def test_cash_without_bank_still_creates_order_without_qr(client, minimum_shop_with_product):
    ctx = minimum_shop_with_product
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product_name"], "price": 1, "quantity": 1}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["qr_url"] is None


def test_debt_without_bank_still_creates_order_without_qr(client, minimum_shop_with_product):
    ctx = minimum_shop_with_product
    customer = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": "Cô Lan", "phone": "0900000001"},
        headers=auth(ctx["token"]),
    )
    assert customer.status_code == 200, customer.text
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product_name"], "price": 1, "quantity": 1}],
            "payment_method": "debt",
            "customer_id": customer.json()["id"],
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DEBT"
    assert response.json()["qr_url"] is None


def test_idempotent_v0_transfer_with_cleared_bank_returns_no_qr_without_duplicate(
    client,
):
    ctx = seller_with_shop(client)
    operation_id = uuid.uuid4().hex
    payload = {
        "items": [
            {
                "product_name": ctx["product"]["name"],
                "price": 1,
                "quantity": 1,
            }
        ],
        "payment_method": "transfer",
        "operation_id": operation_id,
    }
    first = client.post(
        f"/api/orders/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    assert first.status_code == 200, first.text
    assert first.json()["qr_url"] is not None
    assert "qr_intent" not in first.json()

    cleared = client.put(
        f"/api/shops/{ctx['shop_id']}",
        json={
            **SHOP_PAYLOAD,
            "bank_code": "",
            "bank_account_no": "",
            "bank_account_name": "",
        },
        headers=auth(ctx["token"]),
    )
    assert cleared.status_code == 200, cleared.text
    assert (
        cleared.json()["bank_code"],
        cleared.json()["bank_account_no"],
        cleared.json()["bank_account_name"],
    ) == ("", "", "")

    retry = client.post(
        f"/api/orders/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["order_id"] == first.json()["order_id"]
    assert retry.json()["qr_url"] is None
    with SessionLocal() as db:
        assert db.query(models.Order).filter_by(operation_id=operation_id).count() == 1
