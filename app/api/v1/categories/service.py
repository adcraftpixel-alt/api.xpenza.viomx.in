from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.category import Category
from app.models.category_keyword import CategoryKeyword
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError, ValidationError
from app.api.v1.categories.schemas import CreateCategoryRequest, UpdateCategoryRequest

MAX_LEVEL = 2  # 0=root, 1=sub-parent, 2=child — three levels max


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
        # Keyword aliases that drive chat auto-categorisation for this node
        "keywords": [
            {"id": str(k.id), "keyword": k.keyword, "source": k.source}
            for k in (c.keywords or [])
        ],
    }
    if include_children:
        d["children"] = [_cat_to_dict(ch, include_children=True) for ch in c.children]
    return d


class CategoryService:

    # ── Flat list (all user categories, no tree) ──────────────────────────────

    def list(
        self, db: Session, user_id: str, family_group_id: Optional[str] = None
    ) -> List[dict]:
        q = db.query(Category)
        if family_group_id:
            q = q.filter(Category.family_group_id == family_group_id)
        else:
            q = q.filter(
                Category.user_id == user_id, Category.family_group_id.is_(None)
            )
        cats = q.order_by(
            Category.level, Category.is_default.desc(), Category.name
        ).all()
        return [_cat_to_dict(c) for c in cats]

    # ── Hierarchical tree (roots + nested children) ───────────────────────────

    def list_tree(
        self, db: Session, user_id: str, family_group_id: Optional[str] = None
    ) -> List[dict]:
        """Return only root-level categories (level=0) with children nested inside.

        Personal scope (family_group_id=None) excludes shared family categories;
        family scope returns the shared tree for that group.
        """
        q = db.query(Category).filter(Category.level == 0)
        if family_group_id:
            q = q.filter(Category.family_group_id == family_group_id)
        else:
            q = q.filter(
                Category.user_id == user_id, Category.family_group_id.is_(None)
            )
        roots = q.order_by(Category.is_default.desc(), Category.name).all()
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

    def get_root_id(self, db: Session, category_id: str) -> str:
        """Walk up the parent chain and return the main (root, level 0) ancestor's id.

        Budgets attach only to main categories, so any sub/leaf category passed in
        is resolved to the root it belongs to (e.g. 'Restaurants' -> 'Food').
        """
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        hops = 0  # depth is capped at 3 levels; guard against cycles anyway
        while cat.parent_id and hops < MAX_LEVEL + 1:
            parent = db.query(Category).filter(Category.id == cat.parent_id).first()
            if not parent:
                break
            cat = parent
            hops += 1
        return str(cat.id)

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

    # ── Keyword aliases ─────────────────────────────────────────────────────────

    def _owned_category(self, db: Session, category_id: str, user_id: str) -> Category:
        """Fetch a category the caller is allowed to manage (personal or own family)."""
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        if cat.family_group_id:
            # Shared family category — caller must belong to that group
            from app.api.v1.family.service import FamilyService
            group = FamilyService()._get_user_group(db, user_id)
            if not group or str(group.id) != str(cat.family_group_id):
                raise ForbiddenError("Access denied")
        elif str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return cat

    def add_keyword(self, db: Session, category_id: str, user_id: str, keyword: str) -> dict:
        self._owned_category(db, category_id, user_id)
        kw = " ".join((keyword or "").lower().split())
        if not kw:
            raise ValidationError("Keyword cannot be empty")
        if len(kw) > 100:
            raise ValidationError("Keyword too long")
        existing = (
            db.query(CategoryKeyword)
            .filter(CategoryKeyword.category_id == category_id, CategoryKeyword.keyword == kw)
            .first()
        )
        if existing:
            raise ConflictError(f"Keyword '{kw}' already exists for this category")
        row = CategoryKeyword(category_id=category_id, keyword=kw, source="user")
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": str(row.id), "keyword": row.keyword, "source": row.source}

    def delete_keyword(self, db: Session, keyword_id: str, user_id: str) -> bool:
        row = db.query(CategoryKeyword).filter(CategoryKeyword.id == keyword_id).first()
        if not row:
            raise NotFoundError("Keyword not found")
        # Validate the caller owns the parent category
        self._owned_category(db, str(row.category_id), user_id)
        db.delete(row)
        db.commit()
        return True

    # ── Seed defaults ─────────────────────────────────────────────────────────

    def seed_defaults(self, db: Session, user_id: str) -> int:
        """Seed the canonical 3-level default tree + keyword aliases (personal scope)."""
        from app.api.v1.categories.default_tree import seed_category_tree
        return seed_category_tree(db, user_id=user_id, family_group_id=None)
