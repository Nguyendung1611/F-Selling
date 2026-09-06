"""Purchase orders and the exact receipt link used to close them."""

from alembic import op

revision = "0008_purchase_orders"
down_revision = "0007_i10a_qr_payment_domain"
branch_labels = None
depends_on = None

DDL = (
    """CREATE TABLE purchase_orders (
        id INTEGER NOT NULL,
        shop_id INTEGER NOT NULL,
        supplier_id INTEGER NOT NULL,
        status VARCHAR(16) NOT NULL,
        expected_date VARCHAR(10),
        note VARCHAR(500),
        create_operation_id VARCHAR(128) NOT NULL,
        create_fingerprint VARCHAR(64) NOT NULL,
        place_operation_id VARCHAR(128),
        place_fingerprint VARCHAR(64),
        cancel_operation_id VARCHAR(128),
        created_by_user_id INTEGER,
        updated_by_user_id INTEGER,
        placed_by_user_id INTEGER,
        cancelled_by_user_id INTEGER,
        received_by_user_id INTEGER,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        placed_at DATETIME,
        cancelled_at DATETIME,
        received_at DATETIME,
        PRIMARY KEY (id),
        CONSTRAINT ck_purchase_orders_status CHECK (
            status IN ('DRAFT', 'ORDERED', 'RECEIVED', 'CANCELLED')
        ),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(supplier_id) REFERENCES suppliers (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(updated_by_user_id) REFERENCES users (id),
        FOREIGN KEY(placed_by_user_id) REFERENCES users (id),
        FOREIGN KEY(cancelled_by_user_id) REFERENCES users (id),
        FOREIGN KEY(received_by_user_id) REFERENCES users (id)
    )""",
    "CREATE INDEX ix_purchase_orders_shop_created ON purchase_orders (shop_id, created_at)",
    "CREATE INDEX ix_purchase_orders_supplier_created ON purchase_orders (supplier_id, created_at)",
    "CREATE INDEX ix_purchase_orders_shop_status ON purchase_orders (shop_id, status)",
    "CREATE UNIQUE INDEX ux_purchase_orders_create_operation_id ON purchase_orders (create_operation_id)",
    "CREATE UNIQUE INDEX ux_purchase_orders_place_operation_id ON purchase_orders (place_operation_id)",
    "CREATE UNIQUE INDEX ux_purchase_orders_cancel_operation_id ON purchase_orders (cancel_operation_id)",
    """CREATE TABLE purchase_order_items (
        id INTEGER NOT NULL,
        purchase_order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name VARCHAR(300) NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_purchase_order_items_quantity_positive CHECK (quantity > 0),
        FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders (id),
        FOREIGN KEY(product_id) REFERENCES products (id)
    )""",
    "CREATE INDEX ix_purchase_order_items_order_id ON purchase_order_items (purchase_order_id)",
    "CREATE INDEX ix_purchase_order_items_product_id ON purchase_order_items (product_id)",
    "CREATE UNIQUE INDEX ux_purchase_order_items_order_product ON purchase_order_items (purchase_order_id, product_id)",
    "ALTER TABLE purchase_receipts ADD COLUMN purchase_order_id INTEGER REFERENCES purchase_orders (id)",
    "CREATE UNIQUE INDEX ux_purchase_receipts_purchase_order_id ON purchase_receipts (purchase_order_id)",
)


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
            """SELECT type, name FROM sqlite_master
               WHERE name IN (
                 'purchase_orders', 'purchase_order_items',
                 'ix_purchase_orders_shop_created',
                 'ix_purchase_orders_supplier_created',
                 'ix_purchase_orders_shop_status',
                 'ux_purchase_orders_create_operation_id',
                 'ux_purchase_orders_place_operation_id',
                 'ux_purchase_orders_cancel_operation_id',
                 'ix_purchase_order_items_order_id',
                 'ix_purchase_order_items_product_id',
                 'ux_purchase_order_items_order_product',
                 'ux_purchase_receipts_purchase_order_id'
               )"""
        ).fetchall()
    }
    required = {
        ("table", "purchase_orders"),
        ("table", "purchase_order_items"),
        ("index", "ix_purchase_orders_shop_created"),
        ("index", "ix_purchase_orders_supplier_created"),
        ("index", "ix_purchase_orders_shop_status"),
        ("index", "ux_purchase_orders_create_operation_id"),
        ("index", "ux_purchase_orders_place_operation_id"),
        ("index", "ux_purchase_orders_cancel_operation_id"),
        ("index", "ix_purchase_order_items_order_id"),
        ("index", "ix_purchase_order_items_product_id"),
        ("index", "ux_purchase_order_items_order_product"),
        ("index", "ux_purchase_receipts_purchase_order_id"),
    }
    if objects != required:
        raise RuntimeError("PO_VERIFY_SCHEMA_OBJECTS")

    receipt_columns = {
        row[1] for row in execute("PRAGMA table_info(purchase_receipts)").fetchall()
    }
    if "purchase_order_id" not in receipt_columns:
        raise RuntimeError("PO_VERIFY_RECEIPT_LINK")

    invalid_orders = execute(
        """SELECT COUNT(*) FROM purchase_orders
           WHERE status NOT IN ('DRAFT', 'ORDERED', 'RECEIVED', 'CANCELLED')
              OR length(create_operation_id) < 8
              OR length(create_fingerprint) <> 64"""
    ).fetchone()[0]
    invalid_items = execute(
        """SELECT COUNT(*) FROM purchase_order_items i
           LEFT JOIN purchase_orders o ON o.id = i.purchase_order_id
           LEFT JOIN products p ON p.id = i.product_id
           WHERE o.id IS NULL OR p.id IS NULL OR p.shop_id <> o.shop_id
              OR typeof(i.quantity) <> 'integer' OR i.quantity <= 0"""
    ).fetchone()[0]
    invalid_receipts = execute(
        """SELECT COUNT(*) FROM purchase_receipts r
           LEFT JOIN purchase_orders o ON o.id = r.purchase_order_id
           WHERE r.purchase_order_id IS NOT NULL
             AND (o.id IS NULL OR o.shop_id <> r.shop_id
                  OR o.supplier_id <> r.supplier_id)"""
    ).fetchone()[0]
    invalid_lifecycle = execute(
        """SELECT COUNT(*) FROM purchase_orders o
           LEFT JOIN purchase_receipts r ON r.purchase_order_id = o.id
           WHERE (o.status = 'RECEIVED'
                  AND (r.id IS NULL OR r.status <> 'POSTED'))
              OR (o.status = 'CANCELLED' AND r.id IS NOT NULL)
              OR (r.status = 'DRAFT' AND o.status <> 'ORDERED')
              OR (r.status = 'POSTED' AND o.status <> 'RECEIVED')"""
    ).fetchone()[0]
    if invalid_orders or invalid_items or invalid_receipts or invalid_lifecycle:
        raise RuntimeError("PO_VERIFY_DATA")


def downgrade():
    raise RuntimeError("FORWARD_ONLY_MIGRATION")
