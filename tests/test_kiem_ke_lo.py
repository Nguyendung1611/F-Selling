"""F6: kiểm kê theo từng lô, cho sản phẩm có theo dõi hạn sử dụng.

Trước F6 `apply_stocktake` từ chối thẳng hàng theo lô: nó gán `prod.stock =
counted`, và làm vậy với hàng có lô là phá vỡ ràng buộc "tổng lô = tồn kho" mà
không có cách nào biết phải cộng trừ vào lô nào.

Ba nguyên tắc an toàn của kiểm kê được giữ nguyên, chỉ hạ xuống mức LÔ. Bất biến
phải giữ sau mọi test ở đây: `sum(product_batches.quantity) == Product.stock`,
kiểm bằng chính `inventory_service.doi_chieu_ton_kho()`.
"""
from datetime import datetime, timedelta

from conftest import _unique, auth, new_seller, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import inventory_service


def _ngay(cach_hom_nay: int) -> str:
    return (datetime.utcnow() + timedelta(days=cach_hom_nay)).strftime("%Y-%m-%d")


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


def _khong_lech(shop_id):
    """Bất biến tổng lô = tồn kho. Dùng chính hàm đối chiếu của hệ thống."""
    session = SessionLocal()
    try:
        return inventory_service.doi_chieu_ton_kho(session, shop_id) == []
    finally:
        session.close()


def _tao_sp_theo_lo(client, ctx, ton_dau=0):
    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("Sua hop"),
            "price": 25000,
            "stock": ton_dau,
            "category_id": ctx["category_id"],
            "track_batches": "true",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _nhap_lo(client, ctx, product_id, so_luong, han, gia_von=None):
    body = {"delta": so_luong, "expiry_date": han}
    if gia_von is not None:
        body["unit_cost"] = gia_von
    res = client.post(
        f"/api/products/{product_id}/stock", json=body, headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()


def _kiem_ke(client, token, shop_id, items):
    return client.post(
        f"/api/products/{shop_id}/stocktake",
        json={"items": items},
        headers=auth(token),
    )


def _dong_lo(client, ctx, sp, dem_theo_lo):
    """Dựng dòng kiểm kê từ {chi_so_lo: so_dem}, snapshot lấy đúng số hiện tại."""
    lo = _lo(sp["id"])
    return {
        "product_id": sp["id"],
        "batches": [
            {
                "batch_id": lo[i].id,
                "counted": so,
                "quantity_snapshot": lo[i].quantity,
            }
            for i, so in dem_theo_lo.items()
        ],
    }


# ---------- Đếm theo lô ----------


def test_dem_thieu_mot_lo(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(90))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"],
                   [_dong_lo(client, ctx, sp, {0: 8})])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tong_lech"] == -2
    assert body["da_dieu_chinh"][0]["batch_id"] == _lo(sp["id"])[0].id

    lo = _lo(sp["id"])
    assert [b.quantity for b in lo] == [8, 5]
    assert _sp(sp["id"]).stock == 13
    assert _khong_lech(ctx["shop_id"])


def test_dem_nhieu_lo_cung_luc(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(10))
    _nhap_lo(client, ctx, sp["id"], 20, _ngay(60))
    _nhap_lo(client, ctx, sp["id"], 30, _ngay(120))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"],
                   [_dong_lo(client, ctx, sp, {0: 9, 1: 20, 2: 33})])
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["da_dieu_chinh"]) == 2      # lô giữa không đổi
    assert body["tong_lech"] == 2               # -1 +3

    assert [b.quantity for b in _lo(sp["id"])] == [9, 20, 33]
    assert _sp(sp["id"]).stock == 62
    assert _khong_lech(ctx["shop_id"])


def test_dem_mot_lo_ve_khong_van_giu_dong_lo(client):
    """Lô về 0 KHÔNG bị xóa: đó là lịch sử, và order_item_batches còn trỏ vào."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 6, _ngay(20))
    _nhap_lo(client, ctx, sp["id"], 4, _ngay(50))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"],
                   [_dong_lo(client, ctx, sp, {0: 0})])
    assert res.status_code == 200, res.text

    lo = _lo(sp["id"])
    assert len(lo) == 2, "Lô hết hàng vẫn phải còn dòng"
    assert [b.quantity for b in lo] == [0, 4]
    assert _sp(sp["id"]).stock == 4
    assert _khong_lech(ctx["shop_id"])


def test_lo_khong_co_trong_phieu_thi_giu_nguyen(client):
    """Nguyên tắc 1 của kiểm kê, hạ xuống mức lô: quên đếm một lô không được
    làm lô đó về 0."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 7, _ngay(15))
    _nhap_lo(client, ctx, sp["id"], 40, _ngay(200))

    _kiem_ke(client, ctx["token"], ctx["shop_id"],
             [_dong_lo(client, ctx, sp, {0: 6})])

    assert [b.quantity for b in _lo(sp["id"])] == [6, 40]
    assert _sp(sp["id"]).stock == 46
    assert _khong_lech(ctx["shop_id"])


