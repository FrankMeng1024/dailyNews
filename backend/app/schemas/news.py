from pydantic import BaseModel, field_serializer
from typing import Optional, List
from datetime import datetime, timedelta
from decimal import Decimal


def to_beijing_time(dt: datetime) -> str:
    """Convert UTC datetime to Beijing time string (HH:MM:SS)"""
    if dt is None:
        return ""
    # Add 8 hours for Beijing timezone
    beijing_dt = dt + timedelta(hours=8)
    return beijing_dt.strftime("%H:%M:%S")


def to_beijing_datetime(dt: datetime) -> str:
    """Convert UTC datetime to Beijing datetime string"""
    if dt is None:
        return ""
    beijing_dt = dt + timedelta(hours=8)
    return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")


class NewsBase(BaseModel):
    title: str
    source_name: str
    source_url: Optional[str] = None
    author: Optional[str] = None
    content: Optional[str] = None
    image_url: Optional[str] = None
    published_at: datetime


class NewsCreate(NewsBase):
    external_id: str
    api_score: Optional[Decimal] = None


class NewsResponse(BaseModel):
    id: int
    title: str
    source_name: str
    source_url: Optional[str] = None
    author: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    image_url: Optional[str] = None
    published_at: datetime
    published_at_beijing: Optional[str] = None  # Beijing time HH:MM:SS
    final_score: Optional[float] = None
    category: str
    created_at: datetime

    @field_serializer('published_at')
    def serialize_published_at(self, v: datetime) -> str:
        if v:
            beijing_dt = v + timedelta(hours=8)
            return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")
        return ""

    @field_serializer('created_at')
    def serialize_created_at(self, v: datetime) -> str:
        if v:
            beijing_dt = v + timedelta(hours=8)
            return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")
        return ""

    class Config:
        from_attributes = True


class NewsListResponse(BaseModel):
    items: List[NewsResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class NewsFetchResponse(BaseModel):
    fetched_count: int
    message: str
