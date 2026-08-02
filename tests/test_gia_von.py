"""F1: giá vốn bình quân gia quyền và báo cáo lãi gộp.

Nguyên tắc xuyên suốt bộ test này: `cost_price = NULL` ("chưa ai khai") KHÔNG
BAO GIỜ được đối xử như `cost_price = 0` ("hàng tặng"). Gộp hai ca đó lại là
biến mọi sản phẩm chưa khai thành lãi bằng đúng giá bán - một con số sai theo
hướng làm người xem yên tâm, nên rất khó phát hiện.
"""
from conftest import (
    _unique,
    admin_token,
    auth,
    new_seller,
    new_staff,
    seller_with_shop,
)

from fselling import models
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


def _gia_von(product_id):
    return _sp(product_id).cost_price


def _nhap_kho(client, token, product_id, delta, unit_cost=None):
    body = {"delta": delta}
    if unit_cost is not None:
        body["unit_cost"] = unit_cost
    return client.post(
        f"/api/products/{product_id}/stock", json=body, headers=auth(token)
    )


def _tao_sp_co_gia_von(client, ctx, gia_ban, ton, gia_von, ten=None):
    """Sản phẩm có sẵn giá vốn ngay từ lúc tạo."""
    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": ten or _unique("SP"),
            "price": gia_ban,
            "stock": ton,
            "category_id": ctx["category_id"],
            "cost_price": gia_von,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _dong_hang(product, qty=1):
    """Một dòng giỏ hàng. `price` là bắt buộc theo schema nhưng server luôn
    tính lại từ database, nên con số gửi lên chỉ để cho đủ khuôn."""
    return {"product_id": product["id"], "price": product["price"], "quantity": qty}


def _dat_don(client, ctx, product, qty=1, method="cash"):
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [_dong_hang(product, qty)],
            "payment_method": method,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()["order_id"]


def _don_da_tra(client, ctx, product, qty=1):
    order_id = _dat_don(client, ctx, product, qty)
    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    return order_id


def _stats(client, ctx):
    res = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------- Khai giá vốn ----------
def test_tao_san_pham_khong_khai_thi_gia_von_la_null(client):
    ctx = seller_with_shop(client)
    assert _gia_von(ctx["product"]["id"]) is None, (
        "Không khai phải ra NULL, không phải 0 - 0 nghĩa là hàng tặng"
    )


def test_tao_san_pham_co_khai_gia_von(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=5, gia_von=30000)
    assert _gia_von(sp["id"]) == 30000


def test_gia_von_bang_0_khac_han_chua_khai(client):
    """Hàng tặng: giá vốn 0 là một con số thật và phải được lưu là 0."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=5, gia_von=0)
    assert _gia_von(sp["id"]) == 0
    assert _gia_von(sp["id"]) is not None


def test_tu_choi_gia_von_am(client):
    ctx = seller_with_shop(client)
    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("SP"),
            "price": 50000,
            "stock": 1,
            "category_id": ctx["category_id"],
            "cost_price": -1,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_sua_san_pham_khong_gui_field_thi_giu_nguyen_gia_von(client):
    """Bẫy #3: form không gửi field khác hẳn form gửi field rỗng."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=5, gia_von=30000)

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": sp["name"],
            "price": 60000,
            "category_id": ctx["category_id"],
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert _gia_von(sp["id"]) == 30000, "Không gửi cost_price = giữ nguyên"


def test_sua_san_pham_gui_rong_thi_xoa_gia_von(client):
    """Khai nhầm thì phải gỡ ra được, về đúng trạng thái 'chưa khai'."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=5, gia_von=30000)

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": sp["name"],
            "price": 60000,
            "category_id": ctx["category_id"],
            "cost_price": "",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert _gia_von(sp["id"]) is None


def test_sua_gia_von_bang_chu_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=5, gia_von=30000)
    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": sp["name"],
            "price": 60000,
            "category_id": ctx["category_id"],
            "cost_price": "ba mươi nghìn",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert _gia_von(sp["id"]) == 30000, "Lỗi parse không được làm hỏng dữ liệu cũ"


# ---------- Bình quân gia quyền ----------
def test_nhap_kho_tinh_binh_quan_gia_quyen(client):
    """10 cái giá 30k + 10 cái giá 40k = 20 cái giá 35k."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = _nhap_kho(client, ctx["token"], sp["id"], 10, unit_cost=40000)
    assert res.status_code == 200, res.text
    assert _gia_von(sp["id"]) == 35000
    assert _sp(sp["id"]).stock == 20


