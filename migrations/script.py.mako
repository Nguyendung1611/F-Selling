"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade(connection, before_statement=None):
    raise NotImplementedError("Write self-contained SQLite DDL")


def verify(connection):
    raise NotImplementedError("Write a revision-local verifier")


def downgrade():
    raise RuntimeError("F-Selling I04 migrations are forward-only")
