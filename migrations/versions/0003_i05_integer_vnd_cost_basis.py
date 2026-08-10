"""I05 canonical INTEGER VND and exact inventory cost provenance."""

from alembic import op

revision = "0003_i05_integer_vnd_cost_basis"
down_revision = "0002_i04_operational_tables"
branch_labels = None
depends_on = None

MAX_SAFE_VND = 9000000000000000
MAX_SAFE_QUANTITY = 1000000000


DDL = (
    "ALTER TABLE products ADD COLUMN price_vnd INTEGER NOT NULL DEFAULT 0 CHECK(price_vnd >= 0 AND price_vnd <= 9000000000000000)",
    "ALTER TABLE products ADD COLUMN cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000)",
    "ALTER TABLE products ADD COLUMN cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000)",
    "ALTER TABLE products ADD COLUMN cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000)",
    "ALTER TABLE products ADD COLUMN cost_deficit_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_deficit_qty >= 0 AND cost_deficit_qty <= 1000000000)",
    "ALTER TABLE products ADD COLUMN cost_state_version INTEGER NOT NULL DEFAULT 0 CHECK(cost_state_version >= 0)",
    "ALTER TABLE product_batches ADD COLUMN cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000)",
    "ALTER TABLE product_batches ADD COLUMN cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000)",
    "ALTER TABLE product_batches ADD COLUMN cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000)",
    "ALTER TABLE product_batches ADD COLUMN cost_deficit_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_deficit_qty >= 0 AND cost_deficit_qty <= 1000000000)",
    "ALTER TABLE product_batches ADD COLUMN cost_state_version INTEGER NOT NULL DEFAULT 0 CHECK(cost_state_version >= 0)",
    "ALTER TABLE orders ADD COLUMN total_vnd INTEGER NOT NULL DEFAULT 0 CHECK(total_vnd >= 0 AND total_vnd <= 9000000000000000)",
    "ALTER TABLE orders ADD COLUMN discount_vnd INTEGER NOT NULL DEFAULT 0 CHECK(discount_vnd >= 0 AND discount_vnd <= 9000000000000000)",
    "ALTER TABLE orders ADD COLUMN cash_tendered_vnd INTEGER CHECK(cash_tendered_vnd IS NULL OR (cash_tendered_vnd >= 0 AND cash_tendered_vnd <= 9000000000000000))",
    "ALTER TABLE orders ADD COLUMN cash_change_vnd INTEGER CHECK(cash_change_vnd IS NULL OR (cash_change_vnd >= 0 AND cash_change_vnd <= 9000000000000000))",
    "ALTER TABLE orders ADD COLUMN paid_vnd INTEGER CHECK(paid_vnd IS NULL OR (paid_vnd >= 0 AND paid_vnd <= 9000000000000000))",
    "ALTER TABLE orders ADD COLUMN cash_paid_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cash_paid_vnd >= 0 AND cash_paid_vnd <= 9000000000000000)",
    "ALTER TABLE orders ADD COLUMN refunded_vnd INTEGER NOT NULL DEFAULT 0 CHECK(refunded_vnd >= 0 AND refunded_vnd <= 9000000000000000)",
    "ALTER TABLE orders ADD COLUMN refund_due_vnd INTEGER NOT NULL DEFAULT 0 CHECK(refund_due_vnd >= 0 AND refund_due_vnd <= 9000000000000000)",
    "ALTER TABLE orders ADD COLUMN loyalty_discount_vnd INTEGER NOT NULL DEFAULT 0 CHECK(loyalty_discount_vnd >= 0 AND loyalty_discount_vnd <= 9000000000000000)",
    "ALTER TABLE orders ADD COLUMN loyalty_earn_amount_step_vnd INTEGER CHECK(loyalty_earn_amount_step_vnd IS NULL OR (loyalty_earn_amount_step_vnd > 0 AND loyalty_earn_amount_step_vnd <= 9000000000000000))",
    "ALTER TABLE orders ADD COLUMN inventory_reversed INTEGER NOT NULL DEFAULT 0 CHECK(inventory_reversed IN (0, 1))",
    "ALTER TABLE orders ADD COLUMN inventory_reversal_key VARCHAR(128)",
    "ALTER TABLE orders ADD COLUMN inventory_reversal_version INTEGER NOT NULL DEFAULT 0 CHECK(inventory_reversal_version >= 0)",
    "CREATE UNIQUE INDEX ux_orders_inventory_reversal_key ON orders (inventory_reversal_key)",
    "ALTER TABLE order_items ADD COLUMN unit_price_vnd INTEGER NOT NULL DEFAULT 0 CHECK(unit_price_vnd >= 0 AND unit_price_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN discount_vnd INTEGER NOT NULL DEFAULT 0 CHECK(discount_vnd >= 0 AND discount_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN loyalty_discount_vnd INTEGER NOT NULL DEFAULT 0 CHECK(loyalty_discount_vnd >= 0 AND loyalty_discount_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN net_amount_vnd INTEGER NOT NULL DEFAULT 0 CHECK(net_amount_vnd >= 0 AND net_amount_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000)",
    "ALTER TABLE order_items ADD COLUMN cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000)",
    "ALTER TABLE order_items ADD COLUMN cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN returned_total_qty INTEGER NOT NULL DEFAULT 0 CHECK(returned_total_qty >= 0 AND returned_total_qty <= 1000000000)",
    "ALTER TABLE order_items ADD COLUMN returned_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(returned_known_qty >= 0 AND returned_known_qty <= 1000000000)",
    "ALTER TABLE order_items ADD COLUMN returned_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(returned_unknown_qty >= 0 AND returned_unknown_qty <= 1000000000)",
    "ALTER TABLE order_items ADD COLUMN returned_cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(returned_cost_basis_vnd >= 0 AND returned_cost_basis_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN returned_refund_vnd INTEGER NOT NULL DEFAULT 0 CHECK(returned_refund_vnd >= 0 AND returned_refund_vnd <= 9000000000000000)",
    "ALTER TABLE order_items ADD COLUMN cost_return_version INTEGER NOT NULL DEFAULT 0 CHECK(cost_return_version >= 0)",
    "ALTER TABLE order_items ADD COLUMN inventory_reversed INTEGER NOT NULL DEFAULT 0 CHECK(inventory_reversed IN (0, 1))",
    "ALTER TABLE order_items ADD COLUMN inventory_reversal_version INTEGER NOT NULL DEFAULT 0 CHECK(inventory_reversal_version >= 0)",
    "ALTER TABLE order_item_batches ADD COLUMN cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN returned_total_qty INTEGER NOT NULL DEFAULT 0 CHECK(returned_total_qty >= 0 AND returned_total_qty <= 1000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN returned_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(returned_known_qty >= 0 AND returned_known_qty <= 1000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN returned_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(returned_unknown_qty >= 0 AND returned_unknown_qty <= 1000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN returned_cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(returned_cost_basis_vnd >= 0 AND returned_cost_basis_vnd <= 9000000000000000)",
    "ALTER TABLE order_item_batches ADD COLUMN cost_return_version INTEGER NOT NULL DEFAULT 0 CHECK(cost_return_version >= 0)",
    "ALTER TABLE order_item_batches ADD COLUMN inventory_reversed INTEGER NOT NULL DEFAULT 0 CHECK(inventory_reversed IN (0, 1))",
    "ALTER TABLE order_item_batches ADD COLUMN inventory_reversal_version INTEGER NOT NULL DEFAULT 0 CHECK(inventory_reversal_version >= 0)",
    "ALTER TABLE order_returns ADD COLUMN refund_vnd INTEGER NOT NULL DEFAULT 0 CHECK(refund_vnd >= 0 AND refund_vnd <= 9000000000000000)",
    "ALTER TABLE order_return_items ADD COLUMN unit_price_vnd INTEGER NOT NULL DEFAULT 0 CHECK(unit_price_vnd >= 0 AND unit_price_vnd <= 9000000000000000)",
    "ALTER TABLE order_return_items ADD COLUMN refund_vnd INTEGER NOT NULL DEFAULT 0 CHECK(refund_vnd >= 0 AND refund_vnd <= 9000000000000000)",
    "ALTER TABLE order_return_items ADD COLUMN cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000)",
    "ALTER TABLE order_return_items ADD COLUMN cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000)",
    "ALTER TABLE order_return_items ADD COLUMN cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000)",
    "CREATE UNIQUE INDEX ux_order_return_items_event_source ON order_return_items (return_id, order_item_id)",
    "CREATE TABLE order_return_item_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, return_item_id INTEGER NOT NULL, source_order_item_batch_id INTEGER NOT NULL, batch_id INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0 AND quantity <= 1000000000), cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000), cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000), cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000), restocked INTEGER NOT NULL DEFAULT 1 CHECK(restocked IN (0, 1)), FOREIGN KEY(return_item_id) REFERENCES order_return_items(id), FOREIGN KEY(source_order_item_batch_id) REFERENCES order_item_batches(id), FOREIGN KEY(batch_id) REFERENCES product_batches(id), UNIQUE(return_item_id, source_order_item_batch_id))",
    "CREATE INDEX ix_order_return_item_batches_return_item ON order_return_item_batches (return_item_id)",
    "CREATE INDEX ix_order_return_item_batches_source ON order_return_item_batches (source_order_item_batch_id)",
    "CREATE UNIQUE INDEX ux_order_return_item_batches_event_source ON order_return_item_batches (return_item_id, source_order_item_batch_id)",
    "CREATE TABLE offline_batch_stock_deficits (id INTEGER PRIMARY KEY AUTOINCREMENT, order_item_id INTEGER NOT NULL, product_id INTEGER NOT NULL, deficit_quantity INTEGER NOT NULL CHECK(deficit_quantity > 0 AND deficit_quantity <= 1000000000), remaining_quantity INTEGER NOT NULL CHECK(remaining_quantity >= 0 AND remaining_quantity <= deficit_quantity), resolution_kind VARCHAR(32), state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0), CHECK((remaining_quantity > 0 AND resolution_kind IS NULL) OR (remaining_quantity = 0 AND resolution_kind IN ('STOCKTAKE', 'MIGRATION_RECONCILED'))), FOREIGN KEY(order_item_id) REFERENCES order_items(id), FOREIGN KEY(product_id) REFERENCES products(id))",
    "CREATE UNIQUE INDEX ux_offline_batch_stock_deficits_order_item ON offline_batch_stock_deficits (order_item_id)",
    "CREATE INDEX ix_offline_batch_stock_deficits_product ON offline_batch_stock_deficits (product_id)",
    "CREATE TRIGGER trg_i05_offline_batch_deficit_update BEFORE UPDATE ON offline_batch_stock_deficits FOR EACH ROW WHEN NEW.order_item_id<>OLD.order_item_id OR NEW.product_id<>OLD.product_id OR NEW.deficit_quantity<>OLD.deficit_quantity OR NOT (OLD.remaining_quantity>0 AND NEW.remaining_quantity=0 AND NEW.resolution_kind='STOCKTAKE' AND OLD.resolution_kind IS NULL AND NEW.state_version=OLD.state_version+1) BEGIN SELECT RAISE(ABORT, 'I05_OFFLINE_DEFICIT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i05_offline_batch_deficit_delete BEFORE DELETE ON offline_batch_stock_deficits FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'I05_OFFLINE_DEFICIT_IMMUTABLE'); END",
    # SQLite validates an ADD COLUMN default against every existing row.  A
    # fake positive default would make the ALTER pass but could silently turn
    # a future omitted amount into money.  Add nullable-with-range, backfill
    # every legacy row exactly below, and make requiredness durable with the
    # INSERT/UPDATE triggers in the same transaction.
    "ALTER TABLE order_payments ADD COLUMN amount_vnd INTEGER CHECK(amount_vnd IS NULL OR (amount_vnd > 0 AND amount_vnd <= 9000000000000000))",
    "CREATE TRIGGER trg_i05_order_payments_amount_vnd_insert BEFORE INSERT ON order_payments FOR EACH ROW WHEN NEW.amount_vnd IS NULL BEGIN SELECT RAISE(ABORT, 'I05_REQUIRED_VND:order_payments.amount_vnd'); END",
    "CREATE TRIGGER trg_i05_order_payments_amount_vnd_update BEFORE UPDATE OF amount_vnd ON order_payments FOR EACH ROW WHEN NEW.amount_vnd IS NULL BEGIN SELECT RAISE(ABORT, 'I05_REQUIRED_VND:order_payments.amount_vnd'); END",
    "ALTER TABLE cash_shifts ADD COLUMN opening_cash_vnd INTEGER NOT NULL DEFAULT 0 CHECK(opening_cash_vnd >= 0 AND opening_cash_vnd <= 9000000000000000)",
    "ALTER TABLE cash_shifts ADD COLUMN counted_cash_vnd INTEGER CHECK(counted_cash_vnd IS NULL OR (counted_cash_vnd >= 0 AND counted_cash_vnd <= 9000000000000000))",
    "ALTER TABLE cash_shifts ADD COLUMN expected_cash_vnd INTEGER CHECK(expected_cash_vnd IS NULL OR (expected_cash_vnd >= 0 AND expected_cash_vnd <= 9000000000000000))",
    "ALTER TABLE cash_shifts ADD COLUMN variance_vnd INTEGER CHECK(variance_vnd IS NULL OR (variance_vnd >= -9000000000000000 AND variance_vnd <= 9000000000000000))",
    "ALTER TABLE cash_movements ADD COLUMN amount_vnd INTEGER CHECK(amount_vnd IS NULL OR (amount_vnd > 0 AND amount_vnd <= 9000000000000000))",
    "CREATE TRIGGER trg_i05_cash_movements_amount_vnd_insert BEFORE INSERT ON cash_movements FOR EACH ROW WHEN NEW.amount_vnd IS NULL BEGIN SELECT RAISE(ABORT, 'I05_REQUIRED_VND:cash_movements.amount_vnd'); END",
    "CREATE TRIGGER trg_i05_cash_movements_amount_vnd_update BEFORE UPDATE OF amount_vnd ON cash_movements FOR EACH ROW WHEN NEW.amount_vnd IS NULL BEGIN SELECT RAISE(ABORT, 'I05_REQUIRED_VND:cash_movements.amount_vnd'); END",
    "ALTER TABLE customers ADD COLUMN credit_limit_vnd INTEGER CHECK(credit_limit_vnd IS NULL OR (credit_limit_vnd >= 0 AND credit_limit_vnd <= 9000000000000000))",
    "ALTER TABLE loyalty_programs ADD COLUMN earn_amount_vnd INTEGER CHECK(earn_amount_vnd IS NULL OR (earn_amount_vnd > 0 AND earn_amount_vnd <= 9000000000000000))",
    "ALTER TABLE loyalty_programs ADD COLUMN redeem_amount_vnd INTEGER CHECK(redeem_amount_vnd IS NULL OR (redeem_amount_vnd > 0 AND redeem_amount_vnd <= 9000000000000000))",
    "ALTER TABLE loyalty_programs ADD COLUMN max_redeem_bps INTEGER NOT NULL DEFAULT 10000 CHECK(max_redeem_bps >= 0 AND max_redeem_bps <= 10000)",
    "ALTER TABLE vouchers ADD COLUMN discount_value_vnd INTEGER CHECK(discount_value_vnd IS NULL OR (discount_value_vnd >= 0 AND discount_value_vnd <= 9000000000000000))",
    "ALTER TABLE vouchers ADD COLUMN discount_bps INTEGER CHECK(discount_bps IS NULL OR (discount_bps >= 0 AND discount_bps <= 10000))",
    "ALTER TABLE vouchers ADD COLUMN min_order_vnd INTEGER NOT NULL DEFAULT 0 CHECK(min_order_vnd >= 0 AND min_order_vnd <= 9000000000000000)",
    "ALTER TABLE vouchers ADD COLUMN max_discount_vnd INTEGER NOT NULL DEFAULT 0 CHECK(max_discount_vnd >= 0 AND max_discount_vnd <= 9000000000000000)",
    "ALTER TABLE stock_write_off_items ADD COLUMN cost_known_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_known_qty >= 0 AND cost_known_qty <= 1000000000)",
    "ALTER TABLE stock_write_off_items ADD COLUMN cost_unknown_qty INTEGER NOT NULL DEFAULT 0 CHECK(cost_unknown_qty >= 0 AND cost_unknown_qty <= 1000000000)",
    "ALTER TABLE stock_write_off_items ADD COLUMN cost_basis_vnd INTEGER NOT NULL DEFAULT 0 CHECK(cost_basis_vnd >= 0 AND cost_basis_vnd <= 9000000000000000)",
)

