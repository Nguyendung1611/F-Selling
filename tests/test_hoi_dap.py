"""L3: hỏi đáp báo cáo bằng tiếng Việt.

Hai luật xuyên suốt:

1. **Không đoán bừa.** Câu không khớp mẫu nào thì nói thẳng là chưa hiểu. Một
   con số bịa ra trông y hệt một con số thật, và người hỏi không có cách nào
   biết là nó sai.
2. **Không có hàng rào phân quyền riêng.** Trợ lý gọi lại đúng các báo cáo cũ
   nên đi qua đúng các hàng rào cũ; nếu nó tự dựng một lớp kiểm mới thì lớp đó
   sẽ lệch dần khỏi lớp thật.
"""
from datetime import datetime, timedelta

from conftest import auth, create_category, create_product, create_shop, new_seller, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import assistant_service


def _hoi(client, ctx, cau_hoi):
    return client.post(
        f"/api/assistant/{ctx['shop_id']}",
        json={"cau_hoi": cau_hoi},
        headers=auth(ctx["token"]),
    )


def _ban(client, ctx, product_id, quantity=1, so_ngay_truoc=0):
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": product_id, "price": 1, "quantity": quantity}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    if so_ngay_truoc:
        session = SessionLocal()
        try:
            o = session.query(models.Order).filter(
                models.Order.id == res.json()["order_id"]
            ).first()
            o.created_at = datetime.utcnow() - timedelta(days=so_ngay_truoc)
            session.commit()
        finally:
            session.close()
    return res.json()["order_id"]


# ---------- Hiểu câu hỏi ----------
def test_ba_cau_hoi_trong_ban_thiet_ke_deu_hieu_duoc():
    """Đúng ba câu ghi trong tiêu chí nghiệm thu."""
    for cau, mong_doi in (
        ("Hôm nay bán được bao nhiêu đơn?", assistant_service.Y_DINH_SO_DON),
        ("Sản phẩm nào sắp hết hạn?", assistant_service.Y_DINH_SAP_HET_HAN),
        ("So sánh doanh thu tuần này với tuần trước?", assistant_service.Y_DINH_SO_SANH_TUAN),
    ):
        assert assistant_service._doan_y_dinh(assistant_service._bo_dau(cau)) == mong_doi, cau


def test_go_khong_dau_van_hieu():
    """Người dùng gõ nhanh trên điện thoại thường không bỏ dấu."""
    assert assistant_service._doan_y_dinh(
        assistant_service._bo_dau("hom nay ban duoc bao nhieu")
    ) == assistant_service.Y_DINH_DOANH_THU
    assert assistant_service._doan_y_dinh(
        assistant_service._bo_dau("hang nao sap het han")
    ) == assistant_service.Y_DINH_SAP_HET_HAN


def test_cau_la_thi_noi_chua_hieu_chu_khong_doan(client):
    ctx = seller_with_shop(client)
    body = _hoi(client, ctx, "Trời hôm nay đẹp không?").json()

    assert body["hieu_duoc"] is False
    assert body["y_dinh"] is None
    assert body["goi_y"], "phải gợi ý câu hỏi làm được thay vì bỏ mặc"
    # Tuyệt đối không có con số nào trong câu trả lời "chưa hiểu".
    assert "chi_tiet" not in body or body.get("chi_tiet") is None


def test_khoang_thoi_gian_doc_dung():
    from fselling.core import thoi_gian

    hom_nay = thoi_gian.hom_nay_vn()
    _, tu, den, nhan = assistant_service._khoang_ngay(
        assistant_service._bo_dau("doanh thu hôm qua")
    )
    assert tu == den == hom_nay - timedelta(days=1)
    assert nhan == "hôm qua"

    _, tu, den, _ = assistant_service._khoang_ngay(
        assistant_service._bo_dau("doanh thu 7 ngày qua")
    )
    assert (den - tu).days == 6 and den == hom_nay

    ma, tu, den, nhan = assistant_service._khoang_ngay(
        assistant_service._bo_dau("doanh thu tuần trước")
    )
    assert nhan == "tuần trước"
    assert tu.weekday() == 0 and (den - tu).days == 6


def test_tuan_truoc_khong_bi_hieu_nham_thanh_tuan_nay():
    """Mẫu dài phải được thử trước mẫu ngắn, nếu không 'tuần trước' rơi vào
    nhánh 'tuần này' và con số sai mà nhìn vẫn hợp lý."""
    _, tu_truoc, _, _ = assistant_service._khoang_ngay(
        assistant_service._bo_dau("tuần trước")
    )
    _, tu_nay, _, _ = assistant_service._khoang_ngay(
        assistant_service._bo_dau("tuần này")
    )
    assert tu_truoc < tu_nay


# ---------- Trả lời đúng số ----------
def test_so_don_hom_nay_khop_voi_thuc_te(client):
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    for _ in range(3):
        _ban(client, ctx, ctx_full["product"]["id"])

    body = _hoi(client, ctx, "Hôm nay bao nhiêu đơn?").json()
    assert body["hieu_duoc"] is True
    assert body["chi_tiet"]["so_don"] == 3
    assert "3 đơn" in body["tra_loi"]


def test_don_hom_qua_khong_tinh_vao_hom_nay(client):
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    _ban(client, ctx, ctx_full["product"]["id"], so_ngay_truoc=1)

    hom_nay = _hoi(client, ctx, "Hôm nay bán được bao nhiêu?").json()
    hom_qua = _hoi(client, ctx, "Hôm qua bán được bao nhiêu?").json()
    assert hom_nay["chi_tiet"]["so_don"] == 0
    assert hom_qua["chi_tiet"]["so_don"] == 1


