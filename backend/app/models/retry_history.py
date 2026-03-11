"""
Retry History Model - 记录内容重试历史
"""

from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime, timezone
from app.database import Base


class RetryHistory(Base):
    """内容重试历史记录"""
    __tablename__ = "retry_history"

    id = Column(Integer, primary_key=True, index=True)
    trigger_type = Column(String(50))  # 'auto' or 'manual'
    processed_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
