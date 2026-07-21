"""Nhóm B: GET /api/orders/{order_id}/detail - xem chi tiết đơn kèm từng dòng hàng."""
from conftest import (
    admin_token,
    auth,
    create_category,
    create_product,
    create_shop,
    new_seller,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal


def _chi_tiet(client, token, order_id):
    return client.get(f"/api/orders/{order_id}/detail", headers=auth(token))


def test_chi_tiet_don_mot_san_pham(client):
    ctx = seller_with_shop(client)  # SP giá 100000, tồn 10
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 2}]},
        headers=auth(ctx["token"]),
    ).json()

    body = _chi_tiet(client, ctx["token"], order["order_id"]).json()

    assert set(body.keys()) == {
        "id",
        "shop_id",
        "shop_name",
        "status",
        "created_at",
        "payment_method",
        "voucher_code",
        "discount_amount",
        "total_amount",
        "subtotal",
        "items",
    }
    assert len(body["items"]) == 1
    dong = body["items"][0]
    assert set(dong.keys()) == {"product_id", "product_name", "price", "quantity", "line_total"}
    assert dong["product_id"] == ctx["product"]["id"]
    assert dong["price"] == 100000, "Giá lấy từ DB, không phải giá client gửi"
    assert dong["quantity"] == 2
    assert dong["line_total"] == 200000
    assert body["subtotal"] == 200000
    assert body["total_amount"] == 200000


def test_chi_tiet_don_nhieu_san_pham(client):
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    create_product(client, token, shop_id, "Ca phe", 25000, 10, cat_id)
    create_product(client, token, shop_id, "Banh mi", 15000, 10, cat_id)

    order = client.post(
        f"/api/orders/{shop_id}",
        json={
            "items": [
                {"product_name": "Ca phe", "price": 1, "quantity": 2},
                {"product_name": "Banh mi", "price": 1, "quantity": 3},
            ]
        },
        headers=auth(token),
    ).json()

    body = _chi_tiet(client, token, order["order_id"]).json()
    theo_ten = {i["product_name"]: i for i in body["items"]}

    assert len(body["items"]) == 2
    assert theo_ten["Ca phe"]["line_total"] == 50000
    assert theo_ten["Banh mi"]["line_total"] == 45000
    assert body["subtotal"] == 95000


def test_chi_tiet_hien_thi_giam_gia_va_ma_voucher(client):
    ctx = seller_with_shop(client)
    client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "CTIET10K", "discount_type": "flat", "discount_value": 10000},
        headers=auth(ctx["token"]),
    )
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
            "voucher_code": "CTIET10K",
        },
        headers=auth(ctx["token"]),
    ).json()

    body = _chi_tiet(client, ctx["token"], order["order_id"]).json()
    assert body["voucher_code"] == "CTIET10K"
    assert body["discount_amount"] == 10000
    assert body["subtotal"] == 100000
    assert body["total_amount"] == 90000


def test_giu_gia_da_ban_du_san_pham_doi_gia_sau_do(client):
    """order_items là ảnh chụp lúc bán - đổi giá sản phẩm không làm sai đơn cũ."""
    ctx = seller_with_shop(client)
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()

    session = SessionLocal()
    try:
        prod = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product"]["id"])
            .first()
        )
        prod.price = 999999
        session.commit()
    finally:
        session.close()

    body = _chi_tiet(client, ctx["token"], order["order_id"]).json()
    assert body["items"][0]["price"] == 100000, "Đơn cũ phải giữ giá tại thời điểm bán"


def test_trang_thai_don_hien_trong_chi_tiet(client):
    ctx = seller_with_shop(client)
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()

    assert _chi_tiet(client, ctx["token"], order["order_id"]).json()["status"] == "PENDING"

    client.post(f"/api/orders/{order['order_id']}/cancel", headers=auth(ctx["token"]))
    assert _chi_tiet(client, ctx["token"], order["order_id"]).json()["status"] == "CANCELLED"


# ---------- Phân quyền ----------
def test_seller_khac_khong_xem_duoc_chi_tiet(client):
    ctx = seller_with_shop(client)
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()

    _, token_b = new_seller(client)
    assert _chi_tiet(client, token_b, order["order_id"]).status_code == 403


def test_chua_dang_nhap_khong_xem_duoc(client):
    ctx = seller_with_shop(client)
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()
    assert client.get(f"/api/orders/{order['order_id']}/detail").status_code == 401


def test_admin_xem_duoc_chi_tiet_don_cua_seller(client):
    ctx = seller_with_shop(client)
    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()
    assert _chi_tiet(client, admin_token(client), order["order_id"]).status_code == 200


def test_don_khong_ton_tai_tra_404(client):
    _, token = new_seller(client)
    assert _chi_tiet(client, token, 999999).status_code == 404
