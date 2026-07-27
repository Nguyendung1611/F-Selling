from typing import Optional

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    note: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    note: Optional[str] = None
