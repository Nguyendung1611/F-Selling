"""F6: biến thể sản phẩm (size/màu).

Quyết định nền của cả tính năng: **một biến thể là một dòng `Product` đầy đủ**,
không phải một bảng con. Nhờ vậy tồn kho, lô hạn, giá vốn, đơn hàng, trả hàng và
kiểm kê chạy y nguyên như trước mà không phải sửa một dòng nào - và bộ test này
canh đúng điều đó, chứ không chỉ canh hai cột mới.

Hai cột `variant_group` / `variant_name` luôn ĐI CÙNG NHAU: cả hai NULL là sản
phẩm đơn lẻ (đại đa số hàng trong tiệm), cả hai có giá trị là một biến thể.
`test_san_pham_don_le_chay_y_nhu_cu` giữ nhánh thứ nhất khỏi bị hỏng.
"""
from datetime import datetime, timedelta

from conftest import _unique, auth, create_shop, new_seller, seller_with_shop

from fselling import models
from fselling.core import bootstrap
from fselling.core.database import SessionLocal


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


def _tao(client, token, shop_id, cat_id, ten, bien_the=None, **kwargs):
    data = {
        "name": ten,
        "price": kwargs.pop("price", 50000),
        "stock": kwargs.pop("stock", 10),
        "category_id": cat_id,
    }
    if bien_the is not None:
        data["variant_name"] = bien_the
    data.update(kwargs)
    return client.post(
        "/api/products",
        params={"shop_id": shop_id},
        data=data,
        headers=auth(token),
    )


def _tao_ok(client, ctx, ten, bien_the=None, **kwargs):
    res = _tao(client, ctx["token"], ctx["shop_id"], ctx["category_id"], ten,
               bien_the, **kwargs)
    assert res.status_code == 200, res.text
    return res.json()


def _sua(client, ctx, sp, **kwargs):
    data = {
        "name": kwargs.pop("name", sp["variant_group"] or sp["name"]),
        "price": kwargs.pop("price", sp["price"]),
        "category_id": kwargs.pop("category_id", ctx["category_id"]),
    }
    data.update(kwargs)
    return client.put(
        f"/api/products/{sp['id']}", data=data, headers=auth(ctx["token"])
    )


