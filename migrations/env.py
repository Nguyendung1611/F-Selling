"""Alembic environment driven exclusively by the F-Selling coordinator."""
from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError(
            "F-Selling Alembic requires a coordinator-injected SQLAlchemy Connection"
        )
    if not context.config.attributes.get("coordinator_begin_immediate"):
        raise RuntimeError("F-Selling Alembic requires coordinator BEGIN IMMEDIATE")
    if not connection.in_transaction():
        raise RuntimeError("Injected Alembic connection is not in a transaction")

    context.configure(
        connection=connection,
        target_metadata=None,
        transactional_ddl=True,
        transaction_per_migration=False,
        version_table="alembic_version",
    )
    # The external transaction is detected by Alembic and remains coordinator-owned.
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline Alembic execution is disabled for F-Selling")
run_migrations_online()
