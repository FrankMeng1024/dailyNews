from sqlalchemy import Column, Integer, String, Text, Enum, DateTime, ForeignKey, Boolean, func, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class AudioRecording(Base):
    __tablename__ = "audio_recordings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False, comment="Auto-generated or user-defined title")
    file_path = Column(String(512), nullable=False, comment="Relative path to audio file")
    file_size = Column(Integer, default=0, comment="File size in bytes")
    duration = Column(Integer, default=0, comment="Duration in seconds")
    language = Column(Enum("zh", "en", "bilingual"), nullable=False, default="zh")
    status = Column(Enum("pending", "processing", "completed", "failed"), default="pending", index=True)
    error_message = Column(Text, default=None)
    transcript = Column(JSON, default=None, comment="Dialogue transcript [{speaker, text, start, end}, ...]")
    is_favorite = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="audio_recordings")
    news_items = relationship("AudioNews", back_populates="audio", cascade="all, delete-orphan")


class AudioNews(Base):
    __tablename__ = "audio_news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audio_id = Column(Integer, ForeignKey("audio_recordings.id", ondelete="CASCADE"), nullable=False, index=True)
    news_id = Column(Integer, ForeignKey("news.id", ondelete="CASCADE"), nullable=False, index=True)
    display_order = Column(Integer, nullable=False, default=0, comment="Order of news in audio")

    audio = relationship("AudioRecording", back_populates="news_items")
    news = relationship("News")
