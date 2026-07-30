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
    "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN session_id VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN verification_code VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN verification_code_expires DATETIME",
    # A1a: tham chiếu sản phẩm trên từng dòng đơn hàng (phục vụ hoàn tồn kho khi hủy đơn).
    "ALTER TABLE order_items ADD COLUMN product_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_order_items_product_id ON order_items(product_id)",
    # C1a: nhân viên (role=STAFF) được gán vào đúng một shop. NULL với ADMIN/SELLER.
    "ALTER TABLE users ADD COLUMN staff_shop_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_users_staff_shop_id ON users(staff_shop_id)",
    # Preset quyền cho STAFF. Backfill MANAGER giữ nguyên quyền vận hành rộng
    # của mọi tài khoản nhân viên đã được tạo trước khi có RBAC.
    "ALTER TABLE users ADD COLUMN staff_role VARCHAR(20)",
    "UPDATE users SET staff_role = 'MANAGER' "
    "WHERE role = 'STAFF' AND staff_role IS NULL",
    # C2a: khách hàng gắn vào đơn (tùy chọn). Bảng `customers` do create_all() tự
    # tạo; ở đây chỉ cần thêm cột customer_id cho bảng orders đã tồn tại.
    "ALTER TABLE orders ADD COLUMN customer_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id)",
    # B1a: mã vạch sản phẩm. Duy nhất theo shop - SQLite coi mỗi NULL là một giá
    # trị khác nhau, nên nhiều sản phẩm chưa gán mã vạch vẫn cùng tồn tại được.
    "ALTER TABLE products ADD COLUMN barcode VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_shop_barcode "
    "ON products(shop_id, barcode)",
    # B1c: mã nội bộ cũng phải duy nhất theo shop. PHẢI chạy sau
    # dedupe_product_codes(), nếu không lệnh này thất bại vì dữ liệu còn trùng.
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_shop_code "
    "ON products(shop_id, code)",
    # B1d: tên sản phẩm cũng phải duy nhất theo shop. `create_product` và
    # `update_product` đã từ chối tên trùng từ lâu, nhưng không có ràng buộc ở
    # DB nên hai request đồng thời vẫn lọt được - và lọt trong IM LẶNG.
    # CỐ Ý không có bước dồn dữ liệu tự động như với `code`: tên sản phẩm là dữ
    # liệu do người dùng đặt, tự ý đổi thành "... (2)" là quyết định không nên
    # thay họ. DB nào còn tên trùng thì lệnh này thất bại và
    # verify_required_indexes() sẽ nêu tên index bị thiếu để người vận hành tự
    # sửa - vẫn hơn hẳn tình trạng hiện nay là không có ràng buộc nào cả.
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_shop_name "
    "ON products(shop_id, name)",
    # D1: lưu vết tiền thực nhận từ webhook ngân hàng. CỐ Ý không unique trên
    # bank_txn_id: ngân hàng gửi lại cùng một giao dịch là chuyện bình thường,
    # và việc chống xử lý lặp đã do máy trạng thái đảm nhiệm.
    "ALTER TABLE orders ADD COLUMN paid_amount FLOAT",
    "ALTER TABLE orders ADD COLUMN bank_txn_id VARCHAR(128)",
    "CREATE INDEX IF NOT EXISTS ix_orders_bank_txn_id ON orders(bank_txn_id)",
    # D4: đối soát cộng dồn, bù tiền mặt và hoàn tiền thừa. Bảng
    # `order_payments` do create_all() tạo; các ALTER dưới đây dành cho DB cũ.
    "ALTER TABLE orders ADD COLUMN cash_paid_amount FLOAT NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN refunded_amount FLOAT NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN refund_due_amount FLOAT NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN refund_completed_at DATETIME",
    "ALTER TABLE orders ADD COLUMN refund_completed_by INTEGER",
    "ALTER TABLE orders ADD COLUMN refund_method VARCHAR(20)",
    "ALTER TABLE orders ADD COLUMN refund_note VARCHAR(500)",
    "ALTER TABLE orders ADD COLUMN refund_reference VARCHAR(128)",
    "ALTER TABLE orders ADD COLUMN reconciliation_reason VARCHAR(32)",
    "ALTER TABLE order_payments ADD COLUMN reference VARCHAR(128)",
    "ALTER TABLE order_payments ADD COLUMN provider VARCHAR(32)",
    "CREATE INDEX IF NOT EXISTS ix_orders_reconciliation_reason "
    "ON orders(reconciliation_reason)",
    "CREATE INDEX IF NOT EXISTS ix_order_payments_order_id "
    "ON order_payments(order_id)",
    # CỐ Ý không unique bank_txn_id. Một mã thô chỉ dùng để tra cứu; ngân hàng
    # retry được chặn bằng khóa idempotency đã chuẩn hóa bên dưới.
    "CREATE INDEX IF NOT EXISTS ix_order_payments_bank_txn_id "
    "ON order_payments(bank_txn_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_order_payments_idempotency_key "
    "ON order_payments(idempotency_key)",
    # Không đoán UNRECONCILED cũ là thiếu tiền hay tiền về sau khi hủy. Đưa vào
    # hàng chờ kiểm tra legacy để tuyệt đối không tự PAID khi webhook tiếp theo về.
    "UPDATE orders SET reconciliation_reason = 'LEGACY_REVIEW' "
    "WHERE status = 'UNRECONCILED' AND reconciliation_reason IS NULL",
    # Phân loại phần lớn đơn đối soát cũ từ audit đã có. LATE ưu tiên cao hơn
    # UNDERPAID vì tuyệt đối không được hồi sinh đơn từng hủy.
    "UPDATE orders SET reconciliation_reason = 'LATE_PAYMENT', "
    "refund_due_amount = MAX("
    "COALESCE(paid_amount, 0) + COALESCE(cash_paid_amount, 0) "
    "- COALESCE(refunded_amount, 0), 0) "
    "WHERE status = 'UNRECONCILED' "
    "AND reconciliation_reason = 'LEGACY_REVIEW' "
    "AND EXISTS (SELECT 1 FROM system_logs l "
    "WHERE l.action = 'WEBHOOK_UNRECONCILED' "
    "AND l.details LIKE 'Order ' || orders.id || ':%')",
    "UPDATE orders SET reconciliation_reason = 'UNDERPAID', "
    "refund_due_amount = 0 "
    "WHERE status = 'UNRECONCILED' "
    "AND reconciliation_reason = 'LEGACY_REVIEW' "
    "AND EXISTS (SELECT 1 FROM system_logs l "
    "WHERE l.action = 'WEBHOOK_THIEU_TIEN' "
    "AND l.details LIKE 'Order ' || orders.id || ':%')",
    # Đơn tiền mặt đã PAID từ bản cũ chưa có cash_paid_amount. Backfill để một
    # khoản ngân hàng đến sau được nhận đúng là tiền dư, không phải tiền đầu tiên.
    "UPDATE orders SET cash_paid_amount = total_amount "
    "WHERE status = 'PAID' AND payment_method = 'cash' "
    "AND COALESCE(cash_paid_amount, 0) = 0 AND paid_amount IS NULL",
    # Bản cũ đã ghi paid_amount khi khách chuyển thừa nhưng chưa có trạng thái
    # hoàn tiền. Đưa phần dư còn thấy được vào hàng chờ hoàn.
    "UPDATE orders SET reconciliation_reason = 'OVERPAID', "
    "refund_due_amount = paid_amount - total_amount "
    "WHERE status = 'PAID' AND paid_amount > total_amount "
    "AND COALESCE(refunded_amount, 0) = 0 "
    "AND COALESCE(refund_due_amount, 0) = 0",
    # E1: ca thu ngân server-side. Hai bảng cash_shifts/cash_movements được
    # create_all() tạo mới; các ALTER này nâng cấp orders/order_payments cũ.
    "ALTER TABLE orders ADD COLUMN created_by_user_id INTEGER",
    "ALTER TABLE orders ADD COLUMN shift_id INTEGER",
    "ALTER TABLE orders ADD COLUMN cash_tendered_amount FLOAT",
    "ALTER TABLE orders ADD COLUMN cash_change_amount FLOAT",
    "ALTER TABLE orders ADD COLUMN operation_id VARCHAR(128)",
    "ALTER TABLE orders ADD COLUMN operation_fingerprint VARCHAR(64)",
    "ALTER TABLE order_payments ADD COLUMN shift_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_orders_created_by_user_id "
    "ON orders(created_by_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_shift_id ON orders(shift_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_payments_shift_id "
    "ON order_payments(shift_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_operation_id "
    "ON orders(operation_id)",
    "CREATE INDEX IF NOT EXISTS ix_cash_shifts_shop_id ON cash_shifts(shop_id)",
    "CREATE INDEX IF NOT EXISTS ix_cash_shifts_opened_by_user_id "
    "ON cash_shifts(opened_by_user_id)",
    # Nhiều người được mở ca trong cùng shop; duy nhất chỉ theo cặp shop + user
    # và chỉ trên ca OPEN để không chặn lịch sử.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_cash_shifts_shop_user_open "
    "ON cash_shifts(shop_id, opened_by_user_id) WHERE status = 'OPEN'",
    "CREATE INDEX IF NOT EXISTS ix_cash_movements_shift_id "
    "ON cash_movements(shift_id)",
    "CREATE INDEX IF NOT EXISTS ix_cash_movements_order_id "
    "ON cash_movements(order_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_cash_movements_operation_id "
    "ON cash_movements(operation_id)",
]

