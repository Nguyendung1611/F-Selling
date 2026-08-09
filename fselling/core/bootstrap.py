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
    # F1: giá vốn để tính lãi gộp. CỐ Ý để NULL thay vì DEFAULT 0 - "chưa ai khai
    # giá vốn" và "hàng được tặng, giá vốn bằng 0" là hai chuyện khác hẳn nhau.
    # Gộp lại thì mọi sản phẩm cũ bỗng có lãi bằng đúng giá bán, và chủ shop mở
    # dashboard ra tin là thật. Backfill cũng vì vậy mà KHÔNG có: đơn bán trước
    # migration này không có cơ sở nào để biết giá vốn, báo cáo phải đếm riêng
    # và nói ra, chứ không được đoán.
    "ALTER TABLE products ADD COLUMN cost_price FLOAT",
    "ALTER TABLE order_items ADD COLUMN cost_price FLOAT",
    # F2: trả hàng. Hai bảng order_returns/order_return_items do create_all()
    # tạo mới nên không cần ALTER; các index dưới đây phục vụ báo cáo lọc theo
    # shop + NGÀY TRẢ và tra lịch sử trả của một đơn.
    "CREATE INDEX IF NOT EXISTS ix_order_returns_order_id "
    "ON order_returns(order_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_returns_shop_id_created_at "
    "ON order_returns(shop_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_order_return_items_return_id "
    "ON order_return_items(return_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_return_items_order_item_id "
    "ON order_return_items(order_item_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_order_returns_idempotency_key "
    "ON order_returns(idempotency_key)",
    # F3: chống dò mật khẩu và dò mã OTP. Bộ đếm để trong DB chứ không trong bộ
    # nhớ tiến trình - restart là kẻ tấn công được xóa bộ đếm, mà restart thì họ
    # ép được.
    "ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN locked_until DATETIME",
    "ALTER TABLE users ADD COLUMN verification_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN verification_code_sent_at DATETIME",
    # F4: bán ghi nợ. NULL = không giới hạn, giữ nguyên hành vi cho khách cũ.
    "ALTER TABLE customers ADD COLUMN credit_limit FLOAT",
    "CREATE INDEX IF NOT EXISTS ix_orders_status_customer "
    "ON orders(status, customer_id)",
    # F5: lô hàng + hạn sử dụng. Hai bảng product_batches/order_item_batches do
    # create_all() tạo mới; cờ dưới đây mặc định TẮT nên mọi sản phẩm đang có
    # giữ nguyên hành vi cũ.
    "ALTER TABLE products ADD COLUMN track_batches BOOLEAN NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS ix_product_batches_product_expiry "
    "ON product_batches(product_id, expiry_date)",
    "CREATE INDEX IF NOT EXISTS ix_order_item_batches_order_item_id "
    "ON order_item_batches(order_item_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_item_batches_batch_id "
    "ON order_item_batches(batch_id)",
    # F6: biến thể (size/màu). Mỗi biến thể vẫn là một dòng products đầy đủ, nên
    # hai cột này là toàn bộ phần lược đồ phải thêm - không có bảng mới, không
    # có backfill, và mọi sản phẩm đang có giữ nguyên NULL nghĩa là "đơn lẻ".
    "ALTER TABLE products ADD COLUMN variant_group VARCHAR(200)",
    "ALTER TABLE products ADD COLUMN variant_name VARCHAR(100)",
    "CREATE INDEX IF NOT EXISTS ix_products_shop_variant_group "
    "ON products(shop_id, variant_group)",
    # Hai biến thể trùng tên trong cùng một nhóm là lỗi nhập liệu, và nếu lọt
    # thì thu ngân không phân biệt được hai ô giống hệt nhau trên lưới POS.
    # SQLite coi mỗi NULL là một giá trị KHÁC NHAU nên vô số sản phẩm đơn lẻ
    # (cả hai cột NULL) vẫn cùng tồn tại được dưới index này.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_products_shop_variant "
    "ON products(shop_id, variant_group, variant_name)",
    # F6: phiếu hủy hàng. Hai bảng do create_all() tạo mới nên không cần ALTER.
    # Index theo (shop, ngày tạo) vì báo cáo luôn hỏi "shop này lỗ bao nhiêu vì
    # hủy hàng trong khoảng ngày nào".
    "CREATE INDEX IF NOT EXISTS ix_stock_write_offs_shop_created "
    "ON stock_write_offs(shop_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_stock_write_off_items_write_off_id "
    "ON stock_write_off_items(write_off_id)",
    # Bấm hai lần là TRỪ KHO HAI LẦN. Chống lặp bằng khóa riêng như phiếu trả
    # hàng, không dựa vào máy trạng thái (phiếu hủy không có trạng thái nào).
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_write_offs_idempotency_key "
    "ON stock_write_offs(idempotency_key)",
    # G2: bán khi mất mạng. Đơn offline KHÁC HẲN đơn thường ở chỗ giao dịch đã
    # xảy ra rồi, ở một mức giá đã biết - server chỉ đang được báo lại. Bốn cột
    # dưới đây giữ đúng những gì `create_order` vốn tự quyết:
    #   offline_uuid    - máy bán sinh, chống ghi hai lần khi sync lặp
    #   sold_offline_at - GIỜ BÁN, không phải giờ sync (ca thu ngân dựa vào đây)
    #   offline_issue   - vướng gì lúc ghi, để nổi lên màn Đối Soát
    #   offline_device  - máy nào bán, chủ shop cần biết để đi hỏi
    "ALTER TABLE orders ADD COLUMN offline_uuid VARCHAR(64)",
    "ALTER TABLE orders ADD COLUMN sold_offline_at DATETIME",
    "ALTER TABLE orders ADD COLUMN offline_issue VARCHAR(120)",
    "ALTER TABLE orders ADD COLUMN offline_device VARCHAR(64)",
    # Index này bảo vệ SỔ TIỀN: thiếu nó thì hai lần sync cùng một phiếu đẻ ra
    # hai đơn, doanh thu và tồn kho đều nhân đôi. Vì vậy nó nằm trong cả
    # _REQUIRED_INDEXES lẫn financial_indexes - thiếu là app KHÔNG khởi động.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_offline_uuid "
    "ON orders(offline_uuid)",
    "CREATE INDEX IF NOT EXISTS ix_orders_offline_issue ON orders(offline_issue)",
    # H1: chương trình tích điểm. Hai bảng loyalty_* do create_all() tạo mới;
    # các ALTER dưới đây nâng DB cũ mà tuyệt đối không backfill điểm cho đơn cũ.
    "ALTER TABLE customers ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
    "ALTER TABLE orders ADD COLUMN loyalty_points_redeemed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN loyalty_discount_amount FLOAT NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN loyalty_earn_amount_step FLOAT",
    "ALTER TABLE orders ADD COLUMN loyalty_earn_points_step INTEGER",
    "ALTER TABLE orders ADD COLUMN loyalty_expiry_days_snapshot INTEGER",
    "ALTER TABLE orders ADD COLUMN loyalty_points_earned INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN loyalty_awarded_at DATETIME",
    "ALTER TABLE order_returns ADD COLUMN loyalty_points_restored INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE order_returns ADD COLUMN loyalty_points_reversed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE order_returns ADD COLUMN operation_fingerprint VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_loyalty_programs_shop_id "
    "ON loyalty_programs(shop_id)",
    # Điểm quy đổi ra tiền, nên retry mà ghi hai ledger entry là lỗi sổ tiền.
    # Index này phải được verify và fail-fast như payment idempotency.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_loyalty_point_entries_idempotency_key "
    "ON loyalty_point_entries(idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_loyalty_point_entries_customer_created "
    "ON loyalty_point_entries(customer_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_loyalty_point_entries_shop_created "
    "ON loyalty_point_entries(shop_id, created_at)",
    # I1: nhà cung cấp + phiếu nhập + công nợ phải trả. Các bảng mới do
    # create_all() tạo; khai lại mọi khóa chống lặp để DB cũ/khởi động lỗi dở
    # vẫn được tự chữa, rồi nhóm financial bên dưới kiểm đúng cả unique+cột.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_suppliers_create_operation_id "
    "ON suppliers(create_operation_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_purchase_receipts_create_operation_id "
    "ON purchase_receipts(create_operation_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_purchase_receipts_confirm_operation_id "
    "ON purchase_receipts(confirm_operation_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_payable_entries_idempotency_key "
    "ON supplier_payable_entries(idempotency_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_payable_entries_receipt_id "
    "ON supplier_payable_entries(receipt_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_payments_idempotency_key "
    "ON supplier_payments(idempotency_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_payment_allocations_pair "
    "ON supplier_payment_allocations(payment_id, payable_entry_id)",
    # J1: gói Free/Pro theo shop. Các bảng mới do create_all() tạo; khai lại
    # các unique để DB cũ/khởi động lỗi dở tự chữa, rồi verify fail-fast bên dưới.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_shop_subscriptions_shop_id "
    "ON shop_subscriptions(shop_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscription_grants_operation_id "
    "ON subscription_grants(operation_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscription_grants_revoke_operation_id "
    "ON subscription_grants(revoke_operation_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscription_checkouts_reference_code "
    "ON subscription_checkouts(reference_code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscription_checkouts_operation_id "
    "ON subscription_checkouts(operation_id)",
    "ALTER TABLE subscription_checkouts ADD COLUMN entitlement_starts_at DATETIME",
    "ALTER TABLE subscription_checkouts ADD COLUMN entitlement_ends_at DATETIME",
    "CREATE INDEX IF NOT EXISTS ix_subscription_checkouts_shop_entitlement "
    "ON subscription_checkouts(shop_id, entitlement_starts_at, entitlement_ends_at)",
    # Mã quá 24 giờ không còn là QR mở. Dọn trước khi dựng hàng rào một QR/shop.
    "UPDATE subscription_checkouts SET status = 'EXPIRED' "
    "WHERE status IN ('PENDING', 'UNDERPAID') "
    "AND activated_at IS NULL AND expires_at <= CURRENT_TIMESTAMP",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscription_checkouts_one_open_per_shop "
    "ON subscription_checkouts(shop_id) "
    "WHERE status IN ('PENDING', 'UNDERPAID')",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_subscription_payments_idempotency_key "
    "ON subscription_payments(idempotency_key)",
    # Log mới ghi thẳng shop_id để thao tác của ADMIN (tặng/thu hồi Pro) hiện
    # đúng ở "Ai Làm Gì" của shop đó mà không lẫn dữ liệu shop khác.
    "ALTER TABLE system_logs ADD COLUMN shop_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_system_logs_shop_id ON system_logs(shop_id)",
    # L4: bộ đếm lượt gọi Gemini của trợ lý. Bảng do create_all() tạo; index
    # duy nhất khai ở đây VÀ trong _REQUIRED_INDEXES vì thiếu nó thì hai
    # request cùng lúc đẻ ra hai dòng cho cùng một ngày và trần bị nhân đôi.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_assistant_ai_usage_shop_ngay "
    "ON assistant_ai_usage(shop_id, ngay)",
    # K1: chi phí vận hành + lãi ròng + dòng tiền. Ba bảng mới do create_all()
    # tạo; khai lại mọi khóa để DB cũ hoặc lần khởi động lỗi dở tự chữa được.
    # CỐ Ý không backfill gì: shop cũ bắt đầu với sổ chi phí rỗng, và lãi ròng
    # bằng đúng lãi gộp cho tới khi chủ shop khai khoản đầu tiên. Đoán chi phí
    # quá khứ là bịa ra một con số lỗ mà không ai kiểm chứng được.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_expense_categories_shop_name "
    "ON expense_categories(shop_id, name)",
    "CREATE INDEX IF NOT EXISTS ix_expense_categories_shop_active "
    "ON expense_categories(shop_id, is_active)",
    "CREATE INDEX IF NOT EXISTS ix_expense_templates_shop_active "
    "ON expense_templates(shop_id, is_active)",
    "CREATE INDEX IF NOT EXISTS ix_expense_templates_category_id "
    "ON expense_templates(category_id)",
    "CREATE INDEX IF NOT EXISTS ix_operating_expenses_shop_date "
    "ON operating_expenses(shop_id, expense_date)",
    "CREATE INDEX IF NOT EXISTS ix_operating_expenses_shop_amortize "
    "ON operating_expenses(shop_id, amortize_start_date, amortize_end_date)",
    "CREATE INDEX IF NOT EXISTS ix_operating_expenses_category_id "
    "ON operating_expenses(category_id)",
    "CREATE INDEX IF NOT EXISTS ix_operating_expenses_template_id "
    "ON operating_expenses(template_id)",
    "CREATE INDEX IF NOT EXISTS ix_operating_expenses_shift_id "
    "ON operating_expenses(shift_id)",
    # Bấm hai lần là trừ két hai lần. Cùng lớp bảo vệ với phiếu hủy hàng và
    # trả nhà cung cấp, nên index này nằm trong nhóm financial fail-fast.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_operating_expenses_idempotency_key "
    "ON operating_expenses(idempotency_key)",
]

