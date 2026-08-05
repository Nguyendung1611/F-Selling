"""Kiểm bán hàng khi mất mạng.

Mỗi test ở đây tương ứng một cách mất tiền thật, không phải kiểm cho đủ:

- Giá tính lại theo hôm nay  -> ghi sai số tiền đang nằm trong két
- Sync hai lần               -> doanh thu và tồn kho cùng nhân đôi
- Hết hàng nên từ chối đơn   -> mất luôn dấu vết giao dịch, két thừa so với sổ
- Ca gắn theo giờ sync       -> doanh thu rơi sang ca đã chốt quỹ xong
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta

from conftest import auth, create_product, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _uid() -> str:
    return "off-" + _uuid.uuid4().hex


def _phieu(product, so_luong=1, gia=None, tien_dua=None, luc_ban=None, uuid=None, may="POS-01"):
    """Mặc định `sold_at` = BÂY GIỜ, không phải quá khứ.

    Từng để mặc định 30 phút trước và bốn test đỏ oan: ca trong test được mở
    ngay lúc chạy, nên mọi phiếu "bán 30 phút trước" đều rơi vào khoảng chưa ai
    mở ca và bị gắn cờ KHONG_CO_CA. Đó là hành vi ĐÚNG của service — chỉ có
    kịch bản test là sai.
    """
    gia = product["price"] if gia is None else gia
    tong = gia * so_luong
    return {
        "offline_uuid": uuid or _uid(),
        "sold_at": (luc_ban or datetime.utcnow()).isoformat(),
        "items": [
            {
                "product_id": product["id"],
                "product_name": product["name"],
                "unit_price": gia,
                "quantity": so_luong,
            }
        ],
        "cash_tendered": tong if tien_dua is None else tien_dua,
        "device_label": may,
    }


def _gui(client, ctx, phieu):
    return client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        json=phieu,
        headers=auth(ctx["token"]),
    )


def _mo_ca(client, ctx, tien_dau=0):
    res = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": tien_dau},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _doi_gia(client, ctx, sp, gia_moi):
    """PUT sản phẩm là form đầy đủ: thiếu `name` hay `category_id` là 422."""
    res = client.put(
        f"/api/products/{sp['id']}",
        data={"name": sp["name"], "price": gia_moi, "category_id": ctx["category_id"]},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text


def _ton_kho(product_id: int) -> int:
    s = SessionLocal()
    try:
        return s.query(models.Product).filter(models.Product.id == product_id).first().stock
    finally:
        s.close()


# ---------- Giá phải lấy từ phiếu ----------
def test_giu_nguyen_gia_tren_phieu_du_gia_hien_tai_da_doi(client):
    """Bán 100k lúc 9h, chủ shop đổi giá 120k, sync lúc 14h.

    Ghi 120k là ghi sai số tiền đang nằm trong két — lệch 20k và không tra ra
    được vì sao. Đây là lý do tồn tại của cả endpoint này.
    """
    ctx = seller_with_shop(client)
    sp = ctx["product"]  # giá 100000
    _mo_ca(client, ctx)

    _doi_gia(client, ctx, sp, 120000)  # chủ shop đổi giá SAU khi đã bán

    res = _gui(client, ctx, _phieu(sp, so_luong=1, gia=100000))
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 100000, "phải ghi giá khách đã trả, không phải giá hôm nay"


def test_gia_doi_thi_gan_co_cho_chu_shop_biet(client):
    ctx = seller_with_shop(client)
    sp = ctx["product"]
    _mo_ca(client, ctx)
    _doi_gia(client, ctx, sp, 120000)

    res = _gui(client, ctx, _phieu(sp, gia=100000))
    assert "GIA_DOI" in res.json()["issues"]


def test_gia_khong_doi_thi_khong_gan_co_gi(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    res = _gui(client, ctx, _phieu(ctx["product"]))
    assert res.status_code == 200, res.text
    assert res.json()["issues"] == []


# ---------- Chống ghi hai lần ----------
def test_gui_lai_cung_uuid_khong_tao_don_thu_hai(client):
    """Máy bán mất sóng giữa lúc gửi rồi gửi lại là chuyện BÌNH THƯỜNG."""
    ctx = seller_with_shop(client)
    sp = ctx["product"]
    _mo_ca(client, ctx)
    phieu = _phieu(sp, so_luong=2)

    r1 = _gui(client, ctx, phieu)
    assert r1.status_code == 200, r1.text
    assert r1.json()["created"] is True

    r2 = _gui(client, ctx, phieu)
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] is False, "lần hai phải là no-op"
    assert r2.json()["order_id"] == r1.json()["order_id"]


def test_gui_lai_khong_tru_kho_lan_hai(client):
    ctx = seller_with_shop(client)
    sp = ctx["product"]  # tồn 10
    _mo_ca(client, ctx)
    phieu = _phieu(sp, so_luong=3)

    _gui(client, ctx, phieu)
    con_sau_lan_dau = _ton_kho(sp["id"])
    _gui(client, ctx, phieu)
    assert _ton_kho(sp["id"]) == con_sau_lan_dau == 7


def test_gui_lai_khong_cong_tien_lan_hai(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    phieu = _phieu(ctx["product"], so_luong=2)
    _gui(client, ctx, phieu)
    _gui(client, ctx, phieu)

    s = SessionLocal()
    try:
        don_id = s.query(models.Order).filter(models.Order.offline_uuid == phieu["offline_uuid"]).first().id
        so_but_toan = (
            s.query(models.OrderPayment).filter(models.OrderPayment.order_id == don_id).count()
        )
    finally:
        s.close()
    assert so_but_toan == 1, "một phiếu chỉ được sinh đúng một bút toán tiền mặt"


# ---------- Hết hàng vẫn phải ghi ----------
def test_khong_du_ton_van_ghi_don_va_cho_ton_am(client):
    """Hàng đã ra khỏi cửa thật. Từ chối đơn là mất dấu vết giao dịch, và tiền
    trong két sẽ thừa so với sổ."""
    ctx = seller_with_shop(client)
    sp = ctx["product"]  # tồn 10
    _mo_ca(client, ctx)

    res = _gui(client, ctx, _phieu(sp, so_luong=13))
    assert res.status_code == 200, res.text
    assert "TON_AM" in res.json()["issues"]
    assert _ton_kho(sp["id"]) == -3


def test_du_ton_thi_khong_gan_co_ton_am(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    res = _gui(client, ctx, _phieu(ctx["product"], so_luong=4))
    assert "TON_AM" not in res.json()["issues"]
    assert _ton_kho(ctx["product"]["id"]) == 6


def test_don_ton_am_hien_o_danh_sach_can_xu_ly(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    _gui(client, ctx, _phieu(ctx["product"], so_luong=99, may="POS-KIOT-2"))

    res = client.get(
        f"/api/orders/{ctx['shop_id']}/offline-issues", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    ds = res.json()
    assert len(ds) == 1
    assert "TON_AM" in ds[0]["issues"]
    assert ds[0]["device"] == "POS-KIOT-2", "chủ shop cần biết máy nào bán"


def test_don_khong_van_de_khong_lam_ban_danh_sach_xu_ly(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    _gui(client, ctx, _phieu(ctx["product"], so_luong=1))
    res = client.get(
        f"/api/orders/{ctx['shop_id']}/offline-issues", headers=auth(ctx["token"])
    )
    assert res.json() == []


# ---------- Ca thu ngân theo giờ bán ----------
def test_don_gan_vao_ca_dang_mo_luc_ban(client):
    ctx = seller_with_shop(client)
    ca = _mo_ca(client, ctx)
    res = _gui(client, ctx, _phieu(ctx["product"], luc_ban=datetime.utcnow()))
    assert res.json()["shift_id"] == ca["id"]
    assert res.json()["issues"] == []


def test_ban_truoc_khi_mo_ca_thi_bao_khong_co_ca(client):
    """Bán lúc chưa ai mở ca: không được im lặng gán bừa vào ca hiện tại."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    hom_qua = datetime.utcnow() - timedelta(days=1)

    res = _gui(client, ctx, _phieu(ctx["product"], luc_ban=hom_qua))
    assert res.status_code == 200, res.text
    assert "KHONG_CO_CA" in res.json()["issues"]
    assert res.json()["shift_id"] is None


