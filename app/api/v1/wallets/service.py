from typing import List
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from app.models.wallet import Wallet, WalletTransaction
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.wallets.schemas import CreateWalletRequest, UpdateWalletRequest, CreateTransactionRequest


def _transaction_to_dict(t: WalletTransaction) -> dict:
    return {
        "id": str(t.id),
        "wallet_id": str(t.wallet_id),
        "user_id": str(t.user_id),
        "amount": float(t.amount),
        "description": t.description,
        "transaction_date": str(t.transaction_date),
        "type": t.type,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _compute_spent_this_month(db: Session, wallet_id: str, user_id: str) -> float:
    from app.utils.period import current_period_window
    win_start, win_end = current_period_window(db, user_id)
    total = (
        db.query(func.sum(WalletTransaction.amount))
        .filter(
            WalletTransaction.wallet_id == wallet_id,
            WalletTransaction.type == "debit",
            WalletTransaction.transaction_date >= win_start,
            WalletTransaction.transaction_date <= win_end,
        )
        .scalar()
    )
    return float(total) if total else 0.0


def _wallet_to_dict(w: Wallet, db: Session, include_transactions: bool = False) -> dict:
    allocated = float(w.allocated)
    spent = _compute_spent_this_month(db, str(w.id), str(w.user_id))
    remaining = max(0.0, allocated - spent)
    percent_used = round((spent / allocated * 100), 2) if allocated > 0 else 0.0

    result = {
        "id": str(w.id),
        "user_id": str(w.user_id),
        "name": w.name,
        "allocated": allocated,
        "color": w.color,
        "icon": w.icon,
        "is_active": w.is_active,
        "spent_this_month": spent,
        "remaining": remaining,
        "percent_used": percent_used,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }

    if include_transactions:
        txns = (
            db.query(WalletTransaction)
            .filter(WalletTransaction.wallet_id == str(w.id))
            .order_by(WalletTransaction.transaction_date.desc())
            .all()
        )
        result["transactions"] = [_transaction_to_dict(t) for t in txns]
    else:
        result["transactions"] = []

    return result


class WalletService:
    def create(self, db: Session, user_id: str, data: CreateWalletRequest) -> dict:
        wallet = Wallet(
            user_id=user_id,
            name=data.name,
            allocated=data.allocated,
            color=data.color,
            icon=data.icon,
        )
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        return _wallet_to_dict(wallet, db)

    def list(self, db: Session, user_id: str) -> List[dict]:
        wallets = (
            db.query(Wallet)
            .filter(Wallet.user_id == user_id)
            .order_by(Wallet.created_at.asc())
            .all()
        )
        return [_wallet_to_dict(w, db) for w in wallets]

    def get_by_id(self, db: Session, wallet_id: str, user_id: str) -> dict:
        w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not w:
            raise NotFoundError("Wallet not found")
        if str(w.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _wallet_to_dict(w, db, include_transactions=True)

    def update(self, db: Session, wallet_id: str, user_id: str, data: UpdateWalletRequest) -> dict:
        w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not w:
            raise NotFoundError("Wallet not found")
        if str(w.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(w, field, value)
        w.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(w)
        return _wallet_to_dict(w, db)

    def delete(self, db: Session, wallet_id: str, user_id: str) -> bool:
        w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not w:
            raise NotFoundError("Wallet not found")
        if str(w.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        db.delete(w)
        db.commit()
        return True

    def get_summary(self, db: Session, user_id: str) -> dict:
        wallets = (
            db.query(Wallet)
            .filter(Wallet.user_id == user_id, Wallet.is_active == True)
            .all()
        )
        total_allocated = sum(float(w.allocated) for w in wallets)
        total_spent = sum(_compute_spent_this_month(db, str(w.id), str(w.user_id)) for w in wallets)
        total_remaining = max(0.0, total_allocated - total_spent)
        percent_used = round((total_spent / total_allocated * 100), 2) if total_allocated > 0 else 0.0
        return {
            "total_allocated": total_allocated,
            "total_spent": total_spent,
            "total_remaining": total_remaining,
            "wallet_count": len(wallets),
            "percent_used": percent_used,
        }

    def add_transaction(
        self, db: Session, wallet_id: str, user_id: str, data: CreateTransactionRequest
    ) -> dict:
        w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not w:
            raise NotFoundError("Wallet not found")
        if str(w.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        txn = WalletTransaction(
            wallet_id=wallet_id,
            user_id=user_id,
            amount=data.amount,
            description=data.description,
            transaction_date=data.transaction_date,
            type=data.type,
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        return _transaction_to_dict(txn)

    def list_transactions(self, db: Session, wallet_id: str, user_id: str) -> List[dict]:
        w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        if not w:
            raise NotFoundError("Wallet not found")
        if str(w.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        txns = (
            db.query(WalletTransaction)
            .filter(WalletTransaction.wallet_id == wallet_id)
            .order_by(WalletTransaction.transaction_date.desc(), WalletTransaction.created_at.desc())
            .all()
        )
        return [_transaction_to_dict(t) for t in txns]
