"""Typed failures returned by the operator migration CLI."""


class MigrationError(RuntimeError):
    """Base class for a fail-closed migration decision."""

    code = "MIGRATION_ERROR"


class GraphError(MigrationError):
    code = "GRAPH_INVALID"


class ChecksumError(MigrationError):
    code = "CHECKSUM_DRIFT"


class SchemaMismatchError(MigrationError):
    code = "SCHEMA_MISMATCH"


class ControlSchemaError(MigrationError):
    code = "CONTROL_SCHEMA_MISMATCH"


class RevisionStateError(MigrationError):
    code = "REVISION_STATE_INVALID"


class LeaseBusyError(MigrationError):
    code = "LEASE_BUSY"


class StaleFenceError(MigrationError):
    code = "STALE_FENCE"


class BackupVerificationError(MigrationError):
    code = "BACKUP_UNVERIFIED"


class TopologyError(MigrationError):
    code = "TOPOLOGY_UNSUPPORTED"


class OperationCancelled(MigrationError):
    code = "OPERATION_CANCELLED"