# Các index bắt buộc phải tồn tại sau khi migrate. `run_migrations` cố tình nuốt
# lỗi để chạy lặp lại được, nên một lệnh CREATE UNIQUE INDEX thất bại (ví dụ DB
# đang có sẵn dữ liệu trùng) sẽ trôi qua im lặng và app vẫn khởi động bình
# thường - rồi ràng buộc trùng lặp bị hổng mà không ai biết. Kiểm lại tường minh.
_REQUIRED_INDEXES = [
    "ix_products_shop_barcode",
    "ix_products_shop_code",
    "ix_products_shop_name",
    "ux_products_shop_variant",
    "ux_order_payments_idempotency_key",
    "ux_orders_operation_id",
    "ux_cash_shifts_shop_user_open",
    "ux_cash_movements_operation_id",
    "ux_order_returns_idempotency_key",
    "ux_stock_write_offs_idempotency_key",
    "ux_orders_offline_uuid",
    "ux_loyalty_programs_shop_id",
    "ux_loyalty_point_entries_idempotency_key",
    "ux_suppliers_create_operation_id",
    "ux_assistant_ai_usage_shop_ngay",
    "ux_purchase_receipts_create_operation_id",
    "ux_purchase_receipts_confirm_operation_id",
    "ux_supplier_payable_entries_idempotency_key",
    "ux_supplier_payable_entries_receipt_id",
    "ux_supplier_payments_idempotency_key",
    "ux_supplier_payment_allocations_pair",
    "ux_shop_subscriptions_shop_id",
    "ux_subscription_grants_operation_id",
    "ux_subscription_grants_revoke_operation_id",
    "ux_subscription_checkouts_reference_code",
    "ux_subscription_checkouts_operation_id",
    "ux_subscription_checkouts_one_open_per_shop",
    "ux_subscription_payments_idempotency_key",
    "ux_expense_categories_shop_name",
    "ux_operating_expenses_idempotency_key",
]