EXPECTED_COLUMNS = {
    "products": ("price_vnd", "cost_known_qty", "cost_unknown_qty", "cost_basis_vnd", "cost_deficit_qty", "cost_state_version"),
    "product_batches": ("cost_known_qty", "cost_unknown_qty", "cost_basis_vnd", "cost_deficit_qty", "cost_state_version"),
    "orders": ("total_vnd", "discount_vnd", "paid_vnd", "cash_paid_vnd", "inventory_reversed"),
    "order_items": ("unit_price_vnd", "net_amount_vnd", "cost_known_qty", "returned_total_qty", "returned_cost_basis_vnd", "cost_return_version"),
    "order_item_batches": ("cost_known_qty", "returned_total_qty", "cost_return_version"),
    "order_returns": ("refund_vnd",),
    "order_return_items": ("unit_price_vnd", "refund_vnd", "cost_basis_vnd"),
    "offline_batch_stock_deficits": (
        "order_item_id",
        "product_id",
        "deficit_quantity",
        "remaining_quantity",
        "state_version",
    ),
    "order_payments": ("amount_vnd",),
    "cash_shifts": ("opening_cash_vnd", "variance_vnd"),
    "cash_movements": ("amount_vnd",),
    "customers": ("credit_limit_vnd",),
    "loyalty_programs": ("earn_amount_vnd", "redeem_amount_vnd", "max_redeem_bps"),
    "vouchers": ("discount_value_vnd", "discount_bps", "min_order_vnd", "max_discount_vnd"),
    "stock_write_off_items": ("cost_known_qty", "cost_unknown_qty", "cost_basis_vnd"),
}

