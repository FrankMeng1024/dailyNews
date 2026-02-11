from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class AudioLanguage(str, Enum):
    zh = "zh"
    en = "en"
    bilingual = "bilingual"


class AudioStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AudioCreate(BaseModel):
    news_ids: List[int]
    language: AudioLanguage = AudioLanguage.zh


class AudioResponse(BaseModel):
    id: int
    title: str
    file_path: Optional[str] = None
    file_size: int = 0
    duration: int = 0
    language: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AudioDetailResponse(AudioResponse):
    news: List["NewsResponse"] = []

    class Config:
        from_attributes = True


class AudioListResponse(BaseModel):
    items: List[AudioResponse]
    total: int
    page: int
    limit: int


class AudioStatusResponse(BaseModel):
    status: str
    progress: Optional[int] = None
    message: Optional[str] = None


# Import here to avoid circular import
from app.schemas.news import NewsResponse
AudioDetailResponse.model_rebuild()