# Thiếu/sai một index trong nhóm này thì tiếp tục chạy có thể nhân đôi tiền,
# tồn kho hoặc điểm. Không chỉ kiểm TÊN: cùng tên nhưng non-unique, trỏ
# nhầm cột, hay có mệnh đề WHERE sai cũng không bảo vệ được gì.
# Mỗi spec là (bảng, các cột, predicate). Predicate None nghĩa là index
# phải bao phủ TOÀN BỘ bảng; riêng ca thu ngân cố ý chỉ unique khi OPEN.
_FINANCIAL_INDEX_SPECS = {
    "ux_order_payments_idempotency_key": (
        "order_payments",
        ("idempotency_key",),
        None,
    ),
    "ux_orders_operation_id": ("orders", ("operation_id",), None),
    "ux_cash_shifts_shop_user_open": (
        "cash_shifts",
        ("shop_id", "opened_by_user_id"),
        "status = 'OPEN'",
    ),
    "ux_cash_movements_operation_id": (
        "cash_movements",
        ("operation_id",),
        None,
    ),
    "ux_order_returns_idempotency_key": (
        "order_returns",
        ("idempotency_key",),
        None,
    ),
    "ux_orders_offline_uuid": ("orders", ("offline_uuid",), None),
    "ux_loyalty_programs_shop_id": (
        "loyalty_programs",
        ("shop_id",),
        None,
    ),
    "ux_loyalty_point_entries_idempotency_key": (
        "loyalty_point_entries",
        ("idempotency_key",),
        None,
    ),
    "ux_suppliers_create_operation_id": (
        "suppliers",
        ("create_operation_id",),
        None,
    ),
    "ux_purchase_receipts_create_operation_id": (
        "purchase_receipts",
        ("create_operation_id",),
        None,
    ),
    "ux_purchase_receipts_confirm_operation_id": (
        "purchase_receipts",
        ("confirm_operation_id",),
        None,
    ),
    "ux_supplier_payable_entries_idempotency_key": (
        "supplier_payable_entries",
        ("idempotency_key",),
        None,
    ),
    "ux_supplier_payable_entries_receipt_id": (
        "supplier_payable_entries",
        ("receipt_id",),
        None,
    ),
    "ux_supplier_payments_idempotency_key": (
        "supplier_payments",
        ("idempotency_key",),
        None,
    ),
    "ux_supplier_payment_allocations_pair": (
        "supplier_payment_allocations",
        ("payment_id", "payable_entry_id"),
        None,
    ),
    "ux_shop_subscriptions_shop_id": (
        "shop_subscriptions",
        ("shop_id",),
        None,
    ),
    "ux_subscription_grants_operation_id": (
        "subscription_grants",
        ("operation_id",),
        None,
    ),
    "ux_subscription_grants_revoke_operation_id": (
        "subscription_grants",
        ("revoke_operation_id",),
        None,
    ),
    "ux_subscription_checkouts_reference_code": (
        "subscription_checkouts",
        ("reference_code",),
        None,
    ),
    "ux_subscription_checkouts_operation_id": (
        "subscription_checkouts",
        ("operation_id",),
        None,
    ),
    "ux_subscription_checkouts_one_open_per_shop": (
        "subscription_checkouts",
        ("shop_id",),
        "status IN ('PENDING', 'UNDERPAID')",
    ),
    "ux_subscription_payments_idempotency_key": (
        "subscription_payments",
        ("idempotency_key",),
        None,
    ),
    "ux_operating_expenses_idempotency_key": (
        "operating_expenses",
        ("idempotency_key",),
        None,
    ),
}
_FINANCIAL_INDEXES = frozenset(_FINANCIAL_INDEX_SPECS)

