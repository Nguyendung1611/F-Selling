"""Migration nhẹ cho SQLite + seed tài khoản admin khi khởi động."""
from __future__ import annotations

import os
from typing import Tuple

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
]

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
        backfill_order_item_product_id(db)
        seed_admin(db)
    finally:
        db.close()
