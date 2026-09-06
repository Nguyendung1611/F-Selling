"""SQLite online snapshot plus verified scratch restore for legacy adoption."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import BackupVerificationError


@dataclass(frozen=True)
class VerifiedBackup:
    path: Path
    sha256: str
    size: int


def _readonly(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, isolation_level=None)


def _schema_signature(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT type, name, tbl_name, sql FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
    ).fetchall()
    payload = repr(rows).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_verified_backup(source_path: Path, backup_path: Path) -> VerifiedBackup:
    """Create, restore and integrity-check a snapshot before adoption mutates DB."""
    source_path = source_path.resolve()
    backup_path = backup_path.resolve()
    if not source_path.is_file() or source_path.stat().st_size == 0:
        raise BackupVerificationError(f"Source database is missing or empty: {source_path}")
    if backup_path == source_path:
        raise BackupVerificationError("Backup path must differ from the live database")
    if backup_path.exists():
        raise BackupVerificationError(
            f"Refusing to overwrite an existing adoption backup: {backup_path}"
        )
    if not backup_path.parent.is_dir():
        raise BackupVerificationError(
            f"Backup directory does not exist: {backup_path.parent}"
        )

    source = _readonly(source_path)
    try:
        source_schema = _schema_signature(source)
        destination = sqlite3.connect(str(backup_path), isolation_level=None)
        try:
            source.backup(destination)
        finally:
            destination.close()
    except Exception as exc:
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise BackupVerificationError(f"SQLite backup failed: {exc}") from exc
    finally:
        source.close()

    scratch_fd, scratch_name = tempfile.mkstemp(prefix="fselling_i04_restore_", suffix=".db")
    os.close(scratch_fd)
    scratch_path = Path(scratch_name)
    try:
        snapshot = _readonly(backup_path)
        try:
            restored = sqlite3.connect(str(scratch_path), isolation_level=None)
            try:
                snapshot.backup(restored)
                result = restored.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise BackupVerificationError(
                        f"Scratch restore integrity_check failed: {result!r}"
                    )
                if _schema_signature(restored) != source_schema:
                    raise BackupVerificationError(
                        "Scratch restore schema differs from the live source snapshot"
                    )
            finally:
                restored.close()
        finally:
            snapshot.close()
    except BackupVerificationError:
        raise
    except Exception as exc:
        raise BackupVerificationError(f"Scratch restore rehearsal failed: {exc}") from exc
    finally:
        scratch_path.unlink(missing_ok=True)

    content = backup_path.read_bytes()
    if not content:
        raise BackupVerificationError("Verified backup is unexpectedly empty")
    return VerifiedBackup(
        path=backup_path,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )


def verify_existing_backup(
    backup_path: Path, *, live_database_path: Path | None = None
) -> VerifiedBackup:
    """Integrity-check and scratch-restore an existing immutable adoption backup."""
    backup_path = backup_path.resolve()
    if (
        live_database_path is not None
        and backup_path == live_database_path.expanduser().resolve()
    ):
        raise BackupVerificationError("Backup path must differ from the live database")
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise BackupVerificationError(
            f"Existing adoption backup is missing or empty: {backup_path}"
        )
    source = _readonly(backup_path)
    scratch_fd, scratch_name = tempfile.mkstemp(
        prefix="fselling_i04_existing_restore_", suffix=".db"
    )
    os.close(scratch_fd)
    scratch_path = Path(scratch_name)
    try:
        expected_schema = _schema_signature(source)
        restored = sqlite3.connect(str(scratch_path), isolation_level=None)
        try:
            source.backup(restored)
            result = restored.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupVerificationError(
                    f"Existing backup integrity_check failed: {result!r}"
                )
            if _schema_signature(restored) != expected_schema:
                raise BackupVerificationError(
                    "Existing backup scratch restore schema mismatch"
                )
        finally:
            restored.close()
    except BackupVerificationError:
        raise
    except Exception as exc:
        raise BackupVerificationError(
            f"Existing backup scratch restore rehearsal failed: {exc}"
        ) from exc
    finally:
        source.close()
        scratch_path.unlink(missing_ok=True)
    content = backup_path.read_bytes()
    return VerifiedBackup(
        path=backup_path,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )
