"""C1a: schema cho nhân viên (role=STAFF, cột users.staff_shop_id).

Commit này CHỈ thêm schema và quan hệ ORM. Chưa có endpoint quản lý nhân viên,
chưa có phân quyền staff - những phần đó ở C1b/C1c/C1d.

Mục tiêu quan trọng nhất: xác nhận User có HAI khóa ngoại trỏ tới shops
(owner_id qua Shop, staff_shop_id trên User) mà SQLAlchemy vẫn map được,
không báo lỗi "ambiguous foreign keys".
"""
from sqlalchemy import text

from conftest import auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _cot_users(session):
    return {row[1] for row in session.execute(text("PRAGMA table_info(users)"))}


# ---------- Schema ----------
def test_cot_staff_shop_id_ton_tai(client, db):
    assert "staff_shop_id" in _cot_users(db)


def test_index_staff_shop_id_ton_tai(client, db):
    indexes = {row[1] for row in db.execute(text("PRAGMA index_list(users)"))}
    assert "ix_users_staff_shop_id" in indexes


def test_cac_cot_user_cu_van_nguyen(client, db):
    cols = _cot_users(db)
    assert {
        "id",
        "username",
        "hashed_password",
        "role",
        "email",
        "is_verified",
        "session_id",
    } <= cols


# ---------- Quan hệ ORM (điểm dễ vỡ) ----------
def test_hai_khoa_ngoai_toi_shops_khong_gay_mo_ho(client):
    """Tạo owner+shop, rồi tạo một STAFF gắn shop đó. Truy vấn lại và đọc
    CẢ hai quan hệ - nếu mapping mơ hồ, chỗ này sẽ ném lỗi."""
    ctx = seller_with_shop(client)

    session = SessionLocal()
    try:
        staff = models.User(
            username="staff_schema_test",
            hashed_password="x",
            role="STAFF",
            is_verified=True,
            staff_shop_id=ctx["shop_id"],
        )
        session.add(staff)
        session.commit()
        staff_id = staff.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        # Đọc quan hệ staff_shop (FK staff_shop_id)
        staff = session.query(models.User).filter(models.User.id == staff_id).first()
        assert staff.staff_shop is not None
        assert staff.staff_shop.id == ctx["shop_id"]

        # Đọc quan hệ owner.shops (FK owner_id) - phía còn lại phải vẫn hoạt động
        owner = (
            session.query(models.User)
            .filter(models.User.username == ctx["username"])
            .first()
        )
        assert any(s.id == ctx["shop_id"] for s in owner.shops)
        # Owner không phải staff của shop nào
        assert owner.staff_shop_id is None
    finally:
        session.close()


def test_shop_owner_relationship_van_hoat_dong(client):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        shop = session.query(models.Shop).filter(models.Shop.id == ctx["shop_id"]).first()
        assert shop.owner is not None
        assert shop.owner.username == ctx["username"]
    finally:
        session.close()


# ---------- Hành vi cũ KHÔNG đổi ----------
def test_user_moi_mac_dinh_khong_phai_staff(client):
    """Đăng ký thường vẫn tạo SELLER với staff_shop_id = NULL."""
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        user = (
            session.query(models.User)
            .filter(models.User.username == ctx["username"])
            .first()
        )
        assert user.role == "SELLER"
        assert user.staff_shop_id is None
    finally:
        session.close()


def test_dang_ky_va_dang_nhap_van_chay(client):
    """Smoke: luồng auth không bị schema mới làm hỏng."""
    ctx = seller_with_shop(client)
    res = client.get("/api/auth/session-check", headers=auth(ctx["token"]))
    assert res.status_code == 200