def test_binh_quan_theo_ty_trong_so_luong(client):
    """30 cái giá 10k + 10 cái giá 20k = 40 cái giá 12.5k (không phải 15k)."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=30, gia_von=10000)

    _nhap_kho(client, ctx["token"], sp["id"], 10, unit_cost=20000)
    assert _gia_von(sp["id"]) == 12500, (
        "Phải là bình quân GIA QUYỀN theo số lượng, không phải trung bình cộng"
    )


def test_chua_khai_gia_von_thi_lan_nhap_dau_lay_luon_don_gia(client):
    ctx = seller_with_shop(client)  # tồn 10, chưa khai giá vốn
    pid = ctx["product"]["id"]

    _nhap_kho(client, ctx["token"], pid, 5, unit_cost=20000)
    assert _gia_von(pid) == 20000, (
        "Không có giá vốn cũ thì không có gì để bình quân - lấy luôn đơn giá. "
        "Coi giá vốn cũ là 0 sẽ ra 6.666đ, thấp hơn thực tế."
    )


def test_kho_dang_trong_thi_lay_luon_don_gia(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=0, gia_von=30000)

    _nhap_kho(client, ctx["token"], sp["id"], 10, unit_cost=40000)
    assert _gia_von(sp["id"]) == 40000, (
        "Tồn 0 thì giá vốn cũ không còn đại diện cho hàng nào cả"
    )


def test_nhap_hang_tang_gia_0_keo_binh_quan_xuong(client):
    """10 cái giá 30k + 10 cái tặng = 20 cái giá 15k."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = _nhap_kho(client, ctx["token"], sp["id"], 10, unit_cost=0)
    assert res.status_code == 200, res.text
    assert _gia_von(sp["id"]) == 15000, (
        "unit_cost = 0 là đơn giá thật của hàng tặng, không phải 'không khai'"
    )


