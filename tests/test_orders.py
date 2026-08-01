"""Đơn hàng: giá lấy từ DB, tồn kho, quyền tạo đơn, xác nhận thanh toán."""
from conftest import PAYMENT_SUMMARY_KEYS, auth, new_seller, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _order_payload(name, price, qty=1, voucher=None, method="transfer"):
    body = {
        "items": [{"product_name": name, "price": price, "quantity": qty}],
        "payment_method": method,
    }
    if voucher:
        body["voucher_code"] = voucher
    return body


def test_tao_don_dung_gia_tu_database_bo_qua_gia_client(client):
    a = seller_with_shop(client)
    name = a["product"]["name"]

    # Client cố gửi giá 1đ cho sản phẩm giá 100.000đ
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(name, price=1, qty=2),
        headers=auth(a["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subtotal"] == 200000
    assert body["total"] == 200000
    assert set(body.keys()) == {"order_id", "subtotal", "discount", "total", "qr_url"}
    assert "img.vietqr.io" in body["qr_url"]
    assert f"ORDER{body['order_id']}" in body["qr_url"]


def test_tao_don_tru_ton_kho(client):
    a = seller_with_shop(client)
    name = a["product"]["name"]
    client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(name, 100000, qty=3),
        headers=auth(a["token"]),
    )
    session = SessionLocal()
    try:
        prod = session.query(models.Product).filter(models.Product.id == a["product"]["id"]).first()
        assert prod.stock == 7
    finally:
        session.close()


def test_khong_ban_vuot_ton_kho(client):
    a = seller_with_shop(client)
    name = a["product"]["name"]
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(name, 100000, qty=999),
        headers=auth(a["token"]),
    )
    assert res.status_code == 400
    assert "không đủ tồn kho" in res.json()["detail"]

    session = SessionLocal()
    try:
        prod = session.query(models.Product).filter(models.Product.id == a["product"]["id"]).first()
        assert prod.stock == 10  # không bị trừ khi đơn thất bại
    finally:
        session.close()


def test_gop_so_luong_cung_san_pham_khi_kiem_ton_kho(client):
    a = seller_with_shop(client)
    name = a["product"]["name"]
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json={
            "items": [
                {"product_name": name, "price": 100000, "quantity": 6},
                {"product_name": name, "price": 100000, "quantity": 6},
            ],
            "payment_method": "cash",
        },
        headers=auth(a["token"]),
    )
    assert res.status_code == 400  # 12 > 10


def test_so_luong_khong_hop_le(client):
    a = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(a["product"]["name"], 100000, qty=0),
        headers=auth(a["token"]),
    )
    assert res.status_code == 400


def test_don_hang_rong_bi_tu_choi(client):
    a = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{a['shop_id']}", json={"items": []}, headers=auth(a["token"])
    )
    assert res.status_code == 400


def test_san_pham_khong_ton_tai_tra_404(client):
    a = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload("San pham ma", 1000),
        headers=auth(a["token"]),
    )
    assert res.status_code == 404


def test_san_pham_da_an_khong_ban_duoc(client):
    a = seller_with_shop(client)
    client.put(f"/api/products/{a['product']['id']}/status", headers=auth(a["token"]))
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(a["product"]["name"], 100000),
        headers=auth(a["token"]),
    )
    assert res.status_code == 404


def test_tao_don_yeu_cau_dang_nhap(client):
    a = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{a['shop_id']}", json=_order_payload(a["product"]["name"], 100000)
    )
    assert res.status_code == 401


def test_seller_khac_khong_tao_duoc_don_cho_shop_nguoi_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(a["product"]["name"], 100000),
        headers=auth(token_b),
    )
    assert res.status_code == 403


def test_xac_nhan_thanh_toan_thu_cong(client):
    a = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(a["product"]["name"], 100000, method="cash"),
        headers=auth(a["token"]),
    ).json()["order_id"]

    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(a["token"]))
    assert res.status_code == 200
    assert res.json() == {"msg": "Paid successfully"}

    got = client.get(f"/api/orders/{order_id}", headers=auth(a["token"])).json()
    assert got["status"] == "PAID"
    assert set(got.keys()) == {
        "id", "shop_id", "status", "total_amount", "payment_method",
    } | PAYMENT_SUMMARY_KEYS
    assert got["cash_paid_amount"] == 100000
    assert got["invoice_issued"] is True


def test_seller_khac_khong_xac_nhan_duoc_thanh_toan(client):
    a = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(a["product"]["name"], 100000),
        headers=auth(a["token"]),
    ).json()["order_id"]

    _, token_b = new_seller(client)
    assert client.post(f"/api/orders/{order_id}/pay", headers=auth(token_b)).status_code == 403
    assert client.get(f"/api/orders/{order_id}", headers=auth(token_b)).status_code == 403


def test_doanh_thu_chi_tinh_don_da_thanh_toan(client):
    a = seller_with_shop(client)
    name = a["product"]["name"]
    client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(name, 100000),
        headers=auth(a["token"]),
    )
    stats = client.get(f"/api/shops/{a['shop_id']}/stats", headers=auth(a["token"])).json()
    assert stats["total_revenue"] == 0
    assert stats["total_orders"] == 1

    order_id = client.post(
        f"/api/orders/{a['shop_id']}",
        json=_order_payload(name, 100000, method="cash"),
        headers=auth(a["token"]),
    ).json()["order_id"]
    client.post(f"/api/orders/{order_id}/pay", headers=auth(a["token"]))

    stats = client.get(f"/api/shops/{a['shop_id']}/stats", headers=auth(a["token"])).json()
    assert stats["total_revenue"] == 100000
    assert set(stats.keys()) == {
        "total_revenue",
        "total_orders",
        "total_sold",
        "top_products",
        "trend_labels",
        "trend_data",
        # F1: nhóm field lãi gộp, chỉ chủ shop và ADMIN mới nhận được.
        "revenue_with_cost",
        "total_cost",
        "gross_profit",
        "gross_margin",
        "orders_missing_cost",
        "revenue_missing_cost",
        "returns_missing_cost",
        # F2: hàng khách trả lại (ngày trả, không phải ngày bán).
        "returned_amount",
        "net_revenue",
    }
