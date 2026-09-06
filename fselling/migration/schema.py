"""Immutable control-schema v1 and deterministic SQLite shape fingerprints."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable

from .errors import ControlSchemaError, SchemaMismatchError

CONTROL_SCHEMA_VERSION = 1
CONTROL_TABLES = frozenset(
    {
        "fs_migration_control",
        "fs_migration_lock",
        "fs_migration_revision_journal",
        "fs_migration_campaigns",
        "fs_migration_attempts",
        "fs_migration_requests",
    }
)
CONTROL_TRIGGERS = frozenset(
    {
        "trg_fs_migration_control_no_update",
        "trg_fs_migration_control_no_delete",
        "trg_fs_migration_journal_no_update",
        "trg_fs_migration_journal_no_delete",
        "trg_fs_migration_attempts_guard_update",
        "trg_fs_migration_attempts_no_delete",
        "trg_fs_migration_requests_guard_update",
        "trg_fs_migration_requests_no_delete",
    }
)
OPERATIONAL_TABLES = frozenset(
    {
        "fs_migration_worksets",
        "fs_migration_work_items",
        "fs_migration_checkpoints",
        "fs_migration_manifests",
        "fs_migration_quarantine",
        "fs_migration_reconciliation",
        "fs_migration_feature_flags",
    }
)

CONTROL_DDL = (
    """CREATE TABLE fs_migration_control (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL CHECK (schema_version = 1),
        schema_fingerprint TEXT NOT NULL,
        database_uuid TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE fs_migration_lock (
        lock_name TEXT PRIMARY KEY,
        owner_id TEXT,
        lease_expires_at TEXT,
        fence_token INTEGER NOT NULL DEFAULT 0 CHECK (fence_token >= 0),
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE fs_migration_revision_journal (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        revision TEXT NOT NULL UNIQUE,
        down_revision TEXT,
        checksum TEXT NOT NULL CHECK (length(checksum) = 64),
        database_uuid TEXT NOT NULL,
        operation_key TEXT NOT NULL,
        attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        applied_at TEXT NOT NULL,
        UNIQUE (operation_key, attempt_no)
    )""",
    """CREATE TABLE fs_migration_campaigns (
        campaign_key TEXT PRIMARY KEY,
        phase TEXT NOT NULL CHECK (phase IN (
            'PREFLIGHT', 'EXPAND', 'DUAL_WRITE', 'BACKFILL', 'RECONCILE',
            'CUTOVER', 'STABILIZE', 'CLEANUP'
        )),
        phase_version INTEGER NOT NULL CHECK (phase_version >= 0),
        state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'COMPLETE', 'BLOCKED')),
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE fs_migration_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_key TEXT NOT NULL,
        attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
        request_id TEXT,
        command TEXT NOT NULL,
        target_revision TEXT,
        state TEXT NOT NULL CHECK (state IN (
            'RUNNING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_BLOCKED'
        )),
        fence_token INTEGER NOT NULL CHECK (fence_token > 0),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        error_code TEXT,
        error_digest TEXT CHECK (error_digest IS NULL OR length(error_digest) = 64),
        UNIQUE (operation_key, attempt_no)
    )""",
    """CREATE TABLE fs_migration_requests (
        request_id TEXT PRIMARY KEY,
        command TEXT NOT NULL,
        target_revision TEXT,
        input_digest TEXT CHECK (input_digest IS NULL OR length(input_digest) = 64),
        state TEXT NOT NULL CHECK (state IN (
            'RUNNING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_BLOCKED'
        )),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        error_code TEXT,
        error_digest TEXT CHECK (error_digest IS NULL OR length(error_digest) = 64)
    )""",
    """CREATE TRIGGER trg_fs_migration_control_no_update
    BEFORE UPDATE ON fs_migration_control
    BEGIN SELECT RAISE(ABORT, 'migration control row is immutable'); END""",
    """CREATE TRIGGER trg_fs_migration_control_no_delete
    BEFORE DELETE ON fs_migration_control
    BEGIN SELECT RAISE(ABORT, 'migration control row is immutable'); END""",
    """CREATE TRIGGER trg_fs_migration_journal_no_update
    BEFORE UPDATE ON fs_migration_revision_journal
    BEGIN SELECT RAISE(ABORT, 'revision journal is append-only'); END""",
    """CREATE TRIGGER trg_fs_migration_journal_no_delete
    BEFORE DELETE ON fs_migration_revision_journal
    BEGIN SELECT RAISE(ABORT, 'revision journal is append-only'); END""",
    """CREATE TRIGGER trg_fs_migration_attempts_guard_update
    BEFORE UPDATE ON fs_migration_attempts
    WHEN OLD.state <> 'RUNNING'
      OR NEW.operation_key <> OLD.operation_key
      OR NEW.attempt_no <> OLD.attempt_no
      OR COALESCE(NEW.request_id, '') <> COALESCE(OLD.request_id, '')
      OR NEW.command <> OLD.command
      OR COALESCE(NEW.target_revision, '') <> COALESCE(OLD.target_revision, '')
      OR NEW.fence_token <> OLD.fence_token
      OR NEW.started_at <> OLD.started_at
      OR NEW.state = 'RUNNING'
    BEGIN SELECT RAISE(ABORT, 'invalid migration attempt transition'); END""",
    """CREATE TRIGGER trg_fs_migration_attempts_no_delete
    BEFORE DELETE ON fs_migration_attempts
    BEGIN SELECT RAISE(ABORT, 'migration attempts are append-only'); END""",
    """CREATE TRIGGER trg_fs_migration_requests_guard_update
    BEFORE UPDATE ON fs_migration_requests
    WHEN OLD.state <> 'RUNNING'
      OR NEW.request_id <> OLD.request_id
      OR NEW.command <> OLD.command
      OR COALESCE(NEW.target_revision, '') <> COALESCE(OLD.target_revision, '')
      OR COALESCE(NEW.input_digest, '') <> COALESCE(OLD.input_digest, '')
      OR NEW.started_at <> OLD.started_at
      OR NEW.state = 'RUNNING'
    BEGIN SELECT RAISE(ABORT, 'invalid migration request transition'); END""",
    """CREATE TRIGGER trg_fs_migration_requests_no_delete
    BEFORE DELETE ON fs_migration_requests
    BEGIN SELECT RAISE(ABORT, 'migration requests are append-only'); END""",
)

# Filled from the canonical CONTROL_DDL shape.  Keeping the value checked in
# makes an accidental control-table edit a deliberate protocol change.
CONTROL_SCHEMA_FINGERPRINT = "1be2c54a0e8ccce8c35e61509eeb142047fc91ca42f4704033e179e553c26b62"


def _normalize_sql(sql: str | None) -> str | None:
    if sql is None:
        return None
    value = re.sub(r"\s+", " ", sql.strip()).rstrip(";")
    return re.sub(r"\s*([(),])\s*", r"\1", value)


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _object_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }


def schema_descriptor(
    connection: sqlite3.Connection,
    *,
    include_names: Iterable[str] | None = None,
    business_only: bool = False,
) -> list[dict[str, object]]:
    """Return a stable, structural description including checks and indexes."""
    wanted = set(include_names) if include_names is not None else None
    rows = connection.execute(
        """SELECT type, name, tbl_name, sql
           FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%'
           ORDER BY type, name"""
    ).fetchall()
    descriptor: list[dict[str, object]] = []
    for object_type, name, table_name, sql in rows:
        if business_only and (
            name == "alembic_version"
            or name.startswith("fs_migration_")
            or table_name.startswith("fs_migration_")
        ):
            continue
        if wanted is not None and name not in wanted and table_name not in wanted:
            continue
        item: dict[str, object] = {
            "type": object_type,
            "name": name,
            "table": table_name,
            "sql": _normalize_sql(sql),
        }
        if object_type == "table":
            item["columns"] = [
                list(row)
                for row in connection.execute(
                    f"PRAGMA table_xinfo({_quoted(name)})"
                ).fetchall()
            ]
            item["foreign_keys"] = [
                list(row)
                for row in connection.execute(
                    f"PRAGMA foreign_key_list({_quoted(name)})"
                ).fetchall()
            ]
        elif object_type == "index":
            index_row = next(
                (
                    row
                    for row in connection.execute(
                        f"PRAGMA index_list({_quoted(table_name)})"
                    ).fetchall()
                    if row[1] == name
                ),
                None,
            )
            item.pop("sql", None)
            item["unique"] = bool(index_row and index_row[2])
            item["origin"] = index_row[3] if index_row and len(index_row) > 3 else None
            item["partial"] = bool(index_row and len(index_row) > 4 and index_row[4])
            normalized = _normalize_sql(sql)
            lower = normalized.lower() if normalized else ""
            marker = " where "
            item["predicate"] = (
                "".join(lower.split(marker, 1)[1].split())
                if marker in lower
                else None
            )
            item["columns"] = [
                list(row)
                for row in connection.execute(
                    f"PRAGMA index_xinfo({_quoted(name)})"
                ).fetchall()
            ]
        descriptor.append(item)
    return descriptor


def schema_fingerprint(
    connection: sqlite3.Connection,
    *,
    include_names: Iterable[str] | None = None,
    business_only: bool = False,
) -> str:
    payload = json.dumps(
        schema_descriptor(
            connection,
            include_names=include_names,
            business_only=business_only,
        ),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_control_schema(connection: sqlite3.Connection, database_uuid: str, now: str) -> None:
    for statement in CONTROL_DDL:
        connection.execute(statement)
    actual = schema_fingerprint(
        connection,
        include_names=CONTROL_TABLES | CONTROL_TRIGGERS,
    )
    if actual != CONTROL_SCHEMA_FINGERPRINT:
        raise ControlSchemaError(
            "Checked-in control fingerprint does not match CONTROL_DDL: "
            f"expected {CONTROL_SCHEMA_FINGERPRINT}, got {actual}"
        )
    connection.execute(
        """INSERT INTO fs_migration_control (
               singleton, schema_version, schema_fingerprint, database_uuid, created_at
           ) VALUES (1, ?, ?, ?, ?)""",
        (CONTROL_SCHEMA_VERSION, CONTROL_SCHEMA_FINGERPRINT, database_uuid, now),
    )
    connection.execute(
        """INSERT INTO fs_migration_lock (
               lock_name, owner_id, lease_expires_at, fence_token, updated_at
           ) VALUES ('schema', NULL, NULL, 0, ?)""",
        (now,),
    )


def verify_control_schema(connection: sqlite3.Connection) -> tuple[str, str]:
    names = _object_names(connection)
    present = names.intersection(CONTROL_TABLES | CONTROL_TRIGGERS)
    expected = CONTROL_TABLES | CONTROL_TRIGGERS
    if present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        raise ControlSchemaError(
            f"Control schema shape is incomplete (missing={missing}, extra={extra})"
        )
    actual = schema_fingerprint(connection, include_names=expected)
    row = connection.execute(
        """SELECT schema_version, schema_fingerprint, database_uuid
           FROM fs_migration_control WHERE singleton = 1"""
    ).fetchone()
    if row is None:
        raise ControlSchemaError("Control row singleton=1 is missing")
    version, stored, database_uuid = row
    if version != CONTROL_SCHEMA_VERSION:
        raise ControlSchemaError(
            f"Unsupported control schema version {version!r}; expected 1"
        )
    if stored != CONTROL_SCHEMA_FINGERPRINT or actual != CONTROL_SCHEMA_FINGERPRINT:
        raise ControlSchemaError(
            "Control schema fingerprint mismatch: "
            f"stored={stored}, actual={actual}, expected={CONTROL_SCHEMA_FINGERPRINT}"
        )
    if not isinstance(database_uuid, str) or not database_uuid:
        raise ControlSchemaError("Database UUID is missing")
    return database_uuid, actual


def assert_fingerprint(
    connection: sqlite3.Connection,
    expected: str,
    *,
    business_only: bool = False,
    include_names: Iterable[str] | None = None,
    label: str,
) -> None:
    actual = schema_fingerprint(
        connection,
        business_only=business_only,
        include_names=include_names,
    )
    if actual != expected:
        raise SchemaMismatchError(
            f"{label} fingerprint mismatch: expected {expected}, got {actual}"
        )