# Các index bắt buộc phải tồn tại sau khi migrate. `run_migrations` cố tình nuốt
# lỗi để chạy lặp lại được, nên một lệnh CREATE UNIQUE INDEX thất bại (ví dụ DB
# đang có sẵn dữ liệu trùng) sẽ trôi qua im lặng và app vẫn khởi động bình
# thường - rồi ràng buộc trùng lặp bị hổng mà không ai biết. Kiểm lại tường minh.
_REQUIRED_INDEXES = [
    "ix_products_shop_barcode",
    "ix_products_shop_code",
    "ix_products_shop_name",
    "ux_order_payments_idempotency_key",
    "ux_orders_operation_id",
    "ux_cash_shifts_shop_user_open",
    "ux_cash_movements_operation_id",
]

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

# Dedupe B1c: mã nội bộ trùng nhau trong cùng một shop.
# Nguyên nhân: bản cũ sinh mã bằng `SP-<timestamp giây>` nên mọi sản phẩm được
# tạo trong cùng một giây đều mang chung một mã, và sửa sản phẩm không hề kiểm
# trùng. Mã trùng làm việc tra cứu theo mã trở nên vô nghĩa.
#
# Quy tắc: trong mỗi nhóm trùng, sản phẩm có id NHỎ NHẤT được giữ mã (thường là
# cái được tạo trước, nhiều khả năng đã in ra nhãn/phiếu); các sản phẩm còn lại
# nhận mã mới `SP-<id>`. Chỉ đụng vào đúng những dòng đang trùng.
_DEDUPE_PRODUCT_CODES = """
UPDATE products
SET code = 'SP-' || id
WHERE EXISTS (
    SELECT 1 FROM products cu
    WHERE cu.shop_id = products.shop_id
      AND cu.code = products.code
      AND cu.id < products.id
)
"""

