from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://manjitparmar@localhost:5432/aifinanceos"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "dev-secret-key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Razorpay (INR recurring auto-pay: UPI AutoPay + card e-mandate)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    # Trial length in days before the first ₹199 auto-debit
    TRIAL_DAYS: int = 30
    # Machine-to-machine key the VIOMX Control Hub sends to Rupexi (X-Service-Key).
    SERVICE_API_KEY: str = ""
    # VIOMX Control Hub — Rupexi pulls plans/caps and reports purchases here.
    # CONTROL_HUB_KEY is presented as X-Product-Key (must equal RUPEXI_INGEST_KEY on the Hub).
    CONTROL_HUB_URL: str = ""          # e.g. https://hub.viomx.io/api/v1
    CONTROL_HUB_KEY: str = ""
    PRODUCT_CODE: str = "RUPEXI"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = "aifinanceos-uploads"
    AWS_REGION: str = "ap-south-1"
    SENDGRID_API_KEY: str = ""
    # MSG91 (SMS OTP delivery — replaces Twilio; handles India DLT)
    MSG91_AUTH_KEY: str = ""
    MSG91_TEMPLATE_ID: str = ""   # DLT-approved template; required to send
    MSG91_SENDER_ID: str = ""     # 6-char DLT header, e.g. RUPEXI (optional)
    FRONTEND_URL: str = "http://localhost:3000"
    ADMIN_URL: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"
    AI_SERVICE_URL: str = "http://localhost:8001"
    # Firebase Admin service-account JSON (full JSON string) — enables FCM push.
    # Get it from Firebase console → Project settings → Service accounts →
    # "Generate new private key". Paste the whole JSON as one env var.
    FIREBASE_SERVICE_ACCOUNT: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
