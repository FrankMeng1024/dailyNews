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
    summary: Optional[str] = None
    image_url: Optional[str] = None
    published_at: datetime
    published_at_beijing: Optional[str] = None  # Beijing time HH:MM:SS
    created_at: datetime

    # 来源类型
    source_type: str = "news"  # news/blog/paper/discussion

    # 状态机字段
    processing_status: str = "created"  # created/fetching/verifying/translating/refining/complete
    visibility_status: str = "inactive"  # inactive/active/skip/failed

    # 评分
    quality_score: Optional[float] = None
    verification_score: Optional[float] = None

    # 错误信息
    last_error: Optional[str] = None
    error_step: Optional[str] = None
    retry_count: int = 0

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
