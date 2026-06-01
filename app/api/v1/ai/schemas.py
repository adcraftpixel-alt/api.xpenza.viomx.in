from typing import Optional, List, Any
from pydantic import BaseModel


class InsightResponse(BaseModel):
    id: str
    type: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    data: Optional[Any] = None
    is_read: bool = False


class HealthScoreResponse(BaseModel):
    score: int
    grade: str
    breakdown: dict
    recommendations: List[str] = []


class PredictionResponse(BaseModel):
    next_month_estimate: float
    trend: str
    monthly_data: List[dict] = []
    confidence: float = 0.0


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    text: str
    data_type: Optional[str] = None
    data: Optional[Any] = None
    suggestions: List[str] = []
