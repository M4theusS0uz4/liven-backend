import os
from dotenv import load_dotenv

load_dotenv()

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
    "OTP_RATE_LIMIT": int(os.getenv("OTP_RATE_LIMIT", "3")),
    "OTP_RATE_WINDOW_SECONDS": int(os.getenv("OTP_RATE_WINDOW_SECONDS", "900")),
    "MOCK_OTP": os.getenv("MOCK_OTP", "true").lower() == "true",
    "DETECTOR_BACKEND": os.getenv("DETECTOR_BACKEND", "opencv"),
    "DEEPFACE_MODEL": os.getenv("DEEPFACE_MODEL", "VGG-Face"),
    "QR_CODE_EXPIRY_MINUTES": int(os.getenv("QR_CODE_EXPIRY_MINUTES", "60")),
}
