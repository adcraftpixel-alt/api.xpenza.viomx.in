from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_, extract

from app.models.family_group import FamilyGroup, FamilyGroupMember
from app.models.expense import Expense
from app.models.budget import Budget
from app.models.user import User
from app.core.exceptions import NotFoundError, ForbiddenError, BadRequestError
from app.api.v1.family.schemas import CreateGroupRequest, InviteMemberRequest


def _same_phone(a: str, b: str) -> bool:
    """Compare two phone numbers by their last 10 digits (ignores +91 etc.)."""
    da = "".join(ch for ch in (a or "") if ch.isdigit())[-10:]
    db_ = "".join(ch for ch in (b or "") if ch.isdigit())[-10:]
    return bool(da) and da == db_


def _member_to_dict(m: FamilyGroupMember) -> dict:
    return {
        "id": str(m.id),
        "phone": m.phone,
        "name": m.name or (m.user.name if m.user else None),
        "role": m.role,
        "status": m.status,
        "user_id": str(m.user_id) if m.user_id else None,
        "contribution": float(m.contribution or 0),
    }


def _group_to_dict(g: FamilyGroup) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "created_by": str(g.created_by),
        "members": [_member_to_dict(m) for m in g.members],
    }


def _expense_to_dict(e: Expense) -> dict:
    return {
        "id": str(e.id),
        "user_id": str(e.user_id),
        "added_by_user_id": str(e.added_by_user_id) if e.added_by_user_id else str(e.user_id),
        "added_by_name": e.user.name if e.user else "Unknown",
        "category_id": str(e.category_id) if e.category_id else None,
        "amount": float(e.amount),
        "currency": e.currency,
        "description": e.description,
        "merchant": e.merchant,
        "payment_method": e.payment_method,
        "expense_date": str(e.expense_date),
        "source": e.source,
        "ai_category": e.ai_category,
        "family_group_id": str(e.family_group_id) if e.family_group_id else None,
        "created_at": str(e.created_at),
    }


def _budget_to_dict(b: Budget, member_spent: Optional[dict] = None) -> dict:
    amount = float(b.amount)
    spent = float(b.spent)
    percent = round((spent / amount * 100), 2) if amount > 0 else 0
    return {
        "id": str(b.id),
        "user_id": str(b.user_id),
        "name": b.name,
        "amount": amount,
        "spent": spent,
        "percent_used": percent,
        "period": b.period,
        "is_shared": b.is_shared,
        "family_group_id": str(b.family_group_id) if b.family_group_id else None,
        "alert_threshold": float(b.alert_threshold),
        "is_active": b.is_active,
        "member_spent": member_spent or {},
    }


