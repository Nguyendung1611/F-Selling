"""Request schemas cho nhà cung cấp, phiếu nhập và trả công nợ."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, StrictInt, field_validator

from ..core.numeric_limits import MAX_SAFE_QUANTITY, MAX_SAFE_VND


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=64)
    tax_code: Optional[str] = Field(default=None, max_length=64)
    address: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)
    opening_balance: StrictInt = Field(default=0, ge=0, le=MAX_SAFE_VND)
    opening_date: Optional[str] = Field(default=None, max_length=10)
    opening_due_date: Optional[str] = Field(default=None, max_length=10)
    opening_note: Optional[str] = Field(default=None, max_length=500)
    operation_id: str = Field(min_length=8, max_length=128)


class SupplierUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=64)
    tax_code: Optional[str] = Field(default=None, max_length=64)
    address: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)


class SupplierStatusUpdate(BaseModel):
    is_active: bool


class PurchaseReceiptItemInput(BaseModel):
    product_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(gt=0, le=MAX_SAFE_QUANTITY)
    unit_cost: StrictInt = Field(ge=0, le=MAX_SAFE_VND)
    expiry_date: Optional[str] = Field(default=None, max_length=10)

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        try:
            datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("Hạn sử dụng phải theo định dạng YYYY-MM-DD") from error
        return value.strip()


class PurchaseReceiptCreate(BaseModel):
    supplier_id: StrictInt = Field(gt=0)
    items: List[PurchaseReceiptItemInput] = Field(min_length=1)
    supplier_invoice_number: Optional[str] = Field(default=None, max_length=128)
    received_date: Optional[str] = Field(default=None, max_length=10)
    due_date: Optional[str] = Field(default=None, max_length=10)
    note: Optional[str] = Field(default=None, max_length=500)
    operation_id: str = Field(min_length=8, max_length=128)


class PurchaseReceiptUpdate(BaseModel):
    supplier_id: StrictInt = Field(gt=0)
    items: List[PurchaseReceiptItemInput] = Field(min_length=1)
    supplier_invoice_number: Optional[str] = Field(default=None, max_length=128)
    received_date: Optional[str] = Field(default=None, max_length=10)
    due_date: Optional[str] = Field(default=None, max_length=10)
    note: Optional[str] = Field(default=None, max_length=500)


class PurchaseReceiptConfirm(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128)
    # Dấu vân tay của đúng bản nháp người dùng vừa xem. Bắt buộc gửi lại để
    # server không chốt một nội dung đã bị người khác sửa ở tab/phiên khác.
    draft_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    # Không mặc định 0: đây là quyết định tiền bạc, client phải gửi rõ người
    # dùng đã chọn trả 0 / một phần / toàn bộ.
    paid_amount: StrictInt = Field(ge=0, le=MAX_SAFE_VND)
    method: Optional[Literal["CASH_SHIFT", "TRANSFER", "OUTSIDE"]] = None
    note: Optional[str] = Field(default=None, max_length=500)
    reference: Optional[str] = Field(default=None, max_length=128)


class SupplierPaymentCreate(BaseModel):
    amount: StrictInt = Field(gt=0, le=MAX_SAFE_VND)
    method: Literal["CASH_SHIFT", "TRANSFER", "OUTSIDE"]
    note: Optional[str] = Field(default=None, max_length=500)
    reference: Optional[str] = Field(default=None, max_length=128)
    operation_id: str = Field(min_length=8, max_length=128)


__all__ = [
    "SupplierCreate",
    "SupplierUpdate",
    "SupplierStatusUpdate",
    "SupplierPaymentCreate",
    "PurchaseReceiptItemInput",
    "PurchaseReceiptCreate",
    "PurchaseReceiptUpdate",
    "PurchaseReceiptConfirm",
]