def _danh_sach(client, ctx):
    res = client.get(
        f"/api/products/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------- Tạo biến thể ----------


def test_tao_bien_the_ghep_ten_day_du(client):
    """Ô "Tên sản phẩm" thành tên NHÓM, server ghép ra tên đầy đủ.

    Ghép ở server chứ không bắt người dùng gõ hai lần: gõ tay thì sớm muộn cũng
    có dòng lệch nhóm ("Áo thun đỏ L" trong khi nhóm là "Áo thun"), và lúc đó
    lưới POS gom sai mà không ai biết vì sai ở dữ liệu chứ không ở code.
    """
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun co tron", "Do / L")

    assert sp["name"] == "Ao thun co tron - Do / L"
    assert sp["variant_group"] == "Ao thun co tron"
    assert sp["variant_name"] == "Do / L"


def test_nhieu_bien_the_cung_nhom(client):
    ctx = seller_with_shop(client)
    do = _tao_ok(client, ctx, "Ao thun", "Do / L")
    xanh = _tao_ok(client, ctx, "Ao thun", "Xanh / M")

    assert do["variant_group"] == xanh["variant_group"] == "Ao thun"
    assert do["id"] != xanh["id"]
    ds = _danh_sach(client, ctx)
    trong_nhom = [p for p in ds if p["variant_group"] == "Ao thun"]
    assert {p["variant_name"] for p in trong_nhom} == {"Do / L", "Xanh / M"}


def test_trung_bien_the_trong_cung_nhom_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    _tao_ok(client, ctx, "Ao thun", "Do / L")

    res = _tao(client, ctx["token"], ctx["shop_id"], ctx["category_id"],
               "Ao thun", "Do / L")
    assert res.status_code == 400
    assert "đã tồn tại" in res.json()["detail"]


def test_cung_ten_bien_the_o_hai_nhom_khac_nhau_thi_duoc(client):
    """"Đỏ / L" của áo và "Đỏ / L" của quần là hai món hàng khác nhau."""
    ctx = seller_with_shop(client)
    ao = _tao_ok(client, ctx, "Ao thun", "Do / L")
    quan = _tao_ok(client, ctx, "Quan jean", "Do / L")

    assert ao["id"] != quan["id"]
    assert ao["name"] != quan["name"]


def test_hai_shop_dung_chung_ten_nhom_va_bien_the(client):
    """Ràng buộc duy nhất chỉ trong phạm vi MỘT shop, như mọi ràng buộc khác."""
    ctx = seller_with_shop(client)
    _tao_ok(client, ctx, "Ao thun", "Do / L")

    _, token2 = new_seller(client)
    shop2 = create_shop(client, token2)
    cat2 = client.post(
        "/api/categories",
        params={"name": "Danh muc B", "shop_id": shop2},
        headers=auth(token2),
    ).json()["id"]

    res = _tao(client, token2, shop2, cat2, "Ao thun", "Do / L")
    assert res.status_code == 200, res.text


def test_ten_bien_the_qua_dai_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _tao(client, ctx["token"], ctx["shop_id"], ctx["category_id"],
               "Ao thun", "X" * 101)
    assert res.status_code == 400
    assert "tối đa" in res.json()["detail"]


def test_ten_bien_the_chi_co_khoang_trang_thi_coi_nhu_khong_khai(client):
    """Ô rỗng và ô toàn dấu cách phải ra cùng một kết quả: sản phẩm đơn lẻ."""
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, _unique("Hang le"), "   ")

    assert sp["variant_group"] is None
    assert sp["variant_name"] is None
    assert " - " not in sp["name"]


# ---------- Sản phẩm đơn lẻ không được đổi hành vi ----------


def test_san_pham_don_le_chay_y_nhu_cu(client):
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, _unique("Nuoc ngot"))

    assert sp["variant_group"] is None
    assert sp["variant_name"] is None
    assert sp["name"].startswith("Nuoc ngot")


def test_nhieu_san_pham_don_le_cung_ton_tai(client):
    """Unique index (shop_id, variant_group, variant_name) không được chặn hàng
    đơn lẻ. SQLite coi mỗi NULL là một giá trị khác nhau nên chuyện này chạy
    được - nhưng nó là chỗ dễ vỡ nếu đổi sang database khác, nên phải có test."""
    ctx = seller_with_shop(client)
    for _ in range(5):
        _tao_ok(client, ctx, _unique("Le"))

    ds = _danh_sach(client, ctx)
    don_le = [p for p in ds if p["variant_group"] is None]
    assert len(don_le) >= 5


def test_form_cu_khong_gui_o_bien_the_van_tao_duoc(client):
    ctx = seller_with_shop(client)
    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("Client cu"),
            "price": 10000,
            "stock": 5,
            "category_id": ctx["category_id"],
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["variant_group"] is None


# ---------- Sửa sản phẩm ----------


def test_doi_ten_nhom_keo_theo_ten_day_du(client):
    """Đổi tên nhóm ở một biến thể phải ghép lại tên đầy đủ của chính nó.

    Không tự đổi lây sang các biến thể anh em: mỗi dòng là một sản phẩm độc lập,
    sửa hàng loạt là quyết định của người dùng chứ không phải tác dụng phụ.
    """
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun", "Do / L")
    anh_em = _tao_ok(client, ctx, "Ao thun", "Xanh / M")

    res = _sua(client, ctx, sp, name="Ao thun cao cap")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Ao thun cao cap - Do / L"
    assert body["variant_group"] == "Ao thun cao cap"
    assert body["variant_name"] == "Do / L"

    assert _sp(anh_em["id"]).variant_group == "Ao thun"


