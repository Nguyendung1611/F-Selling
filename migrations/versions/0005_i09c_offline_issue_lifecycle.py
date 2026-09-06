"""I09-C durable offline issue lifecycle: deficit/issue guards and legacy backfill.

Revision 0004 released the tables but no guard and no rows.  Its source and
checksum are immutable, so every missing invariant arrives here instead.

Three things happen, in this order and inside the coordinator's one
BEGIN IMMEDIATE:

1. Triggers make `offline_stock_deficits` and `offline_receipt_issues` durable:
   a deficit is born open and may only shrink, an issue may only move forward,
   and neither table can be deleted from.  CHECK constraints alone are not a
   guard - `PRAGMA ignore_check_constraints`, a restored backup or a legacy
   writer all get past them.
2. `orders.offline_issue` - a comma-joined string that cannot say which line or
   how much is still missing - is backfilled once into real issue rows.
3. `verify()` re-derives every new invariant from row counts, independently of
   the CHECKs and triggers above, and never looks at the clock.
"""

from alembic import op

revision = "0005_i09c_offline_issue_lifecycle"
down_revision = "0004_i09_offline_receipts"
branch_labels = None
depends_on = None

MAX_SAFE_QUANTITY = 1000000000

# Same fixed-width UTC-naive shape 0004 pinned.  Re-declared instead of imported
# because a released revision may not depend on another module.
CANONICAL_TIME_GLOB = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] "
    "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
    "[0-9][0-9][0-9][0-9][0-9][0-9]"
)

# Every legacy code that may appear in `orders.offline_issue`.  Anything else
# blocks the migration: silently dropping an unknown code throws away the only
# record that something went wrong with real money.
ISSUE_TON_AM = "TON_AM"
ISSUE_CA_DA_CHOT = "CA_DA_CHOT"
ISSUE_KHONG_CO_CA = "KHONG_CO_CA"
ISSUE_SP_KHONG_CON = "SP_KHONG_CON"
ISSUE_GIA_DOI = "GIA_DOI"
KNOWN_ISSUE_CODES = (
    ISSUE_TON_AM,
    ISSUE_CA_DA_CHOT,
    ISSUE_KHONG_CO_CA,
    ISSUE_SP_KHONG_CON,
    ISSUE_GIA_DOI,
)


def _canonical_time_predicate(column, *, nullable=False):
    shape = (
        "typeof(" + column + ") = 'text' AND length(" + column + ") = 26 "
        "AND " + column + " GLOB '" + CANONICAL_TIME_GLOB + "'"
    )
    if nullable:
        return "(" + column + " IS NULL OR (" + shape + "))"
    return "(" + column + " IS NOT NULL AND " + shape + ")"


# `IS` and not `=` everywhere a nullable column is compared to a literal: a WHEN
# clause that evaluates to NULL does NOT fire the trigger, so a single `=` on a
# NULL column would silently open the exact hole the trigger exists to close.
_DEFICIT_UPDATE_IS_LEGAL = (
    "NEW.order_item_id = OLD.order_item_id"
    " AND NEW.product_id = OLD.product_id"
    " AND NEW.deficit_quantity = OLD.deficit_quantity"
    # The row must have been open. A closed row is history, not state.
    " AND OLD.remaining_quantity > 0"
    " AND OLD.resolution_kind IS NULL AND OLD.resolved_by_user_id IS NULL"
    " AND OLD.resolved_at IS NULL AND OLD.resolution_reason IS NULL"
    # Strictly shrinking: no reopen, no top-up, no silent no-op bump.
    " AND NEW.remaining_quantity >= 0"
    " AND NEW.remaining_quantity < OLD.remaining_quantity"
    " AND NEW.state_version = OLD.state_version + 1"
    " AND ("
    "  (NEW.remaining_quantity > 0 AND NEW.resolution_kind IS NULL"
    "   AND NEW.resolved_by_user_id IS NULL AND NEW.resolved_at IS NULL"
    "   AND NEW.resolution_reason IS NULL)"
    "  OR (NEW.remaining_quantity = 0 AND NEW.resolution_kind IS 'STOCKTAKE'"
    "      AND NEW.resolved_by_user_id IS NOT NULL"
    "      AND " + _canonical_time_predicate("NEW.resolved_at") + ")"
    " )"
)

