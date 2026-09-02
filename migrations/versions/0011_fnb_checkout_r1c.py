"""F&B R1C checks, checkout and immutable order provenance."""

from alembic import op


revision = "0011_fnb_checkout_r1c"
down_revision = "0010_fnb_kitchen_stock_r1b"
branch_labels = None
depends_on = None

DDL = (
    """CREATE TABLE fnb_service_checks (
        id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        label VARCHAR(100) NOT NULL,
        is_primary BOOLEAN NOT NULL DEFAULT 0,
        status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
        revision INTEGER NOT NULL DEFAULT 0,
        order_id INTEGER,
        discount_kind VARCHAR(16) NOT NULL DEFAULT 'NONE',
        discount_value INTEGER NOT NULL DEFAULT 0,
        service_charge_kind VARCHAR(16) NOT NULL DEFAULT 'NONE',
        service_charge_value INTEGER NOT NULL DEFAULT 0,
        subtotal_vnd INTEGER NOT NULL DEFAULT 0,
        discount_vnd INTEGER NOT NULL DEFAULT 0,
        service_charge_vnd INTEGER NOT NULL DEFAULT 0,
        total_vnd INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        settled_at DATETIME,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_checks_status CHECK (
            status IN ('OPEN','PAYING','PAYMENT_PENDING','PAID','DEBT','CANCELLED')
        ),
        CONSTRAINT ck_fnb_checks_adjustment_kinds CHECK (
            discount_kind IN ('NONE','FLAT','PERCENT') AND
            service_charge_kind IN ('NONE','FLAT','PERCENT')
        ),
        CONSTRAINT ck_fnb_checks_values CHECK (
            revision >= 0 AND discount_value >= 0 AND service_charge_value >= 0
            AND subtotal_vnd >= 0 AND discount_vnd >= 0
            AND service_charge_vnd >= 0 AND total_vnd >= 0
        ),
        FOREIGN KEY(session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(order_id) REFERENCES orders (id)
    )""",
    "CREATE INDEX ix_fnb_checks_session_status ON fnb_service_checks (session_id, status, id)",
    "CREATE UNIQUE INDEX ux_fnb_checks_order_id ON fnb_service_checks (order_id)",
    "CREATE UNIQUE INDEX ux_fnb_checks_primary_session ON fnb_service_checks (session_id) WHERE is_primary = 1",
    """CREATE TABLE fnb_check_lines (
        id INTEGER NOT NULL,
        check_id INTEGER NOT NULL,
        session_line_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_check_lines_quantity CHECK (quantity > 0),
        FOREIGN KEY(check_id) REFERENCES fnb_service_checks (id),
        FOREIGN KEY(session_line_id) REFERENCES fnb_session_lines (id)
    )""",
    "CREATE UNIQUE INDEX ux_fnb_check_line ON fnb_check_lines (check_id, session_line_id)",
    "CREATE INDEX ix_fnb_check_lines_session_line ON fnb_check_lines (session_line_id, check_id)",
    """CREATE TABLE fnb_allocation_transfers (
        id INTEGER NOT NULL,
        allocation_id INTEGER NOT NULL,
        check_id INTEGER NOT NULL,
        order_item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        cost_known_qty INTEGER NOT NULL DEFAULT 0,
        cost_unknown_qty INTEGER NOT NULL DEFAULT 0,
        cost_basis_vnd INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_transfer_quantity CHECK (quantity > 0),
        CONSTRAINT ck_fnb_transfer_cost CHECK (
            cost_known_qty >= 0 AND cost_unknown_qty >= 0
            AND cost_known_qty + cost_unknown_qty = quantity
            AND cost_basis_vnd >= 0
        ),
        FOREIGN KEY(allocation_id) REFERENCES fnb_stock_allocations (id),
        FOREIGN KEY(check_id) REFERENCES fnb_service_checks (id),
        FOREIGN KEY(order_item_id) REFERENCES order_items (id)
    )""",
    "CREATE UNIQUE INDEX ux_fnb_transfer_allocation_order_item ON fnb_allocation_transfers (allocation_id, order_item_id)",
    "CREATE INDEX ix_fnb_transfers_check ON fnb_allocation_transfers (check_id, id)",
    "CREATE INDEX ix_fnb_transfers_order_item ON fnb_allocation_transfers (order_item_id, id)",
    """INSERT INTO fnb_service_checks
        (session_id, label, is_primary, status, revision)
        SELECT id, 'Bill chính', 1,
               CASE WHEN status='CANCELLED' THEN 'CANCELLED' ELSE 'OPEN' END, 0
        FROM fnb_service_sessions""",
    """INSERT INTO fnb_check_lines (check_id, session_line_id, quantity)
        SELECT c.id, l.id, l.sent_quantity-l.sent_cancelled_quantity
        FROM fnb_session_lines l
        JOIN fnb_service_checks c ON c.session_id=l.session_id AND c.is_primary=1
        WHERE l.sent_quantity-l.sent_cancelled_quantity > 0""",
)

