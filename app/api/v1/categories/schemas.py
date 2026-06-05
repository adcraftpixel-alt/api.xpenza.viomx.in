from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class CreateCategoryRequest(BaseModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    parent_id: Optional[str] = None   # omit for root; set for sub-parent or child


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    parent_id: Optional[str] = None          # set to move category; use "" to promote back to root


class CategoryResponse(BaseModel):
    id: str
    user_id: str
    parent_id: Optional[str] = None
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    level: int
    is_default: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CategoryTreeNode(BaseModel):
    """A category with its nested children (up to 2 levels deep)."""
    id: str
    user_id: str
    parent_id: Optional[str] = None
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    level: int
    is_default: bool
    created_at: Optional[datetime] = None
    children: List["CategoryTreeNode"] = []

    class Config:
        from_attributes = True


CategoryTreeNode.model_rebuild()
