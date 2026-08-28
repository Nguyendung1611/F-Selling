import pytest

from conftest import SHOP_PAYLOAD, auth, new_seller


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
