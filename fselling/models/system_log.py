import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class SystemLog(Base):
    __tablename__ = "system_logs"
    id = Column(Integer, primary_key=True, index=True)
    # Có thể null nếu action từ hệ thống hoặc chưa login
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Dòng mới nên ghi tường minh shop_id khi biết. Đặc biệt ADMIN thao tác trên
    # nhiều shop: chỉ suy từ user_id sẽ hoặc làm log vô hình, hoặc lộ việc của
    # shop khác. NULL giữ tương thích toàn bộ lịch sử cũ.
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True, index=True)
    action = Column(String, index=True)
    details = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
