from typing import Optional

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    note: Optional[str] = None
    # F4: tran cong no. None = khong gioi han (mac dinh).
    credit_limit: Optional[float] = None


class CustomerUpdate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    note: Optional[str] = None
    credit_limit: Optional[float] = None


class CustomerStatusUpdate(BaseModel):
    is_active: bool
