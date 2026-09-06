"""Schema JSON cho tab cài đặt chương trình khách thân thiết."""
from typing import Optional

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, field_validator

from ..core.numeric_limits import MAX_SAFE_VND
from .money import BasisPointPercent, ExactVND


class LoyaltyProgramUpdate(BaseModel):
    """Cập nhật từng phần; field không gửi được giữ nguyên.

    Các tỷ lệ được phép để ``null`` khi chương trình đang tắt. Service ghép
    dữ liệu cũ + dữ liệu mới rồi mới kiểm tra, vì chỉ nhìn riêng request sẽ
    không biết một cấu hình cập nhật từng phần đã đủ bốn tỷ lệ hay chưa.
    """

    model_config = ConfigDict(extra="forbid")

    # VND accepts only exactly-integral compatibility representations.  Point
    # and day counters remain strict integers.  The visible percentage is
    # normalized through integer basis points (at most two decimal places).
    enabled: Optional[StrictBool] = None
    earn_amount: Optional[ExactVND] = None
    earn_points: Optional[StrictInt] = None
    redeem_points: Optional[StrictInt] = None
    redeem_amount: Optional[ExactVND] = None
    min_redeem_points: Optional[StrictInt] = None
    max_redeem_percent: Optional[BasisPointPercent] = None
    expiry_days: Optional[StrictInt] = None

    @field_validator(
        "earn_points",
        "redeem_points",
        "min_redeem_points",
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
