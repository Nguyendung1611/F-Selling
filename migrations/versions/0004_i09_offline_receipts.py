"""I09-A offline receipt platform schema: lease, registry, receipt, evidence.

Schema only. Lease issuance, fingerprint canonicalization, ingest behaviour,
issue lifecycle, recovery and UI belong to I09-B and later; this revision must
be self-contained so a released migration never depends on mutable helpers.
"""

from alembic import op

revision = "0004_i09_offline_receipts"
down_revision = "0003_i05_integer_vnd_cost_basis"
branch_labels = None
depends_on = None

# Every 0004 time value uses one UTC-naive representation.  Lexicographic time
# comparisons below are meaningful only because every value has the same
# fixed-width `YYYY-MM-DD HH:MM:SS.ffffff` shape.  I09-B must convert aware
# values to UTC, drop tzinfo and serialize exactly six microseconds before bind.
CANONICAL_TIME_GLOB_0004 = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] "
    "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
    "[0-9][0-9][0-9][0-9][0-9][0-9]"
)


def _canonical_time_predicate(column, *, nullable=False):
    shape = (
        f"typeof({column}) = 'text' AND length({column}) = 26 "
        f"AND {column} GLOB '{CANONICAL_TIME_GLOB_0004}'"
    )
    if nullable:
        return f"({column} IS NULL OR ({shape}))"
    return f"({column} IS NOT NULL AND {shape})"


