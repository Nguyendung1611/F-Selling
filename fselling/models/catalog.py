from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"))
    is_active = Column(Boolean, default=True)

    shop = relationship("Shop", back_populates="categories")
    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, index=True, nullable=True)  # Mã SP tự sinh hoặc nhập
    # Mã vạch in trên bao bì (EAN-13/UPC/Code128). Tách riêng khỏi `code` vì
    # `code` là mã nội bộ tự sinh dạng SP-<timestamp>. NULL = chưa gán mã vạch;
    # duy nhất trong phạm vi một shop (unique index ix_products_shop_barcode).
    barcode = Column(String(64), index=True, nullable=True)
    name = Column(String, index=True)
    price = Column(Float)
    stock = Column(Integer, default=0)
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    shop_id = Column(Integer, ForeignKey("shops.id"))

    category = relationship("Category", back_populates="products")
    shop = relationship("Shop", back_populates="products")


class Voucher(Base):
    __tablename__ = "vouchers"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"))
    discount_type = Column(String)  # 'percentage' hoặc 'flat'
    discount_value = Column(Float)
    min_order_value = Column(Float, default=0)
    max_discount = Column(Float, default=0)  # Cho percentage
    usage_limit = Column(Integer, default=-1)  # -1 là ko giới hạn
    usage_count = Column(Integer, default=0)
    expires_at = Column(String, nullable=True)  # YYYY-MM-DD
