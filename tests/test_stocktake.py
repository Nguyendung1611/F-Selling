"""GĐ 4: kiểm kê - đặt tồn kho bằng số đếm thực tế."""
from __future__ import annotations

from conftest import (
    auth,
    create_category,
    create_shop,
    new_seller,
    new_staff,
    seller_with_shop,
)


def _tao_sp(client, token, shop_id, cat_id, name, stock=10):
    res = client.post(
        "/api/products",
        params={"shop_id": shop_id},
        data={"name": name, "price": 10000, "stock": stock, "category_id": cat_id},
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _kiem_ke(client, token, shop_id, items):
    return client.post(
        f"/api/products/{shop_id}/stocktake",
        json={"items": items},
        headers=auth(token),
    )


def _ton(client, token, shop_id, product_id):
    ds = client.get(f"/api/products/{shop_id}", headers=auth(token)).json()
    return [p for p in ds if p["id"] == product_id][0]["stock"]


# ---------- Điều chỉnh cơ bản ----------


def test_dem_thieu_thi_giam_ton(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP hao hut", 20)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 17, "stock_snapshot": 20}
    ])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tong_lech"] == -3
    assert body["da_dieu_chinh"][0]["truoc"] == 20
    assert body["da_dieu_chinh"][0]["sau"] == 17
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 17


def test_dem_thua_thi_tang_ton(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP du", 5)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 8, "stock_snapshot": 5}
    ])
    assert res.json()["tong_lech"] == 3
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 8


def test_dem_dung_thi_khong_doi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP khop", 12)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 12, "stock_snapshot": 12}
    ])
    body = res.json()
    assert body["khong_doi"] == 1
    assert body["da_dieu_chinh"] == []
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 12


def test_dem_ve_khong(client):
    """Đếm ra 0 là hợp lệ - hàng đã bán hết hoặc mất sạch."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP het", 9)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 0, "stock_snapshot": 9}
    ])
    assert res.status_code == 200, res.text
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 0


def test_nhieu_san_pham_cung_luc(client):
    ctx = seller_with_shop(client)
    a = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Nhieu A", 10)
    b = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Nhieu B", 20)
    c = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Nhieu C", 30)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": a["id"], "counted": 8, "stock_snapshot": 10},
        {"product_id": b["id"], "counted": 20, "stock_snapshot": 20},
        {"product_id": c["id"], "counted": 33, "stock_snapshot": 30},
    ])
    body = res.json()
    assert len(body["da_dieu_chinh"]) == 2
    assert body["khong_doi"] == 1
    assert body["tong_lech"] == 1          # -2 +3
    assert _ton(client, ctx["token"], ctx["shop_id"], a["id"]) == 8
    assert _ton(client, ctx["token"], ctx["shop_id"], c["id"]) == 33


# ---------- Nguyên tắc an toàn ----------


def test_sp_khong_dem_toi_thi_giu_nguyen(client):
    """Quên quét một kệ hàng không được làm mất sạch tồn kho của kệ đó."""
    ctx = seller_with_shop(client)
    dem = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Co dem", 10)
    quen = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Quen dem", 77)

    _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": dem["id"], "counted": 9, "stock_snapshot": 10}
    ])
    assert _ton(client, ctx["token"], ctx["shop_id"], quen["id"]) == 77


def test_ton_doi_giua_chung_thi_bo_qua_dong_do(client):
    """Bán hàng vẫn chạy khi đang kiểm kê; không được nuốt mất số vừa bán."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP dang ban", 20)

    # Nhân viên bắt đầu đếm khi tồn là 20, nhưng POS bán mất 4 trước khi bấm Lưu.
    client.post(
        f"/api/products/{sp['id']}/stock", json={"delta": -4}, headers=auth(ctx["token"])
    )

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 20, "stock_snapshot": 20}
    ])
    body = res.json()
    assert body["da_dieu_chinh"] == []
    assert len(body["bo_qua"]) == 1
    assert "đã đổi" in body["bo_qua"][0]["ly_do"]
    assert body["bo_qua"][0]["name"] == "SP dang ban"
    # Tồn giữ nguyên 16, KHÔNG bị đẩy ngược lên 20.
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 16


