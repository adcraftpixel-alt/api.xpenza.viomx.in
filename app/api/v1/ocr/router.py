from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.concurrency import run_in_threadpool
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
    # process_image is a blocking call — for a big/dense bill it now makes
    # several sequential Groq calls with rate-limit pacing (can legitimately
    # take a couple of minutes). Running it inline here would freeze this
    # whole worker's event loop for every other request during that time, so
    # push it to a thread instead.
    result = await run_in_threadpool(
        service.process_image, file_bytes, file.filename or "receipt.jpg",
        str(current_user.id), db,
    )
    return success(result, message="Receipt scanned successfully")
