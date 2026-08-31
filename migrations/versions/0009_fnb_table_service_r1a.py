"""F&B table-service R1A domain schema."""

from alembic import op


revision = "0009_fnb_table_service_r1a"
down_revision = "0008_purchase_orders"
branch_labels = None
depends_on = None

DDL = (
    "ALTER TABLE shops ADD COLUMN fnb_enabled BOOLEAN NOT NULL DEFAULT 0",
    "ALTER TABLE shops ADD COLUMN fnb_revision INTEGER NOT NULL DEFAULT 0",
    """CREATE TABLE fnb_areas (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        name VARCHAR(100) NOT NULL,
        name_key VARCHAR(100) NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active BOOLEAN NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id)
    )""",
    "CREATE INDEX ix_fnb_areas_shop_id ON fnb_areas (shop_id)",
    "CREATE UNIQUE INDEX ux_fnb_areas_shop_name_key ON fnb_areas (shop_id, name_key)",
    """CREATE TABLE fnb_tables (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        area_id INTEGER NOT NULL,
        name VARCHAR(100) NOT NULL,
        name_key VARCHAR(100) NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active BOOLEAN NOT NULL DEFAULT 1,
        state_version INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(area_id) REFERENCES fnb_areas (id)
    )""",
    "CREATE INDEX ix_fnb_tables_shop_id ON fnb_tables (shop_id)",
    "CREATE INDEX ix_fnb_tables_area_id ON fnb_tables (area_id)",
    "CREATE UNIQUE INDEX ux_fnb_tables_area_name_key ON fnb_tables (area_id, name_key)",
    "CREATE INDEX ix_fnb_floor_area ON fnb_tables (shop_id, area_id, active, sort_order)",
    """CREATE TABLE fnb_service_sessions (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
        revision INTEGER NOT NULL DEFAULT 0,
        merged_into_session_id INTEGER,
        opened_by_user_id INTEGER NOT NULL,
        opened_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_by_user_id INTEGER,
        closed_at DATETIME,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_sessions_status CHECK (
            status IN ('OPEN','PARTIALLY_SETTLED','PAYMENT_PENDING','CLOSED','CANCELLED')
        ),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(merged_into_session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(opened_by_user_id) REFERENCES users (id),
        FOREIGN KEY(closed_by_user_id) REFERENCES users (id)
    )""",
    "CREATE INDEX ix_fnb_service_sessions_shop_id ON fnb_service_sessions (shop_id)",
    "CREATE INDEX ix_fnb_service_sessions_status ON fnb_service_sessions (status)",
    "CREATE INDEX ix_fnb_sessions_shop_status ON fnb_service_sessions (shop_id, status)",
    """CREATE TABLE fnb_session_tables (
        id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        table_id INTEGER NOT NULL,
        added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        released_at DATETIME,
        PRIMARY KEY (id),
        FOREIGN KEY(session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(table_id) REFERENCES fnb_tables (id)
    )""",
    "CREATE INDEX ix_fnb_session_tables_session_id ON fnb_session_tables (session_id)",
    "CREATE INDEX ix_fnb_session_tables_table_id ON fnb_session_tables (table_id)",
    """CREATE UNIQUE INDEX ux_fnb_active_session_table
       ON fnb_session_tables (table_id) WHERE released_at IS NULL""",
    """CREATE TABLE fnb_session_lines (
        id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name VARCHAR(300) NOT NULL,
        unit_price_vnd INTEGER NOT NULL,
        note VARCHAR(500),
        quantity INTEGER NOT NULL,
        cancelled_quantity INTEGER NOT NULL DEFAULT 0,
        created_by_user_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        state_version INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id),
        CONSTRAINT ck_fnb_session_lines_quantity CHECK (quantity > 0),
        CONSTRAINT ck_fnb_session_lines_cancelled CHECK (
            cancelled_quantity >= 0 AND cancelled_quantity <= quantity
        ),
        FOREIGN KEY(session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )""",
    "CREATE INDEX ix_fnb_session_lines_session_id ON fnb_session_lines (session_id)",
    "CREATE INDEX ix_fnb_lines_session_created ON fnb_session_lines (session_id, created_at)",
    """CREATE TABLE fnb_action_logs (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        session_id INTEGER,
        actor_user_id INTEGER NOT NULL,
        action VARCHAR(64) NOT NULL,
        operation_id VARCHAR(128) NOT NULL,
        operation_fingerprint VARCHAR(64) NOT NULL,
        result_json TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        reason VARCHAR(500),
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(session_id) REFERENCES fnb_service_sessions (id),
        FOREIGN KEY(actor_user_id) REFERENCES users (id)
    )""",
    "CREATE INDEX ix_fnb_action_logs_shop_id ON fnb_action_logs (shop_id)",
    "CREATE INDEX ix_fnb_action_logs_session_id ON fnb_action_logs (session_id)",
    "CREATE UNIQUE INDEX ux_fnb_action_shop_operation ON fnb_action_logs (shop_id, operation_id)",
)

