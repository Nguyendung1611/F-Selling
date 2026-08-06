"""Schema JSON cho tab cài đặt chương trình khách thân thiết."""
from typing import Optional

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, field_validator


class LoyaltyProgramUpdate(BaseModel):
    """Cập nhật từng phần; field không gửi được giữ nguyên.

    Các tỷ lệ được phép để ``null`` khi chương trình đang tắt. Service ghép
    dữ liệu cũ + dữ liệu mới rồi mới kiểm tra, vì chỉ nhìn riêng request sẽ
    không biết một cấu hình cập nhật từng phần đã đủ bốn tỷ lệ hay chưa.
    """

    model_config = ConfigDict(extra="forbid")

    # Những ô này quyết định trực tiếp giá trị tiền của điểm. Dùng kiểu strict
    # để JSON ``1.5``, ``1.0`` hay chuỗi ``"1"`` không bị Pydantic âm thầm đổi
    # thành số nguyên. Giao diện gửi số nguyên thật nên không ảnh hưởng đường
    # lưu bình thường.
    enabled: Optional[StrictBool] = None
    earn_amount: Optional[StrictInt] = None
    earn_points: Optional[StrictInt] = None
    redeem_points: Optional[StrictInt] = None
    redeem_amount: Optional[StrictInt] = None
    min_redeem_points: Optional[StrictInt] = None
    max_redeem_percent: Optional[StrictInt] = None
    expiry_days: Optional[StrictInt] = None

    @field_validator(
        "earn_amount",
        "earn_points",
        "redeem_points",
        "redeem_amount",
        "min_redeem_points",
        "max_redeem_percent",
        "expiry_days",
        mode="before",
    )
    @classmethod
    def reject_boolean_as_number(cls, value):
        """JSON true/false không được Pydantic đổi ngầm thành 1/0."""
        if isinstance(value, bool):
            raise ValueError("Giá trị số không được là true/false")
        return value


__all__ = ["LoyaltyProgramUpdate"]