_ISSUE_UPDATE_IS_LEGAL = (
    # Scope and evidence are what the row IS; only its state may move.
    "NEW.order_id = OLD.order_id"
    " AND NEW.order_item_id IS OLD.order_item_id"
    " AND NEW.product_id IS OLD.product_id"
    " AND NEW.issue_code = OLD.issue_code"
    " AND NEW.evidence_kind = OLD.evidence_kind"
    " AND NEW.evidence_id IS OLD.evidence_id"
    " AND NEW.severity = OLD.severity"
    " AND NEW.opened_at = OLD.opened_at"
    " AND NEW.state_version = OLD.state_version + 1"
    # ACKNOWLEDGED is kept reachable so I09-G recovery still has a road.
    " AND ("
    "  (OLD.state = 'OPEN' AND NEW.state = 'ACKNOWLEDGED')"
    "  OR (OLD.state = 'OPEN' AND NEW.state = 'RESOLVED')"
    "  OR (OLD.state = 'ACKNOWLEDGED' AND NEW.state = 'RESOLVED')"
    " )"
    " AND ("
    "  (NEW.state = 'ACKNOWLEDGED' AND NEW.reason IS NOT NULL"
    "   AND length(trim(NEW.reason)) > 0 AND NEW.resolution_kind IS NULL)"
    "  OR (NEW.state = 'RESOLVED' AND NEW.resolution_kind IS NOT NULL"
    "      AND length(trim(NEW.resolution_kind)) > 0)"
    " )"
)

DDL = (
    # ------------------------------------------------- exact non-batch deficit
    "CREATE TRIGGER trg_i09c_offline_stock_deficit_insert"
    " BEFORE INSERT ON offline_stock_deficits FOR EACH ROW"
    " WHEN NEW.state_version <> 0"
    "   OR NEW.remaining_quantity <> NEW.deficit_quantity"
    "   OR NEW.resolution_kind IS NOT NULL"
    "   OR NEW.resolved_by_user_id IS NOT NULL"
    "   OR NEW.resolved_at IS NOT NULL"
    "   OR NEW.resolution_reason IS NOT NULL"
    " BEGIN SELECT RAISE(ABORT, 'I09C_OFFLINE_DEFICIT_INSERT_NOT_OPEN'); END",
    "CREATE TRIGGER trg_i09c_offline_stock_deficit_update"
    " BEFORE UPDATE ON offline_stock_deficits FOR EACH ROW"
    " WHEN NOT (" + _DEFICIT_UPDATE_IS_LEGAL + ")"
    " BEGIN SELECT RAISE(ABORT, 'I09C_OFFLINE_DEFICIT_IMMUTABLE'); END",
    "CREATE TRIGGER trg_i09c_offline_stock_deficit_delete"
    " BEFORE DELETE ON offline_stock_deficits FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I09C_OFFLINE_DEFICIT_IMMUTABLE'); END",
    # ----------------------------------------------------------- issue records
    # An issue may be born OPEN, or born RESOLVED when it is purely
    # informational.  It may never be born ACKNOWLEDGED: an acknowledgement is
    # somebody taking responsibility, so it has to be an audited transition.
    "CREATE TRIGGER trg_i09c_offline_issue_insert"
    " BEFORE INSERT ON offline_receipt_issues FOR EACH ROW"
    " WHEN NEW.state_version <> 0"
    "   OR NEW.state NOT IN ('OPEN', 'RESOLVED')"
    "   OR (NEW.state = 'RESOLVED'"
    "       AND (NEW.resolution_kind IS NULL"
    "            OR length(trim(NEW.resolution_kind)) = 0))"
    " BEGIN SELECT RAISE(ABORT, 'I09C_OFFLINE_ISSUE_INSERT_INVALID'); END",
    "CREATE TRIGGER trg_i09c_offline_issue_update"
    " BEFORE UPDATE ON offline_receipt_issues FOR EACH ROW"
    " WHEN NOT (" + _ISSUE_UPDATE_IS_LEGAL + ")"
    " BEGIN SELECT RAISE(ABORT, 'I09C_OFFLINE_ISSUE_TRANSITION'); END",
    "CREATE TRIGGER trg_i09c_offline_issue_delete"
    " BEFORE DELETE ON offline_receipt_issues FOR EACH ROW"
    " BEGIN SELECT RAISE(ABORT, 'I09C_OFFLINE_ISSUE_IMMUTABLE'); END",
)

