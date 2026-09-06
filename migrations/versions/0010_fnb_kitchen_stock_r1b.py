"""F&B R1B Kitchen/Bar, stock provenance and manager approvals."""

from alembic import op


revision = "0010_fnb_kitchen_stock_r1b"
down_revision = "0009_fnb_table_service_r1a"
branch_labels = None
depends_on = None

DDL = (
    "ALTER TABLE products ADD COLUMN fnb_station VARCHAR(16) NOT NULL "
    "DEFAULT 'DIRECT' CHECK (fnb_station IN ('KITCHEN','BAR','DIRECT'))",
    "ALTER TABLE fnb_session_lines ADD COLUMN station VARCHAR(16) NOT NULL "
    "DEFAULT 'DIRECT' CHECK (station IN ('KITCHEN','BAR','DIRECT'))",
    "ALTER TABLE fnb_session_lines ADD COLUMN sent_quantity INTEGER NOT NULL "
    "DEFAULT 0 CHECK (sent_quantity >= 0 AND sent_quantity <= quantity)",
    "ALTER TABLE fnb_session_lines ADD COLUMN sent_cancelled_quantity INTEGER "
    "NOT NULL DEFAULT 0 CHECK (sent_cancelled_quantity >= 0 AND "
    "sent_cancelled_quantity <= sent_quantity AND "
    "sent_cancelled_quantity <= cancelled_quantity)",
    "ALTER TABLE users ADD COLUMN fnb_manager_pin_hash VARCHAR(128)",
    """CREATE TABLE fnb_kitchen_tickets (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        station VARCHAR(16) NOT NULL,
        sequence INTEGER NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'NEW',
        operation_id VARCHAR(128) NOT NULL,
        created_by_user_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        started_by_user_id INTEGER,
        started_at DATETIME,
        done_by_user_id INTEGER,
        done_at DATETIME,
        out_of_stock_reason VARCHAR(500),
        state_version INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_ticket_station CHECK (station IN ('KITCHEN','BAR')),
        CONSTRAINT ck_fnb_ticket_status CHECK (
            status IN ('NEW','IN_PROGRESS','DONE','CANCELLED')
        ),
        CONSTRAINT ck_fnb_ticket_sequence CHECK (sequence > 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(started_by_user_id) REFERENCES users (id),
        FOREIGN KEY(done_by_user_id) REFERENCES users (id)
    )""",
    "CREATE INDEX ix_fnb_tickets_shop_station_status ON "
    "fnb_kitchen_tickets (shop_id, station, status, sequence)",
    "CREATE INDEX ix_fnb_tickets_session_id ON fnb_kitchen_tickets (session_id)",
    "CREATE UNIQUE INDEX ux_fnb_ticket_sequence ON "
    "fnb_kitchen_tickets (shop_id, station, sequence)",
    "CREATE UNIQUE INDEX ux_fnb_ticket_operation_station ON "
    "fnb_kitchen_tickets (shop_id, operation_id, station)",
    """CREATE TABLE fnb_kitchen_ticket_items (
        id INTEGER NOT NULL,
        ticket_id INTEGER NOT NULL,
        session_line_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        cancelled_quantity INTEGER NOT NULL DEFAULT 0,
        product_name VARCHAR(300) NOT NULL,
        note VARCHAR(500),
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_ticket_item_quantity CHECK (quantity > 0),
        CONSTRAINT ck_fnb_ticket_item_cancelled CHECK (
            cancelled_quantity >= 0 AND cancelled_quantity <= quantity
        ),
        FOREIGN KEY(ticket_id) REFERENCES fnb_kitchen_tickets (id),
        FOREIGN KEY(session_line_id) REFERENCES fnb_session_lines (id)
    )""",
    "CREATE INDEX ix_fnb_ticket_items_ticket_id ON fnb_kitchen_ticket_items (ticket_id)",
    "CREATE INDEX ix_fnb_ticket_items_line_id ON fnb_kitchen_ticket_items (session_line_id)",
    """CREATE TABLE fnb_stock_allocations (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        session_line_id INTEGER NOT NULL,
        ticket_item_id INTEGER,
        product_id INTEGER NOT NULL,
        batch_id INTEGER,
        quantity INTEGER NOT NULL,
        cost_known_qty INTEGER NOT NULL DEFAULT 0,
        cost_unknown_qty INTEGER NOT NULL DEFAULT 0,
        cost_basis_vnd INTEGER NOT NULL DEFAULT 0,
        state VARCHAR(32) NOT NULL DEFAULT 'CONSUMED',
        operation_id VARCHAR(128) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resolved_at DATETIME,
        resolution_reason VARCHAR(500),
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_allocation_quantity CHECK (quantity > 0),
        CONSTRAINT ck_fnb_allocation_cost CHECK (
            cost_known_qty >= 0 AND cost_unknown_qty >= 0
            AND cost_known_qty + cost_unknown_qty = quantity
            AND cost_basis_vnd >= 0
        ),
        CONSTRAINT ck_fnb_allocation_state CHECK (
            state IN ('CONSUMED','RESTOCKED','TRANSFERRED_TO_ORDER','WASTE')
        ),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(session_line_id) REFERENCES fnb_session_lines (id),
        FOREIGN KEY(ticket_item_id) REFERENCES fnb_kitchen_ticket_items (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(batch_id) REFERENCES product_batches (id)
    )""",
    "CREATE INDEX ix_fnb_allocations_line_state ON "
    "fnb_stock_allocations (session_line_id, state, id)",
    "CREATE INDEX ix_fnb_allocations_ticket_item ON "
    "fnb_stock_allocations (ticket_item_id)",
    "CREATE INDEX ix_fnb_allocations_product ON "
    "fnb_stock_allocations (product_id, state)",
    """CREATE TABLE fnb_manager_approvals (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        approver_user_id INTEGER NOT NULL,
        actor_user_id INTEGER NOT NULL,
        action VARCHAR(64) NOT NULL,
        entity_type VARCHAR(32) NOT NULL,
        entity_id INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        expires_at DATETIME NOT NULL,
        used_at DATETIME,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_approval_revision CHECK (revision >= 0),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(approver_user_id) REFERENCES users (id),
        FOREIGN KEY(actor_user_id) REFERENCES users (id)
    )""",
    "CREATE UNIQUE INDEX ux_fnb_approval_token_hash ON fnb_manager_approvals (token_hash)",
    "CREATE INDEX ix_fnb_approval_scope ON "
    "fnb_manager_approvals (shop_id, actor_user_id, action, entity_id, used_at)",
)

