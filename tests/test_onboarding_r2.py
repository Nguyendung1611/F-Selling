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


DEFAULT_CATEGORY_NAME = "Chưa phân loại"


def test_seller_hosts_r2_assets_and_accessible_shell():
    html = open("static/seller.html", encoding="utf-8").read()
    assert 'id="firstRunShell"' in html
    assert 'id="firstRunResumeCard"' in html
    assert 'id="firstRunShopForm"' in html
    assert 'id="firstRunProductForm"' in html
    assert "/css/onboarding-r2.css?v=20260828-r2" in html
    assert "/js/onboarding-r2.js?v=20260828-r2" in html
    assert html.index("/js/onboarding-r2.js") < html.index("/js/seller.js")


def test_seller_r2_shell_keeps_each_task_and_resume_action_focused():
    html = open("static/seller.html", encoding="utf-8").read()
    assert 'aria-live="polite"' in html
    assert 'data-i18n="seller.first_run.step_product.title"' in html
    assert 'id="firstRunProductStock"' in html
    assert 'id="firstRunProductStock" name="stock" type="number"' in html
    assert 'id="firstRunProductStock" name="stock" type="number" value=' not in html
    assert html.count('id="firstRunResumeAction"') == 1


def test_r2_uses_new_keys_without_restoring_r1_checklist():
    locale = open("static/js/locales/seller.js", encoding="utf-8").read()
    assert "seller.first_run.step_shop.title" in locale
    assert "seller.onboarding." not in locale


def _post_product_without_category(client, ctx, name, stock=7):
    return client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={"name": name, "price": 15000, "stock": stock},
        headers=auth(ctx["token"]),
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


def test_first_product_without_category_creates_and_reuses_default(client, minimum_shop):
    first = _post_product_without_category(client, minimum_shop, "Mì gói", stock=7)
    second = _post_product_without_category(client, minimum_shop, "Nước suối", stock=3)

    assert first.status_code == second.status_code == 200
    assert first.json()["category_id"] == second.json()["category_id"]
    with SessionLocal() as db:
        categories = db.query(models.Category).filter_by(
            shop_id=minimum_shop["shop_id"], name=DEFAULT_CATEGORY_NAME
        ).all()
        assert len(categories) == 1


def test_failed_first_product_rolls_back_lazy_default_category(client, minimum_shop):
    explicit_id = create_category(
        client, minimum_shop["token"], minimum_shop["shop_id"], "Đồ uống"
    )
    create_product(
        client,
        minimum_shop["token"],
        minimum_shop["shop_id"],
        "Trùng tên",
        10000,
        2,
        explicit_id,
    )

    failed = _post_product_without_category(client, minimum_shop, "Trùng tên")

    assert failed.status_code == 400
    with SessionLocal() as db:
        assert (
            db.query(models.Category)
            .filter_by(
                shop_id=minimum_shop["shop_id"], name=DEFAULT_CATEGORY_NAME
            )
            .count()
            == 0
        )


def test_first_product_reactivates_existing_inactive_default_category(
    client, minimum_shop
):
    category_id = create_category(
        client,
        minimum_shop["token"],
        minimum_shop["shop_id"],
        DEFAULT_CATEGORY_NAME,
    )
    deactivated = client.put(
        f"/api/categories/{category_id}",
        json={"name": DEFAULT_CATEGORY_NAME, "is_active": False},
        headers=auth(minimum_shop["token"]),
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False

    created = _post_product_without_category(client, minimum_shop, "Gạo", stock=5)

    assert created.status_code == 200, created.text
    assert created.json()["category_id"] == category_id
    with SessionLocal() as db:
        category = db.query(models.Category).filter_by(id=category_id).one()
        assert category.is_active is True