# Quantities stay inside the canonical I05 domain (0 .. 1000000000): an offline
# deficit is measured from an order line that already lives in that range.
#
# `length(trim(value, '0123456789abcdef')) = 0` proves every character is
# lowercase hex — `trim` strips matching characters from both ends, so anything
# else survives. A bare length check would accept a 64-character non-digest.
DDL = (
    # ------------------------------------------------------------------ lease
    # A lease is the only credential that authorizes normal v1 ingest.  The
    # secret itself is never stored: only its SHA-256 digest, compared against
    # sha256(candidate_token) by the service layer in I09-B.
    f"""CREATE TABLE offline_leases (
        lease_id TEXT NOT NULL,
        shop_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        device_id TEXT NOT NULL,
        contract_version INTEGER NOT NULL,
        catalog_version INTEGER NOT NULL,
        catalog_snapshot_digest TEXT NOT NULL,
        secret_sha256 TEXT NOT NULL,
        server_anchor_id TEXT NOT NULL,
        anchor_server_time_utc TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        state_version INTEGER NOT NULL DEFAULT 0,
        revoked_at TEXT,
        revoke_reason TEXT,
        revoked_by_user_id INTEGER,
        PRIMARY KEY (lease_id),
        CONSTRAINT ck_offline_leases_identifiers CHECK (
            length(lease_id) > 0 AND length(device_id) > 0
            AND length(server_anchor_id) > 0
        ),
        CONSTRAINT ck_offline_leases_secret_digest CHECK (
            length(secret_sha256) = 64
            AND length(trim(secret_sha256, '0123456789abcdef')) = 0
        ),
        CONSTRAINT ck_offline_leases_catalog_digest CHECK (
            length(catalog_snapshot_digest) = 64
            AND length(trim(catalog_snapshot_digest, '0123456789abcdef')) = 0
        ),
        CONSTRAINT ck_offline_leases_contract_version CHECK (contract_version >= 1),
        CONSTRAINT ck_offline_leases_catalog_version CHECK (catalog_version >= 0),
        CONSTRAINT ck_offline_leases_state_version CHECK (state_version >= 0),
        CONSTRAINT ck_offline_leases_time_format CHECK (
            {_canonical_time_predicate("anchor_server_time_utc")}
            AND {_canonical_time_predicate("issued_at")}
            AND {_canonical_time_predicate("expires_at")}
            AND {_canonical_time_predicate("revoked_at", nullable=True)}
        ),
        CONSTRAINT ck_offline_leases_expiry CHECK (expires_at > issued_at),
        CONSTRAINT ck_offline_leases_revocation CHECK (
            (revoked_at IS NULL AND revoke_reason IS NULL
             AND revoked_by_user_id IS NULL)
            OR (revoked_at IS NOT NULL AND revoke_reason IS NOT NULL
                AND revoked_by_user_id IS NOT NULL AND revoked_at >= issued_at)
        ),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(user_id) REFERENCES users (id),
        FOREIGN KEY(revoked_by_user_id) REFERENCES users (id)
    )""",
    # --------------------------------------------------------------- registry
    # The registry is the durable tombstone for one offline UUID.  It exists
    # even when no order does, so a corrected or abandoned receipt can never be
    # ingested a second time as fresh revenue.
    f"""CREATE TABLE offline_receipt_registry (
        offline_uuid TEXT NOT NULL,
        shop_id INTEGER NOT NULL,
        order_id INTEGER,
        server_fingerprint TEXT NOT NULL,
        contract_version INTEGER NOT NULL,
        state TEXT NOT NULL,
        superseded_by_offline_uuid TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        state_version INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (offline_uuid),
        CONSTRAINT ck_offline_receipt_registry_uuid CHECK (length(offline_uuid) > 0),
        CONSTRAINT ck_offline_receipt_registry_fingerprint CHECK (
            length(server_fingerprint) >= 8 AND length(server_fingerprint) <= 128
        ),
        CONSTRAINT ck_offline_receipt_registry_contract_version CHECK (
            contract_version >= 0
        ),
        CONSTRAINT ck_offline_receipt_registry_state_version CHECK (state_version >= 0),
        CONSTRAINT ck_offline_receipt_registry_time_format CHECK (
            {_canonical_time_predicate("created_at")}
            AND {_canonical_time_predicate("updated_at")}
        ),
        CONSTRAINT ck_offline_receipt_registry_state CHECK (
            state IN ('INGESTED', 'SUPERSEDED', 'ABANDONED')
        ),
        CONSTRAINT ck_offline_receipt_registry_ingested_order CHECK (
            (state = 'INGESTED' AND order_id IS NOT NULL)
            OR (state <> 'INGESTED' AND order_id IS NULL)
        ),
        CONSTRAINT ck_offline_receipt_registry_supersede CHECK (
            (state = 'SUPERSEDED' AND superseded_by_offline_uuid IS NOT NULL
             AND superseded_by_offline_uuid <> offline_uuid)
            OR (state <> 'SUPERSEDED' AND superseded_by_offline_uuid IS NULL)
        ),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(superseded_by_offline_uuid)
            REFERENCES offline_receipt_registry (offline_uuid)
    )""",
    # --------------------------------------------------------------- receipts
    # One row per ingested offline document.  `sold_by_claimed_user_id` is a
    # claim carried by a browser lease, never proof of who physically sold; the
    # separate `synced_by_user_id` records who actually uploaded it.
    #
    # A v0 receipt predates the lease protocol, so lease/session/sequence/anchor
    # must stay NULL — inventing them later is fabricating evidence about money.
    # `device_id` is deliberately not forbidden on v0: the canonical v0 payload
    # already carries a client-declared device label, which claims nothing.
    f"""CREATE TABLE offline_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        offline_uuid TEXT NOT NULL,
        contract_version INTEGER NOT NULL,
        lease_id TEXT,
        device_id TEXT,
        offline_session_id TEXT,
        sequence INTEGER,
        server_fingerprint TEXT NOT NULL,
        client_fingerprint TEXT,
        client_fingerprint_mismatch INTEGER NOT NULL,
        sold_by_claimed_user_id INTEGER NOT NULL,
        synced_by_user_id INTEGER NOT NULL,
        attribution_kind TEXT NOT NULL,
        sold_at_effective TEXT NOT NULL,
        sold_at_client_utc TEXT NOT NULL,
        sold_at_upper_bound TEXT,
        time_confidence TEXT NOT NULL,
        client_monotonic_ms INTEGER,
        server_anchor_id TEXT,
        ingested_at TEXT NOT NULL,
        CONSTRAINT ck_offline_receipts_contract_version CHECK (contract_version >= 0),
        CONSTRAINT ck_offline_receipts_sequence CHECK (
            sequence IS NULL OR sequence > 0
        ),
        CONSTRAINT ck_offline_receipts_mismatch_flag CHECK (
            client_fingerprint_mismatch IN (0, 1)
        ),
        CONSTRAINT ck_offline_receipts_mismatch_evidence CHECK (
            client_fingerprint_mismatch = 0 OR client_fingerprint IS NOT NULL
        ),
        CONSTRAINT ck_offline_receipts_server_fingerprint CHECK (
            length(server_fingerprint) >= 8 AND length(server_fingerprint) <= 128
        ),
        CONSTRAINT ck_offline_receipts_client_fingerprint CHECK (
            client_fingerprint IS NULL
            OR (length(client_fingerprint) >= 8
                AND length(client_fingerprint) <= 128)
        ),
        CONSTRAINT ck_offline_receipts_time_format CHECK (
            {_canonical_time_predicate("sold_at_effective")}
            AND {_canonical_time_predicate("sold_at_client_utc")}
            AND {_canonical_time_predicate("sold_at_upper_bound", nullable=True)}
            AND {_canonical_time_predicate("ingested_at")}
        ),
        CONSTRAINT ck_offline_receipts_time_confidence CHECK (
            time_confidence IN (
                'ANCHORED_CLIENT', 'BOUNDED', 'ANOMALY', 'LEGACY', 'RECOVERED'
            )
        ),
        CONSTRAINT ck_offline_receipts_attribution CHECK (
            attribution_kind IN ('LEASE_CLAIM', 'LEGACY_UNKNOWN', 'OWNER_RECOVERY')
        ),
        CONSTRAINT ck_offline_receipts_legacy_contract CHECK (
            (contract_version = 0 AND attribution_kind = 'LEGACY_UNKNOWN'
             AND time_confidence = 'LEGACY')
            OR (contract_version >= 1 AND attribution_kind <> 'LEGACY_UNKNOWN'
                AND time_confidence <> 'LEGACY')
        ),
        CONSTRAINT ck_offline_receipts_owner_recovery CHECK (
            (attribution_kind = 'OWNER_RECOVERY' AND time_confidence = 'RECOVERED')
            OR (attribution_kind <> 'OWNER_RECOVERY'
                AND time_confidence <> 'RECOVERED')
        ),
        CONSTRAINT ck_offline_receipts_lease_claim CHECK (
            attribution_kind <> 'LEASE_CLAIM'
            OR time_confidence IN ('ANCHORED_CLIENT', 'BOUNDED', 'ANOMALY')
        ),
        CONSTRAINT ck_offline_receipts_v1_binding CHECK (
            (contract_version = 0 AND lease_id IS NULL
             AND offline_session_id IS NULL AND sequence IS NULL
             AND server_anchor_id IS NULL)
            OR (contract_version >= 1 AND lease_id IS NOT NULL
                AND device_id IS NOT NULL AND offline_session_id IS NOT NULL
                AND sequence IS NOT NULL AND server_anchor_id IS NOT NULL
                AND offline_session_id = lease_id)
        ),
        CONSTRAINT ck_offline_receipts_upper_bound CHECK (
            sold_at_upper_bound IS NULL OR sold_at_upper_bound >= sold_at_effective
        ),
        CONSTRAINT ck_offline_receipts_monotonic CHECK (
            client_monotonic_ms IS NULL OR client_monotonic_ms >= 0
        ),
        FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(offline_uuid)
            REFERENCES offline_receipt_registry (offline_uuid),
        FOREIGN KEY(lease_id) REFERENCES offline_leases (lease_id),
        FOREIGN KEY(sold_by_claimed_user_id) REFERENCES users (id),
        FOREIGN KEY(synced_by_user_id) REFERENCES users (id)
    )""",
    # --------------------------------------------------------------- deficits
    # Exact per-line evidence that goods left the shop with no stock behind
    # them.  Only a positive stocktake reconciliation may close it: an owner
    # acknowledgement is deliberately NOT a resolution kind here, because a
    # click cannot make the missing quantity reappear.
    f"""CREATE TABLE offline_stock_deficits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_item_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        deficit_quantity INTEGER NOT NULL,
        remaining_quantity INTEGER NOT NULL,
        resolution_kind TEXT,
        resolved_by_user_id INTEGER,
        resolved_at TEXT,
        resolution_reason TEXT,
        state_version INTEGER NOT NULL DEFAULT 0,
        CONSTRAINT ck_offline_stock_deficits_quantity CHECK (
            deficit_quantity > 0 AND deficit_quantity <= 1000000000
        ),
        CONSTRAINT ck_offline_stock_deficits_remaining CHECK (
            remaining_quantity >= 0 AND remaining_quantity <= deficit_quantity
        ),
        CONSTRAINT ck_offline_stock_deficits_state_version CHECK (state_version >= 0),
        CONSTRAINT ck_offline_stock_deficits_time_format CHECK (
            {_canonical_time_predicate("resolved_at", nullable=True)}
        ),
        CONSTRAINT ck_offline_stock_deficits_resolution_kind CHECK (
            resolution_kind IS NULL OR resolution_kind = 'STOCKTAKE'
        ),
        CONSTRAINT ck_offline_stock_deficits_open CHECK (
            remaining_quantity = 0
            OR (resolution_kind IS NULL AND resolved_by_user_id IS NULL
                AND resolved_at IS NULL)
        ),
        -- `IS` and not `=`: a NULL resolution_kind must fail this constraint,
        -- and SQLite lets a CHECK that evaluates to NULL pass.
        CONSTRAINT ck_offline_stock_deficits_closed CHECK (
            remaining_quantity > 0
            OR (resolution_kind IS 'STOCKTAKE' AND resolved_by_user_id IS NOT NULL
                AND resolved_at IS NOT NULL AND state_version >= 1)
        ),
        FOREIGN KEY(order_item_id) REFERENCES order_items (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(resolved_by_user_id) REFERENCES users (id)
    )""",
    # ----------------------------------------------------------------- issues
    # `evidence_id` is a typed pointer, not a foreign key: OFFLINE_BATCH_DEFICIT
    # points at the I05 table and OFFLINE_STOCK_DEFICIT at the one above.  Every
    # other kind must carry no evidence link at all, so nothing can fake one.
    f"""CREATE TABLE offline_receipt_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        order_item_id INTEGER,
        product_id INTEGER,
        issue_code TEXT NOT NULL,
        evidence_kind TEXT NOT NULL,
        evidence_id INTEGER,
        severity TEXT NOT NULL,
        state TEXT NOT NULL,
        reason TEXT,
        opened_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by_user_id INTEGER,
        resolution_kind TEXT,
        state_version INTEGER NOT NULL DEFAULT 0,
        CONSTRAINT ck_offline_receipt_issues_code CHECK (length(issue_code) > 0),
        CONSTRAINT ck_offline_receipt_issues_evidence_kind CHECK (
            evidence_kind IN (
                'OFFLINE_BATCH_DEFICIT', 'OFFLINE_STOCK_DEFICIT', 'SHIFT',
                'CATALOG', 'TIME', 'IDENTITY', 'LEGACY_AMBIGUOUS'
            )
        ),
        CONSTRAINT ck_offline_receipt_issues_severity CHECK (
            severity IN ('INFO', 'ACTION')
        ),
        CONSTRAINT ck_offline_receipt_issues_state CHECK (
            state IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')
        ),
        CONSTRAINT ck_offline_receipt_issues_state_version CHECK (state_version >= 0),
        CONSTRAINT ck_offline_receipt_issues_time_format CHECK (
            {_canonical_time_predicate("opened_at")}
            AND {_canonical_time_predicate("resolved_at", nullable=True)}
        ),
        CONSTRAINT ck_offline_receipt_issues_open CHECK (
            state <> 'OPEN'
            OR (resolved_at IS NULL AND resolved_by_user_id IS NULL
                AND resolution_kind IS NULL)
        ),
        CONSTRAINT ck_offline_receipt_issues_resolved_actor CHECK (
            state = 'OPEN'
            OR (resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)
        ),
        CONSTRAINT ck_offline_receipt_issues_ack_reason CHECK (
            state <> 'ACKNOWLEDGED' OR reason IS NOT NULL
        ),
        CONSTRAINT ck_offline_receipt_issues_evidence_link CHECK (
            (evidence_kind IN ('OFFLINE_BATCH_DEFICIT', 'OFFLINE_STOCK_DEFICIT')
             AND evidence_id IS NOT NULL AND order_item_id IS NOT NULL
             AND product_id IS NOT NULL)
            OR (evidence_kind NOT IN (
                    'OFFLINE_BATCH_DEFICIT', 'OFFLINE_STOCK_DEFICIT'
                ) AND evidence_id IS NULL)
        ),
        FOREIGN KEY(order_id) REFERENCES orders (id),
        FOREIGN KEY(order_item_id) REFERENCES order_items (id),
        FOREIGN KEY(product_id) REFERENCES products (id),
        FOREIGN KEY(resolved_by_user_id) REFERENCES users (id)
    )""",
    # --------------------------------------------------------------- recovery
    # `system_log_id` is NOT NULL so an owner recovery cannot exist without its
    # audit row.  I09-B must build that SystemLog transaction-locally and flush
    # for its id; the current `log_system_action()` helper commits by itself and
    # therefore must not be used on this path.
    f"""CREATE TABLE offline_recovery_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL,
        action_kind TEXT NOT NULL,
        original_offline_uuid TEXT NOT NULL,
        original_fingerprint TEXT,
        replacement_offline_uuid TEXT,
        file_digest TEXT,
        reason TEXT NOT NULL,
        performed_by_user_id INTEGER NOT NULL,
        performed_at TEXT NOT NULL,
        system_log_id INTEGER NOT NULL,
        CONSTRAINT ck_offline_recovery_actions_kind CHECK (
            action_kind IN (
                'IMPORT', 'LEGACY_INGEST', 'CORRECT', 'ABANDON',
                'RECLAIM_DENIED_OVERRIDE'
            )
        ),
        CONSTRAINT ck_offline_recovery_actions_uuid CHECK (
            length(original_offline_uuid) > 0
        ),
        CONSTRAINT ck_offline_recovery_actions_reason CHECK (length(reason) >= 10),
        CONSTRAINT ck_offline_recovery_actions_time_format CHECK (
            {_canonical_time_predicate("performed_at")}
        ),
        CONSTRAINT ck_offline_recovery_actions_fingerprint CHECK (
            original_fingerprint IS NULL
            OR (length(original_fingerprint) >= 8
                AND length(original_fingerprint) <= 128)
        ),
        CONSTRAINT ck_offline_recovery_actions_file_digest CHECK (
            file_digest IS NULL
            OR (length(file_digest) = 64
                AND length(trim(file_digest, '0123456789abcdef')) = 0)
        ),
        CONSTRAINT ck_offline_recovery_actions_replacement CHECK (
            (action_kind = 'CORRECT' AND replacement_offline_uuid IS NOT NULL
             AND replacement_offline_uuid <> original_offline_uuid)
            OR (action_kind <> 'CORRECT' AND replacement_offline_uuid IS NULL)
        ),
        FOREIGN KEY(shop_id) REFERENCES shops (id),
        FOREIGN KEY(performed_by_user_id) REFERENCES users (id),
        FOREIGN KEY(system_log_id) REFERENCES system_logs (id)
    )""",
    # ---------------------------------------------------------------- indexes
    "CREATE INDEX ix_offline_leases_shop_user ON offline_leases (shop_id, user_id)",
    "CREATE INDEX ix_offline_leases_expires ON offline_leases (expires_at)",
    "CREATE UNIQUE INDEX ux_offline_receipts_order_id ON offline_receipts (order_id)",
    "CREATE UNIQUE INDEX ux_offline_receipts_offline_uuid ON offline_receipts (offline_uuid)",
    """CREATE UNIQUE INDEX ux_offline_receipts_lease_sequence
        ON offline_receipts (lease_id, sequence) WHERE lease_id IS NOT NULL""",
    "CREATE INDEX ix_offline_receipts_sold_at ON offline_receipts (sold_at_effective)",
    """CREATE UNIQUE INDEX ux_offline_stock_deficits_order_item
        ON offline_stock_deficits (order_item_id)""",
    """CREATE INDEX ix_offline_stock_deficits_open
        ON offline_stock_deficits (product_id, id) WHERE remaining_quantity > 0""",
    """CREATE UNIQUE INDEX ux_offline_receipt_issues_scope
        ON offline_receipt_issues (
            order_id, issue_code, COALESCE(order_item_id, 0), COALESCE(product_id, 0)
        )""",
    """CREATE INDEX ix_offline_receipt_issues_open
        ON offline_receipt_issues (state, severity, order_id)
        WHERE state <> 'RESOLVED'""",
    """CREATE INDEX ix_offline_receipt_registry_shop
        ON offline_receipt_registry (shop_id, state)""",
    """CREATE INDEX ix_offline_recovery_actions_shop
        ON offline_recovery_actions (shop_id, performed_at)""",
    """CREATE INDEX ix_offline_recovery_actions_uuid
        ON offline_recovery_actions (original_offline_uuid)""",
)

