"""F5: lô hàng và hạn sử dụng (thuốc, đồ ăn, nguyên liệu).

Nguyên tắc xuyên suốt: với sản phẩm bật `track_batches`, **bảng lô là sự thật**
còn `Product.stock` chỉ là bản sao của tổng lô, ghi trong cùng transaction.
`test_tong_lo_luon_khop_ton_kho` canh đúng ràng buộc đó.

Sản phẩm KHÔNG bật cờ phải chạy y hệt như trước khi có F5 -
`test_san_pham_khong_bat_co_chay_y_nhu_cu` giữ điều đó.
"""
from datetime import datetime, timedelta

from conftest import _unique, auth, seller_with_shop

from fselling import models
from fselling.core import thoi_gian
from fselling.core.database import SessionLocal


def _ngay(cach_hom_nay: int) -> str:
    """Ngày cách hôm nay N ngày, tính theo NGÀY NGHIỆP VỤ Việt Nam.

    Trước đây tính bằng `datetime.utcnow()`. Trong khung 0h-7h sáng giờ Việt
    Nam, UTC vẫn còn là hôm qua, nên "lô hết hạn hôm nay" của test thực ra là lô
    đã quá hạn từ hôm qua - và `test_lo_het_han_hom_nay_van_ban_duoc` đỏ dù luật
    "hết hạn ngày hôm nay thì dùng hết ngày hôm nay" không hề đổi (bẫy 36).
    """
    return (thoi_gian.hom_nay_vn() + timedelta(days=cach_hom_nay)).isoformat()


def _sp(product_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.Product)
            .filter(models.Product.id == product_id)
            .first()
        )
    finally:
        session.close()


def _lo(product_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.ProductBatch)
            .filter(models.ProductBatch.product_id == product_id)
            .order_by(models.ProductBatch.id)
            .all()
        )
    finally:
        session.close()


def _tao_sp_theo_lo(client, ctx, gia_ban=50000, ton_dau=0):
    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("Thuoc"),
            "price": gia_ban,
            "stock": ton_dau,
            "category_id": ctx["category_id"],
            "track_batches": "true",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _nhap_lo(client, ctx, product_id, so_luong, han, gia_von=None):
    body = {
        "delta": so_luong,
        "expiry_date": han,
        "reason": "Kiểm thử nhập lô",
    }
    if gia_von is not None:
        body["unit_cost"] = gia_von
    return client.post(
        f"/api/products/{product_id}/stock", json=body, headers=auth(ctx["token"])
    )


def _ban(client, ctx, sp, qty):
    return client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": sp["id"], "price": sp["price"], "quantity": qty}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )


# ---------- Nhập kho theo lô ----------
def test_nhap_hang_phai_khai_han_su_dung(client):
    """Bật theo dõi hạn rồi mà nhập không khai hạn thì lô đó vô nghĩa."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)

    res = client.post(
        f"/api/products/{sp['id']}/stock",
        json={"delta": 10, "reason": "Kiểm thử nhập kho"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert _sp(sp["id"]).stock == 0


def test_moi_lan_nhap_tao_mot_lo_rieng(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)

    assert _nhap_lo(client, ctx, sp["id"], 10, _ngay(30)).status_code == 200
    assert _nhap_lo(client, ctx, sp["id"], 5, _ngay(90)).status_code == 200

    lo = _lo(sp["id"])
    assert [b.quantity for b in lo] == [10, 5]
    assert [b.expiry_date for b in lo] == [_ngay(30), _ngay(90)]
    assert _sp(sp["id"]).stock == 15


def test_han_sai_dinh_dang_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)

    assert _nhap_lo(client, ctx, sp["id"], 5, "31-12-2026").status_code == 400
    assert _nhap_lo(client, ctx, sp["id"], 5, "2026-02-31").status_code == 400
    assert _sp(sp["id"]).stock == 0


# ---------- Bán trừ FEFO ----------
def test_ban_tru_lo_han_gan_nhat_truoc(client):
    """Hàng cũ phải ra khỏi kệ trước, nếu không nó nằm lại tới lúc hỏng."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(90))   # lô dài hạn nhập TRƯỚC
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(10))   # lô cận hạn nhập SAU

    assert _ban(client, ctx, sp, 6).status_code == 200

    lo = {b.expiry_date: b.quantity for b in _lo(sp["id"])}
    assert lo[_ngay(10)] == 4, "Phải trừ lô cận hạn trước dù nó nhập sau"
    assert lo[_ngay(90)] == 10
    assert _sp(sp["id"]).stock == 14


