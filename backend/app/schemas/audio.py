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
    title: Optional[str] = None  # User custom title, optional
    language: AudioLanguage = AudioLanguage.zh
    voice_female: Optional[str] = None  # Female voice ID, e.g. zh-CN-XiaoxiaoNeural
    voice_male: Optional[str] = None  # Male voice ID, e.g. zh-CN-YunxiNeural
    host_female_name: Optional[str] = None  # Custom female host name, default "小雅"
    host_male_name: Optional[str] = None  # Custom male host name, default "小明"
    speed: float = 1.15  # Speech speed (0.5-2.0), default slightly faster


class VoiceOption(BaseModel):
    id: str
    name: str
    desc: str


class VoiceListResponse(BaseModel):
    female: List[VoiceOption]
    male: List[VoiceOption]


class AudioResponse(BaseModel):
    id: int
    title: str
    file_path: Optional[str] = None
    file_size: int = 0
    duration: int = 0
    language: str
    status: str
    error_message: Optional[str] = None
    is_favorite: bool = False
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


class TranscriptItem(BaseModel):
    speaker: str
    text: str
    start: float
    end: float


class TranscriptResponse(BaseModel):
    audio_id: int
    transcript: List[TranscriptItem]


# Import here to avoid circular import
from app.schemas.news import NewsResponse
AudioDetailResponse.model_rebuild()
