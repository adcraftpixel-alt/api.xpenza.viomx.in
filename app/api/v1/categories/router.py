from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.categories.schemas import CreateCategoryRequest, UpdateCategoryRequest
from app.api.v1.categories.service import CategoryService
from app.utils.response import success

router = APIRouter(tags=["Categories"])
service = CategoryService()


class AddKeywordRequest(BaseModel):
    keyword: str


@router.get("")
def list_categories(
    family_group_id: Optional[str] = Query(
        None, description="Set => shared family categories; omit => personal"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Flat list of categories for the current user (or a family group)."""
    return success(service.list(db, str(current_user.id), family_group_id))


@router.get("/tree")
def list_categories_tree(
    family_group_id: Optional[str] = Query(
        None, description="Set => shared family tree; omit => personal tree"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Hierarchical tree of categories (roots with nested children up to 3 levels)."""
    return success(service.list_tree(db, str(current_user.id), family_group_id))


@router.post("", status_code=201)
def create_category(
    data: CreateCategoryRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a category. Pass parent_id to create a sub-category or child."""
    cat = service.create(db, str(current_user.id), data)
    return success(cat, message="Category created")


@router.get("/{category_id}")
def get_category(
    category_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return success(service.get_by_id(db, category_id, str(current_user.id)))


@router.put("/{category_id}")
def update_category(
    category_id: str,
    data: UpdateCategoryRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    cat = service.update(db, category_id, str(current_user.id), data)
    return success(cat, message="Category updated")


@router.post("/{category_id}/keywords", status_code=201)
def add_category_keyword(
    category_id: str,
    data: AddKeywordRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add a keyword alias so chat auto-categorisation routes items here."""
    kw = service.add_keyword(db, category_id, str(current_user.id), data.keyword)
    return success(kw, message="Keyword added")


@router.delete("/keywords/{keyword_id}")
def delete_category_keyword(
    keyword_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Remove a keyword alias from a category."""
    service.delete_keyword(db, keyword_id, str(current_user.id))
    return success(None, message="Keyword removed")


@router.post("/seed-defaults", status_code=201)
def seed_default_categories(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Seed the full default category set for the current user.
    Safe to call multiple times — skips categories that already exist."""
    count = service.seed_defaults(db, str(current_user.id))
    return success({"created": count}, message=f"{count} default categories added")


@router.delete("/{category_id}")
def delete_category(
    category_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a category and all its children (cascade)."""
    service.delete(db, category_id, str(current_user.id))
    return success(None, message="Category deleted")
