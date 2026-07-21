"""Regression tests cho thao tác sửa sản phẩm từ tab Kho hàng."""
import io

from conftest import (
    admin_token,
    auth,
    create_category,
    create_product,
    create_shop,
    new_seller,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _payload(ctx, **overrides):
    data = {
        "code": "SP-UPDATED",
        "name": "Sản phẩm đã sửa",
        "price": 125000,
        "stock": 17,
        "category_id": ctx["category_id"],
    }
    data.update(overrides)
    return data


def test_seller_sua_duoc_san_pham_cua_minh(client):
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]

    res = client.put(
        f"/api/products/{product_id}",
        data=_payload(ctx),
        headers=auth(ctx["token"]),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == "SP-UPDATED"
    assert body["name"] == "Sản phẩm đã sửa"
    assert body["price"] == 125000
    assert body["stock"] == 17


def test_seller_khong_sua_duoc_san_pham_shop_khac(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)

    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        headers=auth(token_b),
    )

    assert res.status_code == 403


def test_sua_san_pham_tu_choi_gia_va_ton_kho_khong_hop_le(client):
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]

    bad_price = client.put(
        f"/api/products/{product_id}",
        data=_payload(ctx, price=0),
        headers=auth(ctx["token"]),
    )
    bad_stock = client.put(
        f"/api/products/{product_id}",
        data=_payload(ctx, stock=-1),
        headers=auth(ctx["token"]),
    )

    assert bad_price.status_code == 400
    assert bad_stock.status_code == 400


def test_khong_gan_duoc_danh_muc_cua_shop_khac(client):
    """Không được mượn category_id của shop khác để lách sang dữ liệu người ta."""
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    shop_b = create_shop(client, token_b)
    cat_b = create_category(client, token_b, shop_b, name="Danh muc shop B")

    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, category_id=cat_b),
        headers=auth(ctx["token"]),
    )

    assert res.status_code == 400
    assert "Danh mục" in res.json()["detail"]


def test_khong_dat_trung_ten_voi_san_pham_khac_cung_shop(client):
    ctx = seller_with_shop(client)
    khac = create_product(
        client, ctx["token"], ctx["shop_id"], "Ten da co", 50000, 5, ctx["category_id"]
    )

    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, name="Ten da co"),
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400

    # Nhưng giữ nguyên tên của chính nó thì phải được
    giu_ten = client.put(
        f"/api/products/{khac['id']}",
        data=_payload(ctx, name="Ten da co"),
        headers=auth(ctx["token"]),
    )
    assert giu_ten.status_code == 200


def test_de_trong_ma_sp_thi_giu_ma_cu(client):
    ctx = seller_with_shop(client)
    ma_cu = ctx["product"]["code"]

    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, code=""),
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    assert res.json()["code"] == ma_cu


def test_ten_rong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, name="   "),
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_khong_upload_anh_thi_giu_anh_cu(client):
    ctx = seller_with_shop(client)
    anh_cu = ctx["product"]["image_url"]

    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    assert res.json()["image_url"] == anh_cu


def test_upload_anh_moi_khi_sua(client):
    ctx = seller_with_shop(client)
    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        files={"image": ("moi.png", io.BytesIO(PNG_BYTES), "image/png")},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    assert res.json()["image_url"].startswith("/uploads/")


def test_anh_gia_mao_bi_tu_choi_khi_sua(client):
    """save_product_image vẫn kiểm magic bytes ở đường sửa, không chỉ đường tạo."""
    ctx = seller_with_shop(client)
    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        files={"image": ("gia.png", io.BytesIO(b"<script>alert(1)</script>" * 4), "image/png")},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert "không phải ảnh" in res.json()["detail"]


def test_admin_sua_duoc_san_pham_cua_seller(client):
    ctx = seller_with_shop(client)
    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        headers=auth(admin_token(client)),
    )
    assert res.status_code == 200


def test_san_pham_khong_ton_tai_tra_404(client):
    ctx = seller_with_shop(client)
    res = client.put(
        "/api/products/999999", data=_payload(ctx), headers=auth(ctx["token"])
    )
    assert res.status_code == 404


def test_khong_doi_duoc_shop_cua_san_pham(client):
    """shop_id không nằm trong form - sản phẩm phải ở nguyên shop cũ."""
    ctx = seller_with_shop(client)
    client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        headers=auth(ctx["token"]),
    )
    session = SessionLocal()
    try:
        prod = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product"]["id"])
            .first()
        )
        assert prod.shop_id == ctx["shop_id"]
    finally:
        session.close()