_INDEX_EXISTS = (
    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = :name"
)


def _normalized_index_predicate(index_sql: object) -> str | None:
    """Lấy và chuẩn hóa phần sau ``WHERE`` của lệnh tạo index.

    SQLite giữ nguyên SQL với khoảng trắng khác nhau tùy index được
    tạo bởi migration hay SQLAlchemy. Bỏ khoảng trắng + không phân biệt
    hoa thường là đủ để so đúng predicate của dự án; predicate khác
    cùng nghĩa vẫn fail-closed để người vận hành kiểm tra lại.
    """
    if not index_sql:
        return None
    compact = " ".join(str(index_sql).strip().split())
    lower = compact.lower()
    marker = " where "
    position = lower.find(marker)
    if position < 0:
        return None
    predicate = compact[position + len(marker):]
    return "".join(predicate.lower().split())

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

# Shop cũ không có created_at đáng tin cậy. Quyết định nghiệp vụ đã chốt là cấp
# đúng một trial 30 ngày từ lúc migration đầu tiên; WHERE NOT EXISTS làm lệnh
# chạy lặp lại mà không gia hạn trial sau mỗi lần restart.
_BACKFILL_SHOP_SUBSCRIPTIONS = """
INSERT INTO shop_subscriptions (
    shop_id, trial_started_at, trial_ends_at, paid_until, updated_at
)
SELECT
    s.id,
    CURRENT_TIMESTAMP,
    datetime(CURRENT_TIMESTAMP, '+30 days'),
    NULL,
    CURRENT_TIMESTAMP
FROM shops s
WHERE NOT EXISTS (
    SELECT 1 FROM shop_subscriptions ss WHERE ss.shop_id = s.id
)
"""