class FamilyService:

    def _get_user_group(self, db: Session, user_id: str) -> Optional[FamilyGroup]:
        """Returns the family group the user belongs to (as admin or accepted member)."""
        # Check if user created a group
        group = db.query(FamilyGroup).filter(FamilyGroup.created_by == user_id).first()
        if group:
            return group
        # Check if user is an accepted member
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.phone:
            member = db.query(FamilyGroupMember).filter(
                FamilyGroupMember.phone == user.phone,
                FamilyGroupMember.status == "accepted",
            ).first()
            if member:
                return db.query(FamilyGroup).filter(FamilyGroup.id == member.group_id).first()
        return None

    def create_group(self, db: Session, user_id: str, data: CreateGroupRequest) -> dict:
        existing = self._get_user_group(db, user_id)
        if existing:
            raise BadRequestError("You already belong to a family group")

        user = db.query(User).filter(User.id == user_id).first()
        group = FamilyGroup(name=data.name, created_by=user_id)
        db.add(group)
        db.flush()

        # Creator's contribution: explicit value, else default to their salary
        creator_contribution = data.contribution
        if creator_contribution is None:
            creator_contribution = float(user.monthly_income or 0) if user else 0

        # Add creator as admin member
        admin = FamilyGroupMember(
            group_id=str(group.id),
            user_id=user_id,
            phone=user.phone or "",
            name=user.name,
            role="admin",
            status="accepted",
            contribution=creator_contribution,
            joined_at=datetime.utcnow(),
        )
        db.add(admin)
        db.commit()
        db.refresh(group)
        return _group_to_dict(group)

    def get_my_group(self, db: Session, user_id: str) -> Optional[dict]:
        group = self._get_user_group(db, user_id)
        if not group:
            return None
        return _group_to_dict(group)

    def invite_member(self, db: Session, user_id: str, data: InviteMemberRequest) -> dict:
        group = self._get_user_group(db, user_id)
        if not group:
            # Auto-create a default group so the user can invite straight away
            user = db.query(User).filter(User.id == user_id).first()
            group_name = f"{user.name}'s Family" if user and user.name else "My Family"
            group = FamilyGroup(name=group_name, created_by=user_id)
            db.add(group)
            db.flush()
            db.add(FamilyGroupMember(
                group_id=str(group.id),
                user_id=user_id,
                phone=(user.phone if user else "") or "",
                name=user.name if user else None,
                role="admin",
                status="accepted",
                joined_at=datetime.utcnow(),
            ))
            db.flush()

        # ── Validation: can't invite your own number ──────────────────────
        inviter = db.query(User).filter(User.id == user_id).first()
        if inviter and inviter.phone and \
                _same_phone(inviter.phone, data.phone):
            raise BadRequestError("You can't invite your own number")

        # ── Already invited / member ──────────────────────────────────────
        existing = db.query(FamilyGroupMember).filter(
            FamilyGroupMember.group_id == str(group.id),
            FamilyGroupMember.phone == data.phone,
        ).first()
        if existing:
            if existing.status == "accepted":
                raise BadRequestError("This number is already a member")
            # Still pending → treat as a re-send (re-notify the invitee)
            linked = db.query(User).filter(User.phone == data.phone).first()
            if linked:
                self._notify_invitee(db, linked, group, user_id)
            return _member_to_dict(existing)

        member = FamilyGroupMember(
            group_id=str(group.id),
            phone=data.phone,
            name=data.name,
            role="member",
            status="pending",
            invited_by=user_id,
        )
        # Auto-link if user with this phone already exists
        linked_user = db.query(User).filter(User.phone == data.phone).first()
        if linked_user:
            member.user_id = str(linked_user.id)
            member.name = member.name or linked_user.name

        db.add(member)
        db.commit()
        db.refresh(member)

        # Notify the invitee if they're already a Rupexi user
        if linked_user:
            self._notify_invitee(db, linked_user, group, user_id)

        return _member_to_dict(member)

    def _notify_invitee(self, db: Session, invitee: User,
                        group: FamilyGroup, inviter_id: str) -> None:
        """Create an in-app notification + push for a known invitee."""
        inviter = db.query(User).filter(User.id == inviter_id).first()
        inviter_name = (inviter.name if inviter else None) or "Someone"
        title = "Family invite"
        body  = f"{inviter_name} invited you to join \"{group.name}\""

        # 1. In-app notification row (shows in notification center + drives badge)
        try:
            from app.models.notification import Notification
            db.add(Notification(
                user_id=str(invitee.id),
                title=title,
                body=body,
                type="family_invite",
                is_read=False,
                data={"group_id": str(group.id), "group_name": group.name},
            ))
            db.commit()
        except Exception:
            db.rollback()

        # 2. Push notification to all the invitee's registered devices
        try:
            from app.models.device_token import UserDeviceToken
            from app.utils.fcm import send_push_notification
            tokens = db.query(UserDeviceToken).filter(
                UserDeviceToken.user_id == str(invitee.id)
            ).all()
            for t in tokens:
                send_push_notification(
                    device_token=t.device_token,
                    title=title,
                    body=body,
                    data={"group_id": str(group.id)},
                    notification_type="family_invite",
                )
        except Exception:
            pass

    def get_members(self, db: Session, user_id: str) -> List[dict]:
        group = self._get_user_group(db, user_id)
        if not group:
            return []
        return [_member_to_dict(m) for m in group.members]

    def accept_invite(self, db: Session, user_id: str, group_id: str) -> dict:
        user = db.query(User).filter(User.id == user_id).first()
        member = db.query(FamilyGroupMember).filter(
            FamilyGroupMember.group_id == group_id,
            FamilyGroupMember.phone == (user.phone or ""),
            FamilyGroupMember.status == "pending",
        ).first()
        if not member:
            raise NotFoundError("Invite not found")

        member.status = "accepted"
        member.user_id = user_id
        member.name = member.name or user.name
        member.joined_at = datetime.utcnow()
        # Default contribution to their salary so the household pool reflects them
        if float(member.contribution or 0) == 0 and user.monthly_income:
            member.contribution = float(user.monthly_income)
        db.commit()
        db.refresh(member)
        return _member_to_dict(member)

    def get_pending_invites(self, db: Session, user_id: str) -> List[dict]:
        """Return pending invites for the current user's phone."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.phone:
            return []
        members = db.query(FamilyGroupMember).filter(
            FamilyGroupMember.phone == user.phone,
            FamilyGroupMember.status == "pending",
        ).all()
        return [
            {
                "group_id": str(m.group_id),
                "group_name": m.group.name if m.group else "",
                "invited_by": m.inviter.name if m.inviter else "Someone",
                "member_id": str(m.id),
            }
            for m in members
        ]

    def get_family_expenses(
        self,
        db: Session,
        user_id: str,
        year: int,
        month: int,
    ) -> dict:
        group = self._get_user_group(db, user_id)
        if not group:
            return {"has_group": False, "expenses": [], "total": 0,
                    "member_totals": {}}

        # Collect all accepted member user_ids
        member_user_ids = [
            str(m.user_id) for m in group.members
            if m.user_id and m.status == "accepted"
        ]

        expenses = db.query(Expense).filter(
            Expense.user_id.in_(member_user_ids),
            extract("year", Expense.expense_date) == year,
            extract("month", Expense.expense_date) == month,
        ).order_by(Expense.expense_date.desc()).all()

        # Per-member totals
        member_totals: dict = {}
        for e in expenses:
            uid = str(e.user_id)
            member_totals[uid] = member_totals.get(uid, 0) + float(e.amount)

        # Enrich with member names
        member_names = {
            str(m.user_id): (m.name or (m.user.name if m.user else "Member"))
            for m in group.members if m.user_id
        }

        # Household income = sum of contributions across accepted members
        accepted = [m for m in group.members if m.status == "accepted"]
        household_income = sum(float(m.contribution or 0) for m in accepted)
        earner_count = sum(1 for m in accepted if float(m.contribution or 0) > 0)
        total_spent = sum(float(e.amount) for e in expenses)

        # Per-member contribution breakdown
        member_contributions = {
            (m.name or (m.user.name if m.user else "Member")): float(m.contribution or 0)
            for m in accepted if float(m.contribution or 0) > 0
        }

        return {
            "has_group": True,
            "group_name": group.name,
            "member_count": len(accepted),
            "expenses": [_expense_to_dict(e) for e in expenses],
            "total": total_spent,
            "household_income": household_income,
            "earner_count": earner_count,
            "saved": max(0.0, household_income - total_spent),
            "member_totals": {
                member_names.get(uid, uid): amt
                for uid, amt in member_totals.items()
            },
            "member_contributions": member_contributions,
        }

    def set_contribution(self, db: Session, user_id: str,
                         member_id: str, amount: float) -> dict:
        """Set a member's household contribution.
        Each member can edit ONLY their own income (privacy)."""
        group = self._get_user_group(db, user_id)
        if not group:
            raise NotFoundError("No family group")

        member = db.query(FamilyGroupMember).filter(
            FamilyGroupMember.id == member_id,
            FamilyGroupMember.group_id == str(group.id),
        ).first()
        if not member:
            raise NotFoundError("Member not found")

        # Privacy: you can only edit your own income contribution
        is_self = member.user_id and str(member.user_id) == str(user_id)
        if not is_self:
            raise ForbiddenError(
                "Each member can only edit their own income")

        member.contribution = max(0.0, amount)
        db.commit()
        db.refresh(member)
        return _member_to_dict(member)

    def get_shared_budgets(self, db: Session, user_id: str) -> List[dict]:
        group = self._get_user_group(db, user_id)
        if not group:
            return []

        member_user_ids = [
            str(m.user_id) for m in group.members
            if m.user_id and m.status == "accepted"
        ]

        budgets = db.query(Budget).filter(
            Budget.is_shared == True,
            Budget.family_group_id == str(group.id),
            Budget.is_active == True,
        ).all()

        result = []
        for b in budgets:
            # Per-member spent breakdown
            member_spent: dict = {}
            for uid in member_user_ids:
                from sqlalchemy import func
                q = db.query(func.sum(Expense.amount)).filter(
                    Expense.user_id == uid,
                    Expense.expense_date >= b.start_date,
                )
                if b.end_date:
                    q = q.filter(Expense.expense_date <= b.end_date)
                if b.category_id:
                    q = q.filter(Expense.category_id == b.category_id)
                spent = float(q.scalar() or 0)
                if spent > 0:
                    member = next((m for m in group.members if str(m.user_id) == uid), None)
                    name = member.name or (member.user.name if member and member.user else uid)
                    member_spent[name] = spent

            result.append(_budget_to_dict(b, member_spent))
        return result

    def recalculate_shared_budget(self, db: Session, budget_id: str) -> None:
        from sqlalchemy import func
        b = db.query(Budget).filter(Budget.id == budget_id).first()
        if not b or not b.is_shared or not b.family_group_id:
            return

        group = db.query(FamilyGroup).filter(FamilyGroup.id == b.family_group_id).first()
        if not group:
            return

        member_ids = [
            str(m.user_id) for m in group.members
            if m.user_id and m.status == "accepted"
        ]

        q = db.query(func.sum(Expense.amount)).filter(
            Expense.user_id.in_(member_ids),
            Expense.expense_date >= b.start_date,
        )
        if b.end_date:
            q = q.filter(Expense.expense_date <= b.end_date)
        if b.category_id:
            q = q.filter(Expense.category_id == b.category_id)

        b.spent = float(q.scalar() or 0)
        db.commit()