EXPECTED_TRIGGERS_0005 = (
    "trg_i09c_offline_stock_deficit_insert",
    "trg_i09c_offline_stock_deficit_update",
    "trg_i09c_offline_stock_deficit_delete",
    "trg_i09c_offline_issue_insert",
    "trg_i09c_offline_issue_update",
    "trg_i09c_offline_issue_delete",
)

# `orders.offline_issue` stays a compatibility/history mirror, so it has to keep
# agreeing with the issue table in BOTH directions.  `instr` and not `LIKE`:
# every code contains `_`, which LIKE would treat as a wildcard.
_MIRROR = "(',' || REPLACE(COALESCE(o.offline_issue, ''), ' ', '') || ',')"

# Split the mirror on commas instead of naming the codes.  `KNOWN_ISSUE_CODES`
# is the vocabulary of LEGACY data and must never become the vocabulary of the
# persistent verifier: a later slice that introduces its own durable issue kind
# would otherwise be unable to satisfy both directions at once - with no mirror
# token HAS_EVERY_ISSUE fails, with one an allow-list check fails.
#
# The seed appends a trailing comma, so each step consumes through exactly one
# comma and the remainder always ends in a comma or is empty.  That is what
# makes the recursion terminate.
_MIRROR_TOKENS = """
    WITH RECURSIVE mirror_token(order_id, token, rest) AS (
        SELECT o.id, '',
               REPLACE(COALESCE(o.offline_issue, ''), ' ', '') || ','
          FROM orders o
         WHERE o.offline_issue IS NOT NULL AND trim(o.offline_issue) <> ''
        UNION ALL
        SELECT order_id,
               substr(rest, 1, instr(rest, ',') - 1),
               substr(rest, instr(rest, ',') + 1)
          FROM mirror_token
         WHERE rest <> ''
    )
"""

