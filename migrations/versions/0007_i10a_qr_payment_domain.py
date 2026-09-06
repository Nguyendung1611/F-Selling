"""I10-A immutable sales-QR intent and durable bank evidence domain.

Schema only.  QR issuance/rendering, webhook parsing/application, reconciliation
handlers, account-change locks and rollout gates belong to I10-B/C/D/R.  This
revision is self-contained and deliberately creates no row from legacy orders,
shop bank settings, ORDER{id} references or old payment ledger entries.
"""

from alembic import op

revision = "0007_i10a_qr_payment_domain"
down_revision = "0006_i09e_offline_receipt_items"
branch_labels = None
depends_on = None

MAX_SAFE_VND = 9000000000000000
MAX_STATE_VERSION = 1000000000

INTENT_TABLE = "qr_payment_intents"
EVENT_TABLE = "bank_webhook_events"
ACTION_TABLE = "bank_reconciliation_actions"

CANONICAL_TIME_GLOB = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] "
    "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
    "[0-9][0-9][0-9][0-9][0-9][0-9]"
)


def _canonical_time_predicate(column, *, nullable=False):
    """Exact UTC-naive microsecond text, including real calendar-day bounds."""
    year = "CAST(substr(" + column + ", 1, 4) AS INTEGER)"
    month = "CAST(substr(" + column + ", 6, 2) AS INTEGER)"
    day = "CAST(substr(" + column + ", 9, 2) AS INTEGER)"
    last_day = (
        "CASE "
        "WHEN " + month + " IN (1,3,5,7,8,10,12) THEN 31 "
        "WHEN " + month + " IN (4,6,9,11) THEN 30 "
        "WHEN " + month + " = 2 THEN CASE "
        "WHEN ((" + year + " % 400 = 0) OR (" + year + " % 4 = 0 "
        "AND " + year + " % 100 <> 0)) THEN 29 ELSE 28 END "
        "ELSE 0 END"
    )
    shape = (
        "typeof(" + column + ") = 'text'"
        " AND length(" + column + ") = 26"
        " AND " + column + " GLOB '" + CANONICAL_TIME_GLOB + "'"
        " AND " + year + " BETWEEN 1 AND 9999"
        " AND " + month + " BETWEEN 1 AND 12"
        " AND " + day + " BETWEEN 1 AND (" + last_day + ")"
        " AND CAST(substr(" + column + ", 12, 2) AS INTEGER) BETWEEN 0 AND 23"
        " AND CAST(substr(" + column + ", 15, 2) AS INTEGER) BETWEEN 0 AND 59"
        " AND CAST(substr(" + column + ", 18, 2) AS INTEGER) BETWEEN 0 AND 59"
    )
    if nullable:
        return "(" + column + " IS NULL OR (" + shape + "))"
    return "(" + column + " IS NOT NULL AND " + shape + ")"


def _lower_hex_digest_predicate(column):
    return (
        "typeof(" + column + ") = 'text'"
        " AND length(" + column + ") = 64"
        " AND length(trim(" + column + ", '0123456789abcdef')) = 0"
    )


def _canonical_reference_predicate(column, *, nullable=False):
    shape = (
        "typeof(" + column + ") = 'text'"
        " AND length(" + column + ") BETWEEN 1 AND 128"
        " AND length(CAST(" + column + " AS BLOB)) <= 128"
        " AND " + column + " = trim(" + column + ")"
        " AND " + column + " = upper(" + column + ")"
        " AND " + column + " NOT GLOB '*[^A-Z0-9._:/-]*'"
        " AND " + column + " GLOB '*[A-Z0-9]*'"
    )
    if nullable:
        return "(" + column + " IS NULL OR (" + shape + "))"
    return "(" + column + " IS NOT NULL AND " + shape + ")"


def _identifier_predicate(column, *, maximum=64, nullable=False):
    shape = (
        "typeof(" + column + ") = 'text'"
        " AND length(" + column + ") BETWEEN 1 AND " + str(maximum)
        + " AND length(CAST(" + column + " AS BLOB)) <= " + str(maximum)
        + " AND " + column + " = trim(" + column + ")"
        " AND " + column + " NOT GLOB '*[^A-Za-z0-9._:/-]*'"
        " AND " + column + " GLOB '*[A-Za-z0-9]*'"
    )
    if nullable:
        return "(" + column + " IS NULL OR (" + shape + "))"
    return "(" + column + " IS NOT NULL AND " + shape + ")"


def _code_predicate(column, *, nullable=False):
    shape = (
        "typeof(" + column + ") = 'text'"
        " AND length(" + column + ") BETWEEN 1 AND 64"
        " AND " + column + " = trim(" + column + ")"
        " AND " + column + " = upper(" + column + ")"
        " AND " + column + " NOT GLOB '*[^A-Z0-9_]*'"
        " AND " + column + " GLOB '*[A-Z0-9]*'"
    )
    if nullable:
        return "(" + column + " IS NULL OR (" + shape + "))"
    return "(" + column + " IS NOT NULL AND " + shape + ")"


def _bounded_text_predicate(column, *, maximum_chars, maximum_bytes, nullable=False):
    shape = (
        "typeof(" + column + ") = 'text'"
        " AND length(trim(" + column + ")) BETWEEN 1 AND " + str(maximum_chars)
        + " AND " + column + " = trim(" + column + ")"
        " AND length(CAST(" + column + " AS BLOB)) <= " + str(maximum_bytes)
        + " AND instr(" + column + ", char(0)) = 0"
        " AND instr(" + column + ", char(9)) = 0"
        " AND instr(" + column + ", char(10)) = 0"
        " AND instr(" + column + ", char(13)) = 0"
    )
    if nullable:
        return "(" + column + " IS NULL OR (" + shape + "))"
    return "(" + column + " IS NOT NULL AND " + shape + ")"


INTENT_DDL = f"""CREATE TABLE {INTENT_TABLE} (
    id INTEGER NOT NULL,
    contract_version INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    shop_id INTEGER NOT NULL,
    canonical_reference TEXT NOT NULL,
    expected_vnd INTEGER NOT NULL,
    bank_code TEXT NOT NULL,
    account_no TEXT NOT NULL,
    account_name TEXT NOT NULL,
    adapter_profile_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    display_expires_at TEXT,
    cancel_after TEXT,
    PRIMARY KEY (id),
    CONSTRAINT ck_qr_payment_intents_id CHECK (
        typeof(id) = 'integer' AND id >= 1
    ),
    CONSTRAINT ck_qr_payment_intents_contract CHECK (
        typeof(contract_version) = 'integer' AND contract_version = 1
    ),
    CONSTRAINT ck_qr_payment_intents_scope CHECK (
        typeof(order_id) = 'integer' AND order_id >= 1
        AND typeof(shop_id) = 'integer' AND shop_id >= 1
    ),
    CONSTRAINT ck_qr_payment_intents_reference CHECK (
        {_canonical_reference_predicate('canonical_reference')}
    ),
    CONSTRAINT ck_qr_payment_intents_expected_vnd CHECK (
        typeof(expected_vnd) = 'integer'
        AND expected_vnd > 0 AND expected_vnd <= {MAX_SAFE_VND}
    ),
    CONSTRAINT ck_qr_payment_intents_bank_code CHECK (
        {_identifier_predicate('bank_code', maximum=32)}
    ),
    CONSTRAINT ck_qr_payment_intents_account_no CHECK (
        {_identifier_predicate('account_no', maximum=64)}
    ),
    CONSTRAINT ck_qr_payment_intents_account_name CHECK (
        {_bounded_text_predicate('account_name', maximum_chars=200, maximum_bytes=600)}
    ),
    CONSTRAINT ck_qr_payment_intents_adapter_profile CHECK (
        {_identifier_predicate('adapter_profile_id', maximum=64)}
    ),
    CONSTRAINT ck_qr_payment_intents_time CHECK (
        {_canonical_time_predicate('issued_at')}
        AND {_canonical_time_predicate('display_expires_at', nullable=True)}
        AND {_canonical_time_predicate('cancel_after', nullable=True)}
        AND (display_expires_at IS NULL OR display_expires_at >= issued_at)
        AND (cancel_after IS NULL OR cancel_after >= issued_at)
        AND (display_expires_at IS NULL OR cancel_after IS NULL
             OR cancel_after >= display_expires_at)
    ),
    FOREIGN KEY(order_id, shop_id) REFERENCES orders (id, shop_id),
    FOREIGN KEY(shop_id) REFERENCES shops (id)
)"""

