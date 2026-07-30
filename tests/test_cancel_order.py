"""A1d: hủy đơn + hoàn tồn kho + trả lại lượt voucher.

Toàn bộ tác dụng phụ chỉ chạy khi UPDATE có điều kiện (A1c) thắng, nên hủy
trùng / hủy đua với webhook không bao giờ hoàn kho hai lần.
"""
import pytest
from conftest import (
    auth,
    create_category,
    create_product,
    create_shop,
    new_seller,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.services.order_service import (
    STATUS_CANCELLED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_UNRECONCILED,
    read_status,
)

SECRET = "webhook-secret-a1d"


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _tao_don(client, quantity=3, voucher_code=None, payment_method="transfer"):
    ctx = seller_with_shop(client)  # sản phẩm giá 100000, tồn 10
    body = {
        "items": [
            {"product_name": ctx["product"]["name"], "price": 100000, "quantity": quantity}
        ]
    }
    if voucher_code:
        body["voucher_code"] = voucher_code
    body["payment_method"] = payment_method
    res = client.post(f"/api/orders/{ctx['shop_id']}", json=body, headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    return ctx, res.json()


def _ton_kho(product_id):
    session = SessionLocal()
    try:
        return session.query(models.Product).filter(models.Product.id == product_id).first().stock
    finally:
        session.close()


def _trang_thai(order_id):
    session = SessionLocal()
    try:
        return read_status(session, order_id)
    finally:
        session.close()


def _voucher(shop_id, code):
    session = SessionLocal()
    try:
        return (
            session.query(models.Voucher)
            .filter(models.Voucher.code == code, models.Voucher.shop_id == shop_id)
            .first()
        )
    finally:
        session.close()


def _tao_voucher(client, ctx, code, **kwargs):
    payload = {
        "code": code,
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


def _huy(client, ctx, order_id):
    return client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))


# ---------- Hoàn tồn kho ----------
def test_huy_don_hoan_lai_dung_so_luong(client):
    ctx, order = _tao_don(client, quantity=3)
    assert _ton_kho(ctx["product"]["id"]) == 7

    res = _huy(client, ctx, order["order_id"])
    assert res.status_code == 200
    assert res.json()["restored_items"] == 1
    assert res.json()["unrestored_items"] == 0
    assert _ton_kho(ctx["product"]["id"]) == 10
    assert _trang_thai(order["order_id"]) == STATUS_CANCELLED


def test_huy_don_nhieu_san_pham_hoan_tung_dong(client):
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    p1 = create_product(client, token, shop_id, "SP mot", 10000, 20, cat_id)
    p2 = create_product(client, token, shop_id, "SP hai", 20000, 30, cat_id)
    ctx = {"shop_id": shop_id, "token": token}

    order = client.post(
        f"/api/orders/{shop_id}",
        json={
            "items": [
                {"product_name": "SP mot", "price": 1, "quantity": 5},
                {"product_name": "SP hai", "price": 1, "quantity": 7},
            ]
        },
        headers=auth(token),
    ).json()
    assert (_ton_kho(p1["id"]), _ton_kho(p2["id"])) == (15, 23)

    res = _huy(client, ctx, order["order_id"])
    assert res.json()["restored_items"] == 2
    assert (_ton_kho(p1["id"]), _ton_kho(p2["id"])) == (20, 30)


def test_huy_trung_khong_hoan_kho_hai_lan(client):
    ctx, order = _tao_don(client, quantity=4)

    res1 = _huy(client, ctx, order["order_id"])
    assert res1.status_code == 200
    assert res1.json()["restored_items"] == 1
    assert _ton_kho(ctx["product"]["id"]) == 10

    res2 = _huy(client, ctx, order["order_id"])
    assert res2.status_code == 200, "Bấm hủy trùng trả 200 im lặng"
    assert res2.json()["restored_items"] == 0, "Lần hủy thứ hai KHÔNG được hoàn kho"
    assert _ton_kho(ctx["product"]["id"]) == 10, "Tồn kho không được vượt quá ban đầu"


def test_ban_lai_duoc_sau_khi_huy(client):
    ctx, order = _tao_don(client, quantity=10)  # bán sạch kho
    assert _ton_kho(ctx["product"]["id"]) == 0

    _huy(client, ctx, order["order_id"])
    assert _ton_kho(ctx["product"]["id"]) == 10

    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 10}]},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, "Kho đã hoàn nên phải bán lại được"


def test_dong_thieu_product_id_duoc_dem_rieng_khong_nuot_im_lang(client):
    """Đơn cũ trước migration A1a mà backfill không khớp được."""
    ctx, order = _tao_don(client, quantity=2)
    session = SessionLocal()
    try:
        item = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == order["order_id"])
            .first()
        )
        item.product_id = None  # giả lập dòng dữ liệu cũ
        session.commit()
    finally:
        session.close()

    ton_truoc = _ton_kho(ctx["product"]["id"])
    res = _huy(client, ctx, order["order_id"])

    assert res.status_code == 200
    assert res.json()["restored_items"] == 0
    assert res.json()["unrestored_items"] == 1
    assert _ton_kho(ctx["product"]["id"]) == ton_truoc, "Không đoán mò theo tên"
    assert _trang_thai(order["order_id"]) == STATUS_CANCELLED