# Sản phẩm không có mã: unique index của SQLite bỏ qua NULL nên NULL không gây
# xung đột, nhưng chuỗi rỗng thì có. Gán luôn mã thật cho chúng.
_FILL_EMPTY_PRODUCT_CODES = """
UPDATE products SET code = 'SP-' || id
WHERE code IS NULL OR TRIM(code) = ''
"""

_COUNT_DUPLICATE_CODES = """
SELECT COUNT(*) FROM products p
WHERE EXISTS (
    SELECT 1 FROM products q
    WHERE q.shop_id = p.shop_id AND q.code = p.code AND q.id < p.id
)
"""

_COUNT_EMPTY_CODES = "SELECT COUNT(*) FROM products WHERE code IS NULL OR TRIM(code) = ''"

# D4: ledger ra đời sau hai cột legacy trên orders. Mỗi đơn cũ có đủ mã giao
# dịch được tạo đúng một dòng để retry mã cũ vẫn bị nhận ra kể cả sau khi
# orders.bank_txn_id đã được cập nhật bởi một giao dịch mới.
_BACKFILL_LEGACY_ORDER_PAYMENTS = """
INSERT INTO order_payments (
    order_id, entry_type, amount, idempotency_key, provider,
    bank_txn_id, account_no, note, created_at
)
SELECT
    o.id, 'BANK_IN', o.paid_amount, 'legacy-order:' || o.id, 'legacy',
    o.bank_txn_id, s.bank_account_no,
    'Dữ liệu ngân hàng trước khi có sổ giao dịch',
    COALESCE(o.created_at, CURRENT_TIMESTAMP)
FROM orders o
LEFT JOIN shops s ON s.id = o.shop_id
WHERE o.paid_amount > 0
  AND o.bank_txn_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM order_payments p
      WHERE p.order_id = o.id
        AND p.entry_type = 'BANK_IN'
        AND p.bank_txn_id = o.bank_txn_id
  )
"""


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