EVENT_DDL = f"""CREATE TABLE {EVENT_TABLE} (
    id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT,
    idempotency_key TEXT NOT NULL,
    normalized_account_no TEXT,
    direction TEXT NOT NULL,
    amount_vnd INTEGER,
    reference_state TEXT NOT NULL,
    normalized_reference TEXT,
    normalized_sha256 TEXT NOT NULL,
    envelope_sha256 TEXT NOT NULL,
    intent_id INTEGER,
    order_id INTEGER,
    shop_id INTEGER,
    payment_id INTEGER,
    disposition TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    received_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT ck_bank_webhook_events_id CHECK (
        typeof(id) = 'integer' AND id >= 1
    ),
    CONSTRAINT ck_bank_webhook_events_provider CHECK (
        {_identifier_predicate('provider', maximum=32)}
        AND {_bounded_text_predicate('provider_event_id', maximum_chars=128, maximum_bytes=384, nullable=True)}
    ),
    CONSTRAINT ck_bank_webhook_events_idempotency CHECK (
        {_lower_hex_digest_predicate('idempotency_key')}
    ),
    CONSTRAINT ck_bank_webhook_events_account CHECK (
        {_identifier_predicate('normalized_account_no', maximum=64, nullable=True)}
    ),
    CONSTRAINT ck_bank_webhook_events_direction CHECK (
        direction IN ('IN', 'OUT', 'UNKNOWN')
    ),
    CONSTRAINT ck_bank_webhook_events_amount CHECK (
        amount_vnd IS NULL OR (
            typeof(amount_vnd) = 'integer'
            AND amount_vnd >= 0 AND amount_vnd <= {MAX_SAFE_VND}
        )
    ),
    CONSTRAINT ck_bank_webhook_events_reference_state CHECK (
        reference_state IN ('EXACT', 'MISSING', 'TRUNCATED', 'MULTIPLE', 'INVALID')
        AND {_canonical_reference_predicate('normalized_reference', nullable=True)}
        AND (
            (reference_state IN ('EXACT', 'TRUNCATED')
             AND normalized_reference IS NOT NULL)
            OR (reference_state IN ('MISSING', 'MULTIPLE', 'INVALID')
                AND normalized_reference IS NULL)
        )
    ),
    CONSTRAINT ck_bank_webhook_events_digests CHECK (
        {_lower_hex_digest_predicate('normalized_sha256')}
        AND {_lower_hex_digest_predicate('envelope_sha256')}
    ),
    CONSTRAINT ck_bank_webhook_events_links CHECK (
        (intent_id IS NULL OR (
            typeof(intent_id) = 'integer' AND intent_id >= 1
            AND order_id IS NOT NULL AND shop_id IS NOT NULL
        ))
        AND (order_id IS NULL OR (
            typeof(order_id) = 'integer' AND order_id >= 1
            AND shop_id IS NOT NULL
        ))
        AND (shop_id IS NULL OR (typeof(shop_id) = 'integer' AND shop_id >= 1))
        AND (payment_id IS NULL OR (
            typeof(payment_id) = 'integer' AND payment_id >= 1
            AND order_id IS NOT NULL AND shop_id IS NOT NULL
        ))
    ),
    CONSTRAINT ck_bank_webhook_events_disposition CHECK (
        disposition IN ('UNAPPLIED', 'APPLIED', 'REJECTED_NOT_OURS', 'REFUNDED')
        AND {_code_predicate('reason_code')}
        AND (
            (disposition = 'APPLIED' AND payment_id IS NOT NULL
             AND direction = 'IN' AND amount_vnd IS NOT NULL AND amount_vnd > 0)
            OR (disposition <> 'APPLIED' AND payment_id IS NULL)
        )
    ),
    CONSTRAINT ck_bank_webhook_events_time CHECK (
        {_canonical_time_predicate('received_at')}
        AND {_canonical_time_predicate('updated_at')}
        AND updated_at >= received_at
    ),
    CONSTRAINT ck_bank_webhook_events_state_version CHECK (
        typeof(state_version) = 'integer'
        AND state_version >= 0 AND state_version <= {MAX_STATE_VERSION}
    ),
    FOREIGN KEY(intent_id, order_id, shop_id)
        REFERENCES qr_payment_intents (id, order_id, shop_id),
    FOREIGN KEY(order_id, shop_id) REFERENCES orders (id, shop_id),
    FOREIGN KEY(shop_id) REFERENCES shops (id),
    FOREIGN KEY(payment_id, order_id) REFERENCES order_payments (id, order_id)
)"""

ACTION_DDL = f"""CREATE TABLE {ACTION_TABLE} (
    id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    event_state_version INTEGER NOT NULL,
    action_kind TEXT NOT NULL,
    intent_id INTEGER,
    order_id INTEGER,
    shop_id INTEGER,
    payment_id INTEGER,
    performed_by_user_id INTEGER NOT NULL,
    actor_role TEXT NOT NULL,
    note TEXT,
    performed_at TEXT NOT NULL,
    system_log_id INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_bank_reconciliation_actions_id CHECK (
        typeof(id) = 'integer' AND id >= 1
        AND typeof(event_id) = 'integer' AND event_id >= 1
    ),
    CONSTRAINT ck_bank_reconciliation_actions_event_version CHECK (
        typeof(event_state_version) = 'integer'
        AND event_state_version >= 0
        AND event_state_version <= {MAX_STATE_VERSION}
    ),
    CONSTRAINT ck_bank_reconciliation_actions_kind CHECK (
        action_kind IN (
            'KEEP_OPEN', 'MAP_AND_APPLY',
            'REJECT_NOT_OURS', 'MARK_REFUNDED_EXTERNALLY'
        )
    ),
    CONSTRAINT ck_bank_reconciliation_actions_links CHECK (
        (intent_id IS NULL OR (
            typeof(intent_id) = 'integer' AND intent_id >= 1
            AND order_id IS NOT NULL AND shop_id IS NOT NULL
        ))
        AND (order_id IS NULL OR (
            typeof(order_id) = 'integer' AND order_id >= 1
            AND shop_id IS NOT NULL
        ))
        AND (shop_id IS NULL OR (typeof(shop_id) = 'integer' AND shop_id >= 1))
        AND (
            (action_kind = 'MAP_AND_APPLY'
             AND payment_id IS NOT NULL
             AND typeof(payment_id) = 'integer' AND payment_id >= 1
             AND order_id IS NOT NULL AND shop_id IS NOT NULL)
            OR (action_kind <> 'MAP_AND_APPLY' AND payment_id IS NULL)
        )
    ),
    CONSTRAINT ck_bank_reconciliation_actions_actor CHECK (
        typeof(performed_by_user_id) = 'integer' AND performed_by_user_id >= 1
        AND actor_role IN ('ADMIN', 'OWNER', 'MANAGER')
        AND (shop_id IS NOT NULL OR actor_role = 'ADMIN')
    ),
    CONSTRAINT ck_bank_reconciliation_actions_note CHECK (
        (action_kind NOT IN ('REJECT_NOT_OURS', 'MARK_REFUNDED_EXTERNALLY')
         AND {_bounded_text_predicate('note', maximum_chars=500, maximum_bytes=1500, nullable=True)})
        OR (action_kind IN ('REJECT_NOT_OURS', 'MARK_REFUNDED_EXTERNALLY')
            AND {_bounded_text_predicate('note', maximum_chars=500, maximum_bytes=1500)})
    ),
    CONSTRAINT ck_bank_reconciliation_actions_time CHECK (
        {_canonical_time_predicate('performed_at')}
    ),
    CONSTRAINT ck_bank_reconciliation_actions_audit CHECK (
        typeof(system_log_id) = 'integer' AND system_log_id >= 1
    ),
    FOREIGN KEY(event_id) REFERENCES bank_webhook_events (id),
    FOREIGN KEY(intent_id, order_id, shop_id)
        REFERENCES qr_payment_intents (id, order_id, shop_id),
    FOREIGN KEY(order_id, shop_id) REFERENCES orders (id, shop_id),
    FOREIGN KEY(shop_id) REFERENCES shops (id),
    FOREIGN KEY(payment_id, order_id) REFERENCES order_payments (id, order_id),
    FOREIGN KEY(performed_by_user_id) REFERENCES users (id),
    FOREIGN KEY(system_log_id) REFERENCES system_logs (id)
)"""

