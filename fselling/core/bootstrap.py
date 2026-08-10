"""Post-verification application seeds.

Schema creation and migration deliberately do not live here.  Operators use
``python -m fselling.migration.cli``; web startup calls the read-only verifier
before this module is allowed to seed application data.
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from .. import models
from .database import SessionLocal
from .security import hash_password


def seed_admin(db: Session) -> None:
    """Synchronize the break-glass admin only after schema verification."""
    initial_password = os.getenv("ADMIN_INITIAL_PASSWORD")
    admin = db.query(models.User).filter(models.User.username == "admin").first()

    if initial_password and len(initial_password) >= 8:
        hashed_pw = hash_password(initial_password)
        if not admin:
            admin = models.User(
                username="admin",
                hashed_password=hashed_pw,
                role="ADMIN",
                is_verified=True,
            )
            db.add(admin)
            print("[SEED] Created admin account from ADMIN_INITIAL_PASSWORD.")
        else:
            admin.hashed_password = hashed_pw
            admin.role = "ADMIN"
            admin.is_verified = True
            admin.failed_login_count = 0
            admin.locked_until = None
            print("[SEED] Synchronized admin password from ADMIN_INITIAL_PASSWORD.")
        db.commit()
    elif not admin:
        print(
            "[SEED] Skipped admin: ADMIN_INITIAL_PASSWORD must contain "
            "at least 8 characters."
        )


def initialize_application_data() -> None:
    """Run non-schema startup work after the migration verifier returns GO."""
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
