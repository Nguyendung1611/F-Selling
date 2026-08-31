import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from ..core.database import Base


class FnbArea(Base):
    __tablename__ = "fnb_areas"
    __table_args__ = (
        Index("ux_fnb_areas_shop_name_key", "shop_id", "name_key", unique=True),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    name_key = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class FnbTable(Base):
    __tablename__ = "fnb_tables"
    __table_args__ = (
        Index("ux_fnb_tables_area_name_key", "area_id", "name_key", unique=True),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("fnb_areas.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    name_key = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    state_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class FnbServiceSession(Base):
    __tablename__ = "fnb_service_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','PARTIALLY_SETTLED','PAYMENT_PENDING','CLOSED','CANCELLED')",
            name="ck_fnb_sessions_status",
        ),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="OPEN", index=True)
    revision = Column(Integer, nullable=False, default=0)
    merged_into_session_id = Column(
        Integer, ForeignKey("fnb_service_sessions.id"), nullable=True
    )
    opened_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    opened_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    closed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)


class FnbSessionTable(Base):
    __tablename__ = "fnb_session_tables"
    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey("fnb_service_sessions.id"), nullable=False, index=True
    )
    table_id = Column(Integer, ForeignKey("fnb_tables.id"), nullable=False, index=True)
    added_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    released_at = Column(DateTime, nullable=True)


class FnbSessionLine(Base):
    __tablename__ = "fnb_session_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_fnb_session_lines_quantity"),
        CheckConstraint(
            "cancelled_quantity >= 0 AND cancelled_quantity <= quantity",
            name="ck_fnb_session_lines_cancelled",
        ),
    )
    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer, ForeignKey("fnb_service_sessions.id"), nullable=False, index=True
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String(300), nullable=False)
    unit_price_vnd = Column(Integer, nullable=False)
    note = Column(String(500), nullable=True)
    quantity = Column(Integer, nullable=False)
    cancelled_quantity = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    state_version = Column(Integer, nullable=False, default=0)


class FnbActionLog(Base):
    __tablename__ = "fnb_action_logs"
    __table_args__ = (
        Index(
            "ux_fnb_action_shop_operation",
            "shop_id",
            "operation_id",
            unique=True,
        ),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    session_id = Column(
        Integer, ForeignKey("fnb_service_sessions.id"), nullable=True, index=True
    )
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(64), nullable=False)
    operation_id = Column(String(128), nullable=False)
    operation_fingerprint = Column(String(64), nullable=False)
    result_json = Column(Text, nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
