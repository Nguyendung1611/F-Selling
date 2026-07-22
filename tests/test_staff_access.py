"""C1c: quyền của nhân viên (STAFF).

Nhân viên VẬN HÀNH được shop được gán (bán hàng, quản lý SP/danh mục/voucher/
kho, xem báo cáo) nhưng KHÔNG làm quản trị (sửa/xóa shop, quản lý nhân viên).
Nhân viên của shop A không đụng được shop B.
"""
from conftest import (
    SHOP_PAYLOAD,
    auth,
    create_category,
    create_shop,
    new_seller,
    new_staff,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal


def _ton_kho(pid):
    session = SessionLocal()
    try:
        return session.query(models.Product).filter(models.Product.id == pid).first().stock
    finally:
        session.close()


# ================= STAFF ĐƯỢC VẬN HÀNH =================
def test_staff_thay_shop_duoc_gan(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    res = client.get("/api/shops", headers=auth(staff_token))
    assert res.status_code == 200
    shops = res.json()
    assert len(shops) == 1
    assert shops[0]["id"] == ctx["shop_id"]


def test_staff_ban_hang_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 2}]},
        headers=auth(staff_token),
    )
    assert res.status_code == 200
    assert res.json()["total"] == 200000  # giá vẫn từ DB
    assert _ton_kho(ctx["product"]["id"]) == 8


def test_staff_huy_don_va_xac_nhan_thanh_toan_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(staff_token),
    ).json()["order_id"]

    assert client.get(f"/api/orders/{order_id}", headers=auth(staff_token)).status_code == 200
    assert (
        client.get(f"/api/orders/{order_id}/detail", headers=auth(staff_token)).status_code == 200
    )
    assert client.post(f"/api/orders/{order_id}/pay", headers=auth(staff_token)).status_code == 200


def test_staff_quan_ly_san_pham_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    pid = ctx["product"]["id"]

    # sửa
    res = client.put(
        f"/api/products/{pid}",
        data={"name": "SP staff sua", "price": 55000, "category_id": ctx["category_id"]},
        headers=auth(staff_token),
    )
    assert res.status_code == 200
    # nhập kho
    res = client.post(
        f"/api/products/{pid}/stock", json={"delta": 20}, headers=auth(staff_token)
    )
    assert res.status_code == 200
    assert res.json()["stock"] == 30
    # ẩn/hiện
    assert client.put(f"/api/products/{pid}/status", headers=auth(staff_token)).status_code == 200


def test_staff_tao_san_pham_va_danh_muc_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)

    res = client.post(
        "/api/categories",
        params={"name": "DM staff", "shop_id": ctx["shop_id"]},
        headers=auth(staff_token),
    )
    assert res.status_code == 200
    cat_id = res.json()["id"]

    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={"name": "SP staff tao", "price": 12000, "stock": 5, "category_id": cat_id},
        headers=auth(staff_token),
    )
    assert res.status_code == 200


def test_staff_quan_ly_voucher_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)

    res = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "STAFFVC", "discount_type": "flat", "discount_value": 5000},
        headers=auth(staff_token),
    )
    assert res.status_code == 200
    vid = res.json()["id"]
    assert client.delete(f"/api/vouchers/{vid}", headers=auth(staff_token)).status_code == 200


def test_staff_xem_bao_cao_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    assert (
        client.get(f"/api/dashboard/seller/{ctx['shop_id']}", headers=auth(staff_token)).status_code
        == 200
    )
    assert (
        client.get(f"/api/shops/{ctx['shop_id']}/stats", headers=auth(staff_token)).status_code
        == 200
    )
    assert (
        client.get(f"/api/export/seller/{ctx['shop_id']}", headers=auth(staff_token)).status_code
        == 200
    )


# ================= STAFF KHÔNG LÀM QUẢN TRỊ =================
def test_staff_khong_sua_duoc_thong_tin_shop(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    res = client.put(
        f"/api/shops/{ctx['shop_id']}", json=dict(SHOP_PAYLOAD), headers=auth(staff_token)
    )
    assert res.status_code == 404, "Sửa thông tin shop là quyền quản trị (số TK ngân hàng)"


def test_staff_khong_xoa_duoc_shop(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    assert client.delete(f"/api/shops/{ctx['shop_id']}", headers=auth(staff_token)).status_code == 404


def test_staff_khong_khoa_duoc_shop(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    assert (
        client.put(f"/api/shops/{ctx['shop_id']}/status", headers=auth(staff_token)).status_code
        == 404
    )


def test_staff_khong_quan_ly_duoc_nhan_vien(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)
    # tạo nhân viên khác
    res = client.post(
        f"/api/staff/{ctx['shop_id']}",
        json={"username": "nv_do_staff_tao", "password": "Nhanvien@2026"},
        headers=auth(staff_token),
    )
    assert res.status_code == 404
    # xem danh sách nhân viên
    assert client.get(f"/api/staff/{ctx['shop_id']}", headers=auth(staff_token)).status_code == 404


# ================= STAFF SHOP A KHÔNG ĐỤNG SHOP B =================
def test_staff_khong_dung_duoc_shop_khac(client):
    a = seller_with_shop(client)
    _, staff_a = new_staff(client, a)

    # shop B của người khác
    _, token_b = new_seller(client)
    shop_b = create_shop(client, token_b)
    cat_b = create_category(client, token_b, shop_b)
    prod_b = client.post(
        "/api/products",
        params={"shop_id": shop_b},
        data={"name": "SP shop B", "price": 30000, "stock": 5, "category_id": cat_b},
        headers=auth(token_b),
    ).json()

    # staff của A không bán / không xem / không sửa được shop B
    assert (
        client.post(
            f"/api/orders/{shop_b}",
            json={"items": [{"product_name": "SP shop B", "price": 1, "quantity": 1}]},
            headers=auth(staff_a),
        ).status_code
        == 403
    )
    assert client.get(f"/api/dashboard/seller/{shop_b}", headers=auth(staff_a)).status_code == 403
    assert (
        client.post(
            f"/api/products/{prod_b['id']}/stock", json={"delta": 5}, headers=auth(staff_a)
        ).status_code
        == 403
    )
    assert _ton_kho(prod_b["id"]) == 5, "Tồn kho shop B không bị staff shop A đụng"


def test_hai_staff_hai_shop_doc_lap(client):
    a = seller_with_shop(client)
    _, staff_a = new_staff(client, a)

    b = seller_with_shop(client)
    _, staff_b = new_staff(client, b)

    # staff A thấy đúng shop A, staff B thấy đúng shop B
    shops_a = client.get("/api/shops", headers=auth(staff_a)).json()
    shops_b = client.get("/api/shops", headers=auth(staff_b)).json()
    assert [s["id"] for s in shops_a] == [a["shop_id"]]
    assert [s["id"] for s in shops_b] == [b["shop_id"]]
