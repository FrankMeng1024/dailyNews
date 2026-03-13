"""
News Model - 新闻数据模型

状态机设计：
- processing_status: created → fetching → verifying → translating → refining → complete
- visibility_status: inactive → active / skip / failed
"""

from sqlalchemy import Column, Integer, String, Text, DECIMAL, DateTime, func, JSON
from sqlalchemy.types import TypeDecorator
from datetime import datetime, timezone
from app.database import Base


class TZDateTime(TypeDecorator):
    """Timezone-aware DateTime type"""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not value.tzinfo:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value


class News(Base):
    __tablename__ = "news"

    # ========== 基础字段 ==========
    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(128), unique=True, index=True, comment="URL hash for deduplication")

    # 标题
    title = Column(String(512), nullable=False, comment="Original title")
    title_zh = Column(String(512), comment="Chinese translated title")

    # 来源
    source_name = Column(String(128), nullable=False, comment="Source name")
    source_url = Column(String(1024), comment="Article URL")
    author = Column(String(256), comment="Author name")

    # 内容
    original_content = Column(Text, comment="Original full article text")
    content = Column(Text, comment="Refined content for display")
    summary = Column(Text, comment="Brief summary from RSS/API")
    image_url = Column(String(1024), comment="Featured image URL")

    # 时间
    published_at = Column(TZDateTime, nullable=False, index=True, comment="Published time (UTC)")
    created_at = Column(TZDateTime, server_default=func.now(), comment="Creation time (UTC)")

    # ========== 状态机核心字段 ==========
    processing_status = Column(
        String(32),
        default="created",
        index=True,
        comment="Processing status: created/fetching/verifying/translating/refining/complete"
    )
    visibility_status = Column(
        String(32),
        default="inactive",
        index=True,
        comment="Visibility status: inactive/active/skip/failed"
    )

    # ========== 错误信息（统一） ==========
    last_error = Column(String(512), comment="Last error message")
    error_step = Column(String(32), comment="Step where error occurred")
    retry_count = Column(Integer, default=0, comment="Total retry count")

    # ========== 评分字段 ==========
    quality_score = Column(DECIMAL(5, 4), comment="Comprehensive quality score (0-1)")
    source_authority_score = Column(DECIMAL(5, 4), comment="Source authority score (0-1)")
    content_depth_score = Column(DECIMAL(5, 4), comment="Content depth score (0-1)")
    timeliness_score = Column(DECIMAL(5, 4), comment="Timeliness score (0-1)")

    # ========== 验证字段 ==========
    verification_score = Column(DECIMAL(5, 4), comment="Verification confidence score (0-1)")
    verification_result = Column(JSON, comment="Verification details as JSON")

    # ========== 元数据 ==========
    source_type = Column(
        String(32),
        default="news",
        index=True,
        comment="Content type: news/blog/paper/discussion"
    )
    source_tier = Column(
        Integer,
        default=3,
        index=True,
        comment="Source priority tier (1=highest, 4=lowest)"
    )

    def __repr__(self):
        return f"<News {self.id}: {self.title[:30]}...>"

    def is_ready(self) -> bool:
        """Check if news is ready for display"""
        return self.visibility_status == "active"

    def is_failed(self) -> bool:
        """Check if news processing failed"""
        return self.visibility_status == "failed"

    def can_retry(self) -> bool:
        """Check if news can be retried"""
        return self.visibility_status == "failed" and self.retry_count < 5

    def mark_failed(self, error: str, step: str):
        """Mark news as failed with error info"""
        self.visibility_status = "failed"
        self.last_error = error[:500] if error else None
        self.error_step = step
        self.retry_count = (self.retry_count or 0) + 1

    def clear_error(self):
        """Clear error state for retry"""
        self.visibility_status = "inactive"
        self.last_error = None
        # Keep error_step and retry_count for debugging

    def calculate_quality_score(self) -> float:
        """Calculate comprehensive quality score"""
        scores = {
            'source_authority': float(self.source_authority_score or 0.5),
            'content_depth': float(self.content_depth_score or 0.5),
            'timeliness': float(self.timeliness_score or 0.5),
        }

        weights = {
            'source_authority': 0.50,
            'content_depth': 0.35,
            'timeliness': 0.15,
        }

        final = sum(scores[k] * weights[k] for k in scores)
        self.quality_score = round(final, 4)
        return float(self.quality_score)