def test_tien_mat_vao_dung_ca_luc_ban(client):
    """Bút toán phải mang shift_id của ca lúc bán, vì `_expected_cash` của ca
    cộng theo cột đó."""
    ctx = seller_with_shop(client)
    ca = _mo_ca(client, ctx)
    _gui(client, ctx, _phieu(ctx["product"], so_luong=2, luc_ban=datetime.utcnow()))

    s = SessionLocal()
    try:
        bt = (
            s.query(models.OrderPayment)
            .filter(models.OrderPayment.entry_type == "SALE_CASH")
            .order_by(models.OrderPayment.id.desc())
            .first()
        )
    finally:
        s.close()
    assert bt.shift_id == ca["id"]
    assert bt.amount == 200000


def test_don_offline_lam_tang_tien_mat_du_kien_cua_ca(client):
    ctx = seller_with_shop(client)
    ca = _mo_ca(client, ctx, tien_dau=500000)
    _gui(client, ctx, _phieu(ctx["product"], so_luong=3, luc_ban=datetime.utcnow()))

    res = client.get(f"/api/shifts/{ca['id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    assert res.json()["cash_payment_in_amount"] == 300000


# ---------- Chỉ tiền mặt, và phiếu phải hợp lệ ----------
def test_tien_khach_dua_it_hon_tong_don_thi_tu_choi(client):
    """Đây là phiếu SAI, không phải xung đột dữ liệu. Nhận vào là ghi một khoản
    thu không có thật."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    res = _gui(client, ctx, _phieu(ctx["product"], so_luong=2, tien_dua=150000))
    assert res.status_code == 400
    assert "nhỏ hơn tổng đơn" in res.json()["detail"]


def test_gio_ban_o_tuong_lai_thi_tu_choi(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    mai = datetime.utcnow() + timedelta(days=1)
    res = _gui(client, ctx, _phieu(ctx["product"], luc_ban=mai))
    assert res.status_code == 400


def test_phieu_khong_co_mat_hang_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    phieu = _phieu(ctx["product"])
    phieu["items"] = []
    assert _gui(client, ctx, phieu).status_code == 422


def test_tien_thua_duoc_tinh_dung(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    phieu = _phieu(ctx["product"], so_luong=1, tien_dua=200000)
    res = _gui(client, ctx, phieu)
    assert res.status_code == 200, res.text

    s = SessionLocal()
    try:
        don = s.query(models.Order).filter(models.Order.offline_uuid == phieu["offline_uuid"]).first()
        assert don.cash_change_amount == 100000
        assert don.cash_paid_amount == 100000
        assert don.status == "PAID"
        assert don.payment_method == "cash"
    finally:
        s.close()


# ---------- Cách ly giữa các shop ----------
def test_khong_ban_duoc_hang_cua_shop_khac(client):
    """Đoán product_id của shop khác phải trượt. Thiếu điều kiện shop_id trong
    câu truy vấn là bán được hàng của người ta (bẫy 22)."""
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    _mo_ca(client, a)

    phieu = _phieu(b["product"])  # sản phẩm của shop B
    res = _gui(client, a, phieu)  # gửi vào shop A
    assert res.status_code == 200, res.text
    # Không tìm thấy trong shop A -> ghi nhận tiền nhưng gắn cờ, KHÔNG trừ kho shop B
    assert "SP_KHONG_CON" in res.json()["issues"]
    assert _ton_kho(b["product"]["id"]) == 10, "tồn kho shop B không được đụng tới"


def test_uuid_cua_shop_khac_thi_bao_xung_dot(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    _mo_ca(client, a)
    _mo_ca(client, b)

    phieu = _phieu(a["product"])
    assert _gui(client, a, phieu).status_code == 200
    assert _gui(client, b, phieu).status_code == 409


def test_nguoi_ngoai_khong_gui_duoc_phieu(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{a['shop_id']}/offline",
        json=_phieu(a["product"]),
        headers=auth(b["token"]),
    )
    assert res.status_code in (403, 404)


def test_chua_dang_nhap_thi_bi_chan(client):
    a = seller_with_shop(client)
    res = client.post(f"/api/orders/{a['shop_id']}/offline", json=_phieu(a["product"]))
    assert res.status_code == 401


# ---------- Sản phẩm bị xóa giữa lúc bán và lúc sync ----------
def test_san_pham_da_xoa_van_ghi_duoc_dong_tien(client):
    """Mất tên sản phẩm là khoản tiền trong két không còn tra được về đâu."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    sp = create_product(
        client, ctx["token"], ctx["shop_id"], "Hang sap xoa", 50000, 5, ctx["category_id"]
    )
    phieu = _phieu(sp, so_luong=2)

    res = client.delete(f"/api/products/{sp['id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text

    res = _gui(client, ctx, phieu)
    assert res.status_code == 200, res.text
    assert "SP_KHONG_CON" in res.json()["issues"]
    assert res.json()["total"] == 100000

    s = SessionLocal()
    try:
        don = s.query(models.Order).filter(models.Order.offline_uuid == phieu["offline_uuid"]).first()
        dong = s.query(models.OrderItem).filter(models.OrderItem.order_id == don.id).all()
        assert len(dong) == 1
        assert dong[0].product_name == "Hang sap xoa", "tên đã chụp phải được giữ"
    finally:
        s.close()


# ---------- Nhân viên ----------
def test_nhan_vien_ban_hang_gui_duoc_phieu(client):
    ctx = seller_with_shop(client)
    _, token_nv = new_staff(client, ctx, staff_role="CASHIER")
    res = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        json=_phieu(ctx["product"]),
        headers=auth(token_nv),
    )
    assert res.status_code == 200, res.text
