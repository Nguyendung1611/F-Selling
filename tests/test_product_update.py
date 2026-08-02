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
    ton_ban_dau = ctx["product"]["stock"]

    res = client.put(
        f"/api/products/{product_id}",
        data=_payload(ctx),  # payload có gửi stock=17
        headers=auth(ctx["token"]),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == "SP-UPDATED"
    assert body["name"] == "Sản phẩm đã sửa"
    assert body["price"] == 125000
    # Sửa sản phẩm KHÔNG được đụng tồn kho, dù form có gửi stock khác đi.
    assert body["stock"] == ton_ban_dau


def test_sua_san_pham_khong_ghi_de_ton_kho(client):
    """Bug đã sửa: seller mở form (tồn 10), POS bán bớt, seller Lưu -> không
    được kéo tồn về giá trị cũ trong form."""
    ctx = seller_with_shop(client)  # tồn 10
    product_id = ctx["product"]["id"]

    # Bán 4 -> tồn còn 6
    client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 4}]},
        headers=auth(ctx["token"]),
    )

    # Seller lưu form với stock=10 (giá trị cũ trong form)
    res = client.put(
        f"/api/products/{product_id}",
        data=_payload(ctx, stock=10),
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    assert res.json()["stock"] == 6, "Tồn kho phải giữ giá trị thật, không bị form ghi đè"


def test_seller_khong_sua_duoc_san_pham_shop_khac(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)

    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx),
        headers=auth(token_b),
    )

    assert res.status_code == 403


def test_sua_san_pham_tu_choi_gia_khong_hop_le(client):
    ctx = seller_with_shop(client)
    bad_price = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, price=0),
        headers=auth(ctx["token"]),
    )
    assert bad_price.status_code == 400


def test_sua_san_pham_bo_qua_stock_trong_form(client):
    """PUT không còn validate/áp dụng stock: giá trị stock trong form bị bỏ qua,
    không gây lỗi và không làm đổi tồn kho. Tồn kho đổi qua /stock (đã test riêng)."""
    ctx = seller_with_shop(client)  # tồn 10
    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, stock=-1),  # stock vô lý nhưng bị bỏ qua
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    assert res.json()["stock"] == 10, "Tồn kho không đổi và không nhận giá trị âm từ form"


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


def test_khong_gan_duoc_danh_muc_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    res = client.put(
        f"/api/products/{ctx['product']['id']}",
        data=_payload(ctx, category_id=999999),
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert "Danh mục" in res.json()["detail"]


# ---------- Cùng phép kiểm đó, nhưng lúc TẠO sản phẩm ----------
#
# `update_product` kiểm danh mục từ lâu, `create_product` thì không - đoán
# `category_id` là gắn được sản phẩm của mình vào danh mục của cửa hàng khác, và
# từ đó lưới POS lọc theo danh mục hiện ra một món không thuộc danh mục nào
# người dùng nhìn thấy được.


def _tao_sp(client, token, shop_id, cat_id, ten="SP moi"):
    return client.post(
        "/api/products",
        params={"shop_id": shop_id},
        data={"name": ten, "price": 50000, "stock": 5, "category_id": cat_id},
        headers=auth(token),
    )


def test_tao_sp_khong_gan_duoc_danh_muc_cua_shop_khac(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    shop_b = create_shop(client, token_b)
    cat_b = create_category(client, token_b, shop_b, name="Danh muc shop B")

    res = _tao_sp(client, ctx["token"], ctx["shop_id"], cat_b)

    assert res.status_code == 400
    assert "Danh mục" in res.json()["detail"]


def test_tao_sp_khong_gan_duoc_danh_muc_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(client, ctx["token"], ctx["shop_id"], 999999)
    assert res.status_code == 400
    assert "Danh mục" in res.json()["detail"]


def test_tao_sp_that_bai_thi_khong_de_lai_san_pham_nao(client):
    """Từ chối phải xảy ra TRƯỚC khi tạo dòng Product, nếu không mã tự sinh đã
    tiêu tốn một id và có thể còn sót bản ghi dở."""
    ctx = seller_with_shop(client)
    truoc = len(
        client.get(
            f"/api/products/{ctx['shop_id']}", headers=auth(ctx["token"])
        ).json()
    )

    _tao_sp(client, ctx["token"], ctx["shop_id"], 999999, ten="SP hong")

    sau = client.get(
        f"/api/products/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    assert len(sau) == truoc
    assert all(p["name"] != "SP hong" for p in sau)


def test_tao_sp_voi_danh_muc_dung_shop_van_chay(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"],
                  ten="SP hop le")
    assert res.status_code == 200, res.text
    assert res.json()["category_id"] == ctx["category_id"]


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
