from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(
    title="AI Fashion Agent API",
    description="AI 기반 개인 맞춤형 패션 에이전트 Backend API",
    version="0.1.0",
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {"message": "AI Fashion Agent API"}

