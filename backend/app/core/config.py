import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg:///ai_fashion_agent",
)
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KMA_SERVICE_KEY = os.getenv("KMA_SERVICE_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/api/v1/calendar/oauth/callback",
)
GOOGLE_TOKEN_ENCRYPTION_KEY = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
