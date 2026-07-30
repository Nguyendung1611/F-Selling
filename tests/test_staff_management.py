"""C1b: chủ shop tạo / xem / xóa / đặt lại mật khẩu nhân viên.

Commit này CHỈ quản lý tài khoản nhân viên. Việc staff đăng nhập và được cấp
quyền truy cập shop là C1c/C1d - nên ở đây chưa test staff gọi API nghiệp vụ.
"""
from conftest import ADMIN_PASSWORD, auth, create_shop, login, new_seller, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal

STAFF_PW = "Nhanvien@2026"


def _tao_nv(client, token, shop_id, username="nv_test", password=STAFF_PW):
    return client.post(
        f"/api/staff/{shop_id}",
        json={"username": username, "password": password},
        headers=auth(token),
    )


# ---------- Tạo ----------
def test_chu_shop_tao_duoc_nhan_vien(client):
    ctx = seller_with_shop(client)
    res = _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv_an")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {
        "id", "username", "shop_id", "is_active", "staff_role"
    }
    assert body["username"] == "nv_an"
    assert body["shop_id"] == ctx["shop_id"]
    assert body["staff_role"] == "MANAGER"

    session = SessionLocal()
    try:
        nv = session.query(models.User).filter(models.User.username == "nv_an").first()
        assert nv.role == "STAFF"
        assert nv.staff_role == "MANAGER"
        assert nv.staff_shop_id == ctx["shop_id"]
        assert nv.is_verified is True
        assert nv.email is None
    finally:
        session.close()


def test_tao_nv_mat_khau_yeu_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = _tao_nv(client, ctx["token"], ctx["shop_id"], password="abcdefgh")
    assert res.status_code == 400


def test_tao_nv_username_rong(client):
    ctx = seller_with_shop(client)
    res = _tao_nv(client, ctx["token"], ctx["shop_id"], username="   ")
    assert res.status_code == 400


def test_tao_nv_trung_username(client):
    ctx = seller_with_shop(client)
    _tao_nv(client, ctx["token"], ctx["shop_id"], username="trung")
    res = _tao_nv(client, ctx["token"], ctx["shop_id"], username="trung")
    assert res.status_code == 400


def test_khong_trung_username_voi_seller_dang_co(client):
    ctx = seller_with_shop(client)
    res = _tao_nv(client, ctx["token"], ctx["shop_id"], username=ctx["username"])
    assert res.status_code == 400