def dedupe_product_codes(db: Session) -> Tuple[int, int]:
    """Dọn mã sản phẩm trùng/rỗng để `ix_products_shop_code` tạo được.

    PHẢI chạy TRƯỚC `run_migrations`: `CREATE UNIQUE INDEX` sẽ thất bại nếu dữ
    liệu còn trùng, và `run_migrations` nuốt lỗi nên thất bại đó sẽ không ai
    thấy (chỉ còn `verify_required_indexes` cảnh báo).

    Chạy lặp lại được: lần thứ hai không còn dòng nào trùng để sửa.
    Trả về (số mã trùng đã đổi, số mã rỗng đã điền).
    """
    try:
        trung = db.execute(text(_COUNT_DUPLICATE_CODES)).scalar() or 0
        rong = db.execute(text(_COUNT_EMPTY_CODES)).scalar() or 0
        if not trung and not rong:
            return 0, 0

        if trung:
            db.execute(text(_DEDUPE_PRODUCT_CODES))
        if rong:
            db.execute(text(_FILL_EMPTY_PRODUCT_CODES))
        db.commit()

        print(
            f"[MIGRATE] products.code: doi {trung} ma trung, dien {rong} ma rong"
        )
        return trung, rong
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[MIGRATE] Dedupe products.code failed: {e}")
        return 0, 0


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


def backfill_legacy_order_payments(db: Session) -> int:
    """Đưa dấu vết ngân hàng legacy vào ledger, chạy lặp lại không sinh trùng."""
    try:
        result = db.execute(text(_BACKFILL_LEGACY_ORDER_PAYMENTS))
        db.commit()
        inserted = max(result.rowcount or 0, 0)
        if inserted:
            print(f"[MIGRATE] order_payments: backfill {inserted} giao dịch legacy")
        return inserted
    except SQLAlchemyError as e:
        db.rollback()
        print(f"[MIGRATE] Backfill order_payments failed: {e}")
        return 0


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
        # Dọn dữ liệu trùng trước, rồi mới tạo unique index trên đó.
        dedupe_product_codes(db)
        run_migrations(db)
        missing_indexes = verify_required_indexes(db)
        financial_indexes = {
            "ux_order_payments_idempotency_key",
            "ux_orders_operation_id",
            "ux_cash_shifts_shop_user_open",
            "ux_cash_movements_operation_id",
        }
        missing_financial_indexes = financial_indexes.intersection(missing_indexes)
        if missing_financial_indexes:
            raise RuntimeError(
                "Thiếu unique index bảo vệ sổ tiền: "
                f"{', '.join(sorted(missing_financial_indexes))}; "
                "dừng khởi động để tránh ghi trùng"
            )
        backfill_legacy_order_payments(db)
        backfill_order_item_product_id(db)
        seed_admin(db)
    finally:
        db.close()
