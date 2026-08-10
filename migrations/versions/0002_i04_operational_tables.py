"""I04 operational tables after the 9cf7106 baseline."""

from alembic import op

revision = "0002_i04_operational_tables"
down_revision = "0001_legacy_9cf7106_baseline"
branch_labels = None
depends_on = None

DDL = (
    """CREATE TABLE fs_migration_worksets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_key TEXT NOT NULL,
        workset_key TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('OPEN', 'SEALED', 'COMPLETE', 'BLOCKED')),
        source_fingerprint TEXT NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (campaign_key, workset_key)
    )""",
    """CREATE TABLE fs_migration_work_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workset_id INTEGER NOT NULL,
        item_key TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('PENDING', 'RUNNING', 'DONE', 'QUARANTINED')),
        payload_json TEXT,
        lease_owner TEXT,
        lease_expires_at TEXT,
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        updated_at TEXT NOT NULL,
        UNIQUE (workset_id, item_key)
    )""",
    """CREATE INDEX ix_fs_migration_work_items_state
        ON fs_migration_work_items (workset_id, state, id)""",
    """CREATE TABLE fs_migration_checkpoints (
        workset_id INTEGER NOT NULL,
        checkpoint_key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (workset_id, checkpoint_key)
    )""",
    """CREATE TABLE fs_migration_manifests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_key TEXT NOT NULL,
        manifest_key TEXT NOT NULL,
        checksum TEXT NOT NULL CHECK (length(checksum) = 64),
        item_count INTEGER NOT NULL CHECK (item_count >= 0),
        payload_json TEXT,
        verified_at TEXT NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        UNIQUE (campaign_key, manifest_key)
    )""",
    """CREATE TABLE fs_migration_quarantine (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_key TEXT NOT NULL,
        work_item_id INTEGER,
        reason_code TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        resolution_note TEXT
    )""",
    """CREATE INDEX ix_fs_migration_quarantine_open
        ON fs_migration_quarantine (campaign_key, resolved_at, id)""",
    """CREATE TABLE fs_migration_reconciliation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_key TEXT NOT NULL,
        metric_key TEXT NOT NULL,
        expected_value TEXT NOT NULL,
        actual_value TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('MATCHED', 'MISMATCH', 'WAIVED')),
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        checked_at TEXT NOT NULL,
        UNIQUE (campaign_key, metric_key)
    )""",
    """CREATE TABLE fs_migration_feature_flags (
        flag_key TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        phase_version INTEGER NOT NULL CHECK (phase_version >= 0),
        payload_json TEXT,
        updated_by_attempt_id INTEGER NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        updated_at TEXT NOT NULL
    )""",
)

# Deterministic production repairs that existed in the 9cf7106 bootstrap.
# Ambiguous paid entitlement remains a hard verifier failure below.
DATA_REPAIRS = (
    """UPDATE users SET staff_role = 'MANAGER'
       WHERE role = 'STAFF' AND staff_role IS NULL""",
    """UPDATE orders SET reconciliation_reason = 'LEGACY_REVIEW'
       WHERE status = 'UNRECONCILED' AND reconciliation_reason IS NULL""",
    """UPDATE orders SET reconciliation_reason = 'LATE_PAYMENT',
              refund_due_amount = MAX(
                  COALESCE(paid_amount, 0) + COALESCE(cash_paid_amount, 0)
                  - COALESCE(refunded_amount, 0), 0
              )
       WHERE status = 'UNRECONCILED'
         AND reconciliation_reason = 'LEGACY_REVIEW'
         AND EXISTS (
             SELECT 1 FROM system_logs l
             WHERE l.action = 'WEBHOOK_UNRECONCILED'
               AND l.details LIKE 'Order ' || orders.id || ':%'
         )""",
    """UPDATE orders SET reconciliation_reason = 'UNDERPAID', refund_due_amount = 0
       WHERE status = 'UNRECONCILED'
         AND reconciliation_reason = 'LEGACY_REVIEW'
         AND EXISTS (
             SELECT 1 FROM system_logs l
             WHERE l.action = 'WEBHOOK_THIEU_TIEN'
               AND l.details LIKE 'Order ' || orders.id || ':%'
         )""",
    """UPDATE orders SET cash_paid_amount = total_amount
       WHERE status = 'PAID' AND payment_method = 'cash'
         AND COALESCE(cash_paid_amount, 0) = 0 AND paid_amount IS NULL""",
    """UPDATE orders SET reconciliation_reason = 'OVERPAID',
              refund_due_amount = paid_amount - total_amount
       WHERE status = 'PAID' AND paid_amount > total_amount
         AND COALESCE(refunded_amount, 0) = 0
         AND COALESCE(refund_due_amount, 0) = 0""",
    """UPDATE subscription_checkouts SET status = 'EXPIRED'
       WHERE status IN ('PENDING', 'UNDERPAID')
         AND activated_at IS NULL AND expires_at <= CURRENT_TIMESTAMP""",
    """UPDATE products SET code = 'SP-' || id
       WHERE code IS NULL OR TRIM(code) = ''""",
    """UPDATE products SET code = 'SP-' || id
       WHERE EXISTS (
           SELECT 1 FROM products older
           WHERE older.shop_id = products.shop_id
             AND older.code = products.code AND older.id < products.id
       )""",
    """UPDATE order_items
       SET product_id = (
           SELECT p.id FROM products p JOIN orders o ON o.id = order_items.order_id
           WHERE p.shop_id = o.shop_id AND p.name = order_items.product_name
       ) WHERE product_id IS NULL""",
    """INSERT INTO shop_subscriptions (
           shop_id, trial_started_at, trial_ends_at, paid_until, updated_at
       )
       SELECT s.id, CURRENT_TIMESTAMP, datetime(CURRENT_TIMESTAMP, '+30 days'),
              NULL, CURRENT_TIMESTAMP
       FROM shops s
       WHERE NOT EXISTS (
           SELECT 1 FROM shop_subscriptions ss WHERE ss.shop_id = s.id
       )""",
    """UPDATE subscription_checkouts
       SET entitlement_ends_at = COALESCE(
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
         AND (entitlement_starts_at IS NULL OR entitlement_ends_at IS NULL)""",
    """UPDATE shop_subscriptions
       SET paid_until = (
               SELECT MAX(sc.entitlement_ends_at)
               FROM subscription_checkouts sc
               WHERE sc.shop_id = shop_subscriptions.shop_id
                 AND sc.activated_at IS NOT NULL
                 AND sc.entitlement_ends_at IS NOT NULL
           ), updated_at = CURRENT_TIMESTAMP
       WHERE EXISTS (
           SELECT 1 FROM subscription_checkouts sc
           WHERE sc.shop_id = shop_subscriptions.shop_id
             AND sc.activated_at IS NOT NULL
             AND sc.entitlement_ends_at IS NOT NULL
       )""",
    """INSERT INTO order_payments (
           order_id, entry_type, amount, idempotency_key, provider,
           bank_txn_id, account_no, note, created_at
       )
       SELECT o.id, 'BANK_IN', o.paid_amount, 'legacy-order:' || o.id, 'legacy',
              o.bank_txn_id, s.bank_account_no,
              'Dữ liệu ngân hàng trước khi có sổ giao dịch',
              COALESCE(o.created_at, CURRENT_TIMESTAMP)
       FROM orders o LEFT JOIN shops s ON s.id = o.shop_id
       WHERE o.paid_amount > 0 AND o.bank_txn_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM order_payments p
             WHERE p.order_id = o.id AND p.entry_type = 'BANK_IN'
               AND p.bank_txn_id = o.bank_txn_id
         )""",
)

