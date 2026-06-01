from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task(name="app.workers.report_tasks.generate_export")
def generate_export(user_id: str, format: str, start_date: str, end_date: str) -> dict:
    """Generate report export asynchronously and upload to S3"""
    db = None
    try:
        from app.database import SessionLocal
        from app.api.v1.reports.service import report_service
        db = SessionLocal()

        data = report_service.generate_csv(user_id, start_date, end_date, [], db)

        # Try S3 upload
        from app.utils.storage import upload_to_s3
        filename = f"reports/{user_id}/{start_date}_{end_date}.{format}"
        url = upload_to_s3(data, filename, content_type="text/csv")

        return {"status": "complete", "url": url, "format": format}
    except Exception as e:
        logger.error(f"generate_export failed: {e}")
        return {"status": "failed", "error": str(e)}
    finally:
        if db:
            db.close()