# ---------- Voucher ----------
def test_huy_don_tra_lai_luot_voucher(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, "HUY10K", discount_value=10000)

    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
            "voucher_code": "HUY10K",
        },
        headers=auth(ctx["token"]),
    ).json()
    assert order["discount"] == 10000
    assert _voucher(ctx["shop_id"], "HUY10K").usage_count == 1

    res = _huy(client, ctx, order["order_id"])
    assert res.json()["voucher_released"] is True
    assert _voucher(ctx["shop_id"], "HUY10K").usage_count == 0


def test_khong_tra_luot_cho_voucher_chua_tung_duoc_ap_dung(client):
    """Đơn lưu voucher_code kể cả khi voucher bị bỏ qua - không được trả nhầm lượt."""
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, "MIN999", discount_value=10000, min_order_value=999999999)

    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
            "voucher_code": "MIN999",
        },
        headers=auth(ctx["token"]),
    ).json()
    assert order["discount"] == 0, "Voucher bị bỏ qua vì chưa đạt đơn tối thiểu"
    assert _voucher(ctx["shop_id"], "MIN999").usage_count == 0

    res = _huy(client, ctx, order["order_id"])
    assert res.json()["voucher_released"] is False
    assert _voucher(ctx["shop_id"], "MIN999").usage_count == 0, "Không được xuống âm"


def test_usage_count_khong_bao_gio_xuong_am(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, "AMTEST", discount_value=10000)

    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
            "voucher_code": "AMTEST",
        },
        headers=auth(ctx["token"]),
    ).json()

    _huy(client, ctx, order["order_id"])
    _huy(client, ctx, order["order_id"])  # hủy trùng
    _huy(client, ctx, order["order_id"])

    assert _voucher(ctx["shop_id"], "AMTEST").usage_count == 0


def test_huy_don_giai_phong_luot_cuoi_de_dung_lai_voucher(client):
    ctx = seller_with_shop(client)
    _tao_voucher(client, ctx, "LIMIT1D", discount_value=10000, usage_limit=1)

    order = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}],
            "voucher_code": "LIMIT1D",
        },
        headers=auth(ctx["token"]),
    ).json()

    het_luot = client.post(
        f"/api/vouchers/apply/{ctx['shop_id']}",
        data={"subtotal": 100000, "voucher_code": "LIMIT1D"},
    )
    assert het_luot.status_code == 400

    _huy(client, ctx, order["order_id"])

    dung_lai = client.post(
        f"/api/vouchers/apply/{ctx['shop_id']}",
        data={"subtotal": 100000, "voucher_code": "LIMIT1D"},
    )
    assert dung_lai.status_code == 200, "Hủy đơn phải giải phóng lượt voucher"


# ---------- Trạng thái không cho hủy ----------
def test_khong_huy_duoc_don_da_thanh_toan(client):
    ctx, order = _tao_don(client, quantity=3, payment_method="cash")
    client.post(f"/api/orders/{order['order_id']}/pay", headers=auth(ctx["token"]))
    ton_sau_ban = _ton_kho(ctx["product"]["id"])

    res = _huy(client, ctx, order["order_id"])
    assert res.status_code == 409
    assert STATUS_PAID in res.json()["detail"]
    assert _ton_kho(ctx["product"]["id"]) == ton_sau_ban, "Không được hoàn kho cho đơn đã bán"
    assert _trang_thai(order["order_id"]) == STATUS_PAID


def test_khong_huy_duoc_don_can_doi_soat(client, webhook_secret):
    ctx, order = _tao_don(client, quantity=3)
    order_id = order["order_id"]

    _huy(client, ctx, order_id)
    client.post(
        "/api/orders/webhook",
        json={"order_id": order_id, "amount": 300000},   # 3 x 100000
        headers={"X-Webhook-Secret": SECRET},
    )
    assert _trang_thai(order_id) == STATUS_UNRECONCILED
    ton_hien_tai = _ton_kho(ctx["product"]["id"])

    res = _huy(client, ctx, order_id)
    assert res.status_code == 409
    assert STATUS_UNRECONCILED in res.json()["detail"]
    assert _ton_kho(ctx["product"]["id"]) == ton_hien_tai, "Không hoàn kho lần hai"


