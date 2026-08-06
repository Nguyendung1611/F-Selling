"""A1a: migration thêm `order_items.product_id` + backfill dữ liệu cũ.

Commit này CHỈ thay đổi schema và điền dữ liệu lịch sử.
Không thay đổi logic tạo đơn (việc ghi product_id cho đơn mới thuộc A1b).
"""
from sqlalchemy import text

from conftest import auth, create_category, create_product, create_shop, new_seller, seller_with_shop

from fselling import models
from fselling.core.bootstrap import backfill_order_item_product_id
from fselling.core.database import SessionLocal


def _cot_order_items(session):
    return {row[1] for row in session.execute(text("PRAGMA table_info(order_items)"))}


def _them_dong_don_hang_cu(session, order_id, product_name, quantity=1, price=1000.0):
    """Tạo dòng order_item kiểu cũ: chỉ có tên sản phẩm, product_id để trống."""
    item = models.OrderItem(
        order_id=order_id, product_name=product_name, price=price, quantity=quantity
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    assert item.product_id is None
    return item


def _tao_don_trong(session, shop_id):
    order = models.Order(shop_id=shop_id, total_amount=0, discount_amount=0)
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


# --- Schema ---
def test_cot_product_id_ton_tai(client, db):
    assert "product_id" in _cot_order_items(db)


def test_index_product_id_ton_tai(client, db):
    indexes = {row[1] for row in db.execute(text("PRAGMA index_list(order_items)"))}
    assert "ix_order_items_product_id" in indexes


def test_cac_cot_cu_van_giu_nguyen(client, db):
    cols = _cot_order_items(db)
    assert {"id", "order_id", "product_name", "price", "quantity"} <= cols


# --- Backfill ---
def test_backfill_khop_theo_ten_trong_cung_shop(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        order = _tao_don_trong(session, ctx["shop_id"])
        item = _them_dong_don_hang_cu(session, order.id, ctx["product"]["name"])

        filled, unmatched = backfill_order_item_product_id(session)
        assert filled >= 1

        session.refresh(item)
        assert item.product_id == ctx["product"]["id"]
    finally:
        session.close()


def test_khong_khop_nham_san_pham_cung_ten_o_shop_khac(client):
    """Hai shop có thể có sản phẩm trùng tên - backfill phải khớp đúng shop của đơn."""
    ten_chung = "San pham trung ten"

    _, token_a = new_seller(client)
    shop_a = create_shop(client, token_a)
    cat_a = create_category(client, token_a, shop_a)
    prod_a = create_product(client, token_a, shop_a, ten_chung, 50000, 5, cat_a)

    _, token_b = new_seller(client)
    shop_b = create_shop(client, token_b)
    cat_b = create_category(client, token_b, shop_b)
    prod_b = create_product(client, token_b, shop_b, ten_chung, 70000, 5, cat_b)

    assert prod_a["id"] != prod_b["id"]

    session = SessionLocal()
    try:
        order_b = _tao_don_trong(session, shop_b)
        item_b = _them_dong_don_hang_cu(session, order_b.id, ten_chung)

        backfill_order_item_product_id(session)

        session.refresh(item_b)
        assert item_b.product_id == prod_b["id"], "Phải khớp sản phẩm của shop B, không phải shop A"
    finally:
        session.close()


def test_giu_nguyen_null_khi_san_pham_khong_con_ton_tai(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        order = _tao_don_trong(session, ctx["shop_id"])
        item = _them_dong_don_hang_cu(session, order.id, "San pham da bi xoa vinh vien")

        filled, unmatched = backfill_order_item_product_id(session)
        assert unmatched >= 1

        session.refresh(item)
        assert item.product_id is None
    finally:
        session.close()


def test_khong_ghi_de_dong_da_co_product_id(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        order = _tao_don_trong(session, ctx["shop_id"])
        item = models.OrderItem(
            order_id=order.id,
            product_id=999999,  # giá trị cố ý sai, backfill không được đụng vào
            product_name=ctx["product"]["name"],
            price=1000.0,
            quantity=1,
        )
        session.add(item)
        session.commit()

        backfill_order_item_product_id(session)

        session.refresh(item)
        assert item.product_id == 999999
    finally:
        session.close()


def test_backfill_chay_lai_khong_doi_ket_qua(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        order = _tao_don_trong(session, ctx["shop_id"])
        _them_dong_don_hang_cu(session, order.id, ctx["product"]["name"])
        _them_dong_don_hang_cu(session, order.id, "San pham khong ton tai")

        backfill_order_item_product_id(session)
        con_thieu_lan_1 = session.execute(
            text("SELECT COUNT(*) FROM order_items WHERE product_id IS NULL")
        ).scalar()

        filled_2, unmatched_2 = backfill_order_item_product_id(session)
        con_thieu_lan_2 = session.execute(
            text("SELECT COUNT(*) FROM order_items WHERE product_id IS NULL")
        ).scalar()

        assert con_thieu_lan_1 == con_thieu_lan_2
        assert filled_2 == 0
    finally:
        session.close()


def test_backfill_khong_lam_gi_khi_khong_con_dong_thieu(client):
    session = SessionLocal()
    try:
        session.execute(text("UPDATE order_items SET product_id = -1 WHERE product_id IS NULL"))
        session.commit()

        assert backfill_order_item_product_id(session) == (0, 0)
    finally:
        session.close()


# --- Hành vi hiện tại KHÔNG được đổi ở commit này ---
def test_tao_don_van_hoat_dong_binh_thuong(client):
    """A1a chưa ghi product_id cho đơn mới - đó là việc của A1b."""
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
    assert set(body.keys()) == {
        "order_id", "subtotal", "discount", "total", "qr_url", "status",
        "loyalty_points_redeemed", "loyalty_discount",
        "loyalty_points_earned", "loyalty_balance",
    }
    assert body["total"] == 200000  # giá vẫn lấy từ DB
