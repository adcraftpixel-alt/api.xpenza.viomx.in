from pydantic import BaseModel
from typing import Optional


class CreateFAQRequest(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "General"
    order: int = 0
    is_active: bool = True


class UpdateFAQRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    order: Optional[int] = None
    is_active: Optional[bool] = None