DATA_CHECKS = (
    (
        # Ranges and shape, revalidated without trusting the declared CHECKs.
        "I09C_VERIFY_DEFICIT_SHAPE",
        """SELECT COUNT(*) FROM offline_stock_deficits
           WHERE typeof(id) <> 'integer'
              OR typeof(order_item_id) <> 'integer'
              OR typeof(product_id) <> 'integer'
              OR typeof(deficit_quantity) <> 'integer'
              OR typeof(remaining_quantity) <> 'integer'
              OR typeof(state_version) <> 'integer'
              OR deficit_quantity <= 0
              OR deficit_quantity > """ + str(MAX_SAFE_QUANTITY) + """
              OR remaining_quantity < 0
              OR remaining_quantity > deficit_quantity
              OR state_version < 0""",
    ),
    (
        # Open means nobody has claimed a resolution yet; closed means a real
        # stocktake, a real actor and a canonical instant.
        "I09C_VERIFY_DEFICIT_RESOLUTION",
        """SELECT COUNT(*) FROM offline_stock_deficits d
           LEFT JOIN users u ON u.id = d.resolved_by_user_id
           WHERE (d.remaining_quantity > 0
                  AND (d.resolution_kind IS NOT NULL
                       OR d.resolved_by_user_id IS NOT NULL
                       OR d.resolved_at IS NOT NULL
                       OR d.resolution_reason IS NOT NULL))
              OR (d.remaining_quantity = 0
                  AND (d.resolution_kind IS NOT 'STOCKTAKE'
                       OR d.resolved_by_user_id IS NULL OR u.id IS NULL
                       OR NOT """ + _canonical_time_predicate("d.resolved_at") + """))""",
    ),
    (
        # Every legal update drops `remaining` by at least one and raises
        # `state_version` by exactly one.  A reduction that skipped the version
        # bump - a trigger bypass or a restored corruption - breaks this.
        "I09C_VERIFY_DEFICIT_VERSION_TRAIL",
        """SELECT COUNT(*) FROM offline_stock_deficits
           WHERE state_version > deficit_quantity - remaining_quantity
              OR (remaining_quantity < deficit_quantity AND state_version < 1)
              OR (remaining_quantity = deficit_quantity AND state_version <> 0)""",
    ),
    (
        "I09C_VERIFY_DEFICIT_SCOPE",
        """SELECT COUNT(*) FROM offline_stock_deficits d
           LEFT JOIN order_items i ON i.id = d.order_item_id
           LEFT JOIN products p ON p.id = d.product_id
           WHERE i.id IS NULL OR p.id IS NULL
              OR i.product_id IS NOT d.product_id
              OR NOT EXISTS (SELECT 1 FROM offline_receipts r
                             WHERE r.order_id = i.order_id)""",
    ),
    (
        "I09C_VERIFY_ISSUE_LIFECYCLE",
        """SELECT COUNT(*) FROM offline_receipt_issues
           WHERE (state = 'ACKNOWLEDGED'
                  AND (reason IS NULL OR length(trim(reason)) = 0
                       OR resolution_kind IS NOT NULL
                       OR state_version < 1))
              OR (state = 'RESOLVED'
                  AND (resolution_kind IS NULL
                       OR length(trim(resolution_kind)) = 0))
              OR (state = 'OPEN' AND resolution_kind IS NOT NULL)""",
    ),
    (
        # An issue that points at exact evidence is resolved exactly when that
        # evidence is exhausted - never because somebody clicked a button.
        "I09C_VERIFY_ISSUE_EVIDENCE_STATE",
        """SELECT COUNT(*) FROM offline_receipt_issues s
           LEFT JOIN offline_stock_deficits d
                  ON d.id = s.evidence_id
                 AND s.evidence_kind = 'OFFLINE_STOCK_DEFICIT'
           LEFT JOIN offline_batch_stock_deficits b
                  ON b.id = s.evidence_id
                 AND s.evidence_kind = 'OFFLINE_BATCH_DEFICIT'
           WHERE (s.evidence_kind = 'OFFLINE_STOCK_DEFICIT'
                  AND (d.id IS NULL
                       OR s.issue_code <> 'TON_AM'
                       OR s.state = 'ACKNOWLEDGED'
                       OR (s.state = 'RESOLVED') <> (d.remaining_quantity = 0)))
              OR (s.evidence_kind = 'OFFLINE_BATCH_DEFICIT'
                  AND (b.id IS NULL
                       OR s.issue_code <> 'TON_AM'
                       OR s.state = 'ACKNOWLEDGED'
                       OR (s.state = 'RESOLVED') <> (b.remaining_quantity = 0)))""",
    ),
    (
        "I09C_VERIFY_MIRROR_HAS_EVERY_ISSUE",
        """SELECT COUNT(*) FROM offline_receipt_issues s
           JOIN orders o ON o.id = s.order_id
           WHERE instr(""" + _MIRROR + """, ',' || s.issue_code || ',') = 0""",
    ),
    (
        # Generic over the code vocabulary: a token nobody carries is an orphan
        # whether it is a legacy code, a typo or a kind invented next quarter.
        "I09C_VERIFY_MIRROR_HAS_NO_ORPHAN_CODE",
        _MIRROR_TOKENS + """
        SELECT COUNT(*) FROM mirror_token t
         WHERE t.token <> ''
           AND NOT EXISTS (SELECT 1 FROM offline_receipt_issues s
                           WHERE s.order_id = t.order_id
                             AND s.issue_code = t.token)""",
    ),
    (
        # Every exact shortfall must be somebody's job.  Without this an
        # `offline_stock_deficits` row can exist with no issue at all: goods
        # really went missing and the Đối Soát screen never says so.
        "I09C_VERIFY_EVIDENCE_HAS_ISSUE",
        """SELECT
             (SELECT COUNT(*) FROM offline_stock_deficits d
               JOIN order_items i ON i.id = d.order_item_id
              WHERE (SELECT COUNT(*) FROM offline_receipt_issues s
                      WHERE s.evidence_kind = 'OFFLINE_STOCK_DEFICIT'
                        AND s.evidence_id = d.id
                        AND s.issue_code = 'TON_AM'
                        AND s.order_id = i.order_id
                        AND s.order_item_id IS d.order_item_id
                        AND s.product_id IS d.product_id) <> 1)
           + (SELECT COUNT(*) FROM offline_batch_stock_deficits b
               JOIN order_items i ON i.id = b.order_item_id
              WHERE (SELECT COUNT(*) FROM offline_receipt_issues s
                      WHERE s.evidence_kind = 'OFFLINE_BATCH_DEFICIT'
                        AND s.evidence_id = b.id
                        AND s.issue_code = 'TON_AM'
                        AND s.order_id = i.order_id
                        AND s.order_item_id IS b.order_item_id
                        AND s.product_id IS b.product_id) <> 1)""",
    ),
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


def _rows(connection, statement, parameters=None):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    if parameters is None:
        return execute(statement).fetchall()
    return execute(statement, parameters).fetchall()


def _fail(code):
    """Stable, non-PII migration error. Never echoes a row value."""
    raise RuntimeError("I09C_BACKFILL_" + code + ":orders.offline_issue")


def _canonical_time(value):
    """Normalize a legacy SQLite datetime string to the canonical 26-char shape.

    Three shapes appear in real data and all three are widened, never guessed:
    SQLAlchemy drops `.ffffff` on a whole second, a short fraction is stored
    unpadded, and older rows kept only the date.  `opened_at` is NOT NULL in
    0004, so a date-only value becomes that day's midnight - the one instant the
    stored value denotes.  It is administrative metadata about when a problem
    was recorded, never a money fact.

    Anything else blocks the migration rather than inventing an instant.
    """
    if not isinstance(value, str):
        _fail("UNUSABLE_ORDER_TIME")
    text = value.strip()
    # ISO-8601 with a `T` separator is the same instant written differently.
    if len(text) > 10 and text[10] == "T":
        text = text[:10] + " " + text[11:]
    if len(text) == 10:
        text = text + " 00:00:00.000000"
    elif len(text) == 19:
        text = text + ".000000"
    elif len(text) > 20 and text[19] == ".":
        digits = text[20:]
        if not digits.isdigit() or len(digits) > 6:
            _fail("UNUSABLE_ORDER_TIME")
        text = text[:20] + digits.ljust(6, "0")
    else:
        _fail("UNUSABLE_ORDER_TIME")
    date_part, _, time_part = text.partition(" ")
    if (
        len(text) != 26
        or len(date_part) != 10
        or date_part[4] != "-"
        or date_part[7] != "-"
        or not (date_part[:4] + date_part[5:7] + date_part[8:]).isdigit()
        or len(time_part) != 15
        or time_part[2] != ":"
        or time_part[5] != ":"
        or not (time_part[:2] + time_part[3:5] + time_part[6:8]).isdigit()
    ):
        _fail("UNUSABLE_ORDER_TIME")
    return text


def _parse_codes(raw):
    if raw is None:
        return []
    if not isinstance(raw, str):
        _fail("UNKNOWN_ISSUE_CODE")
    codes = []
    for part in raw.split(","):
        code = part.strip()
        if not code:
            continue
        if code not in KNOWN_ISSUE_CODES:
            _fail("UNKNOWN_ISSUE_CODE")
        if code not in codes:
            codes.append(code)
    return codes


def _plan_backfill(connection):
    """Decide every row before writing one, so a bad order blocks the whole run."""
    orders = _rows(
        connection,
        # The actor is the shop's own owner, else whoever recorded the sale, and
        # each must really exist.  Never an account picked from the rest of the
        # system: naming a stranger on a resolved row is a false statement about
        # who took responsibility for somebody else's money.
        """SELECT o.id, o.shop_id, o.offline_issue, o.sold_offline_at, o.created_at,
                  COALESCE(
                      (SELECT u.id FROM users u WHERE u.id = s.owner_id),
                      (SELECT u.id FROM users u WHERE u.id = o.created_by_user_id))
           FROM orders o
           LEFT JOIN shops s ON s.id = o.shop_id
           WHERE o.offline_issue IS NOT NULL AND trim(o.offline_issue) <> ''
           ORDER BY o.id""",
    )
    tracked_evidence = {}
    for evidence_id, item_id, product_id, remaining, order_id in _rows(
        connection,
        """SELECT d.id, d.order_item_id, d.product_id, d.remaining_quantity,
                  i.order_id
           FROM offline_batch_stock_deficits d
           JOIN order_items i ON i.id = d.order_item_id
           ORDER BY d.id""",
    ):
        tracked_evidence.setdefault(order_id, []).append(
            (evidence_id, item_id, product_id, remaining)
        )
    missing_products = {}
    for item_id, order_id in _rows(
        connection,
        """SELECT id, order_id FROM order_items
           WHERE product_id IS NULL ORDER BY id""",
    ):
        missing_products.setdefault(order_id, []).append(item_id)

    planned = []
    for order_id, shop_id, raw, sold_at, created_at, owner_id in orders:
        codes = _parse_codes(raw)
        if not codes:
            continue
        at = _canonical_time(sold_at if sold_at is not None else created_at)
        for code in codes:
            if code == ISSUE_GIA_DOI:
                # Today's `products.price` is not the price at sync time, so a
                # per-line claim here would be a guess. Order scope is honest.
                planned.append(
                    (order_id, None, None, code, "CATALOG", None, "INFO",
                     "RESOLVED", at, at, owner_id, "MIGRATION_INFORMATIONAL")
                )
            elif code in (ISSUE_CA_DA_CHOT, ISSUE_KHONG_CO_CA):
                planned.append(
                    (order_id, None, None, code, "SHIFT", None, "ACTION",
                     "OPEN", at, None, None, None)
                )
            elif code == ISSUE_SP_KHONG_CON:
                # `product_id IS NULL` is a checkable fact about the line, not
                # an inference, so this one keeps the same scope as ingest.
                items = missing_products.get(order_id, [])
                if items:
                    for item_id in items:
                        planned.append(
                            (order_id, item_id, None, code, "CATALOG", None,
                             "ACTION", "OPEN", at, None, None, None)
                        )
                else:
                    planned.append(
                        (order_id, None, None, code, "CATALOG", None, "ACTION",
                         "OPEN", at, None, None, None)
                    )
            else:
                evidence = tracked_evidence.get(order_id, [])
                if evidence:
                    for evidence_id, item_id, product_id, remaining in evidence:
                        if not isinstance(remaining, int) or isinstance(remaining, bool):
                            _fail("CORRUPT_TRACKED_EVIDENCE")
                        if remaining > 0:
                            planned.append(
                                (order_id, item_id, product_id, code,
                                 "OFFLINE_BATCH_DEFICIT", evidence_id, "ACTION",
                                 "OPEN", at, None, None, None)
                            )
                        else:
                            planned.append(
                                (order_id, item_id, product_id, code,
                                 "OFFLINE_BATCH_DEFICIT", evidence_id, "ACTION",
                                 "RESOLVED", at, at, owner_id,
                                 "MIGRATION_RECONCILED")
                            )
                else:
                    # Legacy non-batch shortfall. The only durable trace is the
                    # aggregate `products.cost_deficit_qty`, which cannot be
                    # attributed back to an order line - guessing an allocation
                    # from it would fabricate evidence about missing goods.
                    planned.append(
                        (order_id, None, None, code, "LEGACY_AMBIGUOUS", None,
                         "ACTION", "OPEN", at, None, None, None)
                    )

    for row in planned:
        if row[7] != "OPEN" and row[10] is None:
            # 0004 requires an actor on any non-OPEN issue.  The row already
            # says a MIGRATION_* kind closed it, so the actor names the
            # accountable principal rather than a human who clicked - but if
            # this shop has nobody accountable, nothing gets signed at all.
            _fail("NO_ACCOUNTABLE_ACTOR")
    return planned


def upgrade():
    connection = op.get_bind()
    planned = _plan_backfill(connection)
    for statement in DDL:
        _execute(statement)
    # Idempotence is decided on the FULL durable scope of
    # `ux_offline_receipt_issues_scope`, not on `(order_id, issue_code)`: an
    # order with several short lines carries several rows of the same code, and
    # a per-code skip would let one existing row hide every other missing scope -
    # a real shortfall that then never reaches the Đối Soát screen.
    already = {
        (order_id, issue_code, item_key, product_key): (
            evidence_kind, evidence_id, severity, state
        )
        for order_id, issue_code, item_key, product_key, evidence_kind,
        evidence_id, severity, state in _rows(
            connection,
            """SELECT order_id, issue_code, COALESCE(order_item_id, 0),
                      COALESCE(product_id, 0), evidence_kind, evidence_id,
                      severity, state
               FROM offline_receipt_issues""",
        )
    }
    for row in planned:
        (
            order_id, order_item_id, product_id, issue_code, evidence_kind,
            evidence_id, severity, state, opened_at, resolved_at,
            resolved_by_user_id, resolution_kind,
        ) = row
        scope = (order_id, issue_code, order_item_id or 0, product_id or 0)
        existing = already.get(scope)
        if existing is not None:
            if existing != (evidence_kind, evidence_id, severity, state):
                # The same durable scope already says something else about this
                # problem. Overwriting would erase one of the two claims and
                # inserting would break the unique index, so stop instead.
                _fail("SCOPE_CONFLICT")
            continue
        _execute_params(
            connection,
            """INSERT INTO offline_receipt_issues
               (order_id, order_item_id, product_id, issue_code, evidence_kind,
                evidence_id, severity, state, reason, opened_at, resolved_at,
                resolved_by_user_id, resolution_kind, state_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 0)""",
            (order_id, order_item_id, product_id, issue_code, evidence_kind,
             evidence_id, severity, state, opened_at, resolved_at,
             resolved_by_user_id, resolution_kind),
        )


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    names = {
        row[0]
        for row in execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing = set(EXPECTED_TRIGGERS_0005) - names
    if missing:
        raise RuntimeError("I09C_VERIFY_SCHEMA_OBJECTS:" + ",".join(sorted(missing)))
    for code, statement in DATA_CHECKS:
        if execute(statement).fetchone()[0]:
            raise RuntimeError(code)


def downgrade():
    raise RuntimeError("F-Selling I09 migrations are forward-only")
