from fastapi import APIRouter, Depends, UploadFile, File, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.users.schemas import (
    UpdateUserRequest,
    OnboardingRequest,
    PreferencesRequest,
    PreferencesResponse,
    OnboardingStatusResponse,
)
from app.api.v1.users.service import UserService
from app.api.v1.users.preferences_service import PreferencesService
from app.utils.response import success

router = APIRouter(tags=["Users"])
service = UserService()
prefs_service = PreferencesService()


@router.get("/me")
def get_me(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return success(service.get_me(current_user, db))


@router.put("/me")
def update_me(
    data: UpdateUserRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    user = service.update_me(db, current_user, data)
    return success(service.get_me(user, db), message="Profile updated")


@router.post("/onboarding")
def complete_onboarding(
    data: OnboardingRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    user = service.complete_onboarding(db, current_user, data)
    return success(service.get_me(user, db), message="Onboarding complete")


@router.get("/onboarding/status", response_model=None)
def onboarding_status(current_user=Depends(get_current_active_user)):
    payload = OnboardingStatusResponse(
        onboarding_done=current_user.onboarding_done,
        user_exists=True,
    )
    return success(payload.model_dump())


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=None)
def get_preferences(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    data = prefs_service.get_with_defaults(db, current_user.id)
    return success(data)


@router.put("/preferences", response_model=None)
def update_preferences(
    data: PreferencesRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    updated = prefs_service.update(
        db,
        current_user.id,
        data.model_dump(exclude_none=True),
    )
    return success(updated, message="Preferences updated")


@router.post("/me/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    file_bytes = await file.read()
    url = service.upload_avatar(
        db, current_user, file_bytes, file.filename,
        base_url=str(request.base_url),
    )
    return success({"avatar_url": url}, message="Avatar uploaded")


@router.delete("/me")
def delete_account(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete_account(db, current_user)
    return success(None, message="Account deleted")