MONEY_COLUMNS = (
    ("products", "price", "price_vnd", False, False),
    ("orders", "total_amount", "total_vnd", False, False),
    ("orders", "discount_amount", "discount_vnd", False, False),
    ("orders", "cash_tendered_amount", "cash_tendered_vnd", True, False),
    ("orders", "cash_change_amount", "cash_change_vnd", True, False),
    ("orders", "paid_amount", "paid_vnd", True, False),
    ("orders", "cash_paid_amount", "cash_paid_vnd", False, False),
    ("orders", "refunded_amount", "refunded_vnd", False, False),
    ("orders", "refund_due_amount", "refund_due_vnd", False, False),
    ("orders", "loyalty_discount_amount", "loyalty_discount_vnd", False, False),
    ("orders", "loyalty_earn_amount_step", "loyalty_earn_amount_step_vnd", True, False),
    ("order_items", "price", "unit_price_vnd", False, False),
    ("order_returns", "refund_amount", "refund_vnd", False, False),
    ("order_return_items", "unit_price", "unit_price_vnd", False, False),
    ("order_return_items", "refund_amount", "refund_vnd", False, False),
    ("order_payments", "amount", "amount_vnd", False, False),
    ("cash_shifts", "opening_cash_amount", "opening_cash_vnd", False, False),
    ("cash_shifts", "counted_cash_amount", "counted_cash_vnd", True, False),
    ("cash_shifts", "expected_cash_amount", "expected_cash_vnd", True, False),
    ("cash_shifts", "variance_amount", "variance_vnd", True, True),
    ("cash_movements", "amount", "amount_vnd", False, False),
    ("customers", "credit_limit", "credit_limit_vnd", True, False),
    ("loyalty_programs", "earn_amount", "earn_amount_vnd", True, False),
    ("loyalty_programs", "redeem_amount", "redeem_amount_vnd", True, False),
)

INTEGER_MONEY_COLUMNS = (
    ("expense_templates", "amount", False, False),
    ("operating_expenses", "amount", False, False),
    ("purchase_receipts", "total_amount", False, False),
    ("purchase_receipt_items", "unit_cost", False, False),
    ("supplier_payable_entries", "amount", False, False),
    ("supplier_payments", "amount", False, False),
    ("supplier_payment_allocations", "amount", False, False),
    ("subscription_checkouts", "amount_due_vnd", False, False),
    ("subscription_checkouts", "received_amount_vnd", False, False),
    ("subscription_checkouts", "refund_due_amount_vnd", False, False),
    ("subscription_payments", "amount_vnd", False, False),
)

QUANTITY_COLUMNS = (
    ("products", "stock", True),
    ("product_batches", "quantity", False),
    ("order_items", "quantity", False),
    ("order_item_batches", "quantity", False),
    ("order_return_items", "quantity", False),
    ("purchase_receipt_items", "quantity", False),
    ("stock_write_off_items", "quantity", False),
    ("stock_write_offs", "total_quantity", False),
)

# Durable verifier coverage.  SQLite's declared affinity is not sufficient:
# a malformed writer can still store TEXT in an INTEGER column.  Verify both
# runtime type and range for every canonical financial value, including I04
# INTEGER columns normalized by this revision.
VERIFY_MONEY_COLUMNS = tuple(
    (table, canonical, nullable, allow_negative)
    for table, _legacy, canonical, nullable, allow_negative in MONEY_COLUMNS
) + INTEGER_MONEY_COLUMNS + (
    ("products", "cost_basis_vnd", False, False),
    ("product_batches", "cost_basis_vnd", False, False),
    ("order_items", "discount_vnd", False, False),
    ("order_items", "loyalty_discount_vnd", False, False),
    ("order_items", "net_amount_vnd", False, False),
    ("order_items", "cost_basis_vnd", False, False),
    ("order_items", "returned_cost_basis_vnd", False, False),
    ("order_items", "returned_refund_vnd", False, False),
    ("order_item_batches", "cost_basis_vnd", False, False),
    ("order_item_batches", "returned_cost_basis_vnd", False, False),
    ("order_return_items", "cost_basis_vnd", False, False),
    ("order_return_item_batches", "cost_basis_vnd", False, False),
    ("vouchers", "discount_value_vnd", True, False),
    ("vouchers", "min_order_vnd", False, False),
    ("vouchers", "max_discount_vnd", False, False),
    ("stock_write_off_items", "cost_basis_vnd", False, False),
)

