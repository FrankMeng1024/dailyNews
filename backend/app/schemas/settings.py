from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class Theme(str, Enum):
    light = "light"
    dark = "dark"
    system = "system"


class AudioLanguage(str, Enum):
    zh = "zh"
    en = "en"
    bilingual = "bilingual"


class SettingsBase(BaseModel):
    fetch_hours: List[str] = Field(default=["8", "12", "18"], description="Hours to auto-fetch (24h format)")
    importance_threshold: float = Field(default=0.5, ge=0, le=1, description="Min importance score (0-1)")
    theme: Theme = Theme.system
    audio_language: AudioLanguage = AudioLanguage.zh


class SettingsUpdate(BaseModel):
    fetch_hours: Optional[List[str]] = None
    importance_threshold: Optional[float] = Field(default=None, ge=0, le=1)
    theme: Optional[Theme] = None
    audio_language: Optional[AudioLanguage] = None


class SettingsResponse(SettingsBase):
    id: int
    user_id: int

    class Config:
        from_attributes = True