# Checkout đã kích hoạt trước khi model segment ra đời vẫn có đủ
# paid_until_after + duration_days để khôi phục chính xác đoạn ngày đã mua.
_BACKFILL_SUBSCRIPTION_ENTITLEMENTS = """
UPDATE subscription_checkouts
SET
    entitlement_ends_at = COALESCE(
        paid_until_after,
        datetime(activated_at, printf('+%d days', duration_days))
    ),
    entitlement_starts_at = datetime(
        COALESCE(
            paid_until_after,
            datetime(activated_at, printf('+%d days', duration_days))
        ),
        printf('-%d days', duration_days)
    )
WHERE activated_at IS NOT NULL
  AND (
      entitlement_starts_at IS NULL
      OR entitlement_ends_at IS NULL
  )
"""

_COUNT_MISSING_SUBSCRIPTION_ENTITLEMENTS = """
SELECT COUNT(*)
FROM subscription_checkouts
WHERE activated_at IS NOT NULL
  AND (
      entitlement_starts_at IS NULL
      OR entitlement_ends_at IS NULL
      OR entitlement_ends_at <= entitlement_starts_at
  )
"""

_SYNC_SUBSCRIPTION_PAID_UNTIL = """
UPDATE shop_subscriptions
SET
    paid_until = (
        SELECT MAX(sc.entitlement_ends_at)
        FROM subscription_checkouts sc
        WHERE sc.shop_id = shop_subscriptions.shop_id
          AND sc.activated_at IS NOT NULL
          AND sc.entitlement_ends_at IS NOT NULL
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE EXISTS (
    SELECT 1
    FROM subscription_checkouts sc
    WHERE sc.shop_id = shop_subscriptions.shop_id
      AND sc.activated_at IS NOT NULL
      AND sc.entitlement_ends_at IS NOT NULL
)
"""

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
            if name in _FINANCIAL_INDEX_SPECS:
                table_name, expected_columns, expected_predicate = (
                    _FINANCIAL_INDEX_SPECS[name]
                )
                safe_table = table_name.replace('"', '""')
                index_rows = db.execute(
                    text(f'PRAGMA index_list("{safe_table}")')
                ).fetchall()
                row = next(
                    (item for item in index_rows if item[1] == name),
                    None,
                )
                unique = bool(row is not None and int(row[2] or 0) == 1)
                partial = bool(
                    row is not None
                    and len(row) > 4
                    and int(row[4] or 0) == 1
                )
                safe_name = name.replace('"', '""')
                columns = tuple(
                    item[2]
                    for item in db.execute(
                        text(f'PRAGMA index_info("{safe_name}")')
                    ).fetchall()
                )
                expected_partial = expected_predicate is not None
                predicate_matches = not expected_partial
                if expected_partial and partial:
                    index_sql = db.execute(
                        text(
                            "SELECT sql FROM sqlite_master "
                            "WHERE type = 'index' AND name = :name"
                        ),
                        {"name": name},
                    ).scalar()
                    predicate_matches = _normalized_index_predicate(
                        index_sql
                    ) == _normalized_index_predicate(
                        f"CREATE INDEX x ON y(z) WHERE {expected_predicate}"
                    )
                found = (
                    unique
                    and columns == expected_columns
                    and partial == expected_partial
                    and predicate_matches
                )
            else:
                found = bool(
                    db.execute(
                        text(_INDEX_EXISTS), {"name": name}
                    ).scalar()
                    or 0
                )
        except SQLAlchemyError as e:
            print(f"[MIGRATE] Không kiểm được index '{name}': {e}")
            found = False
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


