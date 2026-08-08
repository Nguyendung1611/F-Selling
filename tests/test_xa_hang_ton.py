"""L2: xả hàng tồn — quét hàng chôn vốn và đề xuất giá bán mới.

Luật xuyên suốt: **giá đề xuất không bao giờ dưới giá vốn**. Máy dừng ở hòa
vốn; bán lỗ để cắt lỗ là quyết định của chủ shop, không phải của công thức.
"""
from datetime import datetime, timedelta

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
from fselling.core import thoi_gian
from fselling.core.database import SessionLocal
from fselling.services import clearance_service


def _xa_hang(client, ctx, **params):
    chuoi = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/clearance/{ctx['shop_id']}"
    if chuoi:
        url += f"?{chuoi}"
    return client.get(url, headers=auth(ctx["token"]))


def _dong(body, product_id):
    for d in body["danh_sach"]:
        if d["product_id"] == product_id:
            return d
    return None


def _dat_gia_von(product_id, gia_von):
    session = SessionLocal()
    try:
        p = session.query(models.Product).filter(models.Product.id == product_id).first()
        p.cost_price = gia_von
        session.commit()
    finally:
        session.close()


def _ban_cach_day(client, ctx, product_id, so_ngay_truoc):
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": product_id, "price": 1, "quantity": 1}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    session = SessionLocal()
    try:
        o = session.query(models.Order).filter(
            models.Order.id == res.json()["order_id"]
        ).first()
        o.created_at = datetime.utcnow() - timedelta(days=so_ngay_truoc)
        session.commit()
    finally:
        session.close()


def _shop_co_hang(client, gia_ban, gia_von, ton=20):
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    prod = create_product(client, token, shop_id, "Áo thun tồn", gia_ban, ton, cat_id)
    _dat_gia_von(prod["id"], gia_von)
    return {"shop_id": shop_id, "token": token, "product_id": prod["id"]}


# ---------- Phát hiện ----------
def test_hang_chua_ban_lan_nao_bi_coi_la_nam_e(client):
    ctx = _shop_co_hang(client, 100_000, 60_000)
    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])

    assert d is not None
    assert d["ly_do"] == clearance_service.LY_DO_E
    assert d["so_ngay_khong_ban"] is None
    assert d["ngay_ban_gan_nhat"] is None
    assert d["von_dang_dong"] == 60_000 * 20


def test_hang_moi_ban_hom_qua_khong_bi_goi_la_e(client):
    ctx = _shop_co_hang(client, 100_000, 60_000)
    _ban_cach_day(client, ctx, ctx["product_id"], 1)

    body = _xa_hang(client, ctx).json()
    assert _dong(body, ctx["product_id"]) is None
    assert body["so_mat_hang"] == 0


def test_qua_nguong_ngay_moi_bi_goi_la_e(client):
    ctx = _shop_co_hang(client, 100_000, 60_000)
    _ban_cach_day(client, ctx, ctx["product_id"], 50)

    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])
    assert d["so_ngay_khong_ban"] == 50
    assert d["ly_do"] == clearance_service.LY_DO_E

    # Nới ngưỡng lên 60 ngày thì món này chưa bị coi là ế nữa.
    body = _xa_hang(client, ctx, so_ngay_coi_la_e=60).json()
    assert _dong(body, ctx["product_id"]) is None


def test_het_sach_hang_thi_khong_co_gi_de_xa(client):
    ctx = _shop_co_hang(client, 100_000, 60_000, ton=0)
    assert _xa_hang(client, ctx).json()["so_mat_hang"] == 0


# ---------- Giá đề xuất ----------
def test_gia_de_xuat_nhuong_mot_nua_phan_lai(client):
    """Hàng chỉ nằm ế (không vướng hạn): nhường 50% phần lãi."""
    ctx = _shop_co_hang(client, 100_000, 60_000)
    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])

    # Lãi 40.000, nhường một nửa -> 80.000
    assert d["gia_de_xuat"] == 80_000
    assert d["giam_phan_tram"] == 20.0
    assert d["lai_moi_cai_sau_giam"] == 20_000
    assert d["tien_thu_ve_du_kien"] == 80_000 * 20


def test_gia_de_xuat_khong_bao_gio_duoi_gia_von(client):
    """Biên lãi mỏng + làm tròn là ca dễ chui xuống dưới giá vốn nhất."""
    for gia_ban, gia_von in ((2_000, 1_900), (10_500, 10_000), (1_000_000, 999_000)):
        ctx = _shop_co_hang(client, gia_ban, gia_von)
        d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])
        assert d["gia_de_xuat"] >= gia_von, (gia_ban, gia_von, d["gia_de_xuat"])
        assert d["gia_de_xuat"] <= gia_ban, (gia_ban, gia_von, d["gia_de_xuat"])
        assert d["lai_moi_cai_sau_giam"] >= 0


def test_chua_khai_gia_von_thi_khong_doan_gia(client):
    """Giá vốn NULL không được coi là 0 - coi là 0 thì bán 1 đồng cũng "lãi"."""
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    prod = create_product(client, token, shop_id, "Hàng chưa khai vốn", 50_000, 10, cat_id)
    ctx = {"shop_id": shop_id, "token": token}

    body = _xa_hang(client, ctx).json()
    d = _dong(body, prod["id"])
    assert d["gia_de_xuat"] is None
    assert d["khong_tinh_duoc"] == "CHUA_KHAI_GIA_VON"
    assert d["von_dang_dong"] is None
    assert body["so_mat_hang_chua_khai_gia_von"] == 1
    assert body["tong_von_dang_dong"] == 0