# ---------- Quyền tạo ----------
def test_seller_khac_khong_tao_duoc_nv_cho_shop_nguoi_ta(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = _tao_nv(client, token_b, ctx["shop_id"], username="lau")
    assert res.status_code == 404  # require_own_shop trả 404, không lộ shop tồn tại

    session = SessionLocal()
    try:
        assert session.query(models.User).filter(models.User.username == "lau").first() is None
    finally:
        session.close()


def test_admin_khong_phai_chu_shop_khong_tao_duoc_nv(client):
    """require_own_shop chỉ chấp nhận đúng chủ shop, admin cũng nhận 404."""
    ctx = seller_with_shop(client)
    admin_tok = login(client, "admin", ADMIN_PASSWORD)
    res = _tao_nv(client, admin_tok, ctx["shop_id"], username="nv_admin")
    assert res.status_code == 404


def test_chua_dang_nhap_khong_tao_duoc(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/staff/{ctx['shop_id']}", json={"username": "x", "password": STAFF_PW}
    )
    assert res.status_code == 401


# ---------- Danh sách ----------
def test_liet_ke_nhan_vien_cua_shop(client):
    ctx = seller_with_shop(client)
    _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv1")
    _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv2")

    res = client.get(f"/api/staff/{ctx['shop_id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200
    tens = {s["username"] for s in res.json()}
    assert tens == {"nv1", "nv2"}


def test_danh_sach_khong_lan_nhan_vien_shop_khac(client):
    a = seller_with_shop(client)
    _tao_nv(client, a["token"], a["shop_id"], username="nv_shopA")

    _, token_b = new_seller(client)
    shop_b = create_shop(client, token_b)
    _tao_nv(client, token_b, shop_b, username="nv_shopB")

    res_a = client.get(f"/api/staff/{a['shop_id']}", headers=auth(a["token"]))
    assert {s["username"] for s in res_a.json()} == {"nv_shopA"}


def test_seller_khac_khong_xem_duoc_danh_sach_nv(client):
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.get(f"/api/staff/{ctx['shop_id']}", headers=auth(token_b))
    assert res.status_code == 404


# ---------- Xóa ----------
def test_chu_shop_xoa_duoc_nhan_vien(client):
    ctx = seller_with_shop(client)
    nv_id = _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv_xoa").json()["id"]

    res = client.delete(f"/api/staff/member/{nv_id}", headers=auth(ctx["token"]))
    assert res.status_code == 200

    session = SessionLocal()
    try:
        nv = session.query(models.User).filter(models.User.id == nv_id).first()
        assert nv is not None, "Giữ hồ sơ để lịch sử ca/đơn còn tên thu ngân"
        assert nv.is_active is False
    finally:
        session.close()

    listed = client.get(
        f"/api/staff/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).json()
    assert all(item["id"] != nv_id for item in listed)
    disabled_login = client.post(
        "/api/auth/login",
        json={"username": "nv_xoa", "password": STAFF_PW},
    )
    assert disabled_login.status_code == 403


def test_seller_khac_khong_xoa_duoc_nv(client):
    ctx = seller_with_shop(client)
    nv_id = _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv_giu").json()["id"]

    _, token_b = new_seller(client)
    res = client.delete(f"/api/staff/member/{nv_id}", headers=auth(token_b))
    assert res.status_code == 404

    session = SessionLocal()
    try:
        assert session.query(models.User).filter(models.User.id == nv_id).first() is not None
    finally:
        session.close()


def test_khong_ngung_tai_khoan_khi_nhan_vien_con_ca_mo(client):
    ctx = seller_with_shop(client)
    staff = _tao_nv(
        client, ctx["token"], ctx["shop_id"], username="nv_con_ca"
    ).json()
    staff_token = login(client, "nv_con_ca", STAFF_PW)
    shift = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": 0},
        headers=auth(staff_token),
    ).json()

    blocked = client.delete(
        f"/api/staff/member/{staff['id']}", headers=auth(ctx["token"])
    )
    assert blocked.status_code == 409
    assert "kết ca" in blocked.json()["detail"]

    assert client.post(
        f"/api/shifts/{shift['id']}/close",
        json={"counted_cash_amount": 0},
        headers=auth(staff_token),
    ).status_code == 200
    assert client.delete(
        f"/api/staff/member/{staff['id']}", headers=auth(ctx["token"])
    ).status_code == 200


def test_xoa_nv_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    res = client.delete("/api/staff/member/999999", headers=auth(ctx["token"]))
    assert res.status_code == 404


def test_khong_xoa_duoc_seller_qua_endpoint_staff(client):
    """Endpoint staff chỉ đụng role=STAFF, không được xóa nhầm một SELLER."""
    ctx = seller_with_shop(client)
    _, token_b = new_seller(client)
    session = SessionLocal()
    try:
        seller_b = session.query(models.User).filter(
            models.User.role == "SELLER"
        ).order_by(models.User.id.desc()).first()
        seller_b_id = seller_b.id
    finally:
        session.close()

    res = client.delete(f"/api/staff/member/{seller_b_id}", headers=auth(ctx["token"]))
    assert res.status_code == 404, "Không được nhận diện SELLER là nhân viên"


# ---------- Đặt lại mật khẩu ----------
def test_chu_shop_dat_lai_mat_khau_nv(client):
    ctx = seller_with_shop(client)
    nv_id = _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv_pw").json()["id"]

    res = client.put(
        f"/api/staff/member/{nv_id}/password",
        json={"new_password": "MoiMoi@2026"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200


def test_dat_lai_mat_khau_yeu_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    nv_id = _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv_pw2").json()["id"]

    res = client.put(
        f"/api/staff/member/{nv_id}/password",
        json={"new_password": "yeu"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_seller_khac_khong_dat_lai_mat_khau_nv(client):
    ctx = seller_with_shop(client)
    nv_id = _tao_nv(client, ctx["token"], ctx["shop_id"], username="nv_pw3").json()["id"]

    _, token_b = new_seller(client)
    res = client.put(
        f"/api/staff/member/{nv_id}/password",
        json={"new_password": "MoiMoi@2026"},
        headers=auth(token_b),
    )
    assert res.status_code == 404
