import random
import string
import logging
from datetime import datetime, timedelta
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
from app.core.exceptions import (
    AppException,
    ConflictError,
    UnauthorizedError,
    NotFoundError,
    ValidationError,
)
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
from app.utils.whatsapp import (
    send_whatsapp_otp,
    whatsapp_configured,
    WhatsAppNotConfigured,
    WhatsAppDeliveryError,
)

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 300  # 5 minutes


class OTPServiceError(Exception):
    """Raised when the OTP store (Redis) is unavailable so the request can fail
    with a clear message instead of an opaque 500."""

try:
    redis_client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
except Exception:
    redis_client = None


def _redis_key(identifier: str, purpose: str) -> str:
    prefix = "pwd_reset_otp" if purpose == "pwd_reset" else "otp"
    return f"{prefix}:{identifier}"


def store_otp(identifier: str, code: str, ttl: int, purpose: str, db: Session) -> None:
    """Persist an OTP for later verification.

    Prefers Redis (fast, auto-expiring); falls back to the Postgres ``otp_codes``
    table when Redis is unavailable so OTP works without a Redis instance.
    Raises ``OTPServiceError`` only if BOTH stores fail.
    """
    if redis_client is not None:
        try:
            redis_client.setex(_redis_key(identifier, purpose), ttl, code)
            return
        except Exception as e:
            logger.warning(f"Redis OTP store failed, falling back to Postgres: {e}")

    from app.models.otp_code import OtpCode
    try:
        db.query(OtpCode).filter(
            OtpCode.identifier == identifier, OtpCode.purpose == purpose
        ).delete()
        db.add(OtpCode(
            identifier=identifier,
            purpose=purpose,
            code=code,
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"OTP storage failed (Redis + Postgres both unavailable): {e}")
        raise OTPServiceError(
            "OTP service is temporarily unavailable. Please try again shortly."
        )


def consume_otp(identifier: str, code: str, purpose: str, db: Session) -> bool:
    """Validate a submitted OTP and invalidate it. True if it matched and was unexpired."""
    # Try Redis first.
    if redis_client is not None:
        try:
            key = _redis_key(identifier, purpose)
            stored = redis_client.get(key)
            if stored is not None:
                if stored == code:
                    redis_client.delete(key)
                    return True
                return False
            # Not in Redis — may have been stored in Postgres; fall through.
        except Exception as e:
            logger.warning(f"Redis OTP read failed, trying Postgres: {e}")

    from app.models.otp_code import OtpCode
    try:
        row = (
            db.query(OtpCode)
            .filter(
                OtpCode.identifier == identifier,
                OtpCode.purpose == purpose,
                OtpCode.code == code,
            )
            .order_by(OtpCode.created_at.desc())
            .first()
        )
        if not row:
            return False
        valid = row.expires_at >= datetime.utcnow()
        # Consume all codes for this identifier+purpose regardless of expiry.
        db.query(OtpCode).filter(
            OtpCode.identifier == identifier, OtpCode.purpose == purpose
        ).delete()
        db.commit()
        return valid
    except Exception as e:
        db.rollback()
        logger.error(f"OTP verification failed (Postgres): {e}")
        return False


# Default country used to expand a bare national number into E.164. The apps
# ship an India-first country picker; change this if you launch elsewhere.
DEFAULT_COUNTRY_CODE = "91"


def _phone_auth_unavailable() -> AppException:
    """503 for a server-side Firebase misconfiguration.

    Not a 4xx: the client's request was fine, and it is worth retrying once the
    service account is in place.
    """
    return AppException(
        status_code=503,
        detail="Phone sign-in is temporarily unavailable. Please try again shortly.",
    )


def normalize_phone(phone: str) -> str:
    """Return [phone] in E.164 form (``+919876543210``).

    Historically the apps disagreed: the login screen sent a full ``+91...``
    number while the register screen stripped the prefix, so ``users.phone``
    holds both shapes. Firebase always reports E.164, so everything is funnelled
    through here to stop the same person getting two accounts.
    """
    if not phone:
        return phone

    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if digits.startswith("+"):
        return "+" + "".join(ch for ch in digits if ch.isdigit())

    if digits.startswith("00"):
        return "+" + digits[2:]

    # Bare national number (10 digits in India) — prepend the default country.
    if len(digits) <= 10:
        return f"+{DEFAULT_COUNTRY_CODE}{digits}"

    return "+" + digits


def _phone_lookup_candidates(phone: str) -> list[str]:
    """Every stored spelling of [phone] we might match an existing row on."""
    e164 = normalize_phone(phone)
    bare = e164.lstrip("+")
    candidates = {phone, e164, bare}

    # Strip the country code to recover the legacy bare-national form.
    if bare.startswith(DEFAULT_COUNTRY_CODE):
        national = bare[len(DEFAULT_COUNTRY_CODE):]
        if national:
            candidates.add(national)

    return [c for c in candidates if c]


def _find_user_by_phone(db: Session, phone: str) -> Optional[User]:
    """Look up a user across every legacy phone format."""
    return (
        db.query(User)
        .filter(User.phone.in_(_phone_lookup_candidates(phone)))
        .first()
    )


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
                self.send_otp(data.phone, db)
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
        # OTP is verified strictly against the stored code (Redis or Postgres) —
        # no static bypass codes.
        if not consume_otp(phone, otp, "login", db):
            return None

        # Shared with Firebase sign-in: matches the user across every legacy
        # phone format so an existing account is never duplicated, normalises
        # the row to E.164, and rejects suspended accounts.
        return self._login_verified_phone(db, phone, None)

    def register_phone(self, db: Session, data: PhoneRegisterRequest) -> User:
        existing = db.query(User).filter(User.phone == data.phone).first()
        if existing:
            if existing.is_verified:
                raise ConflictError("Phone already registered")
            # Unverified — resend OTP and return existing user
            try:
                self.send_otp(data.phone, db)
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
            self.send_otp(data.phone, db)
        except Exception as e:
            logger.warning(f"OTP send failed: {e}")

        return user

    def send_otp(self, phone: str, db: Session) -> str:
        otp = "".join(random.choices(string.digits, k=6))

        # The OTP MUST be stored so verify_otp can check it later. store_otp uses
        # Redis when available and falls back to Postgres, raising OTPServiceError
        # only if both are unreachable.
        store_otp(phone, otp, OTP_TTL_SECONDS, "login", db)

        if whatsapp_configured():
            # Let delivery errors propagate so callers can surface them.
            send_whatsapp_otp(phone, otp)
        else:
            # No WhatsApp credentials (e.g. local dev): log so the flow still works.
            logger.warning(f"[OTP-DEV] WhatsApp not configured. {phone} => {otp}")
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

    def _send_otp_via_contact(self, identifier: str, db: Session) -> str:
        """Generate a 6-digit OTP, persist it for 1 hour, and dispatch it."""
        otp = "".join(random.choices(string.digits, k=6))
        store_otp(identifier, otp, 3600, "pwd_reset", db)  # 1-hour expiry
        if "@" in identifier:
            try:
                send_otp_email(identifier, otp)
            except Exception as e:
                logger.warning(f"OTP email failed: {e}")
        else:
            # Phone number — dispatch via MSG91 SMS.
            body = f"Rupexi password reset code: {otp}. Valid for 1 hour."
            if sms_configured():
                try:
                    send_sms(identifier, body)
                except (SMSNotConfigured, SMSDeliveryError) as e:
                    logger.warning(f"Password-reset OTP SMS failed: {e}")
            else:
                logger.warning(f"[PWD-RESET-DEV] MSG91 not configured. {identifier} => {otp}")
        return otp

    def forgot_password(self, db: Session, email_or_phone: str) -> str:
        """Send a password-reset OTP. Returns the masked contact string."""
        user = self._find_user_by_email_or_phone(db, email_or_phone)
        # Always respond the same way to avoid user-enumeration
        if user:
            self._send_otp_via_contact(email_or_phone.strip(), db)
        return self._mask_contact(email_or_phone.strip())

    def reset_password(self, db: Session, email_or_phone: str, otp: str, new_password: str) -> bool:
        """Verify the OTP and update the user's password."""
        identifier = email_or_phone.strip()

        if not consume_otp(identifier, otp, "pwd_reset", db):
            raise UnauthorizedError("Invalid or expired OTP")

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

    def verify_firebase_phone(self, db: Session, id_token: str) -> TokenResponse:
        """Exchange a Firebase phone-auth ID token for a Rupexi session.

        The SMS/OTP round-trip happens entirely between the app and Firebase.
        By the time we get here Firebase has already proven the user controls
        the number, so our only job is to verify the token's signature, trust
        the ``phone_number`` claim, and issue our own JWTs.
        """
        from app.utils.firebase import get_firebase_app

        app = get_firebase_app()
        if app is None:
            logger.error("Firebase phone auth attempted but Admin SDK is not configured")
            raise _phone_auth_unavailable()

        try:
            from firebase_admin import auth as fb_auth
        except ImportError:
            # firebase-admin missing from the image — fail soft rather than 500.
            logger.error("firebase-admin is not installed; phone auth disabled")
            raise _phone_auth_unavailable()

        try:
            # check_revoked=False: these tokens are seconds old and we mint our
            # own session immediately, so a revocation lookup adds latency for
            # no benefit.
            decoded = fb_auth.verify_id_token(id_token, app=app)
        except Exception as e:
            logger.warning(f"Firebase ID token rejected: {e}")
            raise UnauthorizedError("Invalid or expired verification token")

        phone = decoded.get("phone_number")
        if not phone:
            # Token is valid but came from a non-phone provider — refuse rather
            # than creating a phone-less account through the phone endpoint.
            raise UnauthorizedError("Verification token is not a phone sign-in")

        firebase_uid = decoded.get("uid") or decoded.get("sub")
        return self._login_verified_phone(db, phone, firebase_uid)

    def _login_verified_phone(
        self, db: Session, phone_e164: str, firebase_uid: Optional[str]
    ) -> TokenResponse:
        """Find-or-create the user behind an already-verified phone number."""
        user = _find_user_by_phone(db, phone_e164)

        if not user:
            user = User(
                name=phone_e164,  # Placeholder — set during onboarding
                phone=normalize_phone(phone_e164),
                firebase_uid=firebase_uid,
                is_verified=True,
                is_active=True,
                onboarding_done=False,
            )
            db.add(user)
            db.flush()
            db.add(UserPreference(user_id=user.id))
            logger.info(f"New user created via Firebase phone auth: {phone_e164}")
        else:
            if not user.is_active:
                raise UnauthorizedError("Account is suspended")
            user.is_verified = True
            # Normalise legacy rows to E.164 on first Firebase login so the
            # column converges on one format.
            normalized = normalize_phone(phone_e164)
            if user.phone != normalized:
                user.phone = normalized
            if firebase_uid and user.firebase_uid != firebase_uid:
                user.firebase_uid = firebase_uid

        db.commit()
        db.refresh(user)
        return _build_token_response(user)
