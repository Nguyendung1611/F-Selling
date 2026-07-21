import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class SystemLog(Base):
    __tablename__ = "system_logs"
    id = Column(Integer, primary_key=True, index=True)
    # Có thể null nếu action từ hệ thống hoặc chưa login
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, index=True)
    details = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
