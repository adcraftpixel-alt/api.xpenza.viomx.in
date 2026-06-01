from typing import Optional
from pydantic import BaseModel


class OCRResultResponse(BaseModel):
    scan_id: str
    amount: Optional[float] = None
    merchant: Optional[str] = None
    date: Optional[str] = None
    category: Optional[str] = None
    confidence: float = 0.0
    raw_text: Optional[str] = None
    status: str = "completed"
