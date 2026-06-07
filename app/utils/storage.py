import logging
import os
import uuid
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)

LOCAL_UPLOAD_DIR = Path("/tmp/aifinanceos_uploads")
LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_local(filename: str, file_bytes: bytes) -> str:
    """Write bytes under LOCAL_UPLOAD_DIR, creating any nested parent dirs.

    `filename` may contain slashes (e.g. "avatars/<uuid>/x.jpg"), so the parent
    directory must be created first — otherwise write_bytes raises
    FileNotFoundError (this caused 500s on the avatar upload).
    """
    local_path = LOCAL_UPLOAD_DIR / filename
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(file_bytes)
    logger.info(f"[STORAGE STUB] Saved locally: {local_path}")
    return f"/local-uploads/{filename}"


def upload_to_s3(file_bytes: bytes, filename: str, content_type: str = "application/octet-stream") -> str:
    """Upload file to S3. Falls back to local storage if credentials are missing."""
    if not settings.AWS_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID == "...":
        return _save_local(filename, file_bytes)

    try:
        import boto3

        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        s3.put_object(
            Bucket=settings.AWS_S3_BUCKET,
            Key=filename,
            Body=file_bytes,
            ContentType=content_type,
        )
        url = f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{filename}"
        logger.info(f"Uploaded to S3: {url}")
        return url
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        return _save_local(filename, file_bytes)


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a pre-signed URL for an S3 object."""
    if not settings.AWS_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID == "...":
        return f"/local-uploads/{key}"

    try:
        import boto3

        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as e:
        logger.error(f"Presigned URL generation failed: {e}")
        return f"/local-uploads/{key}"


def generate_unique_filename(original_filename: str) -> str:
    ext = Path(original_filename).suffix
    return f"{uuid.uuid4().hex}{ext}"