REQUIRED_COLUMNS = {
    "fnb_service_checks": {
        "id", "session_id", "label", "is_primary", "status", "revision",
        "order_id", "discount_kind", "discount_value", "service_charge_kind",
        "service_charge_value", "subtotal_vnd", "discount_vnd",
        "service_charge_vnd", "total_vnd", "created_at", "settled_at",
    },
    "fnb_check_lines": {"id", "check_id", "session_line_id", "quantity"},
    "fnb_allocation_transfers": {
        "id", "allocation_id", "check_id", "order_item_id", "quantity",
        "cost_known_qty", "cost_unknown_qty", "cost_basis_vnd", "created_at",
    },
}

REQUIRED_INDEXES = {
    "ix_fnb_checks_session_status", "ux_fnb_checks_order_id",
    "ux_fnb_checks_primary_session", "ux_fnb_check_line",
    "ix_fnb_check_lines_session_line", "ux_fnb_transfer_allocation_order_item",
    "ix_fnb_transfers_check", "ix_fnb_transfers_order_item",
}


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def upgrade():
    for statement in DDL:
        _execute(statement)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    objects = {
        (row[0], row[1])
        for row in execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table','index')"
        ).fetchall()
    }
    required = {
        *(("table", name) for name in REQUIRED_COLUMNS),
        *(("index", name) for name in REQUIRED_INDEXES),
    }
    if not required <= objects:
        raise RuntimeError("FNB_R1C_VERIFY_SCHEMA_OBJECTS")
    for table, columns in REQUIRED_COLUMNS.items():
        actual = {row[1] for row in execute(f"PRAGMA table_info({table})").fetchall()}
        if not columns <= actual:
            raise RuntimeError(f"FNB_R1C_VERIFY_COLUMNS:{table}")
    invalid_checks = execute(
        """SELECT COUNT(*) FROM fnb_service_checks c
           LEFT JOIN fnb_service_sessions s ON s.id=c.session_id
           LEFT JOIN orders o ON o.id=c.order_id
           WHERE s.id IS NULL
              OR c.status NOT IN ('OPEN','PAYING','PAYMENT_PENDING','PAID','DEBT','CANCELLED')
              OR c.discount_kind NOT IN ('NONE','FLAT','PERCENT')
              OR c.service_charge_kind NOT IN ('NONE','FLAT','PERCENT')
              OR c.revision<0 OR c.discount_value<0 OR c.service_charge_value<0
              OR c.subtotal_vnd<0 OR c.discount_vnd<0
              OR c.service_charge_vnd<0 OR c.total_vnd<0
              OR (c.order_id IS NOT NULL AND (o.id IS NULL OR o.shop_id<>s.shop_id))"""
    ).fetchone()[0]
    if invalid_checks:
        raise RuntimeError("FNB_R1C_VERIFY_CHECK_SCOPE")
    invalid_lines = execute(
        """SELECT COUNT(*) FROM fnb_check_lines cl
           LEFT JOIN fnb_service_checks c ON c.id=cl.check_id
           LEFT JOIN fnb_session_lines l ON l.id=cl.session_line_id
           WHERE c.id IS NULL OR l.id IS NULL OR c.session_id<>l.session_id
              OR cl.quantity<=0"""
    ).fetchone()[0]
    if invalid_lines:
        raise RuntimeError("FNB_R1C_VERIFY_CHECK_LINE_SCOPE")
    over_lines = execute(
        """SELECT COUNT(*) FROM (
             SELECT l.id
             FROM fnb_session_lines l
             JOIN fnb_check_lines cl ON cl.session_line_id=l.id
             GROUP BY l.id, l.sent_quantity, l.sent_cancelled_quantity
             HAVING SUM(cl.quantity) > l.sent_quantity-l.sent_cancelled_quantity
           )"""
    ).fetchone()[0]
    if over_lines:
        raise RuntimeError("FNB_R1C_VERIFY_CHECK_LINE_QUANTITY")
    invalid_transfers = execute(
        """SELECT COUNT(*) FROM fnb_allocation_transfers t
           LEFT JOIN fnb_stock_allocations a ON a.id=t.allocation_id
           LEFT JOIN fnb_service_checks c ON c.id=t.check_id
           LEFT JOIN order_items oi ON oi.id=t.order_item_id
           LEFT JOIN orders o ON o.id=oi.order_id
           LEFT JOIN fnb_service_sessions s ON s.id=c.session_id
           WHERE a.id IS NULL OR c.id IS NULL OR oi.id IS NULL OR o.id IS NULL
              OR s.id IS NULL OR a.session_id<>c.session_id OR o.shop_id<>s.shop_id
              OR t.quantity<=0 OR t.cost_known_qty<0 OR t.cost_unknown_qty<0
              OR t.cost_known_qty+t.cost_unknown_qty<>t.quantity
              OR t.cost_basis_vnd<0"""
    ).fetchone()[0]
    if invalid_transfers:
        raise RuntimeError("FNB_R1C_VERIFY_TRANSFER_SCOPE")
    over_transfers = execute(
        """SELECT COUNT(*) FROM (
             SELECT a.id
             FROM fnb_stock_allocations a
             JOIN fnb_allocation_transfers t ON t.allocation_id=a.id
             GROUP BY a.id, a.quantity
             HAVING SUM(t.quantity)>a.quantity
           )"""
    ).fetchone()[0]
    if over_transfers:
        raise RuntimeError("FNB_R1C_VERIFY_TRANSFER_QUANTITY")


def downgrade():
    raise RuntimeError("FORWARD_ONLY_MIGRATION")
