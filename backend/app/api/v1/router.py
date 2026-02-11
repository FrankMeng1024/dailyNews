from fastapi import APIRouter
from app.api.v1 import auth, news, audio, settings

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(news.router)
api_router.include_router(audio.router)
api_router.include_router(settings.router)
