from pydantic import BaseModel
from typing import Optional


class CreateTicketRequest(BaseModel):
    subject: str
    message: str
    category: Optional[str] = "General"
