from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import SESSION_COOKIE_SECURE, SESSION_SECRET_KEY
from app.services.feedback import InteractionError

if not SESSION_SECRET_KEY or len(SESSION_SECRET_KEY) < 32:
    raise RuntimeError("SESSION_SECRET_KEY 환경변수를 설정해야 합니다.")

app = FastAPI(
    title="AI Fashion Agent API",
    description="AI 기반 개인 맞춤형 패션 에이전트 Backend API",
    version="0.1.0",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="fashion_session",
    max_age=60 * 60 * 2,
    same_site="lax",
    https_only=SESSION_COOKIE_SECURE,
)

app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(InteractionError)
async def interaction_error(request: Request, exc: InteractionError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": str(exc)}},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {"message": "AI Fashion Agent API"}