def test_mot_dong_don_an_qua_nhieu_lo(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 4, _ngay(10))
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(60))

    assert _ban(client, ctx, sp, 7).status_code == 200
    lo = {b.expiry_date: b.quantity for b in _lo(sp["id"])}
    assert lo[_ngay(10)] == 0, "Lấy hết lô cận hạn"
    assert lo[_ngay(60)] == 7, "Rồi mới sang lô sau"


def test_lo_khong_han_xep_sau_cung(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(45))
    # Lô không hạn: chèn thẳng vào DB (hàng nhập trước khi bật cờ theo dõi)
    session = SessionLocal()
    try:
        session.add(
            models.ProductBatch(
                product_id=sp["id"], shop_id=ctx["shop_id"],
                expiry_date=None, quantity=5, cost_price=None,
            )
        )
        prod = session.query(models.Product).filter(
            models.Product.id == sp["id"]
        ).first()
        prod.stock = 10
        session.commit()
    finally:
        session.close()

    _ban(client, ctx, sp, 5)
    lo = {b.expiry_date: b.quantity for b in _lo(sp["id"])}
    assert lo[_ngay(45)] == 0, "Hàng CÓ hạn phải được đẩy đi trước"
    assert lo[None] == 5


# ---------- Chặn bán hàng hết hạn ----------
def test_khong_ban_duoc_lo_da_het_han(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(-1))   # hết hạn từ hôm qua

    res = _ban(client, ctx, sp, 1)
    assert res.status_code == 400
    assert _sp(sp["id"]).stock == 10, "Đơn bị chặn thì tồn không đổi"


def test_ton_kha_dung_loai_phan_qua_han(client):
    """'Còn 40 hộp' mà 12 hộp quá hạn thì chỉ bán được 28 - đây là điểm dễ gây
    thắc mắc nhất tại quầy nên thông báo phải nói rõ."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 12, _ngay(-3))    # đã hỏng
    _nhap_lo(client, ctx, sp["id"], 28, _ngay(60))    # còn tốt

    assert _sp(sp["id"]).stock == 40
    res = _ban(client, ctx, sp, 30)
    assert res.status_code == 400
    assert "28" in res.json()["detail"] and "40" in res.json()["detail"]

    assert _ban(client, ctx, sp, 28).status_code == 200


def test_lo_het_han_hom_nay_van_ban_duoc(client):
    """Hết hạn NGÀY hôm nay nghĩa là dùng hết ngày hôm nay."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(0))
    assert _ban(client, ctx, sp, 5).status_code == 200


# ---------- Giá vốn theo lô ----------
def test_gia_von_lay_tu_dung_lo_da_xuat(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(10), gia_von=20000)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(90), gia_von=30000)

    order_id = _ban(client, ctx, sp, 4).json()["order_id"]
    session = SessionLocal()
    try:
        dong = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == order_id)
            .first()
        )
        assert dong.cost_price == 20000, "Bán lô cận hạn thì lấy giá lô đó"
    finally:
        session.close()


def test_don_an_qua_hai_lo_lay_gia_von_binh_quan_phan_da_lay(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 2, _ngay(10), gia_von=10000)
    _nhap_lo(client, ctx, sp["id"], 8, _ngay(90), gia_von=20000)

    # Lấy 2 của lô 10k + 2 của lô 20k -> bình quân 15k
    order_id = _ban(client, ctx, sp, 4).json()["order_id"]
    session = SessionLocal()
    try:
        dong = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == order_id)
            .first()
        )
        assert dong.cost_price == 15000
    finally:
        session.close()


def test_lo_chua_khai_gia_von_thi_dong_don_la_null(client):
    """NULL nghĩa là 'chưa biết', không được trộn với 0."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(30))          # không khai giá
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(60), gia_von=20000)

    order_id = _ban(client, ctx, sp, 7).json()["order_id"]
    session = SessionLocal()
    try:
        dong = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == order_id)
            .first()
        )
        assert dong.cost_price is None
    finally:
        session.close()


# ---------- Hoàn kho về đúng lô ----------
def test_huy_don_hoan_ve_dung_lo_da_xuat(client):
    """Hàng quay về mang đúng hạn và đúng giá vốn của lúc nó ra đi."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(10), gia_von=10000)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(90), gia_von=20000)

    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": sp["id"], "price": sp["price"], "quantity": 7}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    lo = {b.expiry_date: b.quantity for b in _lo(sp["id"])}
    assert lo[_ngay(10)] == 0 and lo[_ngay(90)] == 3

    assert client.post(
        f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"])
    ).status_code == 200

    lo = {b.expiry_date: b.quantity for b in _lo(sp["id"])}
    assert lo[_ngay(10)] == 5, "Phần của lô cận hạn phải quay về đúng lô đó"
    assert lo[_ngay(90)] == 5
    assert _sp(sp["id"]).stock == 10


