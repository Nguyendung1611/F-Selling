"""Shim tương thích: database đã chuyển sang fselling/core/database.py.

Giữ file này để các script/import cũ (`import database`) vẫn chạy.
"""
from fselling.core.database import (  # noqa: F401
    Base,
    SQLALCHEMY_DATABASE_URL,
    SessionLocal,
    db_path,
    engine,
    get_db,
)

__all__ = ["Base", "SessionLocal", "engine", "get_db", "SQLALCHEMY_DATABASE_URL", "db_path"]
