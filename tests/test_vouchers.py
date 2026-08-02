"""Voucher: hợp lệ, đơn tối thiểu, hết lượt, hết hạn."""
from datetime import date, timedelta

from conftest import auth, new_seller, new_staff, seller_with_shop

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


def _apply(client, shop_id, code, subtotal=100000, token=None):
    return client.post(
        f"/api/vouchers/apply/{shop_id}",
        data={"subtotal": subtotal, "voucher_code": code},
        headers=auth(token) if token else {},
    )


def test_ap_voucher_flat_hop_le(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="FLAT10K", discount_value=10000)
    res = _apply(client, ctx["shop_id"], "FLAT10K", token=ctx["token"])
    assert res.status_code == 200
    assert res.json() == {"discount_amount": 10000, "new_total": 90000}


def test_ap_voucher_phan_tram(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="PT10", discount_type="percentage", discount_value=10)
    res = _apply(client, ctx["shop_id"], "PT10", token=ctx["token"])
    assert res.json()["discount_amount"] == 10000


def test_voucher_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    assert _apply(client, ctx["shop_id"], "KHONGCO", token=ctx["token"]).status_code == 404


def test_voucher_duoi_don_toi_thieu(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="MIN500", min_order_value=500000)
    res = _apply(client, ctx["shop_id"], "MIN500", subtotal=100000, token=ctx["token"])
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
    res = _apply(client, ctx["shop_id"], "LIMIT1", token=ctx["token"])
    assert res.status_code == 400
    assert "hết lượt" in res.json()["detail"]


def test_voucher_het_han_bi_tu_choi(client):
    """BEHAVIOR FIX: trước đây expires_at không bao giờ được kiểm tra."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="HETHAN", expires_at=HOM_QUA)
    res = _apply(client, ctx["shop_id"], "HETHAN", token=ctx["token"])
    assert res.status_code == 400
    assert "hết hạn" in res.json()["detail"]


def test_voucher_con_han_van_dung_duoc(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="CONHAN", expires_at=NGAY_MAI)
    assert _apply(client, ctx["shop_id"], "CONHAN", token=ctx["token"]).status_code == 200


def test_voucher_khong_dat_han_thi_khong_gioi_han_thoi_gian(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="VOHAN", expires_at=None)
    assert _apply(client, ctx["shop_id"], "VOHAN", token=ctx["token"]).status_code == 200


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


# ---------- F6: hai endpoint voucher từng mở cho cả internet ----------
#
# `GET /api/vouchers/{shop_id}` trả về MÃ voucher kèm giá trị giảm. Không xác
# thực nghĩa là dò `shop_id` từ 1 lên là gom được mã của mọi cửa hàng rồi đem
# dùng - lỗ này mất tiền thật, không chỉ mất thông tin.


def test_danh_sach_voucher_bat_buoc_dang_nhap(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="KINDA-SECRET")
    assert client.get(f"/api/vouchers/{ctx['shop_id']}").status_code == 401


def test_seller_khac_khong_xem_duoc_danh_sach_voucher(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="CUATOI")
    _, token_b = new_seller(client)
    res = client.get(f"/api/vouchers/{ctx['shop_id']}", headers=auth(token_b))
    assert res.status_code == 403


def test_chu_shop_van_xem_duoc_danh_sach_voucher(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="VANTHAY")
    res = client.get(f"/api/vouchers/{ctx['shop_id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    assert any(v["code"] == "VANTHAY" for v in res.json())


def test_manager_xem_duoc_danh_sach_voucher_nhung_thu_ngan_thi_khong(client):
    """Khớp đúng giao diện: tab Khuyến Mãi trong seller.js chỉ hiện cho MANAGER."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="PHANVAI")
    _, manager = new_staff(client, ctx, staff_role="MANAGER")
    _, cashier = new_staff(client, ctx, staff_role="CASHIER")

    assert client.get(
        f"/api/vouchers/{ctx['shop_id']}", headers=auth(manager)
    ).status_code == 200
    assert client.get(
        f"/api/vouchers/{ctx['shop_id']}", headers=auth(cashier)
    ).status_code == 403


def test_ap_voucher_bat_buoc_dang_nhap(client):
    """Không xác thực thì gõ mã bừa vào đây là dò ra mã có thật của shop lạ."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="DOTHU", discount_value=10000)
    assert _apply(client, ctx["shop_id"], "DOTHU").status_code == 401


def test_seller_khac_khong_ap_duoc_voucher_cua_shop_nay(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="KHONGPHAICUABAN", discount_value=10000)
    _, token_b = new_seller(client)
    res = _apply(client, ctx["shop_id"], "KHONGPHAICUABAN", token=token_b)
    assert res.status_code == 403


def test_thu_ngan_van_ap_duoc_voucher(client):
    """Áp mã là việc của người đứng quầy: quyền SALE, không phải VOUCHER."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, code="THUNGAN", discount_value=10000)
    _, cashier = new_staff(client, ctx, staff_role="CASHIER")

    res = _apply(client, ctx["shop_id"], "THUNGAN", token=cashier)
    assert res.status_code == 200, res.text
    assert res.json()["discount_amount"] == 10000
