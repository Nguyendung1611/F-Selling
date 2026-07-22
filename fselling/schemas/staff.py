from typing import Optional

from pydantic import BaseModel


class StaffCreate(BaseModel):
    username: str
    password: str


class StaffOut(BaseModel):
    id: int
    username: str
    shop_id: int
    is_active: bool