# ---------- Ràng buộc tổng lô = tồn kho ----------
def test_tong_lo_luon_khop_ton_kho(client):
    """`Product.stock` là bản sao của tổng lô. Lệch là hỏng."""
    from fselling.services import inventory_service

    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(10), gia_von=10000)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(90), gia_von=20000)
    _ban(client, ctx, sp, 12)
    client.post(
        f"/api/products/{sp['id']}/stock",
        json={"delta": -3, "reason": "Kiểm thử xuất kho"},
        headers=auth(ctx["token"]),
    )

    session = SessionLocal()
    try:
        lech = inventory_service.doi_chieu_ton_kho(session, ctx["shop_id"])
        assert lech == [], f"Tồn kho lệch với tổng lô: {lech}"
    finally:
        session.close()


def test_xuat_kho_thu_cong_cung_tru_fefo(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(10))
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(90))

    res = client.post(
        f"/api/products/{sp['id']}/stock",
        json={"delta": -6, "reason": "Kiểm thử xuất kho"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    lo = {b.expiry_date: b.quantity for b in _lo(sp["id"])}
    assert lo[_ngay(10)] == 0 and lo[_ngay(90)] == 4


# ---------- Kiểm kê ----------
def test_kiem_ke_tu_choi_so_TONG_cho_hang_theo_lo(client):
    """Hàng có lô phải đếm theo TỪNG LÔ (F6, xem tests/test_kiem_ke_lo.py).

    Gán thẳng một con số tổng là phá vỡ ràng buộc "tổng lô = tồn kho" mà không
    có cách nào biết phải cộng trừ vào lô nào. Trước F6 cả nghiệp vụ bị từ chối;
    nay chỉ riêng DẠNG dòng này bị từ chối.
    """
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))

    res = client.post(
        f"/api/products/{ctx['shop_id']}/stocktake",
        json={"items": [{"product_id": sp["id"], "counted": 8, "stock_snapshot": 10}]},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert "từng lô" in res.json()["detail"]
    assert _sp(sp["id"]).stock == 10, "Bị chặn thì dữ liệu không đổi"


# ---------- Báo cáo hạn sử dụng ----------
def test_bao_cao_chia_dung_sap_het_va_da_het_han(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 3, _ngay(-5), gia_von=10000)   # đã hỏng
    _nhap_lo(client, ctx, sp["id"], 4, _ngay(7), gia_von=10000)    # sắp hỏng
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(200), gia_von=10000)  # còn lâu

    res = client.get(
        f"/api/products/{ctx['shop_id']}/batches?days=30",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expired_quantity"] == 3
    assert body["expiring_soon_quantity"] == 4
    assert body["expired_value"] == 30000
    assert body["expiring_soon_value"] == 40000
    assert len(body["expired"]) == 1 and len(body["expiring_soon"]) == 1


def test_bao_cao_doi_duoc_so_ngay_canh_bao(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(100))

    trong_30 = client.get(
        f"/api/products/{ctx['shop_id']}/batches?days=30", headers=auth(ctx["token"])
    ).json()
    trong_365 = client.get(
        f"/api/products/{ctx['shop_id']}/batches?days=365", headers=auth(ctx["token"])
    ).json()
    assert trong_30["expiring_soon_quantity"] == 0
    assert trong_365["expiring_soon_quantity"] == 5


# ---------- Không phá hành vi cũ ----------
def test_san_pham_khong_bat_co_chay_y_nhu_cu(client):
    """Ly nhựa, túi nilon không có hạn sử dụng. Ép chúng khai lô là làm khổ
    người nhập hàng vô cớ."""
    ctx = seller_with_shop(client)   # SP mặc định KHÔNG bật cờ
    pid = ctx["product"]["id"]
    assert _sp(pid).track_batches is False

    # Nhập không cần hạn, vẫn chạy
    res = client.post(
        f"/api/products/{pid}/stock",
        json={
            "delta": 5,
            "unit_cost": 30000,
            "reason": "Kiểm thử nhập kho",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert _sp(pid).stock == 15
    assert _lo(pid) == [], "Không tạo lô nào cả"

    # Bán bình thường
    assert _ban(client, ctx, ctx["product"], 3).status_code == 200
    assert _sp(pid).stock == 12

    # Kiểm kê vẫn dùng được
    res = client.post(
        f"/api/products/{ctx['shop_id']}/stocktake",
        json={"items": [{"product_id": pid, "counted": 11, "stock_snapshot": 12}]},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert _sp(pid).stock == 11
