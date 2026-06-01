from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.dashboard.service import DashboardService
from app.utils.response import success

router = APIRouter(tags=["Dashboard"])
service = DashboardService()


@router.get("/summary")
def get_summary(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    data = service.get_summary(db, str(current_user.id), current_user)
    return success(data)