_EVENT_CORE_SAME = (
    "NEW.id = OLD.id"
    " AND NEW.provider = OLD.provider"
    " AND NEW.provider_event_id IS OLD.provider_event_id"
    " AND NEW.idempotency_key = OLD.idempotency_key"
    " AND NEW.normalized_account_no IS OLD.normalized_account_no"
    " AND NEW.direction = OLD.direction"
    " AND NEW.amount_vnd IS OLD.amount_vnd"
    " AND NEW.reference_state = OLD.reference_state"
    " AND NEW.normalized_reference IS OLD.normalized_reference"
    " AND NEW.normalized_sha256 = OLD.normalized_sha256"
    " AND NEW.envelope_sha256 = OLD.envelope_sha256"
    " AND NEW.received_at = OLD.received_at"
)

DDL = (
    # Composite parent keys let SQLite enforce tenant scope, not merely existence.
    "CREATE UNIQUE INDEX ux_i10a_orders_id_shop ON orders (id, shop_id)",
    "CREATE UNIQUE INDEX ux_i10a_order_payments_id_order ON order_payments (id, order_id)",
    INTENT_DDL,
    "CREATE UNIQUE INDEX ux_qr_payment_intents_order_id ON qr_payment_intents (order_id)",
    "CREATE UNIQUE INDEX ux_qr_payment_intents_reference ON qr_payment_intents (canonical_reference)",
    "CREATE UNIQUE INDEX ux_qr_payment_intents_id_order_shop ON qr_payment_intents (id, order_id, shop_id)",
    "CREATE INDEX ix_qr_payment_intents_shop_issued ON qr_payment_intents (shop_id, issued_at, id)",
    EVENT_DDL,
    "CREATE UNIQUE INDEX ux_bank_webhook_events_provider_idempotency ON bank_webhook_events (provider, idempotency_key)",
    "CREATE UNIQUE INDEX ux_bank_webhook_events_payment_id ON bank_webhook_events (payment_id) WHERE payment_id IS NOT NULL",
    "CREATE INDEX ix_bank_webhook_events_provider_event ON bank_webhook_events (provider, provider_event_id) WHERE provider_event_id IS NOT NULL",
    "CREATE INDEX ix_bank_webhook_events_unapplied_shop_received ON bank_webhook_events (shop_id, received_at, id) WHERE disposition = 'UNAPPLIED'",
    "CREATE INDEX ix_bank_webhook_events_reference_received ON bank_webhook_events (normalized_reference, received_at, id) WHERE normalized_reference IS NOT NULL",
    "CREATE INDEX ix_bank_webhook_events_intent_disposition ON bank_webhook_events (intent_id, disposition, received_at) WHERE intent_id IS NOT NULL",
    ACTION_DDL,
    "CREATE UNIQUE INDEX ux_bank_reconciliation_actions_event_version ON bank_reconciliation_actions (event_id, event_state_version)",
    "CREATE UNIQUE INDEX ux_bank_reconciliation_actions_system_log ON bank_reconciliation_actions (system_log_id)",
    "CREATE UNIQUE INDEX ux_bank_reconciliation_actions_terminal_event ON bank_reconciliation_actions (event_id) WHERE action_kind IN ('MAP_AND_APPLY', 'REJECT_NOT_OURS', 'MARK_REFUNDED_EXTERNALLY')",
    "CREATE INDEX ix_bank_reconciliation_actions_shop_performed ON bank_reconciliation_actions (shop_id, performed_at, id)",
    # Intent is immutable evidence and may only be born for an exact online
    # transfer order using the shop account snapshot visible in this transaction.
    "CREATE TRIGGER trg_i10a_qr_intent_insert_guard"
    " BEFORE INSERT ON qr_payment_intents FOR EACH ROW"
    " WHEN NOT EXISTS ("
    "   SELECT 1 FROM orders o JOIN shops s ON s.id = o.shop_id"
    "   WHERE o.id = NEW.order_id AND o.shop_id = NEW.shop_id"
    "     AND o.payment_method = 'transfer'"
    "     AND typeof(o.total_vnd) = 'integer' AND o.total_vnd > 0"
    "     AND o.total_vnd = NEW.expected_vnd AND o.offline_uuid IS NULL"
    "     AND s.bank_code IS NEW.bank_code"
    "     AND s.bank_account_no IS NEW.account_no"
    "     AND s.bank_account_name IS NEW.account_name"
    " )"
    " BEGIN SELECT RAISE(ABORT, 'I10A_QR_INTENT_ORDER_SNAPSHOT'); END",
    "CREATE TRIGGER trg_i10a_qr_intent_no_update"
    " BEFORE UPDATE ON qr_payment_intents FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I10A_QR_INTENT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_qr_intent_no_delete"
    " BEFORE DELETE ON qr_payment_intents FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I10A_QR_INTENT_IMMUTABLE'); END",
    # Once an intent exists, its source order cannot drift away from the exact
    # amount/method/scope the immutable instruction names.
    "CREATE TRIGGER trg_i10a_order_intent_update_guard"
    " BEFORE UPDATE OF id, shop_id, payment_method, total_vnd, offline_uuid ON orders"
    " FOR EACH ROW WHEN EXISTS ("
    "   SELECT 1 FROM qr_payment_intents i WHERE i.order_id = OLD.id"
    " ) AND NOT EXISTS ("
    "   SELECT 1 FROM qr_payment_intents i"
    "   WHERE i.order_id = OLD.id AND NEW.id = OLD.id"
    "     AND NEW.shop_id = i.shop_id"
    "     AND NEW.payment_method = 'transfer'"
    "     AND typeof(NEW.total_vnd) = 'integer'"
    "     AND NEW.total_vnd = i.expected_vnd AND NEW.total_vnd > 0"
    "     AND NEW.offline_uuid IS NULL"
    " )"
    " BEGIN SELECT RAISE(ABORT, 'I10A_QR_INTENT_ORDER_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_order_link_update_guard"
    " BEFORE UPDATE OF id, shop_id, payment_method, total_vnd, offline_uuid"
    " ON orders FOR EACH ROW WHEN ("
    "   EXISTS (SELECT 1 FROM bank_webhook_events e WHERE e.order_id = OLD.id)"
    "   OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "              WHERE a.order_id = OLD.id)"
    " ) AND ("
    "   NEW.id <> OLD.id OR NEW.payment_method <> 'transfer'"
    "   OR typeof(NEW.total_vnd) <> 'integer' OR NEW.total_vnd <= 0"
    "   OR NEW.offline_uuid IS NOT NULL"
    "   OR EXISTS (SELECT 1 FROM bank_webhook_events e"
    "              WHERE e.order_id = OLD.id AND NEW.shop_id IS NOT e.shop_id)"
    "   OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "              WHERE a.order_id = OLD.id AND NEW.shop_id IS NOT a.shop_id)"
    " )"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_ORDER_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_order_link_delete_guard"
    " BEFORE DELETE ON orders FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM qr_payment_intents i WHERE i.order_id = OLD.id)"
    " OR EXISTS (SELECT 1 FROM bank_webhook_events e WHERE e.order_id = OLD.id)"
    " OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a WHERE a.order_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_ORDER_IMMUTABLE'); END",
    # Every inbox row starts UNAPPLIED. Mapping may already be known, but no
    # payment can exist until a later application step validates the evidence.
    "CREATE TRIGGER trg_i10a_bank_event_insert_guard"
    " BEFORE INSERT ON bank_webhook_events FOR EACH ROW WHEN"
    " NEW.disposition <> 'UNAPPLIED' OR NEW.payment_id IS NOT NULL"
    " OR NEW.state_version <> 0"
    " OR (NEW.shop_id IS NOT NULL AND NOT EXISTS ("
    "      SELECT 1 FROM shops s WHERE s.id = NEW.shop_id))"
    " OR (NEW.order_id IS NOT NULL AND NOT EXISTS ("
    "      SELECT 1 FROM orders o"
    "      WHERE o.id = NEW.order_id AND o.shop_id = NEW.shop_id"
    "        AND o.payment_method = 'transfer'"
    "        AND typeof(o.total_vnd) = 'integer' AND o.total_vnd > 0"
    "        AND o.offline_uuid IS NULL))"
    " OR (NEW.intent_id IS NOT NULL AND NOT EXISTS ("
    "      SELECT 1 FROM qr_payment_intents i"
    "      WHERE i.id = NEW.intent_id AND i.order_id = NEW.order_id"
    "        AND i.shop_id = NEW.shop_id))"
    " BEGIN SELECT RAISE(ABORT, 'I10A_BANK_EVENT_INSERT_INVALID'); END",
    "CREATE TRIGGER trg_i10a_bank_event_update_guard"
    " BEFORE UPDATE ON bank_webhook_events FOR EACH ROW WHEN NOT ("
    + _EVENT_CORE_SAME
    + " AND OLD.disposition = 'UNAPPLIED'"
    " AND NEW.disposition IN ("
    "   'UNAPPLIED', 'APPLIED', 'REJECTED_NOT_OURS', 'REFUNDED')"
    " AND NEW.state_version = OLD.state_version + 1"
    " AND NEW.updated_at > OLD.updated_at"
    " AND (NEW.shop_id IS NULL OR EXISTS ("
    "      SELECT 1 FROM shops s WHERE s.id = NEW.shop_id))"
    " AND (NEW.order_id IS NULL OR EXISTS ("
    "      SELECT 1 FROM orders o"
    "      WHERE o.id = NEW.order_id AND o.shop_id = NEW.shop_id"
    "        AND o.payment_method = 'transfer'"
    "        AND typeof(o.total_vnd) = 'integer' AND o.total_vnd > 0"
    "        AND o.offline_uuid IS NULL))"
    " AND (NEW.intent_id IS NULL OR EXISTS ("
    "      SELECT 1 FROM qr_payment_intents i"
    "      WHERE i.id = NEW.intent_id AND i.order_id = NEW.order_id"
    "        AND i.shop_id = NEW.shop_id))"
    " AND (NEW.payment_id IS NULL OR EXISTS ("
    "      SELECT 1 FROM order_payments p"
    "      WHERE p.id = NEW.payment_id AND p.order_id = NEW.order_id"
    "        AND p.entry_type = 'BANK_IN'"
    "        AND typeof(p.amount_vnd) = 'integer'"
    "        AND p.amount_vnd = NEW.amount_vnd"
    "        AND p.idempotency_key = NEW.idempotency_key"
    "        AND p.provider = NEW.provider"
    "        AND p.bank_txn_id IS NEW.provider_event_id"
    "        AND p.account_no IS NEW.normalized_account_no))"
    " AND ("
    "   (NEW.disposition = 'UNAPPLIED' AND NEW.payment_id IS NULL)"
    "   OR EXISTS ("
    "      SELECT 1 FROM bank_reconciliation_actions a"
    "      WHERE a.event_id = OLD.id"
    "        AND a.event_state_version = NEW.state_version"
    "        AND a.intent_id IS NEW.intent_id"
    "        AND a.order_id IS NEW.order_id"
    "        AND a.shop_id IS NEW.shop_id"
    "        AND a.payment_id IS NEW.payment_id"
    "        AND a.performed_at = NEW.updated_at"
    "        AND ((a.action_kind = 'MAP_AND_APPLY'"
    "              AND NEW.disposition = 'APPLIED'"
    "              AND NEW.reason_code = 'MAP_AND_APPLY')"
    "          OR (a.action_kind = 'REJECT_NOT_OURS'"
    "              AND NEW.disposition = 'REJECTED_NOT_OURS'"
    "              AND NEW.reason_code = 'REJECT_NOT_OURS')"
    "          OR (a.action_kind = 'MARK_REFUNDED_EXTERNALLY'"
    "              AND NEW.disposition = 'REFUNDED'"
    "              AND NEW.reason_code = 'MARK_REFUNDED_EXTERNALLY'))"
    "   )"
    " )"
    " ) BEGIN SELECT RAISE(ABORT, 'I10A_BANK_EVENT_TRANSITION'); END",
    "CREATE TRIGGER trg_i10a_bank_event_no_delete"
    " BEFORE DELETE ON bank_webhook_events FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I10A_BANK_EVENT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_payment_no_update"
    " BEFORE UPDATE ON order_payments FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM bank_webhook_events e WHERE e.payment_id = OLD.id)"
    " OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a WHERE a.payment_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_PAYMENT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_payment_no_delete"
    " BEFORE DELETE ON order_payments FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM bank_webhook_events e WHERE e.payment_id = OLD.id)"
    " OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a WHERE a.payment_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_PAYMENT_IMMUTABLE'); END",
    # Runtime SQLite currently has FK enforcement off, so every parent key or
    # audit object owned by 0007 needs an explicit guard. Unrelated legacy rows
    # remain untouched because every trigger is conditional on a 0007 child.
    "CREATE TRIGGER trg_i10a_linked_shop_no_id_update"
    " BEFORE UPDATE OF id ON shops FOR EACH ROW"
    " WHEN NEW.id <> OLD.id AND ("
    "   EXISTS (SELECT 1 FROM qr_payment_intents i WHERE i.shop_id = OLD.id)"
    "   OR EXISTS (SELECT 1 FROM bank_webhook_events e WHERE e.shop_id = OLD.id)"
    "   OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "              WHERE a.shop_id = OLD.id)"
    " )"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_SHOP_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_shop_no_delete"
    " BEFORE DELETE ON shops FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM qr_payment_intents i WHERE i.shop_id = OLD.id)"
    " OR EXISTS (SELECT 1 FROM bank_webhook_events e WHERE e.shop_id = OLD.id)"
    " OR EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "            WHERE a.shop_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_SHOP_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_system_log_no_update"
    " BEFORE UPDATE ON system_logs FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "         WHERE a.system_log_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_AUDIT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_system_log_no_delete"
    " BEFORE DELETE ON system_logs FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "         WHERE a.system_log_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_AUDIT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_actor_no_id_update"
    " BEFORE UPDATE OF id ON users FOR EACH ROW"
    " WHEN NEW.id <> OLD.id AND EXISTS ("
    "   SELECT 1 FROM bank_reconciliation_actions a"
    "   WHERE a.performed_by_user_id = OLD.id"
    " )"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_ACTOR_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i10a_linked_actor_no_delete"
    " BEFORE DELETE ON users FOR EACH ROW WHEN"
    " EXISTS (SELECT 1 FROM bank_reconciliation_actions a"
    "         WHERE a.performed_by_user_id = OLD.id)"
    " BEGIN SELECT RAISE(ABORT, 'I10A_LINKED_ACTOR_IMMUTABLE'); END",
    # Role is snapshotted for audit. Terminal action insert is the sole command
    # that can transition an event: the AFTER trigger below performs the update
    # while this newly inserted, fully validated action is visible to the event
    # guard. Any transition failure rolls the action INSERT back atomically.
    "CREATE TRIGGER trg_i10a_reconciliation_action_insert_guard"
    " BEFORE INSERT ON bank_reconciliation_actions FOR EACH ROW WHEN"
    " NOT EXISTS ("
    "   SELECT 1 FROM bank_webhook_events e"
    "   WHERE e.id = NEW.event_id"
    "     AND e.disposition = 'UNAPPLIED'"
    "     AND ((NEW.action_kind = 'KEEP_OPEN'"
    "           AND NEW.event_state_version = e.state_version"
    "           AND e.intent_id IS NEW.intent_id"
    "           AND e.order_id IS NEW.order_id"
    "           AND e.shop_id IS NEW.shop_id"
    "           AND NEW.payment_id IS NULL)"
    "       OR (NEW.action_kind IN ("
    "             'MAP_AND_APPLY', 'REJECT_NOT_OURS',"
    "             'MARK_REFUNDED_EXTERNALLY')"
    "           AND NEW.event_state_version = e.state_version + 1))"
    " )"
    " OR (NEW.shop_id IS NOT NULL AND NOT EXISTS ("
    "      SELECT 1 FROM shops s WHERE s.id = NEW.shop_id))"
    " OR (NEW.order_id IS NOT NULL AND NOT EXISTS ("
    "      SELECT 1 FROM orders o"
    "      WHERE o.id = NEW.order_id AND o.shop_id = NEW.shop_id"
    "        AND o.payment_method = 'transfer'"
    "        AND typeof(o.total_vnd) = 'integer' AND o.total_vnd > 0"
    "        AND o.offline_uuid IS NULL))"
    " OR (NEW.intent_id IS NOT NULL AND NOT EXISTS ("
    "      SELECT 1 FROM qr_payment_intents i"
    "      WHERE i.id = NEW.intent_id AND i.order_id = NEW.order_id"
    "        AND i.shop_id = NEW.shop_id))"
    " OR (NEW.action_kind = 'MAP_AND_APPLY' AND NOT EXISTS ("
    "      SELECT 1 FROM order_payments p"
    "      JOIN bank_webhook_events e ON e.id = NEW.event_id"
    "      WHERE p.id = NEW.payment_id AND p.order_id = NEW.order_id"
    "        AND p.entry_type = 'BANK_IN'"
    "        AND typeof(p.amount_vnd) = 'integer'"
    "        AND p.amount_vnd = e.amount_vnd"
    "        AND p.idempotency_key = e.idempotency_key"
    "        AND p.provider = e.provider"
    "        AND p.bank_txn_id IS e.provider_event_id"
    "        AND p.account_no IS e.normalized_account_no))"
    " OR NOT EXISTS ("
    "   SELECT 1 FROM system_logs sl"
    "   WHERE sl.id = NEW.system_log_id"
    "     AND sl.user_id IS NEW.performed_by_user_id"
    "     AND sl.shop_id IS NEW.shop_id"
    "     AND sl.action = 'BANK_RECONCILIATION'"
    "     AND typeof(sl.details) = 'text'"
    "     AND length(trim(sl.details)) BETWEEN 1 AND 1500"
    "     AND length(CAST(sl.details AS BLOB)) <= 4500"
    "     AND instr(sl.details, char(0)) = 0"
    "     AND sl.created_at IS NEW.performed_at"
    " )"
    " OR (NEW.action_kind = 'KEEP_OPEN' AND NEW.performed_at < ("
    "       SELECT e.updated_at FROM bank_webhook_events e"
    "       WHERE e.id = NEW.event_id))"
    " OR (NEW.action_kind <> 'KEEP_OPEN' AND NEW.performed_at <= ("
    "       SELECT e.updated_at FROM bank_webhook_events e"
    "       WHERE e.id = NEW.event_id))"
    " OR NOT ("
    "   (NEW.actor_role = 'ADMIN' AND EXISTS ("
    "      SELECT 1 FROM users u"
    "      WHERE u.id = NEW.performed_by_user_id AND u.role = 'ADMIN'))"
    "   OR (NEW.actor_role = 'OWNER' AND NEW.shop_id IS NOT NULL AND EXISTS ("
    "      SELECT 1 FROM shops s"
    "      WHERE s.id = NEW.shop_id AND s.owner_id = NEW.performed_by_user_id))"
    "   OR (NEW.actor_role = 'MANAGER' AND NEW.shop_id IS NOT NULL AND EXISTS ("
    "      SELECT 1 FROM users u"
    "      WHERE u.id = NEW.performed_by_user_id AND u.role = 'STAFF'"
    "        AND u.staff_shop_id = NEW.shop_id"
    "        AND COALESCE(u.staff_role, 'MANAGER') = 'MANAGER'))"
    " )"
    " BEGIN SELECT RAISE(ABORT, 'I10A_RECON_ACTION_INVALID'); END",
    "CREATE TRIGGER trg_i10a_reconciliation_action_apply"
    " AFTER INSERT ON bank_reconciliation_actions FOR EACH ROW"
    " WHEN NEW.action_kind <> 'KEEP_OPEN'"
    " BEGIN"
    "   UPDATE bank_webhook_events"
    "   SET intent_id = NEW.intent_id, order_id = NEW.order_id,"
    "       shop_id = NEW.shop_id, payment_id = NEW.payment_id,"
    "       disposition = CASE NEW.action_kind"
    "         WHEN 'MAP_AND_APPLY' THEN 'APPLIED'"
    "         WHEN 'REJECT_NOT_OURS' THEN 'REJECTED_NOT_OURS'"
    "         WHEN 'MARK_REFUNDED_EXTERNALLY' THEN 'REFUNDED' END,"
    "       reason_code = NEW.action_kind,"
    "       updated_at = NEW.performed_at,"
    "       state_version = NEW.event_state_version"
    "   WHERE id = NEW.event_id;"
    "   SELECT RAISE(ABORT, 'I10A_RECON_ACTION_TRANSITION')"
    "   WHERE NOT EXISTS ("
    "     SELECT 1 FROM bank_webhook_events e"
    "     WHERE e.id = NEW.event_id"
    "       AND e.state_version = NEW.event_state_version"
    "       AND e.intent_id IS NEW.intent_id"
    "       AND e.order_id IS NEW.order_id"
    "       AND e.shop_id IS NEW.shop_id"
    "       AND e.payment_id IS NEW.payment_id"
    "       AND e.updated_at = NEW.performed_at"
    "       AND ((NEW.action_kind = 'MAP_AND_APPLY'"
    "             AND e.disposition = 'APPLIED')"
    "         OR (NEW.action_kind = 'REJECT_NOT_OURS'"
    "             AND e.disposition = 'REJECTED_NOT_OURS')"
    "         OR (NEW.action_kind = 'MARK_REFUNDED_EXTERNALLY'"
    "             AND e.disposition = 'REFUNDED'))"
    "   );"
    " END",
    "CREATE TRIGGER trg_i10a_reconciliation_action_no_update"
    " BEFORE UPDATE ON bank_reconciliation_actions FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I10A_RECON_ACTION_APPEND_ONLY'); END",
    "CREATE TRIGGER trg_i10a_reconciliation_action_no_delete"
    " BEFORE DELETE ON bank_reconciliation_actions FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I10A_RECON_ACTION_APPEND_ONLY'); END",
)

