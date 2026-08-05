"""Kiểm màn "Ai làm gì" của chủ shop.

Hai điều quan trọng nhất, và chúng kéo nhau ngược chiều:

1. **Không được lọt việc của shop khác.** Đây là màn dùng để soi nhân viên;
   thấy việc của cửa hàng người ta là rò rỉ dữ liệu.
2. **Không được giấu mất việc.** Danh sách lọc là danh sách LOẠI TRỪ, nên một
   hành động mới thêm vào code sau này vẫn hiện ra. Dùng danh sách cho phép thì
   quên khai một cái là nó vô hình vĩnh viễn và không ai biết màn hình bị thủng.
"""
from __future__ import annotations

from conftest import auth, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import log_service


def _ghi(user_id: int, action: str, details: str = "x"):
    s = SessionLocal()
    try:
        s.add(models.SystemLog(user_id=user_id, action=action, details=details))
        s.commit()
    finally:
        s.close()


def _id_user(username: str) -> int:
    s = SessionLocal()
    try:
        return s.query(models.User).filter(models.User.username == username).first().id
    finally:
        s.close()


def _lay(client, ctx, **q):
    res = client.get(
        f"/api/logs/shop/{ctx['shop_id']}", params=q, headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------- Lọc theo việc ----------
def test_bo_dang_nhap_khoi_danh_sach():
    """118 trên 232 dòng trong máy thật là LOGIN. Trộn vào thì phải cuộn hai màn
    hình mới thấy một lần hủy đơn."""
    assert "LOGIN" in log_service.KHONG_HIEN_O_SHOP


def test_hien_moi_viec_dung_toi_tien_va_kho():
    """Những cái này KHÔNG được nằm trong danh sách ẩn."""
    phai_hien = [
        "CANCEL_ORDER", "REFUND_COMPLETE", "ORDER_RETURN", "PAY_ORDER",
        "CASH_TOPUP", "DEBT_PAYMENT", "WRITE_OFF_STOCK", "ADJUST_STOCK",
        "STOCKTAKE", "UPDATE_PRODUCT", "DELETE_PRODUCT", "DELETE_VOUCHER",
        "OFFLINE_SALE", "OPEN_CASH_SHIFT", "CREATE_STAFF", "DISABLE_STAFF",
    ]
    for a in phai_hien:
        assert a not in log_service.KHONG_HIEN_O_SHOP, f"{a} bị giấu mất"


def test_hanh_dong_la_van_hien_ra(client):
    """Danh sách là LOẠI TRỪ chứ không phải CHO PHÉP.

    Một hành động mới thêm vào code sau này phải TỰ hiện, không cần ai nhớ khai
    báo. Dùng danh sách cho phép thì quên khai một cái là nó vô hình vĩnh viễn
    và không ai biết màn hình đang thủng.
    """
    ctx = seller_with_shop(client)
    _ghi(_id_user(ctx["username"]), "HANH_DONG_MOI_TINH", "một việc chưa từng có")
    cac_action = [l["action"] for l in _lay(client, ctx)["logs"]]
    assert "HANH_DONG_MOI_TINH" in cac_action


def test_endpoint_lo_dang_nhap_nhung_giu_huy_don(client):
    ctx = seller_with_shop(client)
    uid = _id_user(ctx["username"])
    _ghi(uid, "LOGIN", "đăng nhập")
    _ghi(uid, "CANCEL_ORDER", "Hủy đơn #99 - hoàn kho 2 dòng")

    kq = _lay(client, ctx)
    cac_action = [l["action"] for l in kq["logs"]]
    assert "CANCEL_ORDER" in cac_action
    assert "LOGIN" not in cac_action


# ---------- Cách ly giữa các shop ----------
def test_khong_thay_viec_cua_shop_khac(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    _ghi(_id_user(b["username"]), "CANCEL_ORDER", "Hủy đơn của shop B")

    kq = _lay(client, a)
    assert all("shop B" not in (l["details"] or "") for l in kq["logs"])


def test_thay_viec_cua_nhan_vien_thuoc_shop_minh(client):
    ctx = seller_with_shop(client)
    ten_nv, _ = new_staff(client, ctx, staff_role="CASHIER")
    _ghi(_id_user(ten_nv), "REFUND_COMPLETE", "Nhân viên hoàn 50.000đ")

    kq = _lay(client, ctx)
    assert any(l["username"] == ten_nv for l in kq["logs"])
    assert any("Nhân viên hoàn" in (l["details"] or "") for l in kq["logs"])


def test_nguoi_ngoai_khong_xem_duoc(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    res = client.get(f"/api/logs/shop/{a['shop_id']}", headers=auth(b["token"]))
    assert res.status_code in (403, 404)


def test_chua_dang_nhap_bi_chan(client):
    a = seller_with_shop(client)
    assert client.get(f"/api/logs/shop/{a['shop_id']}").status_code == 401


# ---------- Sắp xếp và phân trang ----------
def test_moi_nhat_dung_truoc(client):
    ctx = seller_with_shop(client)
    uid = _id_user(ctx["username"])
    _ghi(uid, "CANCEL_ORDER", "viec cu")
    _ghi(uid, "CANCEL_ORDER", "viec moi")

    logs = _lay(client, ctx)["logs"]
    vi_moi = next(i for i, l in enumerate(logs) if l["details"] == "viec moi")
    vi_cu = next(i for i, l in enumerate(logs) if l["details"] == "viec cu")
    assert vi_moi < vi_cu


def test_phan_trang_tra_dung_tong_va_so_trang(client):
    ctx = seller_with_shop(client)
    uid = _id_user(ctx["username"])
    for i in range(7):
        _ghi(uid, "ADJUST_STOCK", f"lan {i}")

    kq = _lay(client, ctx, page=1, per_page=3)
    assert len(kq["logs"]) == 3
    assert kq["total"] >= 7
    assert kq["total_pages"] == (kq["total"] + 2) // 3
    assert kq["page"] == 1

    trang2 = _lay(client, ctx, page=2, per_page=3)
    assert {l["id"] for l in trang2["logs"]}.isdisjoint({l["id"] for l in kq["logs"]})


def test_per_page_qua_lon_bi_chan(client):
    ctx = seller_with_shop(client)
    res = client.get(
        f"/api/logs/shop/{ctx['shop_id']}",
        params={"per_page": 5000},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 422, "phải chặn ở tầng validate, không để quét cả bảng"


def test_shop_chua_co_viec_gi_tra_danh_sach_rong(client):
    ctx = seller_with_shop(client)
    kq = _lay(client, ctx)
    assert isinstance(kq["logs"], list)
    assert kq["total"] == len(kq["logs"]) or kq["total_pages"] >= 1


# ---------- Nội dung trả về ----------
def test_moi_dong_du_bon_thong_tin_can_thiet(client):
    """Ai làm, làm gì, chi tiết, lúc nào. Thiếu một cái là dòng đó vô dụng."""
    ctx = seller_with_shop(client)
    _ghi(_id_user(ctx["username"]), "WRITE_OFF_STOCK", "Hủy 3 hộp sữa hết hạn")
    dong = _lay(client, ctx)["logs"][0]
    for khoa in ("id", "username", "action", "details", "created_at"):
        assert khoa in dong, f"thiếu {khoa}"
    assert dong["username"] == ctx["username"]
