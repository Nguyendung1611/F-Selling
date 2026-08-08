"""Chi phí vận hành: danh mục, mẫu nhắc nhở và sổ chi đã trả.

Ba bảng, ba vai trò khác hẳn nhau - đừng gộp:

``expense_categories`` là danh mục do chủ shop tự quản. Danh mục đã có khoản chi
CHỈ được ẩn, không xóa vật lý: SQLite production không bật khóa ngoại (bẫy 32)
nên xóa nhầm không báo lỗi gì cả, chỉ để lại các khoản chi cũ trỏ vào hư không.

``expense_templates`` là MẪU NHẮC NHỞ, không phải chứng từ. Nó không sinh ra
đồng nào cho tới khi chủ shop bấm ghi nhận. Cố ý không tự sinh khoản chi theo
lịch: máy trên Fly.io tự tắt khi vắng khách nên job "ngày 5 hàng tháng" gần như
không bao giờ nổ (xem `routers/cron.py`), và một bút toán tiền tự mọc ra mà chủ
shop chưa nhìn qua là thứ không ai đối chiếu nổi về sau.

``operating_expenses`` là chứng từ tiền thật. Sau khi ghi thì bất biến; khoản đã
rút tiền từ két không hủy được, vì `cash_movements` là sổ chỉ-ghi-thêm và ca có
thể đã đóng với số tiền đếm tay khớp rồi.

**Hai mốc phân bổ luôn có giá trị**, kể cả khoản chi thường: khi không phân bổ
thì cả hai bằng `expense_date`. Nhờ vậy báo cáo chỉ có MỘT đường tính, không có
nhánh `if` nào để quên - phân bổ hay không chỉ là chuyện hai mốc trùng nhau.
"""
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
)
from sqlalchemy.orm import relationship

from ..core.database import Base


class ExpenseCategory(Base):
    """Loại chi phí (Tiền thuê, Điện nước...). Seed sẵn, chủ shop sửa được."""

    __tablename__ = "expense_categories"
    __table_args__ = (
        # Trùng tên trong cùng shop là đường đẻ ra "Điện", "Tiền điện",
        # "điện nước" thành ba cột riêng trong biểu đồ chi phí - biểu đồ đó
        # vụn ra là hết tác dụng.
        Index("ux_expense_categories_shop_name", "shop_id", "name", unique=True),
        Index("ix_expense_categories_shop_active", "shop_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    name = Column(String(120), nullable=False)
    # Ẩn chứ không xóa. Danh mục đã dùng vẫn phải đọc được tên cho báo cáo cũ.
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    expenses = relationship("OperatingExpense", back_populates="category")
    templates = relationship("ExpenseTemplate", back_populates="category")


class ExpenseTemplate(Base):
    """Mẫu chi phí lặp hàng tháng. Chỉ để NHẮC, không tự ghi tiền."""

    __tablename__ = "expense_templates"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_expense_templates_amount_nonnegative"),
        CheckConstraint(
            "day_of_month >= 1 AND day_of_month <= 31",
            name="ck_expense_templates_day_of_month",
        ),
        Index("ix_expense_templates_shop_active", "shop_id", "is_active"),
        Index("ix_expense_templates_category_id", "category_id"),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    category_id = Column(
        Integer, ForeignKey("expense_categories.id"), nullable=False
    )
    name = Column(String(200), nullable=False)
    # Tiền VND lưu số nguyên như phiếu nhập. Đây là số GỢI Ý, người dùng sửa
    # được ở màn ghi nhận - lương tháng nào cũng lệch vì thưởng/phạt.
    amount = Column(Integer, nullable=False, default=0)
    day_of_month = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    note = Column(String(500), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    category = relationship("ExpenseCategory", back_populates="templates")
    expenses = relationship("OperatingExpense", back_populates="template")


class OperatingExpense(Base):
    """Một khoản chi phí vận hành ĐÃ TRẢ. Chứng từ tiền, bất biến."""

    __tablename__ = "operating_expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_operating_expenses_amount_positive"),
        CheckConstraint(
            "method IN ('CASH_SHIFT', 'TRANSFER', 'OUTSIDE')",
            name="ck_operating_expenses_method",
        ),
        # Mốc cuối không được sớm hơn mốc đầu, nếu không số ngày phân bổ ra âm
        # và công thức lũy kế trả về số vô nghĩa.
        CheckConstraint(
            "amortize_end_date >= amortize_start_date",
            name="ck_operating_expenses_amortize_range",
        ),
        # Dòng tiền hỏi "shop này chi bao nhiêu trong khoảng ngày nào".
        Index("ix_operating_expenses_shop_date", "shop_id", "expense_date"),
        # Lãi ròng hỏi khác hẳn: "khoản nào có phần rơi vào khoảng này", tức là
        # lọc theo hai mốc phân bổ chứ không phải ngày chi.
        Index(
            "ix_operating_expenses_shop_amortize",
            "shop_id",
            "amortize_start_date",
            "amortize_end_date",
        ),
        Index("ix_operating_expenses_category_id", "category_id"),
        Index("ix_operating_expenses_template_id", "template_id"),
        Index("ix_operating_expenses_shift_id", "shift_id"),
        # Bấm hai lần là TRỪ KÉT HAI LẦN. Cùng lớp bảo vệ với phiếu hủy hàng và
        # trả nhà cung cấp; index này nằm trong nhóm financial fail-fast.
        Index(
            "ux_operating_expenses_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    category_id = Column(
        Integer, ForeignKey("expense_categories.id"), nullable=False
    )
    # Ghi từ mẫu nào, để ô nhắc biết tháng này đã trả được bao nhiêu trên số
    # phải trả. NULL = khoản lẻ, không thuộc mẫu nào.
    template_id = Column(
        Integer, ForeignKey("expense_templates.id"), nullable=True
    )
    amount = Column(Integer, nullable=False)

    # Ngày tiền RA KHỎI TÚI, là ngày lịch người dùng chọn chứ không phải giờ
    # máy chủ: hôm nay ghi bù khoản đã trả tuần trước thì nó phải rơi vào tuần
    # trước, đừng làm đẹp giả cho hôm nay.
    expense_date = Column(String(10), nullable=False)
    # Khoảng thời gian khoản chi này PHỤC VỤ. Không phân bổ thì cả hai bằng
    # `expense_date` - báo cáo nhờ vậy chỉ có một đường tính duy nhất.
    amortize_start_date = Column(String(10), nullable=False)
    amortize_end_date = Column(String(10), nullable=False)

    method = Column(String(20), nullable=False)
    shift_id = Column(Integer, ForeignKey("cash_shifts.id"), nullable=True)
    cash_movement_id = Column(
        Integer, ForeignKey("cash_movements.id"), nullable=True
    )
    note = Column(String(500), nullable=True)
    reference = Column(String(128), nullable=True)

    idempotency_key = Column(String(128), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )

    # Gõ nhầm thì gỡ được, nhưng CHỈ khi khoản đó không rút tiền từ két. Giữ
    # dòng lại thay vì xóa hẳn để còn truy được ai gỡ và gỡ lúc nào.
    voided_at = Column(DateTime, nullable=True)
    voided_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    category = relationship("ExpenseCategory", back_populates="expenses")
    template = relationship("ExpenseTemplate", back_populates="expenses")


__all__ = ["ExpenseCategory", "ExpenseTemplate", "OperatingExpense"]
