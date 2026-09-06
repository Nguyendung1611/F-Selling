"""Self-contained business schema at Git baseline 9cf710606e55005766a0c7d790a366e0611695f6."""

from alembic import op

revision = "0001_legacy_9cf7106_baseline"
down_revision = None
branch_labels = None
depends_on = None

TABLE_DDL = (
    """CREATE TABLE assistant_ai_usage (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, ngay VARCHAR(10) NOT NULL,
        so_luot INTEGER NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE cash_movements (
        id INTEGER NOT NULL, shift_id INTEGER NOT NULL, order_id INTEGER,
        movement_type VARCHAR(24) NOT NULL, direction VARCHAR(8) NOT NULL,
        amount FLOAT NOT NULL, operation_id VARCHAR(128) NOT NULL,
        note VARCHAR(500) NOT NULL, created_by_user_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_cash_movements_amount_positive CHECK (amount > 0),
        CONSTRAINT ck_cash_movements_direction CHECK (direction IN ('IN', 'OUT')),
        FOREIGN KEY(shift_id) REFERENCES cash_shifts (id),
        FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE cash_shifts (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, status VARCHAR(16) NOT NULL,
        opening_cash_amount FLOAT NOT NULL, opening_note VARCHAR(500),
        opened_by_user_id INTEGER NOT NULL, opened_at DATETIME NOT NULL,
        counted_cash_amount FLOAT, expected_cash_amount FLOAT, variance_amount FLOAT,
        closing_note VARCHAR(500), closed_by_user_id INTEGER, closed_at DATETIME,
        PRIMARY KEY (id),
        CONSTRAINT ck_cash_shifts_status CHECK (status IN ('OPEN', 'CLOSED')),
        CONSTRAINT ck_cash_shifts_opening_cash_nonnegative CHECK (opening_cash_amount >= 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(opened_by_user_id) REFERENCES users (id),
        FOREIGN KEY(closed_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE categories (
        id INTEGER NOT NULL, name VARCHAR, shop_id INTEGER, is_active BOOLEAN,
        PRIMARY KEY (id), FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE customers (
        id INTEGER NOT NULL, shop_id INTEGER, name VARCHAR, phone VARCHAR,
        address VARCHAR, note VARCHAR, credit_limit FLOAT,
        is_active BOOLEAN NOT NULL, created_at DATETIME, PRIMARY KEY (id),
        CONSTRAINT uq_customer_shop_phone UNIQUE (shop_id, phone),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE expense_categories (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL,
        is_active BOOLEAN NOT NULL, sort_order INTEGER NOT NULL,
        created_by_user_id INTEGER, created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE expense_templates (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, category_id INTEGER NOT NULL,
        name VARCHAR(200) NOT NULL, amount INTEGER NOT NULL,
        day_of_month INTEGER NOT NULL, is_active BOOLEAN NOT NULL, note VARCHAR(500),
        created_by_user_id INTEGER, created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_expense_templates_amount_nonnegative CHECK (amount >= 0),
        CONSTRAINT ck_expense_templates_day_of_month CHECK (day_of_month >= 1 AND day_of_month <= 31),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(category_id) REFERENCES expense_categories (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE loyalty_point_entries (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, customer_id INTEGER NOT NULL,
        order_id INTEGER, return_id INTEGER, entry_type VARCHAR(32) NOT NULL,
        points_delta INTEGER NOT NULL, expires_at DATETIME,
        idempotency_key VARCHAR(128) NOT NULL, created_by_user_id INTEGER,
        customer_name VARCHAR(255), customer_phone VARCHAR(64), note VARCHAR(500),
        created_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_loyalty_points_delta_nonzero CHECK (points_delta <> 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(customer_id) REFERENCES customers (id),
        FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(return_id) REFERENCES order_returns (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE loyalty_programs (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, enabled BOOLEAN NOT NULL,
        earn_amount FLOAT, earn_points INTEGER, redeem_points INTEGER,
        redeem_amount FLOAT, min_redeem_points INTEGER NOT NULL,
        max_redeem_percent FLOAT NOT NULL, expiry_days INTEGER,
        updated_by_user_id INTEGER, updated_at DATETIME NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(updated_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE operating_expenses (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, category_id INTEGER NOT NULL,
        template_id INTEGER, amount INTEGER NOT NULL, expense_date VARCHAR(10) NOT NULL,
        amortize_start_date VARCHAR(10) NOT NULL, amortize_end_date VARCHAR(10) NOT NULL,
        method VARCHAR(20) NOT NULL, shift_id INTEGER, cash_movement_id INTEGER,
        note VARCHAR(500), reference VARCHAR(128), idempotency_key VARCHAR(128) NOT NULL,
        created_by_user_id INTEGER, created_at DATETIME NOT NULL, voided_at DATETIME,
        voided_by_user_id INTEGER, PRIMARY KEY (id),
        CONSTRAINT ck_operating_expenses_amount_positive CHECK (amount > 0),
        CONSTRAINT ck_operating_expenses_method CHECK (method IN ('CASH_SHIFT', 'TRANSFER', 'OUTSIDE')),
        CONSTRAINT ck_operating_expenses_amortize_range CHECK (amortize_end_date >= amortize_start_date),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(category_id) REFERENCES expense_categories (id),
        FOREIGN KEY(template_id) REFERENCES expense_templates (id),
        FOREIGN KEY(shift_id) REFERENCES cash_shifts (id),
        FOREIGN KEY(cash_movement_id) REFERENCES cash_movements (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(voided_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE order_item_batches (
        id INTEGER NOT NULL, order_item_id INTEGER NOT NULL, batch_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL, cost_price FLOAT, PRIMARY KEY (id),
        FOREIGN KEY(order_item_id) REFERENCES order_items (id),
        FOREIGN KEY(batch_id) REFERENCES product_batches (id)
    )""",
    """CREATE TABLE order_items (
        id INTEGER NOT NULL, order_id INTEGER, product_id INTEGER,
        product_name VARCHAR, price FLOAT, cost_price FLOAT, quantity INTEGER,
        PRIMARY KEY (id), FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(product_id) REFERENCES products (id)
    )""",
    """CREATE TABLE order_payments (
        id INTEGER NOT NULL, order_id INTEGER NOT NULL, entry_type VARCHAR(24) NOT NULL,
        amount FLOAT NOT NULL, idempotency_key VARCHAR(128), provider VARCHAR(32),
        bank_txn_id VARCHAR(128), account_no VARCHAR(64), created_by_user_id INTEGER,
        shift_id INTEGER, note VARCHAR(500), reference VARCHAR(128),
        created_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_order_payments_amount_positive CHECK (amount > 0),
        FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(shift_id) REFERENCES cash_shifts (id)
    )""",
    """CREATE TABLE order_return_items (
        id INTEGER NOT NULL, return_id INTEGER NOT NULL, order_item_id INTEGER NOT NULL,
        product_id INTEGER, product_name VARCHAR, quantity INTEGER NOT NULL,
        unit_price FLOAT NOT NULL, refund_amount FLOAT NOT NULL, cost_price FLOAT,
        restocked INTEGER NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(return_id) REFERENCES order_returns (id),
        FOREIGN KEY(order_item_id) REFERENCES order_items (id),
        FOREIGN KEY(product_id) REFERENCES products (id)
    )""",
    """CREATE TABLE order_returns (
        id INTEGER NOT NULL, order_id INTEGER NOT NULL, shop_id INTEGER NOT NULL,
        idempotency_key VARCHAR(128), operation_fingerprint VARCHAR(64),
        refund_amount FLOAT NOT NULL, refund_method VARCHAR(20), reason VARCHAR(200),
        note VARCHAR(500), reference VARCHAR(128), created_by_user_id INTEGER,
        shift_id INTEGER, created_at DATETIME NOT NULL,
        loyalty_points_restored INTEGER NOT NULL, loyalty_points_reversed INTEGER NOT NULL,
        PRIMARY KEY (id), FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(shift_id) REFERENCES cash_shifts (id)
    )""",
    """CREATE TABLE orders (
        id INTEGER NOT NULL, shop_id INTEGER, total_amount FLOAT, discount_amount FLOAT,
        voucher_code VARCHAR, payment_method VARCHAR, status VARCHAR, created_at DATETIME,
        operation_id VARCHAR(128), operation_fingerprint VARCHAR(64),
        created_by_user_id INTEGER, shift_id INTEGER, cash_tendered_amount FLOAT,
        cash_change_amount FLOAT, customer_id INTEGER, paid_amount FLOAT,
        bank_txn_id VARCHAR(128), cash_paid_amount FLOAT NOT NULL,
        refunded_amount FLOAT NOT NULL, refund_due_amount FLOAT NOT NULL,
        refund_completed_at DATETIME, refund_completed_by INTEGER,
        refund_method VARCHAR(20), refund_note VARCHAR(500), refund_reference VARCHAR(128),
        reconciliation_reason VARCHAR(32), offline_uuid VARCHAR(64),
        sold_offline_at DATETIME, offline_issue VARCHAR(120), offline_device VARCHAR(64),
        loyalty_points_redeemed INTEGER NOT NULL, loyalty_discount_amount FLOAT NOT NULL,
        loyalty_earn_amount_step FLOAT, loyalty_earn_points_step INTEGER,
        loyalty_expiry_days_snapshot INTEGER, loyalty_points_earned INTEGER NOT NULL,
        loyalty_awarded_at DATETIME, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(shift_id) REFERENCES cash_shifts (id),
        FOREIGN KEY(customer_id) REFERENCES customers (id),
        FOREIGN KEY(refund_completed_by) REFERENCES users (id)
    )""",
    """CREATE TABLE product_batches (
        id INTEGER NOT NULL, product_id INTEGER NOT NULL, shop_id INTEGER NOT NULL,
        expiry_date VARCHAR(10), quantity INTEGER NOT NULL, cost_price FLOAT,
        note VARCHAR(200), created_at DATETIME NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE products (
        id INTEGER NOT NULL, code VARCHAR, barcode VARCHAR(64), name VARCHAR,
        price FLOAT, cost_price FLOAT, stock INTEGER, image_url VARCHAR,
        is_active BOOLEAN, category_id INTEGER, shop_id INTEGER,
        track_batches BOOLEAN NOT NULL, variant_group VARCHAR(200),
        variant_name VARCHAR(100), PRIMARY KEY (id),
        FOREIGN KEY(category_id) REFERENCES categories (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE purchase_receipt_items (
        id INTEGER NOT NULL, receipt_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
        product_name VARCHAR(300) NOT NULL, quantity INTEGER NOT NULL,
        unit_cost INTEGER NOT NULL, expiry_date VARCHAR(10), batch_id INTEGER,
        PRIMARY KEY (id),
        CONSTRAINT ck_purchase_receipt_items_quantity_positive CHECK (quantity > 0),
        CONSTRAINT ck_purchase_receipt_items_cost_nonnegative CHECK (unit_cost >= 0),
        FOREIGN KEY(receipt_id) REFERENCES purchase_receipts (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(batch_id) REFERENCES product_batches (id)
    )""",
    """CREATE TABLE purchase_receipts (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, supplier_id INTEGER NOT NULL,
        status VARCHAR(16) NOT NULL, supplier_invoice_number VARCHAR(128),
        received_date VARCHAR(10) NOT NULL, due_date VARCHAR(10), note VARCHAR(500),
        total_amount INTEGER NOT NULL, create_operation_id VARCHAR(128) NOT NULL,
        create_fingerprint VARCHAR(64) NOT NULL, confirm_operation_id VARCHAR(128),
        confirm_fingerprint VARCHAR(64), created_by_user_id INTEGER,
        updated_by_user_id INTEGER, confirmed_by_user_id INTEGER,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        confirmed_at DATETIME, PRIMARY KEY (id),
        CONSTRAINT ck_purchase_receipts_status CHECK (status IN ('DRAFT', 'POSTED')),
        CONSTRAINT ck_purchase_receipts_total_nonnegative CHECK (total_amount >= 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(supplier_id) REFERENCES suppliers (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(updated_by_user_id) REFERENCES users (id),
        FOREIGN KEY(confirmed_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE shop_subscriptions (
        shop_id INTEGER NOT NULL, trial_started_at DATETIME NOT NULL,
        trial_ends_at DATETIME NOT NULL, paid_until DATETIME,
        updated_at DATETIME NOT NULL, PRIMARY KEY (shop_id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE shops (
        id INTEGER NOT NULL, name VARCHAR, business_address VARCHAR, tax_code VARCHAR,
        phone VARCHAR, email VARCHAR, bank_account_no VARCHAR,
        bank_account_name VARCHAR, bank_code VARCHAR, is_active BOOLEAN,
        owner_id INTEGER, PRIMARY KEY (id),
        FOREIGN KEY(owner_id) REFERENCES users (id)
    )""",
    """CREATE TABLE stock_write_off_items (
        id INTEGER NOT NULL, write_off_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
        product_name VARCHAR, batch_id INTEGER, expiry_date VARCHAR(10),
        quantity INTEGER NOT NULL, cost_price FLOAT, PRIMARY KEY (id),
        FOREIGN KEY(write_off_id) REFERENCES stock_write_offs (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(batch_id) REFERENCES product_batches (id)
    )""",
    """CREATE TABLE stock_write_offs (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, reason VARCHAR(20) NOT NULL,
        note VARCHAR(200), total_quantity INTEGER NOT NULL, created_by_user_id INTEGER,
        idempotency_key VARCHAR(64), created_at DATETIME NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE subscription_checkouts (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, reference_code VARCHAR(32) NOT NULL,
        cycle VARCHAR(16) NOT NULL, amount_due_vnd INTEGER NOT NULL,
        duration_days INTEGER NOT NULL, status VARCHAR(16) NOT NULL,
        received_amount_vnd INTEGER NOT NULL, refund_due_amount_vnd INTEGER NOT NULL,
        operation_id VARCHAR(128) NOT NULL, operation_fingerprint VARCHAR(64) NOT NULL,
        created_by_user_id INTEGER NOT NULL, created_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL, activated_at DATETIME,
        entitlement_starts_at DATETIME, entitlement_ends_at DATETIME,
        paid_until_after DATETIME, PRIMARY KEY (id),
        CONSTRAINT ck_subscription_checkouts_cycle CHECK (cycle IN ('MONTHLY', 'YEARLY')),
        CONSTRAINT ck_subscription_checkouts_status CHECK (status IN ('PENDING', 'UNDERPAID', 'PAID', 'OVERPAID', 'EXPIRED')),
        CONSTRAINT ck_subscription_checkouts_amount_positive CHECK (amount_due_vnd > 0),
        CONSTRAINT ck_subscription_checkouts_duration_positive CHECK (duration_days > 0),
        CONSTRAINT ck_subscription_checkouts_received_nonnegative CHECK (received_amount_vnd >= 0),
        CONSTRAINT ck_subscription_checkouts_refund_nonnegative CHECK (refund_due_amount_vnd >= 0),
        CONSTRAINT ck_subscription_checkouts_entitlement_time CHECK ((entitlement_starts_at IS NULL AND entitlement_ends_at IS NULL) OR (entitlement_starts_at IS NOT NULL AND entitlement_ends_at IS NOT NULL AND entitlement_ends_at > entitlement_starts_at)),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE subscription_grants (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, starts_at DATETIME NOT NULL,
        ends_at DATETIME NOT NULL, expires_on VARCHAR(10) NOT NULL,
        reason VARCHAR(500) NOT NULL, operation_id VARCHAR(128) NOT NULL,
        operation_fingerprint VARCHAR(64) NOT NULL, granted_by_user_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL, revoked_at DATETIME, revoked_by_user_id INTEGER,
        revoke_reason VARCHAR(500), revoke_operation_id VARCHAR(128),
        revoke_fingerprint VARCHAR(64), PRIMARY KEY (id),
        CONSTRAINT ck_subscription_grants_time CHECK (ends_at > starts_at),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(granted_by_user_id) REFERENCES users (id),
        FOREIGN KEY(revoked_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE subscription_payments (
        id INTEGER NOT NULL, checkout_id INTEGER, shop_id INTEGER,
        reference_code VARCHAR(64), amount_vnd INTEGER NOT NULL,
        idempotency_key VARCHAR(128) NOT NULL, provider VARCHAR(32),
        bank_txn_id VARCHAR(128), account_no VARCHAR(128),
        payload_fingerprint VARCHAR(64), needs_review BOOLEAN NOT NULL,
        review_reason VARCHAR(64), created_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_subscription_payments_amount_positive CHECK (amount_vnd > 0),
        FOREIGN KEY(checkout_id) REFERENCES subscription_checkouts (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE supplier_payable_entries (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, supplier_id INTEGER NOT NULL,
        receipt_id INTEGER, entry_type VARCHAR(20) NOT NULL, amount INTEGER NOT NULL,
        entry_date VARCHAR(10) NOT NULL, due_date VARCHAR(10),
        idempotency_key VARCHAR(128) NOT NULL, note VARCHAR(500),
        created_by_user_id INTEGER, created_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_supplier_payable_entries_type CHECK (entry_type IN ('PURCHASE', 'OPENING')),
        CONSTRAINT ck_supplier_payable_entries_amount_positive CHECK (amount > 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(supplier_id) REFERENCES suppliers (id),
        FOREIGN KEY(receipt_id) REFERENCES purchase_receipts (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE supplier_payment_allocations (
        id INTEGER NOT NULL, payment_id INTEGER NOT NULL,
        payable_entry_id INTEGER NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_supplier_payment_allocations_amount_positive CHECK (amount > 0),
        FOREIGN KEY(payment_id) REFERENCES supplier_payments (id),
        FOREIGN KEY(payable_entry_id) REFERENCES supplier_payable_entries (id)
    )""",
    """CREATE TABLE supplier_payments (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, supplier_id INTEGER NOT NULL,
        amount INTEGER NOT NULL, method VARCHAR(20) NOT NULL,
        idempotency_key VARCHAR(128) NOT NULL, operation_fingerprint VARCHAR(64) NOT NULL,
        shift_id INTEGER, cash_movement_id INTEGER, note VARCHAR(500),
        reference VARCHAR(128), created_by_user_id INTEGER,
        created_at DATETIME NOT NULL, PRIMARY KEY (id),
        CONSTRAINT ck_supplier_payments_method CHECK (method IN ('CASH_SHIFT', 'TRANSFER', 'OUTSIDE')),
        CONSTRAINT ck_supplier_payments_amount_positive CHECK (amount > 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(supplier_id) REFERENCES suppliers (id),
        FOREIGN KEY(shift_id) REFERENCES cash_shifts (id),
        FOREIGN KEY(cash_movement_id) REFERENCES cash_movements (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE suppliers (
        id INTEGER NOT NULL, shop_id INTEGER NOT NULL, name VARCHAR(255) NOT NULL,
        phone VARCHAR(64), tax_code VARCHAR(64), address VARCHAR(500), note VARCHAR(500),
        is_active BOOLEAN NOT NULL, create_operation_id VARCHAR(128) NOT NULL,
        create_fingerprint VARCHAR(64) NOT NULL, created_by_user_id INTEGER,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    """CREATE TABLE system_logs (
        id INTEGER NOT NULL, user_id INTEGER, shop_id INTEGER, action VARCHAR,
        details VARCHAR, created_at DATETIME, PRIMARY KEY (id),
        FOREIGN KEY(user_id) REFERENCES users (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE users (
        id INTEGER NOT NULL, username VARCHAR, hashed_password VARCHAR, role VARCHAR,
        email VARCHAR, is_verified BOOLEAN, is_active BOOLEAN NOT NULL,
        session_id VARCHAR, verification_code VARCHAR,
        verification_code_expires DATETIME, failed_login_count INTEGER NOT NULL,
        locked_until DATETIME, verification_attempts INTEGER NOT NULL,
        verification_code_sent_at DATETIME, staff_shop_id INTEGER,
        staff_role VARCHAR, PRIMARY KEY (id),
        FOREIGN KEY(staff_shop_id) REFERENCES shops (id)
    )""",
    """CREATE TABLE vouchers (
        id INTEGER NOT NULL, code VARCHAR, shop_id INTEGER, discount_type VARCHAR,
        discount_value FLOAT, min_order_value FLOAT, max_discount FLOAT,
        usage_limit INTEGER, usage_count INTEGER, expires_at VARCHAR, PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
)

INDEX_DDL = (
    "CREATE INDEX ix_cash_movements_order_id ON cash_movements (order_id)",
    "CREATE INDEX ix_cash_movements_shift_id ON cash_movements (shift_id)",
    "CREATE INDEX ix_cash_shifts_opened_by_user_id ON cash_shifts (opened_by_user_id)",
    "CREATE INDEX ix_cash_shifts_shop_id ON cash_shifts (shop_id)",
    "CREATE INDEX ix_categories_id ON categories (id)",
    "CREATE INDEX ix_categories_name ON categories (name)",
    "CREATE INDEX ix_customers_id ON customers (id)",
    "CREATE INDEX ix_customers_phone ON customers (phone)",
    "CREATE INDEX ix_customers_shop_id ON customers (shop_id)",
    "CREATE INDEX ix_expense_categories_shop_active ON expense_categories (shop_id, is_active)",
    "CREATE INDEX ix_expense_templates_category_id ON expense_templates (category_id)",
    "CREATE INDEX ix_expense_templates_shop_active ON expense_templates (shop_id, is_active)",
    "CREATE INDEX ix_loyalty_point_entries_customer_created ON loyalty_point_entries (customer_id, created_at)",
    "CREATE INDEX ix_loyalty_point_entries_shop_created ON loyalty_point_entries (shop_id, created_at)",
    "CREATE INDEX ix_operating_expenses_category_id ON operating_expenses (category_id)",
    "CREATE INDEX ix_operating_expenses_shift_id ON operating_expenses (shift_id)",
    "CREATE INDEX ix_operating_expenses_shop_amortize ON operating_expenses (shop_id, amortize_start_date, amortize_end_date)",
    "CREATE INDEX ix_operating_expenses_shop_date ON operating_expenses (shop_id, expense_date)",
    "CREATE INDEX ix_operating_expenses_template_id ON operating_expenses (template_id)",
    "CREATE INDEX ix_order_item_batches_batch_id ON order_item_batches (batch_id)",
    "CREATE INDEX ix_order_item_batches_order_item_id ON order_item_batches (order_item_id)",
    "CREATE INDEX ix_order_items_id ON order_items (id)",
    "CREATE INDEX ix_order_items_product_id ON order_items (product_id)",
    "CREATE INDEX ix_order_payments_bank_txn_id ON order_payments (bank_txn_id)",
    "CREATE INDEX ix_order_payments_order_id ON order_payments (order_id)",
    "CREATE INDEX ix_order_payments_shift_id ON order_payments (shift_id)",
    "CREATE INDEX ix_order_return_items_order_item_id ON order_return_items (order_item_id)",
    "CREATE INDEX ix_order_return_items_return_id ON order_return_items (return_id)",
    "CREATE INDEX ix_order_returns_order_id ON order_returns (order_id)",
    "CREATE INDEX ix_order_returns_shift_id ON order_returns (shift_id)",
    "CREATE INDEX ix_order_returns_shop_id_created_at ON order_returns (shop_id, created_at)",
    "CREATE INDEX ix_orders_bank_txn_id ON orders (bank_txn_id)",
    "CREATE INDEX ix_orders_created_by_user_id ON orders (created_by_user_id)",
    "CREATE INDEX ix_orders_customer_id ON orders (customer_id)",
    "CREATE INDEX ix_orders_id ON orders (id)",
    "CREATE INDEX ix_orders_offline_issue ON orders (offline_issue)",
    "CREATE UNIQUE INDEX ix_orders_offline_uuid ON orders (offline_uuid)",
    "CREATE INDEX ix_orders_reconciliation_reason ON orders (reconciliation_reason)",
    "CREATE INDEX ix_orders_shift_id ON orders (shift_id)",
    "CREATE INDEX ix_orders_status_customer ON orders (status, customer_id)",
    "CREATE INDEX ix_product_batches_product_expiry ON product_batches (product_id, expiry_date)",
    "CREATE INDEX ix_products_barcode ON products (barcode)",
    "CREATE INDEX ix_products_code ON products (code)",
    "CREATE INDEX ix_products_id ON products (id)",
    "CREATE INDEX ix_products_name ON products (name)",
    "CREATE UNIQUE INDEX ix_products_shop_barcode ON products (shop_id, barcode)",
    "CREATE UNIQUE INDEX ix_products_shop_code ON products (shop_id, code)",
    "CREATE UNIQUE INDEX ix_products_shop_name ON products (shop_id, name)",
    "CREATE INDEX ix_products_shop_variant_group ON products (shop_id, variant_group)",
    "CREATE INDEX ix_products_variant_group ON products (variant_group)",
    "CREATE INDEX ix_purchase_receipt_items_product_id ON purchase_receipt_items (product_id)",
    "CREATE INDEX ix_purchase_receipt_items_receipt_id ON purchase_receipt_items (receipt_id)",
    "CREATE INDEX ix_purchase_receipts_shop_created ON purchase_receipts (shop_id, created_at)",
    "CREATE INDEX ix_purchase_receipts_supplier_created ON purchase_receipts (supplier_id, created_at)",
    "CREATE INDEX ix_shops_id ON shops (id)",
    "CREATE INDEX ix_shops_name ON shops (name)",
    "CREATE INDEX ix_stock_write_off_items_write_off_id ON stock_write_off_items (write_off_id)",
    "CREATE INDEX ix_stock_write_offs_shop_created ON stock_write_offs (shop_id, created_at)",
    "CREATE INDEX ix_subscription_checkouts_shop_created ON subscription_checkouts (shop_id, created_at)",
    "CREATE INDEX ix_subscription_checkouts_shop_entitlement ON subscription_checkouts (shop_id, entitlement_starts_at, entitlement_ends_at)",
    "CREATE INDEX ix_subscription_grants_shop_ends ON subscription_grants (shop_id, ends_at)",
    "CREATE INDEX ix_subscription_payments_bank_txn_id ON subscription_payments (bank_txn_id)",
    "CREATE INDEX ix_subscription_payments_checkout_id ON subscription_payments (checkout_id)",
    "CREATE INDEX ix_subscription_payments_needs_review ON subscription_payments (needs_review)",
    "CREATE INDEX ix_subscription_payments_shop_created ON subscription_payments (shop_id, created_at)",
    "CREATE INDEX ix_supplier_payable_entries_supplier_created ON supplier_payable_entries (supplier_id, created_at)",
    "CREATE INDEX ix_supplier_payment_allocations_payable_id ON supplier_payment_allocations (payable_entry_id)",
    "CREATE INDEX ix_supplier_payment_allocations_payment_id ON supplier_payment_allocations (payment_id)",
    "CREATE INDEX ix_supplier_payments_shift_id ON supplier_payments (shift_id)",
    "CREATE INDEX ix_supplier_payments_supplier_created ON supplier_payments (supplier_id, created_at)",
    "CREATE INDEX ix_suppliers_shop_name ON suppliers (shop_id, name)",
    "CREATE INDEX ix_system_logs_action ON system_logs (action)",
    "CREATE INDEX ix_system_logs_id ON system_logs (id)",
    "CREATE INDEX ix_system_logs_shop_id ON system_logs (shop_id)",
    "CREATE UNIQUE INDEX ix_users_email ON users (email)",
    "CREATE INDEX ix_users_id ON users (id)",
    "CREATE INDEX ix_users_staff_shop_id ON users (staff_shop_id)",
    "CREATE UNIQUE INDEX ix_users_username ON users (username)",
    "CREATE INDEX ix_vouchers_code ON vouchers (code)",
    "CREATE INDEX ix_vouchers_id ON vouchers (id)",
    "CREATE UNIQUE INDEX ux_assistant_ai_usage_shop_ngay ON assistant_ai_usage (shop_id, ngay)",
    "CREATE UNIQUE INDEX ux_cash_movements_operation_id ON cash_movements (operation_id)",
    "CREATE UNIQUE INDEX ux_cash_shifts_shop_user_open ON cash_shifts (shop_id, opened_by_user_id) WHERE status = 'OPEN'",
    "CREATE UNIQUE INDEX ux_expense_categories_shop_name ON expense_categories (shop_id, name)",
    "CREATE UNIQUE INDEX ux_loyalty_point_entries_idempotency_key ON loyalty_point_entries (idempotency_key)",
    "CREATE UNIQUE INDEX ux_loyalty_programs_shop_id ON loyalty_programs (shop_id)",
    "CREATE UNIQUE INDEX ux_operating_expenses_idempotency_key ON operating_expenses (idempotency_key)",
    "CREATE UNIQUE INDEX ux_order_payments_idempotency_key ON order_payments (idempotency_key)",
    "CREATE UNIQUE INDEX ux_order_returns_idempotency_key ON order_returns (idempotency_key)",
    "CREATE UNIQUE INDEX ux_orders_offline_uuid ON orders (offline_uuid)",
    "CREATE UNIQUE INDEX ux_orders_operation_id ON orders (operation_id)",
    "CREATE UNIQUE INDEX ux_products_shop_variant ON products (shop_id, variant_group, variant_name)",
    "CREATE UNIQUE INDEX ux_purchase_receipts_confirm_operation_id ON purchase_receipts (confirm_operation_id)",
    "CREATE UNIQUE INDEX ux_purchase_receipts_create_operation_id ON purchase_receipts (create_operation_id)",
    "CREATE UNIQUE INDEX ux_shop_subscriptions_shop_id ON shop_subscriptions (shop_id)",
    "CREATE UNIQUE INDEX ux_stock_write_offs_idempotency_key ON stock_write_offs (idempotency_key)",
    "CREATE UNIQUE INDEX ux_subscription_checkouts_one_open_per_shop ON subscription_checkouts (shop_id) WHERE status IN ('PENDING', 'UNDERPAID')",
    "CREATE UNIQUE INDEX ux_subscription_checkouts_operation_id ON subscription_checkouts (operation_id)",
    "CREATE UNIQUE INDEX ux_subscription_checkouts_reference_code ON subscription_checkouts (reference_code)",
    "CREATE UNIQUE INDEX ux_subscription_grants_operation_id ON subscription_grants (operation_id)",
    "CREATE UNIQUE INDEX ux_subscription_grants_revoke_operation_id ON subscription_grants (revoke_operation_id)",
    "CREATE UNIQUE INDEX ux_subscription_payments_idempotency_key ON subscription_payments (idempotency_key)",
    "CREATE UNIQUE INDEX ux_supplier_payable_entries_idempotency_key ON supplier_payable_entries (idempotency_key)",
    "CREATE UNIQUE INDEX ux_supplier_payable_entries_receipt_id ON supplier_payable_entries (receipt_id)",
    "CREATE UNIQUE INDEX ux_supplier_payment_allocations_pair ON supplier_payment_allocations (payment_id, payable_entry_id)",
    "CREATE UNIQUE INDEX ux_supplier_payments_idempotency_key ON supplier_payments (idempotency_key)",
    "CREATE UNIQUE INDEX ux_suppliers_create_operation_id ON suppliers (create_operation_id)",
)


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def upgrade():
    for statement in TABLE_DDL + INDEX_DDL:
        _execute(statement)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    rows = execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = {name for kind, name in rows if kind == "table"}
    indexes = {name for kind, name in rows if kind == "index"}
    expected_tables = 34 + 1
    if len(tables) < expected_tables or len(indexes) < len(INDEX_DDL):
        raise RuntimeError(
            f"0001 verifier failed: tables={len(tables)}, indexes={len(indexes)}"
        )
    required = {
        "users", "shops", "products", "orders", "order_items",
        "order_payments", "ux_order_payments_idempotency_key",
        "ux_orders_offline_uuid", "ux_supplier_payments_idempotency_key",
    }
    if not required.issubset(tables | indexes):
        raise RuntimeError(f"0001 verifier missing {sorted(required - (tables | indexes))}")


def downgrade():
    raise RuntimeError("F-Selling I04 migrations are forward-only")
