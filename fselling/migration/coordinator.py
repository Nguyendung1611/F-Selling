"""Fail-closed I04 coordinator around a real, externally-connected Alembic run."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from .backup import VerifiedBackup, create_verified_backup, verify_existing_backup
from .errors import (
    BackupVerificationError,
    ControlSchemaError,
    LeaseBusyError,
    MigrationError,
    OperationCancelled,
    RevisionStateError,
    SchemaMismatchError,
    StaleFenceError,
)
from .graph import RevisionGraph, RevisionSpec, load_graph
from .schema import (
    CONTROL_TABLES,
    OPERATIONAL_TABLES,
    assert_fingerprint,
    create_control_schema,
    schema_fingerprint,
    verify_control_schema,
)
from .topology import EnvironmentInventory, InventoryProvider, verify_supported_topology

FaultHook = Callable[[str, str], None]
CancelCheck = Callable[[], bool]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class Lease:
    owner_id: str
    fence_token: int
    lease_expires_at: str


@dataclass(frozen=True)
class VerificationReport:
    database_path: str
    database_uuid: str
    current_revision: str
    head_revision: str
    revision_count: int
    business_fingerprint: str
    control_fingerprint: str
    topology_source: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatabaseStatus:
    classification: str
    current_revision: str | None
    head_revision: str
    pending_revisions: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["pending_revisions"] = list(self.pending_revisions)
        return value


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro",
        uri=True,
        isolation_level=None,
        timeout=5,
    )


def _writable(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), isolation_level=None, timeout=5)
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _raw(connection: Connection) -> sqlite3.Connection:
    return connection.connection.driver_connection


class MigrationCoordinator:
    """One-file coordinator; target mutations are explicit operator work only."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        project_root: str | Path | None = None,
        inventory_provider: InventoryProvider | None = None,
        lease_seconds: int = 120,
        fault_hook: FaultHook | None = None,
        cancel_check: CancelCheck | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.inventory_provider = inventory_provider or EnvironmentInventory()
        self.lease_seconds = lease_seconds
        self.fault_hook = fault_hook
        self.cancel_check = cancel_check
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self.clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def _timestamp(self, value: datetime | None = None) -> str:
        return (value or self._now()).astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")

    def _graph(self) -> RevisionGraph:
        return load_graph(self.project_root)

    def _preflight(self) -> tuple[RevisionGraph, str]:
        graph = self._graph()
        topology = verify_supported_topology(self.inventory_provider)
        return graph, topology.source

    @staticmethod
    def _business_names(connection: sqlite3.Connection) -> set[str]:
        return {
            row[0]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE name NOT LIKE 'sqlite_%'
                     AND name <> 'alembic_version'
                     AND name NOT LIKE 'fs_migration_%'"""
            )
        }

    @staticmethod
    def _control_presence(connection: sqlite3.Connection) -> set[str]:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'fs_migration_%'"
            )
        }.intersection(CONTROL_TABLES)

    def _new_engine(self, *, memory: bool = False):
        url = "sqlite+pysqlite:///:memory:" if memory else (
            "sqlite+pysqlite:///" + self.database_path.as_posix()
        )
        return create_engine(
            url,
            poolclass=NullPool,
            connect_args={"timeout": 5, "check_same_thread": False},
        )

    def _alembic_config(
        self,
        connection: Connection,
        *,
        before_statement: Callable[[], None] | None = None,
    ) -> Config:
        config = Config(str(self.project_root / "alembic.ini"))
        config.set_main_option("script_location", str(self.project_root / "migrations"))
        config.attributes["connection"] = connection
        config.attributes["coordinator_begin_immediate"] = True
        config.attributes["before_statement"] = before_statement
        return config

    def _expected_fingerprints(self, graph: RevisionGraph) -> tuple[str, str]:
        engine = self._new_engine(memory=True)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                config = self._alembic_config(connection)
                command.upgrade(config, graph.root.revision)
                graph.root.module.verify(connection)
                business = schema_fingerprint(_raw(connection), business_only=True)
                command.upgrade(config, graph.head.revision)
                for revision in graph.revisions[1:]:
                    revision.module.verify(connection)
                operational = schema_fingerprint(
                    _raw(connection), include_names=OPERATIONAL_TABLES
                )
                connection.rollback()
                return business, operational
        finally:
            engine.dispose()

    def _ensure_control_initialized(
        self, connection: sqlite3.Connection, *, allow_business: bool
    ) -> bool:
        present = self._control_presence(connection)
        if present:
            if present != CONTROL_TABLES:
                raise ControlSchemaError(f"Partial control schema present: {sorted(present)}")
            verify_control_schema(connection)
            return False
        if self._business_names(connection) and not allow_business:
            raise SchemaMismatchError(
                "Database is not empty; use adopt-legacy after exact verification"
            )
        connection.execute("BEGIN IMMEDIATE")
        try:
            create_control_schema(connection, str(uuid.uuid4()), self._timestamp())
            connection.execute("COMMIT")
            return True
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _initialize_adoption_control(
        self,
        *,
        request_id: str | None,
        target_revision: str,
        backup: VerifiedBackup,
    ) -> str:
        """Atomically persist control v1 and an unambiguous adoption intent."""
        effective_request_id = request_id or f"adopt-backup:{backup.sha256}"
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if self._control_presence(connection):
                raise RevisionStateError("Adoption control appeared concurrently")
            create_control_schema(connection, str(uuid.uuid4()), self._timestamp())
            connection.execute(
                """INSERT INTO fs_migration_requests (
                       request_id, command, target_revision, input_digest,
                       state, started_at
                   ) VALUES (?, 'adopt-legacy', ?, ?, 'RUNNING', ?)""",
                (
                    effective_request_id,
                    target_revision,
                    backup.sha256,
                    self._timestamp(),
                ),
            )
            connection.execute("COMMIT")
            return effective_request_id
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _adoption_intent(
        connection: sqlite3.Connection,
    ) -> tuple[str, str, str, str] | None:
        rows = connection.execute(
            """SELECT request_id, target_revision, input_digest, state
               FROM fs_migration_requests WHERE command='adopt-legacy'"""
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise RevisionStateError("Multiple adoption intents are ambiguous")
        return rows[0]

    def acquire_lease(self, owner_id: str | None = None) -> Lease:
        owner_id = owner_id or str(uuid.uuid4())
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            verify_control_schema(connection)
            now = self._timestamp()
            row = connection.execute(
                """SELECT owner_id, lease_expires_at, fence_token
                   FROM fs_migration_lock WHERE lock_name = 'schema'"""
            ).fetchone()
            if row is None:
                raise ControlSchemaError("Schema lock row is missing")
            current_owner, expires_at, fence_token = row
            if current_owner and current_owner != owner_id and expires_at and expires_at > now:
                raise LeaseBusyError("Schema lease is held by another active owner")
            new_fence = int(fence_token) if (
                current_owner == owner_id and expires_at and expires_at > now
            ) else int(fence_token) + 1
            expiry = self._timestamp(self._now() + timedelta(seconds=self.lease_seconds))
            connection.execute(
                """UPDATE fs_migration_lock
                   SET owner_id=?, lease_expires_at=?, fence_token=?, updated_at=?
                   WHERE lock_name='schema'""",
                (owner_id, expiry, new_fence, now),
            )
            connection.execute("COMMIT")
            return Lease(owner_id, new_fence, expiry)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def renew_lease(self, lease: Lease) -> Lease:
        """Heartbeat between commits if this owner still has the current fence."""
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            # Expiry is not ownership loss. If nobody has acquired a newer
            # fence, this BEGIN IMMEDIATE transaction may safely heartbeat the
            # same fence even just after a long revision/checkpoint commit.
            self._assert_fence(connection, lease, require_unexpired=False)
            expiry = self._timestamp(self._now() + timedelta(seconds=self.lease_seconds))
            result = connection.execute(
                """UPDATE fs_migration_lock SET lease_expires_at=?, updated_at=?
                   WHERE lock_name='schema' AND owner_id=? AND fence_token=?""",
                (expiry, self._timestamp(), lease.owner_id, lease.fence_token),
            )
            if result.rowcount != 1:
                raise StaleFenceError("Lease heartbeat lost its fence")
            connection.execute("COMMIT")
            return Lease(lease.owner_id, lease.fence_token, expiry)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    heartbeat = renew_lease

    def release_lease(self, lease: Lease) -> None:
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                """UPDATE fs_migration_lock
                   SET owner_id=NULL, lease_expires_at=NULL, updated_at=?
                   WHERE lock_name='schema' AND owner_id=? AND fence_token=?""",
                (self._timestamp(), lease.owner_id, lease.fence_token),
            )
            if result.rowcount != 1:
                raise StaleFenceError("Cannot release a lease owned by a newer fence")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _assert_fence(
        self,
        connection: sqlite3.Connection,
        lease: Lease,
        *,
        require_unexpired: bool,
    ) -> None:
        sql = (
            "SELECT lease_expires_at FROM fs_migration_lock "
            "WHERE lock_name='schema' AND owner_id=? AND fence_token=?"
        )
        row = connection.execute(sql, (lease.owner_id, lease.fence_token)).fetchone()
        if row is None or (require_unexpired and (not row[0] or row[0] <= self._timestamp())):
            raise StaleFenceError("Migration fence is stale")

    @staticmethod
    def _safe_error(error: Exception) -> tuple[str, str]:
        raw_code = error.code if isinstance(error, MigrationError) else "UNEXPECTED_ERROR"
        code = re.sub(r"[^A-Z0-9_]", "_", str(raw_code).upper())[:64]
        digest = hashlib.sha256(
            f"{type(error).__name__}:{error}".encode("utf-8", errors="replace")
        ).hexdigest()
        return code or "UNEXPECTED_ERROR", digest

    @staticmethod
    def _failure_state(error: Exception) -> str:
        return "FAILED_BLOCKED" if isinstance(
            error, (SchemaMismatchError, RevisionStateError, ControlSchemaError)
        ) else "FAILED_RETRYABLE"

    def _begin_request(
        self, lease: Lease, request_id: str | None, command_name: str, target: str
    ) -> str:
        if request_id is None:
            return "NEW"
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=True)
            row = connection.execute(
                """SELECT command, target_revision, state
                   FROM fs_migration_requests WHERE request_id=?""",
                (request_id,),
            ).fetchone()
            if row:
                if row[0] != command_name or row[1] != target:
                    raise RevisionStateError("request_id is bound to another invocation")
                if row[2] == "SUCCEEDED":
                    connection.execute("COMMIT")
                    return "SUCCEEDED"
                if row[2] != "RUNNING":
                    raise RevisionStateError("request_id belongs to a terminal failed invocation")
                connection.execute("COMMIT")
                return "RUNNING"
            connection.execute(
                """INSERT INTO fs_migration_requests (
                       request_id, command, target_revision, state, started_at
                   ) VALUES (?, ?, ?, 'RUNNING', ?)""",
                (request_id, command_name, target, self._timestamp()),
            )
            connection.execute("COMMIT")
            return "NEW"
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _finish_request_without_revision(
        self, lease: Lease, request_id: str | None
    ) -> None:
        if request_id is None:
            return
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=False)
            connection.execute(
                """UPDATE fs_migration_requests
                   SET state='SUCCEEDED', finished_at=?
                   WHERE request_id=? AND state='RUNNING'""",
                (self._timestamp(), request_id),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _fail_request(
        self, lease: Lease, request_id: str | None, error: Exception
    ) -> None:
        if request_id is None:
            return
        code, digest = self._safe_error(error)
        state = self._failure_state(error)
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=False)
            connection.execute(
                """UPDATE fs_migration_requests SET state=?, finished_at=?,
                       error_code=?, error_digest=?
                   WHERE request_id=? AND state='RUNNING'""",
                (state, self._timestamp(), code, digest, request_id),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _start_attempt(
        self,
        lease: Lease,
        *,
        operation_key: str,
        command_name: str,
        target_revision: str | None,
        request_id: str | None,
    ) -> int:
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=True)
            attempt_no = int(connection.execute(
                """SELECT COALESCE(MAX(attempt_no),0)+1
                   FROM fs_migration_attempts WHERE operation_key=?""",
                (operation_key,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO fs_migration_attempts (
                       operation_key, attempt_no, request_id, command,
                       target_revision, state, fence_token, started_at
                   ) VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, ?)""",
                (operation_key, attempt_no, request_id, command_name,
                 target_revision, lease.fence_token, self._timestamp()),
            )
            connection.execute("COMMIT")
            return attempt_no
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _finish_failed_attempt(
        self, lease: Lease, operation_key: str, attempt_no: int, error: Exception
    ) -> None:
        code, digest = self._safe_error(error)
        state = self._failure_state(error)
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=False)
            result = connection.execute(
                """UPDATE fs_migration_attempts SET state=?, finished_at=?,
                       error_code=?, error_digest=?
                   WHERE operation_key=? AND attempt_no=? AND state='RUNNING'""",
                (state, self._timestamp(), code, digest, operation_key, attempt_no),
            )
            if result.rowcount != 1:
                raise RevisionStateError("Attempt is missing or already terminal")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _revision_state(
        connection: sqlite3.Connection, graph: RevisionGraph
    ) -> tuple[str | None, tuple[str, ...]]:
        version_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        journal = connection.execute(
            """SELECT revision, down_revision, checksum, database_uuid
               FROM fs_migration_revision_journal ORDER BY sequence"""
        ).fetchall()
        if not version_exists:
            if journal:
                raise RevisionStateError("Journal exists without alembic_version")
            return None, ()
        versions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(versions) != 1:
            raise RevisionStateError(
                f"alembic_version must contain exactly one row, got {len(versions)}"
            )
        current = versions[0][0]
        if len(journal) > len(graph.revisions):
            raise RevisionStateError("Journal is longer than checked-in graph")
        database_uuid, _ = verify_control_schema(connection)
        for actual, expected in zip(journal, graph.revisions):
            if actual != (
                expected.revision, expected.down_revision, expected.checksum, database_uuid
            ):
                raise RevisionStateError("Journal is not the exact checked-in linear prefix")
        applied = tuple(row[0] for row in journal)
        if not applied or current != applied[-1]:
            raise RevisionStateError("alembic_version disagrees with revision journal")
        return current, applied

    def _fault(self, stage: str, revision: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(stage, revision)

    def _apply_revision(
        self,
        revision: RevisionSpec,
        lease: Lease,
        *,
        command_name: str,
        request_id: str | None,
        final_for_request: bool,
    ) -> None:
        operation_key = f"revision:{revision.revision}"
        attempt_no = self._start_attempt(
            lease,
            operation_key=operation_key,
            command_name=command_name,
            target_revision=revision.revision,
            request_id=request_id,
        )
        engine = self._new_engine()
        committed = False
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                raw = _raw(connection)
                self._assert_fence(raw, lease, require_unexpired=True)

                def before_statement() -> None:
                    # While BEGIN IMMEDIATE is held, no newer writer can steal
                    # the fence. Expiry alone therefore cannot invalidate this txn.
                    self._assert_fence(raw, lease, require_unexpired=False)
                    if self.cancel_check is not None and self.cancel_check():
                        raise OperationCancelled("Migration was cancelled before commit")

                config = self._alembic_config(connection, before_statement=before_statement)
                command.upgrade(config, revision.revision)
                self._fault("after_ddl", revision.revision)
                self._fault("after_version", revision.revision)
                database_uuid, _ = verify_control_schema(raw)
                raw.execute(
                    """INSERT INTO fs_migration_revision_journal (
                           revision, down_revision, checksum, database_uuid,
                           operation_key, attempt_no, fence_token, applied_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (revision.revision, revision.down_revision, revision.checksum,
                     database_uuid, operation_key, attempt_no, lease.fence_token,
                     self._timestamp()),
                )
                self._fault("after_journal", revision.revision)
                revision.module.verify(connection)
                self._fault("after_verify", revision.revision)
                result = raw.execute(
                    """UPDATE fs_migration_attempts SET state='SUCCEEDED', finished_at=?
                       WHERE operation_key=? AND attempt_no=? AND state='RUNNING'""",
                    (self._timestamp(), operation_key, attempt_no),
                )
                if result.rowcount != 1:
                    raise RevisionStateError("Cannot finalize successful revision attempt")
                if final_for_request and request_id is not None:
                    result = raw.execute(
                        """UPDATE fs_migration_requests SET state='SUCCEEDED', finished_at=?
                           WHERE request_id=? AND state='RUNNING'""",
                        (self._timestamp(), request_id),
                    )
                    if result.rowcount != 1:
                        raise RevisionStateError("Cannot finalize migration request")
                self._assert_fence(raw, lease, require_unexpired=False)
                connection.commit()
                committed = True
                self._fault("after_commit", revision.revision)
        except Exception as exc:
            if not committed:
                self._finish_failed_attempt(lease, operation_key, attempt_no, exc)
            else:
                # The caller may have lost only the CLI response. Preserve the
                # RUNNING invocation so the same request_id can resume later.
                setattr(exc, "_fselling_durable_commit", True)
            raise
        finally:
            engine.dispose()

    def _run_upgrade(
        self, graph: RevisionGraph, target_revision: str, command_name: str,
        request_id: str | None
    ) -> list[str]:
        connection = _readonly(self.database_path)
        try:
            verify_control_schema(connection)
            current, applied = self._revision_state(connection, graph)
        finally:
            connection.close()
        target_index = graph.index(target_revision)
        current_index = -1 if current is None else graph.index(current)
        if target_index < current_index:
            raise RevisionStateError("Downgrade is not supported")
        pending = list(graph.revisions[len(applied): target_index + 1])
        if not pending and request_id is None:
            return []
        lease = self.acquire_lease()
        try:
            request_state = self._begin_request(
                lease, request_id, command_name, target_revision
            )
            if request_state == "SUCCEEDED":
                return []
            if not pending:
                self._finish_request_without_revision(lease, request_id)
                return []
            applied_now: list[str] = []
            for index, revision in enumerate(pending):
                self._apply_revision(
                    revision,
                    lease,
                    command_name=command_name,
                    request_id=request_id,
                    final_for_request=index == len(pending) - 1,
                )
                applied_now.append(revision.revision)
                if index != len(pending) - 1:
                    lease = self.renew_lease(lease)
            return applied_now
        except Exception as exc:
            # A crash/fault after commit is deliberately returned to the caller,
            # but its request and revision are already durable successes.
            probe = _readonly(self.database_path)
            try:
                durable, _ = self._revision_state(probe, graph)
            except Exception:
                durable = None
            finally:
                probe.close()
            if durable != target_revision and not getattr(
                exc, "_fselling_durable_commit", False
            ):
                self._fail_request(lease, request_id, exc)
            raise
        finally:
            self.release_lease(lease)

    def init(self, *, request_id: str | None = None) -> list[str]:
        graph, _ = self._preflight()
        self.database_path.parent.mkdir(parents=False, exist_ok=True)
        connection = _writable(self.database_path)
        try:
            created = self._ensure_control_initialized(connection, allow_business=False)
            current, _ = self._revision_state(connection, graph)
        finally:
            connection.close()
        if created:
            self._fault("after_control_init", graph.root.revision)
        if current is not None:
            return []
        return self._run_upgrade(graph, graph.root.revision, "init", request_id)

    def _verify_legacy_data(self, connection, graph: RevisionGraph) -> None:
        verifier = getattr(graph.revisions[1].module, "verify_legacy_preconditions", None)
        if verifier is not None:
            try:
                verifier(connection)
            except Exception as exc:
                raise SchemaMismatchError("Legacy data invariants are not adoptable") from exc

    def adopt_legacy(
        self, backup_path: str | Path | None, *, request_id: str | None = None
    ) -> VerifiedBackup:
        graph, _ = self._preflight()
        if backup_path is None:
            raise BackupVerificationError("adopt-legacy requires --backup")
        backup_path = Path(backup_path).expanduser().resolve()
        if backup_path == self.database_path:
            raise BackupVerificationError(
                "Backup path must differ from the live database"
            )
        if not self.database_path.is_file():
            raise SchemaMismatchError("Legacy database does not exist")
        expected_business, _ = self._expected_fingerprints(graph)
        connection = _readonly(self.database_path)
        current = None
        intent = None
        try:
            control = self._control_presence(connection)
            if control and control != CONTROL_TABLES:
                raise ControlSchemaError("Partial control schema blocks adoption")
            if control:
                verify_control_schema(connection)
                current, _ = self._revision_state(connection, graph)
                intent = self._adoption_intent(connection)
                if intent is None:
                    raise RevisionStateError(
                        "Managed database has no durable adoption intent"
                    )
            assert_fingerprint(
                connection, expected_business, business_only=True,
                label="legacy 9cf7106"
            )
            self._verify_legacy_data(connection, graph)
        finally:
            connection.close()

        if not control:
            # The first invocation owns snapshot creation. An existing file is
            # never evidence that it belongs to this live database; an orphan
            # left before control/intent commit must be replaced with a new path.
            backup = create_verified_backup(self.database_path, backup_path)
            created = True
        else:
            # Only a durable intent may authorize reusing an existing snapshot.
            # A terminal/ambiguous state fails immediately; digest, target and
            # invocation identity are checked after restore/integrity rehearsal.
            assert intent is not None
            intent_request, intent_target, intent_digest, intent_state = intent
            expected_state = "RUNNING" if current is None else "SUCCEEDED"
            if (
                intent_state != expected_state
                or not isinstance(intent_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", intent_digest) is None
            ):
                raise RevisionStateError(
                    "Durable adoption intent does not match resume/replay"
                )
            backup = verify_existing_backup(
                backup_path, live_database_path=self.database_path
            )
            expected_request_id = request_id or f"adopt-backup:{backup.sha256}"
            if (
                intent_target != graph.root.revision
                or backup.sha256 != intent_digest
                or expected_request_id != intent_request
            ):
                raise RevisionStateError(
                    "Durable adoption intent does not match verified backup replay"
                )
            effective_request_id = intent_request
            created = False

        snapshot = _readonly(backup.path)
        try:
            assert_fingerprint(
                snapshot, expected_business, business_only=True,
                label="verified adoption backup"
            )
            self._verify_legacy_data(snapshot, graph)
        finally:
            snapshot.close()

        if current is not None:
            # A managed revision is replayable only after the SUCCEEDED intent,
            # verified backup digest and request identity all matched above.
            return backup

        if not control:
            effective_request_id = self._initialize_adoption_control(
                request_id=request_id,
                target_revision=graph.root.revision,
                backup=backup,
            )
        if created:
            self._fault("after_control_init", graph.root.revision)

        lease = self.acquire_lease()
        operation_key = f"adopt:{graph.root.revision}"
        try:
            request_state = self._begin_request(
                lease, effective_request_id, "adopt-legacy", graph.root.revision
            )
            if request_state == "SUCCEEDED":
                return backup
            attempt_no = self._start_attempt(
                lease, operation_key=operation_key, command_name="adopt-legacy",
                target_revision=graph.root.revision, request_id=effective_request_id
            )
            engine = self._new_engine()
            committed = False
            try:
                with engine.connect() as sa_connection:
                    sa_connection.exec_driver_sql("BEGIN IMMEDIATE")
                    raw = _raw(sa_connection)
                    self._assert_fence(raw, lease, require_unexpired=True)
                    command.stamp(
                        self._alembic_config(sa_connection), graph.root.revision
                    )
                    database_uuid, _ = verify_control_schema(raw)
                    raw.execute(
                        """INSERT INTO fs_migration_revision_journal (
                               revision, down_revision, checksum, database_uuid,
                               operation_key, attempt_no, fence_token, applied_at
                           ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)""",
                        (graph.root.revision, graph.root.checksum, database_uuid,
                         operation_key, attempt_no, lease.fence_token, self._timestamp()),
                    )
                    graph.root.module.verify(sa_connection)
                    assert_fingerprint(
                        raw, expected_business, business_only=True,
                        label="adopted legacy 9cf7106"
                    )
                    result = raw.execute(
                        """UPDATE fs_migration_attempts SET state='SUCCEEDED', finished_at=?
                           WHERE operation_key=? AND attempt_no=? AND state='RUNNING'""",
                        (self._timestamp(), operation_key, attempt_no),
                    )
                    if result.rowcount != 1:
                        raise RevisionStateError("Cannot finalize adoption attempt")
                    result = raw.execute(
                        """UPDATE fs_migration_requests SET state='SUCCEEDED', finished_at=?
                           WHERE request_id=? AND state='RUNNING'""",
                        (self._timestamp(), effective_request_id),
                    )
                    if result.rowcount != 1:
                        raise RevisionStateError("Cannot finalize adoption request")
                    self._assert_fence(raw, lease, require_unexpired=False)
                    sa_connection.commit()
                    committed = True
                    self._fault("after_commit", graph.root.revision)
            except Exception as exc:
                if not committed:
                    self._finish_failed_attempt(lease, operation_key, attempt_no, exc)
                    # The request row is the immutable durable adoption intent,
                    # not an individual execution. A transient attempt remains
                    # terminal FAILED_RETRYABLE while the RUNNING intent permits
                    # the same request_id to create the next attempt. Ambiguous
                    # or structurally blocked failures terminate the intent.
                    if self._failure_state(exc) == "FAILED_BLOCKED":
                        self._fail_request(lease, effective_request_id, exc)
                raise
            finally:
                engine.dispose()
        finally:
            self.release_lease(lease)
        return backup

    def upgrade(
        self, target: str = "head", *, request_id: str | None = None
    ) -> list[str]:
        graph, _ = self._preflight()
        if not self.database_path.is_file():
            raise RevisionStateError("Database does not exist; run init")
        target_revision = graph.head.revision if target == "head" else target
        return self._run_upgrade(graph, target_revision, "upgrade", request_id)

    def verify(self) -> VerificationReport:
        graph, topology_source = self._preflight()
        if not self.database_path.is_file():
            raise SchemaMismatchError("Database does not exist")
        expected_business, expected_operational = self._expected_fingerprints(graph)
        connection = _readonly(self.database_path)
        try:
            database_uuid, control_fingerprint = verify_control_schema(connection)
            current, applied = self._revision_state(connection, graph)
            if current != graph.head.revision or len(applied) != len(graph.revisions):
                raise RevisionStateError("Database is not at the checked-in head")
            assert_fingerprint(connection, expected_business, business_only=True,
                               label="business schema")
            assert_fingerprint(connection, expected_operational,
                               include_names=OPERATIONAL_TABLES,
                               label="I04 operational schema")
            for revision in graph.revisions:
                revision.module.verify(connection)
            return VerificationReport(
                str(self.database_path), database_uuid, current, graph.head.revision,
                len(applied), schema_fingerprint(connection, business_only=True),
                control_fingerprint, topology_source
            )
        finally:
            connection.close()

    def check(self) -> DatabaseStatus:
        graph, _ = self._preflight()
        if not self.database_path.exists():
            return DatabaseStatus("MISSING", None, graph.head.revision,
                                  tuple(r.revision for r in graph.revisions),
                                  "Run init on a fresh database path")
        connection = _readonly(self.database_path)
        try:
            control = self._control_presence(connection)
            business = self._business_names(connection)
            if not control:
                if not business:
                    return DatabaseStatus("FRESH", None, graph.head.revision,
                                          tuple(r.revision for r in graph.revisions),
                                          "Run init, upgrade head, verify")
                expected_business, _ = self._expected_fingerprints(graph)
                assert_fingerprint(connection, expected_business, business_only=True,
                                   label="legacy 9cf7106")
                self._verify_legacy_data(connection, graph)
                return DatabaseStatus("LEGACY_EXACT", None, graph.head.revision,
                                      tuple(r.revision for r in graph.revisions[1:]),
                                      "Run adopt-legacy, upgrade head, verify")
            if control != CONTROL_TABLES:
                raise ControlSchemaError("Partial control schema")
            verify_control_schema(connection)
            current, applied = self._revision_state(connection, graph)
            pending = tuple(r.revision for r in graph.revisions[len(applied):])
            if current is None and business:
                intent = self._adoption_intent(connection)
                if intent is None or intent[3] != "RUNNING":
                    raise RevisionStateError(
                        "Control-only legacy state has no active adoption intent"
                    )
                classification = "ADOPTION_RESUMABLE"
            else:
                classification = "READY" if not pending else "MANAGED_PENDING"
            return DatabaseStatus(classification, current, graph.head.revision, pending,
                                  "verify required" if not pending else "run upgrade head")
        finally:
            connection.close()

    status = check

    def plan(self, target: str = "head") -> tuple[str, ...]:
        status = self.check()
        graph = self._graph()
        target_revision = graph.head.revision if target == "head" else target
        target_index = graph.index(target_revision)
        current_index = -1 if status.current_revision is None else graph.index(
            status.current_revision
        )
        if target_index < current_index:
            raise RevisionStateError("Downgrade is not supported")
        return tuple(r.revision for r in graph.revisions[current_index + 1:target_index + 1])

    def write_checkpoint(
        self, lease: Lease, *, workset_id: int, checkpoint_key: str, value: Any
    ) -> None:
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=True)
            connection.execute(
                """INSERT INTO fs_migration_checkpoints (
                       workset_id, checkpoint_key, value_json, fence_token, updated_at
                   ) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(workset_id, checkpoint_key) DO UPDATE SET
                       value_json=excluded.value_json,
                       fence_token=excluded.fence_token,
                       updated_at=excluded.updated_at""",
                (workset_id, checkpoint_key,
                 json.dumps(value, ensure_ascii=False, sort_keys=True),
                 lease.fence_token, self._timestamp()),
            )
            self._assert_fence(connection, lease, require_unexpired=False)
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def create_campaign(self, lease: Lease, campaign_key: str) -> None:
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=True)
            now = self._timestamp()
            connection.execute(
                """INSERT INTO fs_migration_campaigns (
                       campaign_key, phase, phase_version, state, fence_token,
                       created_at, updated_at
                   ) VALUES (?, 'PREFLIGHT', 0, 'ACTIVE', ?, ?, ?)""",
                (campaign_key, lease.fence_token, now, now),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def advance_campaign(
        self, lease: Lease, campaign_key: str, *, expected_phase: str,
        expected_version: int, next_phase: str
    ) -> None:
        phases = ("PREFLIGHT", "EXPAND", "DUAL_WRITE", "BACKFILL", "RECONCILE",
                  "CUTOVER", "STABILIZE", "CLEANUP")
        if expected_phase not in phases or next_phase not in phases or (
            phases.index(next_phase) != phases.index(expected_phase) + 1
        ):
            raise RevisionStateError("Campaign phases can only advance one step")
        connection = _writable(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, lease, require_unexpired=True)
            result = connection.execute(
                """UPDATE fs_migration_campaigns
                   SET phase=?, phase_version=phase_version+1, fence_token=?, updated_at=?
                   WHERE campaign_key=? AND phase=? AND phase_version=? AND state='ACTIVE'""",
                (next_phase, lease.fence_token, self._timestamp(), campaign_key,
                 expected_phase, expected_version),
            )
            if result.rowcount != 1:
                raise RevisionStateError("Campaign CAS failed")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


def verify_database_for_startup(
    database_path: str | Path, *, inventory_provider: InventoryProvider | None = None
) -> VerificationReport:
    """Read-only web gate. It never creates or alters a target database."""
    return MigrationCoordinator(
        database_path, inventory_provider=inventory_provider
    ).verify()
