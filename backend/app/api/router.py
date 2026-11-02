from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.settings import router as settings_router
from app.api.v1.wardrobe import router as wardrobe_router
from app.api.v1.weather import router as weather_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(settings_router)
api_router.include_router(wardrobe_router)
api_router.include_router(weather_router)
