import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..core.database import Base


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True)
    name = Column(String)
    phone = Column(String, index=True)
    address = Column(String, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    shop = relationship("Shop")

    # SĐT là duy nhất trong phạm vi một shop: nhập lại SĐT cũ -> nhận ra khách cũ.
    __table_args__ = (
        UniqueConstraint("shop_id", "phone", name="uq_customer_shop_phone"),
    )