EXPECTED_TABLES_0004 = (
    "offline_leases",
    "offline_receipt_registry",
    "offline_receipts",
    "offline_stock_deficits",
    "offline_receipt_issues",
    "offline_recovery_actions",
)

EXPECTED_INDEXES_0004 = (
    "ix_offline_leases_shop_user",
    "ix_offline_leases_expires",
    "ux_offline_receipts_order_id",
    "ux_offline_receipts_offline_uuid",
    "ux_offline_receipts_lease_sequence",
    "ix_offline_receipts_sold_at",
    "ux_offline_stock_deficits_order_item",
    "ix_offline_stock_deficits_open",
    "ux_offline_receipt_issues_scope",
    "ix_offline_receipt_issues_open",
    "ix_offline_receipt_registry_shop",
    "ix_offline_recovery_actions_shop",
    "ix_offline_recovery_actions_uuid",
)

# Every check is a row count that must be zero.  CHECK constraints alone are not
# enough: `PRAGMA ignore_check_constraints`, a restored backup or a legacy
# writer can all produce rows the declared constraint would have refused.
# Nothing here may depend on wall-clock time, or a database would start failing
# verification simply because it sat unused.
DATA_CHECKS = (
    (
        # This group deliberately revalidates the time contract independently
        # of the declared CHECK constraints.  Restores and legacy writers can
        # contain invalid text even when `ignore_check_constraints` was used.
        "I09_VERIFY_TIME_FORMAT",
        f"""SELECT
             (SELECT COUNT(*) FROM offline_leases l
              WHERE NOT {_canonical_time_predicate("l.anchor_server_time_utc")}
                 OR NOT {_canonical_time_predicate("l.issued_at")}
                 OR NOT {_canonical_time_predicate("l.expires_at")}
                 OR NOT {_canonical_time_predicate("l.revoked_at", nullable=True)})
           + (SELECT COUNT(*) FROM offline_receipt_registry g
              WHERE NOT {_canonical_time_predicate("g.created_at")}
                 OR NOT {_canonical_time_predicate("g.updated_at")})
           + (SELECT COUNT(*) FROM offline_receipts r
              WHERE NOT {_canonical_time_predicate("r.sold_at_effective")}
                 OR NOT {_canonical_time_predicate("r.sold_at_client_utc")}
                 OR NOT {_canonical_time_predicate("r.sold_at_upper_bound", nullable=True)}
                 OR NOT {_canonical_time_predicate("r.ingested_at")})
           + (SELECT COUNT(*) FROM offline_stock_deficits d
              WHERE NOT {_canonical_time_predicate("d.resolved_at", nullable=True)})
           + (SELECT COUNT(*) FROM offline_receipt_issues i
              WHERE NOT {_canonical_time_predicate("i.opened_at")}
                 OR NOT {_canonical_time_predicate("i.resolved_at", nullable=True)})
           + (SELECT COUNT(*) FROM offline_recovery_actions a
              WHERE NOT {_canonical_time_predicate("a.performed_at")})""",
    ),
    (
        "I09_VERIFY_LEASE_SHAPE",
        """SELECT COUNT(*) FROM offline_leases
           WHERE typeof(lease_id) <> 'text' OR length(lease_id) = 0
              OR typeof(device_id) <> 'text' OR length(device_id) = 0
              OR typeof(server_anchor_id) <> 'text' OR length(server_anchor_id) = 0
              OR typeof(secret_sha256) <> 'text' OR length(secret_sha256) <> 64
              OR length(trim(secret_sha256, '0123456789abcdef')) <> 0
              OR typeof(catalog_snapshot_digest) <> 'text'
              OR length(catalog_snapshot_digest) <> 64
              OR length(trim(catalog_snapshot_digest, '0123456789abcdef')) <> 0
              OR typeof(contract_version) <> 'integer' OR contract_version < 1
              OR typeof(catalog_version) <> 'integer' OR catalog_version < 0
              OR typeof(state_version) <> 'integer' OR state_version < 0
              OR typeof(issued_at) <> 'text' OR typeof(expires_at) <> 'text'
              OR typeof(anchor_server_time_utc) <> 'text'
              OR expires_at <= issued_at""",
    ),
    (
        "I09_VERIFY_LEASE_REVOCATION",
        """SELECT COUNT(*) FROM offline_leases
           WHERE (revoked_at IS NULL) <> (revoke_reason IS NULL)
              OR (revoked_at IS NULL) <> (revoked_by_user_id IS NULL)
              OR (revoked_at IS NOT NULL
                  AND (typeof(revoked_at) <> 'text' OR revoked_at < issued_at))""",
    ),
    (
        "I09_VERIFY_LEASE_PRINCIPALS",
        """SELECT COUNT(*) FROM offline_leases l
           LEFT JOIN shops s ON s.id = l.shop_id
           LEFT JOIN users u ON u.id = l.user_id
           LEFT JOIN users r ON r.id = l.revoked_by_user_id
           WHERE s.id IS NULL OR u.id IS NULL
              OR (l.revoked_by_user_id IS NOT NULL AND r.id IS NULL)""",
    ),
    (
        "I09_VERIFY_REGISTRY_STATE",
        """SELECT COUNT(*) FROM offline_receipt_registry g
           LEFT JOIN offline_receipt_registry n
                  ON n.offline_uuid = g.superseded_by_offline_uuid
           WHERE g.state NOT IN ('INGESTED', 'SUPERSEDED', 'ABANDONED')
              OR (g.state = 'INGESTED' AND g.order_id IS NULL)
              OR (g.state <> 'INGESTED' AND g.order_id IS NOT NULL)
              OR (g.state = 'SUPERSEDED'
                  AND (g.superseded_by_offline_uuid IS NULL
                       OR g.superseded_by_offline_uuid = g.offline_uuid
                       OR n.offline_uuid IS NULL))
              OR (g.state <> 'SUPERSEDED' AND g.superseded_by_offline_uuid IS NOT NULL)
              OR typeof(g.contract_version) <> 'integer' OR g.contract_version < 0
              OR typeof(g.state_version) <> 'integer' OR g.state_version < 0
              OR typeof(g.created_at) <> 'text' OR typeof(g.updated_at) <> 'text'
              OR length(g.server_fingerprint) < 8
              OR length(g.server_fingerprint) > 128""",
    ),
    (
        "I09_VERIFY_REGISTRY_SCOPE",
        """SELECT COUNT(*) FROM offline_receipt_registry g
           LEFT JOIN shops s ON s.id = g.shop_id
           LEFT JOIN orders o ON o.id = g.order_id
           WHERE s.id IS NULL
              OR (g.order_id IS NOT NULL
                  AND (o.id IS NULL OR o.shop_id IS NOT g.shop_id))""",
    ),
    (
        # A registry row in INGESTED state without its receipt, or a tombstoned
        # UUID that still owns one, would let the same sale be counted twice.
        "I09_VERIFY_REGISTRY_RECEIPT_CARDINALITY",
        """SELECT COUNT(*) FROM offline_receipt_registry g
           WHERE (SELECT COUNT(*) FROM offline_receipts r
                  WHERE r.offline_uuid = g.offline_uuid)
                 <> (CASE WHEN g.state = 'INGESTED' THEN 1 ELSE 0 END)""",
    ),
    (
        "I09_VERIFY_RECEIPT_SHAPE",
        """SELECT COUNT(*) FROM offline_receipts
           WHERE typeof(contract_version) <> 'integer' OR contract_version < 0
              OR (sequence IS NOT NULL
                  AND (typeof(sequence) <> 'integer' OR sequence <= 0))
              OR client_fingerprint_mismatch NOT IN (0, 1)
              OR (client_fingerprint_mismatch = 1 AND client_fingerprint IS NULL)
              OR typeof(server_fingerprint) <> 'text'
              OR length(server_fingerprint) < 8 OR length(server_fingerprint) > 128
              OR (client_fingerprint IS NOT NULL
                  AND (length(client_fingerprint) < 8
                       OR length(client_fingerprint) > 128))
              OR typeof(sold_at_effective) <> 'text'
              OR typeof(sold_at_client_utc) <> 'text'
              OR typeof(ingested_at) <> 'text'
              OR (sold_at_upper_bound IS NOT NULL
                  AND sold_at_upper_bound < sold_at_effective)
              OR (client_monotonic_ms IS NOT NULL
                  AND (typeof(client_monotonic_ms) <> 'integer'
                       OR client_monotonic_ms < 0))""",
    ),
    (
        # v0 is legacy and stays legacy: it can never acquire a lease, an
        # anchor or a sequence after the fact, because none existed at sale.
        "I09_VERIFY_RECEIPT_CONTRACT",
        """SELECT COUNT(*) FROM offline_receipts
           WHERE time_confidence NOT IN (
                     'ANCHORED_CLIENT', 'BOUNDED', 'ANOMALY', 'LEGACY', 'RECOVERED')
              OR attribution_kind NOT IN (
                     'LEASE_CLAIM', 'LEGACY_UNKNOWN', 'OWNER_RECOVERY')
              OR (contract_version = 0) <> (attribution_kind = 'LEGACY_UNKNOWN')
              OR (attribution_kind = 'LEGACY_UNKNOWN')
                 <> (time_confidence = 'LEGACY')
              OR (attribution_kind = 'OWNER_RECOVERY')
                 <> (time_confidence = 'RECOVERED')
              OR (attribution_kind = 'LEASE_CLAIM'
                  AND time_confidence NOT IN ('ANCHORED_CLIENT', 'BOUNDED', 'ANOMALY'))
              OR (contract_version = 0
                  AND (lease_id IS NOT NULL OR offline_session_id IS NOT NULL
                       OR sequence IS NOT NULL OR server_anchor_id IS NOT NULL))
              OR (contract_version >= 1
                  AND (lease_id IS NULL OR device_id IS NULL
                       OR offline_session_id IS NULL OR sequence IS NULL
                       OR server_anchor_id IS NULL
                       OR offline_session_id <> lease_id))""",
    ),
    (
        "I09_VERIFY_RECEIPT_DOCUMENT",
        """SELECT COUNT(*) FROM offline_receipts r
           LEFT JOIN orders o ON o.id = r.order_id
           LEFT JOIN offline_receipt_registry g ON g.offline_uuid = r.offline_uuid
           LEFT JOIN users c ON c.id = r.sold_by_claimed_user_id
           LEFT JOIN users y ON y.id = r.synced_by_user_id
           WHERE o.id IS NULL OR g.offline_uuid IS NULL
              OR c.id IS NULL OR y.id IS NULL
              OR o.offline_uuid IS NOT r.offline_uuid
              OR g.order_id IS NOT r.order_id
              OR g.state <> 'INGESTED'
              OR g.server_fingerprint <> r.server_fingerprint
              OR g.contract_version <> r.contract_version""",
    ),
    (
        # The lease binds shop, claimed seller, device, session and anchor.  A
        # receipt pointing at someone else's lease is an identity claim nobody
        # can audit later.
        "I09_VERIFY_RECEIPT_LEASE",
        """SELECT COUNT(*) FROM offline_receipts r
           LEFT JOIN offline_leases l ON l.lease_id = r.lease_id
           LEFT JOIN offline_receipt_registry g ON g.offline_uuid = r.offline_uuid
           WHERE (r.lease_id IS NOT NULL AND l.lease_id IS NULL)
              OR (r.contract_version >= 1
                  AND (l.lease_id IS NULL
                       OR l.shop_id IS NOT g.shop_id
                       OR l.user_id IS NOT r.sold_by_claimed_user_id
                       OR l.device_id IS NOT r.device_id
                       OR r.offline_session_id IS NOT r.lease_id
                       OR l.server_anchor_id IS NOT r.server_anchor_id))""",
    ),
    (
        "I09_VERIFY_DEFICIT_STATE",
        """SELECT COUNT(*) FROM offline_stock_deficits
           WHERE typeof(deficit_quantity) <> 'integer'
              OR typeof(remaining_quantity) <> 'integer'
              OR typeof(state_version) <> 'integer'
              OR deficit_quantity <= 0 OR deficit_quantity > 1000000000
              OR remaining_quantity < 0 OR remaining_quantity > deficit_quantity
              OR state_version < 0
              OR (resolution_kind IS NOT NULL AND resolution_kind <> 'STOCKTAKE')
              OR (remaining_quantity > 0
                  AND (resolution_kind IS NOT NULL OR resolved_at IS NOT NULL
                       OR resolved_by_user_id IS NOT NULL))
              OR (remaining_quantity = 0
                  AND (resolution_kind IS NOT 'STOCKTAKE' OR resolved_at IS NULL
                       OR resolved_by_user_id IS NULL OR state_version < 1))""",
    ),
    (
        "I09_VERIFY_DEFICIT_EVIDENCE",
        """SELECT COUNT(*) FROM offline_stock_deficits d
           LEFT JOIN order_items i ON i.id = d.order_item_id
           LEFT JOIN products p ON p.id = d.product_id
           LEFT JOIN users u ON u.id = d.resolved_by_user_id
           WHERE i.id IS NULL OR p.id IS NULL
              OR i.product_id IS NOT d.product_id
              OR (d.resolved_by_user_id IS NOT NULL AND u.id IS NULL)
              OR NOT EXISTS (SELECT 1 FROM offline_receipts r
                             WHERE r.order_id = i.order_id)""",
    ),
    (
        "I09_VERIFY_ISSUE_STATE",
        """SELECT COUNT(*) FROM offline_receipt_issues
           WHERE state NOT IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')
              OR severity NOT IN ('INFO', 'ACTION')
              OR evidence_kind NOT IN (
                     'OFFLINE_BATCH_DEFICIT', 'OFFLINE_STOCK_DEFICIT', 'SHIFT',
                     'CATALOG', 'TIME', 'IDENTITY', 'LEGACY_AMBIGUOUS')
              OR typeof(issue_code) <> 'text' OR length(issue_code) = 0
              OR typeof(opened_at) <> 'text'
              OR typeof(state_version) <> 'integer' OR state_version < 0
              OR (state = 'OPEN'
                  AND (resolved_at IS NOT NULL OR resolved_by_user_id IS NOT NULL
                       OR resolution_kind IS NOT NULL))
              OR (state <> 'OPEN'
                  AND (resolved_at IS NULL OR resolved_by_user_id IS NULL))
              OR (state = 'ACKNOWLEDGED' AND reason IS NULL)""",
    ),
    (
        "I09_VERIFY_ISSUE_SCOPE",
        """SELECT COUNT(*) FROM offline_receipt_issues s
           LEFT JOIN orders o ON o.id = s.order_id
           LEFT JOIN order_items i ON i.id = s.order_item_id
           LEFT JOIN products p ON p.id = s.product_id
           LEFT JOIN users u ON u.id = s.resolved_by_user_id
           WHERE o.id IS NULL
              OR (s.order_item_id IS NOT NULL
                  AND (i.id IS NULL OR i.order_id IS NOT s.order_id))
              OR (s.product_id IS NOT NULL AND p.id IS NULL)
              OR (s.resolved_by_user_id IS NOT NULL AND u.id IS NULL)""",
    ),
    (
        "I09_VERIFY_ISSUE_EVIDENCE",
        """SELECT COUNT(*) FROM offline_receipt_issues s
           LEFT JOIN offline_stock_deficits d
                  ON d.id = s.evidence_id
                 AND s.evidence_kind = 'OFFLINE_STOCK_DEFICIT'
           LEFT JOIN offline_batch_stock_deficits b
                  ON b.id = s.evidence_id
                 AND s.evidence_kind = 'OFFLINE_BATCH_DEFICIT'
           LEFT JOIN order_items di ON di.id = d.order_item_id
           LEFT JOIN order_items bi ON bi.id = b.order_item_id
           WHERE (s.evidence_kind = 'OFFLINE_STOCK_DEFICIT'
                  AND (d.id IS NULL
                       OR d.order_item_id IS NOT s.order_item_id
                       OR d.product_id IS NOT s.product_id
                       OR di.id IS NULL OR di.order_id IS NOT s.order_id))
              OR (s.evidence_kind = 'OFFLINE_BATCH_DEFICIT'
                  AND (b.id IS NULL
                       OR b.order_item_id IS NOT s.order_item_id
                       OR b.product_id IS NOT s.product_id
                       OR bi.id IS NULL OR bi.order_id IS NOT s.order_id))
              OR (s.evidence_kind NOT IN (
                      'OFFLINE_BATCH_DEFICIT', 'OFFLINE_STOCK_DEFICIT')
                  AND s.evidence_id IS NOT NULL)""",
    ),
    (
        "I09_VERIFY_RECOVERY_AUDIT",
        """SELECT COUNT(*) FROM offline_recovery_actions a
           LEFT JOIN system_logs sl ON sl.id = a.system_log_id
           LEFT JOIN users u ON u.id = a.performed_by_user_id
           LEFT JOIN shops s ON s.id = a.shop_id
           WHERE sl.id IS NULL OR u.id IS NULL OR s.id IS NULL
              OR sl.user_id IS NOT a.performed_by_user_id
              OR sl.shop_id IS NOT a.shop_id
              OR a.action_kind NOT IN (
                     'IMPORT', 'LEGACY_INGEST', 'CORRECT', 'ABANDON',
                     'RECLAIM_DENIED_OVERRIDE')
              OR typeof(a.performed_at) <> 'text'
              OR typeof(a.reason) <> 'text' OR length(a.reason) < 10
              OR length(a.original_offline_uuid) = 0
              OR (a.original_fingerprint IS NOT NULL
                  AND (length(a.original_fingerprint) < 8
                       OR length(a.original_fingerprint) > 128))
              OR (a.file_digest IS NOT NULL
                  AND (length(a.file_digest) <> 64
                       OR length(trim(a.file_digest, '0123456789abcdef')) <> 0))""",
    ),
    (
        # A correction must point at a real replacement, and the corrected
        # original must be tombstoned onto exactly that replacement.
        "I09_VERIFY_RECOVERY_CORRECTION",
        """SELECT COUNT(*) FROM offline_recovery_actions a
           LEFT JOIN offline_receipt_registry n
                  ON n.offline_uuid = a.replacement_offline_uuid
           LEFT JOIN offline_receipt_registry g
                  ON g.offline_uuid = a.original_offline_uuid
           WHERE (a.action_kind = 'CORRECT'
                  AND (a.replacement_offline_uuid IS NULL
                       OR a.replacement_offline_uuid = a.original_offline_uuid
                       OR n.offline_uuid IS NULL
                       OR (g.offline_uuid IS NOT NULL
                           AND (g.state <> 'SUPERSEDED'
                                OR g.superseded_by_offline_uuid
                                   IS NOT a.replacement_offline_uuid))))
              OR (a.action_kind <> 'CORRECT'
                  AND a.replacement_offline_uuid IS NOT NULL)""",
    ),
)


