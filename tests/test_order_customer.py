"""C2c: gắn khách vào đơn ở POS + lịch sử mua của khách."""
from conftest import auth, new_seller, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _tao_khach(client, token, shop_id, name="Khach A", phone="0900001"):
    return client.post(
        f"/api/customers/{shop_id}", json={"name": name, "phone": phone}, headers=auth(token)
    ).json()["id"]


def _ban(
    client,
    token,
    shop_id,
    product_name,
    qty=1,
    customer_id=None,
    payment_method="transfer",
):
    body = {
        "items": [{"product_name": product_name, "price": 1, "quantity": qty}],
        "payment_method": payment_method,
    }
    if customer_id is not None:
        body["customer_id"] = customer_id
    return client.post(f"/api/orders/{shop_id}", json=body, headers=auth(token))


def _customer_id_cua_don(order_id):
    session = SessionLocal()
    try:
        return session.query(models.Order).filter(models.Order.id == order_id).first().customer_id
    finally:
        session.close()


# ---------- Gắn khách khi bán ----------
def test_ban_khong_gan_khach_van_duoc(client):
    ctx = seller_with_shop(client)
    res = _ban(client, ctx["token"], ctx["shop_id"], ctx["product"]["name"])
    assert res.status_code == 200
    assert _customer_id_cua_don(res.json()["order_id"]) is None


def test_ban_gan_khach(client):
    ctx = seller_with_shop(client)
    kh_id = _tao_khach(client, ctx["token"], ctx["shop_id"])
    res = _ban(client, ctx["token"], ctx["shop_id"], ctx["product"]["name"], customer_id=kh_id)
    assert res.status_code == 200
    assert _customer_id_cua_don(res.json()["order_id"]) == kh_id


def test_khong_gan_duoc_khach_cua_shop_khac(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    kh_b = _tao_khach(client, b["token"], b["shop_id"], phone="0900B")

    # bán ở shop A nhưng gắn khách của shop B -> chặn
    res = _ban(client, a["token"], a["shop_id"], a["product"]["name"], customer_id=kh_b)
    assert res.status_code == 404


def test_gan_khach_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    res = _ban(client, ctx["token"], ctx["shop_id"], ctx["product"]["name"], customer_id=999999)
    assert res.status_code == 404


def test_nhan_vien_gan_khach_khi_ban(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    kh_id = _tao_khach(client, staff_token, ctx["shop_id"], phone="0900555")
    res = _ban(client, staff_token, ctx["shop_id"], ctx["product"]["name"], customer_id=kh_id)
    assert res.status_code == 200
    assert _customer_id_cua_don(res.json()["order_id"]) == kh_id


def test_chi_tiet_don_hien_thong_tin_khach(client):
    ctx = seller_with_shop(client)
    kh_id = _tao_khach(client, ctx["token"], ctx["shop_id"], name="Le Thi B", phone="0900333")
    order_id = _ban(
        client, ctx["token"], ctx["shop_id"], ctx["product"]["name"], customer_id=kh_id
    ).json()["order_id"]

    detail = client.get(f"/api/orders/{order_id}/detail", headers=auth(ctx["token"])).json()
    assert "customer" in detail
    assert detail["customer"]["name"] == "Le Thi B"
    assert detail["customer"]["phone"] == "0900333"


def test_chi_tiet_don_khach_vang_lai_customer_null(client):
    ctx = seller_with_shop(client)
    order_id = _ban(client, ctx["token"], ctx["shop_id"], ctx["product"]["name"]).json()["order_id"]
    detail = client.get(f"/api/orders/{order_id}/detail", headers=auth(ctx["token"])).json()
    assert detail["customer"] is None


# ---------- Lịch sử mua ----------
def test_lich_su_mua_cua_khach(client):
    ctx = seller_with_shop(client)  # SP giá 100000
    kh_id = _tao_khach(client, ctx["token"], ctx["shop_id"])

    # 2 đơn: 1 thanh toán, 1 chưa
    o1 = _ban(
        client,
        ctx["token"],
        ctx["shop_id"],
        ctx["product"]["name"],
        qty=2,
        customer_id=kh_id,
        payment_method="cash",
    ).json()["order_id"]
    client.post(f"/api/orders/{o1}/pay", headers=auth(ctx["token"]))
    _ban(client, ctx["token"], ctx["shop_id"], ctx["product"]["name"], qty=1, customer_id=kh_id)

    res = client.get(
        f"/api/customers/member/{kh_id}/history", headers=auth(ctx["token"])
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"customer", "total_paid", "order_count", "orders"}
    assert body["customer"]["id"] == kh_id
    assert body["order_count"] == 2
    # chỉ đơn đã thanh toán mới tính vào tổng đã chi
    assert body["total_paid"] == 200000


def test_lich_su_khach_moi_chua_mua(client):
    ctx = seller_with_shop(client)
    kh_id = _tao_khach(client, ctx["token"], ctx["shop_id"])
    body = client.get(
        f"/api/customers/member/{kh_id}/history", headers=auth(ctx["token"])
    ).json()
    assert body["order_count"] == 0
    assert body["total_paid"] == 0
    assert body["orders"] == []


def test_nhan_vien_xem_lich_su_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    kh_id = _tao_khach(client, staff_token, ctx["shop_id"], phone="0900777")
    res = client.get(f"/api/customers/member/{kh_id}/history", headers=auth(staff_token))
    assert res.status_code == 200


def test_seller_khac_khong_xem_lich_su_khach_shop_nguoi_ta(client):
    ctx = seller_with_shop(client)
    kh_id = _tao_khach(client, ctx["token"], ctx["shop_id"])
    _, token_b = new_seller(client)
    res = client.get(f"/api/customers/member/{kh_id}/history", headers=auth(token_b))
    assert res.status_code == 403


def test_lich_su_khach_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    res = client.get("/api/customers/member/999999/history", headers=auth(ctx["token"]))
    assert res.status_code == 404


def test_huy_don_van_giu_lien_ket_khach(client):
    """Đơn của khách bị hủy vẫn nằm trong lịch sử, chỉ không tính vào tổng đã chi."""
    ctx = seller_with_shop(client)
    kh_id = _tao_khach(client, ctx["token"], ctx["shop_id"])
    order_id = _ban(
        client, ctx["token"], ctx["shop_id"], ctx["product"]["name"], customer_id=kh_id
    ).json()["order_id"]
    client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))

    body = client.get(
        f"/api/customers/member/{kh_id}/history", headers=auth(ctx["token"])
    ).json()
    assert body["order_count"] == 1
    assert body["total_paid"] == 0
    assert body["orders"][0]["status"] == "CANCELLED"
