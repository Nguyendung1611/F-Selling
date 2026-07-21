import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"))
    total_amount = Column(Float)
    discount_amount = Column(Float, default=0)
    voucher_code = Column(String, nullable=True)
    payment_method = Column(String, default="transfer")  # 'transfer' or 'cash'
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    shop = relationship("Shop", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_name = Column(String)
    price = Column(Float)
    quantity = Column(Integer)
    order = relationship("Order", back_populates="items")