def _execute(statement):
    callback = op.get_context().config.attributes.get("before_statement")
    if callback is not None:
        callback()
    op.execute(statement)


def upgrade():
    # Pure DDL inside the coordinator's BEGIN IMMEDIATE.  No backfill: an
    # existing offline order predates lease, anchor and fingerprint, so any row
    # invented here would be fabricated evidence about real money.
    for statement in DDL:
        _execute(statement)


def verify(connection):
    execute = getattr(connection, "exec_driver_sql", connection.execute)
    rows = execute(
        """SELECT type, name, tbl_name FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%'"""
    ).fetchall()
    tables = {name for kind, name, _table in rows if kind == "table"}
    owned_indexes = {
        name
        for kind, name, table in rows
        if kind == "index" and table in EXPECTED_TABLES_0004
    }
    missing_tables = set(EXPECTED_TABLES_0004) - tables
    missing_indexes = set(EXPECTED_INDEXES_0004) - owned_indexes
    if missing_tables or missing_indexes:
        raise RuntimeError(
            "I09_VERIFY_SCHEMA_OBJECTS:"
            + ",".join(sorted(missing_tables | missing_indexes))
        )
    for code, statement in DATA_CHECKS:
        if execute(statement).fetchone()[0]:
            raise RuntimeError(code)


def downgrade():
    raise RuntimeError("F-Selling I09 migrations are forward-only")
