"""Mockable inventory gate for the supported one-machine/one-file topology."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from .errors import TopologyError


@dataclass(frozen=True)
class TopologySnapshot:
    active_machines: int | None
    sqlite_files: int | None
    source: str


class InventoryProvider(Protocol):
    def snapshot(self) -> TopologySnapshot: ...


class EnvironmentInventory:
    """Read an operator/platform assertion without making a network call.

    Local development has one process and one explicitly selected DB file, so
    it defaults to the supported topology.  Fly must declare both counts; the
    maintenance runbook requires operators to reconcile those assertions with
    platform inventory before every schema-changing command.
    """

    ACTIVE_ENV = "FSELLING_TOPOLOGY_ACTIVE_MACHINES"
    FILE_ENV = "FSELLING_TOPOLOGY_SQLITE_FILES"

    @staticmethod
    def _number(name: str) -> int | None:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return None
        try:
            value = int(raw)
        except ValueError as exc:
            raise TopologyError(f"{name} must be an integer") from exc
        if value < 0:
            raise TopologyError(f"{name} cannot be negative")
        return value

    def snapshot(self) -> TopologySnapshot:
        active = self._number(self.ACTIVE_ENV)
        files = self._number(self.FILE_ENV)
        on_platform = bool(os.getenv("FLY_APP_NAME") or os.getenv("FLY_MACHINE_ID"))
        if not on_platform:
            active = 1 if active is None else active
            files = 1 if files is None else files
            source = "local-environment"
        else:
            source = "platform-environment-assertion"
        return TopologySnapshot(active, files, source)


@dataclass(frozen=True)
class StaticInventory:
    """Test/operator injection; no platform or network access."""

    active_machines: int | None = 1
    sqlite_files: int | None = 1
    source: str = "injected"

    def snapshot(self) -> TopologySnapshot:
        return TopologySnapshot(self.active_machines, self.sqlite_files, self.source)


def verify_supported_topology(provider: InventoryProvider) -> TopologySnapshot:
    snapshot = provider.snapshot()
    if snapshot.active_machines is None or snapshot.sqlite_files is None:
        raise TopologyError(
            "Topology inventory is missing; declare one active machine and one "
            "SQLite file before operating or starting F-Selling"
        )
    if snapshot.active_machines != 1 or snapshot.sqlite_files != 1:
        raise TopologyError(
            "I04 supports exactly one active application machine and one SQLite "
            f"file; inventory reports machines={snapshot.active_machines}, "
            f"files={snapshot.sqlite_files} ({snapshot.source})"
        )
    return snapshot