EXPECTED_TABLE_PREFIXES = {
    INTENT_TABLE: INTENT_DDL,
    EVENT_TABLE: EVENT_DDL,
    ACTION_TABLE: ACTION_DDL,
}

EXPECTED_COLUMNS = {
    INTENT_TABLE: (
        ("id", "INTEGER", 1, None, 1),
        ("contract_version", "INTEGER", 1, None, 0),
        ("order_id", "INTEGER", 1, None, 0),
        ("shop_id", "INTEGER", 1, None, 0),
        ("canonical_reference", "TEXT", 1, None, 0),
        ("expected_vnd", "INTEGER", 1, None, 0),
        ("bank_code", "TEXT", 1, None, 0),
        ("account_no", "TEXT", 1, None, 0),
        ("account_name", "TEXT", 1, None, 0),
        ("adapter_profile_id", "TEXT", 1, None, 0),
        ("issued_at", "TEXT", 1, None, 0),
        ("display_expires_at", "TEXT", 0, None, 0),
        ("cancel_after", "TEXT", 0, None, 0),
    ),
    EVENT_TABLE: (
        ("id", "INTEGER", 1, None, 1),
        ("provider", "TEXT", 1, None, 0),
        ("provider_event_id", "TEXT", 0, None, 0),
        ("idempotency_key", "TEXT", 1, None, 0),
        ("normalized_account_no", "TEXT", 0, None, 0),
        ("direction", "TEXT", 1, None, 0),
        ("amount_vnd", "INTEGER", 0, None, 0),
        ("reference_state", "TEXT", 1, None, 0),
        ("normalized_reference", "TEXT", 0, None, 0),
        ("normalized_sha256", "TEXT", 1, None, 0),
        ("envelope_sha256", "TEXT", 1, None, 0),
        ("intent_id", "INTEGER", 0, None, 0),
        ("order_id", "INTEGER", 0, None, 0),
        ("shop_id", "INTEGER", 0, None, 0),
        ("payment_id", "INTEGER", 0, None, 0),
        ("disposition", "TEXT", 1, None, 0),
        ("reason_code", "TEXT", 1, None, 0),
        ("received_at", "TEXT", 1, None, 0),
        ("updated_at", "TEXT", 1, None, 0),
        ("state_version", "INTEGER", 1, "0", 0),
    ),
    ACTION_TABLE: (
        ("id", "INTEGER", 1, None, 1),
        ("event_id", "INTEGER", 1, None, 0),
        ("event_state_version", "INTEGER", 1, None, 0),
        ("action_kind", "TEXT", 1, None, 0),
        ("intent_id", "INTEGER", 0, None, 0),
        ("order_id", "INTEGER", 0, None, 0),
        ("shop_id", "INTEGER", 0, None, 0),
        ("payment_id", "INTEGER", 0, None, 0),
        ("performed_by_user_id", "INTEGER", 1, None, 0),
        ("actor_role", "TEXT", 1, None, 0),
        ("note", "TEXT", 0, None, 0),
        ("performed_at", "TEXT", 1, None, 0),
        ("system_log_id", "INTEGER", 1, None, 0),
    ),
}