def test_doi_ten_bien_the(client):
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun", "Do / L")

    res = _sua(client, ctx, sp, variant_name="Do / XL")
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Ao thun - Do / XL"
    assert res.json()["variant_name"] == "Do / XL"


def test_go_bien_the_thi_thanh_san_pham_don_le(client):
    """Ô biến thể gửi rỗng = gỡ hẳn, không phải "giữ nguyên" (bẫy #3)."""
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun", "Do / L")

    res = _sua(client, ctx, sp, name="Ao thun bay gio ban le", variant_name="")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Ao thun bay gio ban le"
    assert body["variant_group"] is None
    assert body["variant_name"] is None


def test_go_bien_the_khong_lam_mat_ton_kho(client):
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun", "Do / L", stock=33)

    _sua(client, ctx, sp, name="Ao thun le", variant_name="")
    assert _sp(sp["id"]).stock == 33


def test_form_cu_khong_gui_o_bien_the_thi_giu_nguyen_bien_the(client):
    """Client cũ chỉ sửa giá mà làm mất biến thể là hỏng dữ liệu trong im lặng."""
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun", "Do / L")

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": "Ao thun",
            "price": 99000,
            "category_id": ctx["category_id"],
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["variant_name"] == "Do / L"
    assert body["name"] == "Ao thun - Do / L"
    assert body["price"] == 99000


def test_sua_thanh_bien_the_trung_voi_anh_em_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    _tao_ok(client, ctx, "Ao thun", "Do / L")
    khac = _tao_ok(client, ctx, "Ao thun", "Xanh / M")

    res = _sua(client, ctx, khac, variant_name="Do / L")
    assert res.status_code == 400


def test_bien_san_pham_don_le_thanh_bien_the(client):
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao khoac")

    res = _sua(client, ctx, sp, name="Ao khoac", variant_name="Den / L")
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Ao khoac - Den / L"
    assert res.json()["variant_group"] == "Ao khoac"


# ---------- Biến thể là Product đầy đủ: mọi thứ cũ phải tự đúng ----------


def test_moi_bien_the_co_ton_kho_rieng(client):
    ctx = seller_with_shop(client)
    do = _tao_ok(client, ctx, "Ao thun", "Do / L", stock=10)
    xanh = _tao_ok(client, ctx, "Ao thun", "Xanh / M", stock=7)

    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {"product_id": do["id"], "price": do["price"], "quantity": 3}
            ],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text

    assert _sp(do["id"]).stock == 7
    assert _sp(xanh["id"]).stock == 7  # không đụng tới


def test_moi_bien_the_co_ma_vach_rieng(client):
    ctx = seller_with_shop(client)
    do = _tao_ok(client, ctx, "Ao thun", "Do / L", barcode="8935001110001")
    _tao_ok(client, ctx, "Ao thun", "Xanh / M", barcode="8935001110002")

    res = client.get(
        f"/api/products/{ctx['shop_id']}/barcode/8935001110001",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == do["id"]
    assert body["variant_group"] == "Ao thun"
    assert body["variant_name"] == "Do / L"


def test_hai_bien_the_khong_dung_chung_ma_vach(client):
    ctx = seller_with_shop(client)
    _tao_ok(client, ctx, "Ao thun", "Do / L", barcode="8935001110003")

    res = _tao(client, ctx["token"], ctx["shop_id"], ctx["category_id"],
               "Ao thun", "Xanh / M", barcode="8935001110003")
    assert res.status_code == 400
    assert "Mã vạch" in res.json()["detail"]


def test_don_hang_chot_ten_day_du_kem_bien_the(client):
    """Hóa đơn phải đọc ra được là size nào - "Áo thun" trần thì đổi hàng kiểu gì."""
    ctx = seller_with_shop(client)
    sp = _tao_ok(client, ctx, "Ao thun", "Do / L")

    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {"product_id": sp["id"], "price": sp["price"], "quantity": 1}
            ],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text

    session = SessionLocal()
    try:
        dong = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.product_id == sp["id"])
            .first()
        )
        assert dong.product_name == "Ao thun - Do / L"
    finally:
        session.close()


