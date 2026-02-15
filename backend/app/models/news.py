from sqlalchemy import Column, Integer, String, Text, DECIMAL, DateTime, func
from app.database import Base


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(128), unique=True, comment="NewsAPI article ID or URL hash")
    title = Column(String(512), nullable=False)
    source_name = Column(String(128), nullable=False)
    source_url = Column(String(1024))
    author = Column(String(256))
    content = Column(Text, comment="GLM-generated summary for display")
    summary = Column(Text, comment="GLM-generated summary (deprecated, use content)")
    original_content = Column(Text, comment="Original full article text")
    content_status = Column(String(32), default="pending", comment="pending/generating/ready/failed")
    image_url = Column(String(1024))
    published_at = Column(DateTime, nullable=False, index=True)
    api_score = Column(DECIMAL(5, 4), default=None, comment="NewsAPI relevance score")
    glm_score = Column(DECIMAL(5, 4), default=None, comment="GLM importance score (0-1)")
    final_score = Column(DECIMAL(5, 4), default=None, comment="Hybrid importance score")
    category = Column(String(64), default="ai", index=True, comment="News category")
    fetched_at = Column(DateTime, server_default=func.now(), index=True)
    created_at = Column(DateTime, server_default=func.now())

    # GLM retry fields
    glm_retry_count = Column(Integer, default=0, comment="GLM generation retry count")
    glm_last_error = Column(String(512), comment="Last GLM error message")
    glm_next_retry_at = Column(DateTime, comment="Next retry time for GLM generation")

    def calculate_final_score(self):
        """Calculate hybrid score: 30% API + 70% GLM"""
        api = float(self.api_score) if self.api_score else 0
        glm = float(self.glm_score) if self.glm_score else 0
        self.final_score = api * 0.3 + glm * 0.7
        return self.final_score
