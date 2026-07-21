"""Engine / Session / Base dùng chung cho toàn bộ ứng dụng."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import BASE_DIR

# Đường dẫn DB có thể cấu hình qua biến môi trường DB_PATH (dùng cho volume khi deploy).
db_path = os.getenv("DB_PATH") or os.path.join(BASE_DIR, "fselling_v4.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