def test_moi_bien_the_co_lo_han_rieng(client):
    """Lô gắn theo `product_id`, mà biến thể LÀ một product - nên hạn sử dụng
    tự đúng theo từng biến thể, không phải viết thêm gì."""
    ctx = seller_with_shop(client)
    som = _tao_ok(client, ctx, "Sua tuoi", "Hop 180ml", stock=0,
                  track_batches="true")
    muon = _tao_ok(client, ctx, "Sua tuoi", "Hop 1L", stock=0,
                   track_batches="true")

    han_som = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
    han_muon = (datetime.utcnow() + timedelta(days=300)).strftime("%Y-%m-%d")
    for pid, han in ((som["id"], han_som), (muon["id"], han_muon)):
        res = client.post(
            f"/api/products/{pid}/stock",
            json={"delta": 5, "expiry_date": han, "reason": "Kiểm thử nhập lô"},
            headers=auth(ctx["token"]),
        )
        assert res.status_code == 200, res.text

    session = SessionLocal()
    try:
        lo_som = (
            session.query(models.ProductBatch)
            .filter(models.ProductBatch.product_id == som["id"])
            .all()
        )
        lo_muon = (
            session.query(models.ProductBatch)
            .filter(models.ProductBatch.product_id == muon["id"])
            .all()
        )
        assert [l.expiry_date for l in lo_som] == [han_som]
        assert [l.expiry_date for l in lo_muon] == [han_muon]
    finally:
        session.close()


def test_gia_von_rieng_tung_bien_the(client):
    ctx = seller_with_shop(client)
    re = _tao_ok(client, ctx, "Ao thun", "Size S", stock=0)
    dat = _tao_ok(client, ctx, "Ao thun", "Size XXL", stock=0)

    for pid, gia in ((re["id"], 30000), (dat["id"], 45000)):
        res = client.post(
            f"/api/products/{pid}/stock",
            json={"delta": 10, "unit_cost": gia, "reason": "Kiểm thử nhập kho"},
            headers=auth(ctx["token"]),
        )
        assert res.status_code == 200, res.text

    res = client.get(
        f"/api/products/{ctx['shop_id']}/costs", headers=auth(ctx["token"])
    )
    bang = {d["product_id"]: d["cost_price"] for d in res.json()["costs"]}
    assert bang[re["id"]] == 30000
    assert bang[dat["id"]] == 45000


