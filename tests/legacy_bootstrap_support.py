"""Test-only compatibility for historical pre-I04 bootstrap unit tests.

Production must never import this module.  It preserves old data-backfill and
index-corruption assertions while schema ownership stays exclusively in the
I04 operator coordinator.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from fselling import models
from fselling.core.database import engine
from fselling.migration.coordinator import MigrationCoordinator
from fselling.migration.topology import StaticInventory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ROOT = MigrationCoordinator(
    PROJECT_ROOT / "unused-test-only.db",
    project_root=PROJECT_ROOT,
    inventory_provider=StaticInventory(),
)._graph().root.module

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

_FINANCIAL_INDEXES = frozenset(
    {
        "ux_order_payments_idempotency_key",
        "ux_orders_operation_id",
        "ux_cash_shifts_shop_user_open",
        "ux_cash_movements_operation_id",
        "ux_order_returns_idempotency_key",
        "ux_orders_offline_uuid",
        "ux_loyalty_programs_shop_id",
        "ux_loyalty_point_entries_idempotency_key",
        "ux_suppliers_create_operation_id",
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
        "ux_operating_expenses_idempotency_key",
    }
)


def _expected_index_specs():
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        # Compatibility-only shape fixture. Production migrations are proved
        # in test_migration_i04 via Alembic and baseline Git archive, not here.
        for statement in _ROOT.TABLE_DDL + _ROOT.INDEX_DDL:
            connection.execute(statement)
        specs = {}
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            for row in connection.execute(f'PRAGMA index_list("{table}")'):
                name, unique, partial = row[1], bool(row[2]), bool(row[4])
                if name not in _REQUIRED_INDEXES:
                    continue
                columns = tuple(
                    item[2]
                    for item in connection.execute(f'PRAGMA index_info("{name}")')
                )
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                    (name,),
                ).fetchone()[0]
                predicate = None
                if sql and " WHERE " in sql.upper():
                    predicate = "".join(sql.upper().split(" WHERE ", 1)[1].split())
                specs[name] = (table, columns, unique, partial, predicate)
        return specs
    finally:
        connection.close()


_INDEX_SPECS = _expected_index_specs()


def verify_required_indexes(db):
    missing = []
    for name in _REQUIRED_INDEXES:
        expected = _INDEX_SPECS[name]
        table, columns, unique, partial, predicate = expected
        rows = db.execute(text(f'PRAGMA index_list("{table}")')).fetchall()
        row = next((item for item in rows if item[1] == name), None)
        if row is None:
            missing.append(name)
            continue
        actual_columns = tuple(
            item[2]
            for item in db.execute(text(f'PRAGMA index_info("{name}")')).fetchall()
        )
        sql = db.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": name},
        ).scalar()
        actual_predicate = None
        if sql and " WHERE " in sql.upper():
            actual_predicate = "".join(sql.upper().split(" WHERE ", 1)[1].split())
        if (
            bool(row[2]) != unique
            or bool(row[4]) != partial
            or actual_columns != columns
            or actual_predicate != predicate
        ):
            missing.append(name)
    return missing


def run_migrations(db):
    """Recreate baseline indexes for historical unit tests, without broad catch."""
    for statement in _ROOT.INDEX_DDL:
        if statement.startswith("CREATE UNIQUE INDEX "):
            statement = statement.replace(
                "CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1
            )
        else:
            statement = statement.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
        db.execute(text(statement))
    db.execute(
        text(
            "UPDATE users SET staff_role='MANAGER' "
            "WHERE role='STAFF' AND staff_role IS NULL"
        )
    )
    db.commit()


def initialize():
    """Old isolated fixture behavior; never used by application startup."""
    models.Base.metadata.create_all(bind=engine)
    from fselling.core.database import SessionLocal

    db = SessionLocal()
    try:
        run_migrations(db)
    finally:
        db.close()


_COUNT_DUPLICATE_CODES = """SELECT COUNT(*) FROM products p WHERE EXISTS (
    SELECT 1 FROM products q
    WHERE q.shop_id=p.shop_id AND q.code=p.code AND q.id<p.id)"""
_COUNT_EMPTY_CODES = "SELECT COUNT(*) FROM products WHERE code IS NULL OR TRIM(code)=''"


def dedupe_product_codes(db):
    duplicate = db.execute(text(_COUNT_DUPLICATE_CODES)).scalar() or 0
    empty = db.execute(text(_COUNT_EMPTY_CODES)).scalar() or 0
    if duplicate:
        db.execute(text("""UPDATE products SET code='SP-' || id WHERE EXISTS (
            SELECT 1 FROM products q WHERE q.shop_id=products.shop_id
            AND q.code=products.code AND q.id<products.id)"""))
    if empty:
        db.execute(text("UPDATE products SET code='SP-' || id WHERE code IS NULL OR TRIM(code)=''"))
    db.commit()
    return duplicate, empty


def backfill_order_item_product_id(db):
    before = db.execute(text("SELECT COUNT(*) FROM order_items WHERE product_id IS NULL")).scalar() or 0
    if not before:
        return 0, 0
    db.execute(text("""UPDATE order_items SET product_id=(
        SELECT p.id FROM products p JOIN orders o ON o.id=order_items.order_id
        WHERE p.shop_id=o.shop_id AND p.name=order_items.product_name)
        WHERE product_id IS NULL"""))
    db.commit()
    after = db.execute(text("SELECT COUNT(*) FROM order_items WHERE product_id IS NULL")).scalar() or 0
    return before - after, after


def backfill_legacy_order_payments(db):
    result = db.execute(text("""INSERT INTO order_payments (
        order_id, entry_type, amount, idempotency_key, provider,
        bank_txn_id, account_no, note, created_at)
        SELECT o.id, 'BANK_IN', o.paid_amount, 'legacy-order:' || o.id, 'legacy',
        o.bank_txn_id, s.bank_account_no, 'Dữ liệu ngân hàng trước khi có sổ giao dịch',
        COALESCE(o.created_at, CURRENT_TIMESTAMP)
        FROM orders o LEFT JOIN shops s ON s.id=o.shop_id
        WHERE o.paid_amount>0 AND o.bank_txn_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM order_payments p WHERE p.order_id=o.id
        AND p.entry_type='BANK_IN' AND p.bank_txn_id=o.bank_txn_id)"""))
    db.commit()
    return max(result.rowcount or 0, 0)


def backfill_shop_subscriptions(db):
    try:
        result = db.execute(text("""INSERT INTO shop_subscriptions (
            shop_id, trial_started_at, trial_ends_at, paid_until, updated_at)
            SELECT s.id, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+30 days'),
            NULL, CURRENT_TIMESTAMP FROM shops s WHERE NOT EXISTS (
            SELECT 1 FROM shop_subscriptions ss WHERE ss.shop_id=s.id)"""))
        db.commit()
        return max(result.rowcount or 0, 0)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("Không thể cấp trial cho shop cũ; dừng khởi động") from exc


def backfill_subscription_entitlements(db):
    try:
        result = db.execute(text("""UPDATE subscription_checkouts SET
            entitlement_ends_at=COALESCE(paid_until_after,
                datetime(activated_at, printf('+%d days', duration_days))),
            entitlement_starts_at=datetime(COALESCE(paid_until_after,
                datetime(activated_at, printf('+%d days', duration_days))),
                printf('-%d days', duration_days))
            WHERE activated_at IS NOT NULL AND
            (entitlement_starts_at IS NULL OR entitlement_ends_at IS NULL)"""))
        db.execute(text("""UPDATE shop_subscriptions SET paid_until=(
            SELECT MAX(sc.entitlement_ends_at) FROM subscription_checkouts sc
            WHERE sc.shop_id=shop_subscriptions.shop_id AND sc.activated_at IS NOT NULL
            AND sc.entitlement_ends_at IS NOT NULL), updated_at=CURRENT_TIMESTAMP
            WHERE EXISTS (SELECT 1 FROM subscription_checkouts sc
            WHERE sc.shop_id=shop_subscriptions.shop_id AND sc.activated_at IS NOT NULL
            AND sc.entitlement_ends_at IS NOT NULL)"""))
        missing = db.execute(text("""SELECT COUNT(*) FROM subscription_checkouts
            WHERE activated_at IS NOT NULL AND (entitlement_starts_at IS NULL
            OR entitlement_ends_at IS NULL OR entitlement_ends_at<=entitlement_starts_at)""" )).scalar() or 0
        if missing:
            db.rollback()
            raise RuntimeError("Không khôi phục được segment ngày Pro; dừng khởi động")
        db.commit()
        return max(result.rowcount or 0, 0)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("Không thể backfill segment ngày Pro; dừng khởi động") from exc
