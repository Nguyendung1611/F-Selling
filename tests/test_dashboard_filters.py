"""Nhóm B: phân trang + lọc theo khoảng ngày cho dashboard và thống kê."""
from datetime import datetime, timedelta

from conftest import auth, create_category, create_product, create_shop, new_seller

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services.report_service import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

HOM_NAY = datetime.utcnow().strftime("%Y-%m-%d")
HOM_QUA = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
TUAN_TRUOC = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")


def _shop_co_nhieu_don(
    client, so_don, quantity=1, payment_method="transfer"
):
    """Tạo shop + N đơn. Trả về (ctx, danh sách order_id theo thứ tự tạo)."""
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    create_product(client, token, shop_id, "SP phan trang", 10000, so_don * quantity + 10, cat_id)
    ctx = {"shop_id": shop_id, "token": token}

    ids = []
    for _ in range(so_don):
        res = client.post(
            f"/api/orders/{shop_id}",
            json={
                "items": [
                    {
                        "product_name": "SP phan trang",
                        "price": 1,
                        "quantity": quantity,
                    }
                ],
                "payment_method": payment_method,
            },
            headers=auth(token),
        )
        assert res.status_code == 200, res.text
        ids.append(res.json()["order_id"])
    return ctx, ids


def _doi_ngay_tao(order_id, so_ngay_truoc):
    session = SessionLocal()
    try:
        o = session.query(models.Order).filter(models.Order.id == order_id).first()
        o.created_at = datetime.utcnow() - timedelta(days=so_ngay_truoc)
        session.commit()
    finally:
        session.close()


def _dashboard(client, ctx, **params):
    chuoi = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/dashboard/seller/{ctx['shop_id']}"
    if chuoi:
        url += f"?{chuoi}"
    return client.get(url, headers=auth(ctx["token"]))


# ---------- Contract ----------
def test_dashboard_them_thong_tin_phan_trang(client):
    ctx, _ = _shop_co_nhieu_don(client, 3)
    body = _dashboard(client, ctx).json()

    assert set(body.keys()) == {
        "total_revenue",
        "orders",
        "page",
        "per_page",
        "total_orders",
        "has_more",
        "reconciliation_count",
    }
    assert body["page"] == 1
    assert body["per_page"] == DEFAULT_PAGE_SIZE
    assert body["total_orders"] == 3
    assert body["has_more"] is False


def test_khong_truyen_tham_so_van_tra_du_don_cho_shop_nho(client):
    """Shop ít đơn (dưới 50) phải thấy toàn bộ như trước khi có phân trang."""
    ctx, ids = _shop_co_nhieu_don(client, 5)
    body = _dashboard(client, ctx).json()
    assert len(body["orders"]) == 5
    assert {o["id"] for o in body["orders"]} == set(ids)


# ---------- Phân trang ----------
def test_phan_trang_chia_dung_va_khong_trung_don(client):
    ctx, ids = _shop_co_nhieu_don(client, 7)

    trang1 = _dashboard(client, ctx, page=1, per_page=3).json()
    trang2 = _dashboard(client, ctx, page=2, per_page=3).json()
    trang3 = _dashboard(client, ctx, page=3, per_page=3).json()

    assert [len(t["orders"]) for t in (trang1, trang2, trang3)] == [3, 3, 1]
    assert (trang1["has_more"], trang2["has_more"], trang3["has_more"]) == (True, True, False)

    tat_ca = [o["id"] for t in (trang1, trang2, trang3) for o in t["orders"]]
    assert len(tat_ca) == len(set(tat_ca)) == 7, "Không đơn nào bị trùng hoặc bị bỏ sót"
    assert set(tat_ca) == set(ids)


def test_don_moi_nhat_nam_o_trang_dau(client):
    ctx, ids = _shop_co_nhieu_don(client, 4)
    _doi_ngay_tao(ids[0], 10)  # đẩy đơn đầu về quá khứ

    trang1 = _dashboard(client, ctx, page=1, per_page=2).json()
    assert ids[0] not in [o["id"] for o in trang1["orders"]], "Đơn cũ nhất phải xuống trang sau"


def test_trang_vuot_qua_gioi_han_tra_danh_sach_rong(client):
    ctx, _ = _shop_co_nhieu_don(client, 2)
    body = _dashboard(client, ctx, page=99).json()
    assert body["orders"] == []
    assert body["total_orders"] == 2
    assert body["has_more"] is False


def test_tham_so_phan_trang_khong_hop_le(client):
    ctx, _ = _shop_co_nhieu_don(client, 1)
    assert _dashboard(client, ctx, page=0).status_code == 422
    assert _dashboard(client, ctx, per_page=0).status_code == 422
    assert _dashboard(client, ctx, per_page=MAX_PAGE_SIZE + 1).status_code == 422


def test_doanh_thu_la_cua_ca_khoang_khong_phai_cua_trang(client):
    ctx, ids = _shop_co_nhieu_don(client, 4, payment_method="cash")
    for oid in ids:
        client.post(f"/api/orders/{oid}/pay", headers=auth(ctx["token"]))

    trang1 = _dashboard(client, ctx, page=1, per_page=2).json()
    assert len(trang1["orders"]) == 2
    assert trang1["total_revenue"] == 4 * 10000, "Doanh thu phải tính cả 4 đơn, không chỉ 2 đơn hiển thị"


