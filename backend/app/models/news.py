from sqlalchemy import Column, Integer, String, Text, DECIMAL, DateTime, Boolean, func, JSON
from sqlalchemy.types import TypeDecorator
from datetime import datetime, timezone
from typing import Optional
from app.database import Base


class TZDateTime(TypeDecorator):
    """Timezone-aware DateTime type"""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not value.tzinfo:
                # Assume UTC if no timezone info
                value = value.replace(tzinfo=timezone.utc)
            # Store as UTC
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            # Return as UTC timezone-aware
            return value.replace(tzinfo=timezone.utc)
        return value


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(128), unique=True, comment="NewsAPI article ID or URL hash")
    title = Column(String(512), nullable=False)
    title_zh = Column(String(512), comment="Chinese translated title")
    source_name = Column(String(128), nullable=False)
    source_url = Column(String(1024))
    author = Column(String(256))
    content = Column(Text, comment="GLM-generated summary for display")
    summary = Column(Text, comment="GLM-generated summary (deprecated, use content)")
    original_content = Column(Text, comment="Original full article text")
    content_status = Column(String(32), default="pending", comment="pending/generating/ready/failed")
    image_url = Column(String(1024))
    published_at = Column(TZDateTime, nullable=False, index=True, comment="Published time (UTC)")
    api_score = Column(DECIMAL(5, 4), default=None, comment="NewsAPI relevance score")
    glm_score = Column(DECIMAL(5, 4), default=None, comment="GLM importance score (0-1)")
    final_score = Column(DECIMAL(5, 4), default=None, comment="Comprehensive quality score (0-1)")
    category = Column(String(64), default="ai", index=True, comment="News category")
    fetched_at = Column(TZDateTime, server_default=func.now(), index=True, comment="Fetch time (UTC)")
    created_at = Column(TZDateTime, server_default=func.now(), comment="Creation time (UTC)")

    # Content type and format
    source_type = Column(String(32), default="news", index=True,
                        comment="Content type: news/blog/paper/discussion/podcast/video")
    content_format = Column(String(32), default="text",
                           comment="Format: text/audio/video/mixed")
    media_duration = Column(Integer, comment="Media duration in seconds (for audio/video)")

    # Content verification
    is_verified = Column(Boolean, default=False,
                        comment="Whether content source is verified and trustworthy")
    ai_relevance_score = Column(DECIMAL(5, 4),
                               comment="AI relevance score (0-1) from GLM verification")

    # GLM retry fields
    glm_retry_count = Column(Integer, default=0, comment="GLM generation retry count")
    glm_last_error = Column(String(512), comment="Last GLM error message")
    glm_next_retry_at = Column(TZDateTime, comment="Next retry time for GLM generation")

    # Scraping retry fields
    scraping_retry_count = Column(Integer, default=0, comment="Content scraping retry count")
    scraping_last_error = Column(String(512), comment="Last scraping error message")
    scraping_next_retry_at = Column(TZDateTime, comment="Next retry time for content scraping")

    # Title translation status fields
    title_status = Column(String(32), default="pending", comment="Title translation status: pending/ready/failed")
    title_retry_count = Column(Integer, default=0, comment="Title translation retry count")
    title_last_error = Column(String(512), comment="Last title translation error message")
    title_next_retry_at = Column(TZDateTime, comment="Next retry time for title translation")

    # Quality scoring fields (new)
    source_authority_score = Column(DECIMAL(5, 4), comment="Source authority score (0-1)")
    content_depth_score = Column(DECIMAL(5, 4), comment="Content depth score (0-1)")
    timeliness_score = Column(DECIMAL(5, 4), comment="Timeliness score (0-1)")
    technical_credibility_score = Column(DECIMAL(5, 4), comment="Technical credibility score (0-1)")
    quality_breakdown = Column(JSON, comment="Quality score breakdown details")
    entity_count = Column(Integer, default=0, comment="Technical entity count")
    content_length = Column(Integer, default=0, comment="Content character count")

    # Source priority tier
    source_tier = Column(Integer, default=3, index=True, comment="Source priority tier (1=highest, 4=lowest)")

    def calculate_final_score(self):
        """
        Calculate comprehensive quality score using multi-dimensional scoring

        Weights:
        - Source Authority: 40%
        - Content Depth: 25%
        - Timeliness: 15%
        - AI Relevance: 10%
        - Technical Credibility: 10%
        """
        scores = {
            'source_authority': float(self.source_authority_score or 0.5),
            'content_depth': float(self.content_depth_score or 0.5),
            'timeliness': float(self.timeliness_score or 0.5),
            'ai_relevance': float(self.ai_relevance_score or 0.5),
            'technical_credibility': float(self.technical_credibility_score or 0.5)
        }

        weights = {
            'source_authority': 0.40,
            'content_depth': 0.25,
            'timeliness': 0.15,
            'ai_relevance': 0.10,
            'technical_credibility': 0.10
        }

        final = sum(scores[k] * weights[k] for k in scores)
        self.final_score = round(final, 4)

        # Store breakdown
        self.quality_breakdown = {
            'scores': scores,
            'weights': weights,
            'final': float(self.final_score)
        }

        return self.final_score

    def get_failure_type(self) -> Optional[str]:
        """
        Determine the type of failure for this news item

        Returns:
            "scraping_failed" - Failed to fetch original content (content < 200 chars)
            "glm_failed" - Failed to generate GLM content (content_status != ready)
            None - No failure (both succeeded)
        """
        # Check scraping status (original content must be >= 200 chars)
        has_sufficient_content = self.original_content and len(self.original_content) >= 200

        # Check GLM status (content must be ready)
        glm_ready = self.content_status == "ready"

        # Priority: scraping failure is more critical (can't generate GLM without content)
        if not has_sufficient_content:
            return "scraping_failed"
        elif not glm_ready:
            return "glm_failed"

        return None

    def get_retry_info(self) -> dict:
        """
        Get retry information including countdown timers

        Returns:
            Dict with scraping and GLM retry details
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        # Scraping retry info
        scraping_info = {
            "status": "success" if (self.original_content and len(self.original_content) >= 200) else "failed",
            "retry_count": self.scraping_retry_count or 0,
            "last_error": self.scraping_last_error,
            "next_retry_at": self.scraping_next_retry_at.isoformat() if self.scraping_next_retry_at else None,
            "seconds_until_retry": None
        }

        if self.scraping_next_retry_at:
            delta = (self.scraping_next_retry_at - now).total_seconds()
            scraping_info["seconds_until_retry"] = max(0, int(delta))

        # GLM retry info
        glm_info = {
            "status": self.content_status or "pending",
            "retry_count": self.glm_retry_count or 0,
            "last_error": self.glm_last_error,
            "next_retry_at": self.glm_next_retry_at.isoformat() if self.glm_next_retry_at else None,
            "seconds_until_retry": None
        }

        if self.glm_next_retry_at:
            delta = (self.glm_next_retry_at - now).total_seconds()
            glm_info["seconds_until_retry"] = max(0, int(delta))

        return {
            "scraping": scraping_info,
            "glm": glm_info
        }

    def is_fully_recovered(self) -> bool:
        """
        Check if both scraping AND GLM have succeeded

        Returns:
            True if both phases succeeded, False otherwise
        """
        has_content = self.original_content and len(self.original_content) >= 200
        glm_ready = self.content_status == "ready"

        return has_content and glm_ready

    def get_detailed_error_info(self) -> dict:
        """获取详细错误信息（用于开发者界面）

        Returns:
            包含所有失败类型详细信息的字典
        """
        from app.services.config_service import DEFAULT_CONFIG
        max_retries = DEFAULT_CONFIG["max_retries"]

        return {
            "id": self.id,
            "title": self.title[:100] if self.title else "",
            "title_zh": self.title_zh[:100] if self.title_zh else None,
            "source_name": self.source_name,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "failures": {
                "scraping": {
                    "status": "failed" if (self.scraping_retry_count or 0) >= max_retries else (
                        "success" if self.original_content and len(self.original_content) >= 200 else "pending"
                    ),
                    "retry_count": self.scraping_retry_count or 0,
                    "max_retries": max_retries,
                    "last_error": self.scraping_last_error,
                    "next_retry": self.scraping_next_retry_at.isoformat() if self.scraping_next_retry_at else None,
                    "content_length": len(self.original_content) if self.original_content else 0
                },
                "glm": {
                    "status": self.content_status or "pending",
                    "retry_count": self.glm_retry_count or 0,
                    "max_retries": max_retries,
                    "last_error": self.glm_last_error,
                    "next_retry": self.glm_next_retry_at.isoformat() if self.glm_next_retry_at else None,
                    "content_length": len(self.content) if self.content else 0
                },
                "title_translation": {
                    "status": self.title_status or "pending",
                    "retry_count": self.title_retry_count or 0,
                    "max_retries": max_retries,
                    "last_error": self.title_last_error,
                    "next_retry": self.title_next_retry_at.isoformat() if self.title_next_retry_at else None,
                    "has_translation": bool(self.title_zh)
                }
            },
            "can_retry": self._can_retry()
        }

    def _can_retry(self) -> dict:
        """检查哪些操作可以重试

        Returns:
            各操作是否可重试的字典
        """
        from app.services.config_service import DEFAULT_CONFIG
        max_retries = DEFAULT_CONFIG["max_retries"]

        # 爬虫：内容不足且未达到最大重试次数
        can_retry_scraping = (
            (not self.original_content or len(self.original_content) < 200) and
            (self.scraping_retry_count or 0) < max_retries
        )

        # GLM：内容未就绪且未达到最大重试次数
        can_retry_glm = (
            self.content_status != "ready" and
            (self.glm_retry_count or 0) < max_retries
        )

        # 标题翻译：无中文标题且未达到最大重试次数
        can_retry_title = (
            self.title_status != "ready" and
            (self.title_retry_count or 0) < max_retries
        )

        return {
            "scraping": can_retry_scraping,
            "glm": can_retry_glm,
            "title": can_retry_title
        }

    def reset_retry_counts(self, retry_type: str = "all") -> None:
        """重置重试计数

        Args:
            retry_type: 要重置的类型 ("scraping", "glm", "title", "all")
        """
        if retry_type in ("scraping", "all"):
            self.scraping_retry_count = 0
            self.scraping_last_error = None
            self.scraping_next_retry_at = None

        if retry_type in ("glm", "all"):
            self.glm_retry_count = 0
            self.glm_last_error = None
            self.glm_next_retry_at = None
            if self.content_status == "failed":
                self.content_status = "pending"

        if retry_type in ("title", "all"):
            self.title_retry_count = 0
            self.title_last_error = None
            self.title_next_retry_at = None
            if self.title_status == "failed":
                self.title_status = "pending"
