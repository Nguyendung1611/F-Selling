from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class Shop(Base):
    __tablename__ = "shops"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    business_address = Column(String, nullable=True)
    tax_code = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    bank_account_no = Column(String)
    bank_account_name = Column(String, nullable=True)
    bank_code = Column(String)  # e.g. VCB, MB, etc.
    is_active = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="shops")
    categories = relationship("Category", back_populates="shop")
    products = relationship("Product", back_populates="shop")
    orders = relationship("Order", back_populates="shop")