def test_nhap_kho_khong_gui_don_gia_thi_giu_nguyen_gia_von(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    _nhap_kho(client, ctx["token"], sp["id"], 10)
    assert _gia_von(sp["id"]) == 30000
    assert _sp(sp["id"]).stock == 20


def test_xuat_kho_khong_doi_gia_von(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    _nhap_kho(client, ctx["token"], sp["id"], -4)
    assert _gia_von(sp["id"]) == 30000, (
        "Xuất hàng đi không làm đổi đơn giá bình quân của số còn lại"
    )
    assert _sp(sp["id"]).stock == 6


def test_phieu_xuat_kem_don_gia_bi_tu_choi(client):
    """Từ chối thẳng thay vì im lặng bỏ qua: im lặng để người dùng tin rằng
    giá vốn vừa được cập nhật."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = _nhap_kho(client, ctx["token"], sp["id"], -2, unit_cost=40000)
    assert res.status_code == 400
    assert _gia_von(sp["id"]) == 30000
    assert _sp(sp["id"]).stock == 10, "Phiếu bị từ chối thì tồn kho cũng không đổi"


def test_don_gia_am_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = _nhap_kho(client, ctx["token"], sp["id"], 5, unit_cost=-1000)
    assert res.status_code == 400
    assert _sp(sp["id"]).stock == 10


def test_kiem_ke_khong_doi_gia_von(client):
    """Kiểm kê chỉ đặt lại SỐ LƯỢNG. Hàng thừa/thiếu quy ra tiền theo giá vốn
    hiện hành, chứ bản thân đơn giá không có lý do gì để đổi."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = client.post(
        f"/api/products/{ctx['shop_id']}/stocktake",
        json={
            "items": [
                {"product_id": sp["id"], "counted": 7, "stock_snapshot": 10}
            ]
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert _sp(sp["id"]).stock == 7
    assert _gia_von(sp["id"]) == 30000


# ---------- Chốt giá vốn lúc bán ----------
def _dong_don(order_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == order_id)
            .all()
        )
    finally:
        session.close()


def test_don_hang_chup_lai_gia_von_luc_ban(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    order_id = _dat_don(client, ctx, sp, qty=2)

    dong = _dong_don(order_id)
    assert len(dong) == 1
    assert dong[0].cost_price == 30000


def test_nhap_lo_moi_khong_lam_doi_lai_cua_don_da_ban(client):
    """Điểm quan trọng nhất của cả tính năng: tra ngược Product.cost_price lúc
    làm báo cáo thì mỗi lần nhập lô giá khác là lãi các tháng trước tự đổi số."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    order_id = _dat_don(client, ctx, sp, qty=1)

    _nhap_kho(client, ctx["token"], sp["id"], 90, unit_cost=45000)

    assert _dong_don(order_id)[0].cost_price == 30000, (
        "Giá vốn trên đơn đã bán là ảnh chụp, không được đổi theo lô nhập sau"
    )
    assert _gia_von(sp["id"]) != 30000, "Giá vốn hiện hành thì có đổi"


def test_ban_san_pham_chua_khai_gia_von_thi_dong_don_la_null(client):
    ctx = seller_with_shop(client)
    order_id = _dat_don(client, ctx, ctx["product"], qty=1)
    assert _dong_don(order_id)[0].cost_price is None


def test_huy_don_khong_lam_lech_gia_von_binh_quan(client):
    """Hoàn tồn kho cộng trả đúng số lượng đã trừ, mà số đó ra đi với đúng giá
    vốn đã chốt - nên bình quân tự khớp lại. Chạy lại công thức bình quân lúc
    hoàn mới là cái làm lệch."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    order_id = _dat_don(client, ctx, sp, qty=4)
    assert _sp(sp["id"]).stock == 6

    res = client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    assert _sp(sp["id"]).stock == 10
    assert _gia_von(sp["id"]) == 30000


# ---------- Báo cáo lãi gộp ----------
def test_lai_gop_bang_doanh_thu_tru_gia_von(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    _don_da_tra(client, ctx, sp, qty=2)

    stats = _stats(client, ctx)
    assert stats["total_revenue"] == 100000
    assert stats["total_cost"] == 60000
    assert stats["gross_profit"] == 40000
    assert stats["gross_margin"] == 40.0
    assert stats["orders_missing_cost"] == 0


def test_don_thieu_gia_von_bi_loai_khoi_lai_va_duoc_dem_rieng(client):
    """Loại nửa vời - trừ giá vốn đã biết ra khỏi TOÀN BỘ doanh thu - sẽ ĐẨY
    LÃI LÊN đúng bằng phần chưa khai. Phải loại nguyên đơn và nói ra."""
    ctx = seller_with_shop(client)
    co_gia_von = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    _don_da_tra(client, ctx, co_gia_von, qty=2)          # 100k, vốn 60k
    _don_da_tra(client, ctx, ctx["product"], qty=1)      # 100k, chưa khai

    stats = _stats(client, ctx)
    assert stats["total_revenue"] == 200000, "Doanh thu vẫn tính đủ mọi đơn"
    assert stats["revenue_with_cost"] == 100000
    assert stats["gross_profit"] == 40000, (
        "Không được ra 140.000 - đó là doanh thu cả hai đơn trừ giá vốn một đơn"
    )
    assert stats["orders_missing_cost"] == 1
    assert stats["revenue_missing_cost"] == 100000


def test_don_lan_lon_thieu_mot_dong_thi_loai_ca_don(client):
    ctx = seller_with_shop(client)
    co_gia_von = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                _dong_hang(co_gia_von),
                _dong_hang(ctx["product"]),
            ],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))

    stats = _stats(client, ctx)
    assert stats["orders_missing_cost"] == 1
    assert stats["gross_profit"] == 0
    assert stats["revenue_with_cost"] == 0


def test_hang_tang_van_tinh_duoc_lai(client):
    """Giá vốn 0 phải cho ra lãi bằng cả giá bán - và ĐƯỢC tính, khác hẳn với
    đơn chưa khai giá vốn (bị loại)."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=0)
    _don_da_tra(client, ctx, sp, qty=1)

    stats = _stats(client, ctx)
    assert stats["gross_profit"] == 50000
    assert stats["orders_missing_cost"] == 0


def test_don_chua_thanh_toan_khong_tinh_vao_lai(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    _dat_don(client, ctx, sp, qty=2, method="transfer")   # PENDING

    stats = _stats(client, ctx)
    assert stats["gross_profit"] == 0
    assert stats["orders_missing_cost"] == 0


def test_khong_co_don_nao_thi_ty_suat_la_none(client):
    """Doanh thu 0 thì tỷ suất không xác định, không phải 0%."""
    ctx = seller_with_shop(client)
    stats = _stats(client, ctx)
    assert stats["gross_profit"] == 0
    assert stats["gross_margin"] is None


def test_lai_gop_tru_giam_gia_voucher(client):
    """Giảm giá trừ ở mức đơn hàng, nên nó ăn thẳng vào lãi."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    res = client.post(
        "/api/vouchers",
        params={"shop_id": ctx["shop_id"]},
        json={"code": "GIAM10", "discount_type": "percentage", "discount_value": 10},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text

    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [_dong_hang(sp, 2)],
            "payment_method": "cash",
            "voucher_code": "GIAM10",
        },
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))

    stats = _stats(client, ctx)
    assert stats["total_revenue"] == 90000, "100k - 10%"
    assert stats["total_cost"] == 60000
    assert stats["gross_profit"] == 30000, "Giảm giá ăn thẳng vào lãi"