def test_dang_ban_lo_thi_noi_thang_chu_khong_de_xuat_giam_them(client):
    ctx = _shop_co_hang(client, 50_000, 60_000)
    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])

    assert d["gia_de_xuat"] is None
    assert d["khong_tinh_duoc"] == "DANG_BAN_KHONG_LAI"


# ---------- Hạn sử dụng ----------
def _them_lo(product_id, shop_id, so_ngay_nua, so_luong=10, gia_von=60_000):
    """Thêm một lô có hạn. `gia_von=None` = lô chưa khai giá."""
    han = (thoi_gian.hom_nay_vn() + timedelta(days=so_ngay_nua)).isoformat()
    session = SessionLocal()
    try:
        p = session.query(models.Product).filter(models.Product.id == product_id).first()
        p.track_batches = True
        p.stock = (p.stock or 0) + so_luong
        session.add(
            models.ProductBatch(
                product_id=product_id, shop_id=shop_id, expiry_date=han,
                quantity=so_luong, cost_price=gia_von,
            )
        )
        session.commit()
    finally:
        session.close()
    return han


def test_hang_theo_lo_lay_gia_von_tu_lo_chu_khong_tu_san_pham(client):
    """Bẫy 21: hàng theo lô giữ giá vốn ở TỪNG LÔ, `Product.cost_price` là NULL.

    Đọc nhầm chỗ thì cả màn hình báo "chưa khai giá vốn" trong khi phiếu nhập
    ghi giá đầy đủ - và chủ shop mất luôn tính năng mà không hiểu vì sao.
    """
    ctx = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _dat_gia_von(ctx["product_id"], None)          # sản phẩm KHÔNG khai giá vốn
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=10, so_luong=10, gia_von=60_000)

    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])
    assert d["gia_von"] == 60_000
    assert d.get("khong_tinh_duoc") is None
    assert d["gia_de_xuat"] is not None


def test_nhieu_lo_khac_gia_thi_lay_binh_quan_gia_quyen(client):
    ctx = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _dat_gia_von(ctx["product_id"], None)
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=10, so_luong=10, gia_von=50_000)
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=20, so_luong=30, gia_von=70_000)

    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])
    # (50.000 x 10 + 70.000 x 30) / 40 = 65.000
    assert d["gia_von"] == 65_000
    assert d["gia_de_xuat"] >= 65_000


def test_mot_lo_chua_khai_gia_thi_khong_binh_quan_bua(client):
    """Trộn lô chưa khai với lô đã khai là kéo bình quân xuống dưới sự thật rồi
    đề xuất một mức giá đang lỗ mà nhìn vẫn có lãi."""
    ctx = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _dat_gia_von(ctx["product_id"], None)
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=10, so_luong=10, gia_von=70_000)
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=20, so_luong=10, gia_von=None)

    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])
    assert d["gia_von"] is None
    assert d["khong_tinh_duoc"] == "CHUA_KHAI_GIA_VON"


def test_sap_het_han_thi_bi_goi_ra_du_dang_ban_tot(client):
    ctx = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=5)
    _ban_cach_day(client, ctx, ctx["product_id"], 1)      # hôm qua vẫn bán được

    d = _dong(_xa_hang(client, ctx).json(), ctx["product_id"])
    assert d is not None, "hàng sắp hỏng phải bị gọi ra dù đang bán chạy"
    assert d["ly_do"] == clearance_service.LY_DO_SAP_HET_HAN
    assert d["so_ngay_con_han"] == 5


def test_cang_sat_han_cang_nhuong_nhieu_lai_hon(client):
    ctx_xa = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _them_lo(ctx_xa["product_id"], ctx_xa["shop_id"], so_ngay_nua=30)
    gia_con_lau = _dong(_xa_hang(client, ctx_xa).json(), ctx_xa["product_id"])["gia_de_xuat"]

    ctx_gan = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _them_lo(ctx_gan["product_id"], ctx_gan["shop_id"], so_ngay_nua=2)
    gia_sat_han = _dong(_xa_hang(client, ctx_gan).json(), ctx_gan["product_id"])["gia_de_xuat"]

    assert gia_sat_han < gia_con_lau
    assert gia_sat_han >= 60_000      # vẫn không dưới giá vốn


def test_hang_da_het_han_dem_rieng_de_di_huy_khong_phai_de_ban(client):
    ctx = _shop_co_hang(client, 100_000, 60_000, ton=0)
    _them_lo(ctx["product_id"], ctx["shop_id"], so_ngay_nua=-3, so_luong=7)

    body = _xa_hang(client, ctx).json()
    d = _dong(body, ctx["product_id"])
    assert d["so_luong_da_het_han"] == 7
    assert d["ton_kho"] == 0          # hàng hỏng không nằm trong tồn bán được
    assert body["so_luong_can_huy"] == 7


# ---------- Quyền ----------
def test_shop_cua_nguoi_khac_khong_xem_duoc(client):
    chu_a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.get(f"/api/clearance/{chu_a['shop_id']}", headers=auth(token_b))
    assert res.status_code in (403, 404), res.text


def test_chua_dang_nhap_thi_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    assert client.get(f"/api/clearance/{ctx['shop_id']}").status_code == 401


def test_moi_nhan_vien_deu_bi_chan_ke_ca_quan_ly(client):
    """Cả màn hình dựng từ giá vốn nên không che nửa vời được: cho xem mức giảm
    là cho suy ngược ra giá vốn."""
    chu = seller_with_shop(client)
    for vai_tro in ("CASHIER", "WAREHOUSE", "MANAGER"):
        _, token_nv = new_staff(client, chu, staff_role=vai_tro)
        res = client.get(f"/api/clearance/{chu['shop_id']}", headers=auth(token_nv))
        assert res.status_code == 403, (vai_tro, res.text)
