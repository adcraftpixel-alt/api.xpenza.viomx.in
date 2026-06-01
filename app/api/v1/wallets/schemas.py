from typing import List, Optional
from datetime import date
from pydantic import BaseModel


class CreateWalletRequest(BaseModel):
    name: str
    allocated: float
    color: str = "#16A344"
    icon: str = "💰"


class UpdateWalletRequest(BaseModel):
    name: Optional[str] = None
    allocated: Optional[float] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None


class CreateTransactionRequest(BaseModel):
    amount: float
    description: Optional[str] = None
    transaction_date: date
    type: str = "debit"  # 'debit' | 'credit'


class TransactionResponse(BaseModel):
    id: str
    wallet_id: str
    user_id: str
    amount: float
    description: Optional[str] = None
    transaction_date: str
    type: str
    created_at: str

    class Config:
        from_attributes = True


class WalletResponse(BaseModel):
    id: str
    user_id: str
    name: str
    allocated: float
    color: str
    icon: str
    is_active: bool
    spent_this_month: float
    remaining: float
    percent_used: float
    transactions: List[TransactionResponse] = []
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class WalletSummaryResponse(BaseModel):
    total_allocated: float
    total_spent: float
    total_remaining: float
    wallet_count: int
    percent_used: float

    class Config:
        from_attributes = True