REQUIRED_COLUMNS = {
    "fnb_areas": {
        "id", "shop_id", "name", "name_key", "sort_order", "active",
        "created_at", "updated_at",
    },
    "fnb_tables": {
        "id", "shop_id", "area_id", "name", "name_key", "sort_order",
        "active", "state_version", "created_at", "updated_at",
    },
    "fnb_service_sessions": {
        "id", "shop_id", "status", "revision", "merged_into_session_id",
        "opened_by_user_id", "opened_at", "closed_by_user_id", "closed_at",
    },
    "fnb_session_tables": {
        "id", "session_id", "table_id", "added_at", "released_at",
    },
    "fnb_session_lines": {
        "id", "session_id", "product_id", "product_name", "unit_price_vnd",
        "note", "quantity", "cancelled_quantity", "created_by_user_id",
        "created_at", "state_version",
    },
    "fnb_action_logs": {
        "id", "shop_id", "session_id", "actor_user_id", "action",
        "operation_id", "operation_fingerprint", "result_json", "before_json",
        "after_json", "reason", "created_at",
    },
}

REQUIRED_INDEXES = {
    "ix_fnb_areas_shop_id",
    "ux_fnb_areas_shop_name_key",
    "ix_fnb_tables_shop_id",
    "ix_fnb_tables_area_id",
    "ux_fnb_tables_area_name_key",
    "ix_fnb_floor_area",
    "ix_fnb_service_sessions_shop_id",
    "ix_fnb_service_sessions_status",
    "ix_fnb_sessions_shop_status",
    "ix_fnb_session_tables_session_id",
    "ix_fnb_session_tables_table_id",
    "ux_fnb_active_session_table",
    "ix_fnb_session_lines_session_id",
    "ix_fnb_lines_session_created",
    "ix_fnb_action_logs_shop_id",
    "ix_fnb_action_logs_session_id",
    "ux_fnb_action_shop_operation",
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
            "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'index')"
        ).fetchall()
    }
    required_objects = {
        *(('table', table) for table in REQUIRED_COLUMNS),
        *(('index', index) for index in REQUIRED_INDEXES),
    }
    if not required_objects <= objects:
        raise RuntimeError("FNB_VERIFY_SCHEMA_OBJECTS")

    shop_columns = {
        row[1] for row in execute("PRAGMA table_info(shops)").fetchall()
    }
    if not {"fnb_enabled", "fnb_revision"} <= shop_columns:
        raise RuntimeError("FNB_VERIFY_SHOP_COLUMNS")
    for table, required in REQUIRED_COLUMNS.items():
        columns = {
            row[1] for row in execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not required <= columns:
            raise RuntimeError(f"FNB_VERIFY_COLUMNS:{table}")

    invalid_status = execute(
        "SELECT COUNT(*) FROM fnb_service_sessions "
        "WHERE status NOT IN "
        "('OPEN','PARTIALLY_SETTLED','PAYMENT_PENDING','CLOSED','CANCELLED')"
    ).fetchone()[0]
    if invalid_status:
        raise RuntimeError("FNB_VERIFY_SESSION_STATUS")

    invalid_area_or_table = execute(
        """SELECT COUNT(*) FROM fnb_tables t
           LEFT JOIN shops s ON s.id = t.shop_id
           LEFT JOIN fnb_areas a ON a.id = t.area_id
           WHERE s.id IS NULL OR a.id IS NULL OR a.shop_id <> t.shop_id"""
    ).fetchone()[0]
    invalid_area_or_table += execute(
        """SELECT COUNT(*) FROM fnb_areas a
           LEFT JOIN shops s ON s.id = a.shop_id WHERE s.id IS NULL"""
    ).fetchone()[0]
    if invalid_area_or_table:
        raise RuntimeError("FNB_VERIFY_TABLE_SCOPE")

    invalid_session = execute(
        """SELECT COUNT(*) FROM fnb_service_sessions s
           LEFT JOIN shops sh ON sh.id = s.shop_id
           LEFT JOIN fnb_service_sessions merged ON merged.id = s.merged_into_session_id
           WHERE sh.id IS NULL OR (s.merged_into_session_id IS NOT NULL
             AND (merged.id IS NULL OR merged.shop_id <> s.shop_id))"""
    ).fetchone()[0]
    if invalid_session:
        raise RuntimeError("FNB_VERIFY_SESSION_SCOPE")

    invalid_links = execute(
        """SELECT COUNT(*) FROM fnb_session_tables st
           LEFT JOIN fnb_service_sessions s ON s.id = st.session_id
           LEFT JOIN fnb_tables t ON t.id = st.table_id
           WHERE s.id IS NULL OR t.id IS NULL OR s.shop_id <> t.shop_id"""
    ).fetchone()[0]
    if invalid_links:
        raise RuntimeError("FNB_VERIFY_LINK_SCOPE")
    duplicate_active_links = execute(
        """SELECT COUNT(*) FROM (
             SELECT table_id FROM fnb_session_tables
             WHERE released_at IS NULL GROUP BY table_id HAVING COUNT(*) > 1
           )"""
    ).fetchone()[0]
    if duplicate_active_links:
        raise RuntimeError("FNB_VERIFY_ACTIVE_TABLE")
    terminal_active_links = execute(
        """SELECT COUNT(*) FROM fnb_session_tables st
           JOIN fnb_service_sessions s ON s.id = st.session_id
           WHERE st.released_at IS NULL AND s.status IN ('CLOSED','CANCELLED')"""
    ).fetchone()[0]
    if terminal_active_links:
        raise RuntimeError("FNB_VERIFY_LINK_STATE")

    invalid_lines = execute(
        """SELECT COUNT(*) FROM fnb_session_lines l
           LEFT JOIN fnb_service_sessions s ON s.id = l.session_id
           LEFT JOIN products p ON p.id = l.product_id
           WHERE s.id IS NULL OR p.id IS NULL OR p.shop_id IS NULL
              OR p.shop_id <> s.shop_id
              OR typeof(l.quantity) <> 'integer' OR l.quantity <= 0
              OR typeof(l.cancelled_quantity) <> 'integer'
              OR l.cancelled_quantity < 0 OR l.cancelled_quantity > l.quantity"""
    ).fetchone()[0]
    if invalid_lines:
        raise RuntimeError("FNB_VERIFY_LINE_SCOPE")

    invalid_logs = execute(
        """SELECT COUNT(*) FROM fnb_action_logs l
           LEFT JOIN shops sh ON sh.id = l.shop_id
           LEFT JOIN users u ON u.id = l.actor_user_id
           LEFT JOIN fnb_service_sessions s ON s.id = l.session_id
           WHERE sh.id IS NULL OR u.id IS NULL OR (l.session_id IS NOT NULL
             AND (s.id IS NULL OR s.shop_id <> l.shop_id))"""
    ).fetchone()[0]
    if invalid_logs:
        raise RuntimeError("FNB_VERIFY_ACTION_SCOPE")


def downgrade():
    raise RuntimeError("FORWARD_ONLY_MIGRATION")