VERIFY_QUANTITY_COLUMNS = QUANTITY_COLUMNS + (
    ("products", "cost_known_qty", False),
    ("products", "cost_unknown_qty", False),
    ("products", "cost_deficit_qty", False),
    ("product_batches", "cost_known_qty", False),
    ("product_batches", "cost_unknown_qty", False),
    ("product_batches", "cost_deficit_qty", False),
    ("order_items", "cost_known_qty", False),
    ("order_items", "cost_unknown_qty", False),
    ("order_items", "returned_total_qty", False),
    ("order_items", "returned_known_qty", False),
    ("order_items", "returned_unknown_qty", False),
    ("order_item_batches", "cost_known_qty", False),
    ("order_item_batches", "cost_unknown_qty", False),
    ("order_item_batches", "returned_total_qty", False),
    ("order_item_batches", "returned_known_qty", False),
    ("order_item_batches", "returned_unknown_qty", False),
    ("order_return_items", "cost_known_qty", False),
    ("order_return_items", "cost_unknown_qty", False),
    ("order_return_item_batches", "quantity", False),
    ("order_return_item_batches", "cost_known_qty", False),
    ("order_return_item_batches", "cost_unknown_qty", False),
    ("offline_batch_stock_deficits", "deficit_quantity", False),
    ("offline_batch_stock_deficits", "remaining_quantity", False),
    ("stock_write_off_items", "cost_known_qty", False),
    ("stock_write_off_items", "cost_unknown_qty", False),
)


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def _execute_params(connection, statement, parameters):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    execute(statement, parameters)


def _fail(table, column, code):
    raise RuntimeError("I05_" + code + ":" + table + "." + column)


def _plain_parts(value, table, column):
    if isinstance(value, bool) or value is None:
        _fail(table, column, "CORRUPT_NUMERIC")
    if isinstance(value, int):
        return ("-" if value < 0 else ""), str(abs(value)), ""
    raw = str(value).strip()
    if not raw:
        _fail(table, column, "CORRUPT_NUMERIC")
    sign = ""
    if raw[0] in "+-":
        sign, raw = raw[0], raw[1:]
    pieces = raw.split(".")
    if len(pieces) > 2 or not pieces[0].isdigit():
        _fail(table, column, "CORRUPT_NUMERIC")
    fraction = pieces[1] if len(pieces) == 2 else ""
    if fraction and not fraction.isdigit():
        _fail(table, column, "CORRUPT_NUMERIC")
    return sign, pieces[0], fraction


def _exact_vnd(value, table, column, nullable=False, allow_negative=False):
    if value is None and nullable:
        return None
    sign, whole, fraction = _plain_parts(value, table, column)
    if fraction and any(char != "0" for char in fraction):
        _fail(table, column, "FRACTIONAL_VND")
    number = int(whole)
    if sign == "-":
        number = -number
    if number < 0 and not allow_negative:
        _fail(table, column, "NEGATIVE_VND")
    if abs(number) > MAX_SAFE_VND:
        _fail(table, column, "VND_OVERFLOW")
    return number


def _exact_percentage_bps(value, table, column):
    sign, whole, fraction = _plain_parts(value, table, column)
    if sign == "-":
        _fail(table, column, "RATE_RANGE")
    significant = (fraction + "00")[:2]
    if len(fraction) > 2 and any(char != "0" for char in fraction[2:]):
        _fail(table, column, "RATE_FRACTION")
    bps = int(whole) * 100 + int(significant or "0")
    if bps < 0 or bps > 10000:
        _fail(table, column, "RATE_RANGE")
    return bps


def _exact_quantity(value, table, column, allow_negative=False):
    number = _exact_vnd(value, table, column, False, allow_negative)
    if abs(number) > MAX_SAFE_QUANTITY:
        _fail(table, column, "QUANTITY_OVERFLOW")
    return number


def _rows(connection, statement):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    return execute(statement).fetchall()


def _largest_remainder(total, rows):
    if not rows:
        if total:
            raise RuntimeError("I05_ALLOCATION_WITHOUT_DESTINATION")
        return {}
    weight_sum = sum(row[1] for row in rows)
    if total == 0:
        return {row[0]: 0 for row in rows}
    if weight_sum <= 0:
        raise RuntimeError("I05_ALLOCATION_ZERO_WEIGHT")
    result = {}
    remainders = []
    floor_sum = 0
    for destination_id, weight in rows:
        floor_value, remainder = divmod(total * weight, weight_sum)
        result[destination_id] = floor_value
        floor_sum += floor_value
        remainders.append((remainder, destination_id))
    for _, destination_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[: total - floor_sum]:
        result[destination_id] += 1
    return result


def _collect_backfill(connection):
    updates = []
    for table, legacy, canonical, nullable, allow_negative in MONEY_COLUMNS:
        for row_id, value in _rows(connection, "SELECT id, " + legacy + " FROM " + table + " ORDER BY id"):
            updates.append((table, canonical, row_id, _exact_vnd(value, table, legacy, nullable, allow_negative)))

    normalized = []
    for table, column, nullable, allow_negative in INTEGER_MONEY_COLUMNS:
        for row_id, value in _rows(connection, "SELECT id, " + column + " FROM " + table + " ORDER BY id"):
            normalized.append((table, column, row_id, _exact_vnd(value, table, column, nullable, allow_negative)))
    for table, column, allow_negative in QUANTITY_COLUMNS:
        for row_id, value in _rows(connection, "SELECT id, " + column + " FROM " + table + " ORDER BY id"):
            normalized.append((table, column, row_id, _exact_quantity(value, table, column, allow_negative)))

    vouchers = []
    for row_id, kind, value, minimum, maximum in _rows(connection, "SELECT id, discount_type, discount_value, min_order_value, max_discount FROM vouchers ORDER BY id"):
        if kind == "percentage":
            value_vnd = None
            bps = _exact_percentage_bps(value, "vouchers", "discount_value")
        elif kind == "flat":
            value_vnd = _exact_vnd(value, "vouchers", "discount_value")
            bps = None
        else:
            _fail("vouchers", "discount_type", "AMBIGUOUS_RATE")
        vouchers.append((row_id, value_vnd, bps, _exact_vnd(minimum, "vouchers", "min_order_value"), _exact_vnd(maximum, "vouchers", "max_discount")))

    loyalty_rates = []
    for row_id, value in _rows(connection, "SELECT id, max_redeem_percent FROM loyalty_programs ORDER BY id"):
        loyalty_rates.append((row_id, _exact_percentage_bps(value, "loyalty_programs", "max_redeem_percent")))
    return updates, normalized, vouchers, loyalty_rates


