from sqlalchemy import Column, Integer, String, Enum, JSON, DECIMAL, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    fetch_hours = Column(JSON, nullable=False, default=["8", "12", "18"], comment="Hours to auto-fetch (24h format)")
    importance_threshold = Column(DECIMAL(3, 2), default=0.50, comment="Min importance score (0.00-1.00)")
    theme = Column(Enum("light", "dark", "system"), default="system")
    audio_language = Column(Enum("zh", "en", "bilingual"), default="zh")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="settings")