def test_dem_dung_thi_khong_doi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 12, _ngay(30))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"],
                   [_dong_lo(client, ctx, sp, {0: 12})])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["khong_doi"] == 1
    assert body["da_dieu_chinh"] == []
    assert _sp(sp["id"]).stock == 12


# ---------- Ba nguyên tắc an toàn ----------


def test_lo_doi_giua_chung_thi_bo_qua_dong_do(client):
    """Bán hàng vẫn chạy khi đang đếm. So snapshot ở mức LÔ chứ không mức tổng:
    hai lô đổi ngược chiều nhau làm tổng đứng yên trong khi cả hai đã khác."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 20, _ngay(30))

    dong = _dong_lo(client, ctx, sp, {0: 20})
    # POS bán mất 4 trước khi bấm Lưu (FEFO trừ đúng lô này).
    client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": sp["id"], "price": sp["price"], "quantity": 4}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [dong])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["da_dieu_chinh"] == []
    assert len(body["bo_qua"]) == 1
    assert "đã đổi" in body["bo_qua"][0]["ly_do"]
    # Tồn giữ nguyên 16, KHÔNG bị đẩy ngược lên 20.
    assert _sp(sp["id"]).stock == 16
    assert _khong_lech(ctx["shop_id"])


def test_lo_hop_le_van_ap_dung_khi_lo_khac_bi_bo_qua(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(5))     # lô sẽ bị bán bớt
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(300))

    dong = _dong_lo(client, ctx, sp, {0: 10, 1: 7})
    client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": sp["id"], "price": sp["price"], "quantity": 2}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [dong])
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["da_dieu_chinh"]) == 1
    assert len(body["bo_qua"]) == 1

    assert [b.quantity for b in _lo(sp["id"])] == [8, 7]
    assert _sp(sp["id"]).stock == 15
    assert _khong_lech(ctx["shop_id"])


def test_so_dem_lo_am_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"],
                   [_dong_lo(client, ctx, sp, {0: -1})])
    assert res.status_code == 400
    assert _sp(sp["id"]).stock == 10


def test_lo_trung_nhau_trong_phieu_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))
    lo_id = _lo(sp["id"])[0].id

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [{
        "product_id": sp["id"],
        "batches": [
            {"batch_id": lo_id, "counted": 5, "quantity_snapshot": 10},
            {"batch_id": lo_id, "counted": 7, "quantity_snapshot": 10},
        ],
    }])
    assert res.status_code == 400
    assert _sp(sp["id"]).stock == 10


# ---------- Đếm thừa mà không thuộc lô nào ----------


def test_lo_la_bi_tu_choi_va_chi_duong_nhap_kho(client):
    """Mỗi hộp đều có hạn in trên bao bì nên hàng thừa luôn thuộc một hạn cụ
    thể. Tự tạo lô không hạn còn tệ hơn: lô không hạn xếp SAU CÙNG khi trừ FEFO
    nên số hàng đó nằm lại trên kệ lâu nhất - đúng thứ sẽ hỏng trước."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [{
        "product_id": sp["id"],
        "batches": [{"batch_id": 999999, "counted": 3, "quantity_snapshot": 0}],
    }])
    assert res.status_code == 400
    assert "Nhập kho" in res.json()["detail"]
    assert _sp(sp["id"]).stock == 10
    assert len(_lo(sp["id"])) == 1, "Không được tự tạo lô nào"


def test_lo_cua_san_pham_khac_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    a = _tao_sp_theo_lo(client, ctx)
    b = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, a["id"], 10, _ngay(30))
    _nhap_lo(client, ctx, b["id"], 10, _ngay(30))
    lo_cua_b = _lo(b["id"])[0].id

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [{
        "product_id": a["id"],
        "batches": [{"batch_id": lo_cua_b, "counted": 1, "quantity_snapshot": 10}],
    }])
    assert res.status_code == 400
    assert _sp(b["id"]).stock == 10


