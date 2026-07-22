from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="SELLER")  # ADMIN, SELLER hoặc STAFF
    email = Column(String, unique=True, index=True, nullable=True)
    is_verified = Column(Boolean, default=False)
    session_id = Column(String, nullable=True)
    verification_code = Column(String, nullable=True)
    verification_code_expires = Column(DateTime, nullable=True)
    # Chỉ có giá trị với role=STAFF: shop mà nhân viên này được gán để bán hàng.
    # NULL với ADMIN/SELLER. Một nhân viên chỉ thuộc đúng một shop.
    staff_shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True, index=True)

    shops = relationship("Shop", back_populates="owner", foreign_keys="Shop.owner_id")
    staff_shop = relationship("Shop", foreign_keys=[staff_shop_id])