EXPECTED_FOREIGN_KEYS = {
    INTENT_TABLE: {
        ("orders", (("order_id", "id"), ("shop_id", "shop_id")), "NO ACTION", "NO ACTION", "NONE"),
        ("shops", (("shop_id", "id"),), "NO ACTION", "NO ACTION", "NONE"),
    },
    EVENT_TABLE: {
        ("qr_payment_intents", (("intent_id", "id"), ("order_id", "order_id"), ("shop_id", "shop_id")), "NO ACTION", "NO ACTION", "NONE"),
        ("orders", (("order_id", "id"), ("shop_id", "shop_id")), "NO ACTION", "NO ACTION", "NONE"),
        ("shops", (("shop_id", "id"),), "NO ACTION", "NO ACTION", "NONE"),
        ("order_payments", (("payment_id", "id"), ("order_id", "order_id")), "NO ACTION", "NO ACTION", "NONE"),
    },
    ACTION_TABLE: {
        ("bank_webhook_events", (("event_id", "id"),), "NO ACTION", "NO ACTION", "NONE"),
        ("qr_payment_intents", (("intent_id", "id"), ("order_id", "order_id"), ("shop_id", "shop_id")), "NO ACTION", "NO ACTION", "NONE"),
        ("orders", (("order_id", "id"), ("shop_id", "shop_id")), "NO ACTION", "NO ACTION", "NONE"),
        ("shops", (("shop_id", "id"),), "NO ACTION", "NO ACTION", "NONE"),
        ("order_payments", (("payment_id", "id"), ("order_id", "order_id")), "NO ACTION", "NO ACTION", "NONE"),
        ("users", (("performed_by_user_id", "id"),), "NO ACTION", "NO ACTION", "NONE"),
        ("system_logs", (("system_log_id", "id"),), "NO ACTION", "NO ACTION", "NONE"),
    },
}