# ---------- Quyền xem ----------
def test_nhan_vien_manager_khong_thay_lai(client):
    """MANAGER có PERMISSION_REPORT nên vẫn xem doanh thu, nhưng biết lãi là
    suy ra được giá vốn."""
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx, staff_role="MANAGER")

    res = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(staff_token)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "total_revenue" in body
    for khoa in (
        "gross_profit",
        "gross_margin",
        "total_cost",
        "revenue_with_cost",
        "orders_missing_cost",
        "revenue_missing_cost",
    ):
        assert khoa not in body, (
            f"'{khoa}' phải BỎ HẲN khỏi phản hồi, không được trả 0 - "
            "lãi bằng 0 là một con số có nghĩa"
        )


def test_nhan_vien_khong_goi_duoc_endpoint_gia_von(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx, staff_role="MANAGER")

    res = client.get(
        f"/api/products/{ctx['shop_id']}/costs", headers=auth(staff_token)
    )
    assert res.status_code == 403


def test_danh_sach_san_pham_khong_lo_gia_von(client):
    """GET /api/products/{shop_id} đã có xác thực từ F6, nhưng NHÂN VIÊN vẫn đọc
    được nó - còn giá vốn thì không. Giá vốn lọt vào đây là mọi thu ngân đều
    xem được qua chính lưới hàng của POS."""
    ctx = seller_with_shop(client)
    _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    _, staff_token = new_staff(client, ctx, staff_role="CASHIER")

    res = client.get(f"/api/products/{ctx['shop_id']}", headers=auth(staff_token))
    assert res.status_code == 200
    for sp in res.json():
        assert "cost_price" not in sp


def test_chu_shop_xem_duoc_gia_von(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = client.get(
        f"/api/products/{ctx['shop_id']}/costs", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    body = res.json()
    bang = {d["product_id"]: d["cost_price"] for d in body["costs"]}
    assert bang[sp["id"]] == 30000
    assert bang[ctx["product"]["id"]] is None
    assert body["chua_khai"] == 1


def test_admin_xem_duoc_gia_von(client):
    ctx = seller_with_shop(client)
    _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)

    res = client.get(
        f"/api/products/{ctx['shop_id']}/costs",
        headers=auth(admin_token(client)),
    )
    assert res.status_code == 200, res.text


def test_seller_khac_khong_xem_duoc_gia_von_shop_nguoi_ta(client):
    ctx = seller_with_shop(client)
    _, token_khac = new_seller(client)

    res = client.get(
        f"/api/products/{ctx['shop_id']}/costs", headers=auth(token_khac)
    )
    assert res.status_code == 403


def test_nhan_vien_kho_van_nhap_kho_duoc_nhung_khong_dat_duoc_gia_von(client):
    """Nhân viên kho vẫn làm việc bình thường, chỉ là không đụng vào giá vốn."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    _, staff_token = new_staff(client, ctx, staff_role="WAREHOUSE")

    res = _nhap_kho(client, staff_token, sp["id"], 5)
    assert res.status_code == 200, res.text
    assert _sp(sp["id"]).stock == 15
    assert "cost_price" not in res.json()

    res = _nhap_kho(client, staff_token, sp["id"], 5, unit_cost=99000)
    assert res.status_code == 403
    assert _gia_von(sp["id"]) == 30000
    assert _sp(sp["id"]).stock == 15, "Bị từ chối thì tồn kho cũng không đổi"


def test_nhan_vien_kho_sua_san_pham_khong_bi_chan(client):
    """Nhân viên kho sửa tên/giá bán mà không gửi cost_price thì phải đi lọt -
    chặn ở đây là hỏng luôn việc sửa sản phẩm của họ."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_co_gia_von(client, ctx, gia_ban=50000, ton=10, gia_von=30000)
    _, staff_token = new_staff(client, ctx, staff_role="WAREHOUSE")

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": sp["name"],
            "price": 55000,
            "category_id": ctx["category_id"],
        },
        headers=auth(staff_token),
    )
    assert res.status_code == 200, res.text
    assert _gia_von(sp["id"]) == 30000
