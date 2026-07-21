from typing import Optional

from pydantic import BaseModel


class ShopCreate(BaseModel):
    name: str
    business_address: Optional[str] = None
    tax_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    bank_account_no: str
    bank_account_name: Optional[str] = None
    bank_code: str