# ---------- Hai dạng dòng loại trừ nhau ----------


def test_hang_theo_lo_gui_so_tong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"],
                   [{"product_id": sp["id"], "counted": 8, "stock_snapshot": 10}])
    assert res.status_code == 400
    assert "từng lô" in res.json()["detail"]


def test_hang_theo_lo_gui_ca_hai_kieu_bi_tu_choi(client):
    """Gửi cả số tổng lẫn số theo lô là hai nguồn sự thật cho cùng một con số."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))
    lo_id = _lo(sp["id"])[0].id

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [{
        "product_id": sp["id"],
        "counted": 8,
        "stock_snapshot": 10,
        "batches": [{"batch_id": lo_id, "counted": 8, "quantity_snapshot": 10}],
    }])
    assert res.status_code == 400
    assert _sp(sp["id"]).stock == 10


def test_hang_khong_theo_lo_gui_theo_lo_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [{
        "product_id": ctx["product"]["id"],
        "batches": [{"batch_id": 1, "counted": 1, "quantity_snapshot": 1}],
    }])
    assert res.status_code == 400


def test_hang_khong_theo_lo_van_dem_bang_so_tong(client):
    """Sản phẩm tắt cờ phải chạy y như trước F6."""
    ctx = seller_with_shop(client)
    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": ctx["product"]["id"], "counted": 7, "stock_snapshot": 10}
    ])
    assert res.status_code == 200, res.text
    assert _sp(ctx["product"]["id"]).stock == 7


def test_mot_phieu_lan_ca_hai_loai_san_pham(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))

    dong_lo = _dong_lo(client, ctx, sp, {0: 9})
    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        dong_lo,
        {"product_id": ctx["product"]["id"], "counted": 8, "stock_snapshot": 10},
    ])
    assert res.status_code == 200, res.text
    assert res.json()["tong_lech"] == -3
    assert _sp(sp["id"]).stock == 9
    assert _sp(ctx["product"]["id"]).stock == 8
    assert _khong_lech(ctx["shop_id"])


# ---------- Danh sách lô để dựng phiếu đếm ----------


def test_danh_sach_lo_de_kiem_ke_lay_ca_lo_con_han_dai(client):
    """Khác /batches (chỉ lô sắp/đã hết hạn): kiểm kê phải đếm được HẾT."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 3, _ngay(-5))
    _nhap_lo(client, ctx, sp["id"], 4, _ngay(400))

    res = client.get(
        f"/api/products/{ctx['shop_id']}/stocktake/batches",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    dong = [p for p in res.json()["products"] if p["product_id"] == sp["id"]][0]
    assert [b["quantity"] for b in dong["batches"]] == [3, 4]


def test_lo_da_ve_khong_khong_vao_phieu_dem(client):
    """Lô hết hàng là lịch sử, không phải hàng trên kệ để đếm."""
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(30))
    _kiem_ke(client, ctx["token"], ctx["shop_id"],
             [_dong_lo(client, ctx, sp, {0: 0})])

    res = client.get(
        f"/api/products/{ctx['shop_id']}/stocktake/batches",
        headers=auth(ctx["token"]),
    )
    dong = [p for p in res.json()["products"] if p["product_id"] == sp["id"]][0]
    assert dong["batches"] == []


def test_danh_sach_lo_de_kiem_ke_khong_lo_gia_von(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 5, _ngay(30), gia_von=9000)

    res = client.get(
        f"/api/products/{ctx['shop_id']}/stocktake/batches",
        headers=auth(ctx["token"]),
    )
    for p in res.json()["products"]:
        for b in p["batches"]:
            assert "cost_price" not in b


def test_khong_xem_duoc_lo_de_kiem_ke_cua_shop_khac(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.get(
        f"/api/products/{ctx['shop_id']}/stocktake/batches",
        headers=auth(token_b),
    )
    assert res.status_code == 403


# ---------- Phân quyền ----------


def test_nhan_vien_kho_duoc_kiem_ke_theo_lo(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp_theo_lo(client, ctx)
    _nhap_lo(client, ctx, sp["id"], 10, _ngay(30))
    _, kho = new_staff(client, ctx, staff_role="WAREHOUSE")

    res = _kiem_ke(client, kho, ctx["shop_id"],
                   [_dong_lo(client, ctx, sp, {0: 9})])
    assert res.status_code == 200, res.text
    assert _sp(sp["id"]).stock == 9
