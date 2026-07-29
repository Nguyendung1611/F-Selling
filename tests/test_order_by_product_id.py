"""GĐ 3: đơn hàng định danh sản phẩm bằng product_id thay vì tên.

Khớp theo tên không tin cậy: tên đổi được, và hai sản phẩm trùng tên từng bị
gộp vào cùng một dòng giỏ hàng. Đường cũ (chỉ gửi product_name) vẫn phải chạy
để client cũ không vỡ.
"""
from __future__ import annotations

from conftest import auth, create_category, create_shop, new_seller, seller_with_shop


def _tao_sp(client, token, shop_id, cat_id, name, price=10000, stock=20):
    res = client.post(
        "/api/products",
        params={"shop_id": shop_id},
        data={"name": name, "price": price, "stock": stock, "category_id": cat_id},
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _dat(client, token, shop_id, items):
    return client.post(
        f"/api/orders/{shop_id}",
        json={"items": items, "payment_method": "cash"},
        headers=auth(token),
    )


# ---------- Đường mới: product_id ----------


def test_dat_hang_bang_product_id(client):
    ctx = seller_with_shop(client)
    sp = ctx["product"]

    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "price": 1, "quantity": 2}
    ])
    assert res.status_code == 200, res.text
    # Giá lấy từ DB (100000), không tin giá 1 mà client gửi.
    assert res.json()["total"] == 200000


def test_product_id_thang_khi_gui_kem_ten_sai(client):
    """Server phải định danh theo id, bỏ qua tên client gửi."""
    ctx = seller_with_shop(client)
    sp = ctx["product"]

    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "product_name": "Tên bịa hoàn toàn", "price": 1, "quantity": 1}
    ])
    assert res.status_code == 200, res.text

    ct = client.get(f"/api/orders/{res.json()['order_id']}/detail", headers=auth(ctx["token"]))
    dong = ct.json()["items"][0]
    assert dong["product_id"] == sp["id"]
    assert dong["product_name"] == sp["name"]  # tên chụp từ DB, không phải tên bịa


def test_gom_so_luong_khi_gui_nhieu_dong_cung_product_id(client):
    ctx = seller_with_shop(client)
    sp = ctx["product"]

    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "price": 1, "quantity": 2},
        {"product_id": sp["id"], "price": 1, "quantity": 3},
    ])
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 500000  # 5 x 100000


def test_product_id_khong_ton_tai_tra_404(client):
    ctx = seller_with_shop(client)
    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_id": 999999, "price": 1, "quantity": 1}
    ])
    assert res.status_code == 404


def test_product_id_cua_shop_khac_bi_tu_choi(client):
    """Chốt bảo mật: đoán id không được phép đặt hàng của shop khác."""
    ctx1 = seller_with_shop(client)

    _, token2 = new_seller(client)
    shop2 = create_shop(client, token2)
    cat2 = create_category(client, token2, shop2)
    sp_shop2 = _tao_sp(client, token2, shop2, cat2, "SP cua shop 2")

    # Chủ shop 1 thử đặt sản phẩm của shop 2 vào đơn của shop 1.
    res = _dat(client, ctx1["token"], ctx1["shop_id"], [
        {"product_id": sp_shop2["id"], "price": 1, "quantity": 1}
    ])
    assert res.status_code == 404

    # Tồn kho shop 2 không được đụng tới.
    ds = client.get(f"/api/products/{shop2}")
    assert [p for p in ds.json() if p["id"] == sp_shop2["id"]][0]["stock"] == 20


def test_product_id_cua_sp_da_an_tra_404(client):
    ctx = seller_with_shop(client)
    sp = ctx["product"]
    client.put(f"/api/products/{sp['id']}/status", headers=auth(ctx["token"]))

    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "price": 1, "quantity": 1}
    ])
    assert res.status_code == 404


def test_thieu_ton_kho_bao_ten_san_pham(client):
    ctx = seller_with_shop(client)
    sp = ctx["product"]

    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "price": 1, "quantity": 999}
    ])
    assert res.status_code == 400
    assert sp["name"] in res.json()["detail"]
    assert "không đủ tồn kho" in res.json()["detail"]


# ---------- Đường cũ: chỉ có product_name ----------


def test_dat_hang_chi_bang_ten_van_chay(client):
    """Client cũ chưa gửi product_id không được vỡ."""
    ctx = seller_with_shop(client)
    sp = ctx["product"]

    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_name": sp["name"], "price": 1, "quantity": 2}
    ])
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 200000

    ct = client.get(f"/api/orders/{res.json()['order_id']}/detail", headers=auth(ctx["token"]))
    # Vẫn phải ghi được product_id để hoàn kho chính xác khi hủy đơn.
    assert ct.json()["items"][0]["product_id"] == sp["id"]


def test_khong_co_id_lan_ten_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _dat(client, ctx["token"], ctx["shop_id"], [{"price": 1, "quantity": 1}])
    assert res.status_code == 400
    assert "product_id" in res.json()["detail"]


def test_ten_rong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _dat(client, ctx["token"], ctx["shop_id"], [
        {"product_name": "   ", "price": 1, "quantity": 1}
    ])
    assert res.status_code == 400


# ---------- Điều mà bản cũ làm sai ----------


def test_hai_sp_trung_ten_khong_con_gop_nham_dong(client):
    """Bài kiểm cốt lõi của GĐ 3.

    Ràng buộc mới chặn tên trùng trong cùng shop, nên dựng tình huống bằng hai
    shop: mỗi shop một sản phẩm cùng tên, giá khác nhau. Đặt bằng product_id
    phải ra đúng giá của shop tương ứng - khớp theo tên thì có thể vớ nhầm.
    """
    ctx1 = seller_with_shop(client)
    sp1 = _tao_sp(client, ctx1["token"], ctx1["shop_id"], ctx1["category_id"], "Ao thun", price=50000)

    _, token2 = new_seller(client)
    shop2 = create_shop(client, token2)
    cat2 = create_category(client, token2, shop2)
    sp2 = _tao_sp(client, token2, shop2, cat2, "Ao thun", price=300000)

    r1 = _dat(client, ctx1["token"], ctx1["shop_id"], [
        {"product_id": sp1["id"], "product_name": "Ao thun", "price": 1, "quantity": 1}
    ])
    r2 = _dat(client, token2, shop2, [
        {"product_id": sp2["id"], "product_name": "Ao thun", "price": 1, "quantity": 1}
    ])
    assert r1.json()["total"] == 50000
    assert r2.json()["total"] == 300000
