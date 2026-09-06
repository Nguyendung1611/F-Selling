"""Operator CLI for explicit, fail-closed F-Selling schema operations."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .coordinator import MigrationCoordinator
from .errors import MigrationError
from .topology import StaticInventory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fselling-migrate")
    parser.add_argument(
        "--database",
        default=os.getenv("DB_PATH"),
        help="SQLite file (or set DB_PATH)",
    )
    parser.add_argument("--active-machines", type=int)
    parser.add_argument("--sqlite-files", type=int)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("status")
    plan = subcommands.add_parser("plan")
    plan.add_argument("target", nargs="?", default="head")
    subcommands.add_parser("check")
    init = subcommands.add_parser("init")
    init.add_argument("--request-id")
    adopt = subcommands.add_parser("adopt-legacy")
    adopt.add_argument("--backup", required=True)
    adopt.add_argument("--request-id")
    upgrade = subcommands.add_parser("upgrade")
    upgrade.add_argument("target", nargs="?", default="head")
    upgrade.add_argument("--request-id")
    subcommands.add_parser("verify")
    return parser


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.database:
        print("ERROR: --database or DB_PATH is required", file=sys.stderr)
        return 2
    inventory = None
    if args.active_machines is not None or args.sqlite_files is not None:
        inventory = StaticInventory(args.active_machines, args.sqlite_files, "cli")
    coordinator = MigrationCoordinator(Path(args.database), inventory_provider=inventory)
    try:
        if args.command == "status":
            _print(coordinator.status().as_dict())
        elif args.command == "plan":
            _print({"pending_revisions": list(coordinator.plan(args.target))})
        elif args.command == "check":
            _print(coordinator.check().as_dict())
        elif args.command == "init":
            _print({"applied_revisions": coordinator.init(request_id=args.request_id)})
        elif args.command == "adopt-legacy":
            backup = coordinator.adopt_legacy(
                args.backup,
                request_id=args.request_id,
            )
            _print(
                {
                    "adopted": True,
                    "backup": str(backup.path),
                    "backup_sha256": backup.sha256,
                    "backup_size": backup.size,
                }
            )
        elif args.command == "upgrade":
            _print(
                {
                    "applied_revisions": coordinator.upgrade(
                        args.target,
                        request_id=args.request_id,
                    )
                }
            )
        elif args.command == "verify":
            _print(coordinator.verify().as_dict())
        return 0
    except MigrationError as exc:
        _print({"ok": False, "code": exc.code, "error": str(exc)})
        return 2
    except Exception as exc:
        _print({"ok": False, "code": type(exc).__name__, "error": str(exc)})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