def test_dong_hop_le_van_duoc_ap_dung_khi_dong_khac_bi_bo_qua(client):
    ctx = seller_with_shop(client)
    ok = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "On dinh", 10)
    doi = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Bi ban", 10)
    client.post(
        f"/api/products/{doi['id']}/stock", json={"delta": -2}, headers=auth(ctx["token"])
    )

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": ok["id"], "counted": 7, "stock_snapshot": 10},
        {"product_id": doi["id"], "counted": 10, "stock_snapshot": 10},
    ])
    body = res.json()
    assert len(body["da_dieu_chinh"]) == 1
    assert len(body["bo_qua"]) == 1
    assert _ton(client, ctx["token"], ctx["shop_id"], ok["id"]) == 7
    assert _ton(client, ctx["token"], ctx["shop_id"], doi["id"]) == 8


def test_so_dem_am_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP am", 10)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": -1, "stock_snapshot": 10}
    ])
    assert res.status_code == 400
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 10


def test_phieu_rong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [])
    assert res.status_code == 400


def test_sp_trung_nhau_trong_phieu_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP lap", 10)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 5, "stock_snapshot": 10},
        {"product_id": sp["id"], "counted": 7, "stock_snapshot": 10},
    ])
    assert res.status_code == 400
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 10


def test_sp_khong_ton_tai_thi_bo_qua_khong_vo_ca_phieu(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Van con", 10)

    res = _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 6, "stock_snapshot": 10},
        {"product_id": 999999, "counted": 3, "stock_snapshot": 3},
    ])
    assert res.status_code == 200, res.text
    assert len(res.json()["bo_qua"]) == 1
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 6


# ---------- Phân quyền ----------


def test_khong_kiem_ke_duoc_shop_khac(client):
    ctx1 = seller_with_shop(client)
    sp = _tao_sp(client, ctx1["token"], ctx1["shop_id"], ctx1["category_id"], "Cua shop 1", 10)

    _, token2 = new_seller(client)
    res = _kiem_ke(client, token2, ctx1["shop_id"], [
        {"product_id": sp["id"], "counted": 0, "stock_snapshot": 10}
    ])
    assert res.status_code == 403
    assert _ton(client, ctx1["token"], ctx1["shop_id"], sp["id"]) == 10


def test_khong_kiem_ke_duoc_sp_cua_shop_khac(client):
    """Gửi product_id của shop khác lên phiếu kiểm kê shop mình -> bỏ qua."""
    ctx1 = seller_with_shop(client)
    _, token2 = new_seller(client)
    shop2 = create_shop(client, token2)
    cat2 = create_category(client, token2, shop2)
    sp2 = _tao_sp(client, token2, shop2, cat2, "SP shop 2", 50)

    res = _kiem_ke(client, ctx1["token"], ctx1["shop_id"], [
        {"product_id": sp2["id"], "counted": 0, "stock_snapshot": 50}
    ])
    assert res.status_code == 200, res.text
    assert len(res.json()["bo_qua"]) == 1
    assert _ton(client, token2, shop2, sp2["id"]) == 50


def test_nhan_vien_duoc_kiem_ke(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "NV dem", 10)
    _, staff_token = new_staff(client, ctx)

    res = _kiem_ke(client, staff_token, ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 9, "stock_snapshot": 10}
    ])
    assert res.status_code == 200, res.text
    assert _ton(client, ctx["token"], ctx["shop_id"], sp["id"]) == 9


def test_can_dang_nhap(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/products/{ctx['shop_id']}/stocktake",
        json={"items": [{"product_id": ctx["product"]["id"], "counted": 1, "stock_snapshot": 10}]},
    )
    assert res.status_code == 401


# ---------- Ghi log ----------


def test_co_ghi_log_khi_dieu_chinh(client, db):
    from fselling import models

    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Ghi log", 10)
    _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 4, "stock_snapshot": 10}
    ])

    log = (
        db.query(models.SystemLog)
        .filter(models.SystemLog.action == "STOCKTAKE")
        .order_by(models.SystemLog.id.desc())
        .first()
    )
    assert log is not None
    assert "Ghi log" in log.details
    assert "-6" in log.details


def test_khong_ghi_log_khi_khong_co_gi_thay_doi(client, db):
    from fselling import models

    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Khong doi gi", 10)
    truoc = db.query(models.SystemLog).filter(models.SystemLog.action == "STOCKTAKE").count()

    _kiem_ke(client, ctx["token"], ctx["shop_id"], [
        {"product_id": sp["id"], "counted": 10, "stock_snapshot": 10}
    ])
    sau = db.query(models.SystemLog).filter(models.SystemLog.action == "STOCKTAKE").count()
    assert sau == truoc
