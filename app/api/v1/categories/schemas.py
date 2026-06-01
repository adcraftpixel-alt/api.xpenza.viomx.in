from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class CreateCategoryRequest(BaseModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class CategoryResponse(BaseModel):
    id: str
    user_id: str
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    is_default: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
