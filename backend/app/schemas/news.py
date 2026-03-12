from pydantic import BaseModel, field_serializer
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


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
    title_zh: Optional[str] = None  # Chinese translated title
    source_name: str
    source_url: Optional[str] = None
    author: Optional[str] = None
    content: Optional[str] = None
    original_content: Optional[str] = None  # Full article text
    content_status: str = "pending"  # pending/generating/ready
    summary: Optional[str] = None
    image_url: Optional[str] = None
    published_at: datetime
    published_at_beijing: Optional[str] = None  # Beijing time HH:MM:SS
    final_score: Optional[float] = None
    category: str
    created_at: datetime

    # New fields for content type and verification
    source_type: str = "news"  # news/blog/paper/discussion/podcast/video
    content_format: str = "text"  # text/audio/video/mixed
    media_duration: Optional[int] = None  # Duration in seconds for audio/video
    is_verified: bool = False  # Whether source is verified
    ai_relevance_score: Optional[float] = None  # AI relevance score (0-1)

    # Processing status fields
    processing_status: str = "fetching"  # fetching/verifying/translating/refining/ready/failed
    verification_status: str = "pending"  # pending/verifying/verified/failed
    verification_score: Optional[float] = None  # Verification confidence score (0-1)

    @field_serializer('published_at')
    def serialize_published_at(self, v: datetime) -> str:
        if v:
            return v.isoformat()
        return ""

    @field_serializer('created_at')
    def serialize_created_at(self, v: datetime) -> str:
        if v:
            return v.isoformat()
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