EXPECTED_INDEXES = {
    "ux_i10a_orders_id_shop": ("orders", 1, ("id", "shop_id"), 0, None),
    "ux_i10a_order_payments_id_order": ("order_payments", 1, ("id", "order_id"), 0, None),
    "ux_qr_payment_intents_order_id": (INTENT_TABLE, 1, ("order_id",), 0, None),
    "ux_qr_payment_intents_reference": (INTENT_TABLE, 1, ("canonical_reference",), 0, None),
    "ux_qr_payment_intents_id_order_shop": (INTENT_TABLE, 1, ("id", "order_id", "shop_id"), 0, None),
    "ix_qr_payment_intents_shop_issued": (INTENT_TABLE, 0, ("shop_id", "issued_at", "id"), 0, None),
    "ux_bank_webhook_events_provider_idempotency": (EVENT_TABLE, 1, ("provider", "idempotency_key"), 0, None),
    "ux_bank_webhook_events_payment_id": (EVENT_TABLE, 1, ("payment_id",), 1, "payment_idisnotnull"),
    "ix_bank_webhook_events_provider_event": (EVENT_TABLE, 0, ("provider", "provider_event_id"), 1, "provider_event_idisnotnull"),
    "ix_bank_webhook_events_unapplied_shop_received": (EVENT_TABLE, 0, ("shop_id", "received_at", "id"), 1, "disposition='UNAPPLIED'"),
    "ix_bank_webhook_events_reference_received": (EVENT_TABLE, 0, ("normalized_reference", "received_at", "id"), 1, "normalized_referenceisnotnull"),
    "ix_bank_webhook_events_intent_disposition": (EVENT_TABLE, 0, ("intent_id", "disposition", "received_at"), 1, "intent_idisnotnull"),
    "ux_bank_reconciliation_actions_event_version": (ACTION_TABLE, 1, ("event_id", "event_state_version"), 0, None),
    "ux_bank_reconciliation_actions_system_log": (ACTION_TABLE, 1, ("system_log_id",), 0, None),
    "ux_bank_reconciliation_actions_terminal_event": (ACTION_TABLE, 1, ("event_id",), 1, "action_kindin('MAP_AND_APPLY','REJECT_NOT_OURS','MARK_REFUNDED_EXTERNALLY')"),
    "ix_bank_reconciliation_actions_shop_performed": (ACTION_TABLE, 0, ("shop_id", "performed_at", "id"), 0, None),
}

EXPECTED_INDEX_SQL = {}
for _statement in DDL:
    if _statement.startswith("CREATE UNIQUE INDEX "):
        EXPECTED_INDEX_SQL[_statement.split()[3]] = _statement
    elif _statement.startswith("CREATE INDEX "):
        EXPECTED_INDEX_SQL[_statement.split()[2]] = _statement

EXPECTED_TRIGGER_SQL = {
    statement.split()[2]: statement
    for statement in DDL
    if statement.startswith("CREATE TRIGGER ")
}

