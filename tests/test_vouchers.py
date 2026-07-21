"""Voucher: hợp lệ, đơn tối thiểu, hết lượt, hết hạn."""
from datetime import date, timedelta

from conftest import auth, new_seller, seller_with_shop

HOM_QUA = (date.today() - timedelta(days=1)).isoformat()
NGAY_MAI = (date.today() + timedelta(days=1)).isoformat()


def _tao_voucher(client, ctx, **kwargs):
    payload = {
        "code": kwargs.pop("code", "GIAM10"),
        "discount_type": kwargs.pop("discount_type", "flat"),
        "discount_value": kwargs.pop("discount_value", 10000),
        "min_order_value": kwargs.pop("min_order_value", 0),
        "usage_limit": kwargs.pop("usage_limit", -1),
        "expires_at": kwargs.pop("expires_at", None),
    }
    res = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _apply(client, shop_id, code, subtotal=100000):
    return client.post(
        f"/api/vouchers/apply/{shop_id}",
        data={"subtotal": subtotal, "voucher_code": code},
    )


def test_ap_voucher_flat_hop_le(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="FLAT10K", discount_value=10000)
    res = _apply(client, ctx["shop_id"], "FLAT10K")
    assert res.status_code == 200
    assert res.json() == {"discount_amount": 10000, "new_total": 90000}


def test_ap_voucher_phan_tram(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="PT10", discount_type="percentage", discount_value=10)
    res = _apply(client, ctx["shop_id"], "PT10")
    assert res.json()["discount_amount"] == 10000


def test_voucher_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    assert _apply(client, ctx["shop_id"], "KHONGCO").status_code == 404


def test_voucher_duoi_don_toi_thieu(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="MIN500", min_order_value=500000)
    res = _apply(client, ctx["shop_id"], "MIN500", subtotal=100000)
    assert res.status_code == 400


def test_voucher_het_luot_su_dung(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="LIMIT1", usage_limit=1)

    # dùng 1 lần qua đơn hàng -> usage_count = 1
    client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 100000, "quantity": 1}],
            "voucher_code": "LIMIT1",
        },
        headers=auth(ctx["token"]),
    )
    res = _apply(client, ctx["shop_id"], "LIMIT1")
    assert res.status_code == 400
    assert "hết lượt" in res.json()["detail"]


def test_voucher_het_han_bi_tu_choi(client):
    """BEHAVIOR FIX: trước đây expires_at không bao giờ được kiểm tra."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="HETHAN", expires_at=HOM_QUA)
    res = _apply(client, ctx["shop_id"], "HETHAN")
    assert res.status_code == 400
    assert "hết hạn" in res.json()["detail"]


def test_voucher_con_han_van_dung_duoc(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="CONHAN", expires_at=NGAY_MAI)
    assert _apply(client, ctx["shop_id"], "CONHAN").status_code == 200


def test_voucher_khong_dat_han_thi_khong_gioi_han_thoi_gian(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="VOHAN", expires_at=None)
    assert _apply(client, ctx["shop_id"], "VOHAN").status_code == 200


def test_don_hang_ap_dung_voucher_hop_le(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="DON10K", discount_value=10000)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 100000, "quantity": 1}],
            "voucher_code": "DON10K",
        },
        headers=auth(ctx["token"]),
    )
    body = res.json()
    assert body["discount"] == 10000
    assert body["total"] == 90000


def test_don_hang_bo_qua_voucher_het_han(client):
    """BEHAVIOR FIX: voucher hết hạn không còn được giảm giá khi tạo đơn."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="DONHET", discount_value=10000, expires_at=HOM_QUA)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 100000, "quantity": 1}],
            "voucher_code": "DONHET",
        },
        headers=auth(ctx["token"]),
    )
    body = res.json()
    assert body["discount"] == 0
    assert body["total"] == 100000


def test_tao_voucher_trung_ma_trong_cung_shop(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="TRUNGMA")
    res = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "TRUNGMA", "discount_type": "flat", "discount_value": 5000},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_tao_voucher_phan_tram_ngoai_khoang(client):
    ctx = seller_with_shop(client)
    res = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "PT200", "discount_type": "percentage", "discount_value": 200},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_seller_khac_khong_tao_duoc_voucher(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "LAU", "discount_type": "flat", "discount_value": 1000},
        headers=auth(token_b),
    )
    assert res.status_code == 403