def backfill_shop_subscriptions(db: Session) -> int:
    """Cấp trial một lần cho shop cũ; lỗi phải dừng khởi động.

    Nếu nuốt lỗi ở đây, app vẫn chạy nhưng shop cũ không có aggregate thuê bao
    sẽ bị xem là Free. Đây là lỗi quyền sử dụng khó nhìn thấy hơn một lần startup
    thất bại rõ ràng, nên migration entitlement này cố ý fail-fast.
    """
    try:
        result = db.execute(text(_BACKFILL_SHOP_SUBSCRIPTIONS))
        db.commit()
        inserted = max(result.rowcount or 0, 0)
        if inserted:
            print(
                f"[MIGRATE] shop_subscriptions: cấp trial 30 ngày cho {inserted} shop cũ"
            )
        return inserted
    except SQLAlchemyError as e:
        db.rollback()
        raise RuntimeError(
            "Không thể cấp trial cho shop cũ; dừng khởi động để tránh "
            "âm thầm chuyển shop sang Free"
        ) from e


def backfill_subscription_entitlements(db: Session) -> int:
    """Khôi phục segment paid cũ; thiếu một dòng phải dừng startup."""
    try:
        result = db.execute(text(_BACKFILL_SUBSCRIPTION_ENTITLEMENTS))
        db.execute(text(_SYNC_SUBSCRIPTION_PAID_UNTIL))
        missing = (
            db.execute(text(_COUNT_MISSING_SUBSCRIPTION_ENTITLEMENTS)).scalar()
            or 0
        )
        if missing:
            db.rollback()
            raise RuntimeError(
                "Không khôi phục được segment ngày Pro cho "
                f"{missing} checkout đã thanh toán; dừng khởi động"
            )
        db.commit()
        return max(result.rowcount or 0, 0)
    except SQLAlchemyError as e:
        db.rollback()
        raise RuntimeError(
            "Không thể backfill segment ngày Pro; dừng khởi động để tránh "
            "làm mất ngày khách đã thanh toán"
        ) from e


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
            # Đường cứu cuối khi admin bị khóa vì dò mật khẩu: đặt lại
            # ADMIN_INITIAL_PASSWORD rồi khởi động lại là vào được ngay, không
            # phải ngồi chờ hết giờ khóa. Chỉ chủ máy chủ mới làm được việc này.
            admin.failed_login_count = 0
            admin.locked_until = None
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
        missing_financial_indexes = _FINANCIAL_INDEXES.intersection(
            missing_indexes
        )
        if missing_financial_indexes:
            raise RuntimeError(
                "Thiếu unique index bảo vệ sổ tiền: "
                f"{', '.join(sorted(missing_financial_indexes))}; "
                "dừng khởi động để tránh ghi trùng"
            )
        backfill_shop_subscriptions(db)
        backfill_subscription_entitlements(db)
        backfill_legacy_order_payments(db)
        backfill_order_item_product_id(db)
        seed_admin(db)
    finally:
        db.close()
