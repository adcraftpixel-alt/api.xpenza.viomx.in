from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.v1.auth.schemas import (
    RegisterRequest, LoginRequest, OTPVerifyRequest, ResendOTPRequest,
    TokenResponse, RefreshTokenRequest, ForgotPasswordRequest,
    ResetPasswordRequest, SocialAuthRequest, LogoutRequest,
    PhoneRegisterRequest,
)
from app.api.v1.auth.service import AuthService, OTPServiceError
from app.utils.sms import SMSNotConfigured, SMSDeliveryError
from app.utils.response import success, error

router = APIRouter(tags=["Auth"])
service = AuthService()


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    user = service.register(db, data)
    return success(
        {"id": str(user.id), "name": user.name, "email": user.email, "phone": user.phone},
        message="Registration successful. Please verify your account.",
    )


@router.post("/login", response_model=TokenResponse,
             summary="Login with email/phone + password (JSON)")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    return service.login(db, data)


@router.post("/token", response_model=TokenResponse,
             summary="OAuth2 token endpoint — use this for Swagger UI 'Authorize'",
             include_in_schema=True)
def login_for_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Swagger UI Authorize button compatible endpoint.
    Enter your **email or phone** in the username field and your password.
    Demo credentials: username=demo@rupexi.com  password=demo123
    """
    from app.api.v1.auth.schemas import LoginRequest as LR
    data = LR(email_or_phone=form_data.username, password=form_data.password)
    return service.login(db, data)


@router.post("/register-phone")
def register_phone(data: PhoneRegisterRequest, db: Session = Depends(get_db)):
    user = service.register_phone(db, data)
    return success(
        {"id": str(user.id), "phone": user.phone},
        message="OTP sent to your phone number.",
    )


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(data: OTPVerifyRequest, db: Session = Depends(get_db)):
    result = service.verify_otp(db, data.phone, data.otp)
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    return result


@router.post("/send-otp", summary="Send OTP to phone — creates user if not exists")
def send_otp(data: ResendOTPRequest, db: Session = Depends(get_db)):
    """
    Phone-only auth: send a one-time code to the number via SMS (Twilio).
    Automatically creates the user account if phone not registered.
    """
    from app.models.user import User
    from app.models.user_preference import UserPreference

    # Auto-create user if not exists
    user = db.query(User).filter(User.phone == data.phone).first()
    if not user:
        user = User(
            name=data.phone,  # placeholder name
            phone=data.phone,
            is_verified=False,
            is_active=True,
            onboarding_done=False,
        )
        db.add(user)
        db.flush()
        pref = UserPreference(user_id=user.id)
        db.add(pref)
        db.commit()

    try:
        service.send_otp(data.phone)
    except OTPServiceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (SMSNotConfigured, SMSDeliveryError) as e:
        raise HTTPException(status_code=502, detail=f"Could not send OTP: {e}")
    return success({"phone": data.phone}, message="OTP sent successfully")


@router.post("/resend-otp")
def resend_otp(data: ResendOTPRequest):
    try:
        service.send_otp(data.phone)
    except OTPServiceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (SMSNotConfigured, SMSDeliveryError) as e:
        raise HTTPException(status_code=502, detail=f"Could not send OTP: {e}")
    return success(None, message="OTP sent")


@router.post("/refresh-token", response_model=TokenResponse)
def refresh_token(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    return service.refresh_token(db, data.refresh_token)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    masked = service.forgot_password(db, data.email_or_phone)
    return success({"masked_contact": masked}, message="OTP sent")


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    service.reset_password(db, data.email_or_phone, data.otp, data.new_password)
    return success(None, message="Password reset successful")


@router.post("/google")
def google_auth(data: SocialAuthRequest, db: Session = Depends(get_db)):
    token_response = service.social_auth(db, data.id_token, "google")
    return token_response


@router.post("/apple")
def apple_auth(data: SocialAuthRequest, db: Session = Depends(get_db)):
    token_response = service.social_auth(db, data.id_token, "apple")
    return token_response


@router.post("/logout")
def logout(data: LogoutRequest = None):
    # Stateless JWT: just acknowledge. In production, blacklist the refresh token in Redis.
    return success(None, message="Logged out successfully")
