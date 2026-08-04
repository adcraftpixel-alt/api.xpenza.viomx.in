from typing import Optional, Any
from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: Optional[str] = None


class LoginRequest(BaseModel):
    email_or_phone: Optional[str] = None
    email: Optional[str] = None   # legacy field, maps to email_or_phone
    password: str

    def get_identifier(self) -> str:
        return self.email_or_phone or self.email or ""


class PhoneRegisterRequest(BaseModel):
    name: str
    phone: str


class OTPVerifyRequest(BaseModel):
    phone: str
    otp: str


class ResendOTPRequest(BaseModel):
    phone: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Optional[Any] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email_or_phone: str


class ResetPasswordRequest(BaseModel):
    email_or_phone: str
    otp: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("new_password must be at least 6 characters")
        return v


class SocialAuthRequest(BaseModel):
    id_token: str
    provider: str  # google | apple


class FirebasePhoneAuthRequest(BaseModel):
    """Firebase phone-auth ID token, obtained client-side after the user enters
    the SMS code. Carries the verified ``phone_number`` claim."""

    id_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None
