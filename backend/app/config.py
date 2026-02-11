import os
from typing import List
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "mysql+pymysql://user:password@localhost:3306/ainews"

    # Zhipu GLM API
    GLM_API_KEY: str = ""
    GLM_API_URL: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    GLM_TTS_URL: str = "https://open.bigmodel.cn/api/paas/v4/audio/speech"
    GLM_MODEL: str = "glm-4"

    # NewsAPI
    NEWS_API_KEY: str = ""
    NEWS_API_URL: str = "https://newsapi.org/v2"

    # WeChat Mini Program
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""

    # JWT
    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080  # 7 days

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # Storage
    AUDIO_STORAGE_PATH: str = "storage/audio"

    # Timezone
    TIMEZONE: str = "Asia/Shanghai"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
