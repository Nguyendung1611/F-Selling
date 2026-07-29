"""Migration nhẹ cho SQLite + seed tài khoản admin khi khởi động."""
from __future__ import annotations

import os
from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models
from .database import SessionLocal, engine
from .security import hash_password

# Các câu lệnh này chạy lặp lại được: nếu cột/index đã tồn tại thì bỏ qua.
_MIGRATIONS = [
    "ALTER TABLE shops ADD COLUMN is_active BOOLEAN DEFAULT 1",
    "ALTER TABLE products ADD COLUMN is_active BOOLEAN DEFAULT 1",
    "ALTER TABLE categories ADD COLUMN is_active BOOLEAN DEFAULT 1",
    "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email)",
    "ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 0",
    "ALTER TABLE users ADD COLUMN session_id VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN verification_code VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN verification_code_expires DATETIME",
    # A1a: tham chiếu sản phẩm trên từng dòng đơn hàng (phục vụ hoàn tồn kho khi hủy đơn).
    "ALTER TABLE order_items ADD COLUMN product_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_order_items_product_id ON order_items(product_id)",
    # C1a: nhân viên (role=STAFF) được gán vào đúng một shop. NULL với ADMIN/SELLER.
    "ALTER TABLE users ADD COLUMN staff_shop_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_users_staff_shop_id ON users(staff_shop_id)",
    # C2a: khách hàng gắn vào đơn (tùy chọn). Bảng `customers` do create_all() tự
    # tạo; ở đây chỉ cần thêm cột customer_id cho bảng orders đã tồn tại.
    "ALTER TABLE orders ADD COLUMN customer_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id)",
    # B1a: mã vạch sản phẩm. Duy nhất theo shop - SQLite coi mỗi NULL là một giá
    # trị khác nhau, nên nhiều sản phẩm chưa gán mã vạch vẫn cùng tồn tại được.
    "ALTER TABLE products ADD COLUMN barcode VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_shop_barcode "
    "ON products(shop_id, barcode)",
]

# Các index bắt buộc phải tồn tại sau khi migrate. `run_migrations` cố tình nuốt
# lỗi để chạy lặp lại được, nên một lệnh CREATE UNIQUE INDEX thất bại (ví dụ DB
# đang có sẵn dữ liệu trùng) sẽ trôi qua im lặng và app vẫn khởi động bình
# thường - rồi ràng buộc trùng lặp bị hổng mà không ai biết. Kiểm lại tường minh.
_REQUIRED_INDEXES = ["ix_products_shop_barcode"]

_INDEX_EXISTS = (
    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = :name"
)

# Backfill A1a: khớp dòng đơn hàng cũ với sản phẩm theo (shop của đơn, tên sản phẩm).
# An toàn vì `create_product` đảm bảo tên sản phẩm là duy nhất trong một shop,
# nên phép khớp này là xác định (không có nhiều ứng viên hợp lệ).
_BACKFILL_PRODUCT_ID = """
UPDATE order_items
SET product_id = (
    SELECT p.id
    FROM products p
    JOIN orders o ON o.id = order_items.order_id
    WHERE p.shop_id = o.shop_id
      AND p.name = order_items.product_name
)
WHERE product_id IS NULL
"""

_COUNT_MISSING_PRODUCT_ID = "SELECT COUNT(*) FROM order_items WHERE product_id IS NULL"


def create_tables() -> None:
    models.Base.metadata.create_all(bind=engine)


def run_migrations(db: Session) -> None:
    for statement in _MIGRATIONS:
        try:
            db.execute(text(statement))
            db.commit()
        except SQLAlchemyError:
            # Cột/index đã tồn tại - bỏ qua, đây là migration idempotent.
            db.rollback()


def verify_required_indexes(db: Session) -> List[str]:
    """Kiểm các index bắt buộc có thật sự tồn tại sau khi migrate.

    Trả về danh sách index bị thiếu (rỗng = mọi thứ ổn). Không ném exception:
    app vẫn phải khởi động được, nhưng lỗi phải hiện ra ở log chứ không im lặng.
    """
    missing: List[str] = []
    for name in _REQUIRED_INDEXES:
        try:
            found = db.execute(text(_INDEX_EXISTS), {"name": name}).scalar() or 0
        except SQLAlchemyError as e:
            print(f"[MIGRATE] Không kiểm được index '{name}': {e}")
            continue
        if not found:
            missing.append(name)

    if missing:
        print(
            "[MIGRATE] CẢNH BÁO: thiếu index "
            f"{', '.join(missing)} - ràng buộc trùng lặp KHÔNG được đảm bảo ở "
            "tầng database. Kiểm tra dữ liệu trùng rồi khởi động lại."
        )
    return missing


def backfill_order_item_product_id(db: Session) -> Tuple[int, int]:
    """Điền `order_items.product_id` cho các dòng cũ chỉ có `product_name`.

    Chạy lặp lại được: chỉ đụng vào dòng đang NULL, và dòng không khớp được
    (sản phẩm đã bị xóa hoặc đổi tên) sẽ giữ nguyên NULL.

    Trả về (số dòng vừa khớp được, số dòng vẫn còn NULL).
    """
    try:
        before_missing = db.execute(text(_COUNT_MISSING_PRODUCT_ID)).scalar() or 0
        if before_missing == 0:
            return 0, 0

        db.execute(text(_BACKFILL_PRODUCT_ID))
        db.commit()

        after_missing = db.execute(text(_COUNT_MISSING_PRODUCT_ID)).scalar() or 0
        filled = before_missing - after_missing
        if filled or after_missing:
            print(
                f"[MIGRATE] order_items.product_id: filled {filled}, "
                f"still unmatched {after_missing}"
            )
        return filled, after_missing
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[MIGRATE] Backfill order_items.product_id failed: {e}")
        return 0, 0


def seed_admin(db: Session) -> None:
    """Tự đồng bộ tài khoản admin theo ADMIN_INITIAL_PASSWORD trong .env.

    Muốn đặt/đổi mật khẩu admin: chỉ cần sửa ADMIN_INITIAL_PASSWORD rồi khởi động lại.
    Khi đã hài lòng với mật khẩu và muốn quản lý bằng chức năng "Đổi mật khẩu"
    trong app, chỉ cần XÓA dòng ADMIN_INITIAL_PASSWORD khỏi .env.
    """
    initial_password = os.getenv("ADMIN_INITIAL_PASSWORD")
    admin = db.query(models.User).filter(models.User.username == "admin").first()

    if initial_password and len(initial_password) >= 8:
        hashed_pw = hash_password(initial_password)
        if not admin:
            admin = models.User(
                username="admin", hashed_password=hashed_pw, role="ADMIN", is_verified=True
            )
            db.add(admin)
            print("[SEED] Created admin account from ADMIN_INITIAL_PASSWORD.")
        else:
            admin.hashed_password = hashed_pw
            admin.role = "ADMIN"
            admin.is_verified = True
            print("[SEED] Synchronized admin password from ADMIN_INITIAL_PASSWORD.")
        db.commit()
    elif not admin:
        print("[SEED] Skipped admin: ADMIN_INITIAL_PASSWORD must contain at least 8 characters.")


def initialize() -> None:
    """Chạy khi app khởi động: tạo bảng, migrate, seed admin."""
    create_tables()
    db = SessionLocal()
    try:
        run_migrations(db)
        verify_required_indexes(db)
        backfill_order_item_product_id(db)
        seed_admin(db)
    finally:
        db.close()
