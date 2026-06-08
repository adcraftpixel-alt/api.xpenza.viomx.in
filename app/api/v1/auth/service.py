import random
import string
import logging
from typing import Optional

import redis as redis_lib
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.exceptions import ConflictError, UnauthorizedError, NotFoundError, ValidationError
from app.models.user import User
from app.models.user_preference import UserPreference
from app.api.v1.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    PhoneRegisterRequest,
)
from app.utils.email import send_otp_email
from app.utils.sms import send_sms, sms_configured, SMSNotConfigured, SMSDeliveryError

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 300  # 5 minutes


class OTPServiceError(Exception):
    """Raised when the OTP store (Redis) is unavailable so the request can fail
    with a clear message instead of an opaque 500."""

try:
    redis_client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
except Exception:
    redis_client = None


def _build_token_response(user: User) -> TokenResponse:
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    user_data = {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "user_type": user.user_type,
        "is_verified": user.is_verified,
        "onboarding_done": user.onboarding_done,
        "currency": user.currency,
        "avatar_url": user.avatar_url,
    }
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=user_data)


class AuthService:
    def register(self, db: Session, data: RegisterRequest) -> User:
        if data.email:
            existing = db.query(User).filter(User.email == data.email).first()
            if existing:
                raise ConflictError("Email already registered")
        if data.phone:
            existing = db.query(User).filter(User.phone == data.phone).first()
            if existing:
                raise ConflictError("Phone number already registered")

        user = User(
            name=data.name,
            email=data.email,
            phone=data.phone,
            password_hash=hash_password(data.password) if data.password else None,
            is_verified=False,
            is_active=True,
            onboarding_done=False,
        )
        db.add(user)
        db.flush()

        pref = UserPreference(user_id=user.id)
        db.add(pref)
        db.commit()
        db.refresh(user)

        if data.phone:
            try:
                self.send_otp(data.phone)
            except Exception as e:
                logger.warning(f"OTP send failed: {e}")

        return user

    def login(self, db: Session, data: LoginRequest) -> TokenResponse:
        identifier = data.get_identifier()
        user = (
            db.query(User).filter(User.email == identifier).first()
            or db.query(User).filter(User.phone == identifier).first()
        )
        if not user or not user.password_hash:
            raise UnauthorizedError("Invalid email or password")
        if not verify_password(data.password, user.password_hash):
            raise UnauthorizedError("Invalid email or password")
        if not user.is_active:
            raise UnauthorizedError("Account is suspended")
        return _build_token_response(user)

    def verify_otp(self, db: Session, phone: str, otp: str) -> Optional[TokenResponse]:
        # OTP is verified strictly against the code stored in Redis — no static
        # bypass codes.
        if not redis_client:
            logger.error("Redis not available — cannot verify OTP")
            return None
        key = f"otp:{phone}"
        stored = redis_client.get(key)
        if not stored or stored != otp:
            return None
        redis_client.delete(key)

        # Find or auto-create user for this phone
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            # New user — create account on first OTP verify
            name = phone  # Default name, user updates in profile
            user = User(
                name=name,
                phone=phone,
                is_verified=True,
                is_active=True,
                onboarding_done=False,
            )
            db.add(user)
            db.flush()
            pref = UserPreference(user_id=user.id)
            db.add(pref)
            logger.info(f"New user created via OTP: {phone}")
        else:
            user.is_verified = True

        db.commit()
        db.refresh(user)
        return _build_token_response(user)

    def register_phone(self, db: Session, data: PhoneRegisterRequest) -> User:
        existing = db.query(User).filter(User.phone == data.phone).first()
        if existing:
            if existing.is_verified:
                raise ConflictError("Phone already registered")
            # Unverified — resend OTP and return existing user
            try:
                self.send_otp(data.phone)
            except Exception as e:
                logger.warning(f"OTP send failed: {e}")
            return existing

        user = User(
            name=data.name,
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
        db.refresh(user)

        try:
            self.send_otp(data.phone)
        except Exception as e:
            logger.warning(f"OTP send failed: {e}")

        return user

    def send_otp(self, phone: str) -> str:
        otp = "".join(random.choices(string.digits, k=6))

        # The OTP MUST be stored so verify_otp can check it later. If the store
        # is unreachable, fail clearly rather than sending an un-verifiable code.
        try:
            if not redis_client:
                raise RuntimeError("OTP store (Redis) is not configured")
            redis_client.setex(f"otp:{phone}", OTP_TTL_SECONDS, otp)
        except Exception as e:
            logger.error(f"OTP storage failed (Redis unreachable?): {e}")
            raise OTPServiceError(
                "OTP service is temporarily unavailable. Please try again shortly."
            )

        body = (
            f"Your AI Finance OS verification code is {otp}. "
            f"It expires in {OTP_TTL_SECONDS // 60} minutes."
        )
        if sms_configured():
            # Let delivery errors propagate so callers can surface them.
            send_sms(phone, body)
        else:
            # No Twilio credentials (e.g. local dev): log so the flow still works.
            logger.warning(f"[OTP-DEV] Twilio not configured. {phone} => {otp}")
        return otp

    def refresh_token(self, db: Session, refresh_token_str: str) -> TokenResponse:
        payload = decode_token(refresh_token_str)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type")
        user_id = payload.get("sub")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or inactive")
        return _build_token_response(user)

    def _find_user_by_email_or_phone(self, db: Session, identifier: str) -> Optional[User]:
        """Return a user matched by email or phone, or None."""
        identifier = identifier.strip()
        return (
            db.query(User).filter(User.email == identifier).first()
            or db.query(User).filter(User.phone == identifier).first()
        )

    def _mask_contact(self, identifier: str) -> str:
        """Return a masked version of an email or phone for the API response."""
        if "@" in identifier:
            local, domain = identifier.split("@", 1)
            visible = local[:2] if len(local) > 2 else local[:1]
            return f"{visible}***@{domain}"
        # Phone: show last 4 digits
        return f"***{identifier[-4:]}" if len(identifier) >= 4 else "****"

    def _send_otp_via_contact(self, identifier: str) -> str:
        """Generate a 6-digit OTP, persist in Redis for 1 hour, and dispatch it."""
        otp = "".join(random.choices(string.digits, k=6))
        key = f"pwd_reset_otp:{identifier}"
        if redis_client:
            redis_client.setex(key, 3600, otp)  # 1-hour expiry
        if "@" in identifier:
            try:
                send_otp_email(identifier, otp)
            except Exception as e:
                logger.warning(f"OTP email failed: {e}")
        else:
            # Phone number — dispatch via Twilio SMS.
            body = f"Your AI Finance OS password reset code is {otp}. It expires in 1 hour."
            if sms_configured():
                try:
                    send_sms(identifier, body)
                except (SMSNotConfigured, SMSDeliveryError) as e:
                    logger.warning(f"Password-reset OTP SMS failed: {e}")
            else:
                logger.warning(f"[PWD-RESET-DEV] Twilio not configured. {identifier} => {otp}")
        return otp

    def forgot_password(self, db: Session, email_or_phone: str) -> str:
        """Send a password-reset OTP. Returns the masked contact string."""
        user = self._find_user_by_email_or_phone(db, email_or_phone)
        # Always respond the same way to avoid user-enumeration
        if user:
            self._send_otp_via_contact(email_or_phone.strip())
        return self._mask_contact(email_or_phone.strip())

    def reset_password(self, db: Session, email_or_phone: str, otp: str, new_password: str) -> bool:
        """Verify the OTP and update the user's password."""
        identifier = email_or_phone.strip()
        key = f"pwd_reset_otp:{identifier}"

        if redis_client:
            stored = redis_client.get(key)
            if not stored or stored != otp:
                raise UnauthorizedError("Invalid or expired OTP")
            redis_client.delete(key)
        else:
            logger.warning("Redis unavailable — skipping OTP check for password reset")

        user = self._find_user_by_email_or_phone(db, identifier)
        if not user:
            raise NotFoundError("User not found")
        user.password_hash = hash_password(new_password)
        db.commit()
        return True

    def social_auth(self, db: Session, id_token: str, provider: str) -> TokenResponse:
        """Stub for Firebase social auth. In production: verify id_token with Firebase Admin SDK."""
        logger.warning(f"[SOCIAL AUTH STUB] provider={provider}")
        raise ValidationError("Social auth not fully configured. Set up Firebase Admin SDK.")