# ---------- Đua giữa hủy và thanh toán ----------
def test_thanh_toan_truoc_huy_sau_khong_hoan_kho(client):
    ctx, order = _tao_don(client, quantity=5, payment_method="cash")
    client.post(f"/api/orders/{order['order_id']}/pay", headers=auth(ctx["token"]))

    assert _huy(client, ctx, order["order_id"]).status_code == 409
    assert _ton_kho(ctx["product"]["id"]) == 5


def test_huy_truoc_thanh_toan_sau_bi_tu_choi(client):
    ctx, order = _tao_don(client, quantity=5, payment_method="cash")
    _huy(client, ctx, order["order_id"])

    res = client.post(f"/api/orders/{order['order_id']}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 409
    assert _ton_kho(ctx["product"]["id"]) == 10
    assert _trang_thai(order["order_id"]) == STATUS_CANCELLED


# ---------- Quyền + contract ----------
def test_seller_khac_khong_huy_duoc_don(client):
    ctx, order = _tao_don(client, quantity=3)
    _, token_b = new_seller(client)

    res = client.post(f"/api/orders/{order['order_id']}/cancel", headers=auth(token_b))
    assert res.status_code == 403
    assert _ton_kho(ctx["product"]["id"]) == 7, "Không hoàn kho cho người không có quyền"


def test_huy_yeu_cau_dang_nhap(client):
    _, order = _tao_don(client, quantity=1)
    assert client.post(f"/api/orders/{order['order_id']}/cancel").status_code == 401


def test_huy_don_khong_ton_tai_tra_404(client):
    _, token = new_seller(client)
    assert client.post("/api/orders/999999/cancel", headers=auth(token)).status_code == 404


def test_admin_huy_duoc_don_cua_seller(client):
    from conftest import admin_token

    ctx, order = _tao_don(client, quantity=2)
    res = client.post(
        f"/api/orders/{order['order_id']}/cancel", headers=auth(admin_token(client))
    )
    assert res.status_code == 200
    assert _ton_kho(ctx["product"]["id"]) == 10


def test_admin_huy_duoc_don_mo_coi_khi_shop_da_bi_xoa(client):
    """Dữ liệu legacy có thể còn order/product sau khi shop đã bị xóa."""
    from conftest import admin_token

    ctx, order = _tao_don(client, quantity=2)
    assert _ton_kho(ctx["product"]["id"]) == 8

    session = SessionLocal()
    try:
        session.query(models.Shop).filter(models.Shop.id == ctx["shop_id"]).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()

    res = client.post(
        f"/api/orders/{order['order_id']}/cancel", headers=auth(admin_token(client))
    )
    assert res.status_code == 200, res.text
    assert res.json()["restored_items"] == 1
    assert res.json()["unrestored_items"] == 0
    assert _ton_kho(ctx["product"]["id"]) == 10
    assert _trang_thai(order["order_id"]) == STATUS_CANCELLED


def test_seller_khac_khong_huy_duoc_don_mo_coi(client):
    """Mặt bảo mật của việc admin được bỏ qua kiểm tra shop tồn tại.

    Ngoại lệ đó CHỈ dành cho ADMIN. Seller gặp đơn mồ côi vẫn phải đi qua
    require_shop_access và bị chặn - nếu không, ai cũng hủy được đơn của
    người khác chỉ cần shop đó đã bị xóa.
    """
    ctx, order = _tao_don(client, quantity=2)
    assert _ton_kho(ctx["product"]["id"]) == 8

    session = SessionLocal()
    try:
        session.query(models.Shop).filter(models.Shop.id == ctx["shop_id"]).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()

    _, token_b = new_seller(client)
    res = client.post(f"/api/orders/{order['order_id']}/cancel", headers=auth(token_b))

    assert res.status_code == 404, "Seller không được đụng vào đơn mồ côi"
    assert _ton_kho(ctx["product"]["id"]) == 8, "Không hoàn kho cho người không có quyền"
    assert _trang_thai(order["order_id"]) == STATUS_PENDING


def test_chu_shop_cu_van_huy_duoc_don_cua_minh_khi_shop_con_song(client):
    """Chốt lại: ngoại lệ cho admin không làm hỏng đường đi thường của seller."""
    ctx, order = _tao_don(client, quantity=2)
    res = _huy(client, ctx, order["order_id"])
    assert res.status_code == 200
    assert _ton_kho(ctx["product"]["id"]) == 10


def test_contract_phan_hoi_huy_don(client):
    ctx, order = _tao_don(client, quantity=1)
    body = _huy(client, ctx, order["order_id"]).json()
    assert set(body.keys()) == {
        "msg",
        "order_id",
        "restored_items",
        "unrestored_items",
        "voucher_released",
    }
    assert body["order_id"] == order["order_id"]


def test_doanh_thu_va_thong_ke_khong_tinh_don_da_huy(client):
    ctx, order = _tao_don(client, quantity=2)
    _huy(client, ctx, order["order_id"])

    stats = client.get(f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])).json()
    assert stats["total_revenue"] == 0
    assert stats["total_sold"] == 0
