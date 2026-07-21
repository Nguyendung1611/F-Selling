from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="SELLER")  # ADMIN or SELLER
    email = Column(String, unique=True, index=True, nullable=True)
    is_verified = Column(Boolean, default=False)
    session_id = Column(String, nullable=True)
    verification_code = Column(String, nullable=True)
    verification_code_expires = Column(DateTime, nullable=True)
    shops = relationship("Shop", back_populates="owner")
