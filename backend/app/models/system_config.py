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
    task_id = Column(String(64), unique=True, index=True, comment="UUID for this fetch task")

    # 统计
    found_count = Column(Integer, default=0, comment="Articles found (created news)")
    new_count = Column(Integer, default=0, comment="New articles (became active)")
    skip_count = Column(Integer, default=0, comment="Skipped articles (became skip)")
    failed_count = Column(Integer, default=0, comment="Failed articles (became failed)")

    # 状态
    status = Column(String(32), default="running", index=True, comment="running/completed/failed")
    error_message = Column(Text, comment="Error message if failed")

    # 时间
    started_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(TZDateTime, comment="Fetch completion time")

    def mark_completed(self, found: int = 0, new: int = 0, skip: int = 0, failed: int = 0):
        """Mark fetch as completed"""
        self.completed_at = datetime.now(timezone.utc)
        self.status = "completed"
        self.found_count = found
        self.new_count = new
        self.skip_count = skip
        self.failed_count = failed

    def mark_failed(self, error: str):
        """Mark fetch as failed"""
        self.completed_at = datetime.now(timezone.utc)
        self.status = "failed"
        self.error_message = error[:500] if error else None
