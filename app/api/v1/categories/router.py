from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.categories.schemas import CreateCategoryRequest, UpdateCategoryRequest
from app.api.v1.categories.service import CategoryService
from app.utils.response import success

router = APIRouter(tags=["Categories"])
service = CategoryService()


@router.get("")
def list_categories(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all categories for the current user (custom + defaults)."""
    cats = service.list(db, str(current_user.id))
    return success(cats)


@router.post("", status_code=201)
def create_category(
    data: CreateCategoryRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a custom category."""
    cat = service.create(db, str(current_user.id), data)
    return success(cat, message="Category created")


@router.get("/{category_id}")
def get_category(
    category_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get a single category by ID."""
    cat = service.get_by_id(db, category_id, str(current_user.id))
    return success(cat)


@router.put("/{category_id}")
def update_category(
    category_id: str,
    data: UpdateCategoryRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update a custom category. Default categories cannot be modified."""
    cat = service.update(db, category_id, str(current_user.id), data)
    return success(cat, message="Category updated")


@router.delete("/{category_id}")
def delete_category(
    category_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a custom category. Default categories cannot be deleted."""
    service.delete(db, category_id, str(current_user.id))
    return success(None, message="Category deleted")
