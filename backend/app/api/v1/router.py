from fastapi import APIRouter
from app.api.v1 import auth, news, audio, settings, admin, admin_v2

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(news.router)
api_router.include_router(audio.router)
api_router.include_router(settings.router)
api_router.include_router(admin.router)
api_router.include_router(admin_v2.router)
