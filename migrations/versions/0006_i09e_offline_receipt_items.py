"""I09-E durable canonical item evidence for contract-v1 receipts.

The claimed product identifier belongs to the signed receipt document.  It is
not a verified catalog foreign key: a missing or cross-shop claim must remain
auditable without ever entering ``order_items.product_id``.  This revision is
self-contained and deliberately refuses to fabricate snapshots for pre-0006
v1 receipts.
"""

from alembic import op

revision = "0006_i09e_offline_receipt_items"
down_revision = "0005_i09c_offline_issue_lifecycle"
branch_labels = None
depends_on = None

MAX_SAFE_QUANTITY = 1000000000
MAX_SAFE_VND = 9000000000000000

TABLE = "offline_receipt_items"
EXPECTED_INDEXES_0006 = (
    (
        "ux_offline_receipt_items_receipt_ordinal",
        1,
        ("receipt_id", "item_ordinal"),
        0,
    ),
    ("ux_offline_receipt_items_order_item", 1, ("order_item_id",), 0),
    ("ix_offline_receipt_items_claimed_product", 0, ("claimed_product_id",), 0),
)

DDL = (
    f"""CREATE TABLE {TABLE} (
        id INTEGER NOT NULL,
        receipt_id INTEGER NOT NULL,
        order_item_id INTEGER NOT NULL,
        item_ordinal INTEGER NOT NULL,
        claimed_product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        unit_price_vnd INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_offline_receipt_items_ordinal CHECK (
            typeof(item_ordinal) = 'integer'
            AND item_ordinal >= 1 AND item_ordinal <= 200
        ),
        CONSTRAINT ck_offline_receipt_items_claimed_product CHECK (
            typeof(claimed_product_id) = 'integer'
            AND claimed_product_id >= 1
            AND claimed_product_id <= {MAX_SAFE_QUANTITY}
        ),
        CONSTRAINT ck_offline_receipt_items_product_name CHECK (
            typeof(product_name) = 'text'
            AND length(product_name) >= 1 AND length(product_name) <= 300
            AND length(CAST(product_name AS BLOB)) <= 900
        ),
        CONSTRAINT ck_offline_receipt_items_unit_price CHECK (
            typeof(unit_price_vnd) = 'integer'
            AND unit_price_vnd >= 0 AND unit_price_vnd <= {MAX_SAFE_VND}
        ),
        CONSTRAINT ck_offline_receipt_items_quantity CHECK (
            typeof(quantity) = 'integer'
            AND quantity >= 1 AND quantity <= {MAX_SAFE_QUANTITY}
        ),
        FOREIGN KEY(receipt_id) REFERENCES offline_receipts (id),
        FOREIGN KEY(order_item_id) REFERENCES order_items (id)
    )""",
    f"""CREATE UNIQUE INDEX ux_offline_receipt_items_receipt_ordinal
        ON {TABLE} (receipt_id, item_ordinal)""",
    f"""CREATE UNIQUE INDEX ux_offline_receipt_items_order_item
        ON {TABLE} (order_item_id)""",
    f"""CREATE INDEX ix_offline_receipt_items_claimed_product
        ON {TABLE} (claimed_product_id)""",
)

EXPECTED_COLUMNS_0006 = (
    ("id", "INTEGER", 1, 1),
    ("receipt_id", "INTEGER", 1, 0),
    ("order_item_id", "INTEGER", 1, 0),
    ("item_ordinal", "INTEGER", 1, 0),
    ("claimed_product_id", "INTEGER", 1, 0),
    ("product_name", "TEXT", 1, 0),
    ("unit_price_vnd", "INTEGER", 1, 0),
    ("quantity", "INTEGER", 1, 0),
)

REQUIRED_CONSTRAINTS_0006 = (
    "constraint ck_offline_receipt_items_ordinal check",
    "constraint ck_offline_receipt_items_claimed_product check",
    "constraint ck_offline_receipt_items_product_name check",
    "constraint ck_offline_receipt_items_unit_price check",
    "constraint ck_offline_receipt_items_quantity check",
)

