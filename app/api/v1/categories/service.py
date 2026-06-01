from typing import List
from sqlalchemy.orm import Session
from app.models.category import Category
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError
from app.api.v1.categories.schemas import CreateCategoryRequest, UpdateCategoryRequest

DEFAULT_CATEGORIES = [
    {"name": "Food & Dining",     "icon": "🍕", "color": "#EF4444"},
    {"name": "Groceries",         "icon": "🛒", "color": "#22C55E"},
    {"name": "Transport",         "icon": "🚗", "color": "#3B82F6"},
    {"name": "Shopping",          "icon": "👕", "color": "#8B5CF6"},
    {"name": "Bills & Utilities", "icon": "⚡", "color": "#F59E0B"},
    {"name": "Health",            "icon": "🏥", "color": "#10B981"},
    {"name": "Entertainment",     "icon": "🎬", "color": "#EC4899"},
    {"name": "Education",         "icon": "🎓", "color": "#0EA5E9"},
    {"name": "Travel",            "icon": "✈️", "color": "#14B8A6"},
    {"name": "General",           "icon": "💰", "color": "#6B7280"},
]


def _cat_to_dict(c: Category) -> dict:
    return {
        "id": str(c.id),
        "user_id": str(c.user_id),
        "name": c.name,
        "icon": c.icon,
        "color": c.color,
        "is_default": c.is_default,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


class CategoryService:
    def list(self, db: Session, user_id: str) -> List[dict]:
        """Return all categories belonging to the user (includes defaults seeded for them)."""
        cats = (
            db.query(Category)
            .filter(Category.user_id == user_id)
            .order_by(Category.is_default.desc(), Category.name)
            .all()
        )
        return [_cat_to_dict(c) for c in cats]

    def create(self, db: Session, user_id: str, data: CreateCategoryRequest) -> dict:
        existing = (
            db.query(Category)
            .filter(Category.user_id == user_id, Category.name == data.name)
            .first()
        )
        if existing:
            raise ConflictError(f"Category '{data.name}' already exists")
        cat = Category(
            user_id=user_id,
            name=data.name,
            icon=data.icon,
            color=data.color,
            is_default=False,
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return _cat_to_dict(cat)

    def get_by_id(self, db: Session, category_id: str, user_id: str) -> dict:
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _cat_to_dict(cat)

    def update(
        self, db: Session, category_id: str, user_id: str, data: UpdateCategoryRequest
    ) -> dict:
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        if cat.is_default:
            raise ForbiddenError("Cannot modify a default category")
        if data.name is not None:
            # Check uniqueness against other categories for this user
            duplicate = (
                db.query(Category)
                .filter(
                    Category.user_id == user_id,
                    Category.name == data.name,
                    Category.id != category_id,
                )
                .first()
            )
            if duplicate:
                raise ConflictError(f"Category '{data.name}' already exists")
            cat.name = data.name
        if data.icon is not None:
            cat.icon = data.icon
        if data.color is not None:
            cat.color = data.color
        db.commit()
        db.refresh(cat)
        return _cat_to_dict(cat)

    def delete(self, db: Session, category_id: str, user_id: str) -> bool:
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        if cat.is_default:
            raise ForbiddenError("Cannot delete a default category")
        db.delete(cat)
        db.commit()
        return True

    def seed_defaults(self, db: Session, user_id: str) -> int:
        """Seed default categories for a new user. Returns count of categories created."""
        # Find which defaults already exist for this user to avoid duplicates
        existing_names = {
            row.name
            for row in db.query(Category.name)
            .filter(Category.user_id == user_id, Category.is_default == True)  # noqa: E712
            .all()
        }
        created = 0
        for defaults in DEFAULT_CATEGORIES:
            if defaults["name"] not in existing_names:
                cat = Category(
                    user_id=user_id,
                    name=defaults["name"],
                    icon=defaults["icon"],
                    color=defaults["color"],
                    is_default=True,
                )
                db.add(cat)
                created += 1
        if created:
            db.commit()
        return created
