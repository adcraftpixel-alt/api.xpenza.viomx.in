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
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = "aifinanceos-uploads"
    AWS_REGION: str = "ap-south-1"
    SENDGRID_API_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    ADMIN_URL: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"
    AI_SERVICE_URL: str = "http://localhost:8001"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