DATA_CHECKS = (
    (
        "I09E_VERIFY_ITEM_SHAPE",
        f"""SELECT COUNT(*) FROM {TABLE}
            WHERE typeof(receipt_id) <> 'integer'
               OR typeof(order_item_id) <> 'integer'
               OR typeof(item_ordinal) <> 'integer'
               OR item_ordinal < 1 OR item_ordinal > 200
               OR typeof(claimed_product_id) <> 'integer'
               OR claimed_product_id < 1
               OR claimed_product_id > {MAX_SAFE_QUANTITY}
               OR typeof(product_name) <> 'text'
               OR length(product_name) < 1 OR length(product_name) > 300
               OR length(CAST(product_name AS BLOB)) > 900
               OR typeof(unit_price_vnd) <> 'integer'
               OR unit_price_vnd < 0 OR unit_price_vnd > {MAX_SAFE_VND}
               OR typeof(quantity) <> 'integer'
               OR quantity < 1 OR quantity > {MAX_SAFE_QUANTITY}""",
    ),
    (
        "I09E_VERIFY_V1_ONLY",
        f"""SELECT COUNT(*) FROM {TABLE} s
            LEFT JOIN offline_receipts r ON r.id = s.receipt_id
            WHERE r.id IS NULL OR r.contract_version <> 1""",
    ),
    (
        "I09E_VERIFY_ITEM_SCOPE",
        f"""SELECT COUNT(*) FROM {TABLE} s
            LEFT JOIN offline_receipts r ON r.id = s.receipt_id
            LEFT JOIN order_items i ON i.id = s.order_item_id
            WHERE r.id IS NULL OR i.id IS NULL OR i.order_id IS NOT r.order_id""",
    ),
    (
        "I09E_VERIFY_V1_CARDINALITY",
        """SELECT COUNT(*) FROM offline_receipts r
            WHERE r.contract_version = 1
              AND (
                (SELECT COUNT(*) FROM order_items i WHERE i.order_id = r.order_id)
                  NOT BETWEEN 1 AND 200
                OR (SELECT COUNT(*) FROM offline_receipt_items s
                    WHERE s.receipt_id = r.id)
                   <> (SELECT COUNT(*) FROM order_items i
                       WHERE i.order_id = r.order_id)
              )""",
    ),
    (
        "I09E_VERIFY_ITEM_ORDINALS",
        """SELECT COUNT(*) FROM offline_receipts r
            WHERE r.contract_version = 1
              AND (
                (SELECT MIN(s.item_ordinal) FROM offline_receipt_items s
                 WHERE s.receipt_id = r.id) IS NOT 1
                OR (SELECT MAX(s.item_ordinal) FROM offline_receipt_items s
                    WHERE s.receipt_id = r.id)
                   IS NOT (SELECT COUNT(*) FROM offline_receipt_items s
                           WHERE s.receipt_id = r.id)
                OR (SELECT COUNT(DISTINCT s.item_ordinal)
                    FROM offline_receipt_items s WHERE s.receipt_id = r.id)
                   <> (SELECT COUNT(*) FROM offline_receipt_items s
                       WHERE s.receipt_id = r.id)
              )""",
    ),
    (
        "I09E_VERIFY_ITEM_SNAPSHOT",
        """SELECT COUNT(*) FROM offline_receipt_items s
            JOIN order_items i ON i.id = s.order_item_id
            WHERE s.product_name IS NOT i.product_name
               OR s.unit_price_vnd IS NOT i.unit_price_vnd
               OR s.quantity IS NOT i.quantity""",
    ),
    (
        "I09E_VERIFY_ITEM_CANONICAL_ORDER",
        """SELECT COUNT(*) FROM (
            SELECT item_ordinal,
                   ROW_NUMBER() OVER (
                       PARTITION BY receipt_id
                       ORDER BY claimed_product_id,
                                CAST(product_name AS BLOB),
                                unit_price_vnd, quantity, item_ordinal
                   ) AS canonical_ordinal
            FROM offline_receipt_items
        ) ranked
        WHERE item_ordinal IS NOT canonical_ordinal""",
    ),
    (
        "I09E_VERIFY_VERIFIED_PRODUCT_SCOPE",
        """SELECT COUNT(*) FROM offline_receipt_items s
            JOIN offline_receipts r ON r.id = s.receipt_id
            JOIN order_items i ON i.id = s.order_item_id
            JOIN orders o ON o.id = r.order_id
            LEFT JOIN products p ON p.id = i.product_id
            WHERE (i.product_id IS NOT NULL
                   AND (i.product_id IS NOT s.claimed_product_id
                        OR p.id IS NULL OR p.shop_id IS NOT o.shop_id))
               OR (i.product_id IS NULL
                   AND EXISTS (
                       SELECT 1 FROM products claimed
                       WHERE claimed.id = s.claimed_product_id
                         AND claimed.shop_id = o.shop_id
                   ))""",
    ),
)


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def upgrade():
    # There is no trustworthy source for the original claimed id/order of a v1
    # receipt once only OrderItem remains.  Refuse migration instead of inventing
    # financial evidence; operators must resolve such an unsupported pilot DB.
    connection = op.get_bind()
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    if execute(
        "SELECT COUNT(*) FROM offline_receipts WHERE contract_version = 1"
    ).fetchone()[0]:
        raise RuntimeError("I09E_PREEXISTING_V1_RECEIPTS")
    for statement in DDL:
        _execute(statement)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    table_row = execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
    ).fetchone()
    if table_row is None:
        raise RuntimeError("I09E_VERIFY_SCHEMA_OBJECTS:" + TABLE)

    columns = tuple(
        (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in execute(f"PRAGMA table_info({TABLE})").fetchall()
    )
    indexes = {}
    for row in execute(f"PRAGMA index_list({TABLE})").fetchall():
        name = str(row[1])
        if name.startswith("sqlite_autoindex_"):
            continue
        quoted_name = '"' + name.replace('"', '""') + '"'
        key_columns = tuple(
            item[2]
            for item in sorted(
                execute(f"PRAGMA index_info({quoted_name})").fetchall(),
                key=lambda item: int(item[0]),
            )
        )
        indexes[name] = (int(row[2]), key_columns, int(row[4]))
    foreign_keys = {
        (row[2], row[3], row[4])
        for row in execute(f"PRAGMA foreign_key_list({TABLE})").fetchall()
    }
    compact_sql = " ".join(str(table_row[0]).lower().split())
    if (
        columns != EXPECTED_COLUMNS_0006
        or indexes
        != {
            name: (unique, key_columns, partial)
            for name, unique, key_columns, partial in EXPECTED_INDEXES_0006
        }
        or foreign_keys
        != {
            ("offline_receipts", "receipt_id", "id"),
            ("order_items", "order_item_id", "id"),
        }
        or any(token not in compact_sql for token in REQUIRED_CONSTRAINTS_0006)
    ):
        raise RuntimeError("I09E_VERIFY_SCHEMA_SHAPE")

    for code, statement in DATA_CHECKS:
        if execute(statement).fetchone()[0]:
            raise RuntimeError(code)


def downgrade():
    raise RuntimeError("F-Selling I09-E migrations are forward-only")
