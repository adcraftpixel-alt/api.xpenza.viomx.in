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
    # Comma-separated pool of Groq keys for OCR vision — see .env comment.
    # Falls back to GROQ_API_KEY when unset.
    GROQ_API_KEYS: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Razorpay credentials live only on the Control Hub — it creates/cancels
    # subscriptions and verifies webhook signatures on Rupexi's behalf (see
    # app/services/control_hub.py). Rupexi holds none itself.
    # Trial length in days before the first ₹199 auto-debit
    TRIAL_DAYS: int = 30
    # Machine-to-machine key the VIOMX Control Hub uses to HMAC-sign requests
    # to Rupexi (see app/core/signing.py) — never sent as a bearer header.
    SERVICE_API_KEY: str = ""
    # VIOMX Control Hub — Rupexi pulls plans/caps and reports purchases here.
    # CONTROL_HUB_KEY signs outbound requests (must equal RUPEXI_INGEST_KEY on
    # the Hub); PRODUCT_CODE identifies which product's key the Hub verifies
    # against (X-Product-Code header).
    CONTROL_HUB_URL: str = ""          # e.g. https://api-controlhub.viomx.in/api/v1
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
    # WhatsApp Business Cloud API (Meta Graph API) — login/register OTP delivery
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""    # e.g. 1267262489806885
    WHATSAPP_TEMPLATE_NAME: str = "rupexi_otp"
    WHATSAPP_TEMPLATE_LANG: str = "en"
    WHATSAPP_API_VERSION: str = "v25.0"
    FRONTEND_URL: str = "http://localhost:3000"
    ADMIN_URL: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"
    # CAPTCHA on repeated failed logins — disabled (no-op) until CAPTCHA_PROVIDER
    # is set. Set to "turnstile" (Cloudflare) or "hcaptcha" once you have a
    # site/secret key pair; the frontend also needs the matching widget.
    CAPTCHA_PROVIDER: str = ""
    CAPTCHA_SECRET_KEY: str = ""
    CAPTCHA_FAIL_THRESHOLD: int = 8
    # App Store / Play Store reviewer bypass — this single number skips the
    # real WhatsApp send and always uses REVIEWER_BYPASS_OTP, so reviewers can
    # log in without receiving a live message. Empty phone = disabled. Every
    # other number is unaffected (real random OTP, real WhatsApp send).
    REVIEWER_BYPASS_PHONE: str = ""
    REVIEWER_BYPASS_OTP: str = "111111"
    # Schema-drift alerts land here (see database.py::check_schema_drift).
    ADMIN_ALERT_EMAIL: str = "superadmin@viomx.io"
    AI_SERVICE_URL: str = "http://localhost:8001"
    # Firebase Admin service-account JSON (full JSON string) — enables FCM push.
    # Get it from Firebase console → Project settings → Service accounts →
    # "Generate new private key". Paste the whole JSON as one env var.
    FIREBASE_SERVICE_ACCOUNT: str = ""
    # Google Cloud Vision service-account JSON (full JSON string) — enables
    # document-text OCR for receipt scanning (app/api/v1/ocr/service.py).
    # Get it from Google Cloud Console → IAM & Admin → Service Accounts →
    # create one with the "Cloud Vision AI Service Agent" role (or just
    # "Editor" for a quick start) → Keys → Add key → JSON. Paste the whole
    # JSON as one env var, same pattern as FIREBASE_SERVICE_ACCOUNT above.
    GOOGLE_CLOUD_CREDENTIALS: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