def test_kiem_ke_dem_tung_bien_the_rieng(client):
    ctx = seller_with_shop(client)
    a = _tao_ok(client, ctx, "Ao thun", "Size S", stock=10)
    b = _tao_ok(client, ctx, "Ao thun", "Size M", stock=10)

    res = client.post(
        f"/api/products/{ctx['shop_id']}/stocktake",
        json={
            "items": [
                {"product_id": a["id"], "counted": 8, "stock_snapshot": 10}
            ]
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert _sp(a["id"]).stock == 8
    assert _sp(b["id"]).stock == 10


# ---------- Báo cáo: top sản phẩm gộp theo nhóm ----------
#
# Không gộp thì một cái áo 4 size chiếm 4 trong 5 chỗ của bảng "bán chạy nhất",
# đẩy hết mặt hàng khác ra ngoài - càng nhiều biến thể bảng càng vô dụng.


def _ban_va_thanh_toan(client, ctx, sp, qty):
    don = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": sp["id"], "price": sp["price"], "quantity": qty}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    ).json()
    res = client.post(
        f"/api/orders/{don['order_id']}/pay", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text


def _top(client, ctx):
    res = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()["top_products"]


def test_top_san_pham_gop_cac_bien_the_thanh_mot_dong(client):
    ctx = seller_with_shop(client)
    s = _tao_ok(client, ctx, "Ao thun", "Size S", stock=100)
    m = _tao_ok(client, ctx, "Ao thun", "Size M", stock=100)
    l = _tao_ok(client, ctx, "Ao thun", "Size L", stock=100)
    _ban_va_thanh_toan(client, ctx, s, 3)
    _ban_va_thanh_toan(client, ctx, m, 4)
    _ban_va_thanh_toan(client, ctx, l, 5)

    top = _top(client, ctx)
    ao = [d for d in top if d["name"] == "Ao thun"]
    assert len(ao) == 1, "Ba size phải gộp thành MỘT dòng"
    assert ao[0]["qty"] == 12, "Tổng của cả nhóm"
    assert ao[0]["variants"] == 3


def test_hang_don_le_khong_bi_dan_nhan_so_loai(client):
    """`variants` = 0 để giao diện không ghi '(1 loại)' cho mọi món trong tiệm."""
    ctx = seller_with_shop(client)
    _ban_va_thanh_toan(client, ctx, ctx["product"], 2)

    top = _top(client, ctx)
    don_le = [d for d in top if d["name"] == ctx["product"]["name"]]
    assert len(don_le) == 1
    assert don_le[0]["variants"] == 0


def test_mot_nhom_khong_chiem_het_top_5(client):
    """Đây là lý do tồn tại của cả thay đổi này."""
    ctx = seller_with_shop(client)
    for ten in ("Size S", "Size M", "Size L", "Size XL", "Size XXL"):
        sp = _tao_ok(client, ctx, "Ao thun", ten, stock=100)
        _ban_va_thanh_toan(client, ctx, sp, 10)
    khac = _tao_ok(client, ctx, _unique("Nuoc ngot"), stock=100)
    _ban_va_thanh_toan(client, ctx, khac, 1)

    top = _top(client, ctx)
    ten_top = [d["name"] for d in top]
    assert ten_top.count("Ao thun") == 1
    assert khac["name"] in ten_top, "Mặt hàng khác vẫn phải lọt vào bảng"


def test_gop_theo_nhom_HIEN_TAI_chu_khong_theo_ten_luc_ban(client):
    """Đổi tên nhóm rồi thì báo cáo gom theo tên mới - "áo thun bán được bao
    nhiêu" là câu hỏi về danh mục hôm nay."""
    ctx = seller_with_shop(client)
    s = _tao_ok(client, ctx, "Ao thun", "Size S", stock=100)
    m = _tao_ok(client, ctx, "Ao thun", "Size M", stock=100)
    _ban_va_thanh_toan(client, ctx, s, 2)
    _ban_va_thanh_toan(client, ctx, m, 3)

    for sp in (s, m):
        res = _sua(client, ctx, sp, name="Ao thun cao cap")
        assert res.status_code == 200, res.text

    top = _top(client, ctx)
    assert [d for d in top if d["name"] == "Ao thun cao cap"][0]["qty"] == 5
    assert not [d for d in top if d["name"] == "Ao thun"]


def test_go_bien_the_thi_tach_lai_thanh_hang_don_le(client):
    ctx = seller_with_shop(client)
    s = _tao_ok(client, ctx, "Ao thun", "Size S", stock=100)
    _ban_va_thanh_toan(client, ctx, s, 4)
    _sua(client, ctx, s, name="Ao thun le", variant_name="")

    top = _top(client, ctx)
    dong = [d for d in top if d["qty"] == 4]
    assert len(dong) == 1
    assert dong[0]["variants"] == 0, "Không còn là nhóm nữa"


# ---------- Ràng buộc ở tầng database ----------


def test_unique_index_bien_the_ton_tai(client, db):
    """`run_migrations` nuốt lỗi nên index hỏng sẽ trôi qua trong im lặng
    (bẫy #4). Kiểm lại tường minh, giống cách làm với `ix_products_shop_name`."""
    assert "ux_products_shop_variant" not in bootstrap.verify_required_indexes(db)
