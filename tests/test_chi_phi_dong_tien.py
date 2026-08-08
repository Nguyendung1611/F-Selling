"""K1: chi phí vận hành, lợi nhuận ròng và dòng tiền thực.

Ba thứ bộ test này canh, theo đúng thứ tự nguy hiểm:

1. **Phân bổ trả trước không được lệch một đồng nào.** Chia thẳng cho số tháng
   thì 10 triệu / 3 làm tròn ba lần ra 9.999.999đ, và một đồng lệch trong sổ
   tiền là thứ không bao giờ tìm lại được.
2. **Tiền mặt chỉ được trừ két ĐÚNG MỘT LẦN.** Chi phí sinh một `CashMovement`;
   nếu dòng tiền cộng cả chứng từ lẫn chuyển động thì mỗi lần chi bị đếm hai lần.
3. **Chi phí và lãi ròng chỉ chủ shop xem được.** Biết lãi ròng là suy ngược ra
   được giá vốn, và lương nhân viên không phải thứ để nhân viên khác đọc.
"""
import uuid
from datetime import date, timedelta

from conftest import _unique, auth, new_staff, seller_with_shop

from fselling.services import expense_service


def _op():
    return uuid.uuid4().hex


def _loai(client, ctx, ten):
    """Id của một loại chi phí theo tên (danh mục mặc định đã seed sẵn)."""
    res = client.get(
        f"/api/expense-categories/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    for c in res.json()["categories"]:
        if c["name"] == ten:
            return c["id"]
    raise AssertionError(f"Không thấy loại chi phí '{ten}'")


def _ghi_chi_phi(client, ctx, **kwargs):
    body = {
        "amount": 1_000_000,
        "method": "TRANSFER",
        "operation_id": _op(),
    }
    body.update(kwargs)
    if "category_id" not in body:
        body["category_id"] = _loai(client, ctx, "Điện nước")
    return client.post(
        f"/api/expenses/{ctx['shop_id']}", json=body, headers=auth(ctx["token"])
    )


def _dong_tien(client, ctx, **params):
    res = client.get(
        f"/api/reports/cashflow/{ctx['shop_id']}",
        params=params,
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _mo_ca(client, ctx, tien_dau_ca=10_000_000):
    res = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": tien_dau_ca, "note": "Ca kiểm thử"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _ca_hien_tai(client, ctx):
    res = client.get(
        f"/api/shifts/current/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()["shift"]


# ---------------------------------------------------------------------------
# 1. Phân bổ theo ngày bằng công thức lũy kế
# ---------------------------------------------------------------------------

class _Khoan:
    """Đủ để `phan_bo_trong_ky` chạy, không cần chạm database."""

    def __init__(self, amount, start, end):
        self.amount = amount
        self.amortize_start_date = start
        self.amortize_end_date = end


def test_phan_bo_cong_lai_dung_bang_so_tien_da_chi():
    """Cộng mọi tháng liền nhau phải ra ĐÚNG số đã trả, không thiếu một đồng.

    Đây là lý do dùng công thức lũy kế thay vì chia cho số tháng: các phép trừ
    triệt tiêu nhau nên sai số làm tròn không tích lại được.
    """
    khoan = _Khoan(30_000_000, "2026-08-15", "2026-11-14")
    ky = [
        (date(2026, 8, 15), date(2026, 8, 31)),
        (date(2026, 9, 1), date(2026, 9, 30)),
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), date(2026, 11, 14)),
    ]
    phan = [expense_service.phan_bo_trong_ky(khoan, t, d) for t, d in ky]
    assert sum(phan) == 30_000_000, f"Lệch: {sum(phan)} vs 30.000.000 ({phan})"
    assert all(p > 0 for p in phan)


def test_phan_bo_khong_lech_voi_so_tien_le():
    """Số tiền không chia hết cho số ngày vẫn phải khớp tuyệt đối."""
    khoan = _Khoan(10_000_001, "2026-01-01", "2026-03-31")
    tong = 0
    moc = date(2026, 1, 1)
    while moc <= date(2026, 3, 31):
        tong += expense_service.phan_bo_trong_ky(khoan, moc, moc)
        moc += timedelta(days=1)
    assert tong == 10_000_001


def test_phan_bo_ngoai_khoang_bang_khong():
    khoan = _Khoan(3_000_000, "2026-08-01", "2026-08-31")
    assert expense_service.phan_bo_trong_ky(
        khoan, date(2026, 7, 1), date(2026, 7, 31)
    ) == 0
    assert expense_service.phan_bo_trong_ky(
        khoan, date(2026, 9, 1), date(2026, 9, 30)
    ) == 0
    assert expense_service.phan_bo_trong_ky(
        khoan, date(2026, 8, 1), date(2026, 8, 31)
    ) == 3_000_000


def test_khoan_khong_phan_bo_roi_tron_vao_dung_mot_ngay():
    khoan = _Khoan(500_000, "2026-08-08", "2026-08-08")
    assert expense_service.phan_bo_trong_ky(
        khoan, date(2026, 8, 8), date(2026, 8, 8)
    ) == 500_000
    assert expense_service.phan_bo_trong_ky(
        khoan, date(2026, 8, 9), date(2026, 8, 31)
    ) == 0


def test_con_tra_truoc_giam_dan_ve_khong():
    khoan = _Khoan(30_000_000, "2026-08-01", "2026-10-31")
    assert expense_service.con_tra_truoc(khoan, date(2026, 7, 31)) == 30_000_000
    giua = expense_service.con_tra_truoc(khoan, date(2026, 8, 31))
    assert 0 < giua < 30_000_000
    assert expense_service.con_tra_truoc(khoan, date(2026, 10, 31)) == 0


def test_moc_ket_thuc_phan_bo_thang_thieu_ngay():
    """31/01 + 1 tháng lùi về 28/02, rồi trừ một ngày."""
    assert expense_service.moc_ket_thuc_phan_bo(
        date(2026, 8, 15), 3
    ) == date(2026, 11, 14)
    assert expense_service.moc_ket_thuc_phan_bo(
        date(2026, 1, 31), 1
    ) == date(2026, 2, 27)
    assert expense_service.moc_ket_thuc_phan_bo(
        date(2026, 1, 1), 12
    ) == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# 2. Danh mục
# ---------------------------------------------------------------------------

def test_danh_muc_duoc_seed_san_va_khong_co_hao_hut_hang_hoa(client):
    """Không được có danh mục cho hàng hỏng/hết hạn.

    Hàng đó đã đi qua phiếu hủy và ĐÃ bị trừ vào lãi gộp theo giá vốn của lô.
    Thêm một ô để gõ lại số đó là mời người dùng trừ hai lần.
    """
    ctx = seller_with_shop(client)
    res = client.get(
        f"/api/expense-categories/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    ten = [c["name"] for c in res.json()["categories"]]
    assert "Thuê mặt bằng" in ten
    assert "Lương nhân viên" in ten
    for xau in ("hao hụt", "hàng hỏng", "hết hạn"):
        assert not any(xau in t.lower() for t in ten), (
            f"Danh mục '{xau}' sẽ khiến hàng hủy bị trừ hai lần"
        )


def test_khong_co_duong_xoa_danh_muc(client):
    """Chỉ ẩn được. SQLite production không bật khóa ngoại nên xóa một danh
    mục đang dùng chỉ để lại báo cáo cũ trỏ vào hư không, mà không báo lỗi."""
    ctx = seller_with_shop(client)
    cid = _loai(client, ctx, "Phí ship")
    res = client.delete(
        f"/api/expense-categories/{ctx['shop_id']}/{cid}",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 405

    res = client.put(
        f"/api/expense-categories/{ctx['shop_id']}/{cid}",
        json={"is_active": False},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False


def test_khong_tao_duoc_hai_danh_muc_trung_ten(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/expense-categories/{ctx['shop_id']}",
        json={"name": "Tiền nước đá"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    res = client.post(
        f"/api/expense-categories/{ctx['shop_id']}",
        json={"name": "Tiền nước đá"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# 3. Ghi khoản chi
# ---------------------------------------------------------------------------

def test_ghi_chi_phi_chuyen_khoan_khong_dung_ket(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    truoc = _ca_hien_tai(client, ctx)["expected_cash_amount"]

    res = _ghi_chi_phi(client, ctx, amount=2_000_000, method="TRANSFER")
    assert res.status_code == 200, res.text
    assert res.json()["shift_id"] is None

    assert _ca_hien_tai(client, ctx)["expected_cash_amount"] == truoc


def test_chi_tien_mat_tru_ket_dung_mot_lan(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx, tien_dau_ca=10_000_000)

    res = _ghi_chi_phi(client, ctx, amount=3_000_000, method="CASH_SHIFT")
    assert res.status_code == 200, res.text
    assert res.json()["shift_id"] is not None

    ca = _ca_hien_tai(client, ctx)
    assert ca["pay_out_amount"] == 3_000_000
    assert ca["expected_cash_amount"] == 7_000_000


def test_chi_tien_mat_khong_co_ca_thi_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _ghi_chi_phi(client, ctx, amount=1_000_000, method="CASH_SHIFT")
    assert res.status_code == 409, res.text


def test_chi_tien_mat_vuot_ket_bi_tu_choi_va_khong_ghi_so(client):
    """Từ chối thì cả két lẫn sổ chi phí đều phải nguyên vẹn (cùng transaction)."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx, tien_dau_ca=1_000_000)

    res = _ghi_chi_phi(client, ctx, amount=5_000_000, method="CASH_SHIFT")
    assert res.status_code == 409, res.text

    assert _ca_hien_tai(client, ctx)["expected_cash_amount"] == 1_000_000
    ds = client.get(
        f"/api/expenses/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    assert ds["total"] == 0, "Khoản chi bị từ chối vẫn lọt vào sổ"


def test_bam_hai_lan_khong_tru_ket_hai_lan(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx, tien_dau_ca=10_000_000)
    ma = _op()

    dau = _ghi_chi_phi(
        client, ctx, amount=2_000_000, method="CASH_SHIFT", operation_id=ma
    )
    assert dau.status_code == 200, dau.text
    lai = _ghi_chi_phi(
        client, ctx, amount=2_000_000, method="CASH_SHIFT", operation_id=ma
    )
    assert lai.status_code == 200, lai.text
    assert lai.json()["repeated"] is True
    assert lai.json()["id"] == dau.json()["id"]

    assert _ca_hien_tai(client, ctx)["expected_cash_amount"] == 8_000_000
    ds = client.get(
        f"/api/expenses/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    assert ds["total"] == 1


def test_tien_ngoai_ket_bat_buoc_ghi_chu(client):
    ctx = seller_with_shop(client)
    res = _ghi_chi_phi(client, ctx, method="OUTSIDE", note=None)
    assert res.status_code == 400
    res = _ghi_chi_phi(client, ctx, method="OUTSIDE", note="Tiền túi riêng")
    assert res.status_code == 200, res.text


def test_ngay_chi_mac_dinh_hom_nay_va_khai_lui_duoc(client):
    ctx = seller_with_shop(client)
    res = _ghi_chi_phi(client, ctx)
    assert res.json()["expense_date"] == expense_service.today_vn().isoformat()

    hom_qua = (expense_service.today_vn() - timedelta(days=1)).isoformat()
    res = _ghi_chi_phi(client, ctx, expense_date=hom_qua)
    assert res.json()["expense_date"] == hom_qua


def test_server_tu_tinh_moc_ket_thuc_phan_bo(client):
    """Client chỉ gửi số tháng; quy tắc ngày chỉ được viết ở một chỗ."""
    ctx = seller_with_shop(client)
    res = _ghi_chi_phi(
        client,
        ctx,
        amount=30_000_000,
        expense_date="2026-08-15",
        amortize_months=3,
        category_id=None or _loai(client, ctx, "Thuê mặt bằng"),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["amortize_start_date"] == "2026-08-15"
    assert body["amortize_end_date"] == "2026-11-14"
    assert body["is_amortized"] is True


# ---------------------------------------------------------------------------
# 4. Gỡ khoản ghi nhầm
# ---------------------------------------------------------------------------

def test_go_duoc_khoan_khong_dung_ket(client):
    ctx = seller_with_shop(client)
    khoan = _ghi_chi_phi(client, ctx, method="TRANSFER").json()
    assert khoan["can_void"] is True

    res = client.post(
        f"/api/expenses/{ctx['shop_id']}/{khoan['id']}/void",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    ds = client.get(
        f"/api/expenses/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    assert ds["total"] == 0


def test_khong_go_duoc_khoan_da_lay_tien_tu_ca(client):
    """Két là sổ chỉ-ghi-thêm; ca có thể đã đóng với số đếm tay khớp rồi."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx, tien_dau_ca=10_000_000)
    khoan = _ghi_chi_phi(
        client, ctx, amount=1_000_000, method="CASH_SHIFT"
    ).json()
    assert khoan["can_void"] is False

    res = client.post(
        f"/api/expenses/{ctx['shop_id']}/{khoan['id']}/void",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 409, res.text
    assert _ca_hien_tai(client, ctx)["expected_cash_amount"] == 9_000_000


# ---------------------------------------------------------------------------
# 5. Nhắc chi phí cố định
# ---------------------------------------------------------------------------

def _mau(client, ctx, ten, so_tien, loai="Lương nhân viên"):
    res = client.post(
        f"/api/expense-templates/{ctx['shop_id']}",
        json={
            "category_id": _loai(client, ctx, loai),
            "name": ten,
            "amount": so_tien,
            "day_of_month": 5,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_nhac_theo_so_con_thieu_chu_khong_theo_co_da_ghi(client):
    """Lương trả làm hai đợt: tạm ứng rồi trả nốt.

    Dùng cờ đã-ghi/chưa-ghi thì lời nhắc tắt ngay sau lần tạm ứng và phần còn
    lại bị quên luôn.
    """
    ctx = seller_with_shop(client)
    mau = _mau(client, ctx, "Lương tháng", 5_000_000)

    def _nhac():
        res = client.get(
            f"/api/expense-reminders/{ctx['shop_id']}", headers=auth(ctx["token"])
        )
        assert res.status_code == 200, res.text
        return res.json()

    assert _nhac()["total_missing"] == 5_000_000

    _ghi_chi_phi(
        client,
        ctx,
        amount=2_000_000,
        method="TRANSFER",
        category_id=mau["category_id"],
        template_id=mau["id"],
    )
    con = _nhac()
    assert con["total_missing"] == 3_000_000
    assert con["items"][0]["paid_amount"] == 2_000_000

    _ghi_chi_phi(
        client,
        ctx,
        amount=3_000_000,
        method="TRANSFER",
        category_id=mau["category_id"],
        template_id=mau["id"],
    )
    assert _nhac()["total_missing"] == 0


def test_sua_mau_khong_dung_toi_khoan_da_ghi(client):
    """Mẫu chỉ là lời nhắc; khoản đã trả là chứng từ đã phát sinh."""
    ctx = seller_with_shop(client)
    mau = _mau(client, ctx, "Tiền nhà", 5_000_000, loai="Thuê mặt bằng")
    _ghi_chi_phi(
        client,
        ctx,
        amount=5_000_000,
        method="TRANSFER",
        category_id=mau["category_id"],
        template_id=mau["id"],
    )
    res = client.put(
        f"/api/expense-templates/{ctx['shop_id']}/{mau['id']}",
        json={"amount": 6_000_000},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text

    ds = client.get(
        f"/api/expenses/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    assert ds["expenses"][0]["amount"] == 5_000_000


# ---------------------------------------------------------------------------
# 6. Phân quyền
# ---------------------------------------------------------------------------

def test_nhan_vien_khong_xem_duoc_chi_phi_va_lai_rong(client):
    """MANAGER xem được doanh thu nhưng KHÔNG được xem chi phí/lãi ròng: biết
    lãi ròng là suy ngược ra được giá vốn."""
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx, staff_role="MANAGER")
    for duong in (
        f"/api/expenses/{ctx['shop_id']}",
        f"/api/expense-categories/{ctx['shop_id']}",
        f"/api/expense-templates/{ctx['shop_id']}",
        f"/api/expense-reminders/{ctx['shop_id']}",
        f"/api/reports/cashflow/{ctx['shop_id']}",
    ):
        res = client.get(duong, headers=auth(staff_token))
        assert res.status_code == 403, f"{duong} lộ cho nhân viên: {res.text}"


def test_nhan_vien_khong_ghi_duoc_chi_phi(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx, staff_role="MANAGER")
    res = client.post(
        f"/api/expenses/{ctx['shop_id']}",
        json={
            "category_id": _loai(client, ctx, "Điện nước"),
            "amount": 100_000,
            "method": "TRANSFER",
            "operation_id": _op(),
        },
        headers=auth(staff_token),
    )
    assert res.status_code == 403


def test_shop_khac_khong_doc_duoc_chi_phi(client):
    ctx = seller_with_shop(client)
    nguoi_la = seller_with_shop(client)
    res = client.get(
        f"/api/expenses/{ctx['shop_id']}", headers=auth(nguoi_la["token"])
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 7. Lợi nhuận ròng và dòng tiền
# ---------------------------------------------------------------------------

def _sp_co_gia_von(client, ctx, gia_ban, ton, gia_von):
    res = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("SP"),
            "price": gia_ban,
            "stock": ton,
            "category_id": ctx["category_id"],
            "cost_price": gia_von,
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _ban_va_thu_tien(client, ctx, product, qty=1):
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": product["id"],
                    "price": product["price"],
                    "quantity": qty,
                }
            ],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]
    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    return order_id


def test_lai_rong_bang_lai_gop_tru_chi_phi(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    sp = _sp_co_gia_von(client, ctx, gia_ban=100_000, ton=100, gia_von=60_000)
    _ban_va_thu_tien(client, ctx, sp, qty=10)  # lãi gộp 400.000

    truoc = _dong_tien(client, ctx)
    assert truoc["gross_profit"] == 400_000
    assert truoc["operating_expense_total"] == 0
    assert truoc["net_profit"] == 400_000

    _ghi_chi_phi(client, ctx, amount=150_000, method="TRANSFER")
    sau = _dong_tien(client, ctx)
    assert sau["operating_expense_total"] == 150_000
    assert sau["net_profit"] == 250_000


def test_tra_truoc_chi_vao_lai_mot_phan_nhung_tien_ra_du(client):
    """Trả trước 12 tháng: dòng tiền thấy đủ, lãi ròng chỉ chịu phần của kỳ."""
    ctx = seller_with_shop(client)
    hom_nay = expense_service.today_vn()
    res = _ghi_chi_phi(
        client,
        ctx,
        amount=12_000_000,
        method="TRANSFER",
        expense_date=hom_nay.isoformat(),
        amortize_months=12,
        category_id=_loai(client, ctx, "Thuê mặt bằng"),
    )
    assert res.status_code == 200, res.text

    bao_cao = _dong_tien(
        client, ctx, tu_ngay=hom_nay.isoformat(), den_ngay=hom_nay.isoformat()
    )
    # Một ngày trong ~365 ngày: chi phí tính vào lãi phải rất nhỏ...
    assert 0 < bao_cao["operating_expense_total"] < 100_000
    # ...trong khi tiền đã ra khỏi túi là đủ 12 triệu.
    assert bao_cao["cash_out_total"] == 12_000_000
    # Và phần chưa tính phải hiện ra thành số trả trước còn lại.
    assert bao_cao["prepaid_remaining"] > 11_000_000
    assert any(r["key"] == "prepaid" for r in bao_cao["difference_notes"])


def test_dong_tien_khong_dem_chi_phi_tien_mat_hai_lan(client):
    """Chi phí tiền mặt sinh một `CashMovement`. Cộng cả hai là ra 2x."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx, tien_dau_ca=10_000_000)
    _ghi_chi_phi(client, ctx, amount=4_000_000, method="CASH_SHIFT")

    bao_cao = _dong_tien(client, ctx)
    assert bao_cao["cash_out_total"] == 4_000_000, (
        f"Chi phí tiền mặt bị đếm hai lần: {bao_cao['cash_out_breakdown']}"
    )
    khoa = {r["key"] for r in bao_cao["cash_out_breakdown"]}
    assert khoa == {"expense"}


def test_dong_tien_thay_tien_ban_hang_vao(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    sp = _sp_co_gia_von(client, ctx, gia_ban=200_000, ton=50, gia_von=100_000)
    _ban_va_thu_tien(client, ctx, sp, qty=3)  # 600.000 tiền mặt

    bao_cao = _dong_tien(client, ctx)
    assert bao_cao["cash_in_total"] == 600_000
    assert bao_cao["net_cashflow"] == 600_000
    assert any(
        r["key"] == "sale_cash" and r["amount"] == 600_000
        for r in bao_cao["cash_in_breakdown"]
    )


def test_bieu_do_co_truc_ngay_lien_mach(client):
    ctx = seller_with_shop(client)
    hom_nay = expense_service.today_vn()
    dau = (hom_nay - timedelta(days=4)).isoformat()
    _ghi_chi_phi(client, ctx, amount=500_000, expense_date=hom_nay.isoformat())

    bao_cao = _dong_tien(client, ctx, tu_ngay=dau, den_ngay=hom_nay.isoformat())
    chart = bao_cao["chart"]
    assert chart["labels"] == [
        (hom_nay - timedelta(days=i)).isoformat() for i in range(4, -1, -1)
    ]
    assert len(chart["cash_in"]) == len(chart["labels"])
    assert len(chart["cash_out"]) == len(chart["labels"])
    assert len(chart["cumulative"]) == len(chart["labels"])
    assert chart["cumulative"][-1] == -500_000


def test_khoan_da_go_khong_con_trong_bao_cao(client):
    ctx = seller_with_shop(client)
    khoan = _ghi_chi_phi(client, ctx, amount=700_000, method="TRANSFER").json()
    assert _dong_tien(client, ctx)["operating_expense_total"] == 700_000

    client.post(
        f"/api/expenses/{ctx['shop_id']}/{khoan['id']}/void",
        headers=auth(ctx["token"]),
    )
    sau = _dong_tien(client, ctx)
    assert sau["operating_expense_total"] == 0
    assert sau["cash_out_total"] == 0


def test_hang_huy_khong_bi_tru_hai_lan(client):
    """Hàng hủy đã trừ vào lãi gộp; chi phí vận hành là một sổ KHÁC.

    Test này canh ranh giới: một phiếu hủy không được tự sinh khoản chi phí nào.
    """
    ctx = seller_with_shop(client)
    sp = _sp_co_gia_von(client, ctx, gia_ban=100_000, ton=20, gia_von=40_000)
    res = client.post(
        f"/api/products/{ctx['shop_id']}/write-off",
        json={
            "reason": "EXPIRED",
            "items": [{"product_id": sp["id"], "quantity": 5}],
            "operation_id": _op(),
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text

    bao_cao = _dong_tien(client, ctx)
    assert bao_cao["write_off_loss"] == 200_000
    assert bao_cao["operating_expense_total"] == 0, (
        "Hàng hủy không được đồng thời nằm trong sổ chi phí vận hành"
    )
    assert bao_cao["net_profit"] == -200_000