DATA_CHECKS = (
    (
        "I10A_VERIFY_INTENT_SHAPE",
        f"""SELECT COUNT(*) FROM {INTENT_TABLE}
            WHERE typeof(id) <> 'integer' OR id < 1
               OR typeof(contract_version) <> 'integer' OR contract_version <> 1
               OR typeof(order_id) <> 'integer' OR order_id < 1
               OR typeof(shop_id) <> 'integer' OR shop_id < 1
               OR typeof(expected_vnd) <> 'integer'
               OR expected_vnd <= 0 OR expected_vnd > {MAX_SAFE_VND}
               OR NOT {_canonical_reference_predicate('canonical_reference')}
               OR NOT {_identifier_predicate('bank_code', maximum=32)}
               OR NOT {_identifier_predicate('account_no', maximum=64)}
               OR NOT {_bounded_text_predicate('account_name', maximum_chars=200, maximum_bytes=600)}
               OR NOT {_identifier_predicate('adapter_profile_id', maximum=64)}""",
    ),
    (
        "I10A_VERIFY_INTENT_TIME",
        f"""SELECT COUNT(*) FROM {INTENT_TABLE}
            WHERE NOT {_canonical_time_predicate('issued_at')}
               OR NOT {_canonical_time_predicate('display_expires_at', nullable=True)}
               OR NOT {_canonical_time_predicate('cancel_after', nullable=True)}
               OR (display_expires_at IS NOT NULL AND display_expires_at < issued_at)
               OR (cancel_after IS NOT NULL AND cancel_after < issued_at)
               OR (display_expires_at IS NOT NULL AND cancel_after IS NOT NULL
                   AND cancel_after < display_expires_at)""",
    ),
    (
        "I10A_VERIFY_INTENT_ORDER",
        f"""SELECT COUNT(*) FROM {INTENT_TABLE} i
            LEFT JOIN orders o ON o.id = i.order_id
            LEFT JOIN shops s ON s.id = i.shop_id
            WHERE o.id IS NULL OR s.id IS NULL
               OR o.shop_id IS NOT i.shop_id
               OR o.payment_method IS NOT 'transfer'
               OR typeof(o.total_vnd) <> 'integer' OR o.total_vnd <= 0
               OR o.total_vnd IS NOT i.expected_vnd
               OR o.offline_uuid IS NOT NULL""",
    ),
    (
        "I10A_VERIFY_EVENT_SHAPE",
        f"""SELECT COUNT(*) FROM {EVENT_TABLE}
            WHERE typeof(id) <> 'integer' OR id < 1
               OR NOT {_identifier_predicate('provider', maximum=32)}
               OR NOT {_bounded_text_predicate('provider_event_id', maximum_chars=128, maximum_bytes=384, nullable=True)}
               OR NOT ({_lower_hex_digest_predicate('idempotency_key')})
               OR NOT {_identifier_predicate('normalized_account_no', maximum=64, nullable=True)}
               OR direction NOT IN ('IN', 'OUT', 'UNKNOWN')
               OR (amount_vnd IS NOT NULL AND (
                    typeof(amount_vnd) <> 'integer' OR amount_vnd < 0
                    OR amount_vnd > {MAX_SAFE_VND}))
               OR reference_state NOT IN (
                    'EXACT', 'MISSING', 'TRUNCATED', 'MULTIPLE', 'INVALID')
               OR NOT {_canonical_reference_predicate('normalized_reference', nullable=True)}
               OR ((reference_state IN ('EXACT', 'TRUNCATED'))
                   <> (normalized_reference IS NOT NULL))
               OR NOT ({_lower_hex_digest_predicate('normalized_sha256')})
               OR NOT ({_lower_hex_digest_predicate('envelope_sha256')})
               OR disposition NOT IN (
                    'UNAPPLIED', 'APPLIED', 'REJECTED_NOT_OURS', 'REFUNDED')
               OR NOT {_code_predicate('reason_code')}
               OR typeof(state_version) <> 'integer'
               OR state_version < 0 OR state_version > {MAX_STATE_VERSION}""",
    ),
    (
        "I10A_VERIFY_EVENT_TIME",
        f"""SELECT COUNT(*) FROM {EVENT_TABLE}
            WHERE NOT {_canonical_time_predicate('received_at')}
               OR NOT {_canonical_time_predicate('updated_at')}
               OR updated_at < received_at""",
    ),
    (
        "I10A_VERIFY_EVENT_LINKS",
        f"""SELECT COUNT(*) FROM {EVENT_TABLE} e
            LEFT JOIN shops s ON s.id = e.shop_id
            LEFT JOIN orders o ON o.id = e.order_id
            LEFT JOIN qr_payment_intents i ON i.id = e.intent_id
            LEFT JOIN order_payments p ON p.id = e.payment_id
            WHERE (e.shop_id IS NOT NULL AND s.id IS NULL)
               OR (e.order_id IS NOT NULL
                   AND (e.shop_id IS NULL OR o.id IS NULL
                        OR o.shop_id IS NOT e.shop_id
                        OR o.payment_method IS NOT 'transfer'
                        OR typeof(o.total_vnd) <> 'integer' OR o.total_vnd <= 0
                        OR o.offline_uuid IS NOT NULL))
               OR (e.intent_id IS NOT NULL
                   AND (e.order_id IS NULL OR e.shop_id IS NULL OR i.id IS NULL
                        OR i.order_id IS NOT e.order_id
                        OR i.shop_id IS NOT e.shop_id))
               OR (e.payment_id IS NOT NULL
                   AND (e.order_id IS NULL OR p.id IS NULL
                        OR p.order_id IS NOT e.order_id))
               OR (e.disposition = 'APPLIED'
                   AND (e.payment_id IS NULL OR e.direction <> 'IN'
                        OR typeof(e.amount_vnd) <> 'integer' OR e.amount_vnd <= 0))
               OR (e.disposition <> 'APPLIED' AND e.payment_id IS NOT NULL)""",
    ),
    (
        "I10A_VERIFY_APPLIED_PAYMENT",
        f"""SELECT COUNT(*) FROM {EVENT_TABLE} e
            JOIN order_payments p ON p.id = e.payment_id
            WHERE e.disposition = 'APPLIED'
              AND (p.order_id IS NOT e.order_id
                   OR p.entry_type IS NOT 'BANK_IN'
                   OR typeof(p.amount_vnd) <> 'integer'
                   OR p.amount_vnd IS NOT e.amount_vnd
                   OR p.idempotency_key IS NOT e.idempotency_key
                   OR p.provider IS NOT e.provider
                   OR p.bank_txn_id IS NOT e.provider_event_id
                   OR p.account_no IS NOT e.normalized_account_no)""",
    ),
    (
        "I10A_VERIFY_ACTION_SHAPE",
        f"""SELECT COUNT(*) FROM {ACTION_TABLE}
            WHERE typeof(id) <> 'integer' OR id < 1
               OR typeof(event_id) <> 'integer' OR event_id < 1
               OR typeof(event_state_version) <> 'integer'
               OR event_state_version < 0
               OR event_state_version > {MAX_STATE_VERSION}
               OR action_kind NOT IN (
                    'KEEP_OPEN', 'MAP_AND_APPLY',
                    'REJECT_NOT_OURS', 'MARK_REFUNDED_EXTERNALLY')
               OR actor_role NOT IN ('ADMIN', 'OWNER', 'MANAGER')
               OR typeof(performed_by_user_id) <> 'integer'
               OR performed_by_user_id < 1
               OR (shop_id IS NULL AND actor_role <> 'ADMIN')
               OR (action_kind = 'MAP_AND_APPLY') <> (payment_id IS NOT NULL)
               OR (action_kind IN ('REJECT_NOT_OURS', 'MARK_REFUNDED_EXTERNALLY')
                   AND NOT {_bounded_text_predicate('note', maximum_chars=500, maximum_bytes=1500)})
               OR (note IS NOT NULL
                   AND NOT {_bounded_text_predicate('note', maximum_chars=500, maximum_bytes=1500)})
               OR NOT {_canonical_time_predicate('performed_at')}
               OR typeof(system_log_id) <> 'integer' OR system_log_id < 1""",
    ),
    (
        "I10A_VERIFY_ACTION_SCOPE_AUDIT",
        f"""SELECT COUNT(*) FROM {ACTION_TABLE} a
            LEFT JOIN bank_webhook_events e ON e.id = a.event_id
            LEFT JOIN shops s ON s.id = a.shop_id
            LEFT JOIN orders o ON o.id = a.order_id
            LEFT JOIN qr_payment_intents i ON i.id = a.intent_id
            LEFT JOIN order_payments p ON p.id = a.payment_id
            LEFT JOIN users u ON u.id = a.performed_by_user_id
            LEFT JOIN system_logs sl ON sl.id = a.system_log_id
            WHERE e.id IS NULL OR u.id IS NULL OR sl.id IS NULL
               OR sl.user_id IS NOT a.performed_by_user_id
               OR sl.shop_id IS NOT a.shop_id
               OR sl.action IS NOT 'BANK_RECONCILIATION'
               OR typeof(sl.details) <> 'text'
               OR length(trim(sl.details)) NOT BETWEEN 1 AND 1500
               OR length(CAST(sl.details AS BLOB)) > 4500
               OR instr(sl.details, char(0)) <> 0
               OR sl.created_at IS NOT a.performed_at
               OR a.performed_at < e.updated_at
               OR (a.shop_id IS NOT NULL AND s.id IS NULL)
               OR (a.order_id IS NOT NULL
                   AND (a.shop_id IS NULL OR o.id IS NULL
                        OR o.shop_id IS NOT a.shop_id
                        OR o.payment_method IS NOT 'transfer'
                        OR typeof(o.total_vnd) <> 'integer' OR o.total_vnd <= 0
                        OR o.offline_uuid IS NOT NULL))
               OR (a.intent_id IS NOT NULL
                   AND (a.order_id IS NULL OR a.shop_id IS NULL OR i.id IS NULL
                        OR i.order_id IS NOT a.order_id
                        OR i.shop_id IS NOT a.shop_id))
               OR (a.payment_id IS NOT NULL
                   AND (a.order_id IS NULL OR p.id IS NULL
                        OR p.order_id IS NOT a.order_id))""",
    ),
    (
        "I10A_VERIFY_TERMINAL_ACTION",
        f"""SELECT
             (SELECT COUNT(*) FROM {ACTION_TABLE} a
              LEFT JOIN {EVENT_TABLE} e ON e.id = a.event_id
              WHERE a.action_kind <> 'KEEP_OPEN'
                AND (e.id IS NULL OR a.event_state_version IS NOT e.state_version
                     OR a.intent_id IS NOT e.intent_id
                     OR a.order_id IS NOT e.order_id
                     OR a.shop_id IS NOT e.shop_id
                     OR a.payment_id IS NOT e.payment_id
                     OR (a.action_kind = 'MAP_AND_APPLY'
                         AND (e.disposition <> 'APPLIED'
                              OR e.reason_code <> 'MAP_AND_APPLY'))
                     OR (a.action_kind = 'REJECT_NOT_OURS'
                         AND (e.disposition <> 'REJECTED_NOT_OURS'
                              OR e.reason_code <> 'REJECT_NOT_OURS'))
                     OR (a.action_kind = 'MARK_REFUNDED_EXTERNALLY'
                         AND (e.disposition <> 'REFUNDED'
                              OR e.reason_code <> 'MARK_REFUNDED_EXTERNALLY'))))
            + (SELECT COUNT(*) FROM {ACTION_TABLE} a
               JOIN {EVENT_TABLE} e ON e.id = a.event_id
               WHERE a.action_kind = 'KEEP_OPEN'
                 AND a.event_state_version > e.state_version)
            + (SELECT COUNT(*) FROM {EVENT_TABLE} e
               WHERE e.disposition = 'APPLIED'
                 AND (SELECT COUNT(*) FROM {ACTION_TABLE} a
                      WHERE a.event_id = e.id
                        AND a.action_kind = 'MAP_AND_APPLY') <> 1)
            + (SELECT COUNT(*) FROM {EVENT_TABLE} e
               WHERE e.disposition = 'REJECTED_NOT_OURS'
                 AND (SELECT COUNT(*) FROM {ACTION_TABLE} a
                      WHERE a.event_id = e.id
                        AND a.action_kind = 'REJECT_NOT_OURS') <> 1)
            + (SELECT COUNT(*) FROM {EVENT_TABLE} e
               WHERE e.disposition = 'REFUNDED'
                 AND (SELECT COUNT(*) FROM {ACTION_TABLE} a
                      WHERE a.event_id = e.id
                        AND a.action_kind = 'MARK_REFUNDED_EXTERNALLY') <> 1)""",
    ),
)


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def _normalize_sql(value):
    """Normalize SQL syntax while preserving case/space inside literals."""
    result = []
    quote = None
    pending_space = False
    index = 0
    sql = str(value).strip().rstrip(";")
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            result.append(character)
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    result.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif character in ("'", '"'):
            if pending_space and result:
                result.append(" ")
            pending_space = False
            quote = character
            result.append(character)
        elif character.isspace():
            pending_space = True
        else:
            if pending_space and result:
                result.append(" ")
            pending_space = False
            result.append(character.lower())
        index += 1
    return "".join(result).strip()


