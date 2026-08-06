from typing import List, Optional

from pydantic import BaseModel, Field


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
    # Điều chỉnh kho thủ công nằm ngoài phiếu nhập, nên bắt buộc nói rõ lý do
    # để lịch sử không còn những dòng tăng/giảm tồn không thể đối chiếu.
    reason: str = Field(min_length=1, max_length=500)
    # Đơn giá của lô đang nhập, dùng để tính lại giá vốn bình quân gia quyền.
    # None = không khai (giữ nguyên giá vốn cũ); 0 = hàng tặng, là một đơn giá
    # thật và phải kéo bình quân xuống. JSON body giữ được sự khác biệt đó, khác
    # với form multipart nơi field rỗng rơi về default.
    unit_cost: Optional[float] = None
    # F5: hạn sử dụng của lô đang nhập, dạng 'YYYY-MM-DD'. BẮT BUỘC khi nhập
    # hàng cho sản phẩm đã bật theo dõi lô; bỏ qua với sản phẩm khác.
    expiry_date: Optional[str] = None


class StocktakeBatchCount(BaseModel):
    """Số đếm thực tế của MỘT lô, dùng cho sản phẩm có theo dõi hạn sử dụng.

    `quantity_snapshot` đóng đúng vai trò của `stock_snapshot` ở mức sản phẩm:
    số lượng của lô này mà máy khách nhìn thấy lúc bắt đầu đếm. Phải so ở mức
    LÔ chứ không ở mức tổng - hai lô cùng đổi ngược chiều nhau (bán 3 của lô cũ,
    nhập 3 vào lô mới) làm tổng đứng yên trong khi cả hai lô đều đã khác.
    """

    batch_id: int
    counted: int
    quantity_snapshot: int


class StocktakeItem(BaseModel):
    """Một dòng đếm thực tế trong phiên kiểm kê.

    `stock_snapshot` là tồn kho mà máy khách nhìn thấy lúc BẮT ĐẦU đếm sản phẩm
    này. Server so lại với tồn hiện tại: nếu khác nghĩa là có bán hoặc nhập xen
    vào giữa lúc đếm, và số vừa đếm không còn phản ánh đúng thực tế nữa - dòng
    đó bị bỏ qua thay vì ghi đè làm mất số hàng vừa bán.

    Sản phẩm có `track_batches` thì đếm THEO TỪNG LÔ qua `batches`, và hai
    trường `counted` / `stock_snapshot` phải để trống: đặt thẳng một con số tổng
    cho hàng có lô là phá vỡ ràng buộc "tổng lô = tồn kho" mà không có cách nào
    biết phải cộng trừ vào lô nào. Hai kiểu dòng loại trừ nhau, service từ chối
    dòng nào khai lẫn lộn.
    """

    product_id: int
    counted: Optional[int] = None
    stock_snapshot: Optional[int] = None
    batches: Optional[List[StocktakeBatchCount]] = None


class StocktakeApply(BaseModel):
    items: List[StocktakeItem]


class WriteOffItem(BaseModel):
    """Một dòng của phiếu hủy hàng.

    `batch_id` BẮT BUỘC với sản phẩm có theo dõi lô và phải để trống với sản
    phẩm không theo dõi: hủy hàng có lô mà không nói lô nào thì không biết chốt
    giá vốn nào, và cũng không biết hạn nào vừa bị bỏ đi.
    """

    product_id: int
    batch_id: Optional[int] = None
    quantity: int


class WriteOffCreate(BaseModel):
    # EXPIRED / DAMAGED / LOST - danh sách chốt trong write_off_service.
    reason: str
    items: List[WriteOffItem]
    note: Optional[str] = None
    # Một mã cho đúng một lần bấm. Gửi lại cùng mã trả về chính phiếu cũ thay vì
    # trừ kho lần nữa.
    operation_id: Optional[str] = None
