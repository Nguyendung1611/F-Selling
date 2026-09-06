"""Linear Alembic graph, source checksum and transaction-safety guards."""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from .errors import ChecksumError, GraphError

FORBIDDEN_SQL = (
    "VACUUM",
    "PRAGMA JOURNAL_MODE",
    "PRAGMA WAL_CHECKPOINT",
    "ATTACH DATABASE",
    "DETACH DATABASE",
    "LOAD_EXTENSION",
)
FORBIDDEN_CALLS = ("executescript", "autocommit_block")


@dataclass(frozen=True)
class RevisionSpec:
    revision: str
    down_revision: str | None
    path: Path
    checksum: str
    module: object


@dataclass(frozen=True)
class RevisionGraph:
    revisions: tuple[RevisionSpec, ...]

    @property
    def root(self) -> RevisionSpec:
        return self.revisions[0]

    @property
    def head(self) -> RevisionSpec:
        return self.revisions[-1]

    def index(self, revision: str) -> int:
        for index, item in enumerate(self.revisions):
            if item.revision == revision:
                return index
        raise GraphError(f"Unknown revision: {revision}")


def _source_checksum(path: Path) -> tuple[str, str]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ChecksumError(f"Revision is not valid UTF-8: {path}") from exc
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), normalized


def _validate_revision_source(path: Path, source: str) -> None:
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            if module != "__future__" and not module.startswith("alembic"):
                raise GraphError(
                    f"Revision {path.name} imports mutable/non-Alembic helper {module!r}"
                )
    upper = source.upper()
    for operation in FORBIDDEN_SQL:
        if operation in upper:
            raise GraphError(
                f"Revision {path.name} contains unsupported non-transactional "
                f"operation {operation!r}"
            )
    for call in FORBIDDEN_CALLS:
        if call in source:
            raise GraphError(f"Revision {path.name} uses forbidden call {call!r}")


def load_graph(project_root: Path) -> RevisionGraph:
    manifest_path = project_root / "migrations" / "checksums.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChecksumError(f"Cannot read checksum manifest: {manifest_path}") from exc
    if manifest.get("format") != 1 or not isinstance(manifest.get("revisions"), dict):
        raise ChecksumError("Checksum manifest format must be version 1")

    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    bases = scripts.get_bases()
    heads = scripts.get_heads()
    if len(bases) != 1 or len(heads) != 1:
        raise GraphError(f"Expected one base and one head; bases={bases}, heads={heads}")

    ordered_scripts = list(reversed(list(scripts.walk_revisions())))
    entries = manifest["revisions"]
    revision_ids = {item.revision for item in ordered_scripts}
    if set(entries) != revision_ids:
        raise ChecksumError(
            "Checksum manifest revision set differs from Alembic graph: "
            f"manifest={sorted(entries)}, graph={sorted(revision_ids)}"
        )

    result: list[RevisionSpec] = []
    previous: str | None = None
    for script in ordered_scripts:
        down = script.down_revision
        if down is not None and not isinstance(down, str):
            raise GraphError(f"Branch/merge revision is forbidden: {script.revision}")
        module = script.module
        if getattr(module, "branch_labels", None):
            raise GraphError(f"branch_labels are forbidden: {script.revision}")
        if getattr(module, "depends_on", None):
            raise GraphError(f"depends_on is forbidden: {script.revision}")
        if down != previous:
            raise GraphError(
                f"Graph is not one linear chain at {script.revision}: "
                f"expected down_revision={previous!r}, got {down!r}"
            )
        path = Path(script.path).resolve()
        checksum, source = _source_checksum(path)
        _validate_revision_source(path, source)
        expected = entries[script.revision]
        if expected.get("down_revision") != down:
            raise ChecksumError(
                f"Manifest down_revision drift for {script.revision}"
            )
        if expected.get("path") != path.relative_to(project_root / "migrations").as_posix():
            raise ChecksumError(f"Manifest path drift for {script.revision}")
        if expected.get("sha256") != checksum:
            raise ChecksumError(
                f"Checksum drift for {script.revision}: expected "
                f"{expected.get('sha256')}, got {checksum}"
            )
        if not callable(getattr(module, "upgrade", None)) or not callable(
            getattr(module, "verify", None)
        ):
            raise GraphError(f"Revision {script.revision} must define upgrade and verify")
        result.append(RevisionSpec(script.revision, down, path, checksum, module))
        previous = script.revision
    if not result:
        raise GraphError("Migration graph is empty")
    return RevisionGraph(tuple(result))
