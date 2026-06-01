from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.ocr.service import OCRService
from app.utils.response import success

router = APIRouter(tags=["OCR"])
service = OCRService()


@router.post("/scan")
async def scan_receipt(
    file: UploadFile = File(...),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    file_bytes = await file.read()
    result = service.process_image(file_bytes, file.filename or "receipt.jpg", str(current_user.id), db)
    return success(result, message="Receipt scanned successfully")
