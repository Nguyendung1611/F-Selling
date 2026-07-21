"""A1b: đơn hàng mới luôn ghi kèm `order_items.product_id`.

Commit này chỉ bổ sung dữ liệu khi tạo đơn. Không đổi contract API,
không đổi cách tính tiền, không đổi cách trừ tồn kho.
"""
from sqlalchemy import text

from conftest import (
    auth,
    create_category,
    create_product,
    create_shop,
    new_seller,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal


def _items_cua_don(session, order_id):
    return (
        session.query(models.OrderItem)
        .filter(models.OrderItem.order_id == order_id)
        .order_by(models.OrderItem.id)
        .all()
    )


def _tao_don(client, ctx, items, voucher_code=None):
    body = {"items": items, "payment_method": "transfer"}
    if voucher_code:
        body["voucher_code"] = voucher_code
    res = client.post(
        f"/api/orders/{ctx['shop_id']}", json=body, headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_don_mot_san_pham_co_product_id(client):
    ctx = seller_with_shop(client)
    order = _tao_don(
        client, ctx, [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 2}]
    )

    session = SessionLocal()
    try:
        items = _items_cua_don(session, order["order_id"])
        assert len(items) == 1
        assert items[0].product_id == ctx["product"]["id"]
        assert items[0].product_name == ctx["product"]["name"]
        assert items[0].quantity == 2
    finally:
        session.close()


def test_don_nhieu_san_pham_moi_dong_dung_product_id(client):
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    p1 = create_product(client, token, shop_id, "Ca phe sua", 25000, 10, cat_id)
    p2 = create_product(client, token, shop_id, "Banh mi thit", 15000, 10, cat_id)
    ctx = {"shop_id": shop_id, "token": token}

    order = _tao_don(
        client,
        ctx,
        [
            {"product_name": "Ca phe sua", "price": 1, "quantity": 2},
            {"product_name": "Banh mi thit", "price": 1, "quantity": 3},
        ],
    )

    session = SessionLocal()
    try:
        items = _items_cua_don(session, order["order_id"])
        theo_ten = {i.product_name: i for i in items}
        assert len(items) == 2
        assert theo_ten["Ca phe sua"].product_id == p1["id"]
        assert theo_ten["Banh mi thit"].product_id == p2["id"]
        # Giá vẫn lấy từ DB, không phải giá client gửi
        assert theo_ten["Ca phe sua"].price == 25000
        assert theo_ten["Banh mi thit"].price == 15000
    finally:
        session.close()


def test_gop_dong_trung_san_pham_van_dung_product_id(client):
    ctx = seller_with_shop(client)
    order = _tao_don(
        client,
        ctx,
        [
            {"product_name": ctx["product"]["name"], "price": 1, "quantity": 2},
            {"product_name": ctx["product"]["name"], "price": 1, "quantity": 3},
        ],
    )

    session = SessionLocal()
    try:
        items = _items_cua_don(session, order["order_id"])
        assert len(items) == 1, "Cùng sản phẩm phải được gộp thành một dòng"
        assert items[0].product_id == ctx["product"]["id"]
        assert items[0].quantity == 5
    finally:
        session.close()


def test_product_id_tro_dung_san_pham_da_dung_de_tinh_gia(client):
    """Hai shop có sản phẩm trùng tên: product_id phải là sản phẩm của shop tạo đơn."""
    ten_chung = "Tra da"

    _, token_a = new_seller(client)
    shop_a = create_shop(client, token_a)
    cat_a = create_category(client, token_a, shop_a)
    prod_a = create_product(client, token_a, shop_a, ten_chung, 5000, 10, cat_a)

    _, token_b = new_seller(client)
    shop_b = create_shop(client, token_b)
    cat_b = create_category(client, token_b, shop_b)
    prod_b = create_product(client, token_b, shop_b, ten_chung, 9000, 10, cat_b)

    ctx_b = {"shop_id": shop_b, "token": token_b}
    order = _tao_don(client, ctx_b, [{"product_name": ten_chung, "price": 1, "quantity": 1}])

    session = SessionLocal()
    try:
        item = _items_cua_don(session, order["order_id"])[0]
        assert item.product_id == prod_b["id"]
        assert item.product_id != prod_a["id"]
        assert item.price == 9000  # giá của shop B
    finally:
        session.close()


def test_don_moi_khong_bao_gio_con_product_id_null(client):
    ctx = seller_with_shop(client)
    order = _tao_don(
        client, ctx, [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]
    )

    session = SessionLocal()
    try:
        con_null = session.execute(
            text(
                "SELECT COUNT(*) FROM order_items "
                "WHERE order_id = :oid AND product_id IS NULL"
            ),
            {"oid": order["order_id"]},
        ).scalar()
        assert con_null == 0
    finally:
        session.close()


def test_product_id_khop_voi_san_pham_bi_tru_ton_kho(client):
    """product_id phải trỏ đúng sản phẩm mà tồn kho vừa bị trừ."""
    ctx = seller_with_shop(client)
    order = _tao_don(
        client, ctx, [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 4}]
    )

    session = SessionLocal()
    try:
        item = _items_cua_don(session, order["order_id"])[0]
        prod = session.query(models.Product).filter(models.Product.id == item.product_id).first()
        assert prod is not None
        assert prod.stock == 10 - 4
    finally:
        session.close()


# --- Contract KHÔNG được đổi ở commit này ---
def test_contract_tao_don_giu_nguyen(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 2}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"order_id", "subtotal", "discount", "total", "qr_url"}
    assert body["subtotal"] == 200000
    assert body["total"] == 200000
    assert f"ORDER{body['order_id']}" in body["qr_url"]


def test_voucher_van_hoat_dong_nhu_cu(client):
    ctx = seller_with_shop(client)
    client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "A1B10K", "discount_type": "flat", "discount_value": 10000},
        headers=auth(ctx["token"]),
    )
    order = _tao_don(
        client,
        ctx,
        [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
        voucher_code="A1B10K",
    )
    assert order["discount"] == 10000
    assert order["total"] == 90000
