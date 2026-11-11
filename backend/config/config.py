import os
from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")

env = {
    "APP_ENV": os.getenv("APP_ENV", "development").strip().lower(),
    "DATABASE_URL": os.getenv("DATABASE_URL", "postgresql+psycopg://liven:liven@localhost:5432/liven"),
    "CORS_ORIGINS": [origin.strip().rstrip("/") for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()],
    "ALLOWED_HOSTS": [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()],
    "JWT_SECRET": os.getenv("JWT_SECRET", "dev-only-change-this-secret-please-change-1234567890"),
    "ACCESS_TOKEN_MINUTES": int(os.getenv("ACCESS_TOKEN_MINUTES", "15")),
    "REFRESH_TOKEN_DAYS": int(os.getenv("REFRESH_TOKEN_DAYS", "30")),
    "OTP_EXPIRY_MINUTES": int(os.getenv("OTP_EXPIRY_MINUTES", "5")),
    "OTP_MAX_ATTEMPTS": int(os.getenv("OTP_MAX_ATTEMPTS", "5")),
    "OTP_RESEND_SECONDS": int(os.getenv("OTP_RESEND_SECONDS", "60")),
    "OTP_RATE_LIMIT": int(os.getenv("OTP_RATE_LIMIT", "3")),
    "OTP_RATE_WINDOW_SECONDS": int(os.getenv("OTP_RATE_WINDOW_SECONDS", "900")),
    "MOCK_OTP": os.getenv("MOCK_OTP", "true").lower() == "true",
    "LEGACY_OTP_LOGIN_ENABLED": os.getenv("LEGACY_OTP_LOGIN_ENABLED", "false").lower() == "true",
    "LOGIN_RATE_LIMIT": int(os.getenv("LOGIN_RATE_LIMIT", "5")),
    "LOGIN_IP_RATE_LIMIT": int(os.getenv("LOGIN_IP_RATE_LIMIT", "20")),
    "LOGIN_RATE_WINDOW_SECONDS": int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "900")),
    "OTP_EMAIL_PROVIDER": os.getenv("OTP_EMAIL_PROVIDER", "development").strip().lower(),
    "RESEND_API_KEY": os.getenv("RESEND_API_KEY", ""),
    "OTP_EMAIL_FROM": os.getenv("OTP_EMAIL_FROM", ""),
    "OTP_EMAIL_TIMEOUT_SECONDS": float(os.getenv("OTP_EMAIL_TIMEOUT_SECONDS", "5")),
    "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
    "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
    "SMTP_USERNAME": os.getenv("SMTP_USERNAME", "").strip(),
    "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", ""),
    "SMTP_FROM": os.getenv("SMTP_FROM", "").strip(),
    "DETECTOR_BACKEND": os.getenv("DETECTOR_BACKEND", "opencv"),
    "DEEPFACE_MODEL": os.getenv("DEEPFACE_MODEL", "VGG-Face"),
    "QR_CODE_EXPIRY_MINUTES": int(os.getenv("QR_CODE_EXPIRY_MINUTES", "60")),
}

for key in ("ACCESS_TOKEN_MINUTES", "REFRESH_TOKEN_DAYS", "OTP_EXPIRY_MINUTES", "OTP_MAX_ATTEMPTS", "OTP_RATE_LIMIT", "OTP_RATE_WINDOW_SECONDS", "LOGIN_RATE_LIMIT", "LOGIN_IP_RATE_LIMIT", "LOGIN_RATE_WINDOW_SECONDS"):
    if env[key] <= 0:
        raise ValueError(f"{key} deve ser positivo.")
if env["OTP_RESEND_SECONDS"] < 0:
    raise ValueError("OTP_RESEND_SECONDS não pode ser negativo.")

if env["OTP_EMAIL_TIMEOUT_SECONDS"] <= 0 or env["OTP_EMAIL_TIMEOUT_SECONDS"] > 30:
    raise ValueError("OTP_EMAIL_TIMEOUT_SECONDS deve estar entre 0 e 30 segundos.")