# ---------- Lọc ngày ----------
def test_loc_theo_khoang_ngay(client):
    ctx, ids = _shop_co_nhieu_don(client, 3)
    _doi_ngay_tao(ids[0], 30)
    _doi_ngay_tao(ids[1], 3)
    # ids[2] giữ nguyên hôm nay

    body = _dashboard(client, ctx, tu_ngay=TUAN_TRUOC).json()
    con_lai = {o["id"] for o in body["orders"]}
    assert ids[0] not in con_lai, "Đơn 30 ngày trước phải bị lọc ra"
    assert {ids[1], ids[2]} <= con_lai
    assert body["total_orders"] == 2


def test_den_ngay_tinh_tron_ca_ngay_do(client):
    ctx, ids = _shop_co_nhieu_don(client, 1)
    # Đơn tạo hôm nay, lọc den_ngay = hôm nay -> vẫn phải thấy
    body = _dashboard(client, ctx, tu_ngay=HOM_NAY, den_ngay=HOM_NAY).json()
    assert ids[0] in [o["id"] for o in body["orders"]]


def test_loc_ngay_khong_co_don_nao(client):
    ctx, _ = _shop_co_nhieu_don(client, 2)
    body = _dashboard(client, ctx, tu_ngay="2020-01-01", den_ngay="2020-01-31").json()
    assert body["orders"] == []
    assert body["total_orders"] == 0
    assert body["total_revenue"] == 0


def test_ngay_sai_dinh_dang_tra_400(client):
    ctx, _ = _shop_co_nhieu_don(client, 1)
    res = _dashboard(client, ctx, tu_ngay="25-12-2026")
    assert res.status_code == 400
    assert "YYYY-MM-DD" in res.json()["detail"]


def test_tu_ngay_lon_hon_den_ngay_tra_400(client):
    ctx, _ = _shop_co_nhieu_don(client, 1)
    res = _dashboard(client, ctx, tu_ngay=HOM_NAY, den_ngay=HOM_QUA)
    assert res.status_code == 400


# ---------- Thống kê theo khoảng ngày ----------
def _stats(client, ctx, **params):
    chuoi = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/shops/{ctx['shop_id']}/stats"
    if chuoi:
        url += f"?{chuoi}"
    return client.get(url, headers=auth(ctx["token"]))


def test_stats_khong_loc_giu_nguyen_contract(client):
    ctx, _ = _shop_co_nhieu_don(client, 2)
    body = _stats(client, ctx).json()
    assert set(body.keys()) == {
        "total_revenue",
        "total_orders",
        "total_sold",
        "top_products",
        "trend_labels",
        "trend_data",
        # F1: nhóm field lãi gộp. Chỉ có mặt khi người gọi là chủ shop hoặc
        # ADMIN - fixture này đăng nhập bằng chủ shop nên phải thấy đủ.
        # test_gia_von.py kiểm ca ngược lại: MANAGER không được thấy field nào
        # trong nhóm này.
        "revenue_with_cost",
        "total_cost",
        "gross_profit",
        "gross_margin",
        "orders_missing_cost",
        "revenue_missing_cost",
        "returns_missing_cost",
        # F2: hàng khách trả lại, tính theo ngày trả. Hai khóa này KHÔNG bị
        # giới hạn quyền - chỉ số tiền lãi mới nhạy cảm.
        "returned_amount",
        "net_revenue",
        # F4: công nợ phải thu. Đứng riêng, KHÔNG cộng vào doanh thu.
        # F6: hủy hàng (hết hạn, hỏng vỡ, thất thoát). Lỗ đúng bằng giá vốn
        # số hàng đã bỏ đi, và nó ĐÃ được trừ khỏi `gross_profit`.
        "written_off_quantity",
        "write_off_loss",
        "write_offs_missing_cost",
        "receivable_amount",
    }
    assert len(body["trend_labels"]) == 7, "Mặc định vẫn là xu hướng 7 ngày"


def test_stats_loc_theo_ngay(client):
    ctx, ids = _shop_co_nhieu_don(
        client, 3, quantity=2, payment_method="cash"
    )
    for oid in ids:
        client.post(f"/api/orders/{oid}/pay", headers=auth(ctx["token"]))
    _doi_ngay_tao(ids[0], 30)

    toan_bo = _stats(client, ctx).json()
    trong_tuan = _stats(client, ctx, tu_ngay=TUAN_TRUOC).json()

    assert toan_bo["total_orders"] == 3
    assert trong_tuan["total_orders"] == 2, "Đơn 30 ngày trước bị loại"
    assert trong_tuan["total_revenue"] < toan_bo["total_revenue"]
    assert trong_tuan["total_sold"] == 4, "2 đơn x 2 sản phẩm"


def test_stats_ngay_sai_dinh_dang_tra_400(client):
    ctx, _ = _shop_co_nhieu_don(client, 1)
    assert _stats(client, ctx, den_ngay="hom-qua").status_code == 400


# ---------- Phân quyền vẫn nguyên ----------
def test_seller_khac_khong_xem_duoc_dashboard_da_phan_trang(client):
    ctx, _ = _shop_co_nhieu_don(client, 2)
    _, token_b = new_seller(client)
    res = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}?page=1&per_page=10",
        headers=auth(token_b),
    )
    assert res.status_code == 403
