import os
from dotenv import load_dotenv

load_dotenv()

env = {
    "DATABASE_URL": os.getenv("DATABASE_URL", "postgresql+psycopg://liven:liven@localhost:5432/liven"),
    "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    "DETECTOR_BACKEND": os.getenv("DETECTOR_BACKEND", "opencv"),
    "DEEPFACE_MODEL": os.getenv("DEEPFACE_MODEL", "VGG-Face"),
    "QR_CODE_EXPIRY_MINUTES": int(os.getenv("QR_CODE_EXPIRY_MINUTES", "60")),
}