EXPECTED_TABLES = {
    "fs_migration_worksets",
    "fs_migration_work_items",
    "fs_migration_checkpoints",
    "fs_migration_manifests",
    "fs_migration_quarantine",
    "fs_migration_reconciliation",
    "fs_migration_feature_flags",
}
EXPECTED_INDEXES = {
    "ix_fs_migration_work_items_state",
    "ix_fs_migration_quarantine_open",
}


def verify_legacy_preconditions(connection):
    """Fail before adoption when an entitlement cannot be reconstructed exactly."""
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    ambiguous = execute(
        """SELECT COUNT(*) FROM subscription_checkouts
           WHERE activated_at IS NOT NULL
             AND (entitlement_starts_at IS NULL OR entitlement_ends_at IS NULL)
             AND (
                 duration_days IS NULL OR duration_days <= 0
                 OR COALESCE(
                     paid_until_after,
                     datetime(activated_at, printf('+%d days', duration_days))
                 ) IS NULL
             )"""
    ).fetchone()[0]
    if ambiguous:
        raise RuntimeError(
            "legacy entitlement cannot be reconstructed without guessing"
        )


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def upgrade():
    for statement in DATA_REPAIRS + DDL:
        _execute(statement)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    rows = execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = {name for kind, name in rows if kind == "table"}
    indexes = {name for kind, name in rows if kind == "index"}
    missing_tables = EXPECTED_TABLES - tables
    missing_indexes = EXPECTED_INDEXES - indexes
    if missing_tables or missing_indexes:
        raise RuntimeError(
            f"0002 verifier failed: tables={sorted(missing_tables)}, "
            f"indexes={sorted(missing_indexes)}"
        )
    missing_entitlements = execute(
        """SELECT COUNT(*) FROM subscription_checkouts
           WHERE activated_at IS NOT NULL AND (
               entitlement_starts_at IS NULL OR entitlement_ends_at IS NULL
               OR entitlement_ends_at <= entitlement_starts_at
           )"""
    ).fetchone()[0]
    if missing_entitlements:
        raise RuntimeError(
            "0002 verifier: activated subscription entitlement is incomplete"
        )
    duplicate_codes = execute(
        """SELECT COUNT(*) FROM products p WHERE EXISTS (
               SELECT 1 FROM products q
               WHERE q.shop_id = p.shop_id AND q.code = p.code AND q.id < p.id
           )"""
    ).fetchone()[0]
    empty_codes = execute(
        "SELECT COUNT(*) FROM products WHERE code IS NULL OR TRIM(code) = ''"
    ).fetchone()[0]
    if duplicate_codes or empty_codes:
        raise RuntimeError("0002 verifier: product code invariant is not satisfied")
    durable_historical_mismatch = execute(
        """SELECT
             (SELECT COUNT(*) FROM users
              WHERE role='STAFF' AND staff_role IS NULL)
           + (SELECT COUNT(*) FROM orders
              WHERE status='UNRECONCILED' AND reconciliation_reason IS NULL)"""
    ).fetchone()[0]
    # Open checkout expiry is a runtime state transition, not durable
    # corruption. DATA_REPAIRS handles rows already expired at upgrade time;
    # startup verification must remain stable as wall-clock time advances.
    if durable_historical_mismatch:
        raise RuntimeError("0002 verifier: historical baseline invariant is not satisfied")


def downgrade():
    raise RuntimeError("F-Selling I04 migrations are forward-only")
