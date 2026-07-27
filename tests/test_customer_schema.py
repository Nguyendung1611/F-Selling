"""C2a: schema khách hàng (bảng customers + cột orders.customer_id).

Commit này CHỈ thêm schema và quan hệ ORM. Chưa có endpoint quản lý khách,
chưa gắn khách vào đơn - những phần đó ở C2b/C2c/C2d.
"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from conftest import auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _bang_ton_tai(session, ten):
    row = session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": ten}
    ).first()
    return row is not None


# ---------- Schema ----------
def test_bang_customers_ton_tai(client, db):
    assert _bang_ton_tai(db, "customers")


def test_cot_orders_customer_id_ton_tai(client, db):
    cols = {r[1] for r in db.execute(text("PRAGMA table_info(orders)"))}
    assert "customer_id" in cols


def test_customers_co_du_cot(client, db):
    cols = {r[1] for r in db.execute(text("PRAGMA table_info(customers)"))}
    assert {"id", "shop_id", "name", "phone", "address", "note", "created_at"} <= cols


# ---------- Quan hệ + ràng buộc ----------
def test_tao_khach_va_gan_vao_don(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        kh = models.Customer(
            shop_id=ctx["shop_id"], name="Nguyen Van A", phone="0900000001",
            address="123 Test", note="khach quen",
        )
        session.add(kh)
        session.commit()
        kh_id = kh.id

        order = models.Order(shop_id=ctx["shop_id"], total_amount=50000, customer_id=kh_id)
        session.add(order)
        session.commit()
        order_id = order.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        order = session.query(models.Order).filter(models.Order.id == order_id).first()
        assert order.customer is not None
        assert order.customer.name == "Nguyen Van A"
        assert order.customer.phone == "0900000001"
    finally:
        session.close()


def test_sdt_duy_nhat_trong_mot_shop(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        session.add(models.Customer(shop_id=ctx["shop_id"], name="A", phone="0911111111"))
        session.commit()
        session.add(models.Customer(shop_id=ctx["shop_id"], name="B", phone="0911111111"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_sdt_trung_o_shop_khac_van_duoc(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    session = SessionLocal()
    try:
        session.add(models.Customer(shop_id=a["shop_id"], name="A", phone="0922222222"))
        session.add(models.Customer(shop_id=b["shop_id"], name="B", phone="0922222222"))
        session.commit()  # không được ném lỗi
        dem = session.query(models.Customer).filter(
            models.Customer.phone == "0922222222"
        ).count()
        assert dem == 2
    finally:
        session.close()


# ---------- Hành vi cũ KHÔNG đổi ----------
def test_don_moi_van_khong_can_khach(client):
    """Đơn tạo qua API vẫn hoạt động, customer_id để trống (khách vãng lai)."""
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200

    session = SessionLocal()
    try:
        order = session.query(models.Order).filter(
            models.Order.id == res.json()["order_id"]
        ).first()
        assert order.customer_id is None
    finally:
        session.close()