def _prepare_documents(connection):
    order_values = {}
    for row in _rows(connection, "SELECT id, total_amount, discount_amount, loyalty_discount_amount, status, reconciliation_reason, offline_issue FROM orders ORDER BY id"):
        order_values[row[0]] = {
            "total": _exact_vnd(row[1], "orders", "total_amount"),
            "discount": _exact_vnd(row[2], "orders", "discount_amount"),
            "loyalty": _exact_vnd(row[3], "orders", "loyalty_discount_amount"),
            "status": row[4],
            "reason": row[5],
            "offline_issue": row[6],
        }
    items = {}
    for item_id, order_id, product_id, price, quantity in _rows(connection, "SELECT id, order_id, product_id, price, quantity FROM order_items ORDER BY id"):
        unit = _exact_vnd(price, "order_items", "price")
        qty = _exact_quantity(quantity, "order_items", "quantity")
        if qty <= 0 or (unit and qty > MAX_SAFE_VND // unit):
            _fail("order_items", "quantity", "DOCUMENT_OVERFLOW")
        items[item_id] = {
            "order_id": order_id,
            "product_id": product_id,
            "unit": unit,
            "qty": qty,
            "gross": unit * qty,
        }
    allocations = {}
    for order_id, order in order_values.items():
        lines = [(item_id, item["gross"]) for item_id, item in items.items() if item["order_id"] == order_id]
        gross = sum(weight for _, weight in lines)
        if gross > MAX_SAFE_VND:
            _fail("orders", "total_amount", "DOCUMENT_OVERFLOW")
        if gross - order["discount"] - order["loyalty"] != order["total"]:
            _fail("orders", "total_amount", "AMBIGUOUS_DOCUMENT_TOTAL")
        discount = _largest_remainder(order["discount"], lines)
        after_voucher = [(item_id, weight - discount[item_id]) for item_id, weight in lines]
        loyalty = _largest_remainder(order["loyalty"], after_voucher)
        for item_id, weight in lines:
            net = weight - discount[item_id] - loyalty[item_id]
            if net < 0:
                _fail("order_items", "price", "NEGATIVE_LINE_TOTAL")
            allocations[item_id] = (discount[item_id], loyalty[item_id], net)
    return order_values, items, allocations


def _prepare_cost_provenance(connection, order_values, items):
    products = {}
    for product_id, stock, tracked in _rows(connection, "SELECT id, stock, track_batches FROM products ORDER BY id"):
        qty = _exact_quantity(stock, "products", "stock", True)
        products[product_id] = {"stock": qty, "tracked": bool(tracked)}
    batches = {}
    for batch_id, product_id, quantity in _rows(connection, "SELECT id, product_id, quantity FROM product_batches ORDER BY id"):
        qty = _exact_quantity(quantity, "product_batches", "quantity")
        if qty < 0:
            _fail("product_batches", "quantity", "NEGATIVE_QUANTITY")
        batches[batch_id] = {"product_id": product_id, "qty": qty, "repair": 0}

    sources = {}
    sources_by_item = {}
    for source_id, item_id, batch_id, quantity in _rows(connection, "SELECT id, order_item_id, batch_id, quantity FROM order_item_batches ORDER BY id"):
        qty = _exact_quantity(quantity, "order_item_batches", "quantity")
        if qty <= 0:
            _fail("order_item_batches", "quantity", "NONPOSITIVE_QUANTITY")
        item = items.get(item_id)
        batch = batches.get(batch_id)
        if (
            item is None
            or batch is None
            or batch["product_id"] != item["product_id"]
        ):
            _fail(
                "order_item_batches",
                "batch_id",
                "SOURCE_PRODUCT_PROVENANCE",
            )
        sources[source_id] = {"item_id": item_id, "batch_id": batch_id, "qty": qty, "returned": 0, "reversed": 0}
        sources_by_item.setdefault(item_id, []).append(source_id)

    # A tracked offline sale may have a source-less tail because the goods had
    # already left the shop before sync. Preserve that exact gap as durable
    # evidence; the order-level TON_AM flag alone is not sufficient because it
    # neither identifies the product nor the unresolved quantity.
    offline_deficits = []
    for item_id, item in items.items():
        source_ids = sources_by_item.get(item_id, [])
        allocated = sum(sources[source_id]["qty"] for source_id in source_ids)
        if allocated > item["qty"]:
            _fail("order_item_batches", "quantity", "SOURCE_RECONCILIATION")
        if allocated == item["qty"]:
            continue
        product = products.get(item["product_id"])
        order = order_values.get(item["order_id"])
        issues = {
            part.strip()
            for part in str(order["offline_issue"] or "").split(",")
            if part.strip()
        } if order else set()
        if product and product["tracked"] and "TON_AM" in issues:
            offline_deficits.append({
                "order_item_id": item_id,
                "order_id": item["order_id"],
                "product_id": item["product_id"],
                "quantity": item["qty"] - allocated,
            })
            continue
        # Preserve legacy lines with no batch allocations at all: they can
        # predate batch tracking. A partial allocation, however, is only valid
        # with exact durable offline-deficit evidence.
        if source_ids:
            _fail("order_item_batches", "quantity", "SOURCE_RECONCILIATION")
    offline_deficit_item_ids = {
        row["order_item_id"] for row in offline_deficits
    }

    returned_by_item = {}
    refund_by_item = {}
    return_provenance = []
    duplicate_pairs = set()
    return_rows = _rows(connection, "SELECT ri.id, ri.return_id, ri.order_item_id, ri.quantity, ri.refund_amount, ri.restocked FROM order_return_items ri ORDER BY ri.return_id, ri.id")
    for return_item_id, return_id, item_id, quantity, refund, restocked in return_rows:
        pair = (return_id, item_id)
        if pair in duplicate_pairs:
            _fail("order_return_items", "order_item_id", "DUPLICATE_EVENT_SOURCE")
        duplicate_pairs.add(pair)
        qty = _exact_quantity(quantity, "order_return_items", "quantity")
        if qty > 0 and item_id in offline_deficit_item_ids:
            _fail(
                "order_return_items",
                "quantity",
                "OFFLINE_DEFICIT_RETURN_PROVENANCE",
            )
        amount = _exact_vnd(refund, "order_return_items", "refund_amount")
        returned_by_item[item_id] = returned_by_item.get(item_id, 0) + qty
        refund_by_item[item_id] = refund_by_item.get(item_id, 0) + amount
        if item_id in sources_by_item:
            remaining = qty
            for source_id in sorted(sources_by_item[item_id], reverse=True):
                source = sources[source_id]
                available = source["qty"] - source["returned"]
                take = min(available, remaining)
                if take <= 0:
                    continue
                source["returned"] += take
                if restocked:
                    batches[source["batch_id"]]["repair"] += take
                return_provenance.append((return_item_id, source_id, source["batch_id"], take, 1 if restocked else 0))
                remaining -= take
                if remaining == 0:
                    break
            if remaining:
                _fail("order_return_items", "quantity", "RETURN_SOURCE_RECONCILIATION")

    for item_id, returned in returned_by_item.items():
        if item_id not in items or returned > items[item_id]["qty"]:
            _fail("order_return_items", "quantity", "OVER_RETURNED")

    open_deficit_items = set()
    for product_id, product in products.items():
        if not product["tracked"]:
            continue
        current = sum(batch["qty"] for batch in batches.values() if batch["product_id"] == product_id)
        repair = sum(batch["repair"] for batch in batches.values() if batch["product_id"] == product_id)
        unresolved = current + repair - product["stock"]
        if unresolved < 0:
            _fail("product_batches", "quantity", "BATCH_STOCK_RECONCILIATION")
        candidates = sorted(
            (
                row for row in offline_deficits
                if row["product_id"] == product_id
            ),
            key=lambda row: row["order_item_id"],
            reverse=True,
        )
        remaining = unresolved
        for row in candidates:
            if remaining == 0:
                break
            if row["quantity"] > remaining:
                _fail(
                    "offline_batch_stock_deficits",
                    "remaining_quantity",
                    "AMBIGUOUS_BATCH_DEFICIT",
                )
            open_deficit_items.add(row["order_item_id"])
            remaining -= row["quantity"]
        if remaining:
            _fail("product_batches", "quantity", "BATCH_STOCK_RECONCILIATION")

    reversed_orders = {
        order_id for order_id, value in order_values.items()
        if value["status"] == "CANCELLED" or value["reason"] == "LATE_PAYMENT"
    }
    if any(row["order_id"] in reversed_orders for row in offline_deficits):
        _fail(
            "offline_batch_stock_deficits",
            "order_item_id",
            "OFFLINE_DEFICIT_REVERSAL",
        )
    for row in offline_deficits:
        is_open = row["order_item_id"] in open_deficit_items
        row["remaining_quantity"] = row["quantity"] if is_open else 0
        row["resolution_kind"] = None if is_open else "MIGRATION_RECONCILED"
    return (
        products,
        batches,
        sources,
        returned_by_item,
        refund_by_item,
        return_provenance,
        reversed_orders,
        offline_deficits,
    )


def upgrade():
    connection = op.get_bind()
    updates, normalized, vouchers, loyalty_rates = _collect_backfill(connection)
    order_values, items, allocations = _prepare_documents(connection)
    (
        products,
        batches,
        sources,
        returned_by_item,
        refund_by_item,
        return_provenance,
        reversed_orders,
        offline_deficits,
    ) = _prepare_cost_provenance(connection, order_values, items)

    for statement in DDL:
        _execute(statement)
    for table, column, row_id, value in updates:
        _execute_params(connection, "UPDATE " + table + " SET " + column + " = ? WHERE id = ?", (value, row_id))
    for table, column, row_id, value in normalized:
        _execute_params(connection, "UPDATE " + table + " SET " + column + " = ? WHERE id = ?", (value, row_id))
    for row_id, value_vnd, bps, minimum, maximum in vouchers:
        _execute_params(connection, "UPDATE vouchers SET discount_value_vnd=?, discount_bps=?, min_order_vnd=?, max_discount_vnd=? WHERE id=?", (value_vnd, bps, minimum, maximum, row_id))
    for row_id, bps in loyalty_rates:
        _execute_params(connection, "UPDATE loyalty_programs SET max_redeem_bps=? WHERE id=?", (bps, row_id))
    # Legacy write-off Float cost_price is only a hint and never sufficient
    # provenance for known cost. Every legacy quantity is canonical unknown.
    _execute(
        "UPDATE stock_write_off_items "
        "SET cost_known_qty=0, cost_unknown_qty=quantity, cost_basis_vnd=0"
    )

    for item_id, item in items.items():
        discount, loyalty, net = allocations[item_id]
        returned = returned_by_item.get(item_id, 0)
        refunded = refund_by_item.get(item_id, 0)
        _execute_params(connection, "UPDATE order_items SET discount_vnd=?, loyalty_discount_vnd=?, net_amount_vnd=?, cost_unknown_qty=quantity, returned_total_qty=?, returned_unknown_qty=?, returned_refund_vnd=? WHERE id=?", (discount, loyalty, net, returned, returned, refunded, item_id))
    for source_id, source in sources.items():
        reversed_flag = 1 if items[source["item_id"]]["order_id"] in reversed_orders else 0
        _execute_params(connection, "UPDATE order_item_batches SET cost_unknown_qty=quantity, returned_total_qty=?, returned_unknown_qty=?, inventory_reversed=?, inventory_reversal_version=? WHERE id=?", (source["returned"], source["returned"], reversed_flag, reversed_flag, source_id))
    for product_id, product in products.items():
        if product["tracked"]:
            _execute_params(connection, "UPDATE products SET cost_known_qty=0, cost_unknown_qty=0, cost_basis_vnd=0, cost_deficit_qty=0 WHERE id=?", (product_id,))
        elif product["stock"] >= 0:
            _execute_params(connection, "UPDATE products SET cost_unknown_qty=?, cost_deficit_qty=0 WHERE id=?", (product["stock"], product_id))
        else:
            _execute_params(connection, "UPDATE products SET cost_unknown_qty=0, cost_deficit_qty=? WHERE id=?", (-product["stock"], product_id))
    for batch_id, batch in batches.items():
        final_quantity = batch["qty"] + batch["repair"]
        _execute_params(connection, "UPDATE product_batches SET quantity=?, cost_unknown_qty=? WHERE id=?", (final_quantity, final_quantity, batch_id))
    for order_id in reversed_orders:
        key = "cancel:order:" + str(order_id)
        _execute_params(connection, "UPDATE orders SET inventory_reversed=1, inventory_reversal_key=?, inventory_reversal_version=1 WHERE id=?", (key, order_id))
        _execute_params(connection, "UPDATE order_items SET inventory_reversed=1, inventory_reversal_version=1 WHERE order_id=?", (order_id,))
    for return_item_id, source_id, batch_id, quantity, restocked in return_provenance:
        _execute_params(connection, "INSERT INTO order_return_item_batches (return_item_id, source_order_item_batch_id, batch_id, quantity, cost_known_qty, cost_unknown_qty, cost_basis_vnd, restocked) VALUES (?, ?, ?, ?, 0, ?, 0, ?)", (return_item_id, source_id, batch_id, quantity, quantity, restocked))
    for return_item_id, quantity in _rows(connection, "SELECT id, quantity FROM order_return_items ORDER BY id"):
        _execute_params(connection, "UPDATE order_return_items SET cost_unknown_qty=? WHERE id=?", (quantity, return_item_id))
    for row in offline_deficits:
        _execute_params(
            connection,
            "INSERT INTO offline_batch_stock_deficits "
            "(order_item_id, product_id, deficit_quantity, remaining_quantity, "
            "resolution_kind, state_version) VALUES (?, ?, ?, ?, ?, 0)",
            (
                row["order_item_id"],
                row["product_id"],
                row["quantity"],
                row["remaining_quantity"],
                row["resolution_kind"],
            ),
        )


def _verify_integer_range(execute, table, column, nullable, lower, upper, code):
    invalid = (
        "typeof(" + column + ") <> 'integer' OR "
        + column + " < " + str(lower) + " OR "
        + column + " > " + str(upper)
    )
    predicate = (
        column + " IS NOT NULL AND (" + invalid + ")"
        if nullable
        else column + " IS NULL OR " + invalid
    )
    if execute("SELECT COUNT(*) FROM " + table + " WHERE " + predicate).fetchone()[0]:
        raise RuntimeError(code + ":" + table + "." + column)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    objects = execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    names = {name for _, name in objects}
    required = {
        "order_return_item_batches",
        "offline_batch_stock_deficits",
        "ux_offline_batch_stock_deficits_order_item",
        "ix_offline_batch_stock_deficits_product",
        "ux_orders_inventory_reversal_key",
        "ux_order_return_items_event_source",
        "ux_order_return_item_batches_event_source",
        "trg_i05_order_payments_amount_vnd_insert",
        "trg_i05_order_payments_amount_vnd_update",
        "trg_i05_cash_movements_amount_vnd_insert",
        "trg_i05_cash_movements_amount_vnd_update",
        "trg_i05_offline_batch_deficit_update",
        "trg_i05_offline_batch_deficit_delete",
    }
    if not required.issubset(names):
        raise RuntimeError("I05_VERIFY_SCHEMA_OBJECTS")
    for table, expected in EXPECTED_COLUMNS.items():
        columns = {row[1]: str(row[2]).upper() for row in execute("PRAGMA table_info(" + table + ")").fetchall()}
        if any(columns.get(column) != "INTEGER" for column in expected):
            raise RuntimeError("I05_VERIFY_INTEGER_COLUMNS:" + table)

    for table, column, nullable, allow_negative in VERIFY_MONEY_COLUMNS:
        _verify_integer_range(
            execute,
            table,
            column,
            nullable,
            -MAX_SAFE_VND if allow_negative else 0,
            MAX_SAFE_VND,
            "I05_VERIFY_MONEY_RANGE",
        )
    for table, column, allow_negative in VERIFY_QUANTITY_COLUMNS:
        _verify_integer_range(
            execute,
            table,
            column,
            False,
            -MAX_SAFE_QUANTITY if allow_negative else 0,
            MAX_SAFE_QUANTITY,
            "I05_VERIFY_QUANTITY_RANGE",
        )
    if execute(
        """SELECT COUNT(*) FROM vouchers
           WHERE (discount_type='percentage' AND
                  (discount_bps IS NULL OR typeof(discount_bps)<>'integer' OR
                   discount_bps<0 OR discount_bps>10000 OR discount_value_vnd IS NOT NULL))
              OR (discount_type='flat' AND
                  (discount_value_vnd IS NULL OR discount_bps IS NOT NULL))
              OR discount_type NOT IN ('percentage', 'flat')"""
    ).fetchone()[0]:
        raise RuntimeError("I05_VERIFY_VOUCHER_RATE")
    if execute(
        """SELECT COUNT(*) FROM loyalty_programs
           WHERE max_redeem_bps IS NULL OR typeof(max_redeem_bps)<>'integer'
              OR max_redeem_bps<0 OR max_redeem_bps>10000"""
    ).fetchone()[0]:
        raise RuntimeError("I05_VERIFY_LOYALTY_RATE")

    tracked_products = {}
    product_stocks = {}
    for row in execute("SELECT id, track_batches, stock, cost_known_qty, cost_unknown_qty, cost_basis_vnd, cost_deficit_qty FROM products ORDER BY id").fetchall():
        product_id, tracked, stock, known, unknown, basis, deficit = row
        tracked_products[product_id] = bool(tracked)
        product_stocks[product_id] = stock
        if min(known, unknown, basis, deficit) < 0 or max(known, unknown, deficit) > MAX_SAFE_QUANTITY or basis > MAX_SAFE_VND:
            raise RuntimeError("I05_VERIFY_PRODUCT_RANGE")
        if known == 0 and basis != 0:
            raise RuntimeError("I05_VERIFY_PRODUCT_BASIS_WITHOUT_KNOWN")
        if not tracked and stock != known + unknown - deficit:
            raise RuntimeError("I05_VERIFY_PRODUCT_POOL")
        if tracked and (known or unknown or basis or deficit):
            raise RuntimeError("I05_VERIFY_TRACKED_PRODUCT_POOL")
    batch_totals = {}
    batch_products = {}
    for batch_id, product_id, quantity, known, unknown, basis, deficit in execute("SELECT id, product_id, quantity, cost_known_qty, cost_unknown_qty, cost_basis_vnd, cost_deficit_qty FROM product_batches ORDER BY id").fetchall():
        if quantity != known + unknown - deficit or min(known, unknown, basis, deficit) < 0:
            raise RuntimeError("I05_VERIFY_BATCH_POOL")
        if known == 0 and basis != 0:
            raise RuntimeError("I05_VERIFY_BATCH_BASIS_WITHOUT_KNOWN")
        batch_products[batch_id] = product_id
        batch_totals[product_id] = batch_totals.get(product_id, 0) + quantity

    offline_evidence = {}
    unresolved_by_product = {}
    evidence_rows = execute(
        """SELECT d.id, d.order_item_id, d.product_id, d.deficit_quantity,
                  d.remaining_quantity, d.resolution_kind, d.state_version,
                  i.id, i.product_id, i.quantity, i.returned_total_qty,
                  i.inventory_reversed, o.offline_issue, p.track_batches
           FROM offline_batch_stock_deficits d
           LEFT JOIN order_items i ON i.id=d.order_item_id
           LEFT JOIN orders o ON o.id=i.order_id
           LEFT JOIN products p ON p.id=d.product_id
           ORDER BY d.id"""
    ).fetchall()
    for row in evidence_rows:
        (
            _evidence_id,
            item_id,
            product_id,
            deficit_quantity,
            remaining_quantity,
            resolution_kind,
            state_version,
            joined_item_id,
            item_product_id,
            _item_quantity,
            returned_total,
            inventory_reversed,
            offline_issue,
            tracked,
        ) = row
        issues = {
            part.strip()
            for part in str(offline_issue or "").split(",")
            if part.strip()
        }
        if (
            joined_item_id is None
            or item_product_id != product_id
            or tracked != 1
            or "TON_AM" not in issues
            or not isinstance(state_version, int)
            or isinstance(state_version, bool)
            or state_version < 0
            or deficit_quantity <= 0
            or remaining_quantity < 0
            or remaining_quantity > deficit_quantity
            or (remaining_quantity > 0 and resolution_kind is not None)
            or (remaining_quantity > 0 and state_version != 0)
            or (
                remaining_quantity == 0
                and resolution_kind not in ("STOCKTAKE", "MIGRATION_RECONCILED")
            )
            or (resolution_kind == "STOCKTAKE" and state_version != 1)
            or (resolution_kind == "MIGRATION_RECONCILED" and state_version != 0)
            or returned_total != 0
            or inventory_reversed != 0
            or item_id in offline_evidence
        ):
            raise RuntimeError("I05_VERIFY_OFFLINE_BATCH_EVIDENCE")
        offline_evidence[item_id] = (
            product_id,
            deficit_quantity,
            remaining_quantity,
        )
        unresolved_by_product[product_id] = (
            unresolved_by_product.get(product_id, 0) + remaining_quantity
        )
    for product_id, tracked in tracked_products.items():
        if not tracked:
            continue
        stock = product_stocks[product_id]
        gap = batch_totals.get(product_id, 0) - stock
        if gap < 0 or gap != unresolved_by_product.get(product_id, 0):
            raise RuntimeError("I05_VERIFY_BATCH_STOCK_DEFICIT")

    line_totals = {}
    item_allocations = {}
    item_products = {}
    item_orders = {}
    for row in execute("SELECT id, order_id, product_id, quantity, unit_price_vnd, discount_vnd, loyalty_discount_vnd, net_amount_vnd, cost_known_qty, cost_unknown_qty, cost_basis_vnd, returned_total_qty, returned_known_qty, returned_unknown_qty, returned_cost_basis_vnd, returned_refund_vnd FROM order_items ORDER BY id").fetchall():
        item_id, order_id, product_id, quantity, unit, discount, loyalty, net, known, unknown, basis, returned, returned_known, returned_unknown, returned_basis, returned_refund = row
        if known + unknown != quantity or unit * quantity - discount - loyalty != net:
            raise RuntimeError("I05_VERIFY_ORDER_ITEM_ALLOCATION")
        if returned != returned_known + returned_unknown or returned > quantity or returned_basis > basis or returned_refund > net:
            raise RuntimeError("I05_VERIFY_ORDER_ITEM_RETURN")
        if (known == 0 and basis != 0) or (returned_known == 0 and returned_basis != 0):
            raise RuntimeError("I05_VERIFY_ORDER_ITEM_BASIS")
        line_totals[order_id] = line_totals.get(order_id, 0) + net
        item_allocations[item_id] = (
            quantity, known, unknown, basis,
            returned, returned_known, returned_unknown, returned_basis,
        )
        item_products[item_id] = product_id
        item_orders[item_id] = order_id
    for order_id, total in execute("SELECT id, total_vnd FROM orders ORDER BY id").fetchall():
        if line_totals.get(order_id, 0) != total:
            raise RuntimeError("I05_VERIFY_ORDER_TOTAL")
    source_totals = {}
    source_returned_totals = {}
    source_allocations = {}
    for source_id, item_id, batch_id, quantity, known, unknown, basis, returned, returned_known, returned_unknown, returned_basis in execute("SELECT id, order_item_id, batch_id, quantity, cost_known_qty, cost_unknown_qty, cost_basis_vnd, returned_total_qty, returned_known_qty, returned_unknown_qty, returned_cost_basis_vnd FROM order_item_batches ORDER BY id").fetchall():
        if (
            item_id not in item_allocations
            or batch_id not in batch_products
            or batch_products[batch_id] != item_products.get(item_id)
        ):
            raise RuntimeError("I05_VERIFY_BATCH_SOURCE_PRODUCT")
        if known + unknown != quantity or returned != returned_known + returned_unknown or returned > quantity or returned_basis > basis:
            raise RuntimeError("I05_VERIFY_BATCH_SOURCE")
        if (known == 0 and basis != 0) or (returned_known == 0 and returned_basis != 0):
            raise RuntimeError("I05_VERIFY_BATCH_SOURCE_BASIS")
        current = source_totals.get(item_id, (0, 0, 0, 0))
        source_totals[item_id] = tuple(
            current[index] + value
            for index, value in enumerate((quantity, known, unknown, basis))
        )
        current_returned = source_returned_totals.get(item_id, (0, 0, 0, 0))
        source_returned_totals[item_id] = tuple(
            current_returned[index] + value
            for index, value in enumerate(
                (returned, returned_known, returned_unknown, returned_basis)
            )
        )
        source_allocations[source_id] = (
            item_id, returned, returned_known, returned_unknown, returned_basis
        )
    for item_id, totals in source_totals.items():
        item_total = item_allocations.get(item_id, ())[:4]
        if item_id in offline_evidence:
            quantity, known, unknown, basis = item_total
            source_quantity, source_known, source_unknown, source_basis = totals
            evidence_product, deficit_quantity, _remaining = offline_evidence[item_id]
            if (
                item_products.get(item_id) != evidence_product
                or source_quantity + deficit_quantity != quantity
                or source_known != known
                or source_unknown + deficit_quantity != unknown
                or source_basis != basis
            ):
                raise RuntimeError("I05_VERIFY_OFFLINE_BATCH_DEFICIT")
        elif item_total != totals:
            raise RuntimeError("I05_VERIFY_BATCH_SOURCE_ALLOCATION")
        if item_allocations[item_id][4:] != source_returned_totals[item_id]:
            raise RuntimeError("I05_VERIFY_BATCH_SOURCE_RETURN")
    for item_id, (_product_id, deficit_quantity, _remaining) in offline_evidence.items():
        if item_id in source_totals:
            continue
        quantity, known, unknown, basis = item_allocations.get(item_id, (None,) * 8)[:4]
        if (
            quantity != deficit_quantity
            or known != 0
            or unknown != deficit_quantity
            or basis != 0
        ):
            raise RuntimeError("I05_VERIFY_OFFLINE_BATCH_DEFICIT")

    order_issues = {}
    for order_id, offline_issue in execute(
        "SELECT id, offline_issue FROM orders ORDER BY id"
    ).fetchall():
        order_issues[order_id] = {
            part.strip()
            for part in str(offline_issue or "").split(",")
            if part.strip()
        }
    for item_id, allocation in item_allocations.items():
        product_id = item_products[item_id]
        if (
            not tracked_products.get(product_id)
            or "TON_AM" not in order_issues.get(item_orders[item_id], set())
        ):
            continue
        source_quantity = source_totals.get(item_id, (0, 0, 0, 0))[0]
        gap = allocation[0] - source_quantity
        evidence = offline_evidence.get(item_id)
        if gap < 0 or (gap > 0 and (evidence is None or evidence[1] != gap)):
            raise RuntimeError("I05_VERIFY_OFFLINE_BATCH_DEFICIT_REQUIRED")
        if gap == 0 and evidence is not None:
            raise RuntimeError("I05_VERIFY_OFFLINE_BATCH_DEFICIT_UNEXPECTED")

    refund_totals = {}
    return_item_allocations = {}
    for return_item_id, return_id, item_id, quantity, refund, known, unknown, basis in execute("SELECT id, return_id, order_item_id, quantity, refund_vnd, cost_known_qty, cost_unknown_qty, cost_basis_vnd FROM order_return_items ORDER BY id").fetchall():
        if known + unknown != quantity or (known == 0 and basis != 0):
            raise RuntimeError("I05_VERIFY_RETURN_ITEM_ALLOCATION")
        refund_totals[return_id] = refund_totals.get(return_id, 0) + refund
        return_item_allocations[return_item_id] = (item_id, quantity, known, unknown, basis)
    for return_id, refund in execute("SELECT id, refund_vnd FROM order_returns ORDER BY id").fetchall():
        if refund_totals.get(return_id, 0) != refund:
            raise RuntimeError("I05_VERIFY_RETURN_TOTAL")

    return_batch_totals = {}
    provenance_by_source = {}
    for return_item_id, source_id, quantity, known, unknown, basis in execute("SELECT return_item_id, source_order_item_batch_id, quantity, cost_known_qty, cost_unknown_qty, cost_basis_vnd FROM order_return_item_batches ORDER BY id").fetchall():
        if known + unknown != quantity or (known == 0 and basis != 0):
            raise RuntimeError("I05_VERIFY_RETURN_BATCH_ALLOCATION")
        current = return_batch_totals.get(return_item_id, (0, 0, 0, 0))
        return_batch_totals[return_item_id] = tuple(
            current[index] + value
            for index, value in enumerate((quantity, known, unknown, basis))
        )
        current_source = provenance_by_source.get(source_id, (0, 0, 0, 0))
        provenance_by_source[source_id] = tuple(
            current_source[index] + value
            for index, value in enumerate((quantity, known, unknown, basis))
        )
    for return_item_id, totals in return_batch_totals.items():
        if return_item_id not in return_item_allocations:
            raise RuntimeError("I05_VERIFY_RETURN_BATCH_ORPHAN")
        if return_item_allocations[return_item_id][1:] != totals:
            raise RuntimeError("I05_VERIFY_RETURN_BATCH_TOTAL")
    batch_item_ids = set(source_totals)
    for return_item_id, allocation in return_item_allocations.items():
        if allocation[0] in batch_item_ids and return_item_id not in return_batch_totals:
            raise RuntimeError("I05_VERIFY_RETURN_BATCH_MISSING")
    for source_id, allocation in source_allocations.items():
        if provenance_by_source.get(source_id, (0, 0, 0, 0)) != allocation[1:]:
            raise RuntimeError("I05_VERIFY_RETURN_SOURCE_PROVENANCE")

    if execute(
        """SELECT COUNT(*) FROM orders
           WHERE (inventory_reversed=1 AND
                  (inventory_reversal_key IS NULL OR inventory_reversal_version<1))
              OR (inventory_reversed=0 AND
                  (inventory_reversal_key IS NOT NULL OR inventory_reversal_version<>0))"""
    ).fetchone()[0]:
        raise RuntimeError("I05_VERIFY_REVERSAL_MARKER")
    if execute(
        """SELECT COUNT(*) FROM order_items i JOIN orders o ON o.id=i.order_id
           WHERE i.inventory_reversed<>o.inventory_reversed
              OR (i.inventory_reversed=1 AND i.inventory_reversal_version<1)
              OR (i.inventory_reversed=0 AND i.inventory_reversal_version<>0)"""
    ).fetchone()[0]:
        raise RuntimeError("I05_VERIFY_REVERSAL_LINE")
    if execute(
        """SELECT COUNT(*) FROM order_item_batches b
           JOIN order_items i ON i.id=b.order_item_id
           WHERE b.inventory_reversed<>i.inventory_reversed
              OR (b.inventory_reversed=1 AND b.inventory_reversal_version<1)
              OR (b.inventory_reversed=0 AND b.inventory_reversal_version<>0)"""
    ).fetchone()[0]:
        raise RuntimeError("I05_VERIFY_REVERSAL_SOURCE")
    if execute(
        """SELECT COUNT(*) FROM order_return_items r
           JOIN order_items i ON i.id=r.order_item_id
           WHERE i.inventory_reversed=1"""
    ).fetchone()[0]:
        raise RuntimeError("I05_VERIFY_REVERSAL_AFTER_RETURN")
    for quantity, known, unknown, basis in execute(
        """SELECT quantity, cost_known_qty, cost_unknown_qty, cost_basis_vnd
           FROM stock_write_off_items ORDER BY id"""
    ).fetchall():
        if known + unknown != quantity:
            raise RuntimeError("I05_VERIFY_WRITE_OFF_ALLOCATION")
        if known == 0 and basis != 0:
            raise RuntimeError("I05_VERIFY_WRITE_OFF_BASIS")
    if execute("SELECT COUNT(*) FROM order_payments WHERE amount_vnd IS NULL OR amount_vnd <= 0 OR amount_vnd > 9000000000000000").fetchone()[0]:
        raise RuntimeError("I05_VERIFY_ORDER_PAYMENT_AMOUNT")
    if execute("SELECT COUNT(*) FROM cash_movements WHERE amount_vnd IS NULL OR amount_vnd <= 0 OR amount_vnd > 9000000000000000").fetchone()[0]:
        raise RuntimeError("I05_VERIFY_CASH_MOVEMENT_AMOUNT")


def downgrade():
    raise RuntimeError("F-Selling I05 migrations are forward-only")
