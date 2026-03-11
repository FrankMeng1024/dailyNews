"""
System configuration model for tracking fetch metadata
"""

from sqlalchemy import Column, String, DateTime, Integer, Text, JSON
from datetime import datetime, timezone
from app.database import Base
from app.models.news import TZDateTime


class SystemConfig(Base):
    """System-wide configuration and metadata"""
    __tablename__ = "system_config"

    key = Column(String(128), primary_key=True, comment="Config key")
    value = Column(Text, comment="Config value (JSON or string)")
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


class FetchHistory(Base):
    """History of fetch operations"""
    __tablename__ = "fetch_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fetch_type = Column(String(32), index=True, comment="Type: rss/newsapi/manual")
    source_name = Column(String(128), index=True, comment="Source identifier")
    started_at = Column(TZDateTime, nullable=False, comment="Fetch start time")
    completed_at = Column(TZDateTime, comment="Fetch completion time")
    status = Column(String(32), default="running", comment="running/completed/failed")
    articles_found = Column(Integer, default=0, comment="Articles found")
    articles_new = Column(Integer, default=0, comment="New articles added")
    articles_filtered = Column(Integer, default=0, comment="Articles filtered by quality")
    error_message = Column(Text, comment="Error message if failed")
    fetch_metadata = Column(JSON, comment="Additional metadata")

    def mark_completed(self, articles_found: int, articles_new: int, articles_filtered: int = 0):
        """Mark fetch as completed"""
        self.completed_at = datetime.now(timezone.utc)
        self.status = "completed"
        self.articles_found = articles_found
        self.articles_new = articles_new
        self.articles_filtered = articles_filtered

    def mark_failed(self, error: str):
        """Mark fetch as failed"""
        self.completed_at = datetime.now(timezone.utc)
        self.status = "failed"
        self.error_message = error
