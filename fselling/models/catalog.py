import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
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
    # Giá vốn bình quân gia quyền, cập nhật mỗi lần nhập kho có kèm đơn giá.
    # NULL = chưa khai bao giờ, KHÁC HẲN 0 = hàng được tặng. Báo cáo lãi gộp
    # phải loại NULL ra và đếm riêng, không được quy về 0.
    cost_price = Column(Float, nullable=True)
    stock = Column(Integer, default=0)
    image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    shop_id = Column(Integer, ForeignKey("shops.id"))

    # F5: bật theo dõi lô + hạn sử dụng cho riêng sản phẩm này.
    # CỐ Ý là tùy chọn từng sản phẩm chứ không bật cho cả shop: ly nhựa và túi
    # nilon không có hạn sử dụng, ép khai lô cho chúng là làm khổ người nhập
    # hàng vô cớ. Sản phẩm tắt cờ này chạy y hệt như trước khi có F5.
    track_batches = Column(Boolean, nullable=False, default=False)

    # F6: biến thể (size/màu). Mỗi biến thể là một DÒNG Product đầy đủ, không
    # phải một bảng con - nhờ vậy tồn kho, lô hạn, giá vốn, đơn hàng, trả hàng
    # và kiểm kê chạy y nguyên như cũ mà không phải sửa gì.
    #
    # Hai cột luôn ĐI CÙNG NHAU: cả hai NULL = sản phẩm đơn lẻ (đại đa số hàng
    # trong tiệm tạp hóa), cả hai có giá trị = một biến thể của nhóm.
    # `variant_group` chính là tên người dùng gõ ở ô "Tên sản phẩm", còn `name`
    # được server ghép thành "<nhóm> - <biến thể>" để giữ nguyên ràng buộc tên
    # duy nhất theo shop (ix_products_shop_name) mà không bắt ai gõ hai lần.
    variant_group = Column(String(200), nullable=True, index=True)
    variant_name = Column(String(100), nullable=True)

    category = relationship("Category", back_populates="products")
    shop = relationship("Shop", back_populates="products")
    batches = relationship("ProductBatch", back_populates="product")


class ProductBatch(Base):
    """Một lô hàng đã nhập: cùng sản phẩm, cùng hạn sử dụng, cùng giá nhập.

    Đây là NGUỒN SỰ THẬT về tồn kho của sản phẩm có `track_batches`.
    `Product.stock` trở thành bản sao được cập nhật trong CÙNG transaction với
    lô - không phải hai người ghi độc lập, mà một hàm duy nhất ghi cả hai
    (`inventory_service.ghi_ton_kho`). `doi_chieu_ton_kho()` kiểm lại để lệch
    thì lộ ra chứ không âm thầm.

    `expiry_date` lưu dạng chuỗi 'YYYY-MM-DD' như `Voucher.expires_at` - so
    sánh chuỗi theo định dạng đó là so sánh đúng thứ tự ngày, và tránh hẳn bài
    toán múi giờ mà `KIEN_TRUC.md` đã nêu ở phần hiển thị ngày giờ.
    """

    __tablename__ = "product_batches"
    __table_args__ = (
        # Bán hàng luôn hỏi "lô nào của sản phẩm này hết hạn sớm nhất mà còn
        # hàng" - index theo đúng thứ tự đó.
        Index("ix_product_batches_product_expiry", "product_id", "expiry_date"),
    )
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    # NULL = lô không có hạn sử dụng (hàng nhập trước khi bật cờ theo dõi).
    # Lô không hạn được xếp SAU CÙNG khi trừ FEFO.
    expiry_date = Column(String(10), nullable=True)
    quantity = Column(Integer, nullable=False, default=0)
    # Giá nhập của riêng lô này. Bán lô nào thì lãi tính theo giá lô đó.
    cost_price = Column(Float, nullable=True)
    note = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    product = relationship("Product", back_populates="batches")


class StockWriteOff(Base):
    """Một phiếu hủy hàng: hàng ra khỏi kho mà KHÔNG sinh doanh thu.

    Ba nghiệp vụ dễ nhầm với nhau, và đây là cái thứ tư:

    | Nghiệp vụ | Hàng đi đâu | Tiền |
    |---|---|---|
    | Bán | Ra khỏi kho, tới khách | Vào |
    | Xuất kho (`adjust_stock` delta âm) | Ra khỏi kho, không nói đi đâu | Không ghi nhận gì |
    | Trả hàng | Từ khách quay về kho | Ra |
    | **Hủy** | Ra khỏi kho, bỏ đi | **Lỗ đúng bằng giá vốn** |

    Phải có bảng riêng chứ không dùng lại phiếu xuất kho: xuất kho không ghi lý
    do và không có chỗ nào chốt giá vốn, nên số hàng đó biến mất khỏi báo cáo và
    lãi bị thổi lên đúng bằng phần vốn đã mất. Đó cũng là lý do phiếu hủy chốt
    `cost_price` xuống TỪNG DÒNG như `order_items` làm lúc bán.
    """

    __tablename__ = "stock_write_offs"
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    # EXPIRED / DAMAGED / LOST - chốt danh sách trong write_off_service.
    reason = Column(String(20), nullable=False)
    note = Column(String(200), nullable=True)
    total_quantity = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Bấm hai lần là trừ kho hai lần, nên phải chống lặp như phiếu trả hàng.
    idempotency_key = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    items = relationship("StockWriteOffItem", back_populates="write_off")


class StockWriteOffItem(Base):
    """Một dòng của phiếu hủy: đúng một lô (hoặc cả sản phẩm nếu không theo lô).

    `cost_price` CHỐT tại thời điểm hủy, lấy từ đúng lô bị hủy. Tra ngược
    `Product.cost_price` lúc làm báo cáo thì mỗi lần nhập một lô giá khác là số
    lỗ của các tháng trước tự đổi - đúng bài học ở mục 13 của KIEN_TRUC.md.

    NULL nghĩa là lô đó chưa ai khai giá vốn, KHÁC HẲN 0. Báo cáo phải loại
    nguyên phiếu và đếm riêng, không được quy về 0.
    """

    __tablename__ = "stock_write_off_items"
    id = Column(Integer, primary_key=True)
    write_off_id = Column(
        Integer, ForeignKey("stock_write_offs.id"), nullable=False
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    # Chụp lại tên như `order_items.product_name`: sản phẩm đổi tên hoặc bị xóa
    # thì phiếu hủy cũ vẫn đọc được.
    product_name = Column(String, nullable=True)
    # NULL = sản phẩm không theo dõi lô.
    batch_id = Column(Integer, ForeignKey("product_batches.id"), nullable=True)
    expiry_date = Column(String(10), nullable=True)
    quantity = Column(Integer, nullable=False)
    cost_price = Column(Float, nullable=True)

    write_off = relationship("StockWriteOff", back_populates="items")


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
