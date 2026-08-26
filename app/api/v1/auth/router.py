from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.v1.auth.schemas import (
    RegisterRequest, LoginRequest, OTPVerifyRequest, ResendOTPRequest,
    TokenResponse, RefreshTokenRequest, ForgotPasswordRequest,
    ResetPasswordRequest, SocialAuthRequest, LogoutRequest,
    PhoneRegisterRequest, FirebasePhoneAuthRequest,
)
from app.api.v1.auth.service import AuthService, OTPServiceError
from app.core import rate_limit
from app.core.security import decode_token
from app.core.token_blacklist import blacklist_token
from app.utils.whatsapp import WhatsAppNotConfigured, WhatsAppDeliveryError
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
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = rate_limit.get_client_ip(request)
    rate_limit.enforce_rate_limit(
        f"login:ip:{ip}", limit=10, window_seconds=60,
        message="Too many login attempts from this IP. Please try again shortly.",
    )
    rate_limit.check_lock(f"login-ip:{ip}")
    rate_limit.enforce_captcha_if_required(ip, data.captcha_token)
    with rate_limit.track_outcome(ip=ip, identifier=data.get_identifier()):
        return service.login(db, data)


@router.post("/token", response_model=TokenResponse,
             summary="OAuth2 token endpoint — use this for Swagger UI 'Authorize'",
             include_in_schema=True)
def login_for_swagger(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Swagger UI Authorize button compatible endpoint.
    Enter your **email or phone** in the username field and your password.
    Demo credentials: username=demo@rupexi.com  password=demo123
    """
    ip = rate_limit.get_client_ip(request)
    rate_limit.enforce_rate_limit(
        f"login:ip:{ip}", limit=10, window_seconds=60,
        message="Too many login attempts from this IP. Please try again shortly.",
    )
    rate_limit.check_lock(f"login-ip:{ip}")
    from app.api.v1.auth.schemas import LoginRequest as LR
    data = LR(email_or_phone=form_data.username, password=form_data.password)
    with rate_limit.track_outcome(ip=ip, identifier=data.get_identifier()):
        return service.login(db, data)


@router.post("/register-phone")
def register_phone(data: PhoneRegisterRequest, db: Session = Depends(get_db)):
    user = service.register_phone(db, data)
    return success(
        {"id": str(user.id), "phone": user.phone},
        message="OTP sent to your phone number.",
    )


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(data: OTPVerifyRequest, request: Request, db: Session = Depends(get_db)):
    ip = rate_limit.get_client_ip(request)
    rate_limit.enforce_rate_limit(
        f"otpverify:ip:{ip}", limit=20, window_seconds=60,
        message="Too many OTP attempts from this IP. Please try again shortly.",
    )
    result = service.verify_otp(db, data.phone, data.otp)
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    return result


@router.post("/send-otp", summary="Send OTP to phone — creates user if not exists")
def send_otp(data: ResendOTPRequest, request: Request, db: Session = Depends(get_db)):
    """
    Phone-only auth: send a one-time code to the number via WhatsApp.
    Automatically creates the user account if phone not registered.
    """
    ip = rate_limit.get_client_ip(request)
    rate_limit.enforce_rate_limit(
        f"otpsend:ip:{ip}", limit=10, window_seconds=60,
        message="Too many OTP requests from this IP. Please try again shortly.",
    )
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
        service._seed_personal_categories(db, str(user.id))

    try:
        service.send_otp(data.phone, db)
    except OTPServiceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (WhatsAppNotConfigured, WhatsAppDeliveryError) as e:
        raise HTTPException(status_code=502, detail=f"Could not send OTP: {e}")
    return success({"phone": data.phone}, message="OTP sent successfully")


@router.post("/resend-otp")
def resend_otp(data: ResendOTPRequest, request: Request, db: Session = Depends(get_db)):
    ip = rate_limit.get_client_ip(request)
    rate_limit.enforce_rate_limit(
        f"otpsend:ip:{ip}", limit=10, window_seconds=60,
        message="Too many OTP requests from this IP. Please try again shortly.",
    )
    try:
        service.send_otp(data.phone, db)
    except OTPServiceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (WhatsAppNotConfigured, WhatsAppDeliveryError) as e:
        raise HTTPException(status_code=502, detail=f"Could not send OTP: {e}")
    return success(None, message="OTP sent")


@router.post("/refresh-token", response_model=TokenResponse)
def refresh_token(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    return service.refresh_token(db, data.refresh_token)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    ip = rate_limit.get_client_ip(request)
    rate_limit.enforce_rate_limit(
        f"forgotpw:ip:{ip}", limit=10, window_seconds=60,
        message="Too many requests from this IP. Please try again shortly.",
    )
    masked = service.forgot_password(db, data.email_or_phone)
    return success({"masked_contact": masked}, message="OTP sent")


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    service.reset_password(db, data.email_or_phone, data.otp, data.new_password)
    return success(None, message="Password reset successful")


@router.post(
    "/firebase-verify",
    response_model=TokenResponse,
    summary="Exchange a Firebase phone-auth ID token for a Rupexi session",
)
def firebase_verify(
    data: FirebasePhoneAuthRequest, db: Session = Depends(get_db)
):
    """Phone verification is performed by Firebase on the device; this endpoint
    validates the resulting ID token and issues our own access/refresh JWTs.
    Creates the account on first sign-in."""
    return service.verify_firebase_phone(db, data.id_token)


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
    # Access tokens stay stateless (short-lived); the refresh token is what
    # actually needs revoking so it can't keep minting new access tokens.
    if data and data.refresh_token:
        try:
            payload = decode_token(data.refresh_token)
        except HTTPException:
            payload = None  # already invalid/expired — nothing to revoke
        if payload:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                ttl = int(exp - datetime.utcnow().timestamp())
                if ttl > 0:
                    blacklist_token(jti, ttl)
    return success(None, message="Logged out successfully")
