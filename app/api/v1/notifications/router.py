from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.notifications.schemas import PreferencesRequest, DeviceTokenRequest
from app.api.v1.notifications.service import NotificationService
from app.utils.response import success

router = APIRouter(tags=["Notifications"])
service = NotificationService()


# ---------------------------------------------------------------------------
# GET /notifications  — list (with optional unread filter)
# ---------------------------------------------------------------------------

@router.get("")
def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    result = service.list(db, str(current_user.id), unread_only, limit=limit, offset=offset)
    return success(result)


# ---------------------------------------------------------------------------
# PUT /notifications/read-all  — mark all read
# NOTE: must be declared BEFORE /{id}/read to avoid FastAPI routing conflict
# ---------------------------------------------------------------------------

@router.put("/read-all")
def mark_all_read(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    count = service.mark_all_read(db, str(current_user.id))
    return success({"marked_read": count}, message=f"{count} notifications marked as read")


# Keep legacy POST alias for backward compatibility
@router.post("/mark-all-read")
def mark_all_read_post(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    count = service.mark_all_read(db, str(current_user.id))
    return success({"marked_read": count}, message=f"{count} notifications marked as read")


# ---------------------------------------------------------------------------
# GET /notifications/preferences
# ---------------------------------------------------------------------------

@router.get("/preferences")
def get_preferences(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    prefs = service.get_preferences(db, str(current_user.id))
    return success(prefs)


# ---------------------------------------------------------------------------
# PUT /notifications/preferences
# ---------------------------------------------------------------------------

@router.put("/preferences")
def update_preferences(
    data: PreferencesRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    prefs = service.update_preferences(db, str(current_user.id), data)
    return success(prefs, message="Preferences updated")


# ---------------------------------------------------------------------------
# Device-token registration endpoints
# ---------------------------------------------------------------------------

@router.post("/register-device")
def register_device(
    data: DeviceTokenRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.register_device_token(str(current_user.id), data.token, data.platform, db=db)
    return success(None, message="Device token registered")


@router.post("/device-token")
def register_device_token_legacy(
    data: DeviceTokenRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.register_device_token(str(current_user.id), data.token, data.platform, db=db)
    return success(None, message="Device token registered")


# ---------------------------------------------------------------------------
# PUT /notifications/{id}/read  — mark single notification read
# ---------------------------------------------------------------------------

@router.put("/{notif_id}/read")
def mark_read(
    notif_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    notif = service.mark_read(db, notif_id, str(current_user.id))
    return success(notif)


# ---------------------------------------------------------------------------
# DELETE /notifications/{id}
# ---------------------------------------------------------------------------

@router.delete("/{notif_id}")
def delete_notification(
    notif_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete(db, notif_id, str(current_user.id))
    return success(None, message="Notification deleted")
