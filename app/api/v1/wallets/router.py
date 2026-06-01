from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.wallets.schemas import CreateWalletRequest, UpdateWalletRequest, CreateTransactionRequest
from app.api.v1.wallets.service import WalletService
from app.utils.response import success

router = APIRouter(tags=["Wallets"])
service = WalletService()


@router.get("")
def list_wallets(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    wallets = service.list(db, str(current_user.id))
    return success(wallets)


@router.post("")
def create_wallet(
    data: CreateWalletRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    wallet = service.create(db, str(current_user.id), data)
    return success(wallet, message="Wallet created")


@router.get("/summary")
def get_wallet_summary(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    summary = service.get_summary(db, str(current_user.id))
    return success(summary)


@router.get("/{wallet_id}")
def get_wallet(
    wallet_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    wallet = service.get_by_id(db, wallet_id, str(current_user.id))
    return success(wallet)


@router.put("/{wallet_id}")
def update_wallet(
    wallet_id: str,
    data: UpdateWalletRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    wallet = service.update(db, wallet_id, str(current_user.id), data)
    return success(wallet, message="Wallet updated")


@router.delete("/{wallet_id}")
def delete_wallet(
    wallet_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete(db, wallet_id, str(current_user.id))
    return success(None, message="Wallet deleted")


@router.get("/{wallet_id}/transactions")
def list_transactions(
    wallet_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    transactions = service.list_transactions(db, wallet_id, str(current_user.id))
    return success(transactions)


@router.post("/{wallet_id}/transactions")
def add_transaction(
    wallet_id: str,
    data: CreateTransactionRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    transaction = service.add_transaction(db, wallet_id, str(current_user.id), data)
    return success(transaction, message="Transaction added")