REQUIRED_COLUMNS = {
    "fnb_kitchen_tickets": {
        "id", "shop_id", "session_id", "station", "sequence", "status",
        "operation_id", "created_by_user_id", "created_at",
        "started_by_user_id", "started_at", "done_by_user_id", "done_at",
        "out_of_stock_reason", "state_version",
    },
    "fnb_kitchen_ticket_items": {
        "id", "ticket_id", "session_line_id", "quantity", "cancelled_quantity",
        "product_name", "note",
    },
    "fnb_stock_allocations": {
        "id", "shop_id", "session_id", "session_line_id", "ticket_item_id",
        "product_id", "batch_id", "quantity", "cost_known_qty",
        "cost_unknown_qty", "cost_basis_vnd", "state", "operation_id",
        "created_at", "resolved_at", "resolution_reason",
    },
    "fnb_manager_approvals": {
        "id", "shop_id", "approver_user_id", "actor_user_id", "action",
        "entity_type", "entity_id", "revision", "token_hash", "expires_at",
        "used_at", "created_at",
    },
}

REQUIRED_INDEXES = {
    "ix_fnb_tickets_shop_station_status",
    "ix_fnb_tickets_session_id",
    "ux_fnb_ticket_sequence",
    "ux_fnb_ticket_operation_station",
    "ix_fnb_ticket_items_ticket_id",
    "ix_fnb_ticket_items_line_id",
    "ix_fnb_allocations_line_state",
    "ix_fnb_allocations_ticket_item",
    "ix_fnb_allocations_product",
    "ux_fnb_approval_token_hash",
    "ix_fnb_approval_scope",
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
        raise RuntimeError("FNB_R1B_VERIFY_SCHEMA_OBJECTS")
    for table, columns in REQUIRED_COLUMNS.items():
        actual = {row[1] for row in execute(f"PRAGMA table_info({table})").fetchall()}
        if not columns <= actual:
            raise RuntimeError(f"FNB_R1B_VERIFY_COLUMNS:{table}")
    product_columns = {row[1] for row in execute("PRAGMA table_info(products)").fetchall()}
    line_columns = {row[1] for row in execute("PRAGMA table_info(fnb_session_lines)").fetchall()}
    user_columns = {row[1] for row in execute("PRAGMA table_info(users)").fetchall()}
    if "fnb_station" not in product_columns or not {
        "station", "sent_quantity", "sent_cancelled_quantity"
    } <= line_columns or "fnb_manager_pin_hash" not in user_columns:
        raise RuntimeError("FNB_R1B_VERIFY_ADDED_COLUMNS")

    invalid_lines = execute(
        """SELECT COUNT(*) FROM fnb_session_lines
           WHERE station NOT IN ('KITCHEN','BAR','DIRECT')
              OR sent_quantity < 0 OR sent_quantity > quantity
              OR sent_cancelled_quantity < 0
              OR sent_cancelled_quantity > sent_quantity
              OR sent_cancelled_quantity > cancelled_quantity"""
    ).fetchone()[0]
    if invalid_lines:
        raise RuntimeError("FNB_R1B_VERIFY_LINE_STATE")
    invalid_tickets = execute(
        """SELECT COUNT(*) FROM fnb_kitchen_tickets t
           LEFT JOIN shops sh ON sh.id=t.shop_id
           LEFT JOIN fnb_service_sessions s ON s.id=t.session_id
           WHERE sh.id IS NULL OR s.id IS NULL OR s.shop_id<>t.shop_id
              OR t.station NOT IN ('KITCHEN','BAR')
              OR t.status NOT IN ('NEW','IN_PROGRESS','DONE','CANCELLED')"""
    ).fetchone()[0]
    if invalid_tickets:
        raise RuntimeError("FNB_R1B_VERIFY_TICKET_SCOPE")
    invalid_items = execute(
        """SELECT COUNT(*) FROM fnb_kitchen_ticket_items i
           LEFT JOIN fnb_kitchen_tickets t ON t.id=i.ticket_id
           LEFT JOIN fnb_session_lines l ON l.id=i.session_line_id
           WHERE t.id IS NULL OR l.id IS NULL OR t.session_id<>l.session_id
              OR i.quantity<=0 OR i.cancelled_quantity<0
              OR i.cancelled_quantity>i.quantity"""
    ).fetchone()[0]
    if invalid_items:
        raise RuntimeError("FNB_R1B_VERIFY_TICKET_ITEM_SCOPE")
    invalid_allocations = execute(
        """SELECT COUNT(*) FROM fnb_stock_allocations a
           LEFT JOIN fnb_service_sessions s ON s.id=a.session_id
           LEFT JOIN fnb_session_lines l ON l.id=a.session_line_id
           LEFT JOIN products p ON p.id=a.product_id
           LEFT JOIN product_batches b ON b.id=a.batch_id
           LEFT JOIN fnb_kitchen_ticket_items i ON i.id=a.ticket_item_id
           WHERE s.id IS NULL OR l.id IS NULL OR p.id IS NULL
              OR s.shop_id<>a.shop_id OR l.session_id<>a.session_id
              OR p.shop_id<>a.shop_id
              OR (a.batch_id IS NOT NULL AND (b.id IS NULL OR b.product_id<>a.product_id))
              OR (a.ticket_item_id IS NOT NULL AND i.id IS NULL)
              OR a.quantity<=0 OR a.cost_known_qty<0 OR a.cost_unknown_qty<0
              OR a.cost_known_qty+a.cost_unknown_qty<>a.quantity
              OR a.cost_basis_vnd<0
              OR a.state NOT IN ('CONSUMED','RESTOCKED','TRANSFERRED_TO_ORDER','WASTE')"""
    ).fetchone()[0]
    if invalid_allocations:
        raise RuntimeError("FNB_R1B_VERIFY_ALLOCATION_SCOPE")


def downgrade():
    raise RuntimeError("FORWARD_ONLY_MIGRATION")