def _named_check_clauses(value):
    """Return exact normalized named CHECK clauses from SQLite CREATE SQL."""
    sql = _normalize_sql(value)
    result = {}
    cursor = 0
    marker = "constraint "
    while True:
        start = sql.find(marker, cursor)
        if start < 0:
            return result
        name_start = start + len(marker)
        name_end = sql.find(" ", name_start)
        if name_end < 0:
            return result
        next_constraint = sql.find(marker, name_end)
        check_start = sql.find("check (", name_end)
        if check_start < 0 or (
            next_constraint >= 0 and next_constraint < check_start
        ):
            cursor = name_end
            continue

        opening = check_start + len("check ")
        depth = 0
        quote = None
        index = opening
        while index < len(sql):
            character = sql[index]
            if quote is not None:
                if character == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 1
                    else:
                        quote = None
            elif character in ("'", '"'):
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    name = sql[name_start:name_end]
                    result[name] = sql[start:index + 1]
                    cursor = index + 1
                    break
            index += 1
        else:
            return result


def _table_clauses(value):
    """Split normalized CREATE TABLE SQL at top-level definition commas."""
    sql = _normalize_sql(value)
    opening = sql.find("(")
    if opening < 0:
        return ()
    clauses = []
    start = opening + 1
    depth = 1
    quote = None
    index = start
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in ("'", '"'):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                clause = sql[start:index].strip()
                if clause:
                    clauses.append(clause)
                return tuple(clauses)
        elif character == "," and depth == 1:
            clauses.append(sql[start:index].strip())
            start = index + 1
        index += 1
    return ()


def _foreign_key_shape(execute, table):
    grouped = {}
    for row in execute("PRAGMA foreign_key_list('" + table + "')").fetchall():
        key = int(row[0])
        item = grouped.setdefault(
            key,
            {
                "table": str(row[2]),
                "pairs": [],
                "on_update": str(row[5]),
                "on_delete": str(row[6]),
                "match": str(row[7]),
            },
        )
        item["pairs"].append((int(row[1]), str(row[3]), str(row[4])))
    result = set()
    for item in grouped.values():
        pairs = tuple(
            (source, target)
            for _sequence, source, target in sorted(item["pairs"])
        )
        result.add(
            (
                item["table"],
                pairs,
                item["on_update"],
                item["on_delete"],
                item["match"],
            )
        )
    return result


def _index_shapes(execute):
    rows = execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'"
    ).fetchall()
    result = {}
    for name, table, sql in rows:
        if str(name).startswith("sqlite_autoindex_"):
            continue
        quoted = "\"" + str(name).replace("\"", "\"\"") + "\""
        index_row = next(
            row
            for row in execute("PRAGMA index_list('" + str(table) + "')").fetchall()
            if row[1] == name
        )
        xinfo = tuple(
            (
                int(row[0]),
                int(row[1]),
                None if row[2] is None else str(row[2]),
                int(row[3]),
                str(row[4]),
                int(row[5]),
            )
            for row in sorted(
                execute("PRAGMA index_xinfo(" + quoted + ")").fetchall(),
                key=lambda row: int(row[0]),
            )
        )
        normalized = _normalize_sql(sql) if sql is not None else ""
        marker = " where "
        predicate = None
        if marker in normalized:
            predicate = "".join(normalized.split(marker, 1)[1].split())
        result[str(name)] = (
            str(table),
            int(index_row[2]),
            xinfo,
            int(index_row[4]),
            predicate,
            normalized,
        )
    return result


def upgrade():
    # DDL only. There is intentionally no SELECT-driven synthesis/backfill.
    for statement in DDL:
        _execute(statement)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    rows = execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    objects = {(str(kind), str(name)): (str(table), sql) for kind, name, table, sql in rows}

    # A later linear revision may append columns/constraints, but it may not
    # rewrite or weaken any 0007-owned column, named CHECK or FK. SQLite inserts
    # ADD COLUMN text before table constraints, so raw CREATE-SQL prefixes are
    # intentionally not used here.
    for table, expected_sql in EXPECTED_TABLE_PREFIXES.items():
        actual = objects.get(("table", table))
        if actual is None:
            raise RuntimeError("I10A_VERIFY_SCHEMA_OBJECTS:" + table)

        actual_columns = tuple(
            (str(row[1]), str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
            for row in execute("PRAGMA table_info('" + table + "')").fetchall()
        )
        expected_columns = EXPECTED_COLUMNS[table]
        if actual_columns[: len(expected_columns)] != expected_columns:
            raise RuntimeError("I10A_VERIFY_SCHEMA_COLUMNS:" + table)
        expected_clauses = _table_clauses(expected_sql)
        actual_clauses = _table_clauses(actual[1])
        if not expected_clauses or any(
            actual_clauses.count(clause) < expected_clauses.count(clause)
            for clause in expected_clauses
        ):
            raise RuntimeError("I10A_VERIFY_SCHEMA_TABLE:" + table)
        expected_checks = _named_check_clauses(expected_sql)
        actual_checks = _named_check_clauses(actual[1])
        if any(
            actual_checks.get(name) != clause
            for name, clause in expected_checks.items()
        ):
            raise RuntimeError("I10A_VERIFY_SCHEMA_TABLE:" + table)
        if not EXPECTED_FOREIGN_KEYS[table].issubset(_foreign_key_shape(execute, table)):
            raise RuntimeError("I10A_VERIFY_SCHEMA_FKS:" + table)

    indexes = _index_shapes(execute)
    for name, expected in EXPECTED_INDEXES.items():
        table, unique, columns, partial, predicate = expected
        column_positions = {
            str(row[1]): int(row[0])
            for row in execute("PRAGMA table_info('" + table + "')").fetchall()
        }
        expected_xinfo = tuple(
            (sequence, column_positions[column], column, 0, "BINARY", 1)
            for sequence, column in enumerate(columns)
        ) + ((len(columns), -1, None, 0, "BINARY", 0),)
        expected_shape = (
            table,
            unique,
            expected_xinfo,
            partial,
            predicate,
            _normalize_sql(EXPECTED_INDEX_SQL[name]),
        )
        if indexes.get(name) != expected_shape:
            raise RuntimeError("I10A_VERIFY_SCHEMA_INDEX:" + name)

    for name, expected_sql in EXPECTED_TRIGGER_SQL.items():
        actual = objects.get(("trigger", name))
        if actual is None or _normalize_sql(actual[1]) != _normalize_sql(expected_sql):
            raise RuntimeError("I10A_VERIFY_SCHEMA_TRIGGER:" + name)

    for code, statement in DATA_CHECKS:
        if execute(statement).fetchone()[0]:
            raise RuntimeError(code)


def downgrade():
    raise RuntimeError("F-Selling I10-A migrations are forward-only")
