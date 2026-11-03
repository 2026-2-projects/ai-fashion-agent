from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.calendar_privacy import CalendarPrivacyMiddleware
from app.core.config import SESSION_COOKIE_SECURE, SESSION_SECRET_KEY

if not SESSION_SECRET_KEY or len(SESSION_SECRET_KEY) < 32:
    raise RuntimeError("SESSION_SECRET_KEY must contain at least 32 characters")

app = FastAPI(
    title="AI Fashion Agent API",
    description="AI 기반 개인 맞춤형 패션 에이전트 Backend API",
    version="0.1.0",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="fashion_session",
    max_age=7200,
    same_site="lax",
    https_only=SESSION_COOKIE_SECURE,
)

app.add_middleware(CalendarPrivacyMiddleware)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {"message": "AI Fashion Agent API"}
