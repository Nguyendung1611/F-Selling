"""Nhập/xuất kho theo delta: POST /api/products/{product_id}/stock.

Thay cho việc ghi đè tồn kho từ form sửa. Dùng UPDATE nguyên tử nên bán hàng
song song không ghi đè lẫn nhau và tồn kho không bao giờ âm.
"""
from conftest import admin_token, auth, new_seller, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _ton_kho(product_id):
    session = SessionLocal()
    try:
        return session.query(models.Product).filter(models.Product.id == product_id).first().stock
    finally:
        session.close()


def _dieu_chinh(client, token, product_id, delta):
    return client.post(
        f"/api/products/{product_id}/stock",
        json={"delta": delta, "reason": "Kiểm thử điều chỉnh kho"},
        headers=auth(token),
    )


def test_nhap_kho_cong_ton(client):
    ctx = seller_with_shop(client)  # tồn 10
    res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], 5)
    assert res.status_code == 200
    assert res.json()["stock"] == 15
    assert _ton_kho(ctx["product"]["id"]) == 15


def test_xuat_kho_tru_ton(client):
    ctx = seller_with_shop(client)
    res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], -3)
    assert res.status_code == 200
    assert res.json()["stock"] == 7


def test_xuat_qua_ton_bi_tu_choi(client):
    ctx = seller_with_shop(client)  # tồn 10
    res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], -50)
    assert res.status_code == 400
    assert _ton_kho(ctx["product"]["id"]) == 10, "Tồn kho không đổi khi xuất quá số có"


def test_xuat_dung_bang_ton_ve_khong(client):
    ctx = seller_with_shop(client)
    res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], -10)
    assert res.status_code == 200
    assert res.json()["stock"] == 0


def test_delta_khong_duoc_bang_0(client):
    ctx = seller_with_shop(client)
    res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], 0)
    assert res.status_code == 400


def test_dieu_chinh_kho_bat_buoc_co_ly_do(client):
    """Nhập/xuất tay không có chứng từ NCC nên lý do là dấu vết bắt buộc."""
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]

    missing = client.post(
        f"/api/products/{product_id}/stock",
        json={"delta": 5},
        headers=auth(ctx["token"]),
    )
    blank = client.post(
        f"/api/products/{product_id}/stock",
        json={"delta": 5, "reason": "   "},
        headers=auth(ctx["token"]),
    )

    assert missing.status_code in (400, 422)
    assert blank.status_code in (400, 422)
    assert _ton_kho(product_id) == 10


def test_nhap_xuat_lien_tiep_cong_don_dung(client):
    """Nhiều lần điều chỉnh phải cộng dồn theo tồn thực, không ghi đè."""
    ctx = seller_with_shop(client)  # 10
    for delta, mong_doi in [(5, 15), (-8, 7), (3, 10), (-10, 0)]:
        res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], delta)
        assert res.status_code == 200
        assert res.json()["stock"] == mong_doi


def test_dieu_chinh_khong_dung_len_ban_hang(client):
    """Nhập kho cộng lên tồn thực đã bị POS trừ, không kéo về giá trị cũ."""
    ctx = seller_with_shop(client)  # 10
    client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 4}]},
        headers=auth(ctx["token"]),
    )
    assert _ton_kho(ctx["product"]["id"]) == 6

    res = _dieu_chinh(client, ctx["token"], ctx["product"]["id"], 20)
    assert res.json()["stock"] == 26, "6 + 20, không phải 10 + 20"


def test_ghi_log_he_thong(client):
    ctx = seller_with_shop(client)
    _dieu_chinh(client, ctx["token"], ctx["product"]["id"], 7)

    session = SessionLocal()
    try:
        log = (
            session.query(models.SystemLog)
            .filter(models.SystemLog.action == "ADJUST_STOCK")
            .order_by(models.SystemLog.id.desc())
            .first()
        )
        assert log is not None
        assert "Nhập" in log.details
        assert "Kiểm thử điều chỉnh kho" in log.details
    finally:
        session.close()


# ---------- Phân quyền ----------
def test_seller_khac_khong_dieu_chinh_duoc(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = _dieu_chinh(client, token_b, ctx["product"]["id"], 5)
    assert res.status_code == 403
    assert _ton_kho(ctx["product"]["id"]) == 10


def test_admin_dieu_chinh_duoc(client):
    ctx = seller_with_shop(client)
    res = _dieu_chinh(client, admin_token(client), ctx["product"]["id"], 5)
    assert res.status_code == 200


def test_chua_dang_nhap_khong_dieu_chinh_duoc(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/products/{ctx['product']['id']}/stock",
        json={"delta": 5, "reason": "Kiểm thử nhập kho"},
    )
    assert res.status_code == 401


def test_san_pham_khong_ton_tai_tra_404(client):
    _, token = new_seller(client)
    res = _dieu_chinh(client, token, 999999, 5)
    assert res.status_code == 404
