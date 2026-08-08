"""L1: dự báo nhập hàng — công thức, quyền xem, và các ca dễ tính sai."""
from datetime import date, datetime, timedelta

from conftest import (
    auth,
    create_category,
    create_product,
    create_shop,
    new_seller,
    new_staff,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import forecast_service, report_service


def _du_bao(client, ctx, **params):
    chuoi = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/forecast/{ctx['shop_id']}"
    if chuoi:
        url += f"?{chuoi}"
    return client.get(url, headers=auth(ctx["token"]))


def _dong(body, product_id):
    for d in body["danh_sach"]:
        if d["product_id"] == product_id:
            return d
    raise AssertionError(f"Không thấy sản phẩm {product_id} trong danh sách")


def _ban(client, ctx, product_id, quantity, so_ngay_truoc=0):
    """Bán một đơn chuyển khoản, lùi ngày tạo về `so_ngay_truoc` ngày trước."""
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": product_id, "price": 1, "quantity": quantity}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]
    if so_ngay_truoc:
        session = SessionLocal()
        try:
            o = session.query(models.Order).filter(models.Order.id == order_id).first()
            # Trừ nguyên ngày khỏi một mốc UTC nên ngày Việt Nam lùi đúng chừng
            # ấy ngày, không phụ thuộc giờ chạy test.
            o.created_at = datetime.utcnow() - timedelta(days=so_ngay_truoc)
            session.commit()
        finally:
            session.close()
    return order_id


def _shop_ban_deu(client, ton_dau_ky, moi_ngay=2, so_ngay=30):
    """Shop bán đúng `moi_ngay` cái mỗi ngày suốt `so_ngay` — độ lệch chuẩn 0,
    nên số liệu kiểm được bằng tay không cần tra bảng."""
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    prod = create_product(
        client, token, shop_id, "Nước suối", 10000, ton_dau_ky, cat_id
    )
    ctx = {"shop_id": shop_id, "token": token, "product_id": prod["id"]}
    for i in range(so_ngay):
        _ban(client, ctx, prod["id"], moi_ngay, so_ngay_truoc=i)
    return ctx


# ---------- Múi giờ ----------
def test_moc_gio_khop_voi_report_service():
    """Hai màn phải cắt ngày ở cùng một mốc.

    Lệch nhau là màn Dự Báo và màn Thống Kê đếm hai khoảng thời gian khác nhau
    rồi đưa ra hai con số cho cùng một câu hỏi.
    """
    for ngay in (date(2026, 1, 1), date(2026, 8, 9), date(2026, 12, 31)):
        assert forecast_service._dau_ngay_vn_sang_utc(
            ngay
        ) == report_service._dau_ngay_viet_nam_sang_utc(ngay)


# ---------- Công thức ----------
def test_toc_do_ban_va_so_ngay_con_hang(client):
    ctx = _shop_ban_deu(client, ton_dau_ky=100, moi_ngay=2, so_ngay=30)
    body = _du_bao(client, ctx).json()
    d = _dong(body, ctx["product_id"])

    assert d["da_ban_trong_ky"] == 60
    assert d["ban_moi_ngay"] == 2.0
    assert d["ton_kho"] == 40
    assert d["con_ban_duoc_ngay"] == 20.0
    # Bán đều tăm tắp thì không cần đệm dự phòng.
    assert d["dem_du_phong"] == 0
    # Cần 2 x (3 + 7) = 20, đang còn 40 -> chưa phải nhập.
    assert d["can_nhap"] == 0
    assert d["trang_thai"] == forecast_service.TT_ON_DINH


def test_sap_het_thi_doi_nhap_dung_so_luong(client):
    ctx = _shop_ban_deu(client, ton_dau_ky=65, moi_ngay=2, so_ngay=30)
    body = _du_bao(client, ctx).json()
    d = _dong(body, ctx["product_id"])

    assert d["ton_kho"] == 5
    assert d["con_ban_duoc_ngay"] == 2.5
    # 2.5 ngày < 3 ngày hàng mới về -> cháy hàng trước khi hàng tới.
    assert d["trang_thai"] == forecast_service.TT_NGUY_CAP
    # 2 x (3 + 7) + 0 - 5 = 15
    assert d["can_nhap"] == 15
    assert body["so_mat_hang_can_nhap"] == 1


def test_doi_thoi_gian_dat_hang_thi_so_can_nhap_doi_theo(client):
    ctx = _shop_ban_deu(client, ton_dau_ky=65, moi_ngay=2, so_ngay=30)
    body = _du_bao(client, ctx, thoi_gian_dat_hang=10, muon_du_cho=7).json()
    d = _dong(body, ctx["product_id"])
    # 2 x (10 + 7) - 5 = 29
    assert d["can_nhap"] == 29


def test_ngay_khong_ban_duoc_gi_van_tinh_vao_mau_so(client):
    """Bán 60 cái trong 1 ngày duy nhất vẫn là 2 cái/ngày của kỳ 30 ngày.

    Bỏ qua ngày không bán là chia cho số ngày CÓ bán, và mọi sản phẩm bỗng
    thành hàng bán chạy cần nhập gấp.
    """
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    prod = create_product(client, token, shop_id, "Bánh trung thu", 50000, 100, cat_id)
    ctx = {"shop_id": shop_id, "token": token}
    _ban(client, ctx, prod["id"], 60, so_ngay_truoc=3)

    d = _dong(_du_bao(client, ctx).json(), prod["id"])
    assert d["ban_moi_ngay"] == 2.0
    assert d["so_ngay_co_ban"] == 1
    assert d["du_lieu_yeu"] is True


def test_don_da_huy_khong_tinh_la_da_ban(client):
    """Đơn hủy được hoàn tồn kho, nên hàng chưa từng rời kệ."""
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    product_id = ctx_full["product"]["id"]

    order_id = _ban(client, ctx, product_id, 4)
    truoc = _dong(_du_bao(client, ctx).json(), product_id)
    assert truoc["da_ban_trong_ky"] == 4

    res = client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text

    sau = _dong(_du_bao(client, ctx).json(), product_id)
    assert sau["da_ban_trong_ky"] == 0
    assert sau["ban_moi_ngay"] == 0
    assert sau["trang_thai"] == forecast_service.TT_KHONG_BAN


def test_san_pham_khong_ban_duoc_thi_khong_doi_nhap(client):
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    d = _dong(_du_bao(client, ctx).json(), ctx_full["product"]["id"])

    assert d["ban_moi_ngay"] == 0
    assert d["con_ban_duoc_ngay"] is None
    assert d["can_nhap"] == 0
    assert d["trang_thai"] == forecast_service.TT_KHONG_BAN


def test_het_sach_hang_ma_van_dang_ban_duoc_thi_bao_het_hang(client):
    ctx = _shop_ban_deu(client, ton_dau_ky=60, moi_ngay=2, so_ngay=30)
    d = _dong(_du_bao(client, ctx).json(), ctx["product_id"])
    assert d["ton_kho"] == 0
    assert d["trang_thai"] == forecast_service.TT_HET_HANG


# ---------- Hàng theo lô ----------
def test_hang_het_han_khong_duoc_tinh_la_con_ban_duoc(client):
    """Tồn dùng để dự báo là tồn KHẢ DỤNG, đã loại phần quá hạn (bẫy 21).

    Tính cả hàng hết hạn là báo "còn nhiều, khỏi nhập" trong khi kệ toàn hàng
    sắp phải hủy.
    """
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    prod = create_product(client, token, shop_id, "Sữa tươi", 30000, 0, cat_id)
    ctx = {"shop_id": shop_id, "token": token}

    # Lùi hẳn 3 ngày chứ không phải 1: `inventory_service._hom_nay()` so hạn
    # theo ngày UTC, nên "hôm qua" giờ Việt Nam có lúc vẫn là "hôm nay" UTC và
    # test sẽ đỏ/xanh tùy giờ chạy.
    da_het_han = (date.today() - timedelta(days=3)).isoformat()
    sang_nam = (date.today() + timedelta(days=300)).isoformat()
    session = SessionLocal()
    try:
        p = session.query(models.Product).filter(models.Product.id == prod["id"]).first()
        p.track_batches = True
        p.stock = 50  # bản sao của tổng lô, kể cả lô đã hết hạn
        session.add(
            models.ProductBatch(
                product_id=p.id, shop_id=shop_id, expiry_date=da_het_han,
                quantity=30, cost_price=20000,
            )
        )
        session.add(
            models.ProductBatch(
                product_id=p.id, shop_id=shop_id, expiry_date=sang_nam,
                quantity=20, cost_price=20000,
            )
        )
        session.commit()
    finally:
        session.close()

    d = _dong(_du_bao(client, ctx).json(), prod["id"])
    assert d["theo_lo"] is True
    assert d["ton_kho"] == 20      # chỉ phần chưa hết hạn
    assert d["ton_tong"] == 50     # tổng kể cả hàng phải hủy


# ---------- Quyền ----------
def test_shop_cua_nguoi_khac_khong_xem_duoc(client):
    chu_a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.get(
        f"/api/forecast/{chu_a['shop_id']}", headers=auth(token_b)
    )
    assert res.status_code in (403, 404), res.text


def test_chua_dang_nhap_thi_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = client.get(f"/api/forecast/{ctx['shop_id']}")
    assert res.status_code == 401


def test_thu_ngan_khong_duoc_xem_du_bao(client):
    """Thu ngân chỉ có quyền BÁN. Nhập hàng là việc của kho."""
    chu = seller_with_shop(client)
    _, token_nv = new_staff(client, chu, staff_role="CASHIER")
    res = client.get(f"/api/forecast/{chu['shop_id']}", headers=auth(token_nv))
    assert res.status_code == 403, res.text


def test_nhan_vien_kho_xem_duoc_nhung_khong_thay_gia_von(client):
    """Giá vốn bị BỎ HẲN khỏi phản hồi, không phải trả 0 (bẫy 13)."""
    chu = seller_with_shop(client)
    _, token_nv = new_staff(client, chu, staff_role="WAREHOUSE")

    res = client.get(f"/api/forecast/{chu['shop_id']}", headers=auth(token_nv))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["xem_duoc_gia_von"] is False
    assert "tong_tien_can_nhap" not in body
    for d in body["danh_sach"]:
        assert "gia_von" not in d
        assert "tien_can_bo_ra" not in d


def test_chu_shop_thay_gia_von_va_tong_tien(client):
    ctx = _shop_ban_deu(client, ton_dau_ky=65, moi_ngay=2, so_ngay=30)
    session = SessionLocal()
    try:
        p = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product_id"])
            .first()
        )
        p.cost_price = 6000
        session.commit()
    finally:
        session.close()

    body = _du_bao(client, ctx).json()
    d = _dong(body, ctx["product_id"])
    assert body["xem_duoc_gia_von"] is True
    assert d["gia_von"] == 6000
    assert d["tien_can_bo_ra"] == 15 * 6000
    assert body["tong_tien_can_nhap"] == 15 * 6000


def test_chua_khai_gia_von_thi_khong_bia_ra_so_tien(client):
    """`cost_price` NULL là "chưa ai khai", không phải 0 (bẫy 13)."""
    ctx = _shop_ban_deu(client, ton_dau_ky=65, moi_ngay=2, so_ngay=30)
    body = _du_bao(client, ctx).json()
    d = _dong(body, ctx["product_id"])

    assert d["can_nhap"] == 15
    assert d["gia_von"] is None
    assert d["tien_can_bo_ra"] is None
    assert body["tong_tien_can_nhap"] == 0
    assert body["so_mat_hang_chua_khai_gia_von"] == 1
