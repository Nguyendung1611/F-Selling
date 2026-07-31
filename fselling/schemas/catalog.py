from typing import List, Optional

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    price: float
    category_id: int
    image_url: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: str
    is_active: bool


class VoucherCreate(BaseModel):
    code: str
    discount_type: str
    discount_value: float
    min_order_value: float = 0
    max_discount: float = 0
    usage_limit: int = -1
    expires_at: Optional[str] = None


class StockAdjust(BaseModel):
    delta: int  # >0 nhập kho, <0 xuất kho
    # Đơn giá của lô đang nhập, dùng để tính lại giá vốn bình quân gia quyền.
    # None = không khai (giữ nguyên giá vốn cũ); 0 = hàng tặng, là một đơn giá
    # thật và phải kéo bình quân xuống. JSON body giữ được sự khác biệt đó, khác
    # với form multipart nơi field rỗng rơi về default.
    unit_cost: Optional[float] = None


class StocktakeItem(BaseModel):
    """Một dòng đếm thực tế trong phiên kiểm kê.

    `stock_snapshot` là tồn kho mà máy khách nhìn thấy lúc BẮT ĐẦU đếm sản phẩm
    này. Server so lại với tồn hiện tại: nếu khác nghĩa là có bán hoặc nhập xen
    vào giữa lúc đếm, và số vừa đếm không còn phản ánh đúng thực tế nữa - dòng
    đó bị bỏ qua thay vì ghi đè làm mất số hàng vừa bán.
    """

    product_id: int
    counted: int
    stock_snapshot: int


class StocktakeApply(BaseModel):
    items: List[StocktakeItem]