def test_con_so_cua_tro_ly_khop_voi_man_thong_ke(client):
    """Trợ lý gọi lại đúng báo cáo cũ nên hai chỗ KHÔNG được lệch nhau.

    Lệch là người dùng nhận hai câu trả lời cho cùng một câu hỏi rồi không tin
    cái nào nữa - đúng lý do không cho máy tự sinh câu lệnh.
    """
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    for _ in range(2):
        _ban(client, ctx, ctx_full["product"]["id"], quantity=2)

    from fselling.core import thoi_gian
    hom_nay = thoi_gian.hom_nay_vn().isoformat()
    thong_ke = client.get(
        f"/api/shops/{ctx['shop_id']}/stats?tu_ngay={hom_nay}&den_ngay={hom_nay}",
        headers=auth(ctx["token"]),
    ).json()
    tro_ly = _hoi(client, ctx, "Hôm nay bán được bao nhiêu?").json()

    assert tro_ly["chi_tiet"]["so_don"] == thong_ke["total_orders"]
    assert tro_ly["chi_tiet"]["doanh_thu"] == thong_ke["total_revenue"]


def test_don_chua_thanh_toan_khong_duoc_ke_thanh_tien_da_thu(client):
    """`total_orders` đếm MỌI đơn, `total_revenue` chỉ đếm đơn ĐÃ trả tiền.

    Dán liền hai con số vào một câu là ra "bán được 1 đơn, thu về 0đ" — nghe
    như máy hỏng, trong khi cả hai số đều đúng. Phải nói thẳng lý do.
    """
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    # Đơn chuyển khoản: đã tạo, đã trừ kho, nhưng tiền CHƯA về.
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": ctx_full["product"]["id"], "price": 1, "quantity": 1}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text

    body = _hoi(client, ctx, "Hôm nay bán được bao nhiêu?").json()
    assert body["chi_tiet"]["so_don"] == 1
    assert body["chi_tiet"]["doanh_thu"] == 0
    assert "chưa thu được đồng nào" in body["tra_loi"], body["tra_loi"]
    # Và tuyệt đối không được nói "đã thu về 0đ" như thể đó là doanh thu thật.
    assert "đã thu về" not in body["tra_loi"]


def test_hoi_can_nhap_hang_goi_dung_bo_du_bao(client):
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    body = _hoi(client, ctx, "Cần nhập hàng gì?").json()

    assert body["y_dinh"] == assistant_service.Y_DINH_CAN_NHAP
    assert body["nguon"] == "Dự báo nhập hàng"


def test_hoi_hang_e_goi_dung_bo_xa_hang(client):
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}
    body = _hoi(client, ctx, "Hàng nào đang nằm ế?").json()

    assert body["y_dinh"] == assistant_service.Y_DINH_HANG_E
    assert body["nguon"] == "Xả hàng tồn"


# ---------- Quyền ----------
def test_shop_cua_nguoi_khac_khong_hoi_duoc(client):
    chu_a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.post(
        f"/api/assistant/{chu_a['shop_id']}",
        json={"cau_hoi": "Hôm nay bán được bao nhiêu?"},
        headers=auth(token_b),
    )
    assert res.status_code in (403, 404), res.text


def test_chua_dang_nhap_thi_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/assistant/{ctx['shop_id']}", json={"cau_hoi": "Hôm nay bán được bao nhiêu?"}
    )
    assert res.status_code == 401


def test_nhan_vien_hoi_ve_lai_thi_bi_tu_choi_nhung_khong_lo_so_nao(client):
    """MANAGER xem được doanh thu nhưng KHÔNG được biết lãi (biết lãi là suy ra
    giá vốn). Câu trả lời phải từ chối tử tế và tuyệt đối không kèm con số."""
    chu = seller_with_shop(client)
    _, token_nv = new_staff(client, chu, staff_role="MANAGER")
    res = client.post(
        f"/api/assistant/{chu['shop_id']}",
        json={"cau_hoi": "Tháng này lãi bao nhiêu?"},
        headers=auth(token_nv),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["hieu_duoc"] is True
    assert body.get("chi_tiet") is None
    # Không có CHỮ SỐ nào trong câu từ chối. (Đừng kiểm ký tự "đ" - chữ "được"
    # cũng có "đ", và test sẽ đỏ vì một lý do chẳng liên quan gì tới bảo mật.)
    assert not any(k.isdigit() for k in body["tra_loi"]), body["tra_loi"]


def test_thu_ngan_hoi_doanh_thu_thi_bi_chan(client):
    """Thu ngân không có PERMISSION_REPORT; trợ lý không được là đường vòng."""
    chu = seller_with_shop(client)
    _, token_nv = new_staff(client, chu, staff_role="CASHIER")
    res = client.post(
        f"/api/assistant/{chu['shop_id']}",
        json={"cau_hoi": "Hôm nay bán được bao nhiêu?"},
        headers=auth(token_nv),
    )
    assert res.status_code == 403 or res.json().get("chi_tiet") is None


# ---------- Đầu vào bậy ----------
def test_cau_hoi_rong_va_qua_dai_bi_chan(client):
    ctx = seller_with_shop(client)
    assert _hoi(client, ctx, "").status_code == 422
    assert _hoi(client, ctx, "a" * (assistant_service.CAU_HOI_TOI_DA + 1)).status_code == 422


def test_ky_tu_la_khong_lam_vo_bo_so_khop(client):
    ctx = seller_with_shop(client)
    for cau in ("<script>alert(1)</script>", "'; DROP TABLE orders; --", "🙂🙂🙂", "%%%"):
        res = _hoi(client, ctx, cau)
        assert res.status_code == 200, (cau, res.text)
        assert res.json()["hieu_duoc"] is False

    # Và bảng orders vẫn còn nguyên.
    session = SessionLocal()
    try:
        session.query(models.Order).count()
    finally:
        session.close()
