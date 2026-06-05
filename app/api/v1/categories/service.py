from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.category import Category
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError, ValidationError
from app.api.v1.categories.schemas import CreateCategoryRequest, UpdateCategoryRequest

MAX_LEVEL = 2  # 0=root, 1=sub-parent, 2=child — three levels max

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


def _cat_to_dict(c: Category, include_children: bool = False) -> dict:
    d = {
        "id":         str(c.id),
        "user_id":    str(c.user_id),
        "parent_id":  str(c.parent_id) if c.parent_id else None,
        "name":       c.name,
        "icon":       c.icon,
        "color":      c.color,
        "level":      c.level,
        "is_default": c.is_default,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
    if include_children:
        d["children"] = [_cat_to_dict(ch, include_children=True) for ch in c.children]
    return d


class CategoryService:

    # ── Flat list (all user categories, no tree) ──────────────────────────────

    def list(self, db: Session, user_id: str) -> List[dict]:
        cats = (
            db.query(Category)
            .filter(Category.user_id == user_id)
            .order_by(Category.level, Category.is_default.desc(), Category.name)
            .all()
        )
        return [_cat_to_dict(c) for c in cats]

    # ── Hierarchical tree (roots + nested children) ───────────────────────────

    def list_tree(self, db: Session, user_id: str) -> List[dict]:
        """Return only root-level categories (level=0) with children nested inside."""
        roots = (
            db.query(Category)
            .filter(Category.user_id == user_id, Category.level == 0)
            .order_by(Category.is_default.desc(), Category.name)
            .all()
        )
        return [_cat_to_dict(r, include_children=True) for r in roots]

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, db: Session, user_id: str, data: CreateCategoryRequest) -> dict:
        level = 0
        if data.parent_id:
            parent = db.query(Category).filter(Category.id == data.parent_id).first()
            if not parent:
                raise NotFoundError("Parent category not found")
            if str(parent.user_id) != str(user_id):
                raise ForbiddenError("Access denied to parent category")
            level = parent.level + 1
            if level > MAX_LEVEL:
                raise ValidationError(
                    f"Maximum category depth is {MAX_LEVEL + 1} levels. "
                    "Cannot create a child under a level-{parent.level} category."
                )

        existing = (
            db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.name == data.name,
                Category.parent_id == data.parent_id,
            )
            .first()
        )
        if existing:
            raise ConflictError(f"Category '{data.name}' already exists at this level")

        cat = Category(
            user_id=user_id,
            parent_id=data.parent_id,
            name=data.name,
            icon=data.icon,
            color=data.color,
            level=level,
            is_default=False,
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return _cat_to_dict(cat)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_id(self, db: Session, category_id: str, user_id: str) -> dict:
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _cat_to_dict(cat, include_children=True)

    # ── Update ────────────────────────────────────────────────────────────────

    def update(
        self, db: Session, category_id: str, user_id: str, data: UpdateCategoryRequest
    ) -> dict:
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        updated = data.model_dump(exclude_unset=True)

        # ── Handle parent change (drag-drop to sub-category) ──────────────────
        if 'parent_id' in updated:
            new_parent_id = updated['parent_id']
            if new_parent_id:
                # Moving under a new parent
                if new_parent_id == category_id:
                    raise ValidationError("A category cannot be its own parent")
                parent = db.query(Category).filter(Category.id == new_parent_id).first()
                if not parent:
                    raise NotFoundError("Target parent category not found")
                if str(parent.user_id) != str(user_id):
                    raise ForbiddenError("Access denied to target category")
                if parent.level >= MAX_LEVEL:
                    raise ValidationError(
                        f"Cannot nest deeper — maximum {MAX_LEVEL + 1} levels allowed"
                    )
                cat.parent_id = new_parent_id
                cat.level = parent.level + 1
            else:
                # Promoting back to root (empty string = move to top level)
                cat.parent_id = None
                cat.level = 0

        # ── Rename ────────────────────────────────────────────────────────────
        if data.name is not None:
            duplicate = (
                db.query(Category)
                .filter(
                    Category.user_id == user_id,
                    Category.name == data.name,
                    Category.parent_id == cat.parent_id,
                    Category.id != category_id,
                )
                .first()
            )
            if duplicate:
                raise ConflictError(f"Category '{data.name}' already exists at this level")
            cat.name = data.name
        if data.icon is not None:
            cat.icon = data.icon
        if data.color is not None:
            cat.color = data.color
        db.commit()
        db.refresh(cat)
        return _cat_to_dict(cat)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, db: Session, category_id: str, user_id: str) -> bool:
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        # CASCADE on the FK handles child deletion automatically
        db.delete(cat)
        db.commit()
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_descendant_ids(self, db: Session, category_id: str) -> List[str]:
        """Return category_id plus IDs of all descendants (max 3 levels)."""
        ids = [str(category_id)]
        children = (
            db.query(Category.id)
            .filter(Category.parent_id == category_id)
            .all()
        )
        for (child_id,) in children:
            ids.append(str(child_id))
            grandchildren = (
                db.query(Category.id)
                .filter(Category.parent_id == child_id)
                .all()
            )
            for (gc_id,) in grandchildren:
                ids.append(str(gc_id))
        return ids

    # ── Seed defaults ─────────────────────────────────────────────────────────

    def seed_defaults(self, db: Session, user_id: str) -> int:
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
                    parent_id=None,
                    name=defaults["name"],
                    icon=defaults["icon"],
                    color=defaults["color"],
                    level=0,
                    is_default=False,
                )
                db.add(cat)
                created += 1
        if created:
            db.commit()
        return created
